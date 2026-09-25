"""Parsers for the NCES files the school directory is built from.

Every reader returns a polars DataFrame whose columns are all ``String`` and hold
the text exactly as published: no trimming, recoding, type coercion or filling.
An empty field becomes ``null``. Readers check that the columns they promise are
present and that no row was split or merged by a stray quote, and raise
:class:`SourceFormatError` otherwise, so a changed file layout fails loudly.

Files and what is read from them:

* EDGE public school and public LEA geocodes: the pipe-delimited ``.TXT`` inside
  the release zip. The text has no header row, so column names come from the
  first row of the workbook in the same zip.
* EDGE private school geocodes: the workbook (the release has no text file, and
  its ``.dbf`` truncates names to 50 characters).
* CCD school directory (029) and school characteristics (129): the ``.csv``.
* CCD school membership (052): only the one school-total row per school, picked
  out while streaming the 2.3 GB long-format ``.csv``.
* PSS public-use file: the ``.csv``.
"""

import csv
import io
import shutil
import subprocess
import zipfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import polars as pl

from snowlight.sources.nces import xlsx

# Columns each reader guarantees. Extra columns in a file are kept.
EDGE_PUBLIC_SCHOOL_COLUMNS = (
    "NCESSCH",
    "LEAID",
    "NAME",
    "STATE",
    "STFIP",
    "CNTY",
    "NMCNTY",
    "LOCALE",
    "LAT",
    "LON",
    "SCHOOLYEAR",
)
EDGE_LEA_COLUMNS = (
    "LEAID",
    "NAME",
    "CITY",
    "STATE",
    "STFIP",
    "CNTY",
    "NMCNTY",
    "LOCALE",
    "LAT",
    "LON",
    "SCHOOLYEAR",
)
EDGE_PRIVATE_SCHOOL_COLUMNS = (
    "PPIN",
    "NAME",
    "STREET",
    "CITY",
    "STATE",
    "ZIP",
    "STFIP",
    "CNTY",
    "NMCNTY",
    "LOCALE",
    "LAT",
    "LON",
    "SCHOOLYEAR",
)
CCD_DIRECTORY_COLUMNS = (
    "SCHOOL_YEAR",
    "FIPST",
    "ST",
    "SCH_NAME",
    "LEA_NAME",
    "LEAID",
    "NCESSCH",
    "LSTREET1",
    "LCITY",
    "LSTATE",
    "LZIP",
    "PHONE",
    "WEBSITE",
    "UPDATED_STATUS",
    "UPDATED_STATUS_TEXT",
    "SCH_TYPE_TEXT",
    "CHARTER_TEXT",
    "NOGRADES",
    "G_PK_OFFERED",
    "G_KG_OFFERED",
    "G_1_OFFERED",
    "G_2_OFFERED",
    "G_3_OFFERED",
    "G_4_OFFERED",
    "G_5_OFFERED",
    "G_6_OFFERED",
    "G_7_OFFERED",
    "G_8_OFFERED",
    "G_9_OFFERED",
    "G_10_OFFERED",
    "G_11_OFFERED",
    "G_12_OFFERED",
    "G_13_OFFERED",
    "G_UG_OFFERED",
    "G_AE_OFFERED",
    "GSLO",
    "GSHI",
    "LEVEL",
)
CCD_CHARACTERISTICS_COLUMNS = ("NCESSCH", "VIRTUAL", "VIRTUAL_TEXT")
CCD_MEMBERSHIP_COLUMNS = ("NCESSCH", "STUDENT_COUNT", "TOTAL_INDICATOR", "DMS_FLAG")
PSS_COLUMNS = ("PPIN", "PINST", "PPHONE", "LEVEL", "P305", "F_P305")


DEFLATE64 = 9  # zip compression method number


class SourceFormatError(ValueError):
    """A source file does not have the layout its reader expects."""


def read_member(zip_path: Path, member: str) -> bytes:
    """Return the bytes of ``member`` inside the zip at ``zip_path``.

    Raises:
        SourceFormatError: if the file is not a zip or has no such member.
    """
    try:
        with zipfile.ZipFile(zip_path) as archive:
            return archive.read(member)
    except zipfile.BadZipFile as error:
        raise SourceFormatError(f"{zip_path.name} is not a zip file") from error
    except KeyError as error:
        raise SourceFormatError(f"{zip_path.name} has no member {member!r}") from error


@contextmanager
def open_member_stream(zip_path: Path, member: str) -> Iterator[IO[bytes]]:
    """Open ``member`` of the zip at ``zip_path`` as a binary stream.

    Python's :mod:`zipfile` cannot inflate Deflate64 (method 9), which NCES uses
    for members over 2 GB such as the CCD membership file. Those are streamed
    through Info-ZIP ``unzip -p`` instead, which also verifies the member's CRC;
    a non-zero exit raises :class:`SourceFormatError` once the stream is closed.
    """
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as error:
        raise SourceFormatError(f"{zip_path.name} is not a zip file") from error
    with archive:
        try:
            info = archive.getinfo(member)
        except KeyError as error:
            raise SourceFormatError(f"{zip_path.name} has no member {member!r}") from error
        if info.compress_type != DEFLATE64:
            with archive.open(info) as handle:
                yield handle
            return
    unzip = shutil.which("unzip")
    if unzip is None:
        raise SourceFormatError(f"{zip_path.name}:{member} is Deflate64; install Info-ZIP unzip")
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [unzip, "-p", str(zip_path), member],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None  # noqa: S101 - guaranteed by stdout=PIPE
    try:
        yield process.stdout
        process.stdout.read()  # drain so unzip can finish its CRC check
    finally:
        process.stdout.close()
        _, stderr = process.communicate()
    if process.returncode != 0:
        detail = stderr.decode("utf-8", "replace").strip()
        raise SourceFormatError(f"unzip failed on {zip_path.name}:{member}: {detail}")


def _decode(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceFormatError(f"{what} is not UTF-8: {error}") from error


def _require(frame: pl.DataFrame, columns: Sequence[str], what: str) -> pl.DataFrame:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise SourceFormatError(f"{what} lacks columns {missing}")
    return frame


def _record_count(text: str, what: str, *, delimiter: str, width: int | None = None) -> int:
    """Count non-blank records with the stdlib CSV parser, which honours quoted newlines.

    Raises:
        SourceFormatError: if ``width`` is given and a record has another field count.
    """
    count = 0
    for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
        if not row:
            continue
        count += 1
        if width is not None and len(row) != width:
            raise SourceFormatError(f"{what}: record {count} has {len(row)} fields, not {width}")
    return count


def grep_lines(stream: IO[bytes], needle: bytes, chunk_size: int = 1 << 24) -> list[bytes]:
    """Return every complete line of ``stream`` that contains ``needle``.

    The stream is read in large chunks and searched with ``bytes.find``, which is
    far faster than splitting a multi-gigabyte file into lines. Each returned line
    ends with ``b"\\n"`` (one is added to an unterminated last line).
    """
    kept: list[bytes] = []
    tail = b""
    while chunk := stream.read(chunk_size):
        buffer = tail + chunk
        cut = buffer.rfind(b"\n") + 1
        block, tail = buffer[:cut], buffer[cut:]
        position = block.find(needle)
        while position != -1:
            start = block.rfind(b"\n", 0, position) + 1
            end = block.find(b"\n", position) + 1
            kept.append(block[start:end])
            position = block.find(needle, end)
    if needle in tail:
        kept.append(tail + b"\n")
    return kept


def _read_delimited(
    data: bytes,
    what: str,
    *,
    delimiter: str = ",",
    header: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Parse delimited text into all-``String`` columns and verify the row count."""
    text = _decode(data, what)
    width = len(header) if header is not None else None
    expected = _record_count(text, what, delimiter=delimiter, width=width)
    expected -= 0 if header is not None else 1
    frame = pl.read_csv(
        io.BytesIO(data),
        separator=delimiter,
        has_header=header is None,
        new_columns=list(header) if header is not None else None,
        infer_schema=False,
        quote_char='"',
        raise_if_empty=True,
    )
    if frame.height != expected:
        raise SourceFormatError(f"{what}: parsed {frame.height} rows, file holds {expected}")
    return frame


def _strip_cr(frame: pl.DataFrame) -> pl.DataFrame:
    """Drop the carriage return a CRLF file leaves on its last field, if any."""
    last = frame.columns[-1]
    return frame.with_columns(pl.col(last).str.strip_suffix("\r"))


def read_edge_pipe_table(
    zip_path: Path, txt_member: str, xlsx_member: str, columns: Sequence[str]
) -> pl.DataFrame:
    """Read an EDGE pipe-delimited table, naming its columns from the sibling workbook."""
    header = xlsx.read_header(read_member(zip_path, xlsx_member))
    what = f"{zip_path.name}:{txt_member}"
    frame = _read_delimited(read_member(zip_path, txt_member), what, delimiter="|", header=header)
    return _require(_strip_cr(frame), columns, what)


def read_edge_public_schools(zip_path: Path, txt_member: str, xlsx_member: str) -> pl.DataFrame:
    """Read the EDGE public school geocode table (one row per NCESSCH)."""
    return read_edge_pipe_table(zip_path, txt_member, xlsx_member, EDGE_PUBLIC_SCHOOL_COLUMNS)


def read_edge_leas(zip_path: Path, txt_member: str, xlsx_member: str) -> pl.DataFrame:
    """Read the EDGE public LEA (school district) geocode table (one row per LEAID)."""
    return read_edge_pipe_table(zip_path, txt_member, xlsx_member, EDGE_LEA_COLUMNS)


def read_edge_private_schools(zip_path: Path, xlsx_member: str) -> pl.DataFrame:
    """Read the EDGE private school geocode workbook (one row per PSS PPIN)."""
    what = f"{zip_path.name}:{xlsx_member}"
    rows = iter(xlsx.iter_rows(read_member(zip_path, xlsx_member)))
    try:
        header = [str(value).strip() for value in next(rows)]
    except StopIteration as error:
        raise SourceFormatError(f"{what} is empty") from error
    body: list[list[str | None]] = []
    for row in rows:
        if len(row) > len(header):
            raise SourceFormatError(f"{what}: a row has {len(row)} cells, header {len(header)}")
        body.append(row + [None] * (len(header) - len(row)))
    frame = pl.DataFrame(body, schema=dict.fromkeys(header, pl.String), orient="row", strict=True)
    return _require(frame, EDGE_PRIVATE_SCHOOL_COLUMNS, what)


def read_ccd_csv(zip_path: Path, member: str, columns: Sequence[str]) -> pl.DataFrame:
    """Read a wide-format CCD ``.csv`` file."""
    what = f"{zip_path.name}:{member}"
    return _require(_read_delimited(read_member(zip_path, member), what), columns, what)


def read_ccd_directory(zip_path: Path, member: str) -> pl.DataFrame:
    """Read the CCD public school directory (one row per NCESSCH)."""
    return read_ccd_csv(zip_path, member, CCD_DIRECTORY_COLUMNS)


def read_ccd_characteristics(zip_path: Path, member: str) -> pl.DataFrame:
    """Read the CCD school characteristics file (virtual status and more)."""
    return read_ccd_csv(zip_path, member, CCD_CHARACTERISTICS_COLUMNS)


def read_ccd_membership_totals(zip_path: Path, member: str, total_indicator: str) -> pl.DataFrame:
    """Return the rows of the long-format CCD membership file whose ``TOTAL_INDICATOR``
    equals ``total_indicator`` (one per school), without loading the whole file.

    Lines are pre-selected by a byte search for the indicator text and then parsed
    as CSV, and every selected row is re-checked on the parsed column, so a school
    name that happens to contain the indicator text cannot slip through.
    """
    what = f"{zip_path.name}:{member}"
    needle = total_indicator.encode("utf-8")
    with open_member_stream(zip_path, member) as handle:
        header = handle.readline()
        kept = grep_lines(handle, needle)
    frame = _read_delimited(header + b"".join(kept), what)
    frame = _require(frame, CCD_MEMBERSHIP_COLUMNS, what)
    return frame.filter(pl.col("TOTAL_INDICATOR") == total_indicator)


def read_pss(zip_path: Path, member: str, grade_columns: Sequence[str]) -> pl.DataFrame:
    """Read the PSS public-use data file (one row per PPIN).

    ``grade_columns`` names the release's grade-span columns, which carry the
    survey year (``LOGR2024`` and ``HIGR2024`` for 2023-24).
    """
    what = f"{zip_path.name}:{member}"
    frame = _read_delimited(read_member(zip_path, member), what)
    return _require(frame, (*PSS_COLUMNS, *grade_columns), what)

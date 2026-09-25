"""Decoding and splitting of the Census Bureau's delimited text tables.

Gazetteer files have been tab-delimited in some years and pipe-delimited in
others, with header cells that older releases padded with spaces; relationship
files are pipe-delimited UTF-8 with a byte-order mark. :func:`split_table`
accepts all of these and refuses anything ragged.
"""

import zipfile
from pathlib import Path

from snowlight.sources.census import CensusFormatError


def decode(data: bytes, label: str) -> str:
    """Decode UTF-8 text, dropping a leading byte-order mark.

    Raises:
        CensusFormatError: if the bytes are not valid UTF-8.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CensusFormatError(f"{label}: not UTF-8 ({exc})") from exc
    return text.removeprefix("﻿")


def split_table(text: str, label: str) -> tuple[list[str], list[dict[str, str]]]:
    """Split a delimited table into its header and one mapping per row.

    The delimiter is ``|`` when the header line contains one and a tab
    otherwise. Cells are stripped of surrounding whitespace; blank lines are
    ignored.

    Raises:
        CensusFormatError: if a header name repeats, the table has no header,
            or any row has a different number of cells than the header.
    """
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise CensusFormatError(f"{label}: empty table")
    delimiter = "|" if "|" in lines[0] else "\t"
    header = [cell.strip() for cell in lines[0].split(delimiter)]
    if len(set(header)) != len(header):
        raise CensusFormatError(f"{label}: repeated column names in {header}")
    rows: list[dict[str, str]] = []
    for number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cells = [cell.strip() for cell in line.split(delimiter)]
        if len(cells) != len(header):
            raise CensusFormatError(
                f"{label}: line {number} has {len(cells)} cells, header has {len(header)}"
            )
        rows.append(dict(zip(header, cells, strict=True)))
    return header, rows


def require_columns(header: list[str], required: tuple[str, ...], label: str) -> None:
    """Raise :class:`CensusFormatError` unless every ``required`` column is present."""
    missing = [name for name in required if name not in header]
    if missing:
        raise CensusFormatError(f"{label}: missing columns {missing}")


def read_single_member(path: Path, suffix: str = ".txt") -> tuple[str, bytes]:
    """Return ``(member name, bytes)`` of the one ``suffix`` file inside a zip.

    Raises:
        CensusFormatError: unless the archive holds exactly one such file.
    """
    with zipfile.ZipFile(path) as archive:
        members = [
            info
            for info in archive.infolist()
            if not info.is_dir() and info.filename.lower().endswith(suffix)
        ]
        if len(members) != 1:
            names = [info.filename for info in members]
            raise CensusFormatError(f"{path.name}: expected one {suffix} file, found {names}")
        return members[0].filename, archive.read(members[0])

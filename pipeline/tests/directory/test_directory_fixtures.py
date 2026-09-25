"""Checks that every fixture is a documented, verbatim slice of a real NCES file.

``fixtures/PROVENANCE.json`` names, for each fixture zip, the source URL, the
SHA-256 of the full source zip and the line (or worksheet row) numbers kept.
The first test needs only the repository. The others also need the full source
zip in the local download cache (``pipeline/.cache/nces``, filled by
``snowlight directory build``) with that same checksum; there they prove every
fixture row equals the source row it claims to be. In a clean checkout, such as
CI, they are skipped.
"""

import hashlib
import zipfile
from pathlib import Path
from typing import IO, Any

import pytest

from snowlight.directory.config import load_config
from snowlight.sources.nces import xlsx
from snowlight.sources.nces.fetch import cache_path
from snowlight.sources.nces.readers import open_member_stream, read_member

CACHE = Path(__file__).resolve().parents[2] / ".cache" / "nces"
# Text fixtures: (fixture zip, whether the member starts with a header line).
TEXT_FIXTURES = [
    ("EDGE_GEOCODE_PUBLICSCH_2425.zip", False),
    ("EDGE_GEOCODE_PUBLICLEA_2425.zip", False),
    ("ccd_sch_029_2425_w_1a_073025.zip", True),
    ("ccd_sch_052_2425_l_1a_073025.zip", True),
    ("ccd_sch_129_2425_w_1a_073025.zip", True),
    ("pss2324_pu_csv.zip", True),
]
_CHUNK = 1 << 24


def _files(provenance: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = provenance["files"]
    return files


def _cached_source(entry: dict[str, Any]) -> Path:
    path = cache_path(CACHE, entry["source_url"])
    if not path.is_file():
        pytest.skip(f"full source not cached: {entry['source_url']}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    if digest.hexdigest() != entry["source_sha256"]:
        pytest.skip(f"cached copy is not the pinned file: {entry['source_url']}")
    return path


def _streamed_lines(stream: IO[bytes], wanted: set[int]) -> tuple[bytes, dict[int, bytes]]:
    """Return line 1 and the lines numbered in ``wanted``, splitting on ``\\n`` only.

    The whole stream is read, so that ``unzip`` finishes and checks the CRC.
    """
    found: dict[int, bytes] = {}
    first = b""
    number = 1  # number of the first line in the next block
    tail = b""
    while chunk := stream.read(_CHUNK):
        buffer = tail + chunk
        cut = buffer.rfind(b"\n") + 1
        block, tail = buffer[:cut], buffer[cut:]
        count = block.count(b"\n")
        if number == 1 and count:
            first = block[: block.index(b"\n") + 1]
        if any(number <= line < number + count for line in wanted):
            for offset, line in enumerate(block.split(b"\n")[:-1]):
                if number + offset in wanted:
                    found[number + offset] = line + b"\n"
        number += count
    return first, found


def test_every_fixture_is_documented(fixtures_dir: Path, provenance: dict[str, Any]) -> None:
    files = _files(provenance)
    assert {p.name for p in fixtures_dir.glob("*.zip")} == set(files)
    # The real configuration (the ``fixture_config`` fixture re-pins to the slices).
    pinned = {
        candidate.url: candidate.sha256
        for source in load_config().sources.values()
        for candidate in source.candidates
    }
    for name, entry in files.items():
        assert entry["source_url"].startswith("https://nces.ed.gov/")
        assert entry["source_url"].rsplit("/", 1)[1] == name
        assert pinned[entry["source_url"]] == entry["source_sha256"]
        with zipfile.ZipFile(fixtures_dir / name) as archive:
            assert sorted(archive.namelist()) == entry["members_written"]
        assert set(entry["members_written"]) <= set(entry["source_members"])
        numbers = entry["rows_kept"]["line_or_row_numbers"]
        assert numbers == sorted(set(numbers))


@pytest.mark.parametrize(("name", "has_header"), TEXT_FIXTURES)
def test_text_slices_are_verbatim_lines(
    fixtures_dir: Path, provenance: dict[str, Any], name: str, has_header: bool
) -> None:
    entry = _files(provenance)[name]
    member = entry["rows_kept"]["member"]
    numbers: list[int] = entry["rows_kept"]["line_or_row_numbers"]
    fixture_lines = read_member(fixtures_dir / name, member).splitlines(keepends=True)
    source = _cached_source(entry)
    if name.startswith("ccd_sch_052"):
        # The 2.3 GB member is Deflate64: stream it, numbering lines as the
        # fixture maker does for this file (split on "\n" only).
        with open_member_stream(source, member) as handle:
            header, found = _streamed_lines(handle, set(numbers))
        source_header = [header]
    else:
        lines = read_member(source, member).splitlines(keepends=True)
        found = {number: lines[number - 1] for number in numbers}
        source_header = lines[:1] if has_header else []
    expected = source_header + [found[number] for number in numbers]
    assert fixture_lines == expected
    for header_member in set(entry["members_written"]) - {member}:
        assert xlsx.read_header(read_member(fixtures_dir / name, header_member)) == (
            xlsx.read_header(read_member(source, header_member))
        )


def test_private_workbook_rows_are_verbatim(fixtures_dir: Path, provenance: dict[str, Any]) -> None:
    name = "EDGE_GEOCODE_PRIVATESCH_2324.zip"
    entry = _files(provenance)[name]
    member = entry["rows_kept"]["member"]
    fixture_rows = list(xlsx.iter_rows(read_member(fixtures_dir / name, member)))
    source_rows = list(xlsx.iter_rows(read_member(_cached_source(entry), member)))
    assert fixture_rows[0] == source_rows[0]
    by_ppin = {row[0]: row for row in source_rows[1:]}
    assert len(by_ppin) == len(source_rows) - 1
    assert len(fixture_rows) - 1 == len(entry["rows_kept"]["line_or_row_numbers"])
    for row in fixture_rows[1:]:
        assert row == by_ppin[row[0]]

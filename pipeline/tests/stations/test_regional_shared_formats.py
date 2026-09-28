"""The shared list-file formats, read against part 1's committed real fixtures.

Sinclair's and Allen's framed files, RIBA's list and WRCB's file are NewsTicker HTML
exports; WJAC's, WSBT's, WTOV's, WCYB's, KRCG's and NJ 101.5's are "Closings Last
Updated at" grids; KOAM's and KXLY's BLOX files are SC and NewsTicker XML; WKTV's is a CGS "All
Active" page and every Allen page reads an amb-feeds counter. The same
generators wrote the files Gray pages framed years ago, and part 1 keeps real
archived and live copies of them (fixtures/PROVENANCE.json), many populated. This
part's parsers must read every one of them to the same names, in the same order.
"""

import json
from pathlib import Path

import pytest

from snowlight.sources.stations import allen, blox, newsticker
from snowlight.sources.stations.model import Listing, ListingState

FOLDER = Path(__file__).parent / "fixtures"
PARSERS = {
    "gray-file-newsticker": (newsticker.parse, "newsticker-html"),
    "gray-file-grid": (newsticker.parse, "closings-grid"),
    "gray-file-sc-xml": (blox.parse, "blox-sc-xml"),
    "gray-file-newsticker-xml": (blox.parse, "blox-newsticker-xml"),
    "gray-file-cgs": (allen.parse, "cgs-all-active"),
    "gray-file-count-json": (allen.parse, "allen-counter"),
}
ENTRIES = [
    entry
    for entry in json.loads((FOLDER / "PROVENANCE.json").read_text(encoding="utf-8"))
    if entry["expected"]["variant"] in PARSERS
]


def test_the_shared_formats_include_large_populated_files() -> None:
    rows = {entry["file"]: entry["expected"]["rows"] for entry in ENTRIES}
    assert rows["gray/wfsb-file-20260223192016.html"] == 931
    assert rows["gray/wjrt-file-20220203035319.html"] == 216
    assert rows["gray/kake-newsticker-20250219142858.xml"] == 251
    assert len(ENTRIES) >= 25


@pytest.mark.parametrize("entry", ENTRIES, ids=[entry["file"] for entry in ENTRIES])
def test_same_names_as_part_one_reads(entry: dict[str, object]) -> None:
    parse, variant = PARSERS[str(entry["expected"]["variant"])]  # type: ignore[index]
    listing: Listing = parse((FOLDER / str(entry["file"])).read_bytes())
    expected = entry["expected"]
    assert isinstance(expected, dict)
    assert listing.variant == variant
    assert listing.state is ListingState(expected["state"])
    assert [row.name for row in listing.rows] == expected["names"]


def test_block_headings_and_time_apply_to_the_rows_under_them() -> None:
    body = (FOLDER / "gray/wave-file-20190327182656.html").read_bytes()
    first = newsticker.parse(body).rows[0]
    assert first.updated_text == "LAST UPDATED: WEDNESDAY, MAR 27 AT 2:25 PM"
    assert first.extra["state"] == "Kentucky"
    assert first.extra["category"] == "SCHOOLS"
    wafb = newsticker.parse((FOLDER / "gray/wafb-file-20190418025348.html").read_bytes())
    assert len(wafb.rows) == 71

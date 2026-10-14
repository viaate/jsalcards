"""A district notice longer than a row may hold is kept to the row's limit, not refused.

The fixture is real: Bozeman School District 7's Finalsite homepage of 2024-01-17
23:47 UTC (archive-captures run 37161083109; provenance in
``fixtures/gate/PROVENANCE.json``), whose page pop held two of the
superintendent's letters about a statewide emailed bomb threat, over 2,000
characters. Before rows were clipped, this one capture stopped the whole archive
parse with a validation error.
"""

from pathlib import Path

from snowlight.sources.stations import finalsite, notices
from snowlight.sources.stations.gap_markup import make_row
from snowlight.sources.stations.model import MAX_STATUS, ListingState

FIXTURE = Path(__file__).parent / "fixtures" / "gate" / "finalsite" / "bozeman-20240117.html"


def test_a_long_page_pop_is_read_and_clipped() -> None:
    listing = finalsite.parse(FIXTURE.read_bytes())
    assert (listing.variant, listing.state) == ("finalsite-homepage-pops", ListingState.POPULATED)
    (row,) = listing.rows
    assert row.name == "School Safety Update"
    assert row.status.startswith("1.17.2024 Update: We are appreciative of Bozeman Police")
    assert len(row.status) == MAX_STATUS
    assert row.status.endswith("…")
    # It announces no closing (school proceeded at all sites), so it proves nothing.
    assert not notices.row_qualifies(row.name, row.status, listing.variant)


def test_make_row_clips_the_status_and_keeps_a_short_one_whole() -> None:
    long = make_row("Notice", "word " * 1000, None, {})
    assert long is not None
    assert len(long.status) == MAX_STATUS
    short = make_row("Notice", "  Schools   closed today ", None, {})
    assert short is not None
    assert short.status == "Schools closed today"

"""Part 4's SchoolBlocks adapter (district organization alerts) on real fixtures, and its registry.

Every fixture in fixtures/gaps/schoolblocks/ is a real body (see the folder's README and
PROVENANCE.json): Grace School District #148's live homepage with an alert up, and two
live homepages whose alerts lists are empty. Bodies named ``SYNTHETIC_*`` are made up
here, confined to these tests, and exercise the edge cases and refusals.
"""

import json

import pytest

from snowlight.sources.stations import gap_fixtures, notices, schoolblocks
from snowlight.sources.stations.model import ListingState, ShapeError
from snowlight.sources.stations.registry import CountyBasis, load_registry

FOLDER = gap_fixtures.DEFAULT_FOLDER


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def _page(record: object, title: str = "Home - SYNTHETIC District") -> bytes:
    """A made-up SchoolBlocks page whose payload holds ``record`` in two chunks."""
    text = json.dumps(record)
    half = len(text) // 2
    pushes = "".join(
        f"<script>self.__next_f.push({json.dumps([1, part])})</script>"
        for part in (text[:half], text[half:])
    )
    return f"<html><head><title>{title}</title></head><body>{pushes}</body></html>".encode()


def test_graces_live_alert_is_a_row() -> None:
    listing = schoolblocks.parse(_body("schoolblocks/grace-live-20260928.html"))
    assert listing.variant == schoolblocks.VARIANT
    assert listing.state is ListingState.POPULATED
    [row] = listing.rows
    assert row.name == "Grace School District #148"
    assert row.status == (
        "Grace School District will be closed from September 11-October 4 for potato harvest "
        "break. We will return to school on October 5. Emails and phone messages may not be "
        "received or returned until that time."
    )
    assert row.updated_text is None
    assert row.extra == {"alert_id": "28295", "alert_type": "overlay"}


@pytest.mark.parametrize(
    "name", ["schoolblocks/browning-live-20260928.html", "schoolblocks/uinta-1-live-20260928.html"]
)
def test_an_empty_alerts_list_is_an_empty_list(name: str) -> None:
    listing = schoolblocks.parse(_body(name))
    assert listing.variant == schoolblocks.VARIANT
    assert listing.state is ListingState.EMPTY


def test_the_gate_reads_the_alert_and_not_the_district_name() -> None:
    [row] = schoolblocks.parse(_body("schoolblocks/grace-live-20260928.html")).rows
    # Grace's closure is the potato harvest break, a planned break: it does not prove.
    assert not notices.row_qualifies(row.name, row.status, schoolblocks.VARIANT)
    # SYNTHETIC: the same channel announcing a snow closing would.
    assert notices.row_qualifies(
        row.name, "Schools are closed today due to snow.", schoolblocks.VARIANT
    )
    assert schoolblocks.VARIANT in notices.ORG_NAMED_VARIANTS
    assert "schoolblocks" in notices.GENERAL_CHANNEL_ADAPTERS
    # SYNTHETIC: a district named for weather does not prove itself with a hiring alert.
    assert not notices.row_qualifies("Storm Lake Schools", "We are hiring!", schoolblocks.VARIANT)


def test_an_alert_split_across_payload_chunks_is_read() -> None:
    body = _page(
        {
            "type": "district",
            "alerts": [
                {"id": 1, "message": "<p>Two-hour <b>delay</b> today</p>", "type": "banner"}
            ],
        }
    )
    [row] = schoolblocks.parse(body).rows
    assert (row.name, row.status) == ("SYNTHETIC District", "Two-hour delay today")
    assert row.extra == {"alert_id": "1", "alert_type": "banner"}


def test_an_alert_with_no_words_is_skipped() -> None:
    listing = schoolblocks.parse(_page({"alerts": [{"id": 2, "message": "<p> </p>"}]}))
    assert listing.state is ListingState.EMPTY
    assert listing.skipped_rows == 1


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (_page({"alerts": None}), "not a list"),
        (_page({"alerts": [{"message": "no id"}]}), "id"),
        (_page({"shortcuts": []}), "no alerts list"),
        (b"<html><head><title>SYNTHETIC</title></head></html>", "not a SchoolBlocks page"),
    ],
)
def test_other_bodies_are_refused(body: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        schoolblocks.parse(body)


def test_a_real_page_of_another_cms_is_refused() -> None:
    with pytest.raises(ShapeError, match="not a SchoolBlocks page"):
        schoolblocks.parse(_body("edlio/natrona-live-20260928.html"))


@pytest.mark.parametrize(
    "name",
    ["schoolblocks/grace-live-20260928.html", "schoolblocks/browning-live-20260928.html"],
)
def test_a_slice_reads_as_its_page_and_slicing_it_again_changes_nothing(name: str) -> None:
    sliced = _body(name)
    assert schoolblocks.slice_body(sliced) == sliced
    assert schoolblocks.parse(schoolblocks.slice_body(sliced)) == schoolblocks.parse(sliced)


def test_every_schoolblocks_station_is_a_district_source() -> None:
    stations = sorted(
        (s for s in load_registry().stations.values() if s.platform == "schoolblocks"),
        key=lambda s: s.id,
    )
    # 3 in Idaho, 3 in Texas, 2 each in Wyoming and California, 1 each in Montana, Alabama
    # and Mississippi
    assert len(stations) == 12
    for station in stations:
        assert 1 <= len(station.leaids) <= 2, station.id
        assert station.page_url in station.archive_urls
        assert station.data_url is None
        assert station.counties is not None
        assert station.counties.basis is CountyBasis.DISTRICT
        for leaid in station.leaids:
            assert leaid in station.counties.source
        assert station.robots
        assert all(check.allowed for check in station.robots)
    by_id = {s.id: s for s in stations}
    # Browning's elementary and high school districts, which the LEA directory lists
    # with the same website.
    assert by_id["schoolblocks-browning-mt"].leaids == ("3005140", "3005190")
    assert by_id["schoolblocks-grace-id"].leaids == ("1601290",)

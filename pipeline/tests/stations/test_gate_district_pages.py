"""The short states' district homepages read whole (``district-pages``), and the new alert services.

Round 5 of the coverage gate checked again, on 2026-10-13, every district record of a
state short of the target that the gap-state part had left "not built" or "not read"
in late September. The 56 districts whose homepages answer and carry no vendor alert
channel are the ``district-pages`` platform (read by the district-homepage adapter as
text); three more are SharpSchool sites whose alert service answers the homepage
component's POST, one moved to Apptegy, one is a Finalsite site.

Fixtures are real live bodies (``fixtures/gate/README.md`` records each one's URL, read
time and SHA-256): St. Lucie's homepage (no closing line), Greenville's (a news item of
January 2024 still up), Gulf's (the news card "SCHOOL CLOSURES: Hurricane Isaias", posted
2026-10-07 for the hurricane of 8-10 October 2026, read without and with its posting stamp)
and Corona-Norco's alert service. Observation times not taken from a read are named
``synthetic_*``.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from snowlight.sources.stations import district_homepage, fetch, notices, sharpschool, typed_history
from snowlight.sources.stations.model import (
    HealthStatus,
    Listing,
    ListingState,
    ParsedRow,
    ReadMode,
)
from snowlight.sources.stations.registry import CountyBasis, StationStatus, load_registry
from snowlight.sources.stations.storms import WarningDay
from snowlight.sources.stations.typed_history import Seen, Verdict

FOLDER = Path(__file__).parent / "fixtures" / "gate"
REGISTRY = load_registry()
GREENVILLE_AT = datetime(2026, 10, 13, 12, 18, 50, tzinfo=UTC)
GULF_AT = datetime(2026, 10, 13, 12, 19, 7, tzinfo=UTC)
GULF = "https://gulfcoschools.com/"


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def test_every_district_page_is_a_district_source_read_at_its_homepage() -> None:
    stations = [s for s in REGISTRY.stations.values() if s.platform == "district-pages"]
    assert len(stations) == 56
    platform = REGISTRY.platforms["district-pages"]
    assert platform.adapter == "district-homepage"
    assert platform.terms.pollable
    states = sorted({code for station in stations for code in station.states})
    assert states == ["CA", "FL", "ID", "MS", "WY"]
    for station in stations:
        assert station.status is StationStatus.ACTIVE
        assert station.data_url is None
        assert station.page_url is not None
        assert station.poll_url == station.page_url
        assert station.archive_urls[0] == station.page_url
        assert station.counties is not None
        assert station.counties.basis is CountyBasis.DISTRICT
        assert len(station.leaids) == 1, station.id
        assert [check.url for check in station.robots] == [station.page_url], station.id
        assert "2026-10-13" in station.evidence
    # A homepage read as text is a district's general channel: only closings prove it.
    assert "district-homepage" in notices.GENERAL_CHANNEL_ADAPTERS
    # Every read of such a page is an observation of its typed history.
    assert "district-homepage" in fetch.TYPED_PAGE_ADAPTERS
    # St. Lucie, the largest Florida county with no source before round 5.
    lucie = REGISTRY.stations["district-pages-st-lucie-fl"]
    assert (lucie.leaids, lucie.counties.fips if lucie.counties else ()) == (
        ("1201770",),
        ("12111",),
    )
    # A district that moved keeps its old address as an archive URL.
    columbia = REGISTRY.stations["district-pages-columbia-fl"]
    assert columbia.archive_urls == (
        "https://www.columbiak12.com/",
        "https://www.columbia.k12.fl.us/",
    )


def test_the_round_five_alert_services_and_sites() -> None:
    for sid in (
        "sharpschool-corona-norco-ca",
        "sharpschool-desert-sands-ca",
        "sharpschool-butte-id",
    ):
        station = REGISTRY.stations[sid]
        assert station.data_post == sharpschool.POST_BODY
        assert station.data_url is not None
        assert station.data_url.endswith(sharpschool.SERVICE_PATH)
    tallahatchie = REGISTRY.stations["apptegy-west-tallahatchie-ms"]
    assert tallahatchie.page_url == "https://www.wtsdschools.org/"
    goshen = REGISTRY.stations["finalsite-goshen-1-wy"]
    assert goshen.page_check is not None
    assert goshen.page_check.loads == ("https://www.goshen1.org/fs/pages/530/page-pops",)


def test_corona_norcos_alert_service_answers_an_empty_list() -> None:
    listing = sharpschool.parse(_body("sharpschool/corona-norco-alerts-live-20261013.json"))
    assert (listing.variant, listing.state, listing.rows) == (
        sharpschool.ALERTS_VARIANT,
        ListingState.EMPTY,
        (),
    )


def test_st_lucies_homepage_shows_no_closing_and_is_typed() -> None:
    listing = district_homepage.parse(_body("district/st-lucie-live-20261013.html"))
    assert (listing.variant, listing.state, listing.rows) == (
        district_homepage.TEXT,
        ListingState.EMPTY,
        (),
    )
    assert listing.typed
    status, reason = fetch.read_health(listing, GULF_AT, (None, None), (None, None), 0)
    assert (status, reason) == (HealthStatus.EMPTY, None)


def test_a_closing_of_a_day_gone_by_is_not_kept() -> None:
    listing = district_homepage.parse(_body("district/greenville-live-20261013.html"))
    assert listing.typed
    assert [row.name for row in listing.rows] == [
        "GPSD Extended School Year set for June 3, 2024 — GPSD closed on January 16, 2024 "
        "(Due to inclement weather)"
    ]
    judgement = typed_history.judge(listing.rows, GREENVILLE_AT, [])
    assert [item.verdict for item in judgement.rows] == [Verdict.PAST]
    assert judgement.kept == ()
    assert judgement.all_old
    status, _ = fetch.read_health(listing, GREENVILLE_AT, (None, None), (None, judgement), 0)
    assert status is HealthStatus.EMPTY


def test_an_undated_leftover_is_stale_until_an_earlier_read_dates_it() -> None:
    listing = district_homepage.parse(_body("district/gulf-live-20261013.html"))
    assert [row.name for row in listing.rows] == ["SCHOOL CLOSURES: Hurricane Isaias"]
    alone = typed_history.judge(listing.rows, GULF_AT, [])
    assert [item.verdict for item in alone.rows] == [Verdict.UNKNOWN]
    status, _ = fetch.read_health(listing, GULF_AT, (None, None), (None, alone), 0)
    assert status is HealthStatus.STALE
    keys = frozenset(typed_history.parsed_key(row) for row in listing.rows)
    synthetic_lacking = Seen(
        GULF_AT - timedelta(days=400), ReadMode.ARCHIVE, GULF, "0" * 64, frozenset()
    )
    synthetic_holding = Seen(GULF_AT - timedelta(days=200), ReadMode.ARCHIVE, GULF, "1" * 64, keys)
    dated = typed_history.judge(listing.rows, GULF_AT, [synthetic_lacking, synthetic_holding])
    assert [item.verdict for item in dated.rows] == [Verdict.OLD]
    status, _ = fetch.read_health(listing, GULF_AT, (None, None), (None, dated), 0)
    assert status is HealthStatus.EMPTY
    # A line an earlier read of the last day and a half did not hold is new: kept.
    synthetic_recent = Seen(
        GULF_AT - timedelta(hours=2), ReadMode.LIVE, GULF, "2" * 64, frozenset()
    )
    fresh = typed_history.judge(listing.rows, GULF_AT, [synthetic_holding, synthetic_recent])
    assert [item.verdict for item in fresh.rows] == [Verdict.NEW]
    assert fresh.kept == listing.rows


# A news card's posting stamp, and a line repeated unchanged ------------------------------


@dataclass(frozen=True)
class _Read:
    """SYNTHETIC: the field of a proof the page-text rule reads."""

    captured_at: datetime


GULF_COUNTY = "12045"
SYNTHETIC_HURRICANE = {  # the NWS record's shape: HU.W over the panhandle coast, 8-9 Oct 2026
    date(2026, 10, 8): WarningDay(date(2026, 10, 8), 1.0, GULF_COUNTY),
    date(2026, 10, 9): WarningDay(date(2026, 10, 9), 1.0, GULF_COUNTY),
}


def test_a_news_card_is_judged_by_the_day_it_was_posted() -> None:
    listing = district_homepage.parse(_body("district/gulf-live-20261013-posted.html"))
    assert [(row.name, row.status) for row in listing.rows] == [
        (
            "SCHOOL CLOSURES: Hurricane Isaias",
            "SCHOOL CLOSURES: Hurricane Isaias (posted Oct 07, 2026)",
        )
    ]
    row = listing.rows[0]
    assert row.extra["posted"] == "Oct 07, 2026"
    gate_row = notices.GateRow(row.name, row.status, notices.PAGE_TEXT)
    assert notices.posted_day(row.status) == date(2026, 10, 7)
    assert notices.row_qualifies(row.name, row.status, listing.variant, section=notices.PAGE_TEXT)
    read = _Read(datetime(2026, 10, 13, 14, 2, 47, tzinfo=UTC))
    # Posted the day before the Hurricane Warning: a dated post of that day, not a leftover.
    assert notices._text_current(gate_row, read, SYNTHETIC_HURRICANE, known=True)
    # The same card with no weather near its posting proves nothing.
    assert not notices._text_current(gate_row, read, {}, known=True)
    # The live reader sees a day gone by: the line is not kept as today's.
    judgement = typed_history.judge(listing.rows, read.captured_at, [])
    assert judgement.kept == ()


NORTH_GEM = "16029"
NORTH_GEM_LINE = notices.GateRow(
    "Due to current weather conditions, all North Gem schools are closed today.",
    "Due to current weather conditions, all North Gem schools are closed today.",
    notices.PAGE_TEXT,
)


def test_an_undated_line_proves_only_where_the_page_first_showed_it() -> None:
    # North Gem's homepage: the line went up on 2026-02-18 under a Winter Storm Warning and
    # stayed through the spring (captures to 2026-04-25, a Saturday) and to 2026-10-13.
    first = datetime(2026, 2, 18, 19, 21, 39, tzinfo=UTC)
    later = datetime(2026, 4, 25, 7, 2, 46, tzinfo=UTC)
    synthetic_spring_advisory = {  # an advisory near the late capture, as springs have
        date(2026, 4, 24): WarningDay(date(2026, 4, 24), 0.25, NORTH_GEM),
    }
    february = {date(2026, 2, 18): WarningDay(date(2026, 2, 18), 1.0, NORTH_GEM)}
    seen = notices.first_appearances(
        [(later, [NORTH_GEM_LINE]), (first, [NORTH_GEM_LINE]), (first, None)]
    )
    assert seen == {notices.line_key(NORTH_GEM_LINE): first}
    assert notices._text_current(NORTH_GEM_LINE, _Read(first), february, True, seen)
    assert not notices._text_current(
        NORTH_GEM_LINE, _Read(later), synthetic_spring_advisory, True, seen
    )
    # Later the same school day (storms.school_day: UTC plus eight hours) it is still that
    # day's news; on the next school day it is not.
    soon = first + timedelta(hours=3)
    assert notices._text_current(NORTH_GEM_LINE, _Read(soon), february, True, seen)
    next_day = first + timedelta(hours=28)
    assert not notices._text_current(NORTH_GEM_LINE, _Read(next_day), february, True, seen)


def test_a_channels_page_text_line_left_up_is_not_kept_live() -> None:
    # North Gem's SchoolBlocks homepage on 2026-10-13: no alert of the channel, and the
    # page's own line "all North Gem schools are closed today", up since 2026-02-18.
    station = REGISTRY.stations["schoolblocks-north-gem-id"]
    url = station.poll_url or ""
    line = ParsedRow(
        name=NORTH_GEM_LINE[0], status=NORTH_GEM_LINE[1], extra={"section": notices.PAGE_TEXT}
    )
    notice = ParsedRow(name="North Gem SD", status="Picture day is Thursday")
    listing = Listing(
        variant="schoolblocks-org-alerts", state=ListingState.POPULATED, rows=(notice, line)
    )
    read_at = datetime(2026, 10, 13, 14, 52, 12, tzinfo=UTC)
    keys = frozenset({typed_history.parsed_key(line)})
    february = Seen(
        datetime(2026, 2, 18, 19, 21, 39, tzinfo=UTC), ReadMode.ARCHIVE, url, "0" * 64, keys
    )
    april = Seen(datetime(2026, 4, 25, 7, 2, 46, tzinfo=UTC), ReadMode.ARCHIVE, url, "1" * 64, keys)
    history = typed_history.TypedHistory({station.id: [february, april]})
    judgement = fetch.judge_page_text(station, url, listing, read_at, history)
    assert judgement is not None
    assert [item.verdict for item in judgement.rows] == [Verdict.OLD]
    assert fetch.page_text_kept(listing.rows, judgement) == (notice,)
    # A list with no line of its page's text is not judged so.
    assert (
        fetch.judge_page_text(
            station, url, listing.model_copy(update={"rows": (notice,)}), read_at, history
        )
        is None
    )

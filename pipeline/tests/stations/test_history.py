"""A channel's server-dated history proves it only by a corroborated closing; leftovers never do.

The history fixtures (fixtures/history/) are real answers read live on 2026-10-13: pages of
Wyoming districts' Apptegy live feeds and KIFI's REST list of closings articles, each sliced
to one post. The warning days are the values
:func:`snowlight.sources.stations.storms.warning_days` gives for each source's counties from
the NWS record the closure weights count (weight 1.0 a Winter Storm, Blizzard or Ice Storm
Warning, 0.5 an Extreme Cold or Wind Chill Warning, 0.25 a Winter Weather Advisory). The
leftover lines are real: Greenville's and Gulf's homepages read live on 2026-10-13 (the
fixtures gate/district/greenville-live-20261013.html and gulf-live-20261013.html). Values
marked ``SYNTHETIC`` are made up here, confined to these tests.
"""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from snowlight.sources.stations import apptegy_feed, fetch, history, notices, wp_closings
from snowlight.sources.stations.fixtures import load_entries
from snowlight.sources.stations.model import ListingState, ParsedRow, ReadMode, ShapeError
from snowlight.sources.stations.proof import Proof
from snowlight.sources.stations.registry import load_registry
from snowlight.sources.stations.storms import WarningDay

FOLDER = history.DEFAULT_FOLDER
FIXTURES = FOLDER.parent
ENTRIES = {entry.file: entry for entry in load_entries(FOLDER)}
REGISTRY = load_registry()

JOHNSON = "56019"
CONVERSE = "56009"
FREMONT = "56013"
BONNEVILLE = "16019"
WARNINGS = {
    "apptegy-feed-johnson1-wy": {date(2024, 2, 27): WarningDay(date(2024, 2, 27), 1.0, JOHNSON)},
    "apptegy-feed-converse2-wy": {date(2025, 1, 20): WarningDay(date(2025, 1, 20), 0.5, CONVERSE)},
    "apptegy-feed-fremont-24-wy": {date(2025, 3, 6): WarningDay(date(2025, 3, 6), 1.0, FREMONT)},
    "apptegy-feed-fremont-14-wy": {date(2023, 4, 4): WarningDay(date(2023, 4, 4), 1.0, FREMONT)},
    "npg-articles-kifi": {date(2024, 3, 6): WarningDay(date(2024, 3, 6), 1.0, BONNEVILLE)},
}


@dataclass(frozen=True)
class _Proof:
    source_id: str
    mode: str
    url: str
    captured_at: datetime
    variant: str
    basis: str


def _fixture_proof(file: str) -> _Proof:
    entry = ENTRIES[file]
    return _Proof(
        entry.source_id,
        entry.mode.value,
        entry.url,
        entry.captured_at,
        entry.expected.variant,
        f"fixture history/{file}",
    )


# The fixtures and their provenance ---------------------------------------------------


def test_provenance_and_readme_agree_with_the_files() -> None:
    assert len(ENTRIES) == 6
    for entry in ENTRIES.values():
        body = (FOLDER / entry.file).read_bytes()
        assert hashlib.sha256(body).hexdigest() == entry.sha256, entry.file
        assert entry.mode is ReadMode.HISTORY
        assert entry.archive_url is None
        assert entry.slice in history.SLICERS
        listing = apptegy_feed.parse(body) if entry.adapter == "apptegy-feed" else None
        if listing is None:
            listing = wp_closings.parse(body)
        assert listing.state is ListingState.POPULATED
        assert tuple(row.name for row in listing.rows) == entry.expected.names
        # One post: every row carries the post's own time, the fixture's.
        times = {row.updated_text for row in listing.rows}
        assert len(times) == 1
        stamp = datetime.fromisoformat(str(times.pop()).replace("Z", "+00:00"))
        assert stamp.astimezone(UTC).replace(microsecond=0) == entry.captured_at
        assert entry.retrieved_at > entry.captured_at
    readme = history.render_readme([ENTRIES[name] for name in sorted(ENTRIES)])
    assert (FOLDER / "README.md").read_text(encoding="utf-8") == readme


def test_make_entry_refuses_a_slice_that_is_not_the_named_post() -> None:
    entry = ENTRIES["apptegy-feed/johnson1-20240227.json"]
    body = (FOLDER / entry.file).read_bytes()
    origin = history.Origin(
        source_id=entry.source_id,
        adapter="apptegy-feed",
        url=entry.url,
        retrieved_at="2026-10-13T12:55:30Z",
        published_at="2024-02-28T14:24:32Z",  # SYNTHETIC: a day off
    )
    with pytest.raises(ValueError, match="not one post"):
        history.make_entry("apptegy-feed/x.json", origin, body, "apptegy-feed-closings-v2", "")
    empty = json.dumps({"live_feeds": []}).encode()
    with pytest.raises(ValueError, match="holds no row"):
        history.make_entry("apptegy-feed/x.json", origin, empty, "apptegy-feed-closings-v2", "")


# The adapters --------------------------------------------------------------------------


def test_the_feed_adapter_reads_posts_with_their_server_times() -> None:
    body = (FOLDER / "apptegy-feed/johnson1-20240227.json").read_bytes()
    listing = apptegy_feed.parse(body)
    assert listing.variant == "apptegy-live-feed"
    assert listing.dated_rows
    assert listing.list_updated_at == datetime(2024, 2, 27, 14, 24, 32, tzinfo=UTC)
    (row,) = listing.rows
    assert row.status.startswith("Due to road conditions and inclement weather")
    assert row.updated_text == "2024-02-27T07:24:32.609-07:00"
    assert row.extra["post_id"] is not None


def test_the_feed_adapter_skips_unapproved_posts_and_refuses_other_shapes() -> None:
    # SYNTHETIC posts in the feed's shape.
    posts = [
        {"id": 1, "status": "<p>Hello</p>", "time": "2026-01-05T06:00:00-07:00", "approved": False},
        {"id": 2, "status": "Board meeting", "time": "2026-01-04T06:00:00-07:00"},
    ]
    listing = apptegy_feed.parse(json.dumps({"live_feeds": posts}).encode())
    assert [row.status for row in listing.rows] == ["Board meeting"]
    # SYNTHETIC: a post's author is the staff member who posted it, a person's name: the row
    # is named for the feed, and a fixture's slice does not keep it.
    named = {"id": 4, "status": "x", "time": "2026-01-04T06:00:00-07:00", "author_name": "A B"}
    body = json.dumps({"live_feeds": [named]}).encode()
    assert [row.name for row in apptegy_feed.parse(body).rows] == ["Live feed"]
    closing = {**named, "status": "No school today due to the snow storm."}
    sliced = apptegy_feed.slice_body(json.dumps({"live_feeds": [closing]}).encode())
    assert b"author_name" not in sliced
    assert b"A B" not in sliced
    assert listing.skipped_rows == 1
    assert listing.list_updated_at == datetime(2026, 1, 5, 13, 0, tzinfo=UTC)
    empty = apptegy_feed.parse(b'{"live_feeds": []}')
    assert empty.state is ListingState.EMPTY
    for bad in (b"[]", b'{"posts": []}', b'{"live_feeds": [{"id": 3, "status": "x"}]}', b"<html>"):
        with pytest.raises(ShapeError):
            apptegy_feed.parse(bad)


def test_the_articles_adapter_reads_the_station_closings_article_only() -> None:
    body = (FOLDER / "npg-articles/kifi-20240306.json").read_bytes()
    listing = wp_closings.parse(body)
    assert listing.dated_rows
    assert listing.list_updated_at == datetime(2024, 3, 6, 13, 18, 52, tzinfo=UTC)
    assert len(listing.rows) == 19
    assert listing.rows[0].name == "Aberdeen School District 58"
    assert listing.rows[0].status == "closed"
    assert listing.rows[-1].name == "Teton County School District 1"
    assert listing.rows[-1].status == "2 hour late start"
    assert {row.updated_text for row in listing.rows} == {"2024-03-06T22:57:42Z"}
    # SYNTHETIC posts: a wire story about closings elsewhere is not the station's list.
    wire = {
        "id": 9,
        "title": {"rendered": "School closures across the Midwest as cold sets in"},
        "link": "https://localnews8.com/news/national-world/ap-national/2024/01/16/x/",
        "content": {"rendered": "<p>x</p>"},
        "date_gmt": "2024-01-16T07:03:25",
        "modified_gmt": "2024-01-16T07:03:25",
    }
    assert wp_closings.parse(json.dumps([wire]).encode()).state is ListingState.EMPTY
    assert wp_closings.parse(b"[]").state is ListingState.EMPTY
    with pytest.raises(ShapeError):
        wp_closings.parse(b'{"posts": []}')


@pytest.mark.parametrize(
    ("title", "closings"),
    [
        ("School closures and delays for Wednesday, March 6", True),
        ("UPDATE: School Closures and Delays for Tuesday, Jan 16th", True),
        ("School closures for Feb. 28, 2023", True),
        ("Extreme cold causes school delays Wednesday", True),
        ("Overnight lane closures scheduled for U.S. 20 north of Sugar City", False),
        ("Taylorview Middle School closed Thursday due to down heat pumps", True),
        ("School board votes to close Washington Elementary", False),
    ],
)
def test_closings_article_titles(title: str, closings: bool) -> None:
    post = {
        "title": {"rendered": title},
        "link": "https://localnews8.com/news/2024/x/",
        "content": {"rendered": "<p>IDAHO FALLS, Idaho (KIFI) - x</p>"},
    }
    assert wp_closings.closings_article(post) is closings


# Step 6 of the live read: a feed keeps only new posts ------------------------------------


def test_a_feed_keeps_only_posts_published_within_the_window() -> None:
    read_at = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
    fresh = ParsedRow(
        name="FCSD #6", status="No school today", updated_text="2026-01-05T06:10:00-07:00"
    )
    old = ParsedRow(
        name="FCSD #6", status="No school today", updated_text="2025-12-01T06:10:00-07:00"
    )
    undated = ParsedRow(name="FCSD #6", status="No school today")
    assert fetch.posted_recently(fresh, read_at)
    assert not fetch.posted_recently(old, read_at)
    assert not fetch.posted_recently(undated, read_at)
    later = ParsedRow(name="x", status="y", updated_text=(read_at + timedelta(hours=2)).isoformat())
    assert not fetch.posted_recently(later, read_at)
    body = json.dumps(
        {
            "live_feeds": [
                {"id": 1, "status": "No school today", "time": "2025-12-01T06:10:00-07:00"}
            ]
        }
    ).encode()
    listing = apptegy_feed.parse(body)
    assert fetch.current_rows(listing, read_at, None, None) == ()
    status, why = fetch.read_health(listing, read_at, (None, None), (None, None), 0)
    assert status.value == "empty"
    assert why is not None
    assert "none published within 36 hours" in why


# The rule a history post proves by ----------------------------------------------------


@pytest.mark.parametrize(
    ("file", "why"),
    [
        ("apptegy-feed/johnson1-20240227.json", "warning"),
        ("apptegy-feed/converse2-20250120.json", "warning"),
        ("apptegy-feed/fremont-24-20250306.json", "warning"),
        ("apptegy-feed/fremont-14-20230403.json", "warning"),
        ("apptegy-feed/fremont-6-20260818.json", "emergency"),
        ("npg-articles/kifi-20240306.json", "warning"),
    ],
)
def test_each_history_fixture_proves_its_source(file: str, why: str) -> None:
    item = _fixture_proof(file)
    proofs = {item.source_id: [item]}
    report = notices.gate_proofs(
        proofs, REGISTRY, live_rows=[], archive_rows=[], fixtures=FIXTURES, warnings=WARNINGS
    )
    assert proofs[item.source_id] == [item]
    entry = report[item.source_id]
    assert isinstance(entry, dict)
    kept = entry["kept_proofs"]
    assert isinstance(kept, list)
    assert isinstance(kept[0], dict)
    assert why in kept[0]
    assert entry["kind"] == ("list" if item.source_id == "npg-articles-kifi" else "channel")


def test_without_the_nws_record_a_weather_post_does_not_prove() -> None:
    item = _fixture_proof("apptegy-feed/johnson1-20240227.json")
    proofs = {item.source_id: [item]}
    report = notices.gate_proofs(
        proofs, REGISTRY, live_rows=[], archive_rows=[], fixtures=FIXTURES, warnings={}
    )
    assert proofs[item.source_id] == []
    entry = report[item.source_id]
    assert isinstance(entry, dict)
    assert entry["dropped_count"] == 1
    # The water main break needs no warning: an emergency the NWS does not record.
    water = _fixture_proof("apptegy-feed/fremont-6-20260818.json")
    kept = {water.source_id: [water]}
    notices.gate_proofs(
        kept, REGISTRY, live_rows=[], archive_rows=[], fixtures=FIXTURES, warnings={}
    )
    assert kept[water.source_id] == [water]


DAYS = {date(2025, 3, 6): WarningDay(date(2025, 3, 6), 1.0, FREMONT)}


@pytest.mark.parametrize(
    ("status", "published", "proves"),
    [
        # Real posts (feeds of Fremont #24 and Converse #2).
        (
            "Due to the extreme weather and road conditions, there will be no school on "
            "Friday, March 7, 2025.",
            datetime(2025, 3, 6, 21, 57, tzinfo=UTC),
            True,
        ),
        (
            "Good Morning,PreK-6th grade will have school as scheduled today, March 6. If the "
            "storm begins to produces dangerous conditions, we will proceed with an early "
            "dismissal.",
            datetime(2025, 3, 6, 12, 18, tzinfo=UTC),
            False,
        ),
        # SYNTHETIC: the same closing, named a year off (a leftover), and on a dry week.
        (
            "Due to the extreme weather, there will be no school on Friday, March 7, 2025.",
            datetime(2026, 3, 6, 21, 57, tzinfo=UTC),
            False,
        ),
        (
            "Due to snow, all schools are closed today.",
            datetime(2025, 3, 20, 13, 0, tzinfo=UTC),
            False,
        ),
        # SYNTHETIC: a track meet cancelled for the weather is no closing.
        (
            "The MS Track Meet at Wind River tomorrow has been CANCELED due to weather!",
            datetime(2025, 3, 6, 14, 0, tzinfo=UTC),
            False,
        ),
    ],
)
def test_history_row_proves(status: str, published: datetime, proves: bool) -> None:
    found = notices.history_row_proves(
        "Shoshoni Schools", status, title=None, published=published, warnings=DAYS, tv_list=False
    )
    assert (found is not None) is proves


def test_a_friday_evening_post_is_corroborated_by_monday_or_the_day_before() -> None:
    # SYNTHETIC days and post.
    monday = {date(2024, 1, 15): WarningDay(date(2024, 1, 15), 0.5, JOHNSON)}
    friday_evening = datetime(2024, 1, 13, 1, 30, tzinfo=UTC)  # Friday 18:30 MST
    text = "Due to extreme cold, all schools will be closed Monday."
    found = notices.corroborated(text, friday_evening, monday)
    assert isinstance(found, WarningDay)
    assert found.day == date(2024, 1, 15)
    assert notices.corroborated(text, friday_evening, {}) is None


# Proof addresses -----------------------------------------------------------------------


def test_a_history_read_of_a_feed_page_is_of_the_station_current_address() -> None:
    station = REGISTRY.stations["apptegy-feed-johnson1-wy"]
    entry = ENTRIES["apptegy-feed/johnson1-20240227.json"]
    proof = Proof(
        source_id=station.id,
        mode=ReadMode.HISTORY.value,
        url=entry.url,
        captured_at=entry.captured_at,
        rows=1,
        sha256=entry.original_sha256,
        variant=entry.expected.variant,
        basis="fixture history/apptegy-feed/johnson1-20240227.json",
    )
    assert proof.current(station)
    assert proof.capture_url is None
    other = replace(proof, url="https://example.com/feed?page_no=4")
    assert not other.current(station)


def test_a_history_read_is_the_stations_list_only_under_the_lists_own_search() -> None:
    station = REGISTRY.stations["npg-articles-kifi"]
    entry = ENTRIES["npg-articles/kifi-20240306.json"]
    proof = Proof(
        source_id=station.id,
        mode=ReadMode.HISTORY.value,
        url=entry.url,
        captured_at=entry.captured_at,
        rows=19,
        sha256=entry.original_sha256,
        variant=entry.expected.variant,
        basis="fixture history/npg-articles/kifi-20240306.json",
    )
    assert proof.current(station)  # the same search, windowed by after/before
    for search in ("search=snow", "search=school%20closures", "author=7"):
        moved = entry.url.replace("search=school", search, 1)
        assert not replace(proof, url=moved).current(station), search
    widened = entry.url.replace("&categories_exclude=", "&x=1&categories_exclude=", 1)
    assert not replace(proof, url=widened).current(station)
    paged = entry.url + "&page=3&per_page=10"
    assert replace(proof, url=paged).current(station)


# Leftovers on a homepage never prove -----------------------------------------------------


def _page_text_proof(tmp_path: Path, source: str, at: str, line: str) -> tuple[Path, _Proof]:
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        json.dumps(
            {
                "source_id": source,
                "fetched_at": at,
                "raw_name": line,
                "raw_status": line,
                "raw_updated_text": None,
                "raw_extra": {"section": notices.PAGE_TEXT},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    moment = datetime.fromisoformat(at.replace("Z", "+00:00"))
    return rows, _Proof(
        source, "live", "https://example.org/", moment, "district-homepage-text", "live reads"
    )


@pytest.mark.parametrize(
    ("source", "line"),
    [
        (
            "district-pages-greenville-ms",
            "GPSD Extended School Year set for June 3, 2024 — GPSD closed on January 16, "
            "2024 (Due to inclement weather)",
        ),
        # Gulf's card "SCHOOL CLOSURES: Hurricane Isaias" is not a leftover: it was posted
        # on 2026-10-07 for the hurricane of 8-10 October 2026, and is judged by that day
        # (test_gate_district_pages.py); with no NWS record it proves nothing either.
        (
            "district-pages-gulf-fl",
            "SCHOOL CLOSURES: Hurricane Isaias (posted Oct 07, 2026)",
        ),
    ],
)
def test_a_homepage_leftover_read_live_does_not_prove(
    tmp_path: Path, source: str, line: str
) -> None:
    rows, item = _page_text_proof(tmp_path, source, "2026-10-13T12:18:50Z", line)
    proofs = {source: [item]}
    report = notices.gate_proofs(
        proofs, REGISTRY, live_rows=[rows], archive_rows=[], fixtures=None, warnings={}
    )
    assert proofs[source] == []
    entry = report[source]
    assert isinstance(entry, dict)
    dropped = entry["dropped"]
    assert isinstance(dropped, list)
    assert isinstance(dropped[0], dict)
    assert "leftover" in str(dropped[0]["reason"])
    assert isinstance(entry, dict)
    assert entry["dropped_count"] == 1


def test_a_page_text_closing_of_the_day_still_proves(tmp_path: Path) -> None:
    # SYNTHETIC: a line naming the day of the read, on a warning day.
    line = "Due to snow and icy roads, all schools are closed today, Monday, January 13, 2025."
    rows, item = _page_text_proof(tmp_path, "district-pages-firth-id", "2025-01-13T13:00:00Z", line)
    proofs = {item.source_id: [item]}
    notices.gate_proofs(
        proofs, REGISTRY, live_rows=[rows], archive_rows=[], fixtures=None, warnings={}
    )
    assert proofs[item.source_id] == [item]
    # Undated, it needs an NWS code within two days of the read.
    undated = "Due to snow and icy roads, all schools are closed today."
    rows, item = _page_text_proof(
        tmp_path, "district-pages-firth-id", "2025-01-13T13:00:00Z", undated
    )
    proofs = {item.source_id: [item]}
    notices.gate_proofs(
        proofs, REGISTRY, live_rows=[rows], archive_rows=[], fixtures=None, warnings={}
    )
    assert proofs[item.source_id] == []
    near = {date(2025, 1, 14): WarningDay(date(2025, 1, 14), 0.25, "16051")}
    proofs = {item.source_id: [item]}
    notices.gate_proofs(
        proofs,
        REGISTRY,
        live_rows=[rows],
        archive_rows=[],
        fixtures=None,
        warnings={item.source_id: near},
    )
    assert proofs[item.source_id] == [item]

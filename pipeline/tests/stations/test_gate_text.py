"""Round 3 of the coverage gate: the closure-text check, the forms it found misread, Utah.

The critic of round 2 found storm-day captures the adapters had misread while the
gate settled their sources: KULR's ``/schoolclosures/`` page of 2019 listing 23
Montana schools in a form the Cowles adapter refused, Orange County's SharpSchool
homepage of Hurricane Ian whose banner caption no reader looked at, Indian River's
homepage news of Tropical Storm Eta. These tests pin the check that finds such
captures (:mod:`snowlight.sources.stations.closure_text`), the gate's rule that a
source with one in its closure window is never settled (``misread``), the readers
of those forms (fixtures/gate/: every fixture a real capture or live body, provenance
in its PROVENANCE.json), the page-text rows and their stricter proof rule, and the
five Utah district sources. Snippets built here are synthetic and say so (their
URLs are under .test).
"""

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from snowlight.sources.stations import (
    archive,
    closure_text,
    cowles,
    district_homepage,
    edlio,
    fetch,
    finalsite,
    gate,
    gate_cli,
    gate_fixtures,
    homepage,
    notices,
    schoolwires,
    sharpschool,
    sinclair,
    smartsites,
    tegna,
)
from snowlight.sources.stations import body as body_module
from snowlight.sources.stations.apptegy import parse as apptegy_parse
from snowlight.sources.stations.archive import Capture
from snowlight.sources.stations.model import (
    HealthStatus,
    Listing,
    ListingState,
    RawRow,
    ShapeError,
    SourceHealth,
)
from snowlight.sources.stations.registry import PageCheck, StationStatus, load_registry

FOLDER = gate_fixtures.DEFAULT_FOLDER
ENTRIES = {entry.file: entry for entry in gate_fixtures.load_entries(FOLDER)}
REGISTRY = load_registry()


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def _text(name: str) -> str:
    return _body(name).decode("utf-8")


# --- the closure-text check -------------------------------------------------------------

# Lines as captures showed them (the capture is named), and what the check makes of each.
REAL_LINES = [
    ("Statewide school delays and closures for Monday, March 4", True),  # KULR 2019-07-16
    ("SDIRC Closed Monday Nov. 9 Due to Potential Storm Impacts From Tropical Storm Eta", True),
    ("Late Start on January 11", True),  # Juab 2024-01-11
    ("Robstown ISD Schools Closed Tuesday Due to Inclement Weather", True),  # 2025-01-21
    ("Tropical Storm Nicole Update: District & School Closures", True),  # Seminole 2022-11-10
    ("ALL MADISON SCHOOLS WILL BE CLOSED FEB. 14th DUE TO WEATHER", True),  # a draft
    # Not closings: a road's, a link to a procedure, a planned day, a heading, a deadline.
    ("Heavy rain floods roads, prompts road closures for San Diego County", False),  # KNSD
    ("Snow Day Procedures and Process", False),  # Darby 2022-12-01
    ("Easter Monday-No School", False),  # Sweetwater #1 2026-03-02
    ("Early Release Wednesdays", False),  # Cleveland 2026-01-26
    ("School Closures & Delays in Montana", False),  # KULR's heading
    ("Policy No. 2450: School Closures and Boundary Changes Policy", False),  # Cache 2026
    ("Kindergarten online registration opened on March 4, 2026, and will close June 18.", False),
    # A snow day named with no day: an explainer (Weber 2023-2025), a story (Canyons 2023).
    (
        "Utah is a winter state with the Ogden area receiving over five feet of snowfall "
        "annually. During winter months, temperatures can average in the 20s & 30s",
        False,
    ),
    ("Schools in the Canyons District Are Back in Session After Snow Day", False),
    # NBC's empty state on its closings page.
    (
        "But don't worry, we update this page regularly so you'll be the first to know if "
        "your school is closing or will have delays due to bad weather.",
        False,
    ),
]


@pytest.mark.parametrize(("line", "closing"), REAL_LINES)
def test_which_lines_announce_a_closing(line: str, closing: bool) -> None:
    assert closure_text.is_closing(line) is closing


def test_the_check_reads_what_a_visitor_sees_and_marks_links() -> None:
    # SYNTHETIC: a page with a menu, a footer, a script, a teaser link and a notice.
    page = (
        b"<html><body><nav><a href='/c'>School closed Monday due to snow</a></nav>"
        b"<div class='site-menu'><a href='/m'>Snow day Monday: no school</a></div>"
        b"<script>var x = 'Schools closed Monday due to snow';</script>"
        b"<p>All schools <strong>will be closed</strong> Monday due to snow.</p>"
        b"<h3><a href='/story'>Schools closed Tuesday due to ice</a></h3>"
        b"<footer><ul><li>Closed Monday for the storm</li></ul>"
        b"<p>Schools closed Friday for the storm</p></footer></body></html>"
    )
    blocks = closure_text.closing_blocks(page)
    # The menus' entries are not read (their lists, buttons and short links); the rest of
    # the navigation's text is (the footer's paragraph).
    assert [(line.text, line.link) for line in blocks] == [
        ("All schools will be closed Monday due to snow.", False),
        ("Schools closed Tuesday due to ice", True),
        ("Schools closed Friday for the storm", False),
    ]
    # A JSON body is read as its string values, HTML in them as text.
    answer = json.dumps([{"title": "<b>Schools closed Monday</b> for snow"}]).encode()
    assert closure_text.page_lines(answer) == ["Schools closed Monday for snow"]


def test_kulr_and_indian_river_show_closing_lines_in_their_text() -> None:
    kulr = closure_text.closure_lines(closure_text.page_lines(_body("lists/kulr-20190716.html")))
    assert "Statewide school delays and closures for Monday, March 4" in kulr
    river = closure_text.closure_lines(
        closure_text.page_lines(_body("sharpschool/indian-river-20201108.html"))
    )
    assert river[0] == (
        "SDIRC Closed Monday Nov. 9 Due to Potential Storm Impacts From Tropical Storm Eta"
    )


def _row(name: str, status: str = "") -> RawRow:
    return RawRow(
        source_id="synthetic-a",
        fetched_at=datetime(2025, 1, 8, tzinfo=UTC),
        raw_name=name,
        raw_status=status,
        raw_updated_text=None,
        raw_extra={},
    )


def test_outcomes() -> None:
    line = closure_text.Line("Schools closed Monday due to snow")
    teaser = closure_text.Line("Schools closed Monday due to snow", link=True)
    held = closure_text.ReadOf("populated", "v", (_row("District", line.text),))
    empty = closure_text.ReadOf("empty", "v")
    refused = closure_text.ReadOf("error", None, reason="unrecognized shape: not a page")
    shell = closure_text.ReadOf("error", "v", reason="the page holds no list and no count: x")
    assert closure_text.outcome(held, [line])[0] == "read"
    assert closure_text.outcome(empty, [line])[0] == "missed"
    assert closure_text.outcome(empty, [])[0] == "clean"
    assert closure_text.outcome(refused, [])[0] == "unrecognized"
    assert closure_text.outcome(shell, [])[0] == "shell"
    assert closure_text.outcome(shell, [line])[0] == "missed"
    assert closure_text.outcome(closure_text.ReadOf("deferred", "v"), [])[0] == "shell"
    # A page the archive cut off before its list: neither misread nor seen, unless the part
    # it holds shows a closing.
    cut = closure_text.ReadOf("error", None, reason="cut off: the archive holds only ...")
    assert closure_text.outcome(cut, [])[0] == "cut"
    assert closure_text.outcome(cut, [line])[0] == "missed"
    assert "cut" not in closure_text.MISREAD
    # A TV page's story teaser is not its list: excused there, not on a district's page.
    assert closure_text.outcome(empty, [teaser], teasers=True)[0] == "clean"
    assert closure_text.outcome(empty, [teaser])[0] == "missed"
    # A row holds a line when its words hold the line's first 60 characters, or the
    # line holds the row's status.
    assert closure_text.line_read(line.text, closure_text.row_texts([_row(line.text)]))
    long = "Due to snow all district schools will be closed Monday, January 6, and offices too."
    assert closure_text.line_read(long, closure_text.row_texts([_row("X", long[:70])]))


def _manifest(tmp_path: Path, body: bytes, url: str, stamp: str) -> Path:
    run = tmp_path / "artifacts" / "snapshots-1" / "snapshots"
    run.mkdir(parents=True)
    (run / "a.body").write_bytes(body)
    # A SYNTHETIC manifest line in the workflow's format, for a real body.
    record = {
        "timestamp": stamp,
        "url": url,
        "requested": f"https://web.archive.org/web/{stamp}id_/{url}",
        "hops": [],
        "retrieved_at": "2026-10-05T00:00:00Z",
        "final_timestamp": stamp,
        "final_original": url,
        "http_status": 200,
        "file": "snapshots/a.body",
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    (run / "manifest.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    return tmp_path / "artifacts"


def test_check_captures_finds_a_closing_the_read_did_not_hold(tmp_path: Path) -> None:
    body = _body("sharpschool/indian-river-20201108.html")
    url = "https://www.indianriverschools.org/"
    root = _manifest(tmp_path, body, url, "20201108234103")
    when = datetime(2020, 11, 8, 23, 41, 3, tzinfo=UTC)
    # As round 2 read it: an error, the page refused.
    reads = closure_text.Reads()
    reads.by_capture[("20201108234103", "indianriverschools.org/")] = closure_text.ReadOf(
        "error", None, reason="unrecognized shape: no __NUXT_DATA__ payload"
    )
    (found,) = closure_text.check_captures(REGISTRY, root, reads, {"apptegy-indian-river-fl"})
    assert found.outcome == "unrecognized"
    assert found.lines[0]["text"] == (
        "SDIRC Closed Monday Nov. 9 Due to Potential Storm Impacts From Tropical Storm Eta"
    )
    # As round 3 reads it: the page's closing lines are its rows.
    listing = apptegy_parse(body)
    rows = [
        RawRow(
            source_id="apptegy-indian-river-fl",
            fetched_at=when,
            raw_name=row.name,
            raw_status=row.status,
            raw_updated_text=row.updated_text,
            raw_extra=row.extra,
        )
        for row in listing.rows
    ]
    reads.by_capture[("20201108234103", "indianriverschools.org/")] = closure_text.ReadOf(
        "populated", listing.variant, tuple(rows)
    )
    (again,) = closure_text.check_captures(REGISTRY, root, reads, {"apptegy-indian-river-fl"})
    assert again.outcome == "read"
    out = tmp_path / "out"
    coverage = {"path": "coverage.json", "sha256": "c" * 64, "generated_at": None}
    path, summary_path = closure_text.write_checks(out, [found], coverage)
    checked = closure_text.load_checks(path)
    assert checked.misread("20201108234103", "indianriverschools.org/")
    assert checked.coverage_sha256 == "c" * 64
    assert json.loads(summary_path.read_text())["outcomes"] == {"unrecognized": 1}


def test_the_gate_refuses_a_check_made_against_another_coverage(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.json"
    coverage.write_text("{}", encoding="utf-8")
    out = tmp_path / "archive"
    record = {"path": "coverage.json", "sha256": "0" * 64, "generated_at": None}
    path, _ = closure_text.write_checks(out, [], record)
    with pytest.raises(gate.GateError, match="another coverage result"):
        gate_cli._checks(path, coverage)
    sha = hashlib.sha256(coverage.read_bytes()).hexdigest()
    closure_text.write_checks(out, [], {**record, "sha256": sha})
    assert gate_cli._checks(path, coverage).coverage_sha256 == sha
    with pytest.raises(gate.GateError, match="no closure-text check"):
        gate_cli._checks(tmp_path / "missing.jsonl", coverage)


# --- the gate: a misread capture in the window keeps a source open --------------------------

KEY = "synthetic-k.test/closings"


def _census(misread: dict[tuple[str, str], str]) -> gate.Census:
    captures = [
        Capture("20250108150000", "https://synthetic-k.test/closings", "200", "text/html", 9, "A"),
        Capture("20250301150000", "https://synthetic-k.test/closings", "200", "text/html", 9, "B"),
    ]
    return gate.Census(
        listings={KEY: captures},
        listing_names=set(),
        read={("20250108150000", KEY): "empty", ("20250301150000", KEY): "error"},
        misread=misread,
    )


def test_a_misread_window_capture_keeps_the_source_open() -> None:
    closure = {date(2025, 1, 8)}
    clean = gate.key_census(_census({}), "synthetic-k", KEY, None, closure=closure)
    # The capture of March was refused by its adapter (``error``): misread whatever the
    # closure-text check said, but outside the window it keeps nothing open.
    assert (clean.misread, clean.window_misread, clean.window_seen) == (1, 0, 1)
    assert gate.verdict("working", False, [clean], StationStatus.ACTIVE) == "all-read"
    # The storm-day capture showed a closing its read did not hold: misread, never settled.
    missed = _census({("20250108150000", KEY): "missed"})
    census = gate.key_census(missed, "synthetic-k", KEY, None, closure=closure)
    assert (census.misread, census.window_misread) == (2, 1)
    assert census.as_json()["window_misread"] == 1
    for storm_days in (False, True):
        code = gate.verdict("working", False, [census], StationStatus.ACTIVE, storm_days=storm_days)
        assert code == "misread"
        assert code not in gate.TERMINAL
    # A refused capture outside the window counts but does not keep it open.
    outside = _census({("20250301150000", KEY): "unrecognized"})
    fair = gate.key_census(outside, "synthetic-k", KEY, None, closure=closure)
    assert (fair.misread, fair.window_misread) == (1, 0)
    assert gate.verdict("working", False, [fair], StationStatus.ACTIVE) == "all-read"
    # A proven station stays proven.
    assert gate.verdict("working", True, [census], StationStatus.ACTIVE) == "proven"


def test_a_refused_window_capture_keeps_the_source_open_without_the_text_check() -> None:
    # SYNTHETIC census: the storm-day capture was refused by its adapter (``error``);
    # the closure-text check never saw it (no outcome), yet the source is not settled.
    captures = [
        Capture("20250108150000", "https://synthetic-k.test/closings", "200", "text/html", 9, "A"),
        Capture("20250109150000", "https://synthetic-k.test/closings", "200", "text/html", 9, "B"),
    ]
    census = gate.Census(
        listings={KEY: captures},
        listing_names=set(),
        read={("20250108150000", KEY): "error", ("20250109150000", KEY): "empty"},
    )
    days = {date(2025, 1, 8), date(2025, 1, 9)}
    found = gate.key_census(census, "synthetic-k", KEY, None, closure=days)
    assert (found.misread, found.window_misread, found.window_seen) == (1, 1, 1)
    for storm_days in (False, True):
        code = gate.verdict("working", False, [found], StationStatus.ACTIVE, storm_days=storm_days)
        assert code == "misread"
    # A shell (a page that loads its list from an address the archive does not hold)
    # is not misread: it is read state ``shell``, not ``error``.
    shell = gate.Census(
        listings={KEY: captures},
        listing_names=set(),
        read={("20250108150000", KEY): "shell", ("20250109150000", KEY): "empty"},
    )
    seen = gate.key_census(shell, "synthetic-k", KEY, None, closure=days)
    assert (seen.misread, seen.window_misread) == (0, 0)
    assert gate.verdict("working", False, [seen], StationStatus.ACTIVE) == "all-read"


def test_a_window_capture_identical_to_a_misread_one_is_misread() -> None:
    # SYNTHETIC census: the capture of March was found to show a closing its read did
    # not hold; the storm-day capture of January has the same digest, so it showed the
    # same page, and is read by digest only.
    captures = [
        Capture("20250108150000", "https://synthetic-k.test/closings", "200", "text/html", 9, "A"),
        Capture("20250301150000", "https://synthetic-k.test/closings", "200", "text/html", 9, "A"),
    ]
    census = gate.Census(
        listings={KEY: captures},
        listing_names=set(),
        read={("20250301150000", KEY): "empty"},
        misread={("20250301150000", KEY): "missed"},
    )
    found = gate.key_census(census, "synthetic-k", KEY, None, closure={date(2025, 1, 8)})
    assert (found.misread, found.window_misread) == (2, 1)
    assert gate.verdict("working", False, [found], StationStatus.ACTIVE) == "misread"


def test_read_captures_tells_shells_from_refusals() -> None:
    when = datetime(2025, 1, 8, 15, 0, tzinfo=UTC)

    def failure(reason: str, url: str) -> SourceHealth:
        return SourceHealth(
            source_id="synthetic-k",
            url=url,
            checked_at=when,
            status=HealthStatus.ERROR,
            rows=0,
            reason=reason,
            sha256="0" * 64,
        )

    found = gate.read_captures(
        [],
        [
            failure(
                "the page holds no list and no count: it loads its list after the page does",
                "https://a.synthetic-k.test/",
            ),
            failure(
                "the page gives only a count (3 listed), not the list",
                "https://b.synthetic-k.test/",
            ),
            failure("unrecognized shape: not a page", "https://c.synthetic-k.test/"),
        ],
    )
    assert found == {
        ("20250108150000", "a.synthetic-k.test/"): "shell",
        ("20250108150000", "b.synthetic-k.test/"): "shell",
        ("20250108150000", "c.synthetic-k.test/"): "error",
    }
    assert "shell" in gate.BLIND_STATES


def test_census_from_files_marks_the_misread_captures(tmp_path: Path) -> None:
    (tmp_path / "cdx-1").mkdir()
    checks = closure_text.Checked(
        {
            ("20250108150000", KEY): "missed",
            ("20250109150000", KEY): "clean",
            ("20250110150000", KEY): "read",
        },
        frozenset(),
    )
    census = gate.census_from_files(tmp_path, [], [], checks)
    assert census.misread == {("20250108150000", KEY): "missed"}
    assert census.noted == {("20250110150000", KEY)}


def test_a_window_closing_that_did_not_prove_is_unconfirmed_not_storm_read() -> None:
    closure = {date(2025, 1, 8)}
    # The storm-day capture showed a closing its rows hold (a delay naming no weather):
    # every window capture read, but the verdict says the list may be in use.
    noted = gate.Census(
        listings=_census({}).listings,
        read={("20250108150000", KEY): "populated", ("20250301150000", KEY): "empty"},
        noted=frozenset({("20250108150000", KEY)}),
    )
    census = gate.key_census(noted, "synthetic-k", KEY, None, closure=closure)
    assert (census.window_noted, census.as_json()["window_noted"]) == (1, 1)
    code = gate.verdict("working", False, [census], StationStatus.ACTIVE)
    assert code == "unconfirmed"
    assert code in gate.TERMINAL
    # The same closing outside the window changes nothing.
    outside = gate.Census(
        listings=noted.listings, read=noted.read, noted=frozenset({("20250301150000", KEY)})
    )
    fair = gate.key_census(outside, "synthetic-k", KEY, None, closure=closure)
    assert gate.verdict("working", False, [fair], StationStatus.ACTIVE) == "all-read"
    # A misread window capture still keeps it open.
    both = gate.Census(
        listings=noted.listings,
        read=noted.read,
        misread={("20250301150000", KEY): "missed"},
        noted=noted.noted,
    )
    near = gate.key_census(
        both, "synthetic-k", KEY, None, closure={date(2025, 1, 8), date(2025, 3, 1)}
    )
    assert gate.verdict("working", False, [near], StationStatus.ACTIVE) == "misread"


# --- the notice gate: page text and story cards prove only a weather closing ----------------


def test_weather_closing() -> None:
    assert notices.weather_closing("Robstown ISD Schools Closed Tuesday Due to Inclement Weather")
    assert notices.weather_closing("Snow Day Monday: no school")
    assert not notices.weather_closing("Heavy rain floods roads, prompts road closures")
    assert not notices.weather_closing("Dodson Public Schools closed indefinitely due to COVID-19")
    assert not notices.weather_closing("Delayed Start to Class on Jan 26, 2026")
    assert not notices.weather_closing("Thanksgiving Break: schools closed, snow likely")
    # A channel's own notice still proves by the channel rule.
    assert notices.row_qualifies("Delayed Start", "Delayed start on Jan 26", "edlio-homepage-alert")
    # A page-text row proves only a closing for weather or an emergency: a closing that
    # names no reason reads the same as a calendar's planned day.
    assert not notices.row_qualifies(
        "Delayed Start", "Delayed start on Jan 26", "edlio-homepage-alert", section="page-text"
    )
    for planned in ("Early Release Wednesday, Jan. 15", "Closed Monday, Nov. 11 for Veterans Day"):
        assert not notices.row_qualifies(planned, planned, "x", section="page-text")


@pytest.mark.parametrize(
    ("line", "proves"),
    [
        # Real lines of archived homepages (closure-text check, 2026-10-05).
        ("SDIRC Closed Monday Nov. 9 Due to Potential Storm Impacts From Tropical Storm Eta", True),
        ("Hurricane Ian: BPS Announces School and District Closure", True),
        ("All SBHC Schools closed due to severe weather", True),
        ("Due to winter weather, all classes are canceled for the following schools:", True),
        (
            "Classes will be cancelled for Monday, August 28th due to Hurricane Harvey. Updates "
            "will be posted as information becomes available.",
            True,
        ),
        # No reason named: a storm's closing and a calendar's day read alike.
        ("Delayed Start to Class on Jan 26, 2026", False),
        ("No School on Feb 15th, 2019 and Feb 18th, 2019", False),
        ("No Classes 09/01/25", False),
        ("CCISD properties will be closed on Fridays from June 5 through July 27.", False),
        # An event, a label, a teaser, an explainer.
        ("EXLP Snow Day at Aziz Farms", False),
        ("(SNOW DAYS)", False),
        ("Preparing for Extreme Snow Days", False),
        ("The Latest on Hurricane Eta and School Closures", False),
        (
            "Please use this link to read communications related to school closures and "
            "possible closures due to power outages.",
            False,
        ),
        (
            "Utah is a winter state with the Ogden area receiving over five feet of snowfall "
            "annually. ... Read More About Snow Days >>",
            False,
        ),
        (
            "A reception for the candidates scheduled for Wednesday, February 1st has been "
            "canceled due to road closures and conditions.",
            False,
        ),
        ("NO SCHOOL - WINTER BREAKAll Day - Jan 2, 2018", False),
        # Road conditions are weather's in a closing notice (Sublette County School District
        # #9's homepage, 2017-02-03), not in a reminder.
        (
            "Good morning! Due to road conditions SCSD #9 schools will start school an hour "
            "late today. All buses will run with the exception of LaBarge Creek and Fontenelle "
            "Creek. Buses will run accordingly with the late start. Thank you and have a safe "
            "morning!",
            True,
        ),
        ("Check road conditions before you drive to Friday's game", False),
    ],
)
def test_a_page_text_line_proves_only_a_closing_for_weather(line: str, proves: bool) -> None:
    assert notices.page_text_closing(line) is proves
    assert not notices.row_qualifies(
        "Dodson Public Schools closed indefinitely due to positive COVID-19 cases",
        "DODSON, Mont. - Dodson Public Schools closed temporarily ...",
        "cowles-section-cards",
    )


# --- the forms the check found misread ------------------------------------------------------


def test_kulr_closings_article_rows() -> None:
    listing = cowles.parse(_body("lists/kulr-20190716.html"))
    assert (listing.variant, listing.state, len(listing.rows)) == (
        cowles.ARTICLE,
        ListingState.POPULATED,
        23,
    )
    first, hardin = listing.rows[0], listing.rows[12]
    assert (first.name, first.status) == ("Amsterdam School", "CANCELED")
    assert first.extra["group"] == "Western Montana:"
    assert first.extra["headline"] == "Statewide school delays and closures for Monday, March 4"
    assert first.updated_text == "2019-03-03T14:45:00-07:00"
    assert (hardin.name, hardin.status) == ("Hardin SD 17", "No Buses. Classes start on time.")
    assert listing.typed
    assert listing.list_updated_at == datetime(2019, 3, 3, 21, 45, tzinfo=UTC)
    # Live, a typed list this old is not kept (fetch.TYPED_CURRENT).
    assert fetch.typed_not_current(listing, datetime(2019, 7, 16, tzinfo=UTC))
    october = cowles.parse(_body("lists/kulr-20191019.html"))
    assert [(row.name, row.status) for row in october.rows] == [
        ("Pretty Eagle Catholic Academy - St. Xavier", "2 HOUR DELAY"),
        ("Pryor Public Schools", "CLOSED"),
    ]


def test_nonstop_section_cards() -> None:
    cards = cowles.parse(_body("lists/nonstop-cards-20210306.html"))
    assert cards.variant == cowles.CARDS
    assert [row.name for row in cards.rows] == [
        "Dodson Public Schools closed indefinitely due to positive COVID-19 cases"
    ]
    empty = cowles.parse(_body("lists/nonstop-cards-20201124.html"))
    assert (empty.variant, empty.state) == (cowles.CARDS, ListingState.EMPTY)


def test_orange_banner_slider_reads_the_ian_closing() -> None:
    listing = smartsites.parse(_body("sharpschool/orange-20220928.html"))
    assert listing.variant == sharpschool.BANNER_VARIANT
    slide = listing.rows[0]
    assert (slide.name, slide.status) == (
        "Hurricane Ian",
        "All Schools/District Offices Closed Wednesday, Thursday and Friday",
    )
    assert notices.row_qualifies(slide.name, slide.status, listing.variant)
    milton = smartsites.parse(_body("sharpschool/orange-20241009.html"))
    assert [(row.name, row.status) for row in milton.rows] == [
        ("Hurricane Milton", "Click here for updated severe weather information.")
    ]


def test_a_deferred_homepage_showing_closings_reads_them_beside_its_file() -> None:
    river = apptegy_parse(_body("sharpschool/indian-river-20201108.html"))
    assert (river.variant, river.state) == ("sharpschool-homepage", ListingState.POPULATED)
    assert river.also_loads == (sharpschool.SERVICE_PATH,)
    assert all(row.extra == {"section": homepage.PAGE_TEXT} for row in river.rows)
    proving = [
        row
        for row in river.rows
        if notices.row_qualifies(row.name, row.status, river.variant, section="page-text")
    ]
    assert proving
    san_benito = finalsite.parse(_body("finalsite/san-benito-20260125.html"))
    assert san_benito.also_loads == ("/fs/pages/2/page-pops",)
    assert san_benito.rows[0].name == "Delayed start on Monday, January 26th"
    # A homepage showing no closing still defers to its file.
    plain = finalsite.parse(_body("finalsite/davis-20240202.html"))
    assert (plain.state, plain.follows) == (ListingState.DEFERRED, ("/fs/pages/2/page-pops",))


def test_page_text_beside_an_alert_and_text_alone() -> None:
    robstown = edlio.parse(_body("edlio/robstown-20250121.html"))
    assert robstown.variant == edlio.VARIANT
    assert [row.name for row in robstown.rows] == [
        "Robstown ISD Schools Closed Tuesday Due to Inclement Weather"
    ]
    united = smartsites.parse(_body("homepage/united-20260126.html"))
    assert united.variant == homepage.TEXT_VARIANT
    assert united.rows[0].name == "UPDATED: Two-Hour Delayed Start for Monday & Tuesday"
    # SYNTHETIC: a page in no known form, showing nothing, holds no list of its own.
    nothing = homepage.other_form("<html><body><p>Welcome back!</p></body></html>")
    assert (nothing.state, nothing.follows) == (ListingState.DEFERRED, ())
    with pytest.raises(ShapeError):
        homepage.other_form('{"alerts": []}')
    # A JSON answer gets no page text.
    answer = Listing(variant="x", state=ListingState.EMPTY, rows=())
    assert homepage.with_page_text(answer, '{"a": "Schools closed Monday due to snow"}') is answer


def test_tv_page_shells_of_older_templates() -> None:
    liferay = tegna.parse(_body("lists/kbmt-liferay-20170621.html"))
    assert (liferay.variant, liferay.state, liferay.follows) == (
        tegna.LIFERAY_PAGE,
        ListingState.DEFERRED,
        (),
    )
    subindex = tegna.parse(_body("lists/kfmb-subindex-20190406.html"))
    assert subindex.variant == tegna.SUBINDEX_PAGE
    facade = sinclair.parse(_body("lists/kmph-facade-20201026.html"))
    assert facade.follows == ("/resources/ftptransfer/kmph/closings/closings.html",)
    # SYNTHETIC: a subindex page whose settings do not say it shows closings is unknown.
    bare = b'<html><body data-model-metadata="{&quot;contentType&quot;: &quot;subindex&quot;}">'
    with pytest.raises(ShapeError):
        tegna.parse(bare + b"</body></html>")


# --- Utah's district homepages --------------------------------------------------------------


def test_utah_district_fixtures() -> None:
    granite = district_homepage.parse(_body("district/granite-live-20261005.html"))
    assert granite.follows == (district_homepage.GRANITE_FILE,)
    washington = district_homepage.parse(_body("district/washington-live-20261005.html"))
    assert washington.follows == (district_homepage.WCSD_FILE,)
    alerts = district_homepage.parse(_body("district/washington-alerts-live-20261005.json"))
    (alert,) = alerts.rows
    assert (alert.name, alert.extra["alert_id"], alert.extra["type"]) == (
        "NEW STUDENT REGISTRATION",
        96,
        "information",
    )
    assert not notices.row_qualifies(alert.name, alert.status, alerts.variant)
    empty = district_homepage.parse(_body("district/granite-en-live-20261005.json"))
    assert (empty.variant, empty.state) == (district_homepage.ANSWER_EMPTY, ListingState.EMPTY)
    provo = district_homepage.parse(_body("district/provo-live-20261005.html"))
    assert (provo.variant, provo.state) == (district_homepage.ALERTS, ListingState.EMPTY)
    for name in ("district/jordan-live-20261005.html", "district/canyons-live-20261005.html"):
        page = district_homepage.parse(_body(name))
        assert (page.variant, page.state) == (district_homepage.TEXT, ListingState.EMPTY)
    # Granite's homepage of a snow day: the loader page reads its own closing line and
    # still loads the file; the line names no weather, so it does not prove the channel.
    snow_day = district_homepage.parse(_body("district/granite-20230222.html"))
    assert (snow_day.variant, snow_day.state) == (district_homepage.LOADER, ListingState.POPULATED)
    assert snow_day.also_loads == (district_homepage.GRANITE_FILE,)
    (line,) = snow_day.rows
    assert line.name.startswith("Distance Learning Day for Granite School District")
    assert line.extra["section"] == homepage.PAGE_TEXT
    assert not notices.row_qualifies(
        line.name, line.status, snow_day.variant, section=homepage.PAGE_TEXT
    )


def test_utah_synthetic_answers() -> None:
    # SYNTHETIC: a WordPress REST list of one emergency notification.
    post = {
        "id": 7,
        "date": "2023-02-22T05:30:00",
        "date_gmt": "2023-02-22T12:30:00",
        "modified_gmt": "2023-02-22T12:45:00",
        "link": "https://synthetic-granite.test/en/7",
        "title": {"rendered": "Schools Closed Wednesday, Feb. 22 &#8211; Snow"},
        "excerpt": {"rendered": "<p>All schools are closed today due to heavy snow.</p>"},
    }
    listing = district_homepage.parse(json.dumps([post]).encode())
    (row,) = listing.rows
    assert listing.variant == district_homepage.WP_REST
    assert (row.name, row.status, row.updated_text) == (
        "Schools Closed Wednesday, Feb. 22 \u2013 Snow",
        "All schools are closed today due to heavy snow.",
        "2023-02-22T12:45:00",
    )
    assert notices.row_qualifies(row.name, row.status, listing.variant)
    # SYNTHETIC: Provo's alerts section holding one alert.
    page = (
        b"<html><body><section class='alerts'><div class='alert'><h2>Snow Day</h2>"
        b"<p>Provo schools are closed Thursday.</p></div></section></body></html>"
    )
    provo = district_homepage.parse(page)
    assert [(row.name, row.status) for row in provo.rows] == [
        ("Snow Day", "Snow Day Provo schools are closed Thursday.")
    ]
    for bad in (b'{"alerts": []}', b"[{}]", b"\x00\x01"):
        with pytest.raises(ShapeError):
            district_homepage.parse(bad)


def test_the_page_check_accepts_its_file_named_beside_a_page_of_its_own() -> None:
    station = REGISTRY.stations["finalsite-san-benito-tx"]
    check = station.page_check
    assert isinstance(check, PageCheck)
    loads = list(check.loads)
    assert fetch.page_check_mismatch(station, loads) is None
    assert fetch.page_check_mismatch(station, [], loads) is None
    assert fetch.page_check_mismatch(station, []) is not None
    assert fetch.page_check_mismatch(station, [], ["https://synthetic.test/other"]) is not None


def test_an_older_finalsite_template_without_the_live_class_is_read() -> None:
    gulf = finalsite.parse(_body("finalsite/gulf-shores-20191019.html"))
    assert (gulf.variant, gulf.state) == ("finalsite-homepage-pops", ListingState.POPULATED)
    assert gulf.rows[0].name == "GSCS Severe Weather Update"
    # SYNTHETIC: a page in Finalsite's editor stays refused.
    editing = b'<html><body data-pageid="2" class="fsHasHeader fsComposeMode"></body></html>'
    with pytest.raises(ShapeError, match="not a published page"):
        finalsite.parse(editing)


def test_the_announcements_region_is_an_element_not_a_word_in_a_script() -> None:
    # SYNTHETIC: Saraland's theme script names the class; the page has no such region.
    script = '<script>if ($(".cs-important-announcements-outer").length) {}</script>'
    assert not schoolwires.holds_announcements(f"<html><body>{script}</body></html>")
    region = '<div class="x cs-important-announcements-outer" data-pmi-id="1"></div>'
    assert schoolwires.holds_announcements(f"<html><body>{region}</body></html>")


def test_a_page_s_own_furniture_is_no_closing() -> None:
    for line in (
        "ScHOOL CLOSURES - YESTERDAY, TODAY, AND IN THE FUTuRE",
        "This page is dedicated to listing school closures across Santa Cruz County due to "
        "emergencies and/or events that school districts share with the County Office.",
    ):
        assert not closure_text.is_closing(line)


@pytest.mark.parametrize(
    ("body", "empty"),
    [
        # Real: the archive's replays of Palm Beach's page pops (2025-01-05) and
        # Weslaco's (2026-02-27), brotli streams of an empty answer, whole.
        (b"3", True),
        (b"c\x00\x03", True),
        # SYNTHETIC: the two other one-byte empty streams, and what is not one.
        (b"\x06", True),
        (b";", True),
        (b"33", False),
        (b"3\x00", False),
        (b"0", False),
        (b"[]", False),
        (b"", False),
        (b"\x1b\x03\x00\xf8\xa5\x40\x02", False),
    ],
)
def test_an_empty_brotli_stream_is_recognized(body: bytes, empty: bool) -> None:
    assert body_module.empty_brotli(body) is empty


def test_a_brotli_empty_page_pops_answer_is_the_empty_answer() -> None:
    for body in (b"3", b"c\x00\x03"):
        listing = finalsite.parse(body)
        assert (listing.variant, listing.state) == (finalsite.NONE, ListingState.EMPTY)


# --- the captures the check of 2026-10-05 11:02 UTC still found misread ---------------------


def test_sublette_road_conditions_and_hemet() -> None:
    # Sublette #9's homepage of 2017 (before its Edlio site), read as text: its late start
    # names road conditions, which prove it.
    sublette = edlio.parse(_body("homepage/sublette-9-20170203.html"))
    assert (sublette.variant, sublette.state) == (homepage.TEXT_VARIANT, ListingState.POPULATED)
    assert any(
        notices.row_qualifies(row.name, row.status, sublette.variant, section=homepage.PAGE_TEXT)
        and "road conditions" in row.status
        for row in sublette.rows
    )
    # Hemet's Edlio homepage of 2023-03-02: the alert names the weather.
    hemet = apptegy_parse(_body("edlio/hemet-20230302.html"))
    assert hemet.variant == edlio.VARIANT
    first = hemet.rows[0]
    assert first.name == "Idyllwild and Hamilton Schools Closed 3/2/23"
    assert notices.row_qualifies(first.name, first.status, hemet.variant)


def test_a_capture_the_archive_cut_off_is_cut_not_misread() -> None:
    # SYNTHETIC bodies: a page cut off at the archive's 1 MiB mid-script, and a whole page
    # of the same size.
    head = b"<html><body><p>Frenchtown</p><script>window.__NUXT__=(function(a){return {"
    cut = head + b"x" * (archive.ARCHIVE_CUT - len(head))
    whole = cut[: -len(b"</body></html>")] + b"</body></html>"
    assert archive.cut_off(cut)
    assert not archive.cut_off(whole)
    assert not archive.cut_off(cut[:-1])
    when = datetime(2023, 12, 2, 19, 31, 14, tzinfo=UTC)

    def failure(reason: str) -> SourceHealth:
        return SourceHealth(
            source_id="apptegy-frenchtown-mt",
            url="https://frenchtown.test/",
            checked_at=when,
            status=HealthStatus.ERROR,
            rows=0,
            reason=reason,
            sha256="0" * 64,
        )

    found = gate.read_captures(
        [],
        [
            failure(f"{archive.CUT_OFF}: the archive holds only the first 1,048,576 bytes"),
        ],
    )
    assert found == {("20231202193114", "frenchtown.test/"): "cut"}
    refused = gate.read_captures([], [failure("unrecognized shape: not a page")])
    assert set(refused.values()) == {"error"}
    assert "cut" in gate.BLIND_STATES


# --- what the second pass of round 3 found: hidden sliders, tickers, weather status -------


def test_an_aria_hidden_slider_and_a_named_storm_s_closing_are_read() -> None:
    # Seminole's homepage of 2022-11-10: its slider is marked aria-hidden="true" but is
    # what a visitor sees; Madison's district news of 2024-08-09: "Hurricane Debby Closure".
    seminole = smartsites.parse(_body("homepage/seminole-20221110.html"))
    assert [row.name for row in seminole.rows] == [
        "Tropical Storm Nicole Update: District & School Closures"
    ]
    madison = apptegy_parse(_body("homepage/madison-20240809.html"))
    assert [row.name for row in madison.rows] == ["Hurricane Debby Closure"]
    for listing in (seminole, madison):
        row = listing.rows[0]
        assert row.extra["section"] == homepage.PAGE_TEXT
        assert notices.row_qualifies(
            row.name, row.status, listing.variant, section=homepage.PAGE_TEXT
        )
    # SYNTHETIC: an aria-hidden slider's text is read; a named storm's road closures are not
    # a closing.
    hidden = b"<html><body><div aria-hidden='true'><h1>Schools closed Monday for snow</h1></div>"
    assert closure_text.page_lines(hidden + b"</body></html>") == ["Schools closed Monday for snow"]
    assert closure_text.is_closing("Hurricane Milton Closures")
    assert not closure_text.is_closing("Hurricane Ian road closures")


def test_a_district_s_weather_status_for_a_day_is_read_but_does_not_prove() -> None:
    # Pocatello's homepage of 2022-01-05 and Okaloosa's of 2019-10-19 (Tropical Storm
    # Nestor): schools open, for the weather, on a named day.
    pocatello = finalsite.parse(_body("homepage/pocatello-20220105.html"))
    assert [row.name[:60] for row in pocatello.rows] == [
        "School will be in session and follow regular schedules at al"
    ]
    okaloosa = apptegy_parse(_body("homepage/okaloosa-20191019.html"))
    assert [row.name[:40] for row in okaloosa.rows] == [
        "Schools will be in session on Friday. In",
        "Weather Alert: Tropical Cyclone 16 — Sch",
    ]
    for listing in (pocatello, okaloosa):
        for row in listing.rows:
            assert closure_text.is_notice(row.status)
            assert notices.page_text_status(row.status)
            # Read as the district's status, but an open day is no closing: it proves
            # nothing (the gate of 2026-10-13).
            assert not notices.row_qualifies(
                row.name, row.status, listing.variant, section=homepage.PAGE_TEXT
            )
    # Lines as captures showed them that are not a status for a day: Salt Lake City's
    # policy (2019-12-03), Durham's (2024), a survey (Palm Springs, 2024).
    for line in (
        "As we approach winter and the stormy conditions that come with it, Salt Lake City "
        "School District schools will be open on all regularly scheduled school days unless "
        "circumstances create health or safety issues.",
        "All Durham Unified Schools will be open in the event of a power outage.",
        "PSUSD's Winter 2024 Panorama Surveys are now open!",
    ):
        assert not notices.page_text_status(line)
        assert not closure_text.is_notice(line)
    # SYNTHETIC: a game postponed for the weather is not the schools' status.
    assert not notices.page_text_status("Football game Friday postponed due to weather")
    # A TV station's page is not checked for weather status lines.
    status = closure_text.Line("Schools will be open Friday despite the snow", notice=True)
    found, kept = closure_text.outcome(
        closure_text.ReadOf("empty", "synthetic"), [status], teasers=True
    )
    assert (found, kept) == ("clean", [])
    found, kept = closure_text.outcome(closure_text.ReadOf("empty", "synthetic"), [status])
    assert found == "missed"


def test_a_closing_that_names_the_snow_by_what_it_does_proves() -> None:
    # Lander's homepage of 2023-01-02 (Fremont County School District #1), the eve of the
    # snow day its later notes call "the snow day that occurred on January 3".
    lander = apptegy_parse(_body("homepage/lander-20230102.html"))
    row = lander.rows[0]
    assert row.name == (
        "Lander Schools will not have school on Tuesday, January 3, 2023 to allow crews to "
        "clear routes."
    )
    assert notices.page_text_closing(row.status)
    # Alpena's homepage of 2023-02-15: "APS Schools Closed - Dangerously Low Wind
    # Temperatures".
    assert closure_text.is_closing("APS Schools Closed - Dangerously Low Wind Temperatures")
    assert notices.page_text_closing("APS Schools Closed - Dangerously Low Wind Temperatures")


def test_a_menu_s_entries_are_not_read_but_its_ticker_is() -> None:
    # SYNTHETIC, in the shape of Okaloosa's header of 2019-10-17: a <nav> holding the
    # district's menu and its newswire.
    page = (
        b"<html><body><header><nav><ul><li><a href='/w'>Inclement Weather Delay Schedule</a>"
        b"</li></ul><button>Snow Days</button><a href='/d'>Snow Days</a>"
        b"<div class='newswire'><a href='/node/946'>Schools will be in session on Friday. "
        b"In expectation of deteriorating conditions Friday evening, all extracurricular "
        b"activities are cancelled. We will continue to monitor weather conditions.</a></div>"
        b"</nav></header></body></html>"
    )
    lines = closure_text.page_lines(page)
    assert len(lines) == 1
    assert lines[0].startswith("Schools will be in session on Friday.")
    assert closure_text.is_notice(lines[0])


@pytest.mark.parametrize(
    ("lines", "pairs"),
    [
        # Okaloosa's slider of 2019-10-17: a title and its caption.
        (
            [
                "Weather Alert: Tropical Cyclone 16",
                "Schools are in session Friday. After school activities for Friday & "
                "Saturday are cancelled…",
            ],
            1,
        ),
        # A calendar's date over its entry (Pocatello, 2022).
        (["Feb 16", "President's Day - No School"], 0),
        # A posting stamp over a policy (Salt Lake City, 2019-12-03).
        (
            [
                "Posted: Tue. 12-03-2019 - 10:25 AM",
                "As we approach winter and the stormy conditions that come with it, schools "
                "will be open on all regularly scheduled school days",
            ],
            0,
        ),
        # A board meeting's notice over a link to the snow day procedures (Darby, 2022).
        (
            [
                "There will be a School Board Meeting on January 9th at 6:00pm. Agenda",
                "Snow Day Procedures and Process",
            ],
            0,
        ),
        # Each line already says it alone.
        (["Snow update", "Schools closed Monday due to snow"], 0),
    ],
)
def test_a_title_and_the_line_after_it_are_read_together_only_when_they_must_be(
    lines: list[str], pairs: int
) -> None:
    found = closure_text.with_pairs(lines)
    joined = [line for line in found if closure_text.PAIR_JOIN in line]
    assert len(joined) == pairs
    assert [line for line in found if closure_text.PAIR_JOIN not in line] == lines


def test_a_description_of_how_closings_are_announced_is_no_notice() -> None:
    # Missoula's announcements app (2022-02-01 to 03-05) and Clark County's homepage of
    # 2019-12-12, as their captures showed them: standing descriptions, not notices.
    missoula = (
        "Notifying students and staff about severe weather-related school closures or delays."
    )
    assert not notices.announces_closing(missoula)
    assert not notices.page_text_closing(missoula)
    assert not notices.page_text_proves(missoula)
    recess = (
        "Cold Weather Recess With cold weather approaching, we wanted to remind all of our "
        "elementary students and parents of our recess policy."
    )
    assert not notices.announces_closing(recess, "Clark County School District 161")
    # A dated notice that names its procedure still qualifies; a weather status that keeps
    # the schools open does not (Bozeman's homepage page pop of 2024-01-12).
    assert notices.announces_closing(
        "Per our inclement weather procedures, all schools are closed Monday, Jan. 15."
    )
    assert not notices.announces_closing(
        "Friday, January 12, ALL BSD7 schools are OPEN and busses are running regular schedules.",
        "Cold Weather Update",
    )


def test_an_article_s_question_is_no_status() -> None:
    # Murray's homepage of 2022-12-05: a news item's title and its date.
    title = "Why Do Schools Try to Stay Open in Bad Weather?"
    assert not notices.page_text_status(f"{title} — February 27, 2023")
    assert closure_text.with_pairs([title, "February 27, 2023"]) == [title, "February 27, 2023"]


def test_two_inline_runs_side_by_side_are_two_words() -> None:
    # Citrus' homepage slide of 2020-11-13, as its markup wrote it: a title and a summary
    # in two <span> elements. Read apart, the summary is a teaser ("The latest on school
    # closures"), which proves nothing without a day.
    slide = (
        b"<div class='main-text'><span class='title'>Storm Update: Hurricane Eta</span>"
        b"<span class='summary'>The latest on school closures</span></div>"
    )
    assert closure_text.page_lines(slide) == [
        "Storm Update: Hurricane Eta The latest on school closures"
    ]
    assert not notices.page_text_proves("Storm Update: Hurricane Eta The latest on school closures")
    # SYNTHETIC: a word split by an inline element stays one word.
    assert closure_text.page_lines(b"<p>Schools <b>clo</b>sed Monday for snow.</p>") == [
        "Schools closed Monday for snow."
    ]


def test_the_audit_lists_what_the_check_excused() -> None:
    # SYNTHETIC page: a menu entry, a heading, a holiday and a notice the read holds.
    page = (
        b"<html><body><nav><ul><li><a href='/s'>Snow Days</a></li></ul></nav>"
        b"<h2>Weather Closures</h2><p>Winter Break - No School</p>"
        b"<p>Schools closed Monday due to snow.</p><script>var a='closed for snow';</script>"
        b"</body></html>"
    )
    lines = closure_text.broad_lines(page)
    assert lines == [
        "Snow Days",
        "Weather Closures",
        "Winter Break - No School",
        "Schools closed Monday due to snow.",
    ]
    sha = "0" * 64
    blocks = closure_text.closing_blocks(page)
    read = closure_text.ReadOf(
        "populated", "synthetic", (_row("Schools closed Monday due to snow."),)
    )
    found, kept = closure_text.outcome(read, blocks)
    assert found == "read"
    check = closure_text.CaptureCheck(
        "synthetic-a",
        "https://synthetic-a.test/",
        "2025-01-06T12:00:00Z",
        sha,
        read,
        found,
        tuple(kept),
    )
    result = closure_text.audit([check], {sha: lines})
    sources = result["sources"]
    assert isinstance(sources, dict)
    entry = sources["synthetic-a"]
    assert isinstance(entry, dict)
    assert entry["captures"] == 1
    listed = entry["lines"]
    assert isinstance(listed, list)
    assert [item["text"] for item in listed if isinstance(item, dict)] == [
        "Snow Days",
        "Weather Closures",
        "Winter Break - No School",
    ]
    # NBC Los Angeles' empty state is the page's own sentence: excused, and listed.
    nbc = (
        "But don't worry, we update this page regularly so you'll be the first to know if "
        "your school is closing or will have delays due to bad weather."
    )
    assert closure_text.broad_lines(f"<p>{nbc}</p>".encode()) == [nbc]
    assert not closure_text.is_closing(nbc)


def test_an_older_site_alert_module_is_the_district_s_channel() -> None:
    # Calhoun's homepage of 2018-10-11, the day after Hurricane Michael's landfall: its
    # site alert module held the closing posted on October 8.
    calhoun = smartsites.parse(_body("homepage/calhoun-20181011.html"))
    assert calhoun.variant == homepage.SITE_ALERT_VARIANT
    assert [row.name for row in calhoun.rows] == [
        "School Canceled Tuesday, Wednesday, and Thursday"
    ]
    row = calhoun.rows[0]
    assert "section" not in row.extra  # a channel row, read by the channel rule
    assert notices.row_qualifies(row.name, row.status, calhoun.variant)
    assert not notices.page_text_closing(row.status)  # as page text it would not prove
    # SYNTHETIC: a module with no alert is the empty channel.
    empty = homepage.site_alerts(
        "<html><body><div class='module' id='alerts'><div class='site-alert'></div></div>"
        "</body></html>"
    )
    assert empty is not None
    assert empty.state is ListingState.EMPTY
    assert homepage.site_alerts("<html><body><p>Hello</p></body></html>") is None

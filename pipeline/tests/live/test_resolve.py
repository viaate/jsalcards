"""Resolve: interval dating, zones, gates, boards, the reuse of derivations and expansion."""

from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from live.world import (
    ALPHA,
    ALPHA_DISTRICT,
    ALPHA_SCHOOL,
    CHICAGO,
    DENVER,
    VERSION,
    World,
    accepted,
    at,
    directory,
    district_schools,
    lit,
    reasons,
    refused,
    row,
    station,
)
from snowlight.listed.build import GUARD_REASON
from snowlight.listed.located import Place, Verdict
from snowlight.live import resolve as resolve_module
from snowlight.live.guards import Rules, Withheld
from snowlight.live.ledger import Outcome, seen_row
from snowlight.live.resolve import (
    CachedReader,
    CommittedMatch,
    Derived,
    LiveDirectory,
    board_date,
    matcher_fn,
    previous_school_day,
    samples,
)
from snowlight.sources.stations.model import RawRow

SOURCE = "gray-synthetic"


def _warm(world: World, *, source: str = SOURCE) -> None:
    """A read on the school day before (Monday 2026-11-16, local evening)."""
    world.read(at("2026-11-17 02:00"), [], source=source)


def _row_reason(world: World) -> list[str | None]:
    return reasons(world.resolve())


# --- interval dating (T2, T2b, T5) ------------------------------------------------------------


def test_samples_cover_every_quarter_and_half_hour() -> None:
    lo, hi = at("2026-11-17 10:50"), at("2026-11-17 11:40")
    found = samples(lo, hi, [CHICAGO])
    assert found[0] == lo
    assert found[-1] == hi
    assert at("2026-11-17 11:00") in found
    assert at("2026-11-17 11:30") in found
    assert at("2026-11-17 11:05") in found
    assert at("2026-11-17 11:20") in found
    assert found == sorted(set(found))
    assert samples(lo, lo, [CHICAGO]) == [lo]


def test_t2_a_warm_closed_never_lights_a_later_day() -> None:
    world = World()
    _warm(world)
    world.read(at("2026-11-17 11:05"), [])
    world.read(at("2026-11-17 11:10"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-17 11:11"))) == {(0, "2026-11-17"): "CLOSED"}
    for later in ("2026-11-18 11:00", "2026-11-20 11:00"):
        world.read(at(later), [row(ALPHA_SCHOOL)])
        merged = world.publish(at(later) + timedelta(minutes=1))
        assert lit(merged) == {}
        assert merged.withheld.get("past_day") == 1


def test_t2b_an_overnight_outage_dates_a_bare_status_but_a_day_long_one_does_not() -> None:
    world = World()
    _warm(world)
    world.read(at("2026-11-17 04:00"), [])  # Monday 22:00 local
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL)])  # Tuesday 05:00 local
    assert lit(world.publish(at("2026-11-17 11:01"))) == {(0, "2026-11-17"): "CLOSED"}
    (closing,) = world.publish(at("2026-11-17 11:01")).closings
    assert closing.announced_at is None  # the interval is 7 hours: no watched time
    day_long = World()
    day_long.read(at("2026-11-16 11:00"), [])  # Monday 05:00 local
    day_long.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL)])
    assert _row_reason(day_long) == ["interval_disagrees"]
    assert lit(day_long.publish(at("2026-11-17 11:01"))) == {}


def test_an_interval_over_36_hours_is_withheld() -> None:
    world = World(rules=Rules(longest_interval=timedelta(hours=1)))
    world.read(at("2026-11-17 08:00"), [])
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL)])
    assert _row_reason(world) == ["interval_too_long"]


def test_t5_a_split_zone_school_lights_only_when_its_zones_agree() -> None:
    world = World()
    _warm(world)
    world.read(at("2026-11-17 13:00"), [])
    world.read(at("2026-11-17 13:05"), [row("SYNTHETIC Split School")])
    assert lit(world.publish(at("2026-11-17 13:06"))) == {(8, "2026-11-17"): "CLOSED"}
    split = World()
    _warm(split)
    split.read(at("2026-11-17 18:05"), [])  # 12:05 Central, 11:05 Mountain
    split.read(at("2026-11-17 18:10"), [row("SYNTHETIC Split School")])
    assert _row_reason(split) == ["zone_split"]


def test_a_school_with_no_known_zone_is_withheld() -> None:
    world = World()
    _warm(world)
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row("SYNTHETIC Nowhere School")])
    assert _row_reason(world) == ["zone_unknown"]


def test_addendum3_an_undated_row_needs_a_read_on_the_previous_school_day() -> None:
    world = World()
    world.read(at("2026-11-17 06:05"), [])  # Tuesday 00:05 local; nothing on Monday
    world.read(at("2026-11-17 06:10"), [row(ALPHA_SCHOOL), row(ALPHA_DISTRICT, "Closed Nov 17")])
    assert sorted(r or "" for r in _row_reason(world)) == ["", "stale_unproven"]
    assert lit(world.publish(at("2026-11-17 06:11"))) == {
        (0, "2026-11-17"): "CLOSED",
        (1, "2026-11-17"): "CLOSED",
    }
    assert previous_school_day(date(2026, 11, 16)) == date(2026, 11, 13)


# --- boards (T3) -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("row_date", "reason"),
    [("2026-09-20", "board_date"), ("2026-11-18", "board_date"), ("2026-11-17", None)],
)
def test_t3_a_board_row_lights_only_its_own_date(row_date: str, reason: str | None) -> None:
    world = World(stations={"gohsep-synthetic": station("gohsep-synthetic")})
    _warm(world, source="gohsep-synthetic")
    world.read(at("2026-11-17 11:00"), [], source="gohsep-synthetic")
    board = row(ALPHA_DISTRICT, row_date=row_date)
    world.read(at("2026-11-17 11:05"), [board], source="gohsep-synthetic")
    assert _row_reason(world) == [reason]
    expected = {} if reason else {(0, "2026-11-17"): "CLOSED", (1, "2026-11-17"): "CLOSED"}
    assert lit(world.publish(at("2026-11-17 11:06"))) == expected


def test_a_board_with_no_row_date_needs_a_fresh_row_stamp() -> None:
    world = World(stations={"flathead-synthetic": station("flathead-synthetic")})
    _warm(world, source="flathead-synthetic")
    world.read(at("2026-11-17 11:00"), [], source="flathead-synthetic")
    rows = [
        row(ALPHA_SCHOOL),
        row(ALPHA_DISTRICT, row_stamp=at("2026-11-17 11:02"), row_date="5:02 AM"),
    ]
    world.read(at("2026-11-17 11:05"), rows, source="flathead-synthetic")
    assert sorted(r or "" for r in _row_reason(world)) == ["", "board_date"]
    assert board_date("Tuesday, November 17th, 2026") == date(2026, 11, 17)
    assert board_date("11/17/2026") == date(2026, 11, 17)
    assert board_date("someday") is None


# --- reuse (T4) ------------------------------------------------------------------------------


def test_t4_a_304_reuses_the_derivation_and_a_version_bump_re_derives() -> None:
    world = World()
    _warm(world)
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)])
    first = world.resolve()
    assert first[0].counts["derived"] == 1
    calls = world.matcher.calls
    world.read(at("2026-11-17 11:10"), [row(ALPHA_SCHOOL)], outcome=Outcome.NOT_MODIFIED)
    again = world.resolve()
    assert again[0].counts["reused"] == 1
    assert world.matcher.calls == calls
    assert again[0].rows[0].derived == first[0].rows[0].derived
    world.version = "synthetic-f5-bumped"
    bumped = world.resolve()
    assert bumped[0].counts["derived"] == 1
    assert world.matcher.calls == calls + 1


def test_a_vanished_row_keeps_its_derivation_and_an_underived_one_gives_nothing() -> None:
    world = World()
    _warm(world)
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)])
    world.resolve()  # every pass resolves after its reads
    world.read(at("2026-11-17 11:10"), [])
    world.read(at("2026-11-17 11:15"), [])  # an emptied list counts once it repeats
    (result,) = world.resolve()[0].rows
    assert result.reused
    assert not result.present
    assert result.derived.claims
    world.version = "other"
    (result,) = world.resolve()[0].rows
    assert result.derived.withheld is Withheld.NOT_DERIVED  # a status is not kept across versions
    assert result.derived.claims == ()
    assert result.version.startswith(VERSION)  # the version it was derived under


def test_the_derivation_round_trips() -> None:
    world = World()
    _warm(world)
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_DISTRICT, "2 hour delay due to snow")])
    (result,) = world.resolve()[0].rows
    derived = result.derived
    assert Derived.from_json(derived.to_json()) == derived
    (claim,) = derived.claims
    assert (claim.kind, claim.shift_minutes, claim.clock_minute, claim.reason) == (
        "delayed",
        120,
        600,
        "Winter storm",
    )
    with pytest.raises(ValueError, match="object"):
        Derived.from_json([])


def test_the_cached_reader_reads_each_minute_once() -> None:
    calls: list[datetime] = []

    def reader(text: str, *, posted_at: datetime, tz: str) -> object:  # noqa: ARG001
        calls.append(posted_at)
        return text

    cached = CachedReader(reader)  # type: ignore[arg-type]
    for second in (1, 30, 59):
        cached("x", posted_at=datetime(2026, 11, 17, 11, 5, second, tzinfo=UTC), tz=CHICAGO)
    assert calls == [at("2026-11-17 11:05")]
    assert cached.calls == 1


# --- the reading gates (T6, T6b) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Activities cancelled", "not_status"),
        ("Closed [conf=0.7]", "weak"),
        ("Closed [conf=0.8]", None),
        ("Possible closing", "not_status"),
        ("SYNTHETIC words", "not_status"),
        ("Closed due to water main", "not_weather"),
        ("Closed - holiday", "not_weather"),
        ("Closed - teacher work day", "not_weather"),
        ("Closed due to snow and water main", None),
        ("Closed. Snow packet day, buses resume Wednesday", "wording"),
        ("Closed - SAT testing", "wording"),
        ("Closed Wednesday, 18th & 19th", "wording"),
        ("Closing rescinded", "note"),
    ],
)
def test_t6_the_reading_gates(text: str, reason: str | None) -> None:
    world = World()
    _warm(world)
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, text)])
    assert _row_reason(world) == [reason]
    assert bool(lit(world.publish(at("2026-11-17 11:06")))) == (reason is None)


def test_t6b_a_non_weather_row_stands_against_another_status() -> None:
    world = World(stations={SOURCE: station(), "nexstar-synthetic": station("nexstar-synthetic")})
    _warm(world)
    _warm(world, source="nexstar-synthetic")
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)])
    world.read(at("2026-11-17 11:06"), [], source="nexstar-synthetic")
    world.read(
        at("2026-11-17 11:10"),
        [row(ALPHA_SCHOOL, "Closed - water main")],
        source="nexstar-synthetic",
    )
    merged = world.publish(at("2026-11-17 11:11"))
    assert lit(merged) == {}
    assert merged.withheld["retracted"] == 1


# --- matching and expansion (T7a, T11, addendum 1) -------------------------------------------


def test_t7a_unaccepted_listings_are_queued_and_a_place_conflict_is_located() -> None:
    world = World()
    world.matcher.table["SYNTHETIC Lookalike"] = refused("ambiguous", best="x")
    world.matcher.table["SYNTHETIC Elsewhere"] = refused(GUARD_REASON, best="x")
    _warm(world)
    world.read(at("2026-11-17 11:00"), [])
    rows = [row("SYNTHETIC Unknown"), row("SYNTHETIC Lookalike"), row("SYNTHETIC Elsewhere")]
    world.read(at("2026-11-17 11:05"), rows)
    (resolved,) = world.resolve()
    assert sorted(r or "" for r in reasons([resolved])) == [
        "located",
        "rejected_match",
        "unmatched",
    ]
    assert sorted(query.name for query in resolved.unmatched) == [
        "SYNTHETIC Lookalike",
        "SYNTHETIC Unknown",
    ]


def test_matcher_fn_applies_the_place_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    outcome = accepted(direct=(ALPHA[0],))
    monkeypatch.setattr(resolve_module, "match_one", lambda _matcher, _query: outcome)

    class Gazetteer:
        verdict_value = Verdict.CONFLICT

        def verdict(self, *_args: object) -> Verdict:
            return self.verdict_value

    gazetteer = Gazetteer()
    match = CommittedMatch(object(), gazetteer, "gaz-synthetic")  # type: ignore[arg-type]
    placed = row(ALPHA_SCHOOL, places=(Place(state="TX"),))
    guarded = match(station(), placed)
    assert not guarded.accepted
    assert guarded.reason == GUARD_REASON
    gazetteer.verdict_value = Verdict.AGREES
    assert match(station(), placed).accepted
    assert match(station(), row(ALPHA_SCHOOL)) is outcome
    bare = matcher_fn(object())  # type: ignore[arg-type]
    assert bare(station(), placed) is outcome
    assert bare.version == "gaz-none"


def test_addendum1_a_district_row_never_lights_charters_or_virtual_schools() -> None:
    world = World()
    _warm(world)
    world.read(at("2026-11-17 11:00"), [])
    world.read(
        at("2026-11-17 11:05"), [row("SYNTHETIC Escambia County Public Schools", "Closed Tuesday")]
    )
    (resolved,) = world.resolve()
    drops = resolved.rows[0].derived.target_drops
    assert drops == {"district_excludes_charter": 1, "district_excludes_virtual": 1}
    assert lit(world.publish(at("2026-11-17 11:06"))) == {(6, "2026-11-17"): "CLOSED"}
    named = World()
    _warm(named)
    named.read(at("2026-11-17 11:00"), [])
    named.read(
        at("2026-11-17 11:05"), [row("SYNTHETIC Escambia Charter Academy", "Closed Tuesday")]
    )
    assert lit(named.publish(at("2026-11-17 11:06"))) == {(4, "2026-11-17"): "CLOSED"}


def test_alpha_district_lights_its_two_regular_schools_only() -> None:
    world = World()
    _warm(world)
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_DISTRICT)])
    assert lit(world.publish(at("2026-11-17 11:06"))) == {
        (0, "2026-11-17"): "CLOSED",
        (1, "2026-11-17"): "CLOSED",
    }


def test_a_district_row_naming_part_of_the_district_lights_none_and_stands_against() -> None:
    world = World(stations={SOURCE: station(), "nexstar-synthetic": station("nexstar-synthetic")})
    _warm(world)
    _warm(world, source="nexstar-synthetic")
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_DISTRICT)])
    world.read(at("2026-11-17 11:06"), [], source="nexstar-synthetic")
    world.read(
        at("2026-11-17 11:10"),
        [row(ALPHA_DISTRICT, "Closed - intermediate campus")],
        source="nexstar-synthetic",
    )
    merged = world.publish(at("2026-11-17 11:11"))
    assert lit(merged) == {}
    assert merged.withheld["retracted"] == 2


def test_out_of_state_section_and_unanchored_schools() -> None:
    world = World(stations={SOURCE: station(states=("MO",))})
    world.matcher.table["SYNTHETIC Name Only"] = accepted(direct=(ALPHA[1],), reason="name")
    _warm(world)
    world.read(at("2026-11-17 11:00"), [])
    world.read(
        at("2026-11-17 11:05"),
        [row(ALPHA_SCHOOL), row("SYNTHETIC Eastern School", section="Private Schools")],
    )
    assert sorted(r or "" for r in _row_reason(world)) == ["out_of_state", "section"]
    anchored = World()
    anchored.matcher.table["SYNTHETIC Name Only"] = accepted(direct=(ALPHA[1],), reason="name")
    anchored.matcher.table["SYNTHETIC Alpha High"] = accepted(direct=(ALPHA[1],), reason="name")
    _warm(anchored)
    anchored.read(at("2026-11-17 11:00"), [])
    anchored.read(at("2026-11-17 11:05"), [row("SYNTHETIC Name Only"), row("SYNTHETIC Alpha High")])
    assert sorted(r or "" for r in _row_reason(anchored)) == ["", "unanchored"]


def test_excluded_platforms_and_district_sources() -> None:
    world = World(
        stations={
            "edlio-synthetic": station("edlio-synthetic"),
            "hcoe-synthetic": station("hcoe-synthetic"),
            "coesheet-synthetic": station("coesheet-synthetic", leaids=("2000001",)),
            "unknown-synthetic": station("unknown-synthetic"),
        }
    )
    for source in world.stations:
        world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=source)
    assert set(_row_reason(world)) == {"excluded_platform"}


def test_t11_a_big_expansion_needs_a_strong_match() -> None:
    schools = district_schools("5000000", 150, 100)
    ids = tuple(school.record.id for school in schools)
    rules = Rules(breaker_limits={SOURCE: 100})
    weak = World(dir=directory(schools), rules=rules)
    weak.matcher.table["SYNTHETIC Big District"] = accepted(via=ids, reason="context")
    _warm(weak)
    weak.read(at("2026-11-17 11:00"), [])
    weak.read(at("2026-11-17 11:05"), [row("SYNTHETIC Big District")])
    assert _row_reason(weak) == ["big_expansion"]
    strong = World(dir=directory(schools), rules=rules)
    strong.matcher.table["SYNTHETIC Big District"] = accepted(via=ids, reason="alias", conf=0.96)
    _warm(strong)
    strong.read(at("2026-11-17 11:00"), [])
    strong.read(at("2026-11-17 11:05"), [row("SYNTHETIC Big District")])
    assert len(lit(strong.publish(at("2026-11-17 11:06")))) == 150


def test_a_school_the_directory_does_not_hold_is_counted() -> None:
    world = World()
    world.matcher.table["SYNTHETIC Ghost"] = accepted(direct=("999999999999",))
    _warm(world)
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row("SYNTHETIC Ghost")])
    (resolved,) = world.resolve()
    assert resolved.rows[0].derived.withheld is Withheld.UNMATCHED
    assert resolved.counts["target:not_in_directory"] == 1


def test_the_announced_time_rules() -> None:
    off = World(rules=Rules(watched_announce=None))
    _warm(off)
    off.read(at("2026-11-17 11:00"), [])
    off.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)])
    assert [c.announced_at for c in off.publish(at("2026-11-17 11:06")).closings] == [None]
    slow = World()
    _warm(slow)
    slow.read(at("2026-11-17 10:30"), [])
    slow.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)])
    assert [c.announced_at for c in slow.publish(at("2026-11-17 11:06")).closings] == [None]
    assert DENVER


@pytest.mark.parametrize(
    ("text", "days"),
    [
        ("School is open tomorrow", ["2026-11-18"]),
        ("Open today", ["2026-11-17"]),
        ("Open on time Wednesday", ["2026-11-18"]),
        ("Open Monday", ["2026-11-23"]),
        ("Open Nov 19", ["2026-11-19"]),
        ("Open 11/20", ["2026-11-20"]),
        ("Open Dec 25", []),
        ("Open 2/30", []),
        ("Open tonight", []),
        ("Open this week", []),
        ("Open. Updated Monday 5:00 AM", []),
    ],
)
def test_open_days_are_read_exactly(text: str, days: list[str]) -> None:
    found = resolve_module.open_days(text, date(2026, 11, 17))
    assert [day.isoformat() for day in found] == days


def test_the_directory_reads_the_schools_and_zones_tables() -> None:
    schools = pl.DataFrame(
        {
            "index": [0, 1],
            "id": ["200000100001", "200000100003"],
            "kind": ["public", "public"],
            "name": ["SYNTHETIC One", "SYNTHETIC Charter"],
            "district_id": ["2000001", "2000001"],
            "state": ["KS", "KS"],
            "county_fips": ["20091", "20091"],
            "lat": [38.9, 38.9],
            "lon": [-94.7, -94.7],
            "level": ["Elementary", "Middle"],
            "school_type": ["Regular School", "Regular School"],
            "charter": [False, True],
            "virtual": [None, "FULLVIRTUAL"],
            "status": ["Open", "Open"],
            "enrollment": [300, None],
            "grade_low": ["KG", "06"],
            "grade_high": ["05", "08"],
        }
    )
    zones = pl.DataFrame({"index": [0, 1], "zones": [[CHICAGO], []]})
    found = LiveDirectory.from_frames(schools, zones, "edition-x")
    assert found.edition == "edition-x"
    assert found.district_sizes == {"2000001": 2}
    one, charter = found.schools["200000100001"], found.schools["200000100003"]
    assert (one.index, one.zones, one.charter) == (0, (CHICAGO,), False)
    assert (charter.index, charter.zones, charter.charter) == (1, (), True)
    assert charter.record.virtual == "FULLVIRTUAL"
    assert charter.record.enrollment is None


def test_a_board_row_takes_its_row_date_field() -> None:
    raw = RawRow(
        source_id="gohsep-synthetic",
        fetched_at=at("2026-11-17 11:05"),
        raw_name="SYNTHETIC Parish",
        raw_status="Closed",
        raw_updated_text=None,
        raw_extra={"closure_date": "2026-11-17"},
    )
    seen = seen_row(raw, variant="synthetic", platform="gohsep", zone=CHICAGO)
    assert seen.row_date == "2026-11-17"
    assert seen.row_stamp is None

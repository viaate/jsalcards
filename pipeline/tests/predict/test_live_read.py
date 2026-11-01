"""The outcome-blind live labels (advisory-sane L1, Addendum A: O5 yes).

Every read, list, closing and storm here is made up for the tests (SYNTHETIC). The two real
codes (a Washington district's LEAID and the county it is in) only place the first fixture;
its reads, and its lists' capture counts, are invented: on the real coverage files the
county's list has one archive capture, so Methow is not covered on Oct 28 (see
:func:`test_methow_on_its_real_capture_count_is_not_covered`).
"""

import gzip
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from predict import world
from predict.test_learn import (
    CARRIED,
    CFG,
    DAY,
    KC_CARRIED,
    MONDAY,
    SHORT,
    WHOLE,
    Host,
    Source,
    built,
    learn_run,
    morning_of,
    snapshots_for,
)
from predict.test_retention import NOW as RETENTION_NOW
from predict.test_retention import FakeD1
from snowlight.live.evidence import AUDIT, LABELS, TRIALS, EvidenceStore
from snowlight.live.history import Change as LogChange
from snowlight.live.history import ChangeLog, Event, Shown
from snowlight.live.morning import MorningLog, Slot, slot_start
from snowlight.predict import cli, learn, read_cli
from snowlight.predict import live_read as live_read_module
from snowlight.predict.labels import LitStatus
from snowlight.predict.live_labels import Directory, Lit, Morning, StateSource, StationStats
from snowlight.predict.live_read import (
    BY_DATE_LISTS,
    DAYS_PER_RUN,
    LEFT,
    OPEN_LABEL,
    WARNING_CLASSES,
    Closing,
    Coverage,
    HandAudit,
    Label,
    ListStats,
    LiveCaptures,
    NotRead,
    Read,
    ReadDay,
    ReadReport,
    ReadRow,
    ReadRule,
    ReadSources,
    StateReadSource,
    Tier,
    Trial,
    _Storms,
    audit_of,
    beta_interval,
    closing_captures,
    closing_size,
    county_sources_of,
    gzip_json,
    label_read_day,
    labeled_days,
    lit_sources,
    live_captures,
    load_audiences,
    load_read_sources,
    populated_captures,
    read_day,
    read_new_days,
    read_set,
    report_of,
    trial_totals,
    trials_path,
    write_day,
)
from snowlight.predict.situations import WeatherClass, Window
from snowlight.schemas.stats import ReadAudit, ReadAuditDay, ReadClass
from snowlight.schemas.vocab import Reason, Status
from snowlight.sources.stations.registry import load_registry

RULE = ReadRule.of(CFG)

# --- the Methow fixture: one district, one county source ------------------------------------------

METHOW = "5305020"
OKANOGAN = "53047"
OCT28 = date(2026, 10, 28)
PACIFIC = "America/Los_Angeles"
WINDOW_PT = ("13:30", "14:00", "14:30", "15:00", "15:30", "16:00")
"""UTC slots of 06:30-09:30 Pacific daylight time (13:30Z to 16:30Z)."""


def one_district(leaid: str = METHOW, zone: str = PACIFIC) -> Directory:
    return Directory(
        districts=(leaid,),
        eligible=(np.array([0, 1], dtype=np.int64),),
        zones=(zone,),
        content="synthetic",
        stamp=world.STAMP,
    )


def stats_of(*sources: str) -> StationStats:
    return StationStats(
        captures=dict.fromkeys(sources, 10),
        median_rows=dict.fromkeys(sources, 10.0),
        placed=dict.fromkeys(sources, 1.0),
    )


def pt_morning(  # noqa: PLR0913 - every part a test sets
    reads: Mapping[str, Sequence[tuple[int, int, int]]],
    *,
    at: str = "14:00",
    health: int | None = 950,
    named: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    by: Mapping[str, Sequence[str]] | None = None,
    audience: Mapping[str, Mapping[str, date]] | None = None,
    market_of: Mapping[str, str] | None = None,
) -> Morning:
    """SYNTHETIC: Oct 28 06:30-09:30 PT shown under v1, ``reads`` in the ``at`` slot (07:00
    PT by default) with the given healthy share."""
    slots = {
        slot_start(OCT28, key): Slot(shown={"v1"}, health=health if key == at else 990)
        for key in WINDOW_PT
    }
    first = slots[slot_start(OCT28, at)] if at in WINDOW_PT else Slot(shown={"v1"})
    if at not in WINDOW_PT:
        slots[slot_start(OCT28, at)] = first
        first.health = health
    first.reads = {source: set(found) for source, found in reads.items()}
    first.by = {source: set(found) for source, found in (by or {}).items()}
    if named:
        first.named = {
            leaid: {d: set(kinds) for d, kinds in days.items()} for leaid, days in named.items()
        }
    markets = market_of or {"tegna-krem": "Spokane", "flashalert-spokane": "Spokane"}
    return Morning(
        day=OCT28,
        slots=slots,
        audience=audience or {},
        market_of=markets,
        stats=stats_of(*markets),
        prefix="v1",
    )


LIST_IDS = ("tegna-krem", "flashalert-spokane", "district-site", "tv", "radio", "paper")
"""SYNTHETIC lists, each given 10 archive captures of 10 rows (not their real counts)."""


def listed(coverage: Coverage) -> Coverage:
    """``coverage`` with every synthetic list holding 10 archive captures of 10 rows, and the
    registered five-capture minimum."""
    return replace(
        coverage,
        captures=dict.fromkeys(LIST_IDS, 10),
        rows=dict.fromkeys(LIST_IDS, (10,) * 10),
        min_captures=RULE.min_captures,
    )


COUNTY = listed(
    Coverage(county_sources={OKANOGAN: ("tegna-krem",)}, archive={}, county_of={METHOW: OKANOGAN})
)
DARK = Lit({}, frozenset())
SHORT_PEER = replace(COUNTY, rows={**COUNTY.rows, "flashalert-spokane": (4,) * 10})
"""SYNTHETIC: the FlashAlert list runs 4 rows when schools close (so 3 rows is whole)."""

WARNED: Final = ("5300001", "5300002", "5300003")
"""SYNTHETIC: three districts under a snow warning that our map lit closed."""
MARKETS: Final = {
    "tegna-krem": "Spokane", "flashalert-spokane": "Spokane", "cox-kiro": "Spokane", "tv": "KC",
}  # fmt: skip


def closing_of(
    coverage: Coverage,
    lit: AbstractSet[str] | Mapping[date, AbstractSet[str]] = frozenset(WARNED),
) -> Closing:
    """SYNTHETIC: each earlier day's warned districts our map lit (the same every day when
    ``lit`` is a set), all in the Pacific zone."""
    if isinstance(lit, Mapping):
        days = {when: frozenset(found) for when, found in lit.items()}
        zones = dict.fromkeys((leaid for found in days.values() for leaid in found), PACIFIC)
        return Closing(RULE, coverage, lambda when: days.get(when, frozenset()), zones)
    fixed = frozenset(lit)
    return Closing(RULE, coverage, lambda _when: fixed, dict.fromkeys(fixed, PACIFIC))


def counted(log: MorningLog, closing: Closing, day: date = OCT28, days: int = 366) -> LiveCaptures:
    """The record's counted days before ``day`` (lead ruling C2)."""
    return live_captures(log, day, days, closing, market_of=MARKETS, prefix="v1")


def record_on(  # noqa: PLR0913 - every part a test sets
    log: MorningLog,
    when: date,
    reads: Mapping[str, tuple[int, int, int]],
    *,
    by: Mapping[str, Sequence[str]] | None = None,
    stale: Sequence[str] = (),
    health: float | None = 0.95,
    at: str = "14:00",
    shown: str = "v1",
) -> None:
    """SYNTHETIC: one pass of ``when`` at ``at`` UTC (inside the read band)."""
    log.record(
        datetime.fromisoformat(f"{when.isoformat()}T{at}:00+00:00"), shown=shown, reads=reads,
        unknown=(), named={}, health=health, by=by or {}, stale=stale,
    )  # fmt: skip


def methow(  # noqa: PLR0913 - every part a test sets
    morning: Morning,
    *,
    coverage: Coverage = COUNTY,
    recent: Mapping[str, int] | None = None,
    lit: Lit = DARK,
    lit_by: Mapping[str, Mapping[str, datetime]] | None = None,
    weather: WeatherClass = WeatherClass.ADVISORY,
) -> tuple[Label, str | None, Tier | None]:
    found = label_read_day(
        OCT28,
        morning=morning,
        coverage=coverage,
        weather=[weather],
        lit=lit,
        directory=one_district(),
        rule=RULE,
        recent={"tegna-krem": 3} if recent is None else recent,
        lit_by=lit_by,
    )
    (row,) = found.rows
    return row.label, row.why, row.tier


def test_a_covered_unnamed_district_read_whole_is_unnamed_tier_b_and_counts_open() -> None:
    # 1: Methow, Oct 28: the county's proven list read whole at 07:00 PT (ten rows, none of
    # them Methow's), healthy; the map dark.
    found = label_read_day(
        OCT28,
        morning=pt_morning({"tegna-krem": [WHOLE]}),
        coverage=COUNTY,
        weather=[WeatherClass.ADVISORY],
        lit=DARK,
        directory=one_district(),
        rule=RULE,
        recent={"tegna-krem": 3},
    )
    (row,) = found.rows
    assert (row.label, row.why, row.tier) == (Label.UNNAMED, None, Tier.B)
    assert row.sources == ("tegna-krem",)
    assert (row.market, row.slot, row.health) == ("Spokane", "14:00", 950)
    assert OPEN_LABEL is Label.UNNAMED  # the owner's O5
    assert RULE.open_if_unnamed
    (advisory,) = found.audit.classes
    assert (advisory.weather, advisory.alerted, advisory.covered) == ("advisory", 1, 1)
    assert (advisory.read_b, advisory.unnamed, advisory.median_health) == (1, 1, 950)


def test_no_whole_read_in_the_window_gives_no_label() -> None:
    # 2: the only read is at 17:00Z (10:00 PT), after the window.
    assert methow(pt_morning({"tegna-krem": [WHOLE]}, at="17:00")) == (
        Label.NOT_READ, NotRead.NO_WHOLE_READ.value, None,
    )  # fmt: skip
    # A district no list may read is never read.
    alone = listed(Coverage(county_sources={}, archive={}, county_of={METHOW: OKANOGAN}))
    found = methow(pt_morning({"tegna-krem": [WHOLE]}), coverage=alone)
    assert found == (Label.NOT_READ, NotRead.NOT_COVERED.value, None)
    # A read the replay step would drop (a quarter of its rows not read) is not whole.
    dropped = methow(pt_morning({"tegna-krem": [(10, 10, 5)]}))
    assert dropped == (Label.NOT_READ, NotRead.DROPPED_READ.value, None)


def test_a_slot_under_the_healthy_share_gives_no_label() -> None:
    # 3: healthy share 0.85 at 07:00 PT, and no other read.
    assert methow(pt_morning({"tegna-krem": [WHOLE]}, health=850)) == (
        Label.NOT_READ, NotRead.UNHEALTHY.value, None,
    )  # fmt: skip
    assert methow(pt_morning({"tegna-krem": [WHOLE]}, health=900))[0] is Label.UNNAMED
    # A slot recorded before the share was (every slot up to 2026-10-30): never read.
    assert methow(pt_morning({"tegna-krem": [WHOLE]}, health=None)) == (
        Label.NOT_READ, NotRead.HEALTH_UNRECORDED.value, None,
    )  # fmt: skip


def test_a_list_with_no_recent_rows_reads_only_with_a_second_list() -> None:
    # 4: no populated read in the 14 days before, and no second list of the market.
    stale = methow(pt_morning({"tegna-krem": [WHOLE]}), recent={})
    assert stale == (Label.NOT_READ, NotRead.NOT_RECENT.value, None)
    # A second proven list of the market read whole too: read.
    both = listed(
        Coverage(
            county_sources={OKANOGAN: ("flashalert-spokane", "tegna-krem")},
            archive={},
            county_of={METHOW: OKANOGAN},
        )
    )
    morning = pt_morning({"tegna-krem": [(0, 0, 0)], "flashalert-spokane": [(0, 0, 0)]})
    assert methow(morning, coverage=both, recent={}) == (Label.UNNAMED, None, Tier.B)
    # ... but not one of another market.
    apart = pt_morning(
        {"tegna-krem": [WHOLE], "flashalert-spokane": [WHOLE]},
        market_of={"tegna-krem": "Spokane", "flashalert-spokane": "Seattle"},
    )
    assert methow(apart, coverage=both, recent={})[1] == NotRead.NOT_RECENT.value


def test_a_named_district_the_map_did_not_light_is_unknown() -> None:
    # 6: a row named Methow closed for the day (the map stayed dark): never open.
    named = pt_morning({"tegna-krem": [WHOLE]}, named={METHOW: {OCT28.isoformat(): ["closed"]}})
    assert methow(named) == (Label.UNKNOWN, "listed_unread", Tier.B)


def test_a_tier_a_list_wins_the_tier() -> None:
    # 7: the county's list (tier B) and a list that carries the district (tier A) both read.
    coverage = listed(
        Coverage(
            county_sources={OKANOGAN: ("tegna-krem",)},
            archive={"flashalert-spokane": frozenset({METHOW})},
            county_of={METHOW: OKANOGAN},
        )
    )
    morning = pt_morning({"tegna-krem": [WHOLE], "flashalert-spokane": [WHOLE]})
    recent = {"tegna-krem": 1, "flashalert-spokane": 1}
    assert methow(morning, coverage=coverage, recent=recent) == (Label.UNNAMED, None, Tier.A)
    # A district-level list (its own site) is neither tier.
    own = listed(
        Coverage(
            county_sources={},
            archive={"district-site": frozenset({METHOW})},
            county_of={METHOW: OKANOGAN},
            district_sites=frozenset({"district-site"}),
        )
    )
    found = methow(
        pt_morning({"district-site": [WHOLE]}), coverage=own, recent={"district-site": 1}
    )
    assert found[1] == NotRead.NOT_COVERED.value
    # The archive audiences hold codes only, no dates: every archive listing is before any
    # live day, so a list that carries the district is tier A on every live day.
    carried = listed(Coverage(
        county_sources={}, archive={"flashalert-spokane": frozenset({METHOW})},
        county_of={METHOW: OKANOGAN},
    ))  # fmt: skip
    found = methow(
        pt_morning({"flashalert-spokane": [WHOLE]}),
        coverage=carried,
        recent={"flashalert-spokane": 1},
    )
    assert found == (Label.UNNAMED, None, Tier.A)


LIT_AT = datetime(2026, 10, 28, 13, 50, tzinfo=UTC)
"""06:50 PT on Oct 28: inside Methow's window."""


def closed_lit(schools: Sequence[int]) -> Lit:
    return Lit({s: LitStatus(Status.CLOSED, Reason.WINTER_STORM) for s in schools}, frozenset())


def test_a_trial_is_recorded_only_for_a_lit_district() -> None:
    # 8: the map lit Methow closed from the KREM list's row; the FlashAlert list read it too.
    both = listed(
        Coverage(
            county_sources={OKANOGAN: ("flashalert-spokane", "tegna-krem")},
            archive={},
            county_of={METHOW: OKANOGAN},
        )
    )
    recent = {"tegna-krem": 2, "flashalert-spokane": 2}

    def trials(lit: Lit, by: Mapping[str, Sequence[str]]) -> list[tuple[str, Tier, bool]]:
        found = label_read_day(
            OCT28,
            morning=pt_morning(
                {"tegna-krem": [WHOLE], "flashalert-spokane": [WHOLE]},
                by=by,
                named={METHOW: {OCT28.isoformat(): ["closed"]}} if by else None,
            ),
            coverage=both,
            weather=[WeatherClass.ADVISORY],
            lit=lit,
            directory=one_district(),
            rule=RULE,
            recent=recent,
            lit_by={METHOW: {"tegna-krem": LIT_AT}},
        )
        return [(t.source, t.tier, t.named) for t in found.trials]

    lit = closed_lit([0, 1])
    # The lighting list gives no trial; the other names it (a hit) or not (a miss).
    hit = trials(lit, {"tegna-krem": [METHOW], "flashalert-spokane": [METHOW]})
    assert hit == [("flashalert-spokane", Tier.B, True)]
    assert trials(lit, {"tegna-krem": [METHOW]}) == [("flashalert-spokane", Tier.B, False)]
    # A district the map did not light gives none.
    assert trials(DARK, {}) == []
    # With no change log for the day the lighting lists are unknown: no trial at all.
    found = label_read_day(
        OCT28,
        morning=pt_morning({"tegna-krem": [WHOLE], "flashalert-spokane": [WHOLE]}),
        coverage=both, weather=[WeatherClass.ADVISORY], lit=lit, directory=one_district(),
        rule=RULE, recent=recent, lit_by=None,
    )  # fmt: skip
    assert found.trials == []
    assert [r.label for r in found.rows] == [Label.NO_SCHOOL]


def test_the_sensitivity_priors() -> None:
    assert RULE.sensitivity(Tier.A, 0, 0) == 0.9
    assert RULE.sensitivity(Tier.B, 0, 0) == 4 / 6
    assert RULE.sensitivity(Tier.B, 20, 18) == 22 / 26


# --- 5: the read set never looks at what was named or lit ---------------------------------------

LEAIDS = ("2900001", "2900002", "2900003")
SOURCES = ("tv", "radio", "paper")


@settings(max_examples=60, deadline=None)
@given(
    reads=st.dictionaries(
        st.sampled_from(SOURCES),
        st.lists(st.tuples(st.integers(0, 12), st.integers(0, 12), st.integers(0, 3)), max_size=2),
    ),
    health=st.one_of(st.none(), st.integers(800, 1000)),
    named=st.dictionaries(st.sampled_from(LEAIDS), st.sampled_from(["closed", "delayed", "?"])),
    by=st.dictionaries(st.sampled_from(SOURCES), st.sets(st.sampled_from(LEAIDS))),
    recent=st.dictionaries(st.sampled_from(SOURCES), st.integers(0, 2)),
    weather=st.lists(st.sampled_from([None, *WeatherClass]), min_size=3, max_size=3),
    stale=st.sets(st.sampled_from(SOURCES)),
)
def test_clearing_what_was_named_and_lit_leaves_the_read_set_unchanged(  # noqa: PLR0913, PLR0917
    reads: Mapping[str, list[tuple[int, int, int]]],
    health: int | None,
    named: Mapping[str, str],
    by: Mapping[str, set[str]],
    recent: Mapping[str, int],
    weather: list[WeatherClass | None],
    stale: set[str],
) -> None:
    clean = {s: [(rows, min(placed, rows), min(unread, rows)) for rows, placed, unread in found]
             for s, found in reads.items()}  # fmt: skip
    directory = Directory(
        districts=LEAIDS,
        eligible=tuple(np.array([i], dtype=np.int64) for i in range(3)),
        zones=("America/Chicago",) * 3,
        content="synthetic",
        stamp=world.STAMP,
    )
    coverage = listed(
        Coverage(
            county_sources={"29095": ("tv", "radio")},
            archive={"paper": frozenset({"2900003"})},
            county_of=dict.fromkeys(LEAIDS, "29095"),
        )
    )

    def morning(with_outcomes: bool, *, with_by: bool | None = None) -> Morning:
        found = morning_of(clean, audience={})
        for slot in found.slots.values():
            slot.health = health
        first = found.slots[slot_start(DAY, "13:00")]
        first.stale = set(stale)
        if with_outcomes:
            first.named = {leaid: {DAY.isoformat(): {kind}} for leaid, kind in named.items()}
        if with_outcomes if with_by is None else with_by:
            first.by = {s: set(found) for s, found in by.items()}
        return Morning(
            day=found.day,
            slots=found.slots,
            audience=found.audience,
            market_of={"tv": "KC", "radio": "KC", "paper": "KC"},
            stats=stats_of(*SOURCES),
            prefix="v1",
        )

    def reads_of(found: Morning) -> dict[str, Read | NotRead]:
        return read_set(
            found, directory=directory, coverage=coverage, recent=recent, rule=RULE,
            weather=weather,
        )  # fmt: skip

    # What each district was named and what the map lit never decide who is read.
    assert reads_of(morning(with_outcomes=True)) == reads_of(
        morning(with_outcomes=False, with_by=True)
    )
    # Whether a list named anything for the day enters on a warning-or-above morning only
    # (lead ruling B1.3, stale_populated); on every other morning it never does.
    if not any(klass in WARNING_CLASSES for klass in weather):
        assert reads_of(morning(with_outcomes=True)) == reads_of(morning(with_outcomes=False))


# --- the step -----------------------------------------------------------------------------------


class ReadingSource(Source):
    """SYNTHETIC: the S7-L test source with every slot healthy, the lists' recent rows and the
    lighting lists of the day."""

    def morning(self, day: date) -> Morning | str:
        found = super().morning(day)
        if isinstance(found, Morning):
            for slot in found.slots.values():
                slot.health = 960
        return found

    def captures(self, day: date, days: int, closing: Closing | None = None) -> LiveCaptures:  # noqa: ARG002
        return LiveCaptures(days={"tv": 4}, storm_rows={"tv": (10, 10, 10, 10)})

    def lit_by(self, day: date) -> Mapping[str, Mapping[str, datetime]] | None:
        return {"2900001": {"tv": datetime.combine(day, datetime.min.time(), tzinfo=UTC)}}


def coverage_kc() -> Coverage:
    model = world.model()
    return listed(
        Coverage(
            county_sources={},
            archive=CARRIED,
            county_of={k: v.county for k, v in model.districts.items() if v.county is not None},
        )
    )


def test_ready_days_are_labeled_once_and_frozen(tmp_path: Path) -> None:
    folder = tmp_path / "reads"
    shown_monday = world.timeline().model_copy(update={"day": MONDAY})
    source = ReadingSource({DAY: world.timeline(), MONDAY: shown_monday})
    snapshots = {**snapshots_for(DAY), **snapshots_for(MONDAY)}
    now = world.utc("2026-01-08T06:00:00")
    directory = learn.directory_of(built())
    run = read_new_days(
        folder, source, directory=directory, coverage=coverage_kc(),
        snapshots=snapshots, config=SHORT, now=now,
    )  # fmt: skip
    # The 7th is not over everywhere yet: it waits.
    assert run.added == [MONDAY, DAY]
    assert run.skipped == {"not over everywhere yet": 1}
    assert labeled_days(folder) == [MONDAY, DAY]
    found = read_day(folder, DAY)
    assert found is not None
    labels = {row.district: (row.label, row.why, row.tier) for row in found.rows}
    # The synthetic timeline lit 2900001 closed; the other carried districts were read dark
    # on a storm day while their market closed: unknown, never open.
    assert labels["2900001"] == (Label.NO_SCHOOL, None, Tier.A)
    assert labels["2900002"] == (Label.UNKNOWN, "absent_in_storm", Tier.A)
    # Districts no list carries are listed with why.
    assert labels["4900005"] == (Label.NOT_READ, "not_covered", None)
    # Every district the map lit no school, read or not (2900003 no list carries).
    assert found.no_school == ("2900001", "2900003")
    # The 6th knows which districts follow a closing on the 5th: every one the map lit no
    # school, read on the 5th or not (2900003 was never read).
    assert {r.district for r in found.rows if r.after} == {"2900001", "2900003"}
    # What the map showed on the 5th's school day before is not known: never a guess.
    monday = read_day(folder, MONDAY)
    assert monday is not None
    assert {r.after for r in monday.rows} == {None}
    # The lighting list gave no trial; no other list read the lit district.
    assert trials_path(folder, DAY).read_bytes() == b""
    # A rerun changes nothing (a labeled day is frozen).
    before = {p: p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}
    again = read_new_days(
        folder, source, directory=directory, coverage=coverage_kc(),
        snapshots=snapshots, config=SHORT, now=now + timedelta(hours=12),
    )  # fmt: skip
    assert again.added == []
    assert {p: p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()} == before
    # The public audit validates and holds whole counts only.
    audit = audit_of(folder, now)
    data = audit.to_json_bytes()
    assert ReadAudit.from_json_bytes(data) == audit
    assert [d.day for d in audit.days] == [MONDAY, DAY]
    assert not [v for v in _numbers(json.loads(data)) if not isinstance(v, int)]
    assert trial_totals(audit)[Tier.A] == (0, 0)
    (snow,) = (c for c in audit.days[1].classes if c.weather == "snow_warning")
    assert (snow.alerted, snow.covered, snow.read_a, snow.lit_no_school) == (5, 3, 3, 1)
    assert (snow.unknown_absent, snow.not_covered) == (2, 2)


def _numbers(value: object) -> list[object]:
    if isinstance(value, dict):
        return [n for item in value.values() for n in _numbers(item)]
    if isinstance(value, list):
        return [n for item in value for n in _numbers(item)]
    return [value] if isinstance(value, int | float) and not isinstance(value, bool) else []


def test_a_day_whose_record_is_not_ready_waits(tmp_path: Path) -> None:
    folder = tmp_path / "reads"
    shown_monday = world.timeline().model_copy(update={"day": MONDAY})
    source = ReadingSource({DAY: world.timeline(), MONDAY: shown_monday}, unread=[DAY])
    run = read_new_days(
        folder, source, directory=learn.directory_of(built()), coverage=coverage_kc(),
        snapshots={}, config=SHORT, now=world.utc("2026-01-08T06:00:00"),
    )  # fmt: skip
    assert run.added == [MONDAY]
    assert run.skipped["no record of the live reads"] == 1


def listing(day: date, nces: str, source: str, event: Event = Event.LIT) -> LogChange:
    at = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)
    shown = Shown(int(Status.CLOSED), int(Reason.WINTER_STORM), None, None)
    return LogChange(at, day, nces, event, shown, {"source_id": source})


def test_the_lighting_lists_come_from_the_change_log_of_the_day(tmp_path: Path) -> None:
    folder = tmp_path / "state"
    changes = ChangeLog(folder / "changes")
    changes.commit([listing(DAY, "290000100001", "tv"), listing(DAY, "290000200003", "radio")])
    source = StateReadSource(
        StateSource(
            folder=folder, market_of={"tv": "KC"}, zone_of=dict(world.ZONES),
            settings=CFG.labels, prefix="v1", read_file=lambda _path: None,
        )
    )  # fmt: skip
    noon = datetime.combine(DAY, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)
    assert source.lit_by(DAY) == {"2900001": {"tv": noon}, "2900002": {"radio": noon}}
    # A day the change log no longer holds (it keeps 30 days) gives no lighting lists, so no
    # trial: the labels never rest on a pruned change log.
    assert source.lit_by(DAY - timedelta(days=40)) is None
    assert source.captures(DAY, 14) == LiveCaptures()


# --- the coverage files ---------------------------------------------------------------------------


def test_the_coverage_files_hold_codes_and_read_back(tmp_path: Path) -> None:
    proven = {
        OKANOGAN: {"proven": ["tegna-krem"], "proven_districts": []},
        "53007": {"proven": ["thin-list", "cox-kiro"], "proven_districts": ["x"]},
        "06043": {"proven": []},
    }
    captures = populated_captures(
        [
            json.dumps({"source_id": "tegna-krem", "state": "populated"}),
            json.dumps({"source_id": "thin-list", "state": "empty"}),
            "",
        ]
        * 5
    )
    assert captures == {"tegna-krem": 5}
    counties = county_sources_of(proven)
    assert counties == {OKANOGAN: ["tegna-krem"], "53007": ["cox-kiro", "thin-list"]}
    path = tmp_path / "read-sources.json.gz"
    value = {"schema_version": 3, "counties": counties, "captures": captures,
             "closing_rows": {"tegna-krem": [40, 12]}}  # fmt: skip
    path.write_bytes(gzip_json(value))
    assert path.read_bytes() == gzip_json(dict(reversed(value.items())))
    found = load_read_sources(path)
    assert found.counties == {OKANOGAN: ("tegna-krem",), "53007": ("cox-kiro", "thin-list")}
    assert found.captures == {"tegna-krem": 5}
    assert found.rows == {"tegna-krem": (12, 40)}
    audiences = tmp_path / "audiences.json.gz"
    audiences.write_bytes(gzip_json({"schema_version": 3, "audiences": {"tv": ["2900001"]}}))
    assert load_audiences(audiences) == {"tv": frozenset({"2900001"})}
    assert load_read_sources(tmp_path / "none.json.gz") == ReadSources({}, {})
    assert load_audiences(tmp_path / "none.json.gz") == {}
    # A file of an earlier version (1: every archive capture's rows, audiences with dates;
    # 2: every closing-size snapshot's rows, audiences of every season) is refused, never
    # read as this one.
    for version in (1, 2):
        for name, old in (
            ("old-sources.json.gz", {"schema_version": version, "counties": counties, "rows": {}}),
            ("old-audiences.json.gz", {"schema_version": version, "audiences": {}}),
        ):
            (tmp_path / name).write_bytes(gzip_json(old))
            load = load_read_sources if "sources" in name else load_audiences
            with pytest.raises(ValueError, match=f"schema_version {version}"):
                load(tmp_path / name)


def test_a_proven_list_reads_once_it_has_enough_populated_captures() -> None:
    # station_min_captures (5) of the archive and the live record before the day together.
    thin = Coverage(
        county_sources={OKANOGAN: ("tegna-krem",)},
        archive={},
        county_of={METHOW: OKANOGAN},
        captures={"tegna-krem": 1},
        rows={"tegna-krem": (10,)},
        min_captures=5,
    )
    morning = pt_morning({"tegna-krem": [WHOLE]})

    def label(days: int) -> tuple[Label, str | None]:
        live = LiveCaptures(days={"tegna-krem": days}, storm_rows={"tegna-krem": (10,) * days})
        found = label_read_day(
            OCT28, morning=morning, coverage=thin, weather=[WeatherClass.ADVISORY], lit=DARK,
            directory=one_district(), rule=RULE, recent={"tegna-krem": 1}, live=live,
        )  # fmt: skip
        (row,) = found.rows
        return row.label, row.why

    # A live capture is a day with a populated whole read of the list.
    assert label(3) == (Label.NOT_READ, NotRead.NOT_COVERED.value)
    assert label(4) == (Label.UNNAMED, None)


# --- 9: S7-L is untouched -------------------------------------------------------------------------


def test_the_s7_l_labels_and_learn_json_are_the_same_with_the_read_step(tmp_path: Path) -> None:
    now = world.utc("2026-01-08T06:00:00")
    shown_monday = world.timeline().model_copy(update={"day": MONDAY})
    source = ReadingSource({DAY: world.timeline(), MONDAY: shown_monday})
    snapshots = {**snapshots_for(DAY), **snapshots_for(MONDAY)}
    plain, beside = Host(), Host()
    assert cli.learn_once(replace(learn_run(plain, source, now, SHORT), snapshots=snapshots)) == 0
    read_new_days(
        tmp_path / "reads", source, directory=learn.directory_of(built()),
        coverage=coverage_kc(), snapshots=snapshots, config=SHORT, now=now,
    )  # fmt: skip
    assert cli.learn_once(replace(learn_run(beside, source, now, SHORT), snapshots=snapshots)) == 0
    assert plain.files == beside.files
    assert set(plain.files) == {"v1/predictions/learn.json"}
    store = learn.LearnStore.from_bytes(plain.files["v1/predictions/learn.json"])
    assert [d.day for d in store.days] == [MONDAY, DAY]
    assert KC_CARRIED  # the S7-L fixtures this file reuses are the S7-L tests' own


def test_the_shipped_rule_is_the_registered_one() -> None:
    assert (RULE.healthy_share, RULE.recent_days, RULE.min_captures) == (0.9, 14, 5)
    assert (RULE.prior_a, RULE.prior_b) == ((9.0, 1.0), (4.0, 2.0))


ZERO: Final = dict.fromkeys(
    (
        "alerted", "covered", "read_a", "read_b", "named", "lit_no_school", "lit_delayed",
        "unnamed", "unknown_listed", "unknown_partly_lit", "unknown_retracted",
        "unknown_break", "unknown_absent", "not_covered", "no_whole_read", "dropped_read",
        "voided_empty", "stale_empty", "stale_populated", "thin_list", "small_capture",
        "empty_uncorroborated",
        "health_unrecorded", "unhealthy", "not_recent", "trials_a", "hits_a",
        "trials_b", "hits_b", "unnamed_unplaced", "withheld_state",
    ),
    0,
)  # fmt: skip
"""Every count of a :class:`ReadClass` at 0 (``median_health`` left out)."""


def test_the_audit_refuses_counts_that_do_not_add_up() -> None:
    zero = dict.fromkeys(
        (
            "alerted", "covered", "read_a", "read_b", "named", "lit_no_school", "lit_delayed",
            "unnamed", "unknown_listed", "unknown_partly_lit", "unknown_retracted",
            "unknown_break", "unknown_absent", "not_covered", "no_whole_read", "dropped_read",
            "voided_empty", "stale_empty", "stale_populated", "thin_list", "small_capture",
            "empty_uncorroborated",
            "health_unrecorded", "unhealthy", "not_recent", "trials_a", "hits_a",
            "trials_b", "hits_b", "unnamed_unplaced", "withheld_state",
        ),
        0,
    )  # fmt: skip
    good = {**zero, "weather": "advisory", "alerted": 2, "covered": 1, "read_b": 1,
            "unnamed": 1, "not_covered": 1, "median_health": 950}  # fmt: skip
    ReadClass.model_validate(good)
    for bad in (
        {**good, "unnamed": 0},  # a read district not labeled
        {**good, "not_covered": 0},  # a district neither read nor counted
        {**good, "covered": 2},
        {**good, "hits_b": 1},  # more hits than trials
        {**good, "unnamed_unplaced": 2},  # more unnamed with unplaced rows than unnamed
        {**good, "withheld_state": 1},  # a district counted twice
        {**good, "median_health": None},
        {**good, "weather": "storm"},
    ):
        try:
            ReadClass.model_validate(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


# --- the steps ------------------------------------------------------------------------------------


def read_run(host: Host, folder: Path, now: datetime) -> read_cli.ReadLabelsRun:
    shown_monday = world.timeline().model_copy(update={"day": MONDAY})
    return read_cli.ReadLabelsRun(
        config=SHORT,
        host=host,
        prefix="v1",
        source=ReadingSource({DAY: world.timeline(), MONDAY: shown_monday}),
        directory=learn.directory_of(built()),
        coverage=coverage_kc(),
        snapshots={**snapshots_for(DAY), **snapshots_for(MONDAY)},
        folder=folder,
        now=now,
    )


def test_the_step_publishes_the_audit_only_when_a_day_is_added(tmp_path: Path, capsys: Any) -> None:
    host = Host()
    now = world.utc("2026-01-08T06:00:00")
    assert read_cli.read_once(read_run(host, tmp_path / "reads", now)) == 0
    assert host.writes == 1
    audit = ReadAudit.from_json_bytes(host.files["v1/predictions/read-audit.json"])
    assert [d.day for d in audit.days] == [MONDAY, DAY]
    out = capsys.readouterr().out
    assert "predict read-labels: labeled 2026-01-05, 2026-01-06\n" in out
    assert "co-listing trials, all seasons: tier A 0 (0 named), tier B 0 (0 named)" in out
    assert "list sensitivity, this season: " in out
    assert "snow_warning read 6" in out
    # Which lists gain live closing-size values, run by run (review E-R5-3): the synthetic
    # source counts four days of the TV list; the fixture lists hold ten archive values each.
    # Review E-R6-1: and how many lists read with no second list (a counted day in the
    # recent days), the read's live peer-free reach; review R6-S3: how many are tier B.
    assert (
        "counted live days through 2026-01-06: 4 days of 1 lists; 6 lists with 5 closing-size "
        "values, archive and live (lead ruling C2), 0 of them tier B; 1 lists with a counted "
        f"day in the {RULE.recent_days} days before (they read with no second list: "
        "condition 4)\n"
    ) in out
    # A rerun an hour on adds no day and writes nothing.
    assert read_cli.read_once(read_run(host, tmp_path / "reads", now + timedelta(hours=1))) == 0
    assert host.writes == 1
    # A record that does not read is an error, and nothing is written.
    (tmp_path / "reads" / "rows" / "2026-01-06.json").write_text("{")
    assert read_cli.read_once(read_run(host, tmp_path / "reads", now)) == 1
    assert host.writes == 1


def test_the_coverage_files_are_built_from_codes(tmp_path: Path) -> None:
    reads = tmp_path / "reads.jsonl"
    reads.write_text(
        "\n".join(
            json.dumps(
                {
                    "source_id": "tv",
                    "state": "populated",
                    "rows": n,
                    "fetched_at": f"2025-01-0{i}T12:00:00Z",
                }
            )
            for i, n in enumerate((1, 300, 2, 280, 1), start=1)
        )
        + "\n"
    )
    coverage = {"proven": {"counties": {"29095": {"proven": ["tv", "radio"]}}}}
    closing = {
        ("tv", "2025-01-02T12:00:00Z"): date(2025, 1, 2),
        ("tv", "2025-01-04T12:00:00Z"): date(2025, 1, 4),
    }
    data = read_cli.read_sources_of(coverage, reads, 5, closing)
    path = tmp_path / "read-sources.json.gz"
    path.write_bytes(data)
    # Every capture counts for the thin-station gate; only the closing-size ones give rows.
    assert load_read_sources(path) == ReadSources(
        {"29095": ("radio", "tv")}, {"tv": 5}, {"tv": (280, 300)}
    )
    # Review R5-S3: one value a closing-size day, its largest capture. An early snapshot of
    # the 4th's storm (2 rows, still growing) beside its later 280 rows is no second
    # capture, and never the 4th's value.
    early = {**closing, ("tv", "2025-01-03T12:00:00Z"): date(2025, 1, 4)}
    path.write_bytes(read_cli.read_sources_of(coverage, reads, 5, early))
    assert load_read_sources(path).rows == {"tv": (280, 300)}
    listings = [
        ("tv", "2900001", date(2025, 1, 6)),
        ("tv", "2900001", date(2025, 1, 9)),
        ("tv", "2900002", date(2025, 1, 6)),
        ("tv", "A0000007", date(2025, 1, 6)),  # a private school is not a district
    ]
    path = tmp_path / "audiences.json.gz"
    built_ = read_cli.audiences_of(listings, 2, date(2024, 8, 1))
    path.write_bytes(built_.data)
    assert load_audiences(path) == {"tv": frozenset({"2900001"})}
    assert (built_.kept, built_.dropped, built_.dropped_districts) == (1, 0, 0)
    assert live_read_module.load_audience_season(path) == 2025  # the build season's code
    value = json.loads(gzip.decompress(path.read_bytes()))
    del value["season"]
    assert "2025" not in json.dumps(value)  # codes only: no dates
    # Lead ruling C4: only pairs listed in the current or previous season (from the
    # previous season's Aug 1) are kept; older ones are dropped at build time and counted.
    assert read_cli.audience_since(date(2026, 10, 31)) == date(2025, 8, 1)
    assert read_cli.audience_since(date(2026, 7, 31)) == date(2024, 8, 1)
    assert read_cli.audience_since(date(2026, 8, 1)) == date(2025, 8, 1)
    recent = [*listings, ("radio", "2900002", date(2025, 9, 2)),
              ("radio", "2900002", date(2025, 9, 3))]  # fmt: skip
    built_ = read_cli.audiences_of(recent, 2, date(2025, 8, 1))
    path.write_bytes(built_.data)
    assert load_audiences(path) == {"radio": frozenset({"2900002"})}
    assert (built_.kept, built_.dropped, built_.dropped_districts) == (1, 1, 1)
    value = json.loads(gzip.decompress(path.read_bytes()))
    assert value.pop("season") == 2026
    for text in ("2024", "2025", "2026"):
        assert text not in json.dumps(value)
    try:
        read_cli.read_sources_of({}, reads, 5, closing)
    except ValueError:
        return
    raise AssertionError("no proven table")


def test_every_labeled_day_is_offered_to_the_evidence_store(tmp_path: Path) -> None:
    folder = tmp_path / "reads"
    now = world.utc("2026-01-08T06:00:00")
    assert read_cli.read_once(read_run(Host(), folder, now)) == 0
    offers = cli.read_offers(folder)
    assert sorted((o.kind, o.key) for o in offers) == [
        ("audit", "2026-01-05"), ("audit", "2026-01-06"),
        ("labels", "read-2026-01-05"), ("labels", "read-2026-01-06"),
        ("trials", "2026-01-05"), ("trials", "2026-01-06"),
    ]  # fmt: skip
    store = EvidenceStore(FakeD1(), {"GITHUB_WORKFLOW": "predict"}, lambda: RETENTION_NOW)
    assert cli.keep_evidence(store, {}, {}, now, reads=offers) == 0
    assert store.pull(TRIALS) == {"2026-01-05": b"", "2026-01-06": b""}
    assert set(store.pull(AUDIT)) == {"2026-01-05", "2026-01-06"}
    assert (
        store.pull(LABELS)["read-2026-01-06"] == (folder / "rows" / "2026-01-06.json").read_bytes()
    )
    assert cli.read_offers(tmp_path / "none") == []


class BrokenHost(Host):
    """A host whose writes do not stick."""

    def write(self, files: Mapping[str, bytes]) -> None:  # noqa: ARG002 - the protocol
        self.writes += 1


def test_an_audit_that_does_not_read_back_is_an_error_and_a_bad_one_is_replaced(
    tmp_path: Path,
) -> None:
    now = world.utc("2026-01-08T06:00:00")
    assert read_cli.read_once(read_run(BrokenHost(), tmp_path / "a", now)) == 1
    # A published audit that does not read (a schema change, a broken write) is an error:
    # nothing is labeled, since the days it published could not be told apart and would be
    # labeled again; the host keeps it as it was.
    host = Host()
    host.files["v1/predictions/read-audit.json"] = b"{"
    assert read_cli.read_once(read_run(host, tmp_path / "b", now)) == 1
    assert host.files["v1/predictions/read-audit.json"] == b"{"
    assert labeled_days(tmp_path / "b") == []
    # With nothing labeled the log says so.
    empty = audit_of(tmp_path / "none", now)
    assert read_cli.summary(empty, tmp_path / "none")[0] == (
        "0 days labeled, all seasons; no alerted district read yet"
    )


def test_recent_populated_reads_count_the_days_before_only(tmp_path: Path) -> None:
    # Lead ruling C2: a 'recent populated' day is a counted day only. SYNTHETIC: the TV list
    # (ten closing-size archive days of 10 rows) read 9 to 12 rows, naming three warned
    # districts our map lit.
    log = MorningLog(tmp_path / "morning")
    # In January 15:00Z is 07:00 Pacific standard time, inside the read window.
    for text, rows in (("2026-01-02", 9), ("2026-01-05", 0), ("2026-01-06", 12),
                       ("2025-12-01", 10)):  # fmt: skip
        record_on(log, date.fromisoformat(text), {"tv": (rows, rows, 0)}, by={"tv": WARNED},
                  at="15:00")  # fmt: skip
    log.path(date(2025, 12, 1)).write_text("{")  # damaged: never counted
    closing = closing_of(COUNTY)
    assert counted(log, closing, DAY, 14).days == {"tv": 1}
    assert counted(log, closing, DAY, 60).days == {"tv": 1}
    assert counted(log, closing, date(2026, 1, 7), 14).days == {"tv": 2}
    # The same reads naming nothing, or on days our map lit no warned district, never count.
    quiet = MorningLog(tmp_path / "quiet")
    for text in ("2026-01-02", "2026-01-06"):
        record_on(quiet, date.fromisoformat(text), {"tv": (9, 9, 0)}, by={"tv": []}, at="15:00")
    assert counted(quiet, closing, date(2026, 1, 7), 14) == LiveCaptures()
    assert counted(log, closing_of(COUNTY, frozenset()), date(2026, 1, 7), 14) == LiveCaptures()


# --- round 2: the read set never sees the day's own lighting --------------------------------------


def lit_change(day: date, logged: date, source: str, leaid: str = METHOW) -> LogChange:
    """SYNTHETIC: ``source`` lit a school of ``leaid`` closed for ``day``, logged at 23:00 UTC
    on ``logged``."""
    at = datetime.combine(logged, datetime.min.time(), tzinfo=UTC) + timedelta(hours=23)
    shown = Shown(int(Status.CLOSED), int(Reason.WINTER_STORM), None, None)
    return LogChange(at, day, leaid + "00001", Event.LIT, shown, {"source_id": source})


def methow_state(folder: Path) -> StateReadSource:
    """SYNTHETIC: a live state whose record read the KREM list whole every 30 minutes through
    Oct 28's Pacific window, healthy."""
    log = MorningLog(folder / "morning")
    for minutes in range(0, 240, 30):
        log.record(
            datetime(2026, 10, 28, 13, 35, tzinfo=UTC) + timedelta(minutes=minutes),
            shown="v1", reads={"tegna-krem": WHOLE}, unknown=(), named={}, health=0.95,
        )  # fmt: skip
    return StateReadSource(
        StateSource(
            folder=folder, market_of={"tegna-krem": "Spokane"}, zone_of={METHOW: PACIFIC},
            settings=CFG.labels, prefix="v1", read_file=lambda _path: None,
        )
    )  # fmt: skip


def test_what_the_lists_lit_on_the_day_never_decides_who_is_read(tmp_path: Path) -> None:
    source = methow_state(tmp_path / "state")
    changes = ChangeLog(tmp_path / "state" / "changes")
    # The KREM list lit Methow once, ten days before (one live day: not an audience yet).
    changes.commit(
        [lit_change(OCT28 - timedelta(days=10), OCT28 - timedelta(days=10), "tegna-krem")]
    )
    nobody = listed(Coverage(county_sources={}, archive={}, county_of={METHOW: OKANOGAN}))

    def reads() -> Read | NotRead:
        morning = StateReadSource(source.state).morning(OCT28)  # each run reads the log anew
        assert isinstance(morning, Morning)
        found = read_set(
            morning, directory=one_district(), coverage=nobody, recent={"tegna-krem": 3},
            rule=RULE, weather=[WeatherClass.ADVISORY],
        )  # fmt: skip
        return found[METHOW]

    before = reads()
    assert before is NotRead.NOT_COVERED
    # It lights Methow on the 28th itself (the outcome): the read set is as it was.
    changes.commit([lit_change(OCT28, OCT28, "tegna-krem")])
    assert reads() == before
    # And a closing for the 29th, lit on the 28th's log: still as it was.
    changes.commit([lit_change(OCT28 + timedelta(days=1), OCT28, "tegna-krem")])
    assert reads() == before
    # A second lighting before the day makes the list carry Methow from then on: tier A.
    changes.commit([lit_change(OCT28 - timedelta(days=3), OCT28 - timedelta(days=3), "tegna-krem")])
    found = reads()
    assert isinstance(found, Read)
    assert (found.tier, found.sources) == (Tier.A, ("tegna-krem",))


def test_a_proven_list_s_live_captures_are_days_not_slots(tmp_path: Path) -> None:
    log = MorningLog(tmp_path / "morning")
    # ONE storm morning (Oct 27): the same 4-row list naming three warned districts our map
    # lit, recorded in five slots, beside a 6-row market peer (KREM's reference is thin, so
    # the peer vouches for its length: lead ruling B1.2) and an empty read.
    for minutes in ("14:00", "14:30", "15:00", "15:30", "16:00"):
        record_on(log, OCT28 - timedelta(days=1),
                  {"tegna-krem": (4, 4, 0), "flashalert-spokane": (6, 6, 0), "cox-kiro": (0, 0, 0)},
                  by={"tegna-krem": WARNED, "flashalert-spokane": ["5300003"]},
                  at=minutes)  # fmt: skip
    # The peer keeps its ten closing-size captures of 10 rows (it vouches: PeerVouch).
    thin = replace(COUNTY, captures={**COUNTY.captures, "tegna-krem": 5},
                   rows={**COUNTY.rows, "tegna-krem": (4,)})  # fmt: skip
    found = counted(log, closing_of(thin))
    assert found == LiveCaptures(days={"tegna-krem": 1}, storm_rows={"tegna-krem": (4,)})
    assert counted(log, closing_of(thin), OCT28, 14).days == {"tegna-krem": 1}
    stats = ListStats.of(thin, found, RULE.labels.station_min_captures)
    assert stats.captures["tegna-krem"] == 6
    # Two storm-size lists are too few to tell a partial one: no size reference yet.
    assert stats.median_rows["tegna-krem"] == math.inf
    assert methow(pt_morning({"tegna-krem": [WHOLE]}), coverage=thin)[1] == "not_covered"


def test_methow_on_its_real_capture_count_is_not_covered() -> None:
    # The dry-run coverage file gives the county's KREM list one archive capture.
    real = replace(COUNTY, captures={"tegna-krem": 1}, rows={"tegna-krem": (10,)})
    assert methow(pt_morning({"tegna-krem": [WHOLE]}), coverage=real) == (
        Label.NOT_READ, NotRead.NOT_COVERED.value, None,
    )  # fmt: skip


# --- round 2: the station gates tell a whole list from a partial one ------------------------------


def test_a_storm_day_list_under_half_its_median_rows_is_partial() -> None:
    # The list's median is 10 rows; a 2-row read on a warning or advisory day is partial.
    small = pt_morning({"tegna-krem": [(2, 2, 0)]})
    for weather in (WeatherClass.SNOW_WARNING, WeatherClass.ADVISORY):
        assert methow(small, weather=weather) == (
            Label.NOT_READ, NotRead.SMALL_CAPTURE.value, None,
        )  # fmt: skip
    assert methow(pt_morning({"tegna-krem": [(5, 5, 0)]}))[0] is Label.UNNAMED
    # On a plain day the size gate does not apply (as in the archive).
    plain = read_set(
        small, directory=one_district(), coverage=COUNTY, recent={"tegna-krem": 3}, rule=RULE,
        weather=[WeatherClass.NONE],
    )  # fmt: skip
    assert isinstance(plain[METHOW], Read)
    # A list with captures and no closing-size capture is no tier B list at all, and,
    # carried (tier A), reads no populated list on a storm day without a peer.
    unknown = replace(COUNTY, rows={})
    assert methow(pt_morning({"tegna-krem": [WHOLE]}), coverage=unknown)[1] == "not_covered"
    carried = replace(unknown, archive={"tegna-krem": frozenset({METHOW})})
    assert methow(pt_morning({"tegna-krem": [WHOLE]}), coverage=carried)[1] == "small_capture"


def test_a_tier_a_list_with_too_few_captures_never_reads_a_populated_list() -> None:
    carried = {"flashalert-spokane": {METHOW: date(2026, 10, 1)}}
    nobody = Coverage(
        county_sources={}, archive={}, county_of={METHOW: OKANOGAN},
        captures={"flashalert-spokane": 1}, rows={"flashalert-spokane": (3,)}, min_captures=5,
    )  # fmt: skip
    morning = pt_morning({"flashalert-spokane": [(3, 3, 0)]}, audience=carried)
    assert methow(morning, coverage=nobody, recent={"flashalert-spokane": 1}) == (
        Label.NOT_READ, NotRead.THIN_STATION.value, None,
    )  # fmt: skip


def test_a_lone_empty_list_on_a_storm_day_is_not_whole() -> None:
    both = listed(
        Coverage(
            county_sources={OKANOGAN: ("flashalert-spokane", "tegna-krem")},
            archive={},
            county_of={METHOW: OKANOGAN},
        )
    )
    alone = pt_morning({"tegna-krem": [(0, 0, 0)]})
    assert methow(alone, coverage=both) == (
        Label.NOT_READ, NotRead.EMPTY_UNCORROBORATED.value, None,
    )  # fmt: skip
    # A market peer read in the window too (its 3 rows a whole list of its own, under the
    # 5 that void an empty): the empty list is whole.
    peer = pt_morning({"tegna-krem": [(0, 0, 0)], "flashalert-spokane": [(3, 3, 0)]})
    assert methow(peer, coverage=SHORT_PEER)[0] is Label.UNNAMED
    # A peer's partial read (3 rows of a 10-row list on a storm day) corroborates nothing.
    assert methow(peer, coverage=COUNTY)[1] == NotRead.EMPTY_UNCORROBORATED.value


def test_an_empty_judged_from_old_rows_is_never_a_whole_read() -> None:
    # The KREM list's page held a list typed by hand two days before: the reader took it as
    # empty (its rows old notes). A market peer read too (too few rows to void an empty), so
    # only the staleness stops it.
    morning = pt_morning({"tegna-krem": [(0, 0, 0)], "flashalert-spokane": [(3, 3, 0)]})
    morning.slots[slot_start(OCT28, "14:00")].stale = {"tegna-krem"}
    assert methow(morning, coverage=SHORT_PEER) == (
        Label.NOT_READ, NotRead.STALE_EMPTY.value, None,
    )  # fmt: skip
    # Not on a plain day either.
    plain = read_set(
        morning, directory=one_district(), coverage=COUNTY, recent={"tegna-krem": 3}, rule=RULE,
        weather=[WeatherClass.NONE],
    )  # fmt: skip
    assert plain[METHOW] is NotRead.STALE_EMPTY
    # A current empty page in the same morning is whole.
    morning.slots[slot_start(OCT28, "14:00")].stale = set()
    assert methow(morning, coverage=SHORT_PEER)[0] is Label.UNNAMED


# --- round 2: open only when nothing named the district for the day -------------------------------


def test_a_naming_after_the_window_still_keeps_a_district_from_open() -> None:
    morning = pt_morning({"tegna-krem": [WHOLE]})
    # A row named Methow closed at 11:00 PT (18:00Z), after the window, the map dark.
    late = Slot(shown={"v1"}, named={METHOW: {OCT28.isoformat(): {"closed"}}})
    slots = {**morning.slots, slot_start(OCT28, "18:00"): late}
    assert methow(replace(morning, slots=slots)) == (Label.UNKNOWN, "listed_unread", Tier.B)


# --- round 2: the trials --------------------------------------------------------------------------


def test_a_list_that_lit_the_district_after_its_window_is_a_trial() -> None:
    both = listed(
        Coverage(
            county_sources={OKANOGAN: ("flashalert-spokane", "tegna-krem")},
            archive={},
            county_of={METHOW: OKANOGAN},
        )
    )

    def trials(lit_by: Mapping[str, datetime]) -> list[tuple[str, bool]]:
        found = label_read_day(
            OCT28,
            morning=pt_morning(
                {"tegna-krem": [WHOLE], "flashalert-spokane": [WHOLE]},
                by={"tegna-krem": [METHOW]},
                named={METHOW: {OCT28.isoformat(): ["closed"]}},
            ),
            coverage=both, weather=[WeatherClass.ADVISORY], lit=closed_lit([0, 1]),
            directory=one_district(), rule=RULE, recent={"tegna-krem": 2, "flashalert-spokane": 2},
            lit_by={METHOW: lit_by},
        )  # fmt: skip
        return [(t.source, t.named) for t in found.trials]

    # KREM lit it at 06:50 PT: no trial of its own; FlashAlert did not name it: a miss.
    assert trials({"tegna-krem": LIT_AT}) == [("flashalert-spokane", False)]
    # FlashAlert lit it only at 11:00 PT, after the window: it is a trial too (a miss).
    late = datetime(2026, 10, 28, 18, 0, tzinfo=UTC)
    assert trials({"tegna-krem": LIT_AT, "flashalert-spokane": late}) == [
        ("flashalert-spokane", False)
    ]
    # Lit two days ahead by KREM (logged on the 26th): KREM still gives no trial.
    ahead = datetime(2026, 10, 26, 23, 0, tzinfo=UTC)
    assert trials({"tegna-krem": ahead}) == [("flashalert-spokane", False)]


def test_the_lighting_lists_include_a_closing_announced_days_ahead(tmp_path: Path) -> None:
    changes = ChangeLog(tmp_path / "changes")
    changes.commit([lit_change(OCT28, OCT28 - timedelta(days=2), "tegna-krem")])
    changes.commit([lit_change(OCT28, OCT28, "flashalert-spokane")])
    changes.commit([lit_change(OCT28 + timedelta(days=1), OCT28, "cox-kiro")])
    assert lit_sources(changes, OCT28) == {
        METHOW: {
            "flashalert-spokane": datetime(2026, 10, 28, 23, 0, tzinfo=UTC),
            "tegna-krem": datetime(2026, 10, 26, 23, 0, tzinfo=UTC),
        }
    }


def test_the_registered_window_must_be_the_labels_window() -> None:
    read = {**CFG.live_score["read"], "window": ["06:00", "09:30"]}
    moved = CFG.model_copy(update={"live_score": {**CFG.live_score, "read": read}})
    with pytest.raises(ValueError, match="window"):
        ReadRule.of(moved)


# --- round 2: the private report ------------------------------------------------------------------


def test_the_beta_interval() -> None:
    low, high = beta_interval(9, 1)
    assert abs(low - 0.05 ** (1 / 9)) < 1e-3
    assert abs(high - 0.95 ** (1 / 9)) < 1e-3
    assert beta_interval(1, 1) == pytest.approx((0.05, 0.95), abs=1e-4)


def test_the_report_gives_each_tier_s_sensitivity_with_its_interval(tmp_path: Path) -> None:
    folder = tmp_path / "reads"
    now = world.utc("2026-01-08T06:00:00")
    host = Host()
    assert read_cli.read_once(read_run(host, folder, now)) == 0
    report = ReadReport.model_validate_json((folder / "summary.json").read_bytes())
    a, b = report.sensitivity
    # No trial yet: the priors, s_B's mean already under G1's 0.7.
    assert (a.tier, a.trials, a.mean) == (Tier.A, 0, 0.9)
    assert (b.tier, b.trials, b.mean) == (Tier.B, 0, round(4 / 6, 4))
    assert a.low < a.mean < a.high
    assert b.low < b.mean < b.high
    assert not report.tier_b_g1
    assert report.rows["ohio_valley"]["snow_warning"]["no_school"] == 2
    assert sum(report.states.values()) > 0
    assert (report.hand_audit.unnamed, report.hand_audit.drawn) == (0, 0)  # none unnamed
    # The sample is a fixed draw of unnamed rows, the same every run.
    again = read_cli.read_once(read_run(host, folder, now + timedelta(hours=1)))
    assert again == 0
    assert (folder / "summary.json").read_bytes() == report.model_dump_json(indent=1).encode()


# --- round 2: the step ----------------------------------------------------------------------------


def test_without_the_coverage_files_nothing_is_labeled_or_frozen(
    tmp_path: Path, capsys: Any
) -> None:
    host = Host()
    run = replace(
        read_run(host, tmp_path / "reads", world.utc("2026-01-08T06:00:00")),
        missing=("read-sources.json.gz",),
    )
    assert read_cli.read_once(run) == 0
    assert host.writes == 0
    assert labeled_days(tmp_path / "reads") == []
    assert "the coverage files are absent (read-sources.json.gz)" in capsys.readouterr().out


def test_a_published_day_is_never_relabeled_nor_dropped(tmp_path: Path, capsys: Any) -> None:
    now = world.utc("2026-01-08T06:00:00")
    host = Host()
    outputs = tmp_path / "github-output"
    run = replace(read_run(host, tmp_path / "first", now), outputs=outputs)
    assert read_cli.read_once(run) == 0
    assert outputs.read_text() == "added=true\n"
    published = host.files["v1/predictions/read-audit.json"]
    # The Actions cache lost the record: the next run labels nothing the audit holds, keeps
    # every published day as published, and says so.
    later = replace(read_run(host, tmp_path / "lost", now + timedelta(hours=6)), outputs=outputs)
    assert read_cli.read_once(later) == 0
    assert labeled_days(tmp_path / "lost") == []
    assert host.files["v1/predictions/read-audit.json"] == published
    assert outputs.read_text() == "added=true\n"  # no day added: no cache save
    out = capsys.readouterr().out
    assert "::warning::predict read-labels: the record lacks 2 days the public audit holds" in out
    assert "school days not labeled: the public audit holds it" in out
    # With only the 5th published, the 6th is labeled after it as ever.
    only = ReadAudit.from_json_bytes(published)
    host.files["v1/predictions/read-audit.json"] = only.model_copy(
        update={"days": only.days[:1]}
    ).to_json_bytes()
    assert read_cli.read_once(read_run(host, tmp_path / "half", now + timedelta(hours=7))) == 0
    assert labeled_days(tmp_path / "half") == [DAY]
    assert ReadAudit.from_json_bytes(host.files["v1/predictions/read-audit.json"]).days == (
        only.days
    )
    # A held day keeps its published counts even when the record holds other ones.
    held = ReadAudit.from_json_bytes(published)
    changed = held.days[0].model_copy(update={"held": True, "classes": ()})
    mixed = held.model_copy(update={"days": (changed, *held.days[1:])})
    assert audit_of(tmp_path / "first", now, mixed).days == mixed.days


def test_only_the_newest_days_are_offered_and_after_the_snapshots(
    tmp_path: Path, capsys: Any
) -> None:
    folder = tmp_path / "reads"
    now = world.utc("2026-01-08T06:00:00")
    assert read_cli.read_once(read_run(Host(), folder, now)) == 0
    newest = cli.read_offers(folder, 1)
    assert sorted((o.kind, o.key) for o in newest) == [
        ("audit", "2026-01-06"), ("labels", "read-2026-01-06"), ("trials", "2026-01-06"),
    ]  # fmt: skip
    # The audit offer is the bytes written with the day (nothing is parsed to offer it).
    (audit,) = (o for o in newest if o.kind == "audit")
    assert audit.data == (folder / "audit" / "2026-01-06.json").read_bytes()
    store = EvidenceStore(FakeD1(), {"GITHUB_WORKFLOW": "predict"}, lambda: RETENTION_NOW)
    capsys.readouterr()
    assert cli.keep_evidence(store, {}, {}, now, b"{}", reads=newest) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if "finished files" in line]
    # The snapshots, tables and labels go first; the read days with the time left.
    assert [("(read labels)" in line) for line in lines] == [False, False, True, True]


# --- round 3: the size gate's reference is storm-size lists only ----------------------------------


def storm_read(
    read: tuple[int, int, int],
    coverage: Coverage,
    live: LiveCaptures,
    weather: WeatherClass = WeatherClass.SNOW_WARNING,
) -> tuple[Label, str | None]:
    found = label_read_day(
        OCT28, morning=pt_morning({"tegna-krem": [read]}), coverage=coverage, weather=[weather],
        lit=DARK, directory=one_district(), rule=RULE, recent={"tegna-krem": 3}, live=live,
    )  # fmt: skip
    (row,) = found.rows
    return row.label, row.why


def test_quiet_days_never_shrink_the_size_gate_s_reference(tmp_path: Path) -> None:
    # The list ran 276 rows on each of its five archive captures. Twenty quiet mornings of
    # 2 to 5 rows follow in the live record. A 40-row read on a warning morning, the same
    # every pass, is a partial list: never whole, so the districts missing from it are
    # never open.
    proven = replace(COUNTY, captures={"tegna-krem": 5}, rows={"tegna-krem": (276,) * 5})
    log = MorningLog(tmp_path / "morning")
    for back in range(1, 21):
        when = datetime.combine(OCT28 - timedelta(days=back), datetime.min.time(), tzinfo=UTC)
        for minutes, rows in zip((840, 870, 900, 930), (2, 3, 4, 5), strict=True):
            log.record(when + timedelta(minutes=minutes), shown="v1",
                       reads={"tegna-krem": (rows, rows, 0)}, unknown=(), named={},
                       health=0.95)  # fmt: skip
    quiet = counted(log, closing_of(proven, frozenset()))
    assert quiet == LiveCaptures()
    assert storm_read((40, 40, 0), proven, quiet) == (Label.NOT_READ, "small_capture")
    # Even had those small lists named three warned districts our map lit, each day's read
    # is under half the reference as it stood (lead ruling C2: a short read never counts),
    # so the reference stays the archive's.
    named = MorningLog(tmp_path / "named")
    for back in range(1, 21):
        for at, rows in zip(("14:00", "14:30", "15:00", "15:30"), (2, 3, 4, 5), strict=True):
            record_on(named, OCT28 - timedelta(days=back), {"tegna-krem": (rows, rows, 0)},
                      by={"tegna-krem": WARNED}, at=at)  # fmt: skip
    minor = counted(named, closing_of(proven))
    assert minor == LiveCaptures()
    stats = ListStats.of(proven, minor, RULE.labels.station_min_captures)
    assert stats.median_rows == {"tegna-krem": 276.0}
    # And were such values counted, the reference would still never fall under the
    # archive's own median.
    forced = LiveCaptures(days={"tegna-krem": 20}, storm_rows={"tegna-krem": (5,) * 20})
    assert ListStats.of(proven, forced, 5).median_rows == {"tegna-krem": 276.0}
    assert storm_read((40, 40, 0), proven, forced) == (Label.NOT_READ, "small_capture")
    minor = forced
    # A storm-size read is whole.
    assert storm_read((250, 250, 0), proven, minor)[0] is Label.UNNAMED
    # On a plain morning the size gate does not apply (as in the archive and S7-L).
    plain = read_set(
        pt_morning({"tegna-krem": [(40, 40, 0)]}), directory=one_district(), coverage=proven,
        recent={"tegna-krem": 3}, rule=RULE, weather=[WeatherClass.NONE],
        stats=ListStats.of(proven, quiet, RULE.labels.station_min_captures),
    )  # fmt: skip
    assert isinstance(plain[METHOW], Read)


def test_a_list_the_archive_barely_caught_reads_storm_days_only_after_storm_size_lists() -> None:
    # The archive caught the list once (2 rows); 20 live days hold populated reads of it, none
    # a closing-size day. As a proven county list it is not tier B (lead ruling B1.4: only
    # closing-size days count toward its five captures).
    thin = replace(COUNTY, captures={"tegna-krem": 1}, rows={"tegna-krem": (2,)})
    quiet = LiveCaptures(days={"tegna-krem": 20})
    assert storm_read((40, 40, 0), thin, quiet) == (Label.NOT_READ, "not_covered")
    # Carrying the district (tier A), it passes the station gate's five captures, but its
    # closing-size length is not known, so no populated read of it counts on a storm day
    # without a market peer to vouch for its length (lead ruling B1.2).
    carried = replace(thin, archive={"tegna-krem": frozenset({METHOW})})
    assert storm_read((40, 40, 0), carried, quiet) == (Label.NOT_READ, "small_capture")
    assert storm_read((40, 40, 0), carried, quiet, WeatherClass.ADVISORY)[1] == "small_capture"
    # Four closing-size days of about 276 rows give it a reference (and tier B): 40 rows is
    # partial, 250 whole.
    stormy = LiveCaptures(days={"tegna-krem": 20}, storm_rows={"tegna-krem": (270, 276, 280, 290)})
    assert storm_read((40, 40, 0), thin, stormy) == (Label.NOT_READ, "small_capture")
    assert storm_read((250, 250, 0), thin, stormy)[0] is Label.UNNAMED


def test_each_earlier_day_s_storm_lists_come_from_its_snapshot(tmp_path: Path) -> None:
    seen: dict[date, dict[date, set[str]]] = {}

    class Recording(ReadingSource):
        def captures(self, day: date, days: int, closing: Closing | None = None) -> LiveCaptures:
            assert closing is not None
            seen[day] = {
                when: set(closing.districts(when)) for when in (MONDAY, DAY - timedelta(days=9))
            }
            return super().captures(day, days, closing)

    shown_monday = world.timeline().model_copy(update={"day": MONDAY})
    source = Recording({DAY: world.timeline(), MONDAY: shown_monday})
    read_new_days(
        tmp_path / "reads", source, directory=learn.directory_of(built()),
        coverage=coverage_kc(), snapshots={**snapshots_for(DAY), **snapshots_for(MONDAY)},
        config=SHORT, now=world.utc("2026-01-08T06:00:00"),
    )  # fmt: skip
    # The 5th's snapshot put the TV list's districts under a warning, and the map lit two of
    # them: a list naming both still names under three (lead ruling C2). A day with no
    # snapshot has none (its reads never count).
    assert seen[DAY] == {MONDAY: {"2900001", "2900003"}, DAY - timedelta(days=9): set()}


def closing_storms(lit: Lit | None) -> Callable[[date], AbstractSet[str]]:
    weather = SHORT.weather
    return _Storms(
        {**snapshots_for(DAY), **snapshots_for(MONDAY)}, learn.directory_of(built()),
        Window(weather.window_from, weather.window_until, weather.snapshot_hour),
        timedelta(minutes=SHORT.learn.snapshot_slack_minutes),
        lit=lambda when: lit if when == MONDAY else None, settings=RULE.labels,
    )  # fmt: skip


def test_a_day_s_closing_districts_are_warned_and_lit() -> None:
    # SYNTHETIC: 2000004, 2900001 and 2900002 are under a snow warning on the 5th. Schools 5,
    # 0 and 2 are theirs.
    def lit(*schools: int, status: Status = Status.CLOSED) -> Lit:
        found = {s: LitStatus(status=status, reason=Reason.WINTER_STORM) for s in schools}
        return Lit(found, frozenset())

    three = {"2000004", "2900001", "2900002"}
    assert closing_storms(lit(5, 0, 1, 2))(MONDAY) == three
    # Delays count: the list runs long on a delay morning too.
    assert closing_storms(lit(5, 0, 1, 2, status=Status.DELAYED))(MONDAY) == three
    # A day the map is not known, or a day with no snapshot, has none.
    assert closing_storms(None)(MONDAY) == set()
    assert closing_storms(lit(5, 0, 1, 2))(DAY - timedelta(days=9)) == set()


def test_an_advisory_or_cold_day_is_never_closing_size() -> None:
    # SYNTHETIC: the same three districts lit, under an advisory or a cold warning: none is a
    # closing district, so no list's reads that day count.
    weather = SHORT.weather
    lit = Lit(
        {s: LitStatus(status=Status.CLOSED, reason=Reason.WINTER_STORM) for s in (5, 0, 1, 2)},
        frozenset(),
    )
    for klass in (WeatherClass.ADVISORY, WeatherClass.COLD):
        storms = _Storms(
            snapshots_for(MONDAY, klass), learn.directory_of(built()),
            Window(weather.window_from, weather.window_until, weather.snapshot_hour),
            timedelta(minutes=SHORT.learn.snapshot_slack_minutes),
            lit=lambda _when: lit, settings=RULE.labels,
        )  # fmt: skip
        assert storms(MONDAY) == set()
    assert closing_storms(lit)(MONDAY) == {"2000004", "2900001", "2900002"}


def test_one_closing_size_test_for_archive_and_live() -> None:
    # Lead rulings C1 and C2: the list's OWN rows must name three distinct districts the
    # side's test holds (archive: warned that day or the next; live: warned and lit).
    lit = frozenset(WARNED)

    def live(leaid: str, _day: date) -> bool:
        return leaid in lit

    assert closing_size([(d, OCT28) for d in WARNED], live)
    assert not closing_size([(d, OCT28) for d in WARNED[:2]], live)
    # The same district named on two days is one district.
    assert not closing_size([(WARNED[0], OCT28), (WARNED[0], OCT28 + timedelta(days=1)),
                             (WARNED[1], OCT28)], live)  # fmt: skip
    # Districts the map lit that the list did not name never count for it.
    assert not closing_size([(WARNED[0], OCT28), ("5399999", OCT28), ("5399998", OCT28)], live)
    assert closing_size([], live, least=0)
    assert closing_size([(WARNED[0], OCT28)], live, least=1)


# --- round 3: trials are closures only, and their clustering is reported --------------------------


def test_a_district_lit_delayed_gives_no_trial() -> None:
    both = listed(
        Coverage(
            county_sources={OKANOGAN: ("flashalert-spokane", "tegna-krem")},
            archive={},
            county_of={METHOW: OKANOGAN},
        )
    )
    delayed = Lit({s: LitStatus(Status.DELAYED, Reason.WINTER_STORM) for s in (0, 1)}, frozenset())
    found = label_read_day(
        OCT28,
        morning=pt_morning({"tegna-krem": [WHOLE], "flashalert-spokane": [WHOLE]},
                           by={"tegna-krem": [METHOW]}),
        coverage=both, weather=[WeatherClass.ADVISORY], lit=delayed, directory=one_district(),
        rule=RULE, recent={"tegna-krem": 2, "flashalert-spokane": 2},
        lit_by={METHOW: {"tegna-krem": LIT_AT}},
    )  # fmt: skip
    (row,) = found.rows
    assert row.label is Label.DELAYED
    assert found.trials == []
    (advisory,) = found.audit.classes
    assert (advisory.lit_delayed, advisory.trials_b, advisory.hits_b) == (1, 0, 0)
    # Closed the same way, it is a trial.
    closed = label_read_day(
        OCT28,
        morning=pt_morning({"tegna-krem": [WHOLE], "flashalert-spokane": [WHOLE]},
                           by={"tegna-krem": [METHOW]}),
        coverage=both, weather=[WeatherClass.ADVISORY], lit=closed_lit([0, 1]),
        directory=one_district(), rule=RULE, recent={"tegna-krem": 2, "flashalert-spokane": 2},
        lit_by={METHOW: {"tegna-krem": LIT_AT}},
    )  # fmt: skip
    assert [(t.source, t.named) for t in closed.trials] == [("flashalert-spokane", False)]


def write_trials_day(folder: Path, day: date, trials: Sequence[Trial]) -> None:
    hits = sum(t.named for t in trials)
    counts = ReadClass.model_validate(
        {
            **ZERO,
            "weather": "advisory",
            "trials_b": len(trials),
            "hits_b": hits,
            "median_health": None,
        }
    )
    audit = ReadAuditDay(day=day, held=False, classes=(counts,))
    write_day(
        folder,
        ReadDay(schema_version=1, day=day, content="synthetic", rows=(), no_school=(),
                audit=audit),
        trials,
    )  # fmt: skip


def test_twenty_trials_from_one_list_on_one_morning_are_one_date(tmp_path: Path) -> None:
    # SYNTHETIC: twenty districts lit closed on one morning, all named by one other list.
    folder = tmp_path / "reads"
    trials = [
        Trial(district=f"53{i:05d}", source="flashalert-spokane", tier=Tier.B, named=True,
              weather=1)
        for i in range(20)
    ]  # fmt: skip
    write_trials_day(folder, OCT28, trials)
    audit = audit_of(folder, world.utc("2026-10-30T06:00:00"))
    report = report_of(folder, audit, RULE)
    tier_b = report.sensitivity[1]
    # The registered estimator, every trial independent: Beta(24, 2).
    assert (tier_b.trials, tier_b.hits, tier_b.mean) == (20, 20, round(24 / 26, 4))
    assert tier_b.low == pytest.approx(0.8239, abs=2e-4)
    # The record shows where they come from: one date, one list; by date, Beta(5, 2).
    assert (tier_b.dates, tier_b.lists) == (1, 1)
    assert tier_b.day_mean == round(5 / 7, 4)
    assert tier_b.day_low == pytest.approx(0.4182, abs=2e-4)
    # G1's tier B check needs five dates (lead ruling B1.5): one morning never meets it.
    assert not report.tier_b_g1
    (line,) = (x for x in read_cli.summary(audit, folder, report) if x.startswith("list sens"))
    assert "by date 0.418 to 0.937; 20 trials from 1 dates and 1 lists" in line
    assert (
        "not met (1 dates, 1 lists); by-date mean 0.714 (90% 0.418 to 0.937): at least 0.7" in line
    )
    # Five mornings of four trials each meet it.
    spread = tmp_path / "spread"
    for back in range(5):
        write_trials_day(spread, OCT28 - timedelta(days=7 * back), trials[:4])
    report = report_of(spread, audit_of(spread, world.utc("2026-10-30T06:00:00")), RULE)
    assert (report.sensitivity[1].trials, report.sensitivity[1].dates) == (20, 5)
    assert report.tier_b_g1


# --- round 3: thin empties, gated peers, dark unnamed ---------------------------------------------


def test_an_empty_read_of_a_thin_list_is_never_whole() -> None:
    # 'tv' carries Methow in the archive with two captures; it reads empty on an advisory
    # morning while a healthy, proven market peer reads populated.
    coverage = Coverage(
        county_sources={}, archive={"tv": frozenset({METHOW})},
        county_of={METHOW: OKANOGAN}, captures={"tv": 2, "radio": 10},
        rows={"tv": (3, 3), "radio": (10,) * 10}, min_captures=5,
    )  # fmt: skip
    morning = pt_morning(
        {"tv": [(0, 0, 0)], "radio": [(3, 3, 0)]}, market_of={"tv": "Spokane", "radio": "Spokane"}
    )
    assert methow(morning, coverage=coverage, recent={"tv": 1}) == (
        Label.NOT_READ, NotRead.THIN_STATION.value, None,
    )  # fmt: skip
    # Not on a plain day either.
    plain = read_set(
        morning, directory=one_district(), coverage=coverage, recent={"tv": 1}, rule=RULE,
        weather=[WeatherClass.NONE],
    )  # fmt: skip
    assert plain[METHOW] is NotRead.THIN_STATION


def test_only_a_gated_healthy_peer_corroborates_an_empty_list() -> None:
    proven = replace(SHORT_PEER, captures={"tegna-krem": 10, "flashalert-spokane": 2})
    # The peer is thin: its read counts for nothing, so the empty stays uncorroborated.
    thin_peer = pt_morning({"tegna-krem": [(0, 0, 0)], "flashalert-spokane": [(3, 3, 0)]})
    assert methow(thin_peer, coverage=proven) == (
        Label.NOT_READ, NotRead.EMPTY_UNCORROBORATED.value, None,
    )  # fmt: skip
    # A proven peer read in an unhealthy slot does not corroborate either.
    morning = pt_morning({"tegna-krem": [(0, 0, 0)]})
    late = slot_start(OCT28, "15:00")
    morning.slots[late].reads = {"flashalert-spokane": {(3, 3, 0)}}
    morning.slots[late].health = 800
    assert methow(morning)[1] == NotRead.EMPTY_UNCORROBORATED.value
    # Healthy, and a whole list of its own, it does.
    morning.slots[late].health = 950
    assert methow(morning, coverage=SHORT_PEER)[0] is Label.UNNAMED
    assert methow(morning)[1] == NotRead.EMPTY_UNCORROBORATED.value  # 3 of its usual 10


def many_schools(count: int = 20) -> Directory:
    return replace(one_district(), eligible=(np.arange(count, dtype=np.int64),))


def test_an_unnamed_district_with_a_school_lit_is_unknown_never_open() -> None:
    # One of twenty schools lit closed (an override, or a closing lit on an earlier log
    # day), no list naming the district: never open.
    found = label_read_day(
        OCT28, morning=pt_morning({"tegna-krem": [WHOLE]}), coverage=COUNTY,
        weather=[WeatherClass.ADVISORY], lit=closed_lit([0]), directory=many_schools(),
        rule=RULE, recent={"tegna-krem": 3},
    )  # fmt: skip
    (row,) = found.rows
    assert (row.label, row.why) == (Label.UNKNOWN, "partly_lit")
    dark = label_read_day(
        OCT28, morning=pt_morning({"tegna-krem": [WHOLE]}), coverage=COUNTY,
        weather=[WeatherClass.ADVISORY], lit=DARK, directory=many_schools(), rule=RULE,
        recent={"tegna-krem": 3},
    )  # fmt: skip
    assert dark.rows[0].label is Label.UNNAMED


# --- round 3: withheld states and unplaced rows are counted ---------------------------------------


def test_a_district_whose_state_was_withheld_is_counted_apart() -> None:
    morning = pt_morning({"tegna-krem": [WHOLE]})
    for slot in morning.slots.values():
        slot.unknown = {"WA"}
    found = label_read_day(
        OCT28, morning=morning, coverage=COUNTY, weather=[WeatherClass.ADVISORY], lit=DARK,
        directory=one_district(), rule=RULE, recent={"tegna-krem": 3},
    )  # fmt: skip
    (row,) = found.rows
    assert (row.label, row.why) == (Label.NOT_READ, "withheld_state")
    (advisory,) = found.audit.classes
    assert (advisory.withheld_state, advisory.no_whole_read) == (1, 0)
    # Another state's withholding leaves it read.
    for slot in morning.slots.values():
        slot.unknown = {"OR"}
    assert methow(morning)[0] is Label.UNNAMED


def test_an_unnamed_row_read_through_a_list_with_unplaced_rows_is_marked() -> None:
    found = label_read_day(
        OCT28, morning=pt_morning({"tegna-krem": [(10, 8, 0)]}), coverage=COUNTY,
        weather=[WeatherClass.ADVISORY], lit=DARK, directory=one_district(), rule=RULE,
        recent={"tegna-krem": 3},
    )  # fmt: skip
    (row,) = found.rows
    assert (row.label, row.unplaced) == (Label.UNNAMED, True)
    (advisory,) = found.audit.classes
    assert (advisory.unnamed, advisory.unnamed_unplaced) == (1, 1)
    whole = label_read_day(
        OCT28, morning=pt_morning({"tegna-krem": [WHOLE]}), coverage=COUNTY,
        weather=[WeatherClass.ADVISORY], lit=DARK, directory=one_district(), rule=RULE,
        recent={"tegna-krem": 3},
    )  # fmt: skip
    assert not whole.rows[0].unplaced
    assert whole.audit.classes[0].unnamed_unplaced == 0


# --- round 3: the step is bounded and keeps what it wrote -----------------------------------------


def test_a_run_labels_a_few_days_and_one_cut_off_keeps_what_it_wrote(tmp_path: Path) -> None:
    folder = tmp_path / "reads"
    now = world.utc("2026-01-08T06:00:00")
    shown_monday = world.timeline().model_copy(update={"day": MONDAY})
    snapshots = {**snapshots_for(DAY), **snapshots_for(MONDAY)}
    written: list[date] = []

    def run(source: ReadingSource, limit: int | None = None) -> Any:
        return read_new_days(
            folder, source, directory=learn.directory_of(built()), coverage=coverage_kc(),
            snapshots=snapshots, config=SHORT, now=now, limit=limit, on_added=written.append,
        )  # fmt: skip

    # One day a run: the oldest first, the next left for the next run.
    first = run(ReadingSource({DAY: world.timeline(), MONDAY: shown_monday}), limit=1)
    assert (first.added, written) == ([MONDAY], [MONDAY])
    assert first.skipped[LEFT] == 2  # the 6th, and the 7th

    # The next run is cut off after its day is written (the step's time limit): the day
    # stays written and was reported as it was written.
    class CutOff(ReadingSource):
        def lit_by(self, day: date) -> Mapping[str, Mapping[str, datetime]] | None:
            if day > DAY:
                raise KeyboardInterrupt  # pragma: no cover - never reached here
            return super().lit_by(day)

    second = run(CutOff({DAY: world.timeline(), MONDAY: shown_monday}))
    assert (second.added, written) == ([DAY], [MONDAY, DAY])
    assert labeled_days(folder) == [MONDAY, DAY]
    assert DAYS_PER_RUN == 5


def test_the_step_marks_a_day_added_as_soon_as_it_is_written(tmp_path: Path) -> None:
    outputs = tmp_path / "github-output"
    seen: list[str] = []

    class Interrupted(ReadingSource):
        def morning(self, day: date) -> Morning | str:
            if day == DAY:  # the second day: the step is cut off here
                seen.append(outputs.read_text())
                raise OSError("SYNTHETIC: cut off")
            return super().morning(day)

    shown_monday = world.timeline().model_copy(update={"day": MONDAY})
    run = replace(
        read_run(Host(), tmp_path / "reads", world.utc("2026-01-08T06:00:00")),
        source=Interrupted({DAY: world.timeline(), MONDAY: shown_monday}),
        outputs=outputs,
    )
    assert read_cli.read_once(run) == 1
    # added was set when the 5th was written, before the 6th was begun.
    assert seen == ["added=true\n"]
    assert labeled_days(tmp_path / "reads") == [MONDAY]


def test_a_run_reads_the_morning_record_and_change_log_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import snowlight.predict.live_read as module  # noqa: PLC0415

    source = methow_state(tmp_path / "state")
    calls: list[str] = []
    real_days, real_log = module.counted_days, module.LoadedChanges.of

    def days(log: MorningLog, closing: Closing, **kwargs: Any) -> dict[date, dict[str, int]]:
        calls.append("morning")
        return real_days(log, closing, **kwargs)

    def changes(log: ChangeLog) -> Any:
        calls.append("changes")
        return real_log(log)

    monkeypatch.setattr(module, "counted_days", days)
    monkeypatch.setattr(module.LoadedChanges, "of", changes)
    closing = closing_of(COUNTY, {OCT28: frozenset(WARNED)})
    for day in (OCT28, OCT28 + timedelta(days=1), OCT28 + timedelta(days=2)):
        source.captures(day, 366, closing)
        source.captures(day, 14, closing)
        source.lit_by(day)
        source.morning(day)
    assert sorted(calls) == ["changes", "morning"]
    # The fixture's KREM reads name nothing: no day of it counts (lead ruling C2).
    assert source.captures(OCT28 + timedelta(days=1), 366, closing) == LiveCaptures()


class ClockD1(FakeD1):
    """SYNTHETIC: D1 with the hard deadline the live client has and a clock each call
    moves on by ``step`` seconds."""

    def __init__(self, step: float) -> None:
        super().__init__()
        self.now = 0.0
        self.step = step
        self.deadline: float | None = None

    def monotonic(self) -> float:
        return self.now

    def run(self, database: str, statements: Sequence[Any]) -> list[Any]:
        if self.deadline is not None and self.now >= self.deadline:
            from snowlight.live.d1 import D1Error  # noqa: PLC0415

            raise D1Error("out of time")
        self.now += self.step
        return super().run(database, statements)


def test_the_read_labels_push_leaves_its_rest_for_the_next_run_before_the_deadline(
    tmp_path: Path, capsys: Any
) -> None:
    folder = tmp_path / "reads"
    assert read_cli.read_once(read_run(Host(), folder, world.utc("2026-01-08T06:00:00"))) == 0
    offers = cli.read_offers(folder)

    def store_of(api: ClockD1, first_takes: float) -> EvidenceStore:
        """A store whose first push (the snapshots, tables and labels) takes ``first_takes``
        seconds of the 45 the hard deadline gives both."""
        pushes: list[int] = []

        class Slow(EvidenceStore):
            def push(self, offers: Sequence[Any], kinds: Any) -> Any:
                found = super().push(offers, kinds)
                if not pushes:
                    api.now += first_takes
                pushes.append(1)
                return found

        store = Slow(api, {"GITHUB_WORKFLOW": "predict"}, lambda: RETENTION_NOW,
                     monotonic=api.monotonic)  # fmt: skip
        store.seconds = 30.0
        api.deadline = 45.0
        return store

    # The first push took 36 seconds: under 15 are left, so the read labels wait for the
    # next run, with no error and no write past the deadline.
    slow = ClockD1(step=0.5)
    store = store_of(slow, 36.0)
    capsys.readouterr()
    assert cli.keep_evidence(store, {}, {}, RETENTION_NOW, b"{}", reads=offers) == 0
    out = capsys.readouterr()
    assert "out of time" not in out.err
    assert "(read labels): 6 finished files offered" in out.out
    assert "they wait for the next run" in out.out
    assert store.seconds == 30.0
    # The first push took 20 seconds: the second gets what is left before the deadline,
    # less a margin, and stops on its own; the rest waits for the next run.
    tight = ClockD1(step=0.5)
    store = store_of(tight, 20.0)
    assert cli.keep_evidence(store, {}, {}, RETENTION_NOW, b"{}", reads=offers) == 0
    out = capsys.readouterr()
    assert "out of time" not in out.err
    assert "(read labels): 6 finished files offered, 1 held before, 2 kept" in out.out
    assert tight.now <= 45.0
    assert store.seconds == 30.0


# --- round 3: the hand audit ----------------------------------------------------------------------


def write_unnamed_day(folder: Path, day: date, districts: Sequence[str]) -> None:
    rows = tuple(
        ReadRow(district=d, weather=1, after=False, label=Label.UNNAMED, why=None, tier=Tier.B,
                market="Spokane", sources=("tegna-krem",), slot="14:00", health=950)
        for d in districts
    )  # fmt: skip
    counts = ReadClass.model_validate(
        {**ZERO, "weather": "advisory", "alerted": len(rows), "covered": len(rows),
         "read_b": len(rows), "unnamed": len(rows), "median_health": 950 if rows else None}
    )  # fmt: skip
    write_day(
        folder,
        ReadDay(schema_version=1, day=day, content="synthetic", rows=rows, no_school=(),
                audit=ReadAuditDay(day=day, held=False, classes=(counts,))),
        (),
    )  # fmt: skip


def test_the_hand_audit_draws_each_week_once_and_counts_false_opens(tmp_path: Path) -> None:
    folder = tmp_path / "reads"
    monday = date(2026, 11, 2)  # ISO week 2026-W45
    districts = [f"53{i:05d}" for i in range(40)]
    for offset in range(5):
        write_unnamed_day(folder, monday + timedelta(days=offset), districts)
    now = world.utc("2026-11-10T06:00:00")

    def report() -> HandAudit:
        return report_of(folder, audit_of(folder, now), RULE).hand_audit

    # Labeling has not passed the week yet: nothing is drawn.
    first = report()
    assert (first.unnamed, first.weeks, first.drawn, first.g1) == (200, 0, 0, False)
    # Once a day of the next week is labeled, the week's draw is made and kept.
    write_unnamed_day(folder, date(2026, 11, 9), districts[:3])
    drawn = report()
    assert (drawn.weeks, drawn.drawn, drawn.audited, drawn.rate) == (1, 50, 0, None)
    kept = (folder / "hand-audit" / "2026-W45.json").read_bytes()
    # A row added to the week later (never in practice: days are labeled in order) does not
    # move the draw.
    write_unnamed_day(folder, date(2026, 11, 7), [f"54{i:05d}" for i in range(40)])
    assert report().to_audit == drawn.to_audit
    assert (folder / "hand-audit" / "2026-W45.json").read_bytes() == kept
    # The results, entered by hand: 48 open, 2 not.
    lines = [
        json.dumps({"day": d.isoformat(), "district": n, "open": i >= 2})
        for i, (d, n) in enumerate(drawn.to_audit)
    ]
    (folder / "hand-audit" / "results.jsonl").write_text("\n".join(lines) + "\n")
    done = report()
    assert (done.audited, done.false_opens, done.rate, done.to_audit) == (50, 2, 0.04, ())
    assert done.low is not None
    assert done.high is not None
    assert done.low < 0.04 < done.high
    assert done.g1
    # A results line that does not read is an error, never a silent skip.
    (folder / "hand-audit" / "results.jsonl").write_text('{"day": "2026-11-02"}\n')
    with pytest.raises(ValueError, match=r"results\.jsonl line 1"):
        report()


# --- round 4: the lead's rulings (Addendum B1) ----------------------------------------------------


KREM_CARRIES: Final = {"tegna-krem": {METHOW: date(2026, 1, 5)}}
"""SYNTHETIC: the KREM list carries Methow (tier A, so its captures decide nothing of tier)."""


def thin_krem(peer_rows: int | None = None) -> Coverage:
    """SYNTHETIC: KREM caught once by the archive (2 rows); FlashAlert, a market peer proven
    for another county (so it never reads Methow itself), with ten closing-size captures of
    ``peer_rows`` (absent when ``None``)."""
    found = replace(
        COUNTY,
        archive=KREM_CARRIES,
        captures={"tegna-krem": 1},
        rows={"tegna-krem": (2,)},
    )
    if peer_rows is None:
        return found
    return replace(
        found,
        county_sources={**found.county_sources, "53063": ("flashalert-spokane",)},
        captures={**found.captures, "flashalert-spokane": 10},
        rows={**found.rows, "flashalert-spokane": (peer_rows,) * 10},
    )


def thin_read(  # noqa: PLR0913 - every part a test sets
    morning: Morning,
    coverage: Coverage,
    live: LiveCaptures,
    *,
    weather: WeatherClass = WeatherClass.SNOW_WARNING,
    lit: Lit = DARK,
    recent: Mapping[str, int] | None = None,
) -> tuple[Label, str | None]:
    found = label_read_day(
        OCT28, morning=morning, coverage=coverage, weather=[weather], lit=lit,
        directory=one_district(), rule=RULE, recent=recent or {"tegna-krem": 3}, live=live,
    )  # fmt: skip
    (row,) = found.rows
    return row.label, row.why


def test_four_advisory_days_never_set_a_thin_list_s_reference(tmp_path: Path) -> None:
    # Lead ruling B1.2's test. KREM: one archive capture of 2 rows, then four advisory days
    # of 3 to 5 rows in the live record. Advisory days are never closing-size (B1.1), so its
    # reference stays thin: a 40-row read on a warning morning with no market peer is not
    # whole, and Methow, missing from it, is never unnamed (never open).
    log = MorningLog(tmp_path / "morning")
    for back, rows in zip((1, 2, 5, 6), (3, 4, 5, 3), strict=True):
        record_on(log, OCT28 - timedelta(days=back), {"tegna-krem": (rows, rows, 0)},
                  by={"tegna-krem": WARNED[:1]})  # fmt: skip
    live = counted(log, closing_of(thin_krem(), frozenset()))  # advisory days
    assert live == LiveCaptures()
    stats = ListStats.of(thin_krem(), live, RULE.labels.station_min_captures)
    assert (stats.captures, stats.closing) == ({"tegna-krem": 1}, {"tegna-krem": 1})
    assert stats.thin == frozenset({"tegna-krem"})
    warning = pt_morning({"tegna-krem": [(40, 40, 0)]})
    # Lead ruling C2: the advisory days are no station captures either, so the list caught
    # once is too thin to read at all.
    assert thin_read(warning, thin_krem(), live) == (Label.NOT_READ, "thin_station")
    # Caught five times by the archive (once closing-size), it passes the station gate, and
    # the thin reference refuses the read.
    caught = replace(thin_krem(), captures={"tegna-krem": 5})
    assert thin_read(warning, caught, live) == (Label.NOT_READ, "small_capture")
    blizzard = pt_morning({"tegna-krem": [(8, 8, 0)]})
    assert thin_read(blizzard, caught, live, weather=WeatherClass.BLIZZARD)[1] == ("small_capture")
    # Had the advisory days been counted (the round-3 rule), the reference would be 3 rows and
    # the 40-row read whole: the case the ruling closes.
    forced = LiveCaptures(days={"tegna-krem": 4}, storm_rows={"tegna-krem": (3, 3, 4, 5)})
    assert ListStats.of(thin_krem(), forced, 5).median_rows["tegna-krem"] == 3.0
    # A district the map lit closed is not read from it either: dropping only the unnamed
    # districts of a thin read would bias the labels toward closings, so the read is not
    # whole for any district (the outcome-blind reading of "may" in B1.2).
    lit = thin_read(warning, caught, live, lit=closed_lit([0, 1]))
    assert lit == (Label.NOT_READ, "small_capture")


def test_a_market_peer_s_whole_read_vouches_for_a_thin_list_s_length() -> None:
    # SYNTHETIC: FlashAlert (ten closing-size captures of 60 rows) read 60 rows whole and
    # healthy in Methow's window; KREM's thin reference is corroborated when its read holds
    # at least half of that (capture_min_share).
    live = LiveCaptures(days={"tegna-krem": 4})
    recent = {"tegna-krem": 3, "flashalert-spokane": 3}

    def read(rows: int, peer: int, health: int = 950) -> tuple[Label, str | None]:
        morning = pt_morning({"tegna-krem": [(rows, rows, 0)]})
        late = slot_start(OCT28, "15:00")
        morning.slots[late].reads = {"flashalert-spokane": {(peer, peer, 0)}}
        morning.slots[late].health = health
        morning.slots[late].by = {"flashalert-spokane": set()}
        return thin_read(morning, thin_krem(60), live, recent=recent)

    assert read(40, 60) == (Label.UNNAMED, None)
    assert read(30, 60) == (Label.UNNAMED, None)
    assert read(25, 60) == (Label.NOT_READ, "small_capture")
    # A peer read that fails its own size gate (under half its 60), or sits in an unhealthy
    # slot, vouches for nothing.
    assert read(12, 20) == (Label.NOT_READ, "small_capture")
    assert read(40, 60, health=800) == (Label.NOT_READ, "small_capture")
    # On a warning morning a peer still holding an earlier day's rows (naming nothing for the
    # day while its market names districts) vouches for nothing.
    morning = pt_morning({"tegna-krem": [(40, 40, 0)]}, by={"tegna-krem": ["5300002"]})
    late = slot_start(OCT28, "15:00")
    morning.slots[late].reads = {"flashalert-spokane": {(60, 60, 0)}}
    morning.slots[late].by = {"flashalert-spokane": set()}
    assert thin_read(morning, thin_krem(60), live, recent=recent) == (
        Label.NOT_READ, "small_capture",
    )  # fmt: skip
    morning.slots[late].by = {"flashalert-spokane": {"5300003"}}
    assert thin_read(morning, thin_krem(60), live, recent=recent) == (Label.UNNAMED, None)
    # A peer with a thin reference of its own vouches for nothing either.
    thin_peer = replace(thin_krem(60), rows={**thin_krem(60).rows, "flashalert-spokane": (60,)})
    morning = pt_morning({"tegna-krem": [(40, 40, 0)], "flashalert-spokane": [(60, 60, 0)]})
    assert thin_read(morning, thin_peer, live, recent=recent) == (
        Label.NOT_READ, "small_capture",
    )  # fmt: skip


def test_a_list_still_holding_yesterday_s_rows_on_a_warning_morning_is_refused() -> None:
    # Lead ruling B1.3. SYNTHETIC: KREM (five closing-size captures of 276 rows) reads 276
    # rows whole on a snow-warning morning, none of them for the day (by is empty), while
    # FlashAlert, in its market, names districts for it: stale_populated, never unnamed.
    proven = replace(COUNTY, captures={"tegna-krem": 5}, rows={"tegna-krem": (276,) * 5})
    by = {"tegna-krem": [], "flashalert-spokane": ["5300001"]}
    stale = pt_morning({"tegna-krem": [(276, 276, 0)], "flashalert-spokane": [(9, 9, 0)]}, by=by)
    assert methow(stale, coverage=proven, weather=WeatherClass.SNOW_WARNING) == (
        Label.NOT_READ, NotRead.STALE_POPULATED.value, None,
    )  # fmt: skip
    for klass in (WeatherClass.ICE, WeatherClass.BLIZZARD, WeatherClass.LAKE_SNOW):
        assert methow(stale, coverage=proven, weather=klass)[1] == "stale_populated"
    # Naming a district for the day, the same read is whole.
    fresh = pt_morning(
        {"tegna-krem": [(276, 276, 0)], "flashalert-spokane": [(9, 9, 0)]},
        by={**by, "tegna-krem": ["5300002"]},
    )
    assert methow(fresh, coverage=proven, weather=WeatherClass.SNOW_WARNING)[0] is Label.UNNAMED
    # The ruling covers warning-or-above mornings with closings in the market only.
    assert methow(stale, coverage=proven, weather=WeatherClass.ADVISORY)[0] is Label.UNNAMED
    quiet = pt_morning({"tegna-krem": [(276, 276, 0)]}, by={"tegna-krem": []})
    assert methow(quiet, coverage=proven, weather=WeatherClass.SNOW_WARNING)[0] is Label.UNNAMED


def test_a_trial_keeps_whether_the_list_named_the_district_anywhere_in_the_day() -> None:
    # SYNTHETIC: KREM lit Methow; FlashAlert read whole at 07:00 PT without it and named it
    # at 08:30 PT in an unhealthy slot. The registered estimand (a qualifying slot) is a
    # miss; the day's (what the unnamed rule turns on) is a hit.
    both = listed(
        Coverage(
            county_sources={OKANOGAN: ("flashalert-spokane", "tegna-krem")},
            archive={},
            county_of={METHOW: OKANOGAN},
        )
    )
    morning = pt_morning(
        {"tegna-krem": [(10, 10, 0)], "flashalert-spokane": [(10, 10, 0)]},
        by={"tegna-krem": [METHOW], "flashalert-spokane": []},
    )
    late = slot_start(OCT28, "15:30")
    morning.slots[late].reads = {"flashalert-spokane": {(11, 11, 0)}}
    morning.slots[late].by = {"flashalert-spokane": {METHOW}}
    morning.slots[late].health = 800
    found = label_read_day(
        OCT28, morning=morning, coverage=both, weather=[WeatherClass.ADVISORY],
        lit=closed_lit([0, 1]), directory=one_district(), rule=RULE,
        recent={"tegna-krem": 2, "flashalert-spokane": 2},
        lit_by={METHOW: {"tegna-krem": LIT_AT}},
    )  # fmt: skip
    assert [(t.source, t.named, t.named_in_day) for t in found.trials] == [
        ("flashalert-spokane", False, True)
    ]


def test_the_report_gives_both_estimands_and_never_claims_g1_on_a_lost_record(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "reads"
    for back in range(6):
        trials = [
            Trial(district=f"53{i:05d}", source=f"list-{back}", tier=Tier.B, named=i > 0,
                  weather=5, named_in_day=True)
            for i in range(4)
        ]  # fmt: skip
        write_trials_day(folder, OCT28 - timedelta(days=7 * back), trials)
    audit = audit_of(folder, world.utc("2026-10-30T06:00:00"))
    report = report_of(folder, audit, RULE)
    tier_b = report.sensitivity[1]
    assert (tier_b.trials, tier_b.hits, tier_b.dates, tier_b.lists) == (24, 18, 6, 6)
    assert (tier_b.in_day_trials, tier_b.in_day_hits) == (24, 24)
    assert tier_b.in_day_mean > tier_b.mean
    assert (report.incomplete, report.tier_b_g1) == (0, True)
    # The Actions cache loses two days; the published audit keeps them. The totals stay, the
    # dates and lists cannot be told, so G1 is not claimed and the log says why.
    for lost in (OCT28, OCT28 - timedelta(days=7)):
        for path in folder.rglob(f"{lost.isoformat()}.*"):
            path.unlink()
    after = report_of(folder, audit, RULE)
    assert (after.sensitivity[1].trials, after.sensitivity[1].dates) == (24, 4)
    assert (after.incomplete, after.tier_b_g1) == (2, False)
    (line,) = (x for x in read_cli.summary(audit, folder, after) if x.startswith("list sens"))
    assert "not met (4 dates, 4 lists); by-date mean " in line
    assert f"of {BY_DATE_LISTS}); record incomplete: 2 days" in line


def test_the_report_reads_the_current_season_only(tmp_path: Path) -> None:
    folder = tmp_path / "reads"
    trial = Trial(district="5300001", source="tv", tier=Tier.B, named=True, weather=5)
    write_trials_day(folder, date(2026, 2, 2), [trial] * 3)  # last season
    write_trials_day(folder, OCT28, [trial])
    audit = audit_of(folder, world.utc("2026-10-30T06:00:00"))
    report = report_of(folder, audit, RULE, date(2026, 8, 1))
    assert (report.since, report.days, report.sensitivity[1].trials) == (date(2026, 8, 1), 1, 1)
    assert report_of(folder, audit, RULE) == report  # the audit's last day's season
    # One season start for the piece (review R5-E5, lead ruling C4): Aug 1, not July 1.
    assert live_read_module.season_of(date(2026, 7, 31)) == date(2025, 8, 1)
    assert live_read_module.season_of(date(2026, 8, 1)) == date(2026, 8, 1)
    # The public audit keeps every season.
    assert [item.day for item in audit.days] == [date(2026, 2, 2), OCT28]


def test_a_host_with_no_audit_after_one_was_published_is_an_error(
    tmp_path: Path, capsys: Any
) -> None:
    folder = tmp_path / "reads"
    now = world.utc("2026-01-08T06:00:00")
    assert read_cli.read_once(read_run(Host(), folder, now)) == 0
    assert (folder / read_cli.PUBLISHED_MARK).is_file()
    capsys.readouterr()
    # The host answers with no audit (a wrong prefix, a listing glitch): nothing is labeled
    # and nothing published, so no published day is dropped.
    empty = Host()
    assert read_cli.read_once(read_run(empty, folder, now + timedelta(days=1))) == 1
    assert "the host holds no predictions/read-audit.json, though this record" in (
        capsys.readouterr().err
    )
    assert empty.writes == 0


def test_a_day_is_marked_added_before_its_files_are_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = tmp_path / "github-output"

    def cut_off(*_args: object) -> None:
        raise OSError("SYNTHETIC: cut off while writing")

    monkeypatch.setattr("snowlight.predict.live_read.write_day", cut_off)
    run = replace(
        read_run(Host(), tmp_path / "reads", world.utc("2026-01-08T06:00:00")), outputs=outputs
    )
    assert read_cli.read_once(run) == 1
    # Cut off between the mark and the files: the cache is still saved (an unchanged folder).
    assert outputs.read_text() == "added=true\n"


def test_the_committed_coverage_files_hold_codes_and_counts_only() -> None:
    # Lead ruling B1.7: both files are committed and hold codes only (county FIPS, NCES
    # LEAIDs, station ids already public in config/sources) with capture counts and the
    # closing-size captures' row counts; no date, no name, no text from a list or a page.
    stations = set(load_registry().stations)
    proven = load_read_sources()
    carried = load_audiences()
    assert proven.present
    assert carried
    sources = set(proven.captures) | set(proven.rows) | set(carried)
    sources |= {s for found in proven.counties.values() for s in found}
    assert sources <= stations
    assert all(len(c) == 5 and c.isdigit() for c in proven.counties)
    assert all(len(rows) <= proven.captures[s] for s, rows in proven.rows.items())
    assert all(r > 0 for rows in proven.rows.values() for r in rows)
    districts = {d for found in carried.values() for d in found}
    assert all(len(d) == 7 and d.isdigit() for d in districts)
    # No date anywhere (lead ruling C4: the season bound is applied at build time).
    for path in (live_read_module.READ_SOURCES_PATH, live_read_module.AUDIENCES_PATH):
        text = gzip.decompress(path.read_bytes()).decode()
        assert re.search(r"(19|20)\d\d-\d\d", text) is None, path.name
    found = json.loads(gzip.decompress(live_read_module.AUDIENCES_PATH.read_bytes()))
    assert found["audience_seasons"] == read_cli.AUDIENCE_SEASONS == 2
    # Review R6-S4: the build season, a season code (the year of its Aug 1), is the one year
    # the file holds: built Oct 31, 2026, it is current until Aug 1, 2027.
    season = live_read_module.load_audience_season()
    assert season == found.pop("season") == 2026
    assert {k: v for k, v in found.items() if k != "audiences"} == {
        "audience_days": 2, "audience_seasons": 2, "schema_version": 3,
    }  # fmt: skip
    assert live_read_module.audiences_current(season, date(2027, 7, 31))
    assert not live_read_module.audiences_current(season, date(2027, 8, 1))


# --- round 5: closing-size archive captures, thin empties, old populated lists --------------------


def test_only_archive_captures_naming_three_warned_districts_are_closing_size() -> None:
    # An archive capture is a snapshot of any hour of any day; it is closing-size only when its
    # own rows named at least three districts under a warning-or-above class that day (or the
    # next: an evening capture lists the next morning's closings).
    day = date(2024, 1, 16)
    warned = {(f"29000{i:02d}", day): WeatherClass.SNOW_WARNING for i in range(5)}
    weather = {**warned, ("2900009", day): WeatherClass.ADVISORY}
    weather[("2900010", day + timedelta(days=1))] = WeatherClass.BLIZZARD
    weather[("2900011", day + timedelta(days=1))] = WeatherClass.ICE
    weather[("2900012", day + timedelta(days=1))] = WeatherClass.LAKE_SNOW
    named = {
        ("tv", "storm"): {(f"29000{i:02d}", day) for i in range(3)},
        ("tv", "two"): {("2900000", day), ("2900001", day)},
        ("tv", "advisory"): {("2900000", day), ("2900001", day), ("2900009", day)},
        ("tv", "evening"): {("2900010", day), ("2900011", day), ("2900012", day)},
        ("tv", "august"): {("2900000", date(2025, 8, 21)), ("2900001", date(2025, 8, 21)),
                           ("2900002", date(2025, 8, 21))},
        ("tv", "church"): set(),
    }  # fmt: skip
    assert closing_captures(named, weather) == {("tv", "storm"): day, ("tv", "evening"): day}
    # Cold is not a warning-or-above class of the size gate (B1.1's classes).
    cold = {**weather, **dict.fromkeys(warned, WeatherClass.COLD)}
    assert closing_captures(named, cold) == {("tv", "evening"): day}


GRAY_WFSB_ROWS: Final = (1, 1, 2, 3, 3, 232, 598, 761, 931)
"""The rows of one real list's nine populated archive captures (its public station id is
gray-wfsb): five quiet-day pages of 1 to 3 rows, four storm lists of 232 to 931 rows."""


def wfsb_like(tmp_path: Path) -> Coverage:
    """KREM's place in the fixture with gray-wfsb's archive captures, built the way the
    coverage build builds them: the four storm lists named three warned districts each."""
    reads = tmp_path / "reads.jsonl"
    stamps = [f"20{15 + i}-01-10T12:00:00Z" for i in range(len(GRAY_WFSB_ROWS))]
    reads.write_text(
        "\n".join(
            json.dumps(
                {"source_id": "tegna-krem", "state": "populated", "rows": rows, "fetched_at": stamp}
            )
            for rows, stamp in zip(GRAY_WFSB_ROWS, stamps, strict=True)
        )
        + "\n"
    )
    weather = {}
    named: dict[tuple[str, str], set[tuple[str, date]]] = {}
    for rows, stamp in zip(GRAY_WFSB_ROWS, stamps, strict=True):
        day = date.fromisoformat(stamp[:10])
        districts = {(f"09000{i:02d}", day) for i in range(min(rows, 3))}
        named[("tegna-krem", stamp)] = districts
        for leaid, _day in districts:
            # The quiet pages were caught on quiet days; the storm lists under a warning.
            stormy = rows > 100
            weather[(leaid, day)] = WeatherClass.SNOW_WARNING if stormy else WeatherClass.NONE
    closing = closing_captures(named, weather)
    coverage = {"proven": {"counties": {OKANOGAN: {"proven": ["tegna-krem"]}}}}
    path = tmp_path / "read-sources.json.gz"
    path.write_bytes(read_cli.read_sources_of(coverage, reads, 5, closing))
    proven = load_read_sources(path)
    return replace(COUNTY, captures=dict(proven.captures), rows=dict(proven.rows))


def test_a_list_the_archive_caught_mostly_on_quiet_days_never_reads_a_short_list_whole(
    tmp_path: Path,
) -> None:
    # Round-4 review R4-B1: every archive capture used to enter the reference, and with the
    # median of all nine (3 rows) a 2-row read on a warning morning passed the size gate
    # (1.5 rows): Methow, missing from a truncated list, was labeled unnamed (open).
    coverage = wfsb_like(tmp_path)
    assert coverage.captures == {"tegna-krem": 9}
    assert coverage.rows == {"tegna-krem": (232, 598, 761, 931)}
    nothing = LiveCaptures(days={})
    # Four closing-size captures: no tier B list (B1.4 asks five) ...
    assert storm_read((2, 2, 0), coverage, nothing) == (Label.NOT_READ, "not_covered")
    # ... and, carried (tier A), a thin reference: a 2-row warning-morning read with no peer
    # to vouch for its length is small_capture, on a blizzard morning too.
    carried = replace(coverage, archive={"tegna-krem": frozenset({METHOW})})
    for klass in (WeatherClass.SNOW_WARNING, WeatherClass.BLIZZARD, WeatherClass.ADVISORY):
        assert storm_read((2, 2, 0), carried, nothing, klass) == (Label.NOT_READ, "small_capture")
    # A fifth closing-size day (live) gives it a reference of 761 rows: 2 rows is partial,
    # a storm-size list whole.
    live = LiveCaptures(days={"tegna-krem": 1}, storm_rows={"tegna-krem": (800,)})
    stats = ListStats.of(coverage, live, RULE.labels.station_min_captures)
    assert stats.median_rows["tegna-krem"] == 761.0
    assert storm_read((2, 2, 0), coverage, live) == (Label.NOT_READ, "small_capture")
    assert storm_read((700, 700, 0), coverage, live)[0] is Label.UNNAMED


def test_a_peer_whose_archive_holds_only_quiet_pages_vouches_for_nothing() -> None:
    # Round-4 review probe P4: a peer with a KCNC-like archive (captures of 1, 1, 1, 3 and 19
    # rows, one of them closing-size) has a thin reference itself: its 2-row read passes no
    # size gate, so it never vouches for KREM's 1-row read.
    peer = replace(
        thin_krem(),
        county_sources={**COUNTY.county_sources, "53063": ("flashalert-spokane",)},
        captures={"tegna-krem": 1, "flashalert-spokane": 5},
        rows={"tegna-krem": (2,), "flashalert-spokane": (19,)},
    )
    morning = pt_morning({"tegna-krem": [(1, 1, 0)], "flashalert-spokane": [(2, 2, 0)]})
    live = LiveCaptures(days={"tegna-krem": 4})
    recent = {"tegna-krem": 3, "flashalert-spokane": 3}
    assert thin_read(morning, peer, live, recent=recent) == (Label.NOT_READ, "small_capture")


def test_a_thin_list_s_empty_read_beside_a_peer_naming_closures_is_not_whole() -> None:
    # Round-4 review R4-B2 (lead ruling B1.2 for an empty list). SYNTHETIC: KREM (a thin
    # reference: one archive capture, four live days) reads empty on a warning morning;
    # FlashAlert, a gated market peer (ten closing-size captures of 4 rows), reads 3 rows
    # in the window. Zero rows is not half of 3: KREM's empty is never whole, so Methow is
    # never unnamed (open) from it.
    live = LiveCaptures(days={"tegna-krem": 4})
    recent = {"tegna-krem": 3, "flashalert-spokane": 3}

    def read(peer: int) -> tuple[Label, str | None]:
        morning = pt_morning(
            {"tegna-krem": [(0, 0, 0)], "flashalert-spokane": [(peer, peer, 0)]},
            by={"flashalert-spokane": ["5300003"] if peer else []},
        )
        return thin_read(morning, thin_krem(4), live, recent=recent)

    assert read(3) == (Label.NOT_READ, "small_capture")
    assert read(4) == (Label.NOT_READ, "small_capture")
    # A peer list of 5 rows voids the empty (market_rows_void), as before.
    assert read(5) == (Label.NOT_READ, "voided_empty")
    # Beside a peer that read empty too, it is not whole either (review R6-B1): only a
    # populated read at least half its own reference vouches (PeerVouch), and 0 rows is
    # never half of that.
    assert read(0) == (Label.NOT_READ, "small_capture")
    # A list with a reference of its own (five closing-size captures) keeps the registered
    # rule: its empty beside a 3-row peer is whole (the void is market_rows_void's).
    proven = replace(thin_krem(4), rows={**thin_krem(4).rows, "tegna-krem": (10,) * 5})
    morning = pt_morning({"tegna-krem": [(0, 0, 0)], "flashalert-spokane": [(3, 3, 0)]})
    assert thin_read(morning, proven, live, recent=recent) == (Label.UNNAMED, None)


def test_a_populated_list_of_old_rows_is_refused_on_every_morning() -> None:
    # Round-4 review R4-S1. SYNTHETIC: KREM (five closing-size captures of 276 rows) reads 276
    # rows whole, and the reader judged them old (every row dated before the day before: the
    # record's stale). On any morning, warning, advisory, cold or plain, and in a market
    # where no other list named anything, its districts are not labeled from it.
    proven = replace(COUNTY, captures={"tegna-krem": 5}, rows={"tegna-krem": (276,) * 5})
    old = pt_morning({"tegna-krem": [(276, 276, 0)]}, by={"tegna-krem": []})
    old.slots[slot_start(OCT28, "14:00")].stale = {"tegna-krem"}
    for klass in (WeatherClass.SNOW_WARNING, WeatherClass.ADVISORY, WeatherClass.COLD):
        assert methow(old, coverage=proven, weather=klass) == (
            Label.NOT_READ, NotRead.STALE_POPULATED.value, None,
        )  # fmt: skip
    plain = read_set(
        old, directory=one_district(), coverage=proven, recent={"tegna-krem": 3}, rule=RULE,
        weather=[WeatherClass.NONE],
    )  # fmt: skip
    assert plain[METHOW] is NotRead.STALE_POPULATED
    # Not judged old, the same read is whole.
    fresh = pt_morning({"tegna-krem": [(276, 276, 0)]}, by={"tegna-krem": []})
    assert methow(fresh, coverage=proven, weather=WeatherClass.ADVISORY)[0] is Label.UNNAMED


def test_a_capture_s_reference_value_is_the_day_s_largest_gated_read(tmp_path: Path) -> None:
    # Round-4 review R4-S3: a read the replay step would drop (over a quarter unread, or under
    # half its list's median share placed) never sets a closing-size day's value.
    log = MorningLog(tmp_path / "morning")
    proven = replace(COUNTY, captures={"tegna-krem": 5}, rows={"tegna-krem": (100,) * 5})
    for back in range(1, 6):
        record_on(log, OCT28 - timedelta(days=back), {"tegna-krem": (100, 95, 0)},
                  by={"tegna-krem": WARNED})  # fmt: skip
    # 900 rows, 40% unread; 600 rows, 5% placed: both dropped. 120 rows read whole.
    for at, read in (("14:30", (900, 500, 360)), ("15:00", (600, 30, 0)),
                     ("15:30", (120, 115, 0))):  # fmt: skip
        record_on(log, OCT28 - timedelta(days=1), {"tegna-krem": read},
                  by={"tegna-krem": WARNED}, at=at)  # fmt: skip
    found = counted(log, closing_of(proven))
    assert found.storm_rows == {"tegna-krem": (100, 100, 100, 100, 120)}
    # A day whose only reads were dropped is no capture at all.
    lone = MorningLog(tmp_path / "lone")
    record_on(lone, OCT28 - timedelta(days=1), {"tegna-krem": (900, 500, 360)},
              by={"tegna-krem": WARNED}, at="14:30")  # fmt: skip
    assert counted(lone, closing_of(proven)) == LiveCaptures()


def test_g1_met_by_trials_and_not_by_date_says_so(tmp_path: Path) -> None:
    # Round-4 review E-R4-3. SYNTHETIC: 16 hits on one storm morning from one list, and one
    # miss on each of four other dates from another: the registered check holds (s_B 0.769,
    # 20 trials, 5 dates) while the day-aggregated interval lies under 0.7.
    folder = tmp_path / "reads"
    storm = [
        Trial(district=f"53{i:05d}", source="flashalert-spokane", tier=Tier.B, named=True,
              weather=5)
        for i in range(16)
    ]  # fmt: skip
    write_trials_day(folder, date(2026, 11, 18), storm)
    for i, day in enumerate((3, 5, 10, 12)):
        miss = Trial(district=f"54{i:05d}", source="tegna-krem", tier=Tier.B, named=False,
                     weather=1)  # fmt: skip
        write_trials_day(folder, date(2026, 11, day), [miss])
    audit = audit_of(folder, world.utc("2026-11-20T06:00:00"))
    report = report_of(folder, audit, RULE)
    tier_b = report.sensitivity[1]
    assert (tier_b.trials, tier_b.dates, tier_b.lists) == (20, 5, 2)
    assert tier_b.mean >= RULE.tier_b_min > tier_b.day_high
    assert tier_b.day_mean == round(5 / 11, 4) < RULE.tier_b_min  # Beta(4 + 1, 2 + 4)
    assert (report.tier_b_g1, report.tier_b_not_by_date) == (True, True)
    assert (report.tier_b_lists, report.tier_b_by_date_gates) == (2, False)
    (line,) = (x for x in read_cli.summary(audit, folder, report) if x.startswith("list sens"))
    assert "met by trials, not by date (5 dates, 2 lists); by-date mean " in line
    assert line.endswith(
        "under 0.7 (diagnostic, tier B trials from 2 lists, 0 lists tier B now, "
        f"of {BY_DATE_LISTS})"
    )
    # Review R6-S3: the ruling's 20 tier B lists are the lists that are tier B, when more
    # are than give trials: with 20 tier B lists the by-date mean gates, and G1 is not met.
    gated = report_of(folder, audit, RULE, lists_now=BY_DATE_LISTS)
    assert (gated.tier_b_lists, gated.tier_b_lists_now) == (2, BY_DATE_LISTS)
    assert gated.tier_b_by_date_gates
    assert (gated.tier_b_g1, gated.tier_b_not_by_date) == (False, True)
    assert not report_of(folder, audit, RULE, lists_now=BY_DATE_LISTS - 1).tier_b_by_date_gates
    # Spread over five mornings, the same hits meet it by date too.
    spread = tmp_path / "spread"
    for back in range(5):
        write_trials_day(spread, date(2026, 11, 18) - timedelta(days=7 * back), storm[:4])
    report = report_of(spread, audit_of(spread, world.utc("2026-11-20T06:00:00")), RULE)
    assert (report.tier_b_g1, report.tier_b_not_by_date) == (True, False)


def test_the_audit_is_published_before_the_private_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    # Round-4 review R4-LS-2: a report that fails (or a step cut off while making it) costs
    # the private summary only; the days labeled are already in the public audit.
    def broken(*_args: object, **_kwargs: object) -> ReadReport:
        raise ValueError("cut off")

    monkeypatch.setattr(live_read_module, "report_of", broken)
    host = Host()
    assert (
        read_cli.read_once(read_run(host, tmp_path / "reads", world.utc("2026-01-08T06:00:00")))
        == 1
    )
    audit = ReadAudit.from_json_bytes(host.files["v1/predictions/read-audit.json"])
    assert [d.day for d in audit.days] == [MONDAY, DAY]
    assert "error: the private report: ValueError" in capsys.readouterr().err


def test_no_committed_list_reads_storm_days_against_a_quiet_day_reference() -> None:
    # Round-4 review R4-B1 on the committed file: the lists the review found with 1- to
    # 3-row references (their archive's quiet pages) have under 5 closing-size captures, so a
    # thin reference, and no list with 5 has a reference of 10 rows or fewer.
    proven = load_read_sources()
    ready = {s: rows for s, rows in proven.rows.items() if len(rows) >= RULE.min_captures}
    assert ready
    assert min(sorted(rows)[len(rows) // 2] for rows in ready.values()) > 10
    for source in ("gray-wfsb", "cbs-owned-kcnc", "tegna-kgw", "nexstar-wric"):
        assert len(proven.rows.get(source, ())) < RULE.min_captures
        stats = ListStats.of(
            Coverage(county_sources={}, archive={}, county_of={}, rows=proven.rows,
                     captures=proven.captures),
            LiveCaptures(),
            RULE.labels.station_min_captures,
        )  # fmt: skip
        assert source in stats.thin or source not in stats.median_rows


# --- round 6: live days count only from the list's own whole closing-size read (lead ruling C2) --


def krem_label(
    coverage: Coverage, live: LiveCaptures, read: tuple[int, int, int], by: Sequence[str]
) -> tuple[Label, str | None, Tier | None]:
    """Methow on a snow-warning morning: KREM read ``read`` naming ``by``, no market peer, the
    map dark."""
    found = label_read_day(
        OCT28, morning=pt_morning({"tegna-krem": [read]}, by={"tegna-krem": by}),
        coverage=coverage, weather=[WeatherClass.SNOW_WARNING], lit=DARK,
        directory=one_district(), rule=RULE, recent={"tegna-krem": 3}, live=live,
    )  # fmt: skip
    (row,) = found.rows
    return row.label, row.why, row.tier


def test_four_stale_one_row_days_never_make_a_list_tier_b(tmp_path: Path) -> None:
    # Review R5-B1's probe P1. SYNTHETIC: KREM, proven for Okanogan, has one closing-size
    # archive capture of 200 rows (five captures of any day). On four earlier warning days our
    # map lit three warned districts; KREM's page held one old row all day, which the reader
    # judged stale. On a warning morning it reads a 2-row list naming one other district, with
    # no market peer.
    thin = replace(COUNTY, captures={"tegna-krem": 5}, rows={"tegna-krem": (200,)})
    log = MorningLog(tmp_path / "morning")
    for back in (2, 3, 4, 5):
        for at in ("14:00", "14:30", "15:00"):
            record_on(log, OCT28 - timedelta(days=back), {"tegna-krem": (1, 1, 0)},
                      by={"tegna-krem": []}, stale=("tegna-krem",), at=at)  # fmt: skip
    live = counted(log, closing_of(thin))
    assert live == LiveCaptures()
    assert counted(log, closing_of(thin), OCT28, 14).days == {}  # never 'recent populated'
    stats = ListStats.of(thin, live, RULE.labels.station_min_captures)
    assert "tegna-krem" in stats.thin
    assert stats.closing == {"tegna-krem": 1}
    assert krem_label(thin, live, (2, 2, 0), ["5300009"]) == (
        Label.NOT_READ, NotRead.NOT_COVERED.value, None,
    )  # fmt: skip
    # Stale is enough by itself: the same days naming the three lit districts still never
    # count (the reader judged the list old).
    named = MorningLog(tmp_path / "named")
    for back in (2, 3, 4, 5):
        record_on(named, OCT28 - timedelta(days=back), {"tegna-krem": (150, 150, 0)},
                  by={"tegna-krem": WARNED}, stale=("tegna-krem",))  # fmt: skip
    assert counted(named, closing_of(thin)) == LiveCaptures()


def test_fresh_short_lists_naming_none_of_the_lit_districts_never_count(tmp_path: Path) -> None:
    # Review R5-B1's probe P1b: the same four days with fresh 2-row lists that named none of
    # the districts our map lit (the map lit three warned districts the list is proven for).
    thin = replace(COUNTY, captures={"tegna-krem": 5}, rows={"tegna-krem": (200,)})
    log = MorningLog(tmp_path / "morning")
    for back in (2, 3, 4, 5):
        record_on(log, OCT28 - timedelta(days=back), {"tegna-krem": (2, 2, 0)},
                  by={"tegna-krem": ["5300009"]})  # fmt: skip
    live = counted(log, closing_of(thin))
    assert live == LiveCaptures()
    assert krem_label(thin, live, (2, 2, 0), ["5300009"])[:2] == (
        Label.NOT_READ, NotRead.NOT_COVERED.value,
    )  # fmt: skip
    # Naming two of the three is still under CLOSING_LIT.
    two = MorningLog(tmp_path / "two")
    for back in (2, 3, 4, 5):
        record_on(two, OCT28 - timedelta(days=back), {"tegna-krem": (190, 190, 0)},
                  by={"tegna-krem": WARNED[:2]})  # fmt: skip
    assert counted(two, closing_of(thin)) == LiveCaptures()


def test_a_live_day_counts_only_from_a_read_that_passed_every_check(tmp_path: Path) -> None:
    # SYNTHETIC: KREM's reference is not thin (five closing-size archive days of 200 rows).
    # Each earlier warning day it read a list naming the three warned districts our map lit;
    # only the read that passed every check counts.
    proven = replace(COUNTY, captures={"tegna-krem": 5}, rows={"tegna-krem": (200,) * 5})

    def one(back: int, read: tuple[int, int, int] = (190, 190, 0), **kwargs: Any) -> None:
        record_on(log, OCT28 - timedelta(days=back), {"tegna-krem": read},
                  by={"tegna-krem": WARNED}, **kwargs)  # fmt: skip

    log = MorningLog(tmp_path / "morning")
    one(2)  # counts
    one(3, health=0.85)  # an unhealthy slot
    one(4, health=None)  # no healthy share recorded
    one(5, shown="v1-shadow")  # a pass never on the map
    one(6, read=(90, 90, 0))  # under half the reference: a partial list
    one(7, read=(400, 200, 200))  # half its rows unread: dropped
    found = counted(log, closing_of(proven))
    assert found == LiveCaptures(days={"tegna-krem": 1}, storm_rows={"tegna-krem": (190,)})
    # On a day our map lit no warned district (advisory, quiet, or not known), none counts.
    quiet = closing_of(proven, {OCT28 - timedelta(days=3): frozenset(WARNED)})
    assert counted(log, quiet) == LiveCaptures()
    # A list caught under station_min_captures times never counts (thin_station).
    caught = replace(proven, captures={"tegna-krem": 2})
    assert counted(log, closing_of(caught)) == LiveCaptures()


def test_a_thin_list_s_live_day_needs_its_longest_market_peer(tmp_path: Path) -> None:
    # SYNTHETIC: KREM's reference is thin (one closing-size archive capture). A warning day's
    # 40-row list naming three warned districts our map lit counts only when the longest
    # gated market peer's read that day vouches for its length (lead ruling B1.2).
    # The peer keeps its ten closing-size captures of 10 rows (it vouches: PeerVouch).
    thin = replace(COUNTY, captures={**COUNTY.captures, "tegna-krem": 5},
                   rows={**COUNTY.rows, "tegna-krem": (200,)})  # fmt: skip

    def day_of(peer: int | None, short: int | None = None) -> LiveCaptures:
        log = MorningLog(tmp_path / f"m{peer}-{short}")
        reads = {"tegna-krem": (40, 40, 0)}
        if peer is not None:
            reads["flashalert-spokane"] = (peer, peer, 0)
        if short is not None:
            reads["cox-kiro"] = (short, short, 0)
        record_on(log, OCT28 - timedelta(days=1), reads,
                  by={"tegna-krem": WARNED, "flashalert-spokane": ["5300003"]})  # fmt: skip
        return counted(log, closing_of(thin))

    assert day_of(None) == LiveCaptures()  # no peer
    assert day_of(60).storm_rows == {"tegna-krem": (40,)}
    assert day_of(300) == LiveCaptures()  # a storm-size peer: KREM's 40 rows are partial
    # A short peer never vouches while a longer one read a storm-size list.
    assert day_of(300, short=50) == LiveCaptures()


def test_a_thin_list_s_read_is_vouched_for_by_its_longest_peer_only() -> None:
    # Review R5-S1's probe P2. SYNTHETIC: thin KREM reads 3 rows; two gated market peers read
    # whole: a 4-row list (reference 4) and a 300-row list (reference 300). The short peer
    # used to vouch; the longest gated peer decides, as for an empty read.
    coverage = thin_krem(4)
    coverage = replace(
        coverage,
        county_sources={**coverage.county_sources, "53065": ("tv",)},
        captures={**coverage.captures, "tegna-krem": 5, "tv": 10},
        rows={**coverage.rows, "tv": (300,) * 10},
    )
    markets = {"tegna-krem": "Spokane", "flashalert-spokane": "Spokane", "tv": "Spokane"}
    live = LiveCaptures(days={"tegna-krem": 4})
    recent = {"tegna-krem": 3, "flashalert-spokane": 3, "tv": 3}
    both = pt_morning(
        {"tegna-krem": [(3, 3, 0)], "flashalert-spokane": [(4, 4, 0)], "tv": [(300, 300, 0)]},
        by={"tegna-krem": ["5300009"], "flashalert-spokane": ["5300008"], "tv": ["5300007"]},
        market_of=markets,
    )
    assert thin_read(both, coverage, live, recent=recent) == (Label.NOT_READ, "small_capture")
    short = pt_morning(
        {"tegna-krem": [(3, 3, 0)], "flashalert-spokane": [(4, 4, 0)]},
        by={"tegna-krem": ["5300009"], "flashalert-spokane": ["5300008"]},
        market_of=markets,
    )
    assert thin_read(short, coverage, live, recent=recent) == (Label.UNNAMED, None)


def test_g1_s_by_date_mean_gates_once_twenty_lists_give_tier_b_trials(tmp_path: Path) -> None:
    # Lead ruling C5. SYNTHETIC: 20 lists, one trial each on its own date, 15 named: the
    # registered s_B (Beta(19, 7), 0.731) is met by trials over 20 dates; the by-date mean
    # is the same (one trial a date). Then 60 hits on one morning from one list and one miss
    # on each of 19 other dates from 19 more lists: met by trials (s_B 0.75), by-date mean
    # under 0.7, and with 20 lists the by-date mean is part of G1: not met.
    folder = tmp_path / "reads"
    for i in range(20):
        trial = Trial(district=f"53{i:05d}", source=f"list-{i}", tier=Tier.B, named=i < 15,
                      weather=5)  # fmt: skip
        write_trials_day(folder, date(2026, 11, 2) + timedelta(days=i), [trial])
    report = report_of(folder, audit_of(folder, world.utc("2026-12-01T06:00:00")), RULE)
    assert report.tier_b_lists == 20
    assert report.tier_b_by_date_gates
    assert report.sensitivity[1].day_mean >= RULE.tier_b_min
    assert (report.tier_b_g1, report.tier_b_not_by_date) == (True, False)
    clustered = tmp_path / "clustered"
    hits = [
        Trial(district=f"53{i:05d}", source="list-0", tier=Tier.B, named=True, weather=5)
        for i in range(60)
    ]
    write_trials_day(clustered, date(2026, 11, 2), hits)
    for i in range(1, 20):
        miss = Trial(district=f"54{i:05d}", source=f"list-{i}", tier=Tier.B, named=False,
                     weather=5)  # fmt: skip
        write_trials_day(clustered, date(2026, 11, 2) + timedelta(days=i), [miss])
    audit = audit_of(clustered, world.utc("2026-12-01T06:00:00"))
    report = report_of(clustered, audit, RULE)
    tier_b = report.sensitivity[1]
    assert tier_b.mean >= RULE.tier_b_min > tier_b.day_mean
    assert (report.tier_b_lists, report.tier_b_by_date_gates) == (20, True)
    assert (report.tier_b_g1, report.tier_b_not_by_date) == (False, True)
    (line,) = (x for x in read_cli.summary(audit, clustered, report) if x.startswith("list sens"))
    assert "not met: by date (20 dates, 20 lists); by-date mean " in line
    assert line.endswith(
        "under 0.7 (part of G1, tier B trials from 20 lists, 0 lists tier B now, of 20)"
    )


# --- round 7: one peer-vouch rule for the read and the counted days (review R6-B1) -------------


def two_lists(krem: Sequence[int], peer: Sequence[int], peer_captures: int = 10) -> Coverage:
    """SYNTHETIC: KREM (five captures of any day) and FlashAlert (``peer_captures``), Spokane,
    with the given closing-size archive rows."""
    return replace(
        COUNTY,
        captures={**COUNTY.captures, "tegna-krem": 5, "flashalert-spokane": peer_captures},
        rows={**COUNTY.rows, "tegna-krem": tuple(krem), "flashalert-spokane": tuple(peer)},
    )


def four_warning_days(  # noqa: PLR0913 - every part a test sets
    folder: Path,
    krem: int,
    peer: int,
    *,
    peer_by: Sequence[str] = ("5300003",),
    stale: Sequence[str] = (),
    peer_health: float = 0.95,
) -> MorningLog:
    """SYNTHETIC: four earlier warning mornings on which KREM's own read named the three
    warned districts our map lit, FlashAlert's read beside it (in its own slot)."""
    log = MorningLog(folder)
    for back in (2, 3, 4, 5):
        when = OCT28 - timedelta(days=back)
        record_on(log, when, {"tegna-krem": (krem, krem, 0)}, by={"tegna-krem": WARNED})
        record_on(log, when, {"flashalert-spokane": (peer, peer, 0)},
                  by={"flashalert-spokane": peer_by}, stale=stale, health=peer_health,
                  at="14:30")  # fmt: skip
    return log


def test_p1_two_thin_lists_never_vouch_for_each_other(tmp_path: Path) -> None:
    # Review R6-B1's probe P1. SYNTHETIC: KREM and FlashAlert, each caught five times by the
    # archive with one closing-size capture of 200 rows (thin references). On four warning
    # days KREM reads 10 rows and FlashAlert 12, each naming the three warned, lit districts.
    thin = two_lists((200,), (200,), peer_captures=5)
    log = four_warning_days(tmp_path / "m", 10, 12, peer_by=WARNED)
    live = counted(log, closing_of(thin))
    # Neither vouches for the other (a thin peer vouches for nothing), so no day counts:
    # both stay thin, KREM never becomes tier B, and Methow is not covered.
    assert live == LiveCaptures()
    stats = ListStats.of(thin, live, RULE.labels.station_min_captures)
    assert {"tegna-krem", "flashalert-spokane"} <= stats.thin
    assert stats.closing["tegna-krem"] == 1
    assert krem_label(thin, live, (6, 6, 0), ["5300009"]) == (
        Label.NOT_READ, NotRead.NOT_COVERED.value, None,
    )  # fmt: skip
    # The read refuses the same reads by the same rule (KREM carrying Methow, tier A).
    morning = pt_morning(
        {"tegna-krem": [(10, 10, 0)], "flashalert-spokane": [(12, 12, 0)]},
        by={"tegna-krem": WARNED, "flashalert-spokane": WARNED},
    )
    carried = replace(thin, archive=KREM_CARRIES)
    assert thin_read(morning, carried, live) == (Label.NOT_READ, "small_capture")
    # Beside a peer with a reference of its own (ten closing-size captures of 20 rows), the
    # same reads vouch: KREM's four days count, at read time and in the record alike.
    vouched = two_lists((200,), (20,) * 10)
    found = counted(log, closing_of(vouched))
    assert found.storm_rows["tegna-krem"] == (10, 10, 10, 10)
    assert thin_read(morning, replace(vouched, archive=KREM_CARRIES), LiveCaptures()) == (
        Label.UNNAMED, None,
    )  # fmt: skip


def test_p2_a_peer_partial_against_its_own_reference_vouches_for_nothing(tmp_path: Path) -> None:
    # Review R6-B1's probe P2. SYNTHETIC: FlashAlert has a reference of its own (ten
    # closing-size captures of 300 rows) but reads 20 rows: partial by its own gate. KREM's
    # 12-row lists beside it never count, and KREM stays thin.
    coverage = two_lists((200,), (300,) * 10)
    live = counted(four_warning_days(tmp_path / "partial", 12, 20), closing_of(coverage))
    assert live == LiveCaptures()
    assert "tegna-krem" in ListStats.of(coverage, live, RULE.labels.station_min_captures).thin
    assert krem_label(coverage, live, (7, 7, 0), ["5300009"])[1] == NotRead.NOT_COVERED.value
    # Read whole (160 rows, over half its 300), it vouches for KREM's 100-row lists.
    whole = counted(four_warning_days(tmp_path / "whole", 100, 160), closing_of(coverage))
    assert whole.storm_rows == {"tegna-krem": (100, 100, 100, 100)}


@pytest.mark.parametrize(
    ("change", "counts"),
    [
        ({}, True),
        ({"stale": ("flashalert-spokane",)}, False),
        ({"peer_health": 0.8}, False),
        ({"peer_by": ()}, False),  # its market named closings, it named none (B1.3)
        ({"captures": 4}, False),
        ({"district_site": True}, False),
    ],
)
def test_every_check_of_the_peer_vouch_rule_holds_in_the_counted_days(
    tmp_path: Path, change: Mapping[str, Any], counts: bool
) -> None:
    coverage = two_lists((200,), (160,) * 10, peer_captures=change.get("captures", 10))
    if change.get("district_site"):
        coverage = replace(coverage, district_sites=frozenset({"flashalert-spokane"}))
    log = four_warning_days(
        tmp_path / "m", 100, 160, peer_by=change.get("peer_by", ("5300003",)),
        stale=change.get("stale", ()), peer_health=change.get("peer_health", 0.95),
    )  # fmt: skip
    found = counted(log, closing_of(coverage)).days
    assert found == ({"tegna-krem": 4} if counts else {})


def test_the_read_and_the_counted_days_share_one_peer_vouch_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The vouching case of P2, read and counted, then with PeerVouch made to refuse every
    # peer: both sides change together, since both call it.
    coverage = two_lists((200,), (300,) * 10)
    log = four_warning_days(tmp_path / "m", 100, 160)
    morning = pt_morning(
        {"tegna-krem": [(100, 100, 0)], "flashalert-spokane": [(160, 160, 0)]},
        by={"tegna-krem": WARNED, "flashalert-spokane": ["5300003"]},
    )
    carried = replace(coverage, archive=KREM_CARRIES)
    assert counted(log, closing_of(coverage)).days == {"tegna-krem": 4}
    assert thin_read(morning, carried, LiveCaptures()) == (Label.UNNAMED, None)
    monkeypatch.setattr(live_read_module.PeerVouch, "vouches", lambda *_a, **_k: False)
    assert counted(log, closing_of(coverage)) == LiveCaptures()
    assert thin_read(morning, carried, LiveCaptures()) == (Label.NOT_READ, "small_capture")


def test_the_peer_vouch_rule_itself() -> None:
    vouch = live_read_module.PeerVouch(RULE, "v1", frozenset({"site"}), MARKETS)
    stats = ListStats(
        captures={"peer": 10, "thin": 10, "few": 4, "site": 10},
        median_rows={"peer": 100.0, "thin": math.inf, "few": 100.0, "site": 100.0},
    )
    slot = Slot(shown={"v1"}, health=950)
    slot.by = {"peer": {"5300003"}}
    assert vouch.vouches("peer", 50, slot, stats)
    assert not vouch.vouches("peer", 49, slot, stats)  # partial by its own reference
    assert not vouch.vouches("peer", 0, slot, stats)  # an empty read never vouches
    assert not vouch.vouches("thin", 500, slot, stats)
    assert not vouch.vouches("few", 100, slot, stats)
    assert not vouch.vouches("site", 100, slot, stats)
    assert not vouch.vouches("unknown", 100, slot, stats)
    for bad in (Slot(shown={"v1"}, health=800), Slot(shown={"v1"}), Slot(shown={"v1", "v2"})):
        bad.by = slot.by
        assert not vouch.vouches("peer", 100, bad, stats)
    stale = Slot(shown={"v1"}, health=950, stale={"peer"})
    assert not vouch.vouches("peer", 100, stale, stats)
    # Naming nothing for the day while its market named districts (lead ruling B1.3).
    quiet = Slot(shown={"v1"}, health=950)
    assert vouch.vouches("peer", 100, quiet, stats)
    assert not vouch.vouches("peer", 100, quiet, stats, frozenset({"peer"}))


# --- round 7: the counted days as the list stood, in the read window (review R6-S5) ----------


def test_a_counted_day_is_read_in_the_window_of_the_districts_it_named(tmp_path: Path) -> None:
    # SYNTHETIC: the TV list's 10-row reads naming the three warned, lit districts (Pacific).
    # On Jan 6, 14:00Z is 06:00 PST, before the window opens; 15:00Z is 07:00 PST.
    def days(at: str, zones: bool = True) -> Mapping[str, int]:
        log = MorningLog(tmp_path / f"{at}-{zones}")
        record_on(log, date(2026, 1, 6), {"tv": (10, 10, 0)}, by={"tv": WARNED}, at=at)
        closing = closing_of(COUNTY)
        if not zones:
            closing = replace(closing, zones={})
        return counted(log, closing, date(2026, 1, 7)).days

    assert days("15:00") == {"tv": 1}
    assert days("14:00") == {}
    assert days("19:30") == {}  # 11:30 PST, after the window
    assert days("15:00", zones=False) == {}  # a district of no known zone never counts


def test_a_counted_day_s_placed_share_is_the_record_s_up_to_that_day(tmp_path: Path) -> None:
    # SYNTHETIC: on Oct 20 the TV list placed 4 of 10 rows in three passes (its median so
    # far 0.4) and named the three warned, lit districts. Every later pass placed all its
    # rows. Judged by the whole record (median 1.0) the Oct 20 read would be dropped; as the
    # record stood that day it is whole, and the day counts.
    log = MorningLog(tmp_path / "m")
    first = date(2026, 10, 20)
    for at in ("14:00", "14:30", "15:00"):
        record_on(log, first, {"tv": (10, 4, 0)}, by={"tv": WARNED}, at=at)
    for back in range(1, 7):
        for at in ("14:00", "14:30", "15:00"):
            record_on(log, first + timedelta(days=back), {"tv": (10, 10, 0)}, at=at)
    lit = {first: frozenset(WARNED)}
    assert counted(log, closing_of(COUNTY, lit)).days == {"tv": 1}


def test_another_directory_s_timeline_gives_no_closing_districts() -> None:
    # Review R6-S2. SYNTHETIC: Monday's timeline lights district 2900001's schools closed
    # under a snow warning. Read through this directory it gives that district; a timeline
    # in another directory's school indexes gives none.
    weather = SHORT.weather
    stamp = world.STAMP.model_copy(update={"schools": world.STAMP.schools + 1})

    def storms(timeline: Any) -> AbstractSet[str]:
        return _Storms(
            snapshots_for(MONDAY), learn.directory_of(built()),
            Window(weather.window_from, weather.window_until, weather.snapshot_hour),
            timedelta(minutes=SHORT.learn.snapshot_slack_minutes), settings=RULE.labels,
            timeline=lambda _when: timeline,
        )(MONDAY)  # fmt: skip

    ours = world.timeline().model_copy(update={"day": MONDAY})
    assert "2900001" in storms(ours)
    assert storms(world.timeline(stamp).model_copy(update={"day": MONDAY})) == set()
    assert storms(None) == set()


def test_audiences_past_their_two_seasons_are_never_read_as_tier_a(
    tmp_path: Path, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review R6-S4. SYNTHETIC: the TV list carries the Kansas City districts in the archive
    # audiences. Built in the 2025 season, the file is current through Jul 31, 2026; on a run
    # in the 2026 season its pairs are no tier A, and the step says so.
    given: list[Coverage] = []
    labeled = live_read_module.read_new_days

    def spy(folder: Path, source: Any, **kwargs: Any) -> Any:
        given.append(kwargs["coverage"])
        return labeled(folder, source, **kwargs)

    monkeypatch.setattr(live_read_module, "read_new_days", spy)

    def carried(season: int, folder: str) -> object:
        run = read_run(Host(), tmp_path / folder, world.utc("2026-01-08T06:00:00"))
        run = replace(run, coverage=replace(run.coverage, audience_season=season))
        assert read_cli.read_once(run) == 0
        return given[-1].archive

    assert carried(2025, "current") == CARRIED
    assert "was built in the" not in capsys.readouterr().out
    assert carried(2024, "late") == {}
    assert (
        "::warning::predict read-labels: audiences.json.gz was built in the 2024 season"
    ) in capsys.readouterr().out
    path = tmp_path / "audiences.json.gz"
    path.write_bytes(gzip_json({"schema_version": 3, "audiences": {}}))
    with pytest.raises(ValueError, match="no build season"):
        live_read_module.load_audience_season(path)
    assert live_read_module.load_audience_season(tmp_path / "absent.json.gz") is None


def read_days(folder: Path) -> list[ReadDay]:
    return [found for day in labeled_days(folder) if (found := read_day(folder, day))]

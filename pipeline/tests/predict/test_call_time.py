"""The usual call time and its decline (predict-next CALL-TIME-1, the term off).

Every district, list, read, timeline and storm here is made up for the tests (SYNTHETIC): codes
and minutes only, never a real list's rows.
"""

import ast
import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from predict import test_forecast_adjust as fa_test
from predict import world
from predict.test_frozen import _passes, adjusting_pass
from predict.test_golden import golden_file
from predict.test_learn import CFG, MONDAY, Host, snapshots_for
from predict.test_live_read import ReadingSource, listed, read_run, stats_of
from predict.test_retention import CONFIG
from snowlight.live import state
from snowlight.live.ledger import Ledger
from snowlight.live.ledger import Outcome as LedgerOutcome
from snowlight.live.morning import Slot
from snowlight.predict import call_time, frozen, live_read, read_cli
from snowlight.predict.call_time import (
    Call,
    CallKind,
    CallSettings,
    Cuts,
    DarkCause,
    PoolKind,
    Required,
    Risk,
    SlotProof,
    UsualCall,
    applies,
    at_risk,
    called_minutes,
    dark_cause,
    decline,
    delta,
    market_on,
    proven,
    required,
    usual_calls,
    with_decline,
)
from snowlight.predict.config import PIPELINE_ROOT, PredictConfig
from snowlight.predict.live_labels import Directory, Morning
from snowlight.predict.live_read import Coverage, ListStats, LiveCaptures, ReadRule
from snowlight.predict.serve import ADJUST_KINDS
from snowlight.predict.situations import WeatherClass
from snowlight.schemas.live import DayEntry, DayIndex, DayTimeline
from snowlight.schemas.vocab import Reason, Status

SETTINGS = CallSettings.of(CFG)
RULE = ReadRule.of(CFG)
EAST = "America/New_York"
LEAID = "3600001"
"""SYNTHETIC: one New York district (Eastern time) with three schools, 0 to 2."""
WED = date(2026, 1, 14)
"""A Wednesday in standard time (05:00 EST is 10:00 UTC)."""
LISTS = ("tv", "radio")
COVERAGE = listed(Coverage(county_sources={}, archive={s: {LEAID} for s in LISTS}, county_of={}))
STATS = ListStats.of(COVERAGE, LiveCaptures(), RULE.labels.station_min_captures)
MARKETS = {"tv": "Albany", "radio": "Albany", "paper": "Albany"}


def directory(zone: str = EAST, leaid: str = LEAID) -> Directory:
    return Directory(
        districts=(leaid,),
        eligible=(np.array([0, 1, 2], dtype=np.int64),),
        zones=(zone,),
        content="synthetic",
        stamp=world.STAMP,
    )


def utc_at(day: date, local: str, zone: str = EAST) -> datetime:
    return datetime.combine(day, time.fromisoformat(local), tzinfo=ZoneInfo(zone)).astimezone(UTC)


def timeline(
    day: date = WED,
    *,
    changes: Sequence[tuple[int, int, Status | None, Reason | None]] = (),
    stamp: Any = world.STAMP,
) -> DayTimeline:
    """SYNTHETIC: (school, timeline minute, status, reason) changes, in school then time order."""
    ordered = sorted(changes, key=lambda c: (c[0], c[1]))
    schools = sorted({c[0] for c in ordered})
    gaps = tuple(s - (schools[i - 1] if i else -1) - 1 for i, s in enumerate(schools))
    shifted = [c for c in ordered if c[2] in (Status.DELAYED, Status.EARLY_DISMISSAL)]
    return DayTimeline(
        schema_version=1,
        day=day,
        generated_at=datetime.combine(day + timedelta(days=1), time(8), tzinfo=UTC),
        directory=stamp,
        content_sha256=None,
        final=True,
        gaps=gaps,
        counts=tuple(sum(1 for c in ordered if c[0] == s) for s in schools),
        minutes=tuple(c[1] for c in ordered),
        statuses=tuple(c[2] for c in ordered),
        reasons=tuple(c[3] for c in ordered),
        shifts=tuple(60 for _ in shifted),
        clocks=tuple(600 for _ in shifted),
    )


def closed_at(minute: int, day: date = WED) -> DayTimeline:
    """SYNTHETIC: every school closed for snow at the timeline minute ``minute``."""
    return timeline(
        day, changes=[(s, minute, Status.CLOSED, Reason.WINTER_STORM) for s in (0, 1, 2)]
    )


def calls_of(
    found: DayTimeline, klass: WeatherClass = WeatherClass.SNOW_WARNING
) -> dict[str, Call]:
    return called_minutes(found, directory(), [klass], SETTINGS, RULE)


# --- settings and the domain F ----------------------------------------------------------------


def test_the_block_is_registered_off_with_its_domain_and_default() -> None:
    assert SETTINGS.serve == "off"
    assert (SETTINGS.m, SETTINGS.tau) == SETTINGS.default == (0.35, 45.0)
    assert round(delta(30, 0.35, 45), 4) == -0.3802
    assert len(SETTINGS.m_grid) * len(SETTINGS.tau_grid) == 90
    assert len(SETTINGS.domain()) == 75
    assert SETTINGS.ends() == (330, 360, 390, 420, 450, 480, 510, 540, 570, 600)
    for m, tau in ((0.35, 45), (0.60, 90), (0.60, 20), (0.35, 90)):
        assert CallSettings.of(CFG, m, tau).in_domain(m, tau)
    for m, tau in ((0.20, 20), (0.35, 20), (0.65, 45), (0.37, 45)):
        with pytest.raises(ValueError, match="outside the registered F"):
            CallSettings.of(CFG, m, tau)


def test_serving_the_term_is_refused_until_live_reads_lands() -> None:
    block = {**CFG.live_score["call_time"], "serve": "on"}
    with pytest.raises(ValueError, match="off only"):
        PredictConfig.model_validate(
            {**CFG.model_dump(mode="json"), "live_score": {**CFG.live_score, "call_time": block}}
        )
    shipped = PredictConfig.load(PIPELINE_ROOT / "config" / "predict.yaml")
    assert shipped.live_score["call_time"]["serve"] == "off"
    assert CONFIG.live_score["call_time"] == shipped.live_score["call_time"]


def test_the_default_decline_table() -> None:
    # 15, 30, 45, 60, 105 and 165 minutes past an own u (grace 15): x 0, 15, 30, 45, 90, 150
    past = (0, 15, 30, 45, 90, 150)
    assert [round(delta(x, 0.35, 45), 2) for x in past] == [0.0, -0.2, -0.38, -0.53, -0.83, -0.99]
    moved = [round(moved_by(0.5, 0.1, delta(x, 0.35, 45))[0] * 100) for x in past]
    assert moved == [50, 45, 41, 37, 30, 27]
    assert round(moved_by(0.5, 0.1, math.log(0.35))[0] * 100) == 26
    assert round(moved_by(0.8, 0.1, math.log(0.35))[0] * 100) == 58
    assert round(moved_by(0.2, 0.1, math.log(0.35))[0] * 100) == 8
    # the published delay is held, the floor and ceiling hold, and it never raises a chance
    assert moved_by(0.5, 0.07, -0.5)[1] == 0.07
    assert moved_by(0.011, 0.0, -1.0)[0] == 0.01
    for wrong in (0.1, math.nan, math.inf, -math.inf, math.log(0.35) - 0.01):
        with pytest.raises(ValueError, match="from 0 down to ln m"):
            moved_by(0.5, 0.0, wrong)
    for chance in (math.nan, -0.1, 1.1):
        with pytest.raises(ValueError, match="from 0 to 1"):
            moved_by(chance, 0.0, -0.1)


def moved_by(p_raw: float, q: float, delta_: float) -> tuple[float, float]:
    return with_decline(p_raw, q, delta_, 0.01, 0.99, settings=SETTINGS)


def test_decline_and_with_decline_refuse_a_point_outside_f_however_it_was_made() -> None:
    # what serves is what was tested: a settings object replaced or built outside F is refused
    # by the decline itself, not only by CallSettings.of
    steps = [SlotProof(end, end) for end in SETTINGS.ends()]
    usual_ = UsualCall(300, 3, PoolKind.MARKET)
    for m, tau in ((0.20, 20.0), (0.05, 5.0), (0.35, 20.0), (0.65, 45.0), (math.nan, 45.0)):
        wrong = replace(SETTINGS, m=m, tau=tau)
        with pytest.raises(ValueError, match="outside the registered F"):
            decline(steps, usual_, wrong)
        with pytest.raises(ValueError, match="outside the registered F"):
            with_decline(0.5, 0.1, -0.1, 0.01, 0.99, settings=wrong)
    # every point of F is taken
    for m, tau in SETTINGS.domain():
        assert decline(steps, usual_, replace(SETTINGS, m=m, tau=tau))


# --- samples ----------------------------------------------------------------------------------


def test_a_call_is_the_first_local_minute_the_map_showed_no_school() -> None:
    (found,) = calls_of(closed_at(340)).values()
    assert (found.minute, found.kind) == (340, CallKind.MORNING)
    # 20:10 the evening before: evening, kept apart
    assert calls_of(closed_at(-230))[LEAID].kind is CallKind.EVENING
    # before 18:00 the evening before: ahead
    assert calls_of(closed_at(-361))[LEAID].kind is CallKind.AHEAD
    assert calls_of(closed_at(-360))[LEAID].kind is CallKind.EVENING
    assert calls_of(closed_at(570))[LEAID].kind is CallKind.MORNING
    assert calls_of(closed_at(571))[LEAID].kind is CallKind.LATE
    # one school of three at 05:40, a second at 06:10: the share is met at 06:10
    split = timeline(
        changes=[
            (0, 340, Status.CLOSED, Reason.WINTER_STORM),
            (1, 370, Status.CLOSED, Reason.WINTER_STORM),
        ]
    )
    assert calls_of(split)[LEAID].minute == 370


def test_no_call_from_a_non_weather_closing_an_under_share_a_retraction_or_another_day() -> None:
    power = [(s, 340, Status.CLOSED, Reason.POWER_OUTAGE) for s in (0, 1, 2)]
    assert calls_of(timeline(changes=power)) == {}
    assert calls_of(timeline(changes=[(0, 340, Status.CLOSED, Reason.WINTER_STORM)])) == {}
    retracted = [
        (0, 300, Status.CLOSED, Reason.WINTER_STORM),
        (0, 320, None, None),
        (1, 340, Status.CLOSED, Reason.WINTER_STORM),
        (2, 340, Status.CLOSED, Reason.WINTER_STORM),
    ]
    assert calls_of(timeline(changes=retracted)) == {}
    relit = [*retracted, (0, 350, Status.CLOSED, Reason.WINTER_STORM)]
    assert calls_of(timeline(changes=relit)) == {}
    other = world.STAMP.model_copy(update={"districts": world.STAMP.districts + 1})
    closing = [(s, 340, Status.CLOSED, Reason.WINTER_STORM) for s in (0, 1, 2)]
    assert calls_of(timeline(changes=closing, stamp=other)) == {}
    # a quiet day, and a likely break (Martin Luther King Jr. Day)
    assert calls_of(closed_at(340), WeatherClass.NONE) == {}
    assert calls_of(closed_at(340, date(2026, 1, 19))) == {}
    # cold and advisory days count
    assert calls_of(closed_at(340), WeatherClass.COLD)[LEAID].minute == 340
    assert calls_of(closed_at(340), WeatherClass.ADVISORY)[LEAID].minute == 340


def test_a_call_is_a_wall_clock_minute_on_the_days_the_clocks_change() -> None:
    # Nov 1, 2026 (clocks back at 02:00): 05:40 EST is 400 minutes after midnight EDT
    fall = date(2026, 11, 1)
    assert calls_of(closed_at(400, fall))[LEAID].minute == 340
    # Mar 14, 2027 (clocks forward at 02:00): 05:40 EDT is 280 minutes after midnight EST
    spring = date(2027, 3, 14)
    assert calls_of(closed_at(280, spring))[LEAID].minute == 340
    assert calls_of(closed_at(-230, spring))[LEAID].minute == -230


# --- the usual call time ----------------------------------------------------------------------


def morning_call(leaid: str, day: date, minute: int) -> Call:
    return Call(leaid, day, minute, CallKind.MORNING)


def pool_calls() -> list[Call]:
    """SYNTHETIC: ten morning calls of three other districts, median 06:00 (360)."""
    minutes = (330, 340, 350, 355, 360, 360, 365, 370, 380, 390)
    return [
        morning_call(f"360000{n % 3 + 2}", date(2025, 12, 1) + timedelta(days=n), minute)
        for n, minute in enumerate(minutes)
    ]


def usual(
    calls: Sequence[Call],
    markets: Mapping[str, str | None],
    *,
    before: date = WED,
    outside: int | None = None,
) -> dict[str, UsualCall]:
    return usual_calls(
        calls, markets.get, lambda _leaid: "NY", SETTINGS, before=before, outside=outside,
        districts=[LEAID],
    )  # fmt: skip


def test_u_shrinks_own_calls_to_the_market_else_the_state_else_none() -> None:
    others = pool_calls()
    markets = dict.fromkeys({c.leaid for c in others}, "A") | {LEAID: "A"}
    # no own call: the market's median, a 30-minute grace
    found = usual(others, markets)[LEAID]
    assert (found.minute, found.own, found.pool) == (360, 0, PoolKind.MARKET)
    assert found.grace(SETTINGS) == 30
    # three own calls at 07:00 (in the market's pool too: its median 365): the lower median
    # of 420 x3 and 365 x3, grace 15
    own = [morning_call(LEAID, date(2025, 12, 20 + n), 420) for n in range(3)]
    found = usual([*others, *own], markets)[LEAID]
    assert (found.minute, found.own) == (365, 3)
    assert found.grace(SETTINGS) == 15
    four = [*own, morning_call(LEAID, date(2025, 12, 24), 420)]
    assert usual([*others, *four], markets)[LEAID].minute == 420
    # the district's market holds no pool: its state's
    assert usual(others, {**markets, LEAID: "B"})[LEAID].pool is PoolKind.STATE
    # no tier-A list read whole in the 14 days (no market): the state's
    assert usual(others, {**markets, LEAID: None})[LEAID].pool is PoolKind.STATE
    # too few calls anywhere: none, never national
    assert usual(others[:9], markets) == {}
    assert usual([c for c in others if c.leaid != others[0].leaid], markets) == {}
    # evening, ahead and late calls never enter u, and only calls before the day count
    evening = [replace(c, kind=CallKind.EVENING) for c in others]
    assert usual(evening, markets) == {}
    assert usual(others, markets, before=date(2025, 12, 5)) == {}


def test_the_fold_a_call_of_the_held_out_season_never_moves_a_training_u() -> None:
    others = pool_calls()
    markets = dict.fromkeys({c.leaid for c in others}, "A") | {LEAID: "A"}
    held = [morning_call(LEAID, date(2026, 1, 5 + n), 300 + 20 * n) for n in range(3)]
    base = usual([*others, *held], markets, before=date(2026, 3, 1), outside=2025)
    for moved in range(len(held)):
        changed = list(held)
        changed[moved] = replace(changed[moved], minute=500)
        again = usual([*others, *changed], markets, before=date(2026, 3, 1), outside=2025)
        assert again == base
    # the held-out season's calls are out of the pools too
    assert usual(others, markets, before=WED, outside=2025) == {}


def test_a_dead_lowest_id_carrier_of_another_market_is_never_the_lead() -> None:
    coverage = listed(
        Coverage(
            county_sources={}, archive={s: {LEAID} for s in ("paper", "radio", "tv")}, county_of={}
        )
    )
    stats = ListStats.of(coverage, LiveCaptures(), RULE.labels.station_min_captures)
    record = {
        WED - timedelta(days=n): frozenset({"tv"} if n % 2 else {"tv", "radio"})
        for n in range(1, 14)
    }
    markets = {"paper": "Dead", "radio": "B", "tv": "A"}
    kwargs: dict[str, Any] = {"audience": {}, "market_of": markets, "settings": SETTINGS}
    assert market_on(LEAID, WED, record, coverage, stats, **kwargs) == "A"
    # a tie of days goes to more captures, then the lowest id
    even = {WED - timedelta(days=n): frozenset({"tv", "radio"}) for n in range(1, 14)}
    assert market_on(LEAID, WED, even, coverage, stats, **kwargs) == "B"
    more = replace(stats, captures={**stats.captures, "tv": 99})
    assert market_on(LEAID, WED, even, coverage, more, **kwargs) == "A"
    # none read whole in the 14 days: no market
    old = {WED - timedelta(days=20): frozenset({"tv"})}
    assert market_on(LEAID, WED, old, coverage, stats, **kwargs) is None


# --- proof --------------------------------------------------------------------------------------

WINDOW_UTC = tuple(f"{h:02d}:{m:02d}" for h in range(10, 16) for m in (0, 30))
"""UTC slot starts of 05:00 to 11:00 EST on a January day."""
WHOLE = (10, 10, 0)


def morning(  # noqa: PLR0913 - every part a test sets
    reads: Mapping[str, Mapping[str, Sequence[tuple[int, int, int]]]] | None = None,
    *,
    health: Mapping[str, int] | None = None,
    named: Mapping[str, Mapping[str, Mapping[str, Sequence[str]]]] | None = None,
    by: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    until: str = "15:30",
    named_before: Mapping[str, frozenset[str]] | None = None,
    stale: Mapping[str, Sequence[str]] | None = None,
) -> Morning:
    """SYNTHETIC: Jan 14 slots from 05:00 EST, each list reading ``WHOLE`` in every slot
    unless ``reads`` gives a slot's reads; the record reaches ``until`` (UTC)."""
    slots: dict[datetime, Slot] = {}
    for key in WINDOW_UTC:
        if key > until:
            continue
        found = (reads or {}).get(key)
        slot = Slot(
            shown={"v1"},
            health=(health or {}).get(key, 990),
            reads={
                s: set(r)
                for s, r in (found if found is not None else {s: [WHOLE] for s in LISTS}).items()
            },
            named={
                d: {k: set(v) for k, v in days.items()}
                for d, days in (named or {}).get(key, {}).items()
            },
            by={s: set(d) for s, d in (by or {}).get(key, {}).items()},
            stale=set((stale or {}).get(key, ())),
        )
        slots[datetime.combine(WED, time.fromisoformat(key), tzinfo=UTC)] = slot
    return Morning(
        day=WED, slots=slots, audience={}, market_of=MARKETS, stats=stats_of(*MARKETS),
        prefix="v1", named_before=named_before or {},
    )  # fmt: skip


NEEDED = Required(LISTS)


def proofs(
    found: Morning,
    needed: Required = NEEDED,
    *,
    warning: bool = False,
    recent: Mapping[str, int] | None = None,
    every_before: frozenset[str] = frozenset(),
) -> list[SlotProof]:
    cuts = Cuts(found, RULE, STATS, frozenset(), SETTINGS)
    return proven(
        cuts, LEAID, needed, zone=EAST, storm=True, warning=warning,
        recent=dict.fromkeys(LISTS, 1) if recent is None else recent, every_before=every_before,
    )  # fmt: skip


def p_stars(found: Sequence[SlotProof]) -> list[int | None]:
    return [item.p_star for item in found]


OWN_U = UsualCall(360, 3, PoolKind.MARKET)
"""SYNTHETIC: an own usual call time of 06:00, decline from 06:15."""


def xs(found: Sequence[SlotProof], u: UsualCall | None = OWN_U) -> list[float]:
    return [item.x for item in decline(found, u, SETTINGS)]


def test_two_lists_read_whole_every_slot_prove_the_district_and_the_decline_grows() -> None:
    found = proofs(morning())
    assert p_stars(found) == [330, 360, 390, 420, 450, 480, 510, 540, 570, 600]
    assert all(item.ended is None for item in found)
    # x: max(x, min(P* - (u + g), x + 30)); held after 09:30 (the 10:00 row)
    assert xs(found) == [0, 0, 15, 45, 75, 105, 135, 165, 195, 195]
    deltas = [d.delta for d in decline(found, OWN_U, SETTINGS)]
    assert deltas == sorted(deltas, reverse=True)
    assert deltas[-1] == deltas[-2]
    # no usual call time: no decline
    assert xs(found, None) == [0.0] * 10


def test_an_unplaced_row_blocks_its_slot() -> None:
    reads = {key: {"tv": [(10, 9, 0)], "radio": [WHOLE]} for key in WINDOW_UTC if key >= "12:00"}
    found = proofs(morning(reads))
    # tv's last clean slot is 11:30Z (06:30 local start): P stops at 07:00 local
    assert p_stars(found)[-1] == 420


def test_the_main_list_failing_while_a_second_reads_never_lowers() -> None:
    reads = {key: {"radio": [WHOLE]} for key in WINDOW_UTC if key >= "11:30"}
    found = proofs(morning(reads))
    assert p_stars(found)[-1] == 390
    assert all(item.ended is None for item in found)
    full = xs(proofs(morning()))
    held = xs(found)
    assert all(h <= f for h, f in zip(held, full, strict=True))


def test_tier_b_alone_and_an_empty_r_never_prove() -> None:
    assert p_stars(proofs(morning(), Required(()))) == [None] * 10
    assert xs(proofs(morning(), Required(()))) == [0.0] * 10


def test_a_latest_slot_failure_holds() -> None:
    health = {"12:00": 500}
    found = proofs(morning(health=health))
    # 07:00 to 07:30 local is unhealthy: P at 07:30 is 07:00's
    assert p_stars(found)[3:6] == [420, 420, 480]
    assert xs(found)[3:5] == [45, 45]


def test_a_dark_required_list_blocks_proof_all_day() -> None:
    # the lead's ruling: a required list the reader attempts with no whole read in 45 days
    # proves nothing, and the district is never proven, so a reading failure never lowers
    first_at_eight = {
        key: {"tv": [WHOLE], "radio": [WHOLE], "paper": [WHOLE]}
        for key in WINDOW_UTC
        if key >= "13:00"
    }
    unhealthy = {"13:00": 500}
    needed = Required(("paper", *LISTS), dark=("paper",))
    found = proofs(morning(first_at_eight, health=unhealthy), needed)
    assert p_stars(found) == [None] * 7 + [540, 570, 600]
    no_read = proofs(morning(), needed)
    assert p_stars(no_read) == [None] * 10
    assert xs(no_read) == [0.0] * 10


def test_required_lists_are_every_tier_a_list_in_the_live_registry() -> None:
    coverage = listed(
        Coverage(
            county_sources={},
            archive={s: {LEAID} for s in ("paper", "radio", "tv", "gone")},
            county_of={},
        )
    )
    stats = ListStats.of(coverage, LiveCaptures(), RULE.labels.station_min_captures)
    day20 = {
        WED - timedelta(days=20): frozenset({"radio"}),
        WED - timedelta(days=1): frozenset({"tv"}),
    }
    found = required(
        LEAID, WED, day20, coverage, stats, audience={}, registry=MARKETS, settings=SETTINGS
    )
    assert found.sources == ("paper", "radio", "tv")
    # radio read whole on day 20 and failing since stays required, and is not dark
    assert found.dark == ("paper",)
    assert found.archive_only == ("gone",)
    assert dark_cause("blocked") is DarkCause.REFUSED
    assert dark_cause("error") is DarkCause.FAILED
    assert dark_cause("deferred") is DarkCause.DEFERRED
    assert dark_cause("partial") is dark_cause(None) is DarkCause.NEVER_WHOLE
    # a host with no ledger outcomes (the state export's schema-only ledger) never guesses
    assert dark_cause("blocked", known=False) is DarkCause.NOT_HERE
    assert dark_cause(None, known=False) is DarkCause.NOT_HERE


def test_a_list_read_on_day_20_and_failing_since_blocks() -> None:
    reads = {key: {"tv": [WHOLE]} for key in WINDOW_UTC}
    assert p_stars(proofs(morning(reads))) == [None] * 10


def test_a_silent_list_failing_stale_populated_with_no_later_slot_voids() -> None:
    # a warning morning: radio names a district at 07:30 local (12:30Z) while tv, populated,
    # names none; tv's earlier slots fail by the longer window: D's proof ends (Delta 0)
    by = {key: {"radio": ["3699999"]} for key in WINDOW_UTC if key >= "12:00"}
    found = proofs(morning(by=by), warning=True)
    ended = [item.ended for item in found]
    assert ended[:4] == [None] * 4
    assert ended[4:] == ["void"] * 6
    assert [d.delta for d in decline(found, OWN_U, SETTINGS)][4:] == [0.0] * 6
    # the same list naming others from 07:00 on: no void
    both = {key: {"radio": ["3699999"], "tv": ["3699998"]} for key in WINDOW_UTC if key >= "12:00"}
    assert all(item.ended is None for item in proofs(morning(by=both), warning=True))


def test_a_naming_ends_proof_for_the_day() -> None:
    named = {"12:00": {LEAID: {"2026-01-14": ["closed"]}}}
    found = proofs(morning(named=named))
    assert [item.ended for item in found][4:] == ["named"] * 6
    assert [d.delta for d in decline(found, OWN_U, SETTINGS)][4:] == [0.0] * 6
    every = proofs(morning(), every_before=frozenset({LEAID}))
    assert {item.ended for item in every} == {"named"}
    before = proofs(morning(named_before={LEAID: frozenset({"closed"})}))
    assert {item.ended for item in before} == {"named"}


def test_condition_4_and_a_record_that_stops_hold() -> None:
    # neither list has a recent counted day, and both share a market: condition 4 holds
    assert p_stars(proofs(morning(), recent={}))[-1] == 600
    alone = {key: {"tv": [WHOLE]} for key in WINDOW_UTC}
    assert p_stars(proofs(morning(alone), Required(("tv",)), recent={}))[-1] is None
    # the record stops at 12:30Z (07:30 local): every later slot end holds
    cut = proofs(morning(until="12:00"))
    assert p_stars(cut) == [330, 360, 390, 420, 450, 450, 450, 450, 450, 450]
    assert all(item.ended is None for item in cut)


# --- safety -------------------------------------------------------------------------------------


def test_the_decline_is_monotone_and_falls_at_most_its_first_slot_at_the_corners_of_f() -> None:
    corners = ((0.35, 45), (0.60, 90), (0.60, 20), (0.35, 90))
    for m, tau in corners:
        settings = CallSettings.of(CFG, m, tau)
        first = abs(delta(30, m, tau))
        assert first <= settings.first_slot_max + 1e-9
        for u in range(-300, 601, 30):
            usual_ = UsualCall(u, 3, PoolKind.MARKET)
            for lag in (0, 1, 3):
                # late proof, a hold and a resume: P* steps by slot or stands
                steps = [
                    SlotProof(end, max(330, end - 30 * lag) if end > 330 + 30 * lag else None)
                    for end in settings.ends()
                ]
                found = decline(steps, usual_, settings)
                values = [d.delta for d in found]
                assert values == sorted(values, reverse=True)
                assert all(d.delta >= math.log(m) - 1e-12 for d in found)
                gaps = [a.delta - b.delta for a, b in pairwise(found)]
                assert all(g <= first + 1e-9 for g in gaps)
                xs_ = [d.x for d in found]
                assert xs_ == sorted(xs_)
                assert all(b - a <= 30 for a, b in pairwise(xs_))


def test_every_minute_past_u_the_chance_never_rises_while_proof_stands() -> None:
    for minute in range(-300, 601):
        steps = [SlotProof(end, end) for end in SETTINGS.ends()]
        found = decline(steps, UsualCall(minute, 0, PoolKind.STATE), SETTINGS)
        chances = [moved_by(0.5, 0.1, d.delta)[0] for d in found]
        assert chances == sorted(chances, reverse=True)
        assert all(c <= 0.5 for c in chances)


def test_applies_is_the_frozen_records_model_branch_on_the_golden_passes(tmp_path: Path) -> None:
    # the frozen record keeps pr exactly where the pass's chance is the model's own
    # (``_unrounded``'s model branch), and for said_open, which applies never moves
    _passes(adjusting_pass, tmp_path)
    found = frozen.rows(fa_test.DAY, fa_test.DAY, tmp_path)[fa_test.DAY].rows
    assert found
    for row in found:
        kinds = {kind for kind, _points in row.reasons}
        known = row.p_raw is not None
        assert applies(kinds, raw_known=known) is (known and not row.said_open)
        if known and not row.said_open:
            assert not kinds or kinds <= ADJUST_KINDS
    for entry in golden_file().districts:
        for item in entry.days:
            kinds = {str(r.kind) for r in item.why.reasons}  # type: ignore[union-attr]
            assert not applies(kinds, raw_known=True) or not kinds or kinds <= ADJUST_KINDS
    assert not applies({"said_open"}, raw_known=True)
    assert not applies({"snow_total", "neighbors"}, raw_known=True)
    assert applies({"snow_total"}, raw_known=True)
    assert not applies({"snow_total"}, raw_known=False)
    assert applies(set(), raw_known=True)


# --- the decision rule's rows -------------------------------------------------------------------


def test_at_risk_named_at_06_10_closed_at_07_00() -> None:
    kwargs: dict[str, Any] = {"read": True, "served": True, "called": 420, "named": 390}
    assert at_risk(360, **kwargs) is Risk.AT_RISK
    assert at_risk(390, **kwargs) is Risk.NAMED
    assert at_risk(420, **kwargs) is Risk.LIT
    assert at_risk(360, **{**kwargs, "read": False}) is Risk.NOT_READ
    assert at_risk(360, **{**kwargs, "served": False}) is Risk.NOT_SERVED
    named = {"11:00": {LEAID: {"2026-01-14": ["closed"]}}}
    # named in the 06:00 slot: known by its end, 06:30
    assert call_time.first_named(morning(named=named), LEAID, EAST, frozenset()) == 390
    assert call_time.first_named(morning(), LEAID, EAST, frozenset({LEAID})) == -1440


# --- the counts line, the census and the imports ------------------------------------------------


def test_only_read_cli_imports_call_time() -> None:
    importers = []
    for path in sorted((PIPELINE_ROOT / "snowlight").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            if "snowlight.predict.call_time" in names:
                importers.append(path.name)
    assert importers == ["read_cli.py"]


def test_the_counts_line_prints_and_an_error_there_changes_nothing(
    tmp_path: Path, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = world.utc("2026-01-08T06:00:00")
    host = Host()
    assert read_cli.read_once(read_run(host, tmp_path / "a", now)) == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if "call time (off)" in line]
    assert len(lines) == 2
    assert "::warning::" not in out
    assert "u none" in lines[0]

    def broken(*_args: object, **_kwargs: object) -> dict[str, int]:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(call_time, "day_counts", broken)
    other = Host()
    added = tmp_path / "out.txt"
    run = replace(read_run(other, tmp_path / "b", now), outputs=added)
    assert read_cli.read_once(run) == 0
    out = capsys.readouterr().out
    assert "::warning::predict read-labels: call time counts: RuntimeError" in out
    assert other.files == host.files
    assert added.read_text() == "added=true\n"
    for name in ("rows", "trials"):
        a = sorted(p.read_bytes() for p in (tmp_path / "a" / name).glob("*"))
        b = sorted(p.read_bytes() for p in (tmp_path / "b" / name).glob("*"))
        assert a == b


def test_the_counts_line_is_skipped_past_90_seconds(capsys: Any, tmp_path: Path) -> None:
    run = read_run(Host(), tmp_path, world.utc("2026-01-08T06:00:00"))
    done = live_read.ReadRun(added=[date(2026, 1, 6)])
    read_cli.call_time_lines(run, done, began=-1e9)
    assert "skipped past 90 s" in capsys.readouterr().out


def test_the_frozen_rows_served_are_the_ones_with_a_model_chance(tmp_path: Path) -> None:
    assert read_cli._served(None, WED) == frozenset()
    assert read_cli._served(tmp_path / "none", WED) == frozenset()
    _passes(adjusting_pass, tmp_path)
    found = frozen.rows(fa_test.DAY, fa_test.DAY, tmp_path)[fa_test.DAY].rows
    expect = {
        r.leaid for r in found
        if r.freeze == "d0_0630" and r.served and r.p_raw is not None and not r.said_open
    }  # fmt: skip
    assert read_cli._served(tmp_path, fa_test.DAY) == expect


def test_the_counts_line_counts_dark_districts_by_cause_and_proven_ones_by_time() -> None:
    coverage = listed(
        Coverage(county_sources={}, archive={s: {LEAID} for s in (*LISTS, "paper")}, county_of={})
    )
    stats = ListStats.of(coverage, LiveCaptures(), RULE.labels.station_min_captures)
    found = morning()
    record = call_time.whole_reads({WED: found.slots}, "v1")
    calls = [*pool_calls(), morning_call(LEAID, WED, 470)]
    inputs = call_time.DayInputs(
        day=WED, morning=found, directory=directory(), coverage=coverage, stats=stats,
        classes=[WeatherClass.ADVISORY], read={LEAID}, unknown=frozenset(), calls=calls,
        record=record, recent=dict.fromkeys(LISTS, 1), every_before=frozenset(),
        served={LEAID}, outcomes={"paper": "blocked"},
    )  # fmt: skip
    counts = call_time.day_counts(inputs, SETTINGS, RULE)
    # paper, in the registry with no whole read in 45 days, is required: never proven
    assert counts["unproven dark refused"] == 1
    assert counts["proven by 09:30"] == 0
    assert counts["call morning"] == 1
    assert counts["07:30 at_risk"] == 1  # lit at 07:50
    # the market's pool holds none of the ten calls before the day: the state's pool
    assert counts["u state"] == 1
    proven_ = call_time.day_counts(replace(inputs, coverage=COVERAGE, stats=STATS), SETTINGS, RULE)
    assert [proven_[f"proven by {t}"] for t in ("06:30", "07:30", "08:30", "09:30")] == [1, 1, 1, 1]
    assert "unproven dark refused" not in proven_
    line = call_time.counts_line(WED, proven_)
    assert line.startswith(
        "call time (off) 2026-01-14: call ahead 0, call evening 0, call morning 1"
    )
    assert LEAID not in line  # counts only, no ids


def test_a_withheld_state_or_no_record_never_lowers() -> None:
    withheld = morning()
    at = datetime.combine(WED, time(12), tzinfo=UTC)
    withheld.slots[at].unknown = {"NY"}
    found = proofs(withheld)
    # 07:00 to 07:30 local withheld NY whole: that slot adds nothing, so P* holds at 07:30
    assert p_stars(found)[3:6] == [420, 420, 480]
    full = xs(proofs(morning()))
    assert all(a <= b for a, b in zip(xs(found), full, strict=True))
    empty = replace(morning(), slots={})
    assert p_stars(proofs(empty)) == [None] * 10
    assert xs(proofs(empty)) == [0.0] * 10


# --- review r1: the limit inside a day, the export's ledger, mixed causes, the served rows ------


TUESDAY = date(2026, 1, 6)
"""The synthetic world's timeline day."""


class SlowSource(ReadingSource):
    """SYNTHETIC: the read test's source with a day index of final days, whose timeline reads
    advance a fake clock (a slow host) once ``ticking``, and count themselves."""

    def __init__(self, timelines: Mapping[date, DayTimeline], days: Sequence[date]) -> None:
        super().__init__(timelines)
        self.days = days
        self.clock = 0.0
        self.ticking = False
        self.read: list[date] = []

    def index(self) -> DayIndex | None:
        entries = tuple(DayEntry(day=d, schools=1, final=True) for d in sorted(self.days)[::-1])
        return DayIndex(
            schema_version=1, generated_at=world.utc("2026-01-08T06:00:00"), days=entries
        )

    def timeline(self, day: date) -> DayTimeline | None:
        if self.ticking:
            self.read.append(day)
            self.clock += 60.0
        return super().timeline(day)


CLASS_DAYS = (date(2025, 12, 18), date(2025, 12, 19), date(2026, 1, 2), MONDAY, TUESDAY)
"""SYNTHETIC final days with a class snapshot; Dec 17 is final with none."""


def slow_run(tmp_path: Path) -> tuple[read_cli.ReadLabelsRun, SlowSource, live_read.ReadRun]:
    base = read_run(Host(), tmp_path / "reads", world.utc("2026-01-08T06:00:00"))
    timelines = {day: world.timeline().model_copy(update={"day": day}) for day in CLASS_DAYS}
    source = SlowSource(timelines, (date(2025, 12, 17), *CLASS_DAYS))
    snapshots: dict[str, object] = {}
    for day in CLASS_DAYS:
        snapshots.update(snapshots_for(day))
    run = replace(base, source=source, snapshots=snapshots)
    done = live_read.read_new_days(
        run.folder, source, directory=run.directory, coverage=run.coverage,
        snapshots=run.snapshots, config=run.config, now=run.now,
    )  # fmt: skip
    assert done.added == [MONDAY, TUESDAY]
    source.ticking = True
    return run, source, done


def test_the_counts_line_stops_inside_a_day_once_a_slow_host_passes_its_limit(
    tmp_path: Path, capsys: Any
) -> None:
    run, source, done = slow_run(tmp_path)
    # each timeline read takes 60 s: the second ends past 90 s, so no third read starts,
    # the day's line is not printed, and one skip line is
    read_cli.call_time_lines(run, done, 0.0, clock=lambda: source.clock)
    out = capsys.readouterr().out
    assert len(source.read) == 2
    assert source.clock == 120.0
    assert out == "predict read-labels: call time (off): skipped past 90 s of the step\n"


def test_the_counts_line_reads_each_class_days_timeline_once_and_no_other(
    tmp_path: Path, capsys: Any
) -> None:
    run, source, done = slow_run(tmp_path)
    read_cli.call_time_lines(run, done, 0.0, clock=lambda: 0.0)
    out = capsys.readouterr().out
    assert out.count("call time (off) 2026-01-0") == 2
    assert "::warning::" not in out
    # Dec 17 has no class snapshot (u reaches back only as far as the snapshots kept): its
    # timeline is never read; every class day's is read once a run
    assert sorted(source.read) == sorted(CLASS_DAYS)


def test_the_counts_line_limit_counts_from_the_steps_start(tmp_path: Path, capsys: Any) -> None:
    run = replace(read_run(Host(), tmp_path, world.utc("2026-01-08T06:00:00")), started=-1e9)
    assert read_cli.read_once(run) == 0
    out = capsys.readouterr().out
    assert "call time (off): skipped past 90 s of the step" in out
    assert "call time (off) 2026-01-0" not in out
    assert "::warning::" not in out


def test_the_counts_line_reads_the_coverage_l1_read_with(
    tmp_path: Path, capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # audiences of an old season are dropped from L1's coverage: the counts line drops them too
    seen: list[Coverage] = []
    real = call_time.day_counts

    def spy(inputs: call_time.DayInputs, *args: Any, **kwargs: Any) -> dict[str, int]:
        seen.append(inputs.coverage)
        return real(inputs, *args, **kwargs)

    monkeypatch.setattr(call_time, "day_counts", spy)
    base = read_run(Host(), tmp_path, world.utc("2026-01-08T06:00:00"))
    run = replace(base, coverage=replace(base.coverage, audience_season=2020))
    assert run.coverage.archive
    assert read_cli.read_once(run) == 0
    assert "call time (off) 2026-01-05" in capsys.readouterr().out
    assert seen
    assert all(found.archive == {} for found in seen)


def two_dark_inputs(outcomes: Mapping[str, str] | None) -> call_time.DayInputs:
    lists = (*LISTS, "paper", "flashalert-spokane")
    coverage = listed(
        Coverage(county_sources={}, archive={s: {LEAID} for s in lists}, county_of={})
    )
    stats = ListStats.of(coverage, LiveCaptures(), RULE.labels.station_min_captures)
    found = replace(morning(), market_of={**MARKETS, "flashalert-spokane": "Albany"})
    return call_time.DayInputs(
        day=WED, morning=found, directory=directory(), coverage=coverage, stats=stats,
        classes=[WeatherClass.ADVISORY], read={LEAID}, unknown=frozenset(), calls=pool_calls(),
        record=call_time.whole_reads({WED: found.slots}, "v1"), recent=dict.fromkeys(LISTS, 1),
        every_before=frozenset(), served={LEAID}, outcomes=outcomes,
    )  # fmt: skip


def test_a_district_with_dark_lists_of_two_causes_counts_once_under_both() -> None:
    both = {"paper": "blocked", "flashalert-spokane": "error"}
    counts = call_time.day_counts(two_dark_inputs(both), SETTINGS, RULE)
    assert counts["unproven dark refused+failed"] == 1
    assert sum(v for k, v in counts.items() if k.startswith("unproven")) == 1
    same = call_time.day_counts(
        two_dark_inputs({**both, "flashalert-spokane": "blocked"}), SETTINGS, RULE
    )
    assert same["unproven dark refused"] == 1


def test_on_an_exported_state_the_counts_line_never_guesses_a_dark_cause(tmp_path: Path) -> None:
    # the predict job reads the live state's export, whose ledger is schema only: a list the
    # reader is refused must never be counted as never whole there
    full = tmp_path / "state"
    full.mkdir()
    ledger = Ledger(full / "ledger.sqlite")
    ledger.observe("paper", LedgerOutcome.BLOCKED, datetime(2026, 1, 14, 12, tzinfo=UTC))
    ledger.close()
    exported = tmp_path / "exported"
    exported.mkdir()
    state.unpack(state.export(full), exported)

    def held(folder: Path) -> Any:
        return SimpleNamespace(state=SimpleNamespace(folder=folder))

    assert read_cli._outcomes(held(full)) == {"paper": "blocked"}
    assert read_cli._outcomes(held(exported)) is None
    assert read_cli._outcomes(held(tmp_path / "none")) is None
    assert read_cli._outcomes(object()) is None
    counts = call_time.day_counts(
        two_dark_inputs(read_cli._outcomes(held(exported))), SETTINGS, RULE
    )
    assert counts["unproven dark (cause not on this host)"] == 1
    assert not any("never_whole" in k or "refused" in k for k in counts)
    on_box = call_time.day_counts(two_dark_inputs(read_cli._outcomes(held(full))), SETTINGS, RULE)
    assert on_box["unproven dark refused+never_whole"] == 1


def test_a_district_with_only_a_0507_frozen_row_is_not_served_at_07_30(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def row(leaid: str, freeze: str) -> Any:
        return SimpleNamespace(leaid=leaid, freeze=freeze, served=True, p_raw=0.5, said_open=False)

    early = "3600002"
    found = {WED: SimpleNamespace(rows=[row(LEAID, "d0_0630"), row(early, "d0_0507")])}
    monkeypatch.setattr(frozen, "rows", lambda *_args: found)
    served = read_cli._served(tmp_path, WED)
    assert served == {LEAID}
    inputs = replace(
        call_time.DayInputs(
            day=WED, morning=morning(), directory=directory(leaid=early), coverage=COVERAGE,
            stats=STATS, classes=[WeatherClass.ADVISORY], read={early}, unknown=frozenset(),
            calls=[], record={}, recent={}, every_before=frozenset(), served=served,
        ),
    )  # fmt: skip
    assert call_time.day_counts(inputs, SETTINGS, RULE)["07:30 not_served"] == 1

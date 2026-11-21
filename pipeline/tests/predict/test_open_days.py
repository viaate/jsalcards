"""The open-day rule (records-mo MO-2, rule 3 with lead ruling LR-1): planted days off are never
open, a day with a row is decided by its row, and the committed config's rule reads."""

from collections.abc import Iterable, Mapping
from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.predict import open_days, state_records
from snowlight.predict.calendar import is_school_day, thanksgiving
from snowlight.predict.open_days import AlertDays, DistrictDays, OpenDayRule, alert_days

RULE = OpenDayRule(
    rule=3,
    complete_years=("2025-26",),
    winter_late_from=15,
    winter_early_until=12,
    spring_from=(3, 1),
    spring_until=(4, 20),
    four_day_lost_days=6,
    isolation_share=0.8,
    isolation_peers=3,
    crowd_share=0.95,
    crowd_peers=10,
)
LEA = "2900001"
ADVISORY = 1
WARNING = 5
# a year with lost days on every weekday (no four-day week) and a weather row
LOST = {
    date(2025, 10, 6): "C",
    date(2025, 10, 14): "C",
    date(2025, 10, 22): "S",
    date(2025, 10, 30): "C",
    date(2025, 11, 7): "H",
    date(2025, 11, 13): "C",
}


def book(calls: Mapping[date, str], leaid: str = LEA, weather: bool = True) -> DistrictDays:
    found = {(leaid, d): c for d, c in calls.items()}
    years = frozenset({(leaid, 2025)}) if weather else frozenset()
    return DistrictDays(found, years)


def run(
    days: DistrictDays,
    alerts: Iterable[tuple[str, date, int]],
    county: Mapping[str, str] | None = None,
) -> AlertDays:
    return alert_days(days, alerts, (county or {},), RULE)


def kept(days: DistrictDays, day: date, value: int = ADVISORY) -> str | None:
    found = run(days, [(LEA, day, value)])
    return found.kept[0].outcome if found.kept else None


def test_a_planted_day_off_is_never_open() -> None:
    days = book(LOST)
    never = [
        date(2025, 11, 26),  # Thanksgiving Wednesday
        date(2025, 11, 24),  # Thanksgiving week Monday
        date(2026, 1, 19),  # Martin Luther King Jr. Day
        date(2026, 2, 16),  # Presidents' Day
        date(2026, 4, 3),  # Good Friday
        date(2026, 4, 6),  # Easter Monday
        date(2025, 11, 11),  # Veterans Day on a Tuesday
        date(2025, 12, 18),  # no later December row
        date(2026, 1, 6),  # no January row on or before
        date(2026, 3, 10),  # no row that spring week
        date(2025, 12, 1),  # LR-1: the Monday after Thanksgiving week, no row that week
        date(2026, 1, 20),  # LR-1: the Tuesday after MLK Day, no row that week
        date(2026, 2, 17),  # LR-1: the Tuesday after Presidents' Day, no row that week
        date(2025, 11, 15),  # a Saturday
    ]
    for day in never:
        assert kept(days, day) is None, day
    # Veterans Day on a Sunday: the Monday after is its observed day
    assert open_days.fixed_off(date(2018, 11, 12)) == "Veterans Day or its observed day"


def test_a_break_edge_counts_with_a_row_that_week() -> None:
    week = {**LOST, date(2026, 1, 22): "C", date(2025, 12, 3): "M"}
    assert kept(book(week), date(2026, 1, 20)) == "open"
    assert kept(book(week), date(2025, 12, 1), WARNING) == "open"
    assert open_days.break_edge(thanksgiving(2025) + timedelta(days=4))


def test_an_ordinary_alert_day_with_rows_before_it_is_open() -> None:
    assert kept(book(LOST), date(2026, 1, 27)) == "open"
    assert kept(book(LOST), date(2026, 1, 27), WARNING) == "open"


def test_a_day_with_a_row_is_decided_by_its_row_and_a_make_up_day_is_school_held() -> None:
    for call, outcome in (("C", "closed"), ("H", "remote"), ("S", "short"), ("M", "makeup")):
        days = book({**LOST, date(2026, 1, 27): call})
        assert kept(days, date(2026, 1, 27), WARNING) == outcome
    # a row decides even on a day the window tests would leave out
    assert kept(book({**LOST, date(2025, 12, 18): "C"}), date(2025, 12, 18)) == "closed"


def test_a_year_with_no_weather_row_gives_no_open_day_and_other_years_none() -> None:
    assert kept(book(LOST, weather=False), date(2026, 1, 27)) is None
    found = run(book(LOST), [(LEA, date(2024, 1, 23), ADVISORY)])
    assert found.left == {"not a complete year": 1}


def test_the_four_day_week_comes_from_lost_days_only() -> None:
    # every lost day falls Tuesday to Friday; the make-up days fall on Mondays
    lost = {
        date(2025, 10, 7): "C",
        date(2025, 10, 15): "C",
        date(2025, 10, 23): "C",
        date(2025, 10, 31): "C",
        date(2025, 11, 4): "H",
        date(2025, 11, 12): "S",
    }
    made = {date(2025, 10, 13): "M", date(2025, 10, 20): "M", date(2025, 10, 27): "M"}
    days = book({**lost, **made})
    assert kept(days, date(2026, 1, 26)) is None  # a Monday: its day off
    assert kept(days, date(2026, 1, 27)) == "open"
    # fewer than six lost days: every Monday and Friday is left out
    few = book(dict(list(LOST.items())[:5]))
    assert kept(few, date(2026, 1, 26)) is None
    assert kept(few, date(2026, 1, 30)) is None
    assert kept(few, date(2026, 1, 27)) == "open"


def test_an_advisory_day_after_a_no_school_day_is_left_out() -> None:
    days = book({**LOST, date(2026, 1, 26): "C"})
    assert kept(days, date(2026, 1, 27)) is None
    assert kept(days, date(2026, 1, 27), WARNING) == "open"


def test_the_isolation_guard_leaves_out_a_lone_open_day_before_a_closing() -> None:
    day, after = date(2026, 1, 27), date(2026, 1, 28)
    peers = [f"290000{i}" for i in range(2, 6)]
    calls = {(LEA, d): c for d, c in LOST.items()} | {(LEA, after): "C"}
    calls |= {(p, d): c for p in peers for d, c in LOST.items()}
    calls |= {(p, day): "C" for p in peers}
    years = frozenset({(LEA, 2025), *((p, 2025) for p in peers)})
    county = dict.fromkeys([LEA, *peers], "048")
    alerts = [(u, day, WARNING) for u in [LEA, *peers]]
    found = run(DistrictDays(calls, years), alerts, county)
    assert found.isolated == [(LEA, day, "warning")]
    assert {k.outcome for k in found.kept} == {"closed"}
    # school on the next school day, or another county: counted open
    calls[LEA, after] = "M"
    found = run(DistrictDays(calls, years), alerts, county)
    assert not found.isolated
    calls[LEA, after] = "C"
    found = run(DistrictDays(calls, years), alerts, {**county, LEA: "019"})
    assert not found.isolated
    # the same share among the districts near it (a second peer group) is enough
    area = dict.fromkeys([LEA, *peers], "EAX")
    found = alert_days(DistrictDays(calls, years), alerts, ({**county, LEA: "019"}, area), RULE)
    assert found.isolated == [(LEA, day, "warning")]


def test_the_guard_leaves_out_a_no_row_day_when_nearly_every_district_near_it_had_none() -> None:
    # a storm warning day with school on the next school day, so the first arm passes it,
    # but 19 of 20 districts near it had no school that day
    day, after = date(2026, 1, 27), date(2026, 1, 28)
    peers = [f"29001{i:02d}" for i in range(20)]
    calls = {(u, d): c for u in [LEA, *peers] for d, c in LOST.items()} | {(LEA, after): "M"}
    calls |= {(p, day): "C" for p in peers[:19]} | {(peers[19], day): "M"}
    years = frozenset((u, 2025) for u in [LEA, *peers])
    area = dict.fromkeys([LEA, *peers], "EAX")
    alerts = [(u, day, WARNING) for u in [LEA, *peers]]
    found = alert_days(DistrictDays(calls, years), alerts, ({}, area), RULE)
    assert found.isolated == [(LEA, day, "warning")]
    # 18 of 20 (0.9): under the share, counted open
    calls[peers[18], day] = "M"
    found = alert_days(DistrictDays(calls, years), alerts, ({}, area), RULE)
    assert not found.isolated
    assert (LEA, "open") in {(k.leaid, k.outcome) for k in found.kept}
    # all of 9 peers: too few for this arm, counted open
    calls |= {(p, day): "C" for p in peers}
    few = [(u, day, WARNING) for u in [LEA, *peers[:9]]]
    found = alert_days(DistrictDays(calls, years), few, ({}, area), RULE)
    assert not found.isolated


def _county(
    calls: dict[tuple[str, date], str], peers: list[str], day: date, value: int = ADVISORY
) -> AlertDays:
    """The rule over LEA and ``peers`` of one county (each with LOST's year) on ``day``."""
    for unit in [LEA, *peers]:
        calls |= {(unit, d): c for d, c in LOST.items() if (unit, d) not in calls}
    years = frozenset((u, 2025) for u in [LEA, *peers])
    county = dict.fromkeys([LEA, *peers], "048")
    return run(DistrictDays(calls, years), [(u, day, value) for u in [LEA, *peers]], county)


def test_a_peer_whose_own_day_is_left_out_still_counts_by_its_row() -> None:
    # the second day of a storm: every county peer was closed the day before, so its own
    # advisory day is left out as advisory_after, yet its closed row is still the peer's call
    before, day, after = date(2026, 1, 27), date(2026, 1, 28), date(2026, 1, 29)
    peers = ["2900002", "2900003", "2900004"]
    calls = {(LEA, after): "C"} | {(p, d): "C" for p in peers for d in (before, day)}
    found = _county(calls, peers, day)
    assert found.isolated == [(LEA, day, "advisory")]
    assert found.left["advisory after a no-school day"] == len(peers)
    assert not found.kept
    # a peer with no row that fails a test (no weather row that year) is no peer
    found = alert_days(
        DistrictDays(
            {**calls, **{(LEA, d): c for d, c in LOST.items()}}
            | {(p, d): c for p in peers for d, c in LOST.items() if (p, d) not in calls},
            frozenset((u, 2025) for u in [LEA, *peers]),
        ),
        [(u, day, ADVISORY) for u in [LEA, *peers, "2900005"]],
        (dict.fromkeys([LEA, *peers, "2900005"], "048"),),
        RULE,
    )
    assert found.isolated == [(LEA, day, "advisory")]
    # with a weather row that year it is a peer with school: 3 of 4 closed, under the share
    calls = {(LEA, after): "C"} | {(p, d): "C" for p in peers for d in (before, day)}
    found = _county(calls, [*peers, "2900005"], day)
    assert not found.isolated
    assert [(k.leaid, k.outcome) for k in found.kept] == [(LEA, "open"), ("2900005", "open")]
    # a peer with no row whose own advisory day is left out (closed the day before) is no
    # peer with school: the rule does not count its day as one
    calls = {(LEA, after): "C"} | {(p, d): "C" for p in peers for d in (before, day)}
    found = _county(calls | {("2900005", before): "C"}, [*peers, "2900005"], day)
    assert found.isolated == [(LEA, day, "advisory")]
    # the crowd arm reads them too: 10 of 10 closed the day before and that day
    crowd = [f"29001{i:02d}" for i in range(10)]
    calls = {(LEA, after): "M"} | {(p, d): "C" for p in crowd for d in (before, day)}
    assert _county(calls, crowd, day).isolated == [(LEA, day, "advisory")]


def test_an_isolated_day_is_never_another_districts_peer_with_school() -> None:
    # B (no row, closed the next school day) is isolated by the first arm with 10 of 11 peers
    # closed; only once B is left out are all 10 of A's other peers closed, so the crowd arm
    # leaves A's day out too (one pass would keep it open, with B a peer with school)
    day, after = date(2026, 1, 27), date(2026, 1, 28)
    other = "2900099"
    crowd = [f"29001{i:02d}" for i in range(10)]
    calls = {(LEA, after): "M", (other, after): "C"} | {(p, day): "C" for p in crowd}
    found = _county(calls, [other, *crowd], day, WARNING)
    assert sorted(found.isolated) == [(LEA, day, "warning"), (other, day, "warning")]
    assert {k.outcome for k in found.kept} == {"closed"}


def test_the_next_school_day_is_read_past_the_fixed_days_off() -> None:
    # a Friday before Martin Luther King Jr. Day with no row: its next school day is the
    # Tuesday after, which it was closed, as 3 of 3 county peers were that Friday
    friday, tuesday = date(2026, 1, 16), date(2026, 1, 20)
    assert open_days.next_school_day(friday) == tuesday
    assert open_days.next_school_day(date(2025, 11, 21)) == date(2025, 12, 1)
    peers = ["2900002", "2900003", "2900004"]
    calls = {(LEA, tuesday): "C"} | {(p, friday): "C" for p in peers}
    found = _county(calls, peers, friday, WARNING)
    assert found.isolated == [(LEA, friday, "warning")]
    # school that Tuesday: counted open
    calls = {(LEA, tuesday): "M"} | {(p, friday): "C" for p in peers}
    assert not _county(calls, peers, friday, WARNING).isolated


def test_the_committed_rule_is_rule_3_over_the_five_complete_years() -> None:
    rule = state_records.load().states["mo"].open_days
    assert rule is not None
    assert rule.rule == 3
    assert (rule.crowd_share, rule.crowd_peers) == (0.95, 10)
    assert rule.complete_years == ("2016-17", "2017-18", "2018-19", "2024-25", "2025-26")
    days = open_days.read_days(
        state_records.read_derived(state_records.load().states["mo"], "mo-days-ed1.csv")
    )
    assert len(days.calls) == 26265


SEASON = [
    date(2025, 9, 2) + timedelta(days=i)
    for i in range(280)
    if is_school_day(date(2025, 9, 2) + timedelta(days=i))
]


@settings(max_examples=60, deadline=None)
@given(
    off_weekday=st.sampled_from([0, 4]),
    lost=st.sets(st.sampled_from([d for d in SEASON if d.weekday() not in {0, 4}]), min_size=6),
    alerts=st.sets(st.sampled_from(SEASON), min_size=1, max_size=40),
)
def test_no_planted_day_off_is_ever_open(
    off_weekday: int, lost: set[date], alerts: set[date]
) -> None:
    """A four-day week on Mondays or Fridays whose make-ups fall on its day off, Thanksgiving
    week, MLK Day, Presidents' Day, Good Friday, Easter Monday and Veterans Day: none of them
    is ever open, whatever the lost days and alert days."""
    lost = {d for d in lost if d.weekday() != off_weekday}
    if len({d.weekday() for d in lost}) < 3:
        return
    made = {d: "M" for d in SEASON if d.weekday() == off_weekday and d not in lost}
    calls = {**dict.fromkeys(sorted(lost), "C"), **dict(list(made.items())[:10])}
    found = run(book(calls), [(LEA, d, ADVISORY) for d in alerts])
    for item in found.kept:
        if item.outcome == "open":
            assert item.day.weekday() != off_weekday
            assert open_days.fixed_off(item.day) is None
            assert item.day not in calls

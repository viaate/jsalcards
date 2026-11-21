"""Which alert school days of a state's dated calendar file count, and what the district did
on each (records-mo MO-2; docs/predict.md, "Past records").

A state's calendar file lists every school day a district lost to the weather. A school day
with a winter alert that is **not** on the list then counts as a day the district had school,
but only when every test of the open-day rule passes (rule 3: spec SPEC RECORDS-MO r2 section
3 with lead ruling LR-1). Each test only removes days:

1. A weekday and a school day by the default calendar (:func:`calendar.is_school_day`).
2. Not a fixed day off: Thanksgiving week Monday to Friday, Martin Luther King Jr. Day,
   Presidents' Day, Good Friday, Easter Monday, Veterans Day (November 11) and its observed day.
3. **Break edges** (LR-1): the Monday after Thanksgiving week and the Tuesday after Martin
   Luther King Jr. Day and after Presidents' Day count only when the district has a row in that
   Monday to Friday week.
4. **Winter break:** December 15 to 31 counts only with a row on a later December date; January
   1 to 12 only with a row on an earlier or the same January date.
5. **Spring break:** March 1 to April 20 counts only with a row in the same Monday to Friday
   week.
6. **Four-day weeks:** a lost day is one called closed, at home, short or some. In a year with
   ``four_day_lost_days`` or more lost days, a weekday with no lost day all year is the
   district's day off; with fewer, every Monday and Friday is left out. Make-up days never
   count here (a four-day district holds its make-ups on its day off).
7. **Reporting:** a year in which the district lists no weather day row gives no open day.
8. **Isolation guard** (LR-1): a day with no row is left out when the district had no school on
   its next school day (past the fixed days off of test 2) and ``isolation_share`` or more of
   its county peers (at least ``isolation_peers`` of them) had no school that day: a likely day
   off, or a closing filed under a code the file does not hold. A peer is every other district
   of the county with an alert that date, whatever its own record keeps (an advisory day after a
   no-school day included): its row decides by its call (closed or at home, no school; short or
   a make-up day, school), and a peer with no row counts as school only when the rule counts its
   own day as one (it passes tests 1 to 7, is not an advisory day after a no-school day and is
   not itself isolated). The guard runs until no more days are left out, so an isolated day is
   never another district's peer with school. The same test runs over the districts near it (its
   NWS forecast office area, LR-5's peers): the blizzard Monday after Thanksgiving week 2018
   that LR-1 names is left out for three Cass County districts this way (5 of 7 county peers,
   155 of 158 near it, had no school). **Whatever its next school day**, a day with no row is
   also left out when ``crowd_share`` or more of at least ``crowd_peers`` peers of either group
   had no school that day: with nearly every district near it closed, a day the file does not
   list is far likelier a closing it does not hold than a day with school (the storm warning day
   of February 12, 2025, when 188 of 193 districts near two KC-metro districts had none).

A day with a row is never open by the rule: its row decides it (a make-up day held on an alert
day is a day with school). A day whose building rows reach too few schools for a call (``N``)
goes through the tests as a day with no row. An advisory day right after a no-school day is the
situation ``advisory_after`` and is left out of the advisory record, as the standing file's record
leaves it out. Only the file's complete school years count.

Codes, ids, counts and dates only; nothing here is said in a public log next to a date.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from snowlight.predict.calendar import (
    good_friday,
    is_school_day,
    previous_school_day,
    season_label,
    season_of,
    thanksgiving,
    third_monday,
    veterans_day,
)
from snowlight.predict.situations import WeatherClass

type Kind = Literal["advisory", "warning", "cold"]
type Outcome = Literal["closed", "remote", "short", "open", "makeup", "some", "unknown"]
type Reason = Literal[
    "weekend",
    "not a school day",
    "not a complete year",
    "no weather row that year",
    "Thanksgiving week",
    "MLK Day",
    "Presidents' Day",
    "Good Friday or Easter Monday",
    "Veterans Day or its observed day",
    "break edge with no row that week",
    "winter break",
    "spring break",
    "Monday or Friday with few lost days",
    "four-day-week weekday",
    "isolated",
    "advisory after a no-school day",
]

KIND_OF_CLASS: Final[Mapping[WeatherClass, Kind]] = {
    WeatherClass.ADVISORY: "advisory",
    WeatherClass.TROPICAL: "warning",
    WeatherClass.COLD: "cold",
    WeatherClass.LAKE_SNOW: "warning",
    WeatherClass.SNOW_WARNING: "warning",
    WeatherClass.ICE: "warning",
    WeatherClass.BLIZZARD: "warning",
}
"""Each alert class's kind in the habit box (``exposure.CLASSES``)."""
OUTCOME_OF: Final[Mapping[str, Outcome]] = {
    "C": "closed",
    "H": "remote",
    "S": "short",
    "M": "makeup",
    "P": "some",
    "N": "open",
    "U": "unknown",
}
"""A day file's call letter to the day's outcome (``N``, no call, is a day with school)."""
LOST: Final = frozenset({"C", "H", "S", "P"})
"""Calls that are a lost school day (the four-day-week test)."""
NO_SCHOOL: Final = frozenset({"C", "H"})
MONDAY: Final = 0
TUESDAY: Final = 1
FRIDAY: Final = 4
DECEMBER: Final = 12
JANUARY: Final = 1
_ONE_DAY: Final = timedelta(days=1)


class OpenDayRule(BaseModel):
    """A state's open-day rule (``config/state-records.yaml`` ``<state>.open_days``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: Literal[3]
    """The rule's version (3: r2's rule with LR-1's break edges and isolation guard); each kept
    open day carries it, so a later edition can replace them all."""
    complete_years: tuple[str, ...] = Field(min_length=1)
    """The school years the file holds whole (``2016-17``)."""
    winter_late_from: int = Field(ge=1, le=31)
    """December days from this one need a row on a later December date."""
    winter_early_until: int = Field(ge=1, le=31)
    """January days up to this one need a row on an earlier or the same January date."""
    spring_from: tuple[int, int]
    spring_until: tuple[int, int]
    """The spring-break window (month, day), both ends included."""
    four_day_lost_days: int = Field(ge=1)
    isolation_share: float = Field(gt=0, le=1)
    isolation_peers: int = Field(ge=1)
    crowd_share: float = Field(gt=0, le=1)
    """The isolation guard's second arm: the share of peers with no school that leaves out a
    day with no row whatever the district did on its next school day."""
    crowd_peers: int = Field(ge=1)
    """The fewest peers that arm reads."""


@dataclass(frozen=True, slots=True)
class DistrictDays:
    """A state's dated district days (its derived day file)."""

    calls: Mapping[tuple[str, date], str]
    """(LEAID, day) to its call letter."""
    weather_years: frozenset[tuple[str, int]]
    """(LEAID, season) with a weather day row."""


def read_days(data: bytes) -> DistrictDays:
    """A derived day file (``leaid,date,call,scope,weather``).

    Raises:
        ValueError: a row that does not read.
    """
    calls: dict[tuple[str, date], str] = {}
    years: set[tuple[str, int]] = set()
    lines = data.decode().splitlines()
    if not lines or lines[0] != "leaid,date,call,scope,weather":
        raise ValueError("not a derived day file")
    for line in lines[1:]:
        leaid, day_text, call, _scope, weather = line.split(",")
        day = date.fromisoformat(day_text)
        if call not in OUTCOME_OF or weather not in {"0", "1"} or (leaid, day) in calls:
            raise ValueError("a day row that does not read")
        calls[leaid, day] = call
        if weather == "1":
            years.add((leaid, season_of(day)))
    return DistrictDays(calls, frozenset(years))


@dataclass(frozen=True, slots=True)
class AlertDay:
    """One kept alert school day of a district."""

    leaid: str
    day: date
    kind: Kind
    outcome: Outcome


@dataclass(slots=True)
class AlertDays:
    """What the rule kept and left out."""

    kept: list[AlertDay] = field(default_factory=list)
    left: Counter[Reason] = field(default_factory=Counter)
    isolated: list[tuple[str, date, Kind]] = field(default_factory=list)
    """The days the isolation guard left out (LEAID, day, kind), listed for the review."""


def _easter_monday(year: int) -> date:
    return good_friday(year) + timedelta(days=3)


def fixed_off(day: date) -> Reason | None:
    """The fixed day off ``day`` is, if any (test 2)."""
    feast = thanksgiving(day.year)
    if feast - timedelta(days=3) <= day <= feast + _ONE_DAY:
        return "Thanksgiving week"
    if day == third_monday(day.year, 1):
        return "MLK Day"
    if day == third_monday(day.year, 2):
        return "Presidents' Day"
    if day in {good_friday(day.year), _easter_monday(day.year)}:
        return "Good Friday or Easter Monday"
    if day in {date(day.year, 11, 11), veterans_day(day.year)}:
        return "Veterans Day or its observed day"
    return None


def break_edge(day: date) -> bool:
    """``day`` is the Monday after Thanksgiving week, or the Tuesday after Martin Luther King
    Jr. Day or after Presidents' Day (test 3)."""
    return day in {
        thanksgiving(day.year) + timedelta(days=4),
        third_monday(day.year, 1) + _ONE_DAY,
        third_monday(day.year, 2) + _ONE_DAY,
    }


def next_school_day(day: date) -> date:
    """The school day after ``day`` by the default calendar, past the rule's fixed days off
    (a Friday before Martin Luther King Jr. Day reads the Tuesday after it)."""
    after = day + _ONE_DAY
    while not is_school_day(after) or fixed_off(after) is not None:
        after += _ONE_DAY
    return after


class _Book:
    """Each district's rows, for the tests that ask about a window."""

    def __init__(self, days: DistrictDays) -> None:
        self.rows: dict[str, set[date]] = defaultdict(set)
        lost: dict[tuple[str, int], set[date]] = defaultdict(set)
        for (leaid, day), call in days.calls.items():
            if call != "N":
                self.rows[leaid].add(day)
            if call in LOST:
                lost[leaid, season_of(day)].add(day)
        self.lost = lost
        self.days = days

    def row_in(self, leaid: str, first: date, last: date) -> bool:
        return any(first <= d <= last for d in self.rows.get(leaid, ()))

    def days_off(self, leaid: str, season: int, enough: int) -> frozenset[int] | None:
        """The weekdays with no lost day all year, or ``None`` with too few lost days."""
        lost = self.lost.get((leaid, season), set())
        if len(lost) < enough:
            return None
        seen = {d.weekday() for d in lost}
        return frozenset(w for w in range(5) if w not in seen)


def _window_reason(  # noqa: PLR0911 - one reason per test, in the rule's order
    book: _Book, leaid: str, day: date, rule: OpenDayRule
) -> Reason | None:
    """The reason a day with no row is left out, by tests 2 to 6 (``None``: it counts)."""
    fixed = fixed_off(day)
    if fixed is not None:
        return fixed
    week = day - timedelta(days=day.weekday())
    friday = week + timedelta(days=FRIDAY)
    if break_edge(day) and not book.row_in(leaid, week, friday):
        return "break edge with no row that week"
    if (
        day.month == DECEMBER
        and day.day >= rule.winter_late_from
        and not book.row_in(leaid, day, date(day.year, DECEMBER, 31))
    ) or (
        day.month == JANUARY
        and day.day <= rule.winter_early_until
        and not book.row_in(leaid, date(day.year, JANUARY, 1), day)
    ):
        return "winter break"
    if rule.spring_from <= (day.month, day.day) <= rule.spring_until and not book.row_in(
        leaid, week, friday
    ):
        return "spring break"
    off = book.days_off(leaid, season_of(day), rule.four_day_lost_days)
    if off is None and day.weekday() in {MONDAY, FRIDAY}:
        return "Monday or Friday with few lost days"
    if off and day.weekday() in off:
        return "four-day-week weekday"
    return None


def _reason(  # noqa: PLR0913, PLR0917 - one day of one district and the rule
    book: _Book, leaid: str, day: date, row: str | None, rule: OpenDayRule, complete: frozenset[str]
) -> Reason | None:
    """Why a day is left out by tests 1 to 7, in order (``None``: it passes them)."""
    if season_label(season_of(day)) not in complete:
        return "not a complete year"
    if day.weekday() > FRIDAY:
        return "weekend"
    if not is_school_day(day):
        return "not a school day"
    if row is None and (leaid, season_of(day)) not in book.days.weather_years:
        return "no weather row that year"
    if row is None:
        return _window_reason(book, leaid, day, rule)
    return None


@dataclass(slots=True)
class _Day:
    """One alert school day of a district on its way through the rule."""

    leaid: str
    day: date
    kind: Kind
    row: str | None
    """Its call letter, ``None`` with no row (or an ``N`` row, too few schools for a call)."""
    reason: Reason | None
    """Why tests 1 to 7 leave it out (``None``: they pass it)."""
    after: bool
    """An advisory day right after a no-school day."""
    isolated: bool = False


type _Peers = dict[tuple[int, str, date], list[tuple[str, bool]]]


def _peer_groups(items: Sequence[_Day], groups: Sequence[Mapping[str, str]]) -> _Peers:
    """Each group's peers on each date, with whether each had no school.

    Every district of the group with an alert that date and a row is a peer, whatever its own
    record keeps (an advisory day after a no-school day included): its row decides by its call
    (closed or at home, no school; short or a make-up day, school; some or unknown, not a
    peer). A day with no row is a peer with school only while the rule counts it as one: it
    passes tests 1 to 7, is not an advisory day after a no-school day and is not isolated."""
    peers: _Peers = defaultdict(list)
    for item in items:
        if item.row is None:
            if item.reason is not None or item.after or item.isolated:
                continue
            no = False
        elif item.row in NO_SCHOOL or item.row in {"S", "M"}:
            no = item.row in NO_SCHOOL
        else:
            continue
        for g, group in enumerate(groups):
            key = group.get(item.leaid)
            if key is not None:
                peers[g, key, item.day].append((item.leaid, no))
    return peers


def alert_days(
    days: DistrictDays,
    classes: Iterable[tuple[str, date, int]],
    groups: Sequence[Mapping[str, str]],
    rule: OpenDayRule,
) -> AlertDays:
    """Each kept alert school day of the file's districts, with what the district did (see
    the module). ``classes`` holds each (LEAID, day, alert class above none) the class history
    gives for the state's districts; ``groups`` the isolation guard's peer groups, each a
    district's group key (its county, and its forecast office area as LR-5's peers): a day is
    isolated when the share is reached in any of them. The guard runs until no more days are
    left out, so an isolated day is never another district's peer with school."""
    book = _Book(days)
    complete = frozenset(rule.complete_years)
    items: list[_Day] = []
    for leaid, day, value in sorted(classes):
        kind = KIND_OF_CLASS[WeatherClass(value)]
        call = days.calls.get((leaid, day))
        row = None if call in {None, "N"} else call
        reason = _reason(book, leaid, day, row, rule, complete)
        after = kind == "advisory" and (
            days.calls.get((leaid, previous_school_day(day))) in NO_SCHOOL
        )
        items.append(_Day(leaid, day, kind, row, reason, after))
    while True:
        peers = _peer_groups(items, groups)
        newly = [
            item
            for item in items
            if item.row is None
            and item.reason is None
            and not item.isolated
            and _isolated(item, peers, days, groups, rule)
        ]
        if not newly:
            break
        for item in newly:
            item.isolated = True
    found = AlertDays()
    for item in items:
        reason = item.reason
        if reason is None and item.after:
            reason = "advisory after a no-school day"
        if reason is None and item.isolated:
            reason = "isolated"
            found.isolated.append((item.leaid, item.day, item.kind))
        if reason is not None:
            found.left[reason] += 1
            continue
        call = days.calls.get((item.leaid, item.day))
        found.kept.append(AlertDay(item.leaid, item.day, item.kind, OUTCOME_OF[call or "N"]))
    return found


def _isolated(
    item: _Day,
    peers: Mapping[tuple[int, str, date], list[tuple[str, bool]]],
    days: DistrictDays,
    groups: Sequence[Mapping[str, str]],
    rule: OpenDayRule,
) -> bool:
    after = days.calls.get((item.leaid, next_school_day(item.day))) in NO_SCHOOL
    for g, group in enumerate(groups):
        key = group.get(item.leaid)
        if key is None:
            continue
        others = [no for leaid, no in peers.get((g, key, item.day), ()) if leaid != item.leaid]
        closed = sum(others)
        if len(others) >= rule.crowd_peers and closed >= rule.crowd_share * len(others):
            return True
        if (
            after
            and len(others) >= rule.isolation_peers
            and closed >= rule.isolation_share * len(others)
        ):
            return True
    return False

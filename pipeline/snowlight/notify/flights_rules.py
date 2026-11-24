"""The Flights trip alerts (flights spec D12, D18, D20 W8): which alert is due for a saved trip,
worked from the published files exactly as the page works them (web/src/modes/flights/chance.ts,
backup.ts and data.ts waiverState), so an alert never says a number the page would not show.

Each alert is said once per change (``flights_sent``). A trip's chance alerts run in rounds: a
fall ends one, and the next round starts with nothing said (at most :data:`MAX_FALLS` falls).

* ``chance``: the trip's shown cancel or 45+ minute delay chance reaches the account's threshold
  (30, 50 or 70%), once a round; value ``<threshold>:<round>:<level>:<top>``.
* ``rise``: after a chance or rise alert this round (an evening check alone never starts one, so
  nothing under the threshold is sent that would not be sent with the evening check off), the
  level rises a step (Low risk, Some risk, High risk) above every level said, or the chance, at
  the threshold, rises :data:`RISE_POINTS` points above every chance said; value
  ``<round>:<level>:<top>``.
* ``fall``: after a chance or rise alert this round, the chance falls under the threshold and
  :data:`RISE_POINTS` points under the highest said; value ``<round>:<level>:<top>``.
* ``faa``: a live FAA ground stop, ground delay or closing at either end on the trip's day
  (today, read under 30 minutes ago, not past the end the FAA gave it), once per end time the FAA
  gives it; value ``<airport>:<program>:<end>``. Held by the push service no longer than the FAA
  read is trusted (30 minutes from the read, not from this pass) or the program's end, and its
  checked time is the read's (D7).
* ``safer``: while the trip is at some or high risk and at the threshold, the alert's top plans
  include one :data:`SAFER_POINTS` points safer than any plan said before (or none was said).
  Every alert that names plans logs them as ``<plan>:<chance>``, so an option that leaves or
  drops out of the top two never sends one.
* ``waiver``: the trip's airline posted a waiver (or one that may cover it, ``unclear``) at
  either end on the trip's day; value ``<state>:<first day>:<last day>``.
* ``night``: the evening check at the account's time the evening before (in the departure
  airport's time), sent in the 3 hours after it, or, when that time is in quiet hours, in the
  hour before they start; value ``<day>:<round>:<level>:<top>``. A chance, rise or fall alert
  sent in that window, or in the hour before it, stands for it only when it said what the evening
  check would say now (the same round, level and top chance); a safer alert never does. With no
  current live file for the whole window, it says it could not check, in the window's last 40
  minutes (value ``<day>:<round>:none:0``), never an old chance. With a current file that has no
  forecast for the trip (its block shows the usual rate, or an end is not in it), it says there
  is no forecast yet, on time (value ``<day>:<round>:usual:0``).

Plans come same airline and route first among the safer ones (D11; :func:`rank_key`, as
backup.ts ranks them), and only flights that leave at least :data:`BACKUP_LEAD` from now
(:data:`NEARBY_LEAD` from a nearby airport): time to change the ticket and get there. A chance
is said only from forecast values: a block that shows the usual rate, an old file or a day the
file does not cover gives no chance alert (D6, D7: never a made-up number, never a stale one as
current). Every alert but the FAA's waits out the account's quiet
hours (its Schools ones, in the departure airport's time); FAA holds come through, as the Schools
status alerts do.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

from snowlight.schemas.flights import FlightsAirportLive, FlightsLive, FlightsRoutes

type Level = Literal["low", "delay", "cancel"]
type Kind = Literal["chance", "rise", "fall", "faa", "safer", "waiver", "night"]
type Ticket = Literal["basic", "regular", "premium", "unsure"]

BLOCK_STARTS: Final = (300, 540, 720, 1020, 1260)
CANCEL_HIGH: Final = 15
CANCEL_SOME: Final = 5
LATE_SOME: Final = 25
LIVE_FRESH_MINUTES: Final = 60
FAA_FRESH_MINUTES: Final = 30
WAIVERS_FRESH_MINUTES: Final = 120
NIGHT_WINDOW: Final = timedelta(hours=3)
NIGHT_EARLY: Final = timedelta(hours=1)
"""When the evening check's time falls in quiet hours, it is sent in this span before they start."""
NIGHT_FOLD: Final = timedelta(hours=1)
"""A chance, rise or fall alert this long before the evening check, that said what it would say,
stands for it."""
NIGHT_LATE: Final = timedelta(minutes=40)
"""With no current live file, the evening check says so in the last part of its window."""
BACKUP_LEAD: Final = timedelta(hours=2)
"""A backup is named only when it leaves at least this long from now: the same rule as the page
(backup.ts BACKUP_LEAD) and a push or email shown late (copy-trips.ts BACKUP_LEAD_S, checked
against this one by trips-logic.test.ts)."""
NEARBY_LEAD: Final = timedelta(hours=3)
"""The same, for a backup that leaves from a nearby airport (a drive first; NEARBY_LEAD_S)."""
SAFER_POINTS: Final = 10
RISE_POINTS: Final = 20
"""A rise of this many points over the highest chance said is said again (as the Schools sender
does); a fall of as many, under the threshold, after a chance or rise alert, is said once."""
MAX_FALLS: Final = 2
"""At most this many falls (and so rounds of chance alerts) per trip."""
NEARBY_MILES: Final = 120.0
LAYOVER_MIN: Final = 60
LAYOVER_MAX: Final = 240
HUBS_TRIED: Final = 8
ALERT_BACKUPS: Final = 2
"""The safer plans an alert names (D18: the top one or two); its safer alert's log rows."""
ALERT_CARRIED: Final = 6
"""The safer plans an alert carries, best first: a push or email shown late names the top live
one or two of them, and its ``more`` says the sender found others past them, so a late one whose
carried plans have all left never says no safer flight is left when one may be."""
HOLDING: Final = frozenset({0, 1, 4})
"""Ground stop, ground delay and closed: the FAA programs that hold flights."""
LEVELS: Final[tuple[Level, ...]] = ("low", "delay", "cancel")
REGIONAL: Final = frozenset({"9E", "C5", "G7", "MQ", "OH", "OO", "PT", "QX", "YV", "YX", "ZW"})
"""Regional airlines (data.ts REGIONAL_AIRLINES): the waiver is the bigger airline's, never
guessed."""


@dataclass(frozen=True, slots=True)
class Airport:
    code: str
    tz: str
    lat: float
    lon: float
    per_day: float


@dataclass(frozen=True, slots=True)
class Trip:
    id: str
    user_id: str
    carrier: str
    number: int
    from_: str
    to: str
    day: date
    leaves: int
    lands: int
    ticket: Ticket = "unsure"
    need_by: str | None = None


@dataclass(frozen=True, slots=True)
class Choices:
    """An account's Flights alert choices (``flights_notify``; no row: these) and its quiet
    hours (``notify_settings``)."""

    alerts: bool = True
    threshold: int = 30
    night_before: bool = True
    night_time: time = time(20, 0)
    email: bool = True
    quiet_from: time = time(22, 0)
    quiet_to: time = time(5, 0)

    def quiet_at(self, local: time) -> bool:
        start, end = self.quiet_from, self.quiet_to
        if start == end:
            return False
        if start < end:
            return start <= local < end
        return local >= start or local < end


# --- the chance, as chance.ts works it ----------------------------------------------------------


def shown(per_mille: int) -> int:
    """A per mille value as the whole percent the page shows (JavaScript's Math.round)."""
    return math.floor(per_mille / 10 + 0.5)


def level_of(cancel: int, late: int) -> Level:
    """The level from the shown whole percents (chance.ts levelOf)."""
    if cancel >= CANCEL_HIGH:
        return "cancel"
    if cancel >= CANCEL_SOME or late >= LATE_SOME:
        return "delay"
    return "low"


def either(a: int, b: int) -> int:
    """At least one of two chances, per mille (chance.ts either)."""
    return math.floor(1000 - ((1000 - a) * (1000 - b)) / 1000 + 0.5)


def block_of(minute: int) -> tuple[int, bool]:
    m = minute % 1440
    if m < BLOCK_STARTS[0]:
        return 4, True
    block = 0
    for i, start in enumerate(BLOCK_STARTS):
        if m >= start:
            block = i
    return block, False


def instant(day: date, minute: int, zone: str) -> datetime:
    """The instant a local date and minute is in ``zone``."""
    return datetime.combine(day, time(minute // 60, minute % 60), ZoneInfo(zone))


def local(at: datetime, zone: str) -> tuple[date, int]:
    moment = at.astimezone(ZoneInfo(zone))
    return moment.date(), moment.hour * 60 + moment.minute


@dataclass(frozen=True, slots=True)
class EndValue:
    cancel: int | None
    late: int | None
    usual: bool


def _bit(mask: int, block: int) -> bool:
    return (mask >> block) & 1 == 1


def value_at(
    entry: FlightsAirportLive, day: date, block: int, side: Literal["dep", "arr"]
) -> EndValue:
    for index in range(3):
        if entry.today + timedelta(days=index) != day:
            continue
        canc = entry.dep_canc if side == "dep" else entry.arr_canc
        late = entry.dep_late if side == "dep" else entry.arr_late
        target = 0 if side == "dep" else 2
        c = canc[index][block]
        lv = late[index][block]
        usual = _bit(entry.usual[target][index], block) or _bit(
            entry.usual[target + 1][index], block
        )
        return EndValue(c, lv, usual)
    return EndValue(None, None, False)


@dataclass(frozen=True, slots=True)
class Leg:
    carrier: str
    number: int
    from_: str
    to: str
    day: date
    leaves: int
    lands: int
    arrives: datetime
    cancel: int
    """Shown whole percent."""
    late: int
    drive: str = ""
    """The end whose block chance drives the shown number (where its reason is read)."""
    drive_day: date | None = None
    """That end's local day of the block."""

    @property
    def level(self) -> Level:
        return level_of(self.cancel, self.late)


@dataclass(frozen=True, slots=True)
class World:
    """What the files say now: the live chances, the airports, the usual flights and the
    waivers, each with its time."""

    now: datetime
    airports: Mapping[str, Airport]
    live: FlightsLive | None
    """None: no current live file (missing, another stamp, or older than its limit)."""
    routes: Callable[[str], FlightsRoutes | None]
    waivers: Mapping[str, object] | None = None
    entries: Mapping[str, FlightsAirportLive] = field(default_factory=dict)

    @classmethod
    def of(
        cls,
        now: datetime,
        airports: Mapping[str, Airport],
        live: FlightsLive | None,
        routes: Callable[[str], FlightsRoutes | None],
        waivers: Mapping[str, object] | None = None,
    ) -> "World":
        fresh = live is not None and now - live.generated_at < timedelta(minutes=LIVE_FRESH_MINUTES)
        kept = live if fresh else None
        entries = {} if kept is None else {entry.code: entry for entry in kept.airports}
        return cls(now, airports, kept, routes, waivers, entries)


def leg_of(  # noqa: PLR0913, PLR0917 - a flight is its eight fields
    world: World, carrier: str, number: int, from_: str, to: str, day: date, leaves: int, lands: int
) -> Leg | None:
    """One flight on local ``day``, scored from forecast values only, or None."""
    a = world.airports.get(from_)
    b = world.airports.get(to)
    a_live = world.entries.get(from_)
    b_live = world.entries.get(to)
    if a is None or b is None or a_live is None or b_live is None:
        return None
    depart = instant(day, leaves, a.tz)
    if depart <= world.now:
        return None
    arrive = instant(day, lands, b.tz)
    while arrive <= depart:
        arrive += timedelta(days=1)
    while arrive - depart > timedelta(days=1):
        arrive -= timedelta(days=1)
    d_block, d_before = block_of(leaves)
    d_day = day - timedelta(days=1) if d_before else day
    a_day, a_minute = local(arrive, b.tz)
    r_block, r_before = block_of(a_minute)
    r_day = a_day - timedelta(days=1) if r_before else a_day
    dep = value_at(a_live, d_day, d_block, "dep")
    arr = value_at(b_live, r_day, r_block, "arr")
    if dep.cancel is None or arr.cancel is None or dep.late is None or arr.late is None:
        return None
    if dep.usual or arr.usual:
        return None
    cancel = shown(either(dep.cancel, arr.cancel))
    late = shown(max(dep.late, arr.late))
    at_dep = dep.late >= arr.late if late > cancel else dep.cancel >= arr.cancel
    return Leg(
        carrier,
        number,
        from_,
        to,
        day,
        leaves,
        lands,
        arrive,
        cancel,
        late,
        from_ if at_dep else to,
        d_day if at_dep else r_day,
    )


# --- backup plans, as backup.ts works them ------------------------------------------------------


type PlanKind = Literal["same", "other", "nearby", "hub"]
KIND_ORDER: Final[Mapping[str, int]] = {"same": 0, "other": 1, "nearby": 2, "hub": 3}
"""Same airline and route first (that day or the day before), then other airlines on the route,
then nearby airports, then one stop (D11: same airline first). backup.ts PLAN_ORDER."""


@dataclass(frozen=True, slots=True)
class Plan:
    legs: tuple[Leg, ...]
    chance: int
    kind: PlanKind = "same"
    miles: int | None = None
    """A nearby airport's straight-line miles from the trip's end (D18: "about N miles away")."""

    def key(self) -> str:
        return "+".join(
            f"{leg.carrier}{leg.number}-{leg.from_}-{leg.day.isoformat()}" for leg in self.legs
        )


def plan_chance(legs: Sequence[Leg]) -> int:
    fine = 1.0
    for leg in legs:
        fine *= ((100 - leg.cancel) / 100) * ((100 - leg.late) / 100)
    return min(99, max(0, math.floor(fine * 100 + 0.5)))


def miles(a: Airport, b: Airport) -> float:
    rad = math.pi / 180
    d_lat = (b.lat - a.lat) * rad
    d_lon = (b.lon - a.lon) * rad
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(a.lat * rad) * math.cos(b.lat * rad) * math.sin(d_lon / 2) ** 2
    )
    return 3958.8 * 2 * math.asin(min(1.0, math.sqrt(h)))


def nearby(airports: Mapping[str, Airport], code: str) -> list[str]:
    at = airports.get(code)
    if at is None:
        return []
    near = [(miles(at, other), other.code) for other in airports.values() if other.code != code]
    return [c for d, c in sorted(near) if d <= NEARBY_MILES]


def _flights(world: World, code: str) -> list[tuple[str, int, str, int, int, int]]:
    routes = world.routes(code)
    if routes is None or not routes.months:
        return []
    return [
        (f.carrier, f.number, f.to_airport, f.leaves, f.lands, f.weekdays)
        for f in routes.months[0].flights
    ]


def _flies(weekdays: int, day: date) -> bool:
    return (weekdays >> day.weekday()) & 1 == 1


def deadline(trip: Trip, airports: Mapping[str, Airport]) -> datetime | None:
    zone = airports.get(trip.to)
    if trip.need_by is None or zone is None:
        return None
    try:
        at = datetime.strptime(trip.need_by, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    return at.replace(tzinfo=ZoneInfo(zone.tz))


def trip_leg(world: World, trip: Trip) -> Leg | None:
    return leg_of(
        world, trip.carrier, trip.number, trip.from_, trip.to, trip.day, trip.leaves, trip.lands
    )


def backup_plans(world: World, trip: Trip) -> list[Plan]:  # noqa: PLR0912 - four kinds
    """The plans, safest first (backup.ts backupPlans), never the trip itself."""
    plans: list[Plan] = []

    def add(legs: tuple[Leg, ...], kind: PlanKind, distance: int | None = None) -> None:
        plans.append(Plan(legs, plan_chance(legs), kind, distance))

    for day in (trip.day, trip.day - timedelta(days=1)):
        for carrier, number, to, leaves, lands, weekdays in _flights(world, trip.from_):
            if to != trip.to or not _flies(weekdays, day):
                continue
            if carrier == trip.carrier and number == trip.number and day == trip.day:
                continue
            leg = leg_of(world, carrier, number, trip.from_, to, day, leaves, lands)
            if leg is not None:
                add((leg,), "same" if carrier == trip.carrier else "other")
    ends = {trip.to, *nearby(world.airports, trip.to)}
    for start in (trip.from_, *nearby(world.airports, trip.from_)):
        for carrier, number, to, leaves, lands, weekdays in _flights(world, start):
            if (
                to not in ends
                or (start == trip.from_ and to == trip.to)
                or not _flies(weekdays, trip.day)
            ):
                continue
            leg = leg_of(world, carrier, number, start, to, trip.day, leaves, lands)
            if leg is not None:
                add((leg,), "nearby", _away(world.airports, trip, start, to))
    for hub in hubs(world, trip):
        hub_airport = world.airports[hub]
        for carrier, number, to, leaves, lands, weekdays in _flights(world, trip.from_):
            if to != hub or not _flies(weekdays, trip.day):
                continue
            one = leg_of(world, carrier, number, trip.from_, hub, trip.day, leaves, lands)
            if one is None:
                continue
            for c2, n2, to2, leaves2, lands2, weekdays2 in _flights(world, hub):
                if to2 != trip.to:
                    continue
                for day in (trip.day, trip.day + timedelta(days=1)):
                    if not _flies(weekdays2, day):
                        continue
                    two = leg_of(world, c2, n2, hub, to2, day, leaves2, lands2)
                    if two is None:
                        continue
                    layover = (
                        instant(day, leaves2, hub_airport.tz) - one.arrives
                    ).total_seconds() / 60
                    if LAYOVER_MIN <= layover <= LAYOVER_MAX:
                        add((one, two), "hub")
    due = deadline(trip, world.airports)
    kept = [
        plan
        for plan in plans
        if (due is None or plan.legs[-1].arrives <= due)
        and departs(world, plan) >= lead(world, trip, plan)
    ]
    own = trip_leg(world, trip)
    kept.sort(key=rank_key(None if own is None else plan_chance((own,))))
    seen: set[str] = set()
    unique: list[Plan] = []
    for plan in kept:
        if plan.key() not in seen:
            seen.add(plan.key())
            unique.append(plan)
    return unique


def departs(world: World, plan: Plan) -> datetime:
    """When the plan's first flight leaves (every leg's airport is known: leg_of scored it)."""
    first = plan.legs[0]
    return instant(first.day, first.leaves, world.airports[first.from_].tz)


def lead(world: World, trip: Trip, plan: Plan) -> datetime:
    """The soonest a backup may leave to be named: time to change the ticket and get there."""
    near = plan.legs[0].from_ != trip.from_
    return world.now + (NEARBY_LEAD if near else BACKUP_LEAD)


def rank_key(trip_chance: int | None) -> Callable[[Plan], tuple[int, int, int, datetime, int, str]]:
    """backup.ts rankPlans: the plans at least :data:`SAFER_POINTS` safer than the trip come
    first, same airline and route first among them, then other airlines, nearby airports and one
    stop, each by chance; the rest by chance. Ties: the one that lands first, then the kind, then
    the flights."""

    def key(plan: Plan) -> tuple[int, int, int, datetime, int, str]:
        safer = trip_chance is not None and plan.chance >= trip_chance + SAFER_POINTS
        order = KIND_ORDER[plan.kind]
        return (
            0 if safer else 1,
            order if safer else 0,
            -plan.chance,
            plan.legs[-1].arrives,
            order,
            plan.key(),
        )

    return key


def _away(airports: Mapping[str, Airport], trip: Trip, start: str, to: str) -> int | None:
    """The farther of the two ends from the trip's own, in whole miles (backup.ts)."""
    far = 0.0
    for own, other in ((trip.from_, start), (trip.to, to)):
        a, b = airports.get(own), airports.get(other)
        if own != other and a is not None and b is not None:
            far = max(far, miles(a, b))
    return max(1, math.floor(far + 0.5)) if far > 0 else None


def hubs(world: World, trip: Trip) -> list[str]:
    codes = {to for _c, _n, to, _l, _d, _w in _flights(world, trip.from_)} - {trip.from_, trip.to}
    known = [world.airports[code] for code in codes if code in world.airports]
    known.sort(key=lambda a: (-a.per_day, a.code))
    return [a.code for a in known[:HUBS_TRIED]]


# --- the waiver state, as data.ts waiverState works it -------------------------------------------


type WaiverLine = tuple[Literal["waiver", "unclear"], str, str, bool] | None
"""The state, the first and last day it covers, and whether it says plainly that basic economy
is in it (its ``basic_economy`` field; anything else is not)."""


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo is not None else None


def waiver_line(  # noqa: PLR0912 - every field of W3 read on its own
    world: World, carrier: str, airport: str, day: date
) -> WaiverLine:
    """A waiver found, or one that does not plainly say it covers this, on the airline's own page
    read under 2 hours ago; None for none found or not checked (never a guess, W2, LR-W1)."""
    read = world.waivers
    fresh = timedelta(minutes=WAIVERS_FRESH_MINUTES)
    if read is None or carrier in REGIONAL or read.get("schema_version") != 1:
        return None
    made = _instant(read.get("generated_at"))
    if made is None or world.now - made >= fresh:
        return None
    airlines = read.get("airlines")
    status = (
        next(
            (row for row in airlines if isinstance(row, dict) and row.get("code") == carrier),
            None,
        )
        if isinstance(airlines, list)
        else None
    )
    checked = None if status is None else _instant(status.get("read_at"))
    if (
        status is None
        or status.get("state") != "checked"
        or checked is None
        or world.now - checked >= fresh
    ):
        return None
    waivers = read.get("waivers")
    found: WaiverLine = None
    unclear: WaiverLine = None
    for row in waivers if isinstance(waivers, list) else []:
        if not isinstance(row, dict) or row.get("airline") != carrier:
            continue
        if row.get("on_page") is False or row.get("active") is False:
            continue
        airports = row.get("airports")
        where = (
            True
            if row.get("all_airports") is True
            else (None if not isinstance(airports, list) else airport in airports)
        )
        first, last = row.get("travel_from"), row.get("travel_to")
        unclear_days = row.get("unclear_days")
        if isinstance(unclear_days, list) and day.isoformat() in unclear_days:
            when: bool | None = None
        elif not isinstance(first, str) or not isinstance(last, str):
            when = None
        else:
            when = first <= day.isoformat() <= last
        if where is False or when is False:
            continue
        first_day, last_day = str(first), str(last)
        basic = row.get("basic_economy") is True
        if where is True and when is True:
            seen = _instant(row.get("last_seen"))
            if seen is not None and world.now - seen < fresh:
                found = ("waiver", first_day, last_day, basic)
        elif unclear is None:
            unclear = ("unclear", first_day, last_day, basic)
    return found or unclear


# --- the alerts ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Alert:
    """One alert for one trip: what the log records once sent, and its facts (the payload
    web/src/modes/flights/alert.ts reads)."""

    trip: Trip
    kind: Kind
    value: str
    facts: Mapping[str, object]
    ttl: int
    also: tuple[tuple[Kind, str], ...] = ()
    """Other log rows this alert stands for (the plans it names, an evening check it covers)."""


type Sent = Mapping[tuple[str, str], frozenset[str]]
"""The log: per (trip id, kind), the values said."""


@dataclass(frozen=True, slots=True)
class Told:
    """A trip's last chance, rise, fall or safer alert: when it went out, its kind and value."""

    at: datetime
    kind: str
    value: str

    def state(self) -> str | None:
        """The ``<round>:<level>:<top>`` it said, as the evening check would say it now (a fall
        ends its round, so the next round's state), or None (a safer alert says no state)."""
        if self.kind == "chance":
            parts = self.value.split(":")[1:]
        elif self.kind in {"rise", "fall"}:
            parts = self.value.split(":")
        else:
            return None
        if len(parts) != 3 or (number := _whole(parts[0])) is None:  # noqa: PLR2004
            return None
        if self.kind == "fall":
            number += 1
        return f"{number}:{parts[1]}:{parts[2]}"


@dataclass(frozen=True, slots=True)
class Said:
    """What the log says was said for a trip in its current round (a round ends with a fall)."""

    round: int
    level: int | None
    """The highest level a chance, rise or evening alert said this round."""
    top: int | None
    """The highest shown chance (cancel or 45+ minute delay) said this round."""
    warned: bool
    """A chance or rise alert went out this round (a fall can follow it)."""
    best_plan: int | None
    """The best backup chance any alert named."""


def _whole(word: str) -> int | None:
    return int(word) if word.isdigit() else None


def said_of(sent: Sent, trip: Trip) -> Said:
    """The log read back: values are ``<threshold>:<round>:<level>:<top>`` (chance),
    ``<round>:<level>:<top>`` (rise, fall), ``<day>:<round>:<level>:<top>`` (night) and
    ``<plan>:<chance>`` (safer)."""
    falls = sent.get((trip.id, "fall"), frozenset())
    now = len(falls)
    levels: list[int] = []
    tops: list[int] = []
    warned = False
    for kind, skip in (("chance", 1), ("rise", 0), ("night", 1)):
        for value in sent.get((trip.id, kind), frozenset()):
            parts = value.split(":")[skip:]
            if len(parts) != 3 or _whole(parts[0]) != now or parts[1] not in LEVELS:  # noqa: PLR2004
                continue
            levels.append(LEVELS.index(parts[1]))
            top = _whole(parts[2])
            if top is not None:
                tops.append(top)
            warned = warned or kind != "night"
    plans = [
        chance
        for value in sent.get((trip.id, "safer"), frozenset())
        if (chance := _whole(value.rsplit(":", 1)[-1])) is not None
    ]
    return Said(
        now,
        max(levels) if levels else None,
        max(tops) if tops else None,
        warned,
        max(plans) if plans else None,
    )


def _local_minute(at: datetime, zone: str) -> tuple[str, int]:
    day, minute = local(at, zone)
    return day.isoformat(), minute


def _facts(  # noqa: PLR0913, PLR0917 - the payload's parts
    world: World,
    trip: Trip,
    kind: Kind,
    leg: Leg | None,
    plans: Sequence[Plan],
    why: tuple[int, str] | None,
    faa: tuple[str, int, datetime | None] | None = None,
    waiver: tuple[str, WaiverLine] | None = None,
    read_at: datetime | None = None,
    *,
    forecast: bool = False,
) -> dict[str, object]:
    """``read_at``: when what the alert says was read, when it is older than this pass (the FAA
    status): its ``at`` and checked time, so a late push measures the read's age. ``forecast``:
    for an evening check with no chance, whether the forecast was read (it has none for the trip)
    rather than missing."""
    zone = world.airports[trip.from_].tz
    seen = world.now if read_at is None else read_at
    checked_day, checked_minute = _local_minute(seen, zone)
    faa_until = None
    if faa is not None and faa[2] is not None and faa[0] in world.airports:
        faa_until = _local_minute(faa[2], world.airports[faa[0]].tz)[1]
    line = None if waiver is None else waiver[1]
    return {
        "v": 1,
        "kind": "flight",
        "alert": kind,
        "trip": trip.id,
        "carrier": trip.carrier,
        "number": trip.number,
        "from": trip.from_,
        "to": trip.to,
        "day": trip.day.isoformat(),
        "leaves": trip.leaves,
        "cancel": None if leg is None else leg.cancel,
        "late": None if leg is None else leg.late,
        "level": None if leg is None else leg.level,
        "why": None if why is None else why[0],
        "why_at": None if why is None else why[1],
        "at": int(seen.timestamp()),
        "checked": {"day": checked_day, "minute": checked_minute},
        "faa": None if faa is None else {"airport": faa[0], "program": faa[1], "until": faa_until},
        "waiver": None
        if waiver is None or line is None
        else {"state": line[0], "basic": line[3], "airport": waiver[0]},
        "backups": [
            {
                "carrier": plan.legs[0].carrier,
                "number": plan.legs[0].number,
                "from": plan.legs[0].from_,
                "to": plan.legs[-1].to,
                "day": plan.legs[0].day.isoformat(),
                "leaves": plan.legs[0].leaves,
                "departs": int(departs(world, plan).timestamp()),
                "chance": plan.chance,
                "kind": plan.kind,
                "miles": plan.miles,
                "via": None
                if len(plan.legs) == 1
                else {
                    "carrier": plan.legs[1].carrier,
                    "number": plan.legs[1].number,
                    "hub": plan.legs[0].to,
                },
            }
            for plan in plans[:ALERT_CARRIED]
        ],
        "more": len(plans) > ALERT_CARRIED,
        "ticket": trip.ticket,
        **({"no_forecast": True} if forecast and leg is None else {}),
    }


def _why(world: World, leg: Leg) -> tuple[int, str] | None:
    """The forecast's reason at the end whose block chance drives the trip's number, and where."""
    entry = world.entries.get(leg.drive)
    if entry is None or leg.drive_day is None:
        return None
    index = (leg.drive_day - entry.today).days
    whys = entry.why[index] if 0 <= index < len(entry.why) else ()
    return (int(whys[0]), leg.drive) if whys else None


def _holds(world: World, trip: Trip) -> list[tuple[str, int, datetime | None]]:
    """Live FAA holds at either end, for a trip today at its airport (D7: under 30 minutes)."""
    live = world.live
    if live is None or live.programs_at is None:
        return []
    if world.now - live.programs_at >= timedelta(minutes=FAA_FRESH_MINUTES):
        return []
    zone = world.airports.get(trip.from_)
    if zone is None or local(world.now, zone.tz)[0] != trip.day:
        return []
    found: list[tuple[str, int, datetime | None]] = []
    for code in (trip.from_, trip.to):
        entry = world.entries.get(code)
        for program in (entry.programs or ()) if entry is not None else ():
            if int(program.program) not in HOLDING:
                continue
            if program.until is not None and program.until <= world.now:
                continue
            found.append((code, int(program.program), program.until))
    return found


def _seconds(span: timedelta) -> int:
    return max(60, int(span.total_seconds()))


def faa_read(world: World) -> datetime:
    """When the FAA status was read (the live file's ``programs_at``)."""
    read = None if world.live is None else world.live.programs_at
    return world.now if read is None else read


def faa_ttl(world: World, until: datetime | None, depart: datetime) -> int:
    """How long the push service may hold an FAA alert: never past the FAA read's freshness (30
    minutes from the read itself), the program's own end, or the flight (D7: never a stale hold
    shown as current)."""
    ends = [faa_read(world) + timedelta(minutes=FAA_FRESH_MINUTES), depart]
    if until is not None:
        ends.append(until)
    return _seconds(min(ends) - world.now)


def night_window(trip: Trip, choices: Choices, zone: str) -> tuple[datetime, datetime]:
    """When the evening check may go out: 3 hours from the account's time the evening before (up to
    quiet hours, when they start sooner), or, when that time is in quiet hours, the hour before
    they start (it is never lost to them)."""
    tz = ZoneInfo(zone)
    eve = trip.day - timedelta(days=1)
    start = datetime.combine(eve, choices.night_time, tz)
    quiet = datetime.combine(eve, choices.quiet_from, tz)
    if not choices.quiet_at(choices.night_time):
        end = start + NIGHT_WINDOW
        if choices.quiet_from != choices.quiet_to:
            # Quiet hours that start inside the window end it (its last part is before them).
            for begins in (quiet, quiet + timedelta(days=1)):
                if start < begins < end:
                    end = begins
        return start, end
    if quiet > start:
        quiet -= timedelta(days=1)
    return quiet - NIGHT_EARLY, quiet


def alerts_for(  # noqa: PLR0912, PLR0915 - one rule a kind
    world: World, trip: Trip, choices: Choices, sent: Sent, told: Told | None = None
) -> list[Alert]:
    """The alerts due for one trip now, at most one of each kind (see the module's rules).
    ``told``: the trip's last chance, rise, fall or safer alert (None: never)."""
    if not choices.alerts:
        return []
    zone = world.airports.get(trip.from_)
    if zone is None:
        return []
    depart = instant(trip.day, trip.leaves, zone.tz)
    if depart <= world.now:
        return []

    def said(kind: Kind, value: str) -> bool:
        return value in sent.get((trip.id, kind), frozenset())

    local_now = world.now.astimezone(ZoneInfo(zone.tz))
    quiet = choices.quiet_at(local_now.time())
    leg = trip_leg(world, trip)
    plans = (
        []
        if leg is None
        else [
            p for p in backup_plans(world, trip) if p.chance >= plan_chance((leg,)) + SAFER_POINTS
        ]
    )
    named = plans[:ALERT_BACKUPS]
    plan_rows: tuple[tuple[Kind, str], ...] = tuple(
        ("safer", f"{plan.key()}:{plan.chance}") for plan in named
    )
    out: list[Alert] = []
    ttl_chance = 45 * 60
    # FAA holds come through quiet hours, as the Schools status alerts do; each program said once
    # per end time the FAA gives it (a new stop or a longer one is a new change).
    for airport, program, until in _holds(world, trip):
        value = f"{airport}:{program}:{'open' if until is None else until.strftime('%Y%m%dT%H%MZ')}"
        if not said("faa", value):
            out.append(
                Alert(
                    trip,
                    "faa",
                    value,
                    _facts(
                        world,
                        trip,
                        "faa",
                        leg,
                        plans,
                        None,
                        (airport, program, until),
                        read_at=faa_read(world),
                    ),
                    faa_ttl(world, until, depart),
                )
            )
    if quiet:
        return out
    ttl_waiver = _seconds(min(depart - world.now, timedelta(minutes=WAIVERS_FRESH_MINUTES)))
    for code in (trip.from_, trip.to):
        line = waiver_line(world, trip.carrier, code, trip.day)
        if line is None:
            continue
        value = f"{line[0]}:{line[1]}:{line[2]}"
        if not said("waiver", value) and not any(a.kind == "waiver" for a in out):
            out.append(
                Alert(
                    trip,
                    "waiver",
                    value,
                    _facts(world, trip, "waiver", leg, [], None, waiver=(code, line)),
                    ttl_waiver,
                )
            )
    past = said_of(sent, trip)
    night_from, night_to = night_window(trip, choices, zone.tz)
    night_due = (
        choices.night_before
        and night_from <= world.now < night_to
        and not any(
            v.startswith(f"{trip.day.isoformat()}:")
            for v in sent.get((trip.id, "night"), frozenset())
        )
    )
    if leg is None:
        # Never an old chance: with no current file, say it could not check (late in the window,
        # in case the file comes back); with a current one that has no forecast for this trip,
        # say there is none yet.
        if night_due and (world.live is not None or world.now >= night_to - NIGHT_LATE):
            word = "none" if world.live is None else "usual"
            out.append(
                Alert(
                    trip,
                    "night",
                    f"{trip.day.isoformat()}:{past.round}:{word}:0",
                    _facts(world, trip, "night", None, [], None, forecast=world.live is not None),
                    ttl_chance,
                )
            )
        return out
    why = _why(world, leg)
    level = leg.level
    rank = LEVELS.index(level)
    top = max(leg.cancel, leg.late)
    state = f"{past.round}:{level}:{top}"
    # One alert per change: a chance, rise or fall alert just before the evening check stands for
    # it only when it said the same state; any change since gets the evening check.
    if (
        night_due
        and told is not None
        and told.at >= night_from - NIGHT_FOLD
        and told.state() == state
    ):
        night_due = False
    crossed = any(
        v.startswith(f"{choices.threshold}:{past.round}:")
        for v in sent.get((trip.id, "chance"), frozenset())
    )
    # A rise follows a chance or rise alert only: after an evening check alone, nothing under the
    # threshold goes out that would not with the evening check off.
    risen = (
        past.warned
        and past.level is not None
        and (
            rank > past.level
            or (top >= choices.threshold and past.top is not None and top >= past.top + RISE_POINTS)
        )
    )
    fallen = (
        past.warned
        and past.round < MAX_FALLS
        and top < choices.threshold
        and past.top is not None
        and top <= past.top - RISE_POINTS
    )
    if top >= choices.threshold and not crossed:
        kind: Kind | None = "chance"
        value = f"{choices.threshold}:{state}"
    elif risen:
        kind, value = "rise", state
    elif fallen:
        kind, value = "fall", state
    else:
        kind, value = None, ""
    if kind is not None:
        shown_plans = [] if kind == "fall" else plans
        rows = () if kind == "fall" else plan_rows
        out.append(
            Alert(
                trip,
                kind,
                value,
                _facts(world, trip, kind, leg, shown_plans, None if kind == "fall" else why),
                ttl_chance,
                rows,
            )
        )
    elif (
        level != "low"
        and top >= choices.threshold
        and named
        and (
            past.best_plan is None
            or max(plan.chance for plan in named) >= past.best_plan + SAFER_POINTS
        )
    ):
        out.append(
            Alert(
                trip,
                "safer",
                plan_rows[0][1],
                _facts(world, trip, "safer", leg, plans, why),
                ttl_chance,
                plan_rows[1:],
            )
        )
    if night_due:
        night_value = f"{trip.day.isoformat()}:{state}"
        now_told = next(
            (i for i, a in enumerate(out) if a.kind in {"chance", "rise", "fall", "safer"}),
            None,
        )
        if now_told is not None:
            # One alert per change: the chance said this pass stands for the evening check.
            first = out[now_told]
            out[now_told] = Alert(
                first.trip,
                first.kind,
                first.value,
                first.facts,
                first.ttl,
                (*first.also, ("night", night_value)),
            )
        else:
            out.append(
                Alert(
                    trip,
                    "night",
                    night_value,
                    _facts(world, trip, "night", leg, plans, why),
                    ttl_chance,
                    plan_rows,
                )
            )
    return out


def utc(at: datetime) -> datetime:
    return at.astimezone(UTC)

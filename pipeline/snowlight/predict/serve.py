"""One serving pass: every deployed district's chance of no school today and tomorrow.

The pass reads the deployed directory (its ``meta.json`` and ``points.bin``, checked
against its ``edition.json``), the committed model (:mod:`snowlight.predict.artifact`),
the live alerts (:mod:`snowlight.predict.alerts_live`) and, where published, the day
before's closings (the day after a closing), and writes a
:class:`~snowlight.schemas.predictions.PredictionsFile`:

* ``days``: today in ``forecast_zone`` (Los Angeles) and the day after: every contiguous
  district's today is one of them;
* per district and day: ``no_threat`` on a day that is not a school day (contract C1);
  otherwise a ``forecast``: the weather class of its eligible schools at this moment
  (alerts issued so far), its situation, the pooled chance (``p_no_school`` at least
  the floor, every school day), the why (the base alone, piece 1), its record under an
  own base, its neighbors, its time zone, and ``previous`` from the last published
  file when the whole percent moved (kept from that file while it holds).

A file over the size budget is made again with less (:class:`Fit`): first without the record
days under each own base, then also without previous chances. Every chance and every why
stays the same in each; only a file over the budget even without both is dark.

Nothing here touches the network: the caller hands every input in.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from typing import Final, cast

import numpy as np
import numpy.typing as npt

from snowlight.directory.points import NO_DISTRICT, Points
from snowlight.predict.alerts_live import LiveEvent, UgcIndex
from snowlight.predict.artifact import (
    SITUATION_KEYS,
    DistrictModel,
    Learned,
    ModelArtifact,
    RecordDay,
)
from snowlight.predict.calendar import forecast_days, is_school_day, previous_school_day
from snowlight.predict.config import PredictConfig
from snowlight.predict.geography import REGION_OF, districts_near, neighbors, state_of_leaid
from snowlight.predict.labels import NO_SCHOOL, WEATHER_REASONS
from snowlight.predict.opens import NOTHING_SAID, SaidOpen
from snowlight.predict.pool import (
    SCOPES,
    Chain,
    Floats,
    Level,
    LevelCounts,
    Places,
    Rules,
    Scope,
    Strengths,
    chain,
    delay_rules,
    level_counts,
    level_days,
    make_places,
    named_counts,
    propensities,
    publish_rates,
)
from snowlight.predict.share import points_of, says_true
from snowlight.predict.situations import (
    SITUATIONS,
    Group,
    Situation,
    WeatherClass,
    Window,
    counts,
    district_class,
)
from snowlight.predict.why import WEATHER_NAME, Of, reasons_for, record_for, sayable, why_for
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import DayTimeline
from snowlight.schemas.predictions import (
    MAX_OUTLOOKS,
    MAX_SCHOOL_NEIGHBORS,
    MAX_ZONES,
    DistrictForecast,
    Forecast,
    NoThreat,
    PredictionsFile,
    PreviousChance,
    SchoolForecast,
)

SCHEMA_VERSION: Final = 1
PRIVATE: Final = 0x01
CHARTER: Final = 0x02
VIRTUAL: Final = 0x04
_E6: Final = 1e-6
FLOOR: Final = 0.01
"""The chance of no school a unit that said school is on is given: the contract's floor."""
CONTIGUOUS: Final = (-125.0, 24.3, -66.8, 49.5)
"""The contiguous states' box (west, south, east, north), for a school with no known state."""
SITUATION_POSITION: Final = {item.key: i for i, item in enumerate(SITUATIONS)}


class ServeError(RuntimeError):
    """A pass cannot give a true file (the caller publishes nothing: fail dark)."""


class TableError(ServeError):
    """The private schools name more distinct outlooks or time zones than the file's shared
    tables may hold: raised before any school's entry is made, so the pass steps down the
    :class:`Fit` ladder (:func:`snowlight.predict.cli.fitted`) rather than go dark."""


class Fit(Enum):
    """What a pass's file holds, from the whole file to the least it publishes rather than
    go dark, in the order tried: a file over the size budget, or whose private schools name
    more outlooks than the file may hold (:class:`TableError`), is made with the next one.

    Each keeps every chance and every why it holds (its base sentence counts its own days, so
    it stays true without the record days listed): the size budget can never darken a storm's
    chances while the file with no record days and no previous chances fits
    (:attr:`NO_PREVIOUS`: ``tests/predict/test_loop.py`` asserts that it does in the worst
    case, every district with an own base and the table full),
    and the private schools can never darken the districts' (the last two leave them out)."""

    WHOLE = "whole"
    NO_RECORDS = "no_records"
    """No record days under any own base (a learned file may give every district one)."""
    NO_PRIVATE_PREVIOUS = "no_private_previous"
    """No record days, and no previous chances for private schools: a previous chance makes
    each (chance, previous) pair an outlook of its own, which can overflow the shared table
    (``tests/predict/test_private.py`` bounds the outlooks without one)."""
    NO_PREVIOUS = "no_previous"
    """No record days and no previous chances either."""
    NO_SCHOOLS = "no_schools"
    """The districts only, as the whole file holds them (the file before private schools)."""
    NO_SCHOOLS_NO_RECORDS = "no_schools_no_records"
    """The districts only, with no record days."""

    @property
    def records(self) -> bool:
        """Whether its forecasts carry the record days under an own base."""
        return self in {Fit.WHOLE, Fit.NO_SCHOOLS}

    @property
    def previous(self) -> bool:
        """Whether its districts' forecasts carry the previous chance."""
        return self is not Fit.NO_PREVIOUS

    @property
    def private_previous(self) -> bool:
        """Whether its private schools' forecasts carry the previous chance."""
        return self in {Fit.WHOLE, Fit.NO_RECORDS}

    @property
    def schools(self) -> bool:
        """Whether it holds the private schools."""
        return self not in {Fit.NO_SCHOOLS, Fit.NO_SCHOOLS_NO_RECORDS}

    @property
    def left_out(self) -> str:
        """What it leaves out, as the pass's warning says it."""
        return {
            Fit.WHOLE: "nothing",
            Fit.NO_RECORDS: "record days",
            Fit.NO_PRIVATE_PREVIOUS: "record days or private schools' previous chances",
            Fit.NO_PREVIOUS: "record days or previous chances",
            Fit.NO_SCHOOLS: "private schools",
            Fit.NO_SCHOOLS_NO_RECORDS: "private schools or record days",
        }[self]


@dataclass(frozen=True, slots=True)
class DeployedDirectory:
    """The deployed directory: its stamp, district ids and every school's point."""

    stamp: DirectoryStamp
    district_ids: tuple[str, ...]
    points: Points
    content_sha256: str | None = None
    """The deployed edition's content digest (two contents can share one stamp); ``None``
    when the folder named none (a local dry run)."""
    school_ids: tuple[str, ...] | None = None
    """Every school's NCES id, in points order (``meta.json`` ids); ``None`` when not read
    (then no private school is known to the model: each takes the rates around it)."""

    def __post_init__(self) -> None:
        if len(self.district_ids) != self.stamp.districts or len(self.points) != self.stamp.schools:
            raise ServeError("the directory's ids and points disagree with its stamp")
        if self.school_ids is not None and len(self.school_ids) != self.stamp.schools:
            raise ServeError("the directory's school ids disagree with its stamp")
        if self.points.district_count != len(self.district_ids):
            raise ServeError("points.bin counts other districts than meta.json")


@dataclass(slots=True)
class PrivateServe:
    """The private schools a pass gives a chance (contract C3): every private school of the
    contiguous states, each its own unit, with its rates per situation.

    A situation the private schools hold enough recorded days of itself (the private chain's
    own nation minimum) is counted over private schools only (``of`` private schools: the
    school's own record, private schools nearby, in its county, state, region or the
    nation). One they hold too few of is counted over the districts around the school where
    the districts hold enough days of that situation itself, as a district with no record
    of its own would be (``of`` districts); only where neither does, it takes the private
    chain's fallback when that can be said truly, else the districts'. So every private
    school has a chance every school day, counted over the day's own weather wherever any
    chain holds it, and its sentence is true of the days it counts (:func:`_private_model`)."""

    positions: npt.NDArray[np.int64]
    """Directory positions, sorted."""
    time_zone: tuple[str, ...]
    neighbors: tuple[tuple[int, ...], ...]
    """The districts next door as published (nearest first, at most MAX_SCHOOL_NEIGHBORS)."""
    p: npt.NDArray[np.float64]
    q: npt.NDArray[np.float64]
    own: npt.NDArray[np.bool_]
    scope: npt.NDArray[np.int64]
    of_private: tuple[bool, ...]
    """Per situation, whether it is counted over private schools (else over districts)."""
    effective: tuple[int, ...]
    """Per situation, the situation whose rates and sentence it publishes."""
    live: tuple[bool, ...]
    """Per situation, whether its days are days the live pipeline read (districts' only)."""
    records: tuple[Mapping[str, tuple[RecordDay, ...]], ...]
    named_y: npt.NDArray[np.float64]
    named_n: npt.NDArray[np.float64]
    known: int
    whole: npt.NDArray[np.bool_] = field(default_factory=lambda: np.zeros((0, 0), dtype=np.bool_))
    """Per school and situation, whether the days its base counts are all the place's days of
    their weather (:func:`whole_weather`); empty: none is, and no base names its weather."""
    """Private schools the model knows by id."""
    left_out: int = 0
    """Private schools of the contiguous states left out (no time zone): the pass says how
    many (:func:`snowlight.predict.cli.one_pass`), as a left-out school gets no chance."""

    def __len__(self) -> int:
        return int(self.positions.size)


@dataclass(slots=True)
class ServeModel:
    """The rates of every deployed district per situation, and its place and schools: built
    once per directory and model, used by every pass."""

    directory: DeployedDirectory
    artifact: ModelArtifact
    time_zone: tuple[str, ...]
    """IANA zone per deployed district (index order)."""
    neighbors: tuple[tuple[int, ...], ...]
    """Neighbor indexes per deployed district."""
    eligible: tuple[npt.NDArray[np.int64], ...]
    """School positions whose class decides each district's (its eligible schools, or all of
    its schools when it has none)."""
    p: npt.NDArray[np.float64]
    """Published chance of no school, (deployed districts, situations)."""
    q: npt.NDArray[np.float64]
    """Published delay chance, (deployed districts, situations)."""
    own: npt.NDArray[np.bool_]
    scope: npt.NDArray[np.int64]
    effective: tuple[int, ...]
    """Per situation, the situation whose rates and sentence it publishes (its own, or its
    fallback's when the nation has too few labeled days of it)."""
    known: int
    """Deployed districts the model knows."""
    records: tuple[Mapping[str, tuple[RecordDay, ...]], ...] = field(default=())
    named_y: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros((0, 0)))
    named_n: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros((0, 0)))
    """The recorded days (``named_y`` closed or remote of ``named_n``) of the place each
    cell's base names, (deployed districts, situations): its sentence is true of them."""
    anchored: tuple[bool, ...] = ()
    """Per situation, whether it is counted over the days the live pipeline read
    (:class:`~snowlight.predict.artifact.Learned`); empty: none is."""
    private: PrivateServe | None = None
    """The private schools' rates (contract C3); ``None``: the pass gives them none."""
    whole: npt.NDArray[np.bool_] = field(default_factory=lambda: np.zeros((0, 0), dtype=np.bool_))
    """Per deployed district and situation, whether the days its base counts are all the
    place's days of their weather (:func:`whole_weather`); empty: none is."""

    @property
    def coverage(self) -> float:
        """The share of deployed districts the model knows."""
        total = len(self.directory.district_ids)
        return self.known / total if total else 0.0


def _strengths(artifact: ModelArtifact, outcome: str) -> Strengths:
    return Strengths(cast("dict[Level, dict[Group, float]]", artifact.strengths[outcome]))


def _live_counts(places: Places, learned: Learned) -> tuple[Floats, Floats]:
    """The live-read days ``y`` of ``n`` per district and situation (zero where none)."""
    shape = (places.size, len(SITUATION_KEYS))
    y, n = np.zeros(shape), np.zeros(shape)
    for i, leaid in enumerate(places.districts):
        found = learned.live.get(leaid)
        if found is not None:
            y[i], n[i] = found.y, found.n
    return y, n


def _anchored_counts(
    places: Places, learned: Learned, archive: tuple[Floats, Floats, Floats, Floats]
) -> tuple[npt.NDArray[np.bool_], tuple[Floats, Floats, Floats, Floats]]:
    """The anchored situations, and the counts the chain runs on: the live days' in an
    anchored situation's column, the archive's in every other."""
    anchored = np.zeros(len(SITUATION_KEYS), dtype=np.bool_)
    for key in learned.anchored:
        anchored[SITUATION_POSITION[key]] = True
    live = tuple(np.zeros(archive[0].shape) for _ in range(4))
    for i, leaid in enumerate(places.districts):
        found = learned.live.get(leaid)
        if found is not None:
            live[0][i], live[1][i], live[2][i], live[3][i] = found.y, found.n, found.yd, found.nd
    mixed = tuple(
        np.where(anchored[None, :], mine, theirs)
        for mine, theirs in zip(live, archive, strict=True)
    )
    return anchored, (mixed[0], mixed[1], mixed[2], mixed[3])


def _ratios(
    archive: LevelCounts, strengths: Strengths, rules: Rules, anchored: npt.NDArray[np.bool_]
) -> dict[str, Floats]:
    """The archive's relative propensities in the anchored columns; 1 (none) elsewhere."""
    found: Chain = chain(archive, strengths, rules=rules)
    return {
        level: np.where(anchored[None, :], ratio, 1.0)
        for level, ratio in propensities(found).items()
    }


@dataclass(frozen=True, slots=True)
class _Served:
    """The private schools a pass serves, before their rates: positions, ids, places, zones."""

    positions: npt.NDArray[np.int64]
    ids: tuple[str | None, ...]
    state: tuple[str | None, ...]
    county: tuple[str | None, ...]
    zones: tuple[str, ...]
    left_out: int

    def unit(self, i: int) -> str:
        """The school's unit in the chains: its id, or its position when the model has none."""
        found = self.ids[i]
        return found if found is not None else f"~{int(self.positions[i]):07d}"


def _contiguous(lon: float, lat: float) -> bool:
    """Whether a point lies in the contiguous states' box (for a school with no known state)."""
    return CONTIGUOUS[0] <= lon <= CONTIGUOUS[2] and CONTIGUOUS[1] <= lat <= CONTIGUOUS[3]


def _private_served(
    directory: DeployedDirectory,
    artifact: ModelArtifact,
    lon: npt.NDArray[np.float64],
    lat: npt.NDArray[np.float64],
    zone_fallback: Callable[[float, float], str | None],
) -> _Served:
    """Every private school (no district, the private flag) of the contiguous states, with
    its place from the model (by id) or, for one the model does not know, its zone from its
    point and no state (its chains then name only what its point shows)."""
    points = directory.points
    private = np.flatnonzero((points.district == NO_DISTRICT) & ((points.kind & PRIVATE) != 0))
    ids = directory.school_ids
    positions: list[int] = []
    found_ids: list[str | None] = []
    states: list[str | None] = []
    counties: list[str | None] = []
    zones: list[str] = []
    left_out = 0
    for position in private.tolist():
        school = ids[position] if ids is not None else None
        entry = artifact.private.get(school) if school is not None else None
        state = entry.state if entry is not None else None
        x, y = float(lon[position]), float(lat[position])
        if state is not None and state not in REGION_OF:
            continue
        if state is None and not _contiguous(x, y):
            continue
        zone = entry.time_zone if entry is not None and entry.time_zone else zone_fallback(x, y)
        if zone is None:
            left_out += 1
            continue
        positions.append(position)
        found_ids.append(school if entry is not None else None)
        states.append(state)
        counties.append(entry.county if entry is not None else None)
        zones.append(zone)
    return _Served(
        np.array(positions, dtype=np.int64),
        tuple(found_ids),
        tuple(states),
        tuple(counties),
        tuple(zones),
        left_out,
    )


@dataclass(frozen=True, slots=True)
class _Rates:
    """One chain's published rates for a set of units, per situation."""

    p: npt.NDArray[np.float64]
    q: npt.NDArray[np.float64]
    own: npt.NDArray[np.bool_]
    scope: npt.NDArray[np.int64]
    effective: tuple[int, ...]
    """Per situation, the situation it publishes, or -1 when none is backed."""
    named_y: npt.NDArray[np.float64]
    named_n: npt.NDArray[np.float64]
    whole: npt.NDArray[np.bool_]
    """Per unit and situation, whether the base may name its weather (:func:`whole_weather`)."""


def whole_weather(
    found: Chain,
    archive: LevelCounts,
    live: LevelCounts | None,
    anchored: npt.NDArray[np.bool_],
) -> npt.NDArray[np.bool_]:
    """Per cell of a chain, whether the days its base counts are all the place's days of
    their weather, so the sentence may name it ("recorded winter advisory days", addendum e,
    E2): the level the base names holds no day of another situation of the same weather
    (the advisory days after a snow day beside the other advisory days), in the same source
    as the counted days (``live`` when the counted situation is ``anchored``, else the
    ``archive``). A cell counted over a situation with no weather name, or over the days
    after a snow day, is ``False`` (it says "days like this")."""
    target = np.maximum(found.situation, 0)
    whole = np.zeros(target.shape, dtype=np.bool_)
    for t, counted in enumerate(SITUATIONS):
        if counted.after or counted.weather not in WEATHER_NAME:
            continue
        source = live if live is not None and bool(anchored[t]) else archive
        others = np.zeros(target.shape)
        for j, other in enumerate(SITUATIONS):
            if j != t and other.weather == counted.weather:
                others += level_days(source, found, j)
        whole |= (target == t) & (others == 0)
    return whole


def _check_true(rates: _Rates, rules: Rules) -> None:
    """Every served base sentence is true of the recorded days of the place it names."""
    if rules.almost_share is None or not rates.p.size:
        return
    true = says_true(points_of(rates.p), rates.named_y, rates.named_n, rules.almost_share)
    if not true.all():
        raise ServeError(
            f"{int((~true).sum())} served base sentences are not true of the recorded "
            "days of the place they name"
        )


def _private_chain(
    artifact: ModelArtifact,
    served: _Served,
    lon: npt.NDArray[np.float64],
    lat: npt.NDArray[np.float64],
    miles: float,
) -> _Rates | None:
    """The private schools' chain over private schools only, for the served schools (in
    their order), or ``None`` when the model holds no private counts."""
    if not artifact.private or not artifact.private_strengths:
        return None
    units = sorted(set(artifact.private) | {served.unit(i) for i in range(len(served.ids))})
    position = {unit: i for i, unit in enumerate(units)}
    owner = np.full(lon.shape[0], -1, dtype=np.int64)
    for i, school in enumerate(served.positions.tolist()):
        owner[school] = position[served.unit(i)]
    near = neighbors(lon, lat, owner, miles)
    entry = artifact.private
    found = {served.unit(i): i for i in range(len(served.ids))}
    states = [
        entry[u].state if u in entry else served.state[found[u]] if u in found else None
        for u in units
    ]
    places = make_places(
        units,
        region=[_region(state) for state in states],
        state=states,
        county=[entry[u].county if u in entry else None for u in units],
        neighbors={units[d]: [units[e] for e in es] for d, es in near.items()},
    )
    shape = (places.size, len(SITUATION_KEYS))
    y, n, yd, nd = (np.zeros(shape) for _ in range(4))
    for i, unit in enumerate(units):
        model = entry.get(unit)
        if model is None or model.y is None:
            continue
        y[i], n[i], yd[i], nd[i] = model.y, model.n, model.yd, model.nd
    rules = artifact.settings.rules(private=True)
    counts = level_counts(places, y, n)
    strengths = Strengths(
        cast("dict[Level, dict[Group, float]]", artifact.private_strengths["no_school"])
    )
    no_school = chain(counts, strengths, rules=rules)
    effective = no_school.situation[0] if no_school.situation.shape[0] else None
    delay = chain(
        level_counts(places, yd, nd),
        Strengths(cast("dict[Level, dict[Group, float]]", artifact.private_strengths["delay"])),
        rules=delay_rules(rules),
        effective=np.maximum(effective, 0) if effective is not None else None,
    )
    p, q = publish_rates(no_school.p, delay.p, rules.floor, rules.ceiling)
    named_y, named_n = named_counts(counts, no_school)
    whole = whole_weather(no_school, counts, None, np.zeros(len(SITUATION_KEYS), dtype=np.bool_))
    rows = np.array([position[served.unit(i)] for i in range(len(served.ids))], dtype=np.int64)
    return _Rates(
        p=p[rows],
        q=q[rows],
        own=no_school.own[rows],
        scope=no_school.scope[rows],
        effective=tuple(int(k) for k in effective)
        if effective is not None
        else (-1,) * len(SITUATION_KEYS),
        named_y=named_y[rows],
        named_n=named_n[rows],
        whole=whole[rows],
    )


def counted_over_private(
    private: Sequence[int] | None, districts: Sequence[int]
) -> tuple[bool, ...]:
    """Per situation, whether a private school's rates come from the private chain (else the
    districts' around it), given each chain's effective situation per situation (``-1``: none
    backed): the private chain where it holds the situation itself; else the districts' where
    they do; else the private chain's fallback where it can be said truly
    (:func:`~snowlight.predict.why.sayable`), else the districts'."""

    def mine(k: int) -> bool:
        if private is None or private[k] < 0:
            return False
        if private[k] == k:
            return True
        if districts[k] == k:
            return False
        return sayable(SITUATIONS[k], SITUATIONS[private[k]])

    return tuple(mine(k) for k in range(len(districts)))


def _private_model(  # noqa: PLR0913 - the served schools, both chains and the model
    served: _Served,
    *,
    districts: _Rates,
    district_live: tuple[bool, ...],
    private: _Rates | None,
    artifact: ModelArtifact,
    near: Sequence[tuple[int, ...]],
) -> PrivateServe:
    """Each served private school's rates, per situation: the private chain's where private
    schools hold enough recorded days of the situation itself; else the districts' around it
    where the districts do (the day's own weather over another weather's private days: an
    extreme cold warning is counted over cold days, not private winter storm warning days);
    else whichever chain can say its fallback truly, the private one first."""
    rules = artifact.settings.rules(private=True)
    count = len(SITUATION_KEYS)
    of_private = counted_over_private(
        private.effective if private is not None else None, districts.effective
    )
    use = np.array(of_private, dtype=np.bool_)[None, :]

    def pick[T: np.generic](mine: npt.NDArray[T], theirs: npt.NDArray[T]) -> npt.NDArray[T]:
        return np.asarray(np.where(use, mine, theirs), dtype=theirs.dtype)

    mine = private if private is not None else districts
    rates = _Rates(
        p=pick(mine.p, districts.p),
        q=pick(mine.q, districts.q),
        own=pick(mine.own, np.zeros_like(districts.own)),
        scope=pick(mine.scope, districts.scope),
        effective=tuple(
            mine.effective[k] if of_private[k] else districts.effective[k] for k in range(count)
        ),
        named_y=pick(mine.named_y, districts.named_y),
        named_n=pick(mine.named_n, districts.named_n),
        whole=pick(mine.whole, districts.whole),
    )
    _check_true(rates, rules)
    entry = artifact.private
    records = tuple(
        dict(entry[school].record) if school is not None and school in entry else {}
        for school in served.ids
    )
    return PrivateServe(
        positions=served.positions,
        time_zone=served.zones,
        neighbors=tuple(tuple(found[:MAX_SCHOOL_NEIGHBORS]) for found in near),
        p=rates.p,
        q=rates.q,
        own=rates.own,
        scope=rates.scope,
        of_private=of_private,
        effective=rates.effective,
        live=tuple(
            not of_private[k] and bool(district_live and district_live[rates.effective[k]])
            for k in range(count)
        ),
        records=records,
        named_y=rates.named_y,
        named_n=rates.named_n,
        known=sum(1 for school in served.ids if school is not None),
        left_out=served.left_out,
        whole=rates.whole,
    )


def build_model(  # noqa: PLR0915 - the steps of one model, in order
    directory: DeployedDirectory,
    artifact: ModelArtifact,
    config: PredictConfig,
    zone_fallback: Callable[[float, float], str | None],
    learned: Learned | None = None,
) -> ServeModel:
    """Every deployed district's rates per situation (see the module docstring), and every
    private school's of the contiguous states (:class:`PrivateServe`).

    ``zone_fallback(lon, lat)`` gives the zone of a district the model does not know.
    ``learned`` adds what the live-read days taught: its anchored situations are counted over
    the live days, the archive giving relative propensities only (:func:`_anchored_counts`).

    Raises:
        ServeError: a deployed district has no time zone.
    """
    points = directory.points
    lon = points.lon_e6.astype(np.float64) * _E6
    lat = points.lat_e6.astype(np.float64) * _E6
    district = points.district.astype(np.int64)
    district[points.district == NO_DISTRICT] = -1
    deployed = directory.district_ids
    miles = config.serve.neighbor_miles
    near = neighbors(lon, lat, district, miles)
    served = _private_served(directory, artifact, lon, lat, zone_fallback)
    private_near = districts_near(lon, lat, district, served.positions, miles)
    # Each private school is also a district with no record of its own in the districts'
    # chain: the rates around it, for the situations private schools have too few days of.
    pseudo = [f"~{int(position):07d}" for position in served.positions.tolist()]
    leaids = sorted(set(deployed) | set(artifact.districts) | set(pseudo))
    entry = artifact.districts
    pseudo_place = {unit: (served.state[i], served.county[i]) for i, unit in enumerate(pseudo)}
    states = [
        pseudo_place[d][0]
        if d in pseudo_place
        else entry[d].state
        if d in entry
        else state_of_leaid(d)
        for d in leaids
    ]
    nearby = {deployed[d]: [deployed[e] for e in es] for d, es in near.items()}
    nearby.update({unit: [deployed[e] for e in private_near[i]] for i, unit in enumerate(pseudo)})
    places = make_places(
        leaids,
        region=[_region(state) for state in states],
        state=states,
        county=[
            pseudo_place[d][1] if d in pseudo_place else entry[d].county if d in entry else None
            for d in leaids
        ],
        neighbors=nearby,
    )
    size = places.size
    shape = (size, len(SITUATION_KEYS))
    y, n, yd, nd = (np.zeros(shape) for _ in range(4))
    for i, leaid in enumerate(places.districts):
        found = entry.get(leaid)
        if found is None or found.y is None:
            continue
        y[i], n[i], yd[i], nd[i] = found.y, found.n, found.yd, found.nd
    settings = artifact.settings
    rules = settings.rules()
    anchored = np.zeros(len(SITUATION_KEYS), dtype=np.bool_)
    ratios: dict[str, Floats] | None = None
    delay_ratios: dict[str, Floats] | None = None
    archive_counts: LevelCounts | None = None
    live_counts: LevelCounts | None = None
    if learned is not None and learned.anchored:
        archive = (y, n, yd, nd)
        anchored, (y, n, yd, nd) = _anchored_counts(places, learned, archive)
        archive_counts = level_counts(places, archive[0], archive[1])
        live_y, live_n = _live_counts(places, learned)
        live_counts = level_counts(places, live_y, live_n)
        ratios = _ratios(
            archive_counts,
            _strengths(artifact, "no_school"),
            rules,
            anchored,
        )
        delay_ratios = _ratios(
            level_counts(places, archive[2], archive[3]),
            _strengths(artifact, "delay"),
            delay_rules(rules),
            anchored,
        )
    counts = level_counts(places, y, n)
    no_school = chain(counts, _strengths(artifact, "no_school"), rules=rules, ratios=ratios)
    if (no_school.situation < 0).any():
        raise ServeError("a situation has no labeled days to publish from, nor a fallback")
    if no_school.situation.shape[0]:
        for k, target in enumerate(no_school.situation[0]):
            if not sayable(SITUATIONS[k], SITUATIONS[int(target)]):
                raise ServeError(
                    f"{SITUATIONS[k].key} cannot be said over {SITUATIONS[int(target)].key}"
                )
    delay = chain(
        level_counts(places, yd, nd),
        _strengths(artifact, "delay"),
        rules=delay_rules(rules),
        effective=no_school.situation[0] if no_school.situation.shape[0] else None,
        ratios=delay_ratios,
    )
    p, q = publish_rates(no_school.p, delay.p, settings.floor, settings.ceiling)
    named_y, named_n = named_counts(counts, no_school)
    whole = whole_weather(
        no_school, archive_counts if archive_counts is not None else counts, live_counts, anchored
    )
    position = places.position()
    rows = np.array([position[d] for d in deployed], dtype=np.int64)
    effective = (
        tuple(int(k) for k in no_school.situation[0])
        if no_school.situation.shape[0]
        else tuple(range(len(SITUATION_KEYS)))
    )
    # The chain names a place only when its share is true; check it again on the served
    # neighbors and the published (floored) chance, so a false base sentence never ships.
    _check_true(
        _Rates(p[rows], q[rows], no_school.own[rows], no_school.scope[rows], effective,
               named_y[rows], named_n[rows], whole[rows]),
        rules,
    )  # fmt: skip
    zones: list[str] = []
    eligible: list[npt.NDArray[np.int64]] = []
    by_district = _schools_by_district(district, len(deployed))
    open_flags = (points.kind & (PRIVATE | CHARTER | VIRTUAL)) == 0
    for index, leaid in enumerate(deployed):
        schools = by_district[index]
        mine = schools[open_flags[schools]] if schools.size else schools
        eligible.append(mine if mine.size else schools)
        zone = entry[leaid].time_zone if leaid in entry else None
        if zone is None and schools.size:
            zone = zone_fallback(float(lon[schools[0]]), float(lat[schools[0]]))
        if zone is None:
            raise ServeError(f"district {leaid} has no time zone")
        zones.append(zone)
    live = tuple(bool(value) for value in anchored)
    private = None
    if served.positions.size:
        prow = np.array([position[unit] for unit in pseudo], dtype=np.int64)
        around = _Rates(
            p=p[prow],
            q=q[prow],
            own=np.zeros((prow.size, len(SITUATION_KEYS)), dtype=np.bool_),
            scope=no_school.scope[prow],
            effective=effective,
            named_y=named_y[prow],
            named_n=named_n[prow],
            whole=whole[prow],
        )
        private = _private_model(
            served,
            districts=around,
            district_live=live,
            private=_private_chain(artifact, served, lon, lat, miles),
            artifact=artifact,
            near=private_near,
        )
    return ServeModel(
        directory=directory,
        artifact=artifact,
        time_zone=tuple(zones),
        neighbors=tuple(near.get(i, ()) for i in range(len(deployed))),
        eligible=tuple(eligible),
        p=p[rows],
        q=q[rows],
        own=no_school.own[rows],
        scope=no_school.scope[rows],
        effective=effective,
        known=sum(1 for d in deployed if d in entry),
        records=tuple(_records(entry, learned, d) for d in deployed),
        named_y=named_y[rows],
        named_n=named_n[rows],
        anchored=live,
        private=private,
        whole=whole[rows],
    )


def _records(
    entry: Mapping[str, DistrictModel], learned: Learned | None, leaid: str
) -> Mapping[str, tuple[RecordDay, ...]]:
    """A district's record days: the archive's, and the live days' for anchored situations."""
    found = dict(entry[leaid].record) if leaid in entry else {}
    if learned is None:
        return found
    for key in learned.anchored:
        found.pop(key, None)
    found.update(learned.records.get(leaid, {}))
    return found


def _region(state: str | None) -> str | None:
    return None if state is None else REGION_OF.get(state)


def _schools_by_district(
    district: npt.NDArray[np.int64], count: int
) -> list[npt.NDArray[np.int64]]:
    order = np.argsort(district, kind="stable")
    sorted_district = district[order]
    found: list[npt.NDArray[np.int64]] = []
    for index in range(count):
        low = np.searchsorted(sorted_district, index, side="left")
        high = np.searchsorted(sorted_district, index, side="right")
        found.append(np.sort(order[low:high]).astype(np.int64))
    return found


def reached_by(
    event: LiveEvent,
    ugcs: UgcIndex,
    heights: npt.NDArray[np.float64] | None,
    margin: float,
) -> tuple[npt.NDArray[np.int64], int]:
    """The schools ``event`` reaches: those of its zones, and when the alert names heights for
    where it applies, only those within them (``margin`` feet to spare), and how many of those
    it counted with no known height (an unknown height is reached). ``heights``: feet per
    school position, NaN where not known; ``None``: none known."""
    reached = ugcs.reached(event.ugcs)
    limit = event.elevation
    if limit is None or not reached.size:
        return reached, 0
    feet = np.full(reached.size, np.nan, dtype=np.float64) if heights is None else heights[reached]
    return reached[limit.reaches(feet, margin)], int(np.isnan(feet).sum())


def school_classes(  # noqa: PLR0913, PLR0917 - the model, the alerts and the day window
    model: ServeModel,
    events: Sequence[LiveEvent],
    ugcs: UgcIndex,
    days: Sequence[date],
    now: datetime,
    window: Window,
    heights: npt.NDArray[np.float64] | None = None,
    margin: float = 0.0,
) -> npt.NDArray[np.int64]:
    """Each school's class per day, (schools, days), read in its district's zone, or a
    private school's own zone (schools no unit counts stay ``none``). An alert that names
    heights reaches only the schools within them (:func:`reached_by`)."""
    points = model.directory.points
    school_zone = np.full(len(points), -1, dtype=np.int64)
    private = model.private
    zone_names = sorted(set(model.time_zone) | set(private.time_zone if private else ()))
    zone_index = {name: i for i, name in enumerate(zone_names)}
    for index, schools in enumerate(model.eligible):
        school_zone[schools] = zone_index[model.time_zone[index]]
    if private is not None:
        for position, zone in zip(private.positions.tolist(), private.time_zone, strict=True):
            school_zone[position] = zone_index[zone]
    found = np.zeros((len(points), len(days)), dtype=np.int64)
    for item in events:
        weather = item.event.weather
        if weather is None:
            continue
        reached, _unknown = reached_by(item, ugcs, heights, margin)
        if not reached.size:
            continue
        reached = reached[school_zone[reached] >= 0]
        for z, name in enumerate(zone_names):
            group = reached[school_zone[reached] == z]
            for d, day in enumerate(days):
                if group.size and counts(item.event, day, name, window, now):
                    found[group, d] = np.maximum(found[group, d], int(weather))
    return found


def unit_classes(  # noqa: PLR0913, PLR0917 - the model, the alerts and the day window
    model: ServeModel,
    events: Sequence[LiveEvent],
    ugcs: UgcIndex,
    days: Sequence[date],
    now: datetime,
    window: Window,
    share: float,
    heights: npt.NDArray[np.float64] | None = None,
    margin: float = 0.0,
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    """Each deployed district's weather class per day, (districts, days), by the same
    covered-share rule as the history (:func:`snowlight.predict.situations.district_class`),
    and each served private school's, (private schools, days): its own school's class
    (``heights`` and ``margin``: :func:`school_classes`)."""
    by_school = school_classes(model, events, ugcs, days, now, window, heights, margin)
    found = np.zeros((len(model.eligible), len(days)), dtype=np.int64)
    for index, schools in enumerate(model.eligible):
        if not schools.size or not by_school[schools].any():
            continue
        for d in range(len(days)):
            mine = [WeatherClass(int(value)) for value in by_school[schools, d].tolist()]
            found[index, d] = int(district_class(mine, share))
    private = model.private
    own = (
        by_school[private.positions]
        if private is not None
        else np.zeros((0, len(days)), dtype=np.int64)
    )
    return found, own


def district_classes(  # noqa: PLR0913, PLR0917 - the model, the alerts and the day window
    model: ServeModel,
    events: Sequence[LiveEvent],
    ugcs: UgcIndex,
    days: Sequence[date],
    now: datetime,
    window: Window,
    share: float,
) -> npt.NDArray[np.int64]:
    """Each deployed district's weather class per day (:func:`unit_classes`)."""
    return unit_classes(model, events, ugcs, days, now, window, share)[0]


type ClosedOn = Callable[[date], frozenset[int] | None]
"""The deployed districts (or private schools, by directory position) that had no school for
weather on a day, or ``None`` when not published (then none counts as the day after)."""

type Earlier = tuple[float, PreviousChance | None, datetime]
"""A unit's chance of no school on a day in the last file, its previous, and that file's time."""


def _previous(last: PredictionsFile | None) -> dict[tuple[int, date], Earlier]:
    if last is None:
        return {}
    found: dict[tuple[int, date], Earlier] = {}
    for entry in last.districts:
        for day, item in zip(last.days, entry.days, strict=True):
            if isinstance(item, Forecast):
                found[(entry.district, day)] = (item.p_no_school, item.previous, last.generated_at)
    return found


def _previous_schools(last: PredictionsFile | None) -> dict[tuple[int, date], Earlier]:
    if last is None:
        return {}
    found: dict[tuple[int, date], Earlier] = {}
    for entry in last.schools:
        for day, item in zip(last.days, last.outlook_of(entry), strict=True):
            if isinstance(item, Forecast):
                found[(entry.school, day)] = (item.p_no_school, item.previous, last.generated_at)
    return found


def forecast_file(  # noqa: PLR0913 - the model, the classes, the days and the lookups
    model: ServeModel,
    classes: npt.NDArray[np.int64],
    days: Sequence[date],
    now: datetime,
    *,
    closed_on: ClosedOn,
    last: PredictionsFile | None,
    private_classes: npt.NDArray[np.int64] | None = None,
    closed_schools: ClosedOn | None = None,
    said: SaidOpen = NOTHING_SAID,
    fit: Fit = Fit.WHOLE,
) -> PredictionsFile:
    """The predictions file of one pass (see the module docstring): every district, and with
    ``private_classes`` (from :func:`unit_classes`) every served private school; ``fit``: what
    it leaves out to fit the size budget.

    Raises:
        TableError: the private schools' outlooks are more than the file may hold.
    """
    generated = now.astimezone(UTC).replace(microsecond=0)
    same = last if last is not None and last.directory == model.directory.stamp else None
    earlier = _previous(same) if fit.previous else {}
    after_sets = {
        day: (closed_on(previous_school_day(day)) or frozenset())
        if is_school_day(day)
        else frozenset()
        for day in days
    }
    entries: list[DistrictForecast] = []
    for index in range(len(model.directory.district_ids)):
        outlooks: list[Forecast | NoThreat] = []
        for d, day in enumerate(days):
            if not is_school_day(day):
                outlooks.append(NoThreat(state="no_threat"))
                continue
            weather = WeatherClass(int(classes[index, d]))
            situation = Situation.of(weather, index in after_sets[day])
            k = SITUATION_POSITION[situation.key]
            counted = model.effective[k]
            outlooks.append(
                _forecast(
                    _Cell(
                        p=float(model.p[index, k]),
                        q=float(model.q[index, k]),
                        own=bool(model.own[index, k]),
                        scope=SCOPES[int(model.scope[index, k])],
                        counted=SITUATIONS[counted],
                        live=bool(model.anchored and model.anchored[counted]),
                        records=model.records[index] if fit.records else {},
                        of="districts",
                        whole=bool(model.whole[index, k]) if model.whole.size else False,
                    ),
                    situation,
                    day,
                    earlier.get((index, day)),
                    generated,
                    said_open=said.district(day, index),
                )
            )
        entries.append(
            DistrictForecast(
                district=index,
                time_zone=model.time_zone[index],
                neighbors=model.neighbors[index],
                days=tuple(outlooks),
            )
        )
    schools: tuple[SchoolForecast, ...] = ()
    table: tuple[Forecast | NoThreat, ...] = ()
    zones: tuple[str, ...] = ()
    if fit.schools and model.private is not None and private_classes is not None:
        schools, table, zones = _schools(
            model.private,
            private_classes,
            days,
            generated,
            earlier=_previous_schools(same) if fit.private_previous else {},
            closed_on=closed_schools,
            said=said,
            records=fit.records,
        )
    return PredictionsFile(
        schema_version=SCHEMA_VERSION,
        generated_at=generated,
        directory=model.directory.stamp,
        days=tuple(days),
        districts=tuple(entries),
        schools=schools,
        outlooks=table,
        zones=zones,
    )


def _schools(  # noqa: PLR0913 - the private schools, their classes, the days and lookups
    private: PrivateServe,
    classes: npt.NDArray[np.int64],
    days: Sequence[date],
    generated: datetime,
    *,
    earlier: Mapping[tuple[int, date], Earlier],
    closed_on: ClosedOn | None,
    said: SaidOpen,
    records: bool = True,
) -> tuple[tuple[SchoolForecast, ...], tuple[Forecast | NoThreat, ...], tuple[str, ...]]:
    """Every served private school's days, and the distinct outlooks and time zones they name,
    each in the order first named; ``records``: with the record days under own bases.

    Raises:
        TableError: more outlooks or time zones than the file may hold, found before any
            school's entry is made (its index would not validate).
    """
    after_sets = {
        day: (closed_on(previous_school_day(day)) if closed_on is not None else None) or frozenset()
        if is_school_day(day)
        else frozenset()
        for day in days
    }
    table: dict[Forecast | NoThreat, int] = {}
    zones: dict[str, int] = {}
    rows: list[tuple[int, int, tuple[int, ...]]] = []
    for i, position in enumerate(private.positions.tolist()):
        named: list[int] = []
        for d, day in enumerate(days):
            outlook: Forecast | NoThreat
            if not is_school_day(day):
                outlook = NoThreat(state="no_threat")
            else:
                weather = WeatherClass(int(classes[i, d]))
                situation = Situation.of(weather, position in after_sets[day])
                k = SITUATION_POSITION[situation.key]
                outlook = _forecast(
                    _Cell(
                        p=float(private.p[i, k]),
                        q=float(private.q[i, k]),
                        own=bool(private.own[i, k]),
                        scope=SCOPES[int(private.scope[i, k])],
                        counted=SITUATIONS[private.effective[k]],
                        live=private.live[k],
                        records=private.records[i] if records else {},
                        of="private_schools" if private.of_private[k] else "districts",
                        whole=bool(private.whole[i, k]) if private.whole.size else False,
                    ),
                    situation,
                    day,
                    earlier.get((position, day)),
                    generated,
                    said_open=said.school(day, position),
                )
            named.append(table.setdefault(outlook, len(table)))
        if len(table) > MAX_OUTLOOKS:
            raise TableError(f"the private schools name over {MAX_OUTLOOKS:,} distinct outlooks")
        zone = zones.setdefault(private.time_zone[i], len(zones))
        if len(zones) > MAX_ZONES:
            raise TableError(f"the private schools name over {MAX_ZONES} time zones")
        rows.append((position, zone, tuple(named)))
    entries = tuple(
        SchoolForecast(school=position, zone=zone, neighbors=private.neighbors[i], days=named)
        for i, (position, zone, named) in enumerate(rows)
    )
    return entries, tuple(table), tuple(zones)


def possible_outlooks(
    private: PrivateServe, days: Sequence[date]
) -> frozenset[Forecast | NoThreat]:
    """Every outlook a pass with no previous chance for private schools
    (:attr:`Fit.NO_PRIVATE_PREVIOUS`) can give them on ``days``: each school in every
    situation (each weather, the day after or not), with the scope and own record its rates
    name there, said open or not, and the no-threat day. Such a pass's shared table is a
    subset, so while there are no more than :data:`MAX_OUTLOOKS` that step never overflows."""
    generated = datetime(2000, 1, 1, tzinfo=UTC)
    found: set[Forecast | NoThreat] = {NoThreat(state="no_threat")}
    for k, situation in enumerate(SITUATIONS):
        counted = SITUATIONS[private.effective[k]]
        of: Of = "private_schools" if private.of_private[k] else "districts"
        cells: set[tuple[float, float, bool, int, tuple[RecordDay, ...], bool]] = set()
        for i in range(len(private)):
            own = bool(private.own[i, k])
            record = tuple(private.records[i].get(counted.key, ())) if own else ()
            cells.add(
                (
                    float(private.p[i, k]),
                    float(private.q[i, k]),
                    own,
                    int(private.scope[i, k]),
                    record,
                    bool(private.whole[i, k]) if private.whole.size else False,
                )
            )
        for p, q, own, scope, record, whole in cells:
            cell = _Cell(
                p=p,
                q=q,
                own=own,
                scope=SCOPES[scope],
                counted=counted,
                live=private.live[k],
                records={counted.key: record} if record else {},
                of=of,
                whole=whole,
            )
            for day in days:
                for said_open in (False, True):
                    found.add(_forecast(cell, situation, day, None, generated, said_open=said_open))
    return frozenset(found)


@dataclass(frozen=True, slots=True)
class _Cell:
    """One unit's rates in one situation, and what its base says of them."""

    p: float
    q: float
    own: bool
    scope: Scope
    counted: Situation
    """The situation whose rates it publishes."""
    live: bool
    records: Mapping[str, tuple[RecordDay, ...]]
    of: Of
    whole: bool = False
    """The counted days are all the place's days of their weather (:func:`whole_weather`)."""


def _forecast(  # noqa: PLR0913 - one unit, one day, and its last chance
    cell: _Cell,
    situation: Situation,
    day: date,
    earlier: Earlier | None,
    generated: datetime,
    *,
    said_open: bool = False,
) -> Forecast:
    """One unit's forecast for one school day. ``said_open``: the unit said school is on that
    day, so its chance of no school is the floor and of a delay 0 (:mod:`snowlight.predict.
    opens`), with the line that takes the rest of the base away, and no previous chance: the
    line shows what the chance was and why it fell (contract C3; it keeps the file's worst
    case within budget)."""
    p, q = cell.p, cell.q
    floor = FLOOR if said_open else None
    shown = floor if floor is not None else p
    record = record_for(cell.records.get(cell.counted.key, ()), day) if cell.own else None
    previous: PreviousChance | None = None
    if earlier is not None and not said_open:
        last_p, last_previous, last_at = earlier
        if last_at >= generated:
            previous = None
        elif round(last_p * 100) != round(shown * 100):
            previous = PreviousChance(p_no_school=last_p, at=last_at)
        elif last_previous is not None and last_previous.at < generated:
            previous = last_previous
    return Forecast(
        state="forecast",
        p_no_school=shown,
        p_delay=0.0 if said_open else q,
        reasons=reasons_for(situation.weather),
        previous=previous,
        why=why_for(
            cell.counted,
            p,
            cell.own,
            cell.scope,
            situation,
            live=cell.live,
            of=cell.of,
            said_open=floor,
            whole=cell.whole,
        ),
        record=record,
    )


def pass_days(now: datetime, config: PredictConfig) -> tuple[date, date]:
    """The days a pass forecasts."""
    return forecast_days(now, config.serve.forecast_zone)


def closed_districts(timeline: DayTimeline, model: ServeModel, share: float) -> frozenset[int]:
    """The deployed districts that had no school for weather on the timeline's day: at least
    ``share`` of their eligible schools ended the day closed or remote, for a weather reason
    (a closing with no reason named is not counted).

    The timeline's school indexes must be the deployed directory's: the same stamp and, when
    both name one, the same content digest. An emptied timeline (no digest) holds no school.

    Raises:
        ServeError: the timeline is for another directory and shows a weather closing (its
            indexes cannot be read against this one: the pass goes dark rather than drop the
            day after).
    """
    closed: set[int] = set()
    start = 0
    for school, count in zip(timeline.schools(), timeline.counts, strict=True):
        last = start + count - 1
        status, reason = timeline.statuses[last], timeline.reasons[last]
        if status in NO_SCHOOL and reason in WEATHER_REASONS:
            closed.add(school)
        start += count
    own = model.directory.content_sha256
    other = timeline.directory != model.directory.stamp or (
        own is not None and timeline.content_sha256 is not None and timeline.content_sha256 != own
    )
    if other:
        if closed:
            raise ServeError(f"the day timeline of {timeline.day} indexes another directory")
        return frozenset()
    found: set[int] = set()
    for index, schools in enumerate(model.eligible):
        if schools.size and sum(1 for s in schools.tolist() if s in closed) >= share * schools.size:
            found.add(index)
    return frozenset(found)


def closed_private(timeline: DayTimeline, model: ServeModel) -> frozenset[int]:
    """The served private schools (directory positions) that ended the timeline's day closed or
    remote for a weather reason (a closing with no reason named is not counted). A timeline for
    another directory gives none (:func:`closed_districts` darkens the pass for it when it shows
    a closing)."""
    private = model.private
    own = model.directory.content_sha256
    other = timeline.directory != model.directory.stamp or (
        own is not None and timeline.content_sha256 is not None and timeline.content_sha256 != own
    )
    if private is None or other:
        return frozenset()
    served = frozenset(private.positions.tolist())
    closed: set[int] = set()
    start = 0
    for school, count in zip(timeline.schools(), timeline.counts, strict=True):
        last = start + count - 1
        status, reason = timeline.statuses[last], timeline.reasons[last]
        if school in served and status in NO_SCHOOL and reason in WEATHER_REASONS:
            closed.add(school)
        start += count
    return frozenset(closed)

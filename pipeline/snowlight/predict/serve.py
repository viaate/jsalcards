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

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from enum import Enum
from typing import Final, Protocol, cast

import numpy as np
import numpy.typing as npt

from snowlight.directory.points import NO_DISTRICT, Points
from snowlight.predict import forecast_adjust, forecast_values
from snowlight.predict.alerts_live import LiveEvent, UgcIndex
from snowlight.predict.anchor import STANDINGS, Anchor, Grid, Plausible, Unit, implied_summary
from snowlight.predict.anchor import failing as failing_clauses
from snowlight.predict.announce import announces_at
from snowlight.predict.artifact import (
    SITUATION_KEYS,
    DistrictModel,
    Learned,
    ModelArtifact,
    RecordDay,
)
from snowlight.predict.calendar import forecast_days, is_school_day, previous_school_day
from snowlight.predict.config import PredictConfig
from snowlight.predict.exposure import CLASSES
from snowlight.predict.forecast_values import NO_FORECASTS, Forecasts
from snowlight.predict.geography import REGION_OF, districts_near, neighbors, state_of_leaid
from snowlight.predict.labels import NO_SCHOOL, WEATHER_REASONS
from snowlight.predict.night_serve import NO_NIGHTS, Nights
from snowlight.predict.nowcast import UNREAD, Neighbors
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
from snowlight.predict.reasons import DayInputs, Moved, moved
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
from snowlight.predict.terms import NO_TERMS
from snowlight.predict.terms import Model as TermsModel
from snowlight.predict.why import (
    ALERT_KIND,
    WEATHER_NAME,
    Of,
    Standing,
    reasons_for,
    record_for,
    sayable,
    why_for,
)
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import DayTimeline
from snowlight.schemas.predictions import (
    MAX_OUTLOOKS,
    MAX_SCHOOL_NEIGHBORS,
    MAX_ZONES,
    DistrictForecast,
    Forecast,
    NoThreat,
    OutlookReason,
    PredictionsFile,
    PreviousChance,
    SchoolForecast,
    Why,
)
from snowlight.schemas.vocab import Reason

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
OUTLOOK_REASON: Final = (Reason.WINTER_STORM, Reason.ICE, Reason.EXTREME_COLD)
"""The weather an outlook line's forecast kind names (snow, ice, feels)."""


class OutlookLines(Protocol):
    """The outlook's chances and lines a file carries (S7-F,
    :class:`snowlight.predict.outlook_serve.Chances`): by (district, day index)."""

    @property
    def p(self) -> npt.NDArray[np.float64]: ...

    @property
    def delay(self) -> npt.NDArray[np.float64]: ...

    @property
    def lines(self) -> Mapping[tuple[int, int], OutlookReason]: ...


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
    NO_NIGHTS = "no_nights"
    """As :attr:`NO_RECORDS`, with no night charts (docs/predict.md, "The night chart"): tried
    only when the pass has nights, so every later step is the file it was before the chart."""
    NO_PRIVATE_PREVIOUS = "no_private_previous"
    """No record days, and no previous chances for private schools: a previous chance makes
    each (chance, previous) pair an outlook of its own, which can overflow the shared table
    (``tests/predict/test_private.py`` bounds the outlooks without one)."""
    NO_PREVIOUS = "no_previous"
    """No record days and no previous chances either."""
    NO_REASONS = "no_reasons"
    """As :attr:`NO_PREVIOUS`, and the districts' chances are the base alone, with no reason
    lines (piece 3's reasons add up to at most about 320 bytes a district-day): the file before the
    reasons, which the size worst case holds (``tests/predict/test_loop.py``). Each chance it
    holds is the model's base, true of its sentence; the reasons' terms only are left out."""
    NO_SCHOOLS = "no_schools"
    """The districts only, as the whole file holds them (the file before private schools)."""
    NO_SCHOOLS_NO_RECORDS = "no_schools_no_records"
    """The districts only, with no record days."""

    @property
    def records(self) -> bool:
        """Whether its forecasts carry the record days under an own base."""
        return self in {Fit.WHOLE, Fit.NO_SCHOOLS}

    @property
    def nights(self) -> bool:
        """Whether its districts' forecasts carry the night chart (when the pass has nights)."""
        return self in {Fit.WHOLE, Fit.NO_RECORDS}

    @property
    def previous(self) -> bool:
        """Whether its districts' forecasts carry the previous chance."""
        return self not in {Fit.NO_PREVIOUS, Fit.NO_REASONS}

    @property
    def reasons(self) -> bool:
        """Whether its districts' chances carry the reasons (when the pass gives them)."""
        return self in {
            Fit.WHOLE,
            Fit.NO_RECORDS,
            Fit.NO_NIGHTS,
            Fit.NO_PRIVATE_PREVIOUS,
            Fit.NO_PREVIOUS,
        }

    @property
    def private_previous(self) -> bool:
        """Whether its private schools' forecasts carry the previous chance."""
        return self in {Fit.WHOLE, Fit.NO_RECORDS, Fit.NO_NIGHTS}

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
            Fit.NO_NIGHTS: "record days or night charts",
            Fit.NO_PRIVATE_PREVIOUS: "record days or private schools' previous chances",
            Fit.NO_PREVIOUS: "record days or previous chances",
            Fit.NO_REASONS: "record days, previous chances or reasons",
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
    """Private schools the model knows by id."""
    whole: npt.NDArray[np.bool_] = field(default_factory=lambda: np.zeros((0, 0), dtype=np.bool_))
    """Per school and situation, whether the days its base counts are all the place's days of
    their weather (:func:`whole_weather`); empty: none is, and no base names its weather."""
    thin: npt.NDArray[np.bool_] = field(default_factory=lambda: np.zeros((0, 0), dtype=np.bool_))
    """Per school and situation, whether its base names the nation for want of its region's
    days (:func:`snowlight.predict.pool.thin_cells`); empty: none does."""
    left_out: int = 0
    """Private schools of the contiguous states left out (no time zone): the pass says how
    many (:func:`snowlight.predict.cli.one_pass`), as a left-out school gets no chance."""
    classed: tuple[bool, ...] = ()
    """Per situation, whether it is served from its storm class's level (the class anchor,
    the districts' own, with no private offset); empty: none is."""
    tropical: npt.NDArray[np.bool_] = field(default_factory=lambda: np.zeros(0, dtype=np.bool_))
    """Per school, whether its county's exposure holds a tropical storm or hurricane warning
    day (:meth:`~snowlight.predict.exposure.Exposure.has_tropical`); empty: none does."""

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
    thin: npt.NDArray[np.bool_] = field(default_factory=lambda: np.zeros((0, 0), dtype=np.bool_))
    """Per deployed district and situation, whether its base names the nation because its
    region holds too few labeled days of the situation (spec addendum 2026-10-24 e, E3b:
    the base's ``thin`` flag); empty: none does."""
    terms: TermsModel = NO_TERMS
    """The reasons' terms (piece 3, :mod:`snowlight.predict.terms`); none: the base alone."""
    q_rate: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros((0, 0)))
    """The delay rate among days with school before rounding, (deployed districts, situations):
    the reasons keep it when they move the chance of no school (empty: taken from ``q``)."""
    p_rate: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros((0, 0)))
    """The chance of no school before rounding, (deployed districts, situations): the outlook
    (S7-F) mixes these, then rounds once (empty: taken from ``p``)."""
    announce: tuple[int | None, ...] = ()
    """Per deployed district, its usual posting time in minutes from the school day's midnight
    (:mod:`snowlight.predict.announce`), or ``None``; empty: none known."""
    classed: tuple[bool, ...] = ()
    """Per situation, whether it is served from its storm class's level (the class anchor,
    :mod:`snowlight.predict.anchor`); empty: none is."""
    standing: npt.NDArray[np.int8] = field(default_factory=lambda: np.zeros((0, 0), dtype=np.int8))
    """(deployed districts, situations): the district's standing in a classed situation's
    class (the index in :data:`~snowlight.predict.anchor.STANDINGS`); empty: usual."""
    anchor: Anchor | None = None
    """The class anchor the classed situations are served from."""
    usual: tuple[float, ...] = ()
    """Per situation, a classed situation's class level at the reference district as served
    (after any shrink), which a standing sentence is said against; empty: none is classed."""
    plausible: Plausible | None = None
    """What the plausibility check (G6) found and did over the deployed districts before
    serving (:class:`~snowlight.predict.anchor.Plausible`); ``None``: no class anchor."""
    tropical: npt.NDArray[np.bool_] = field(default_factory=lambda: np.zeros(0, dtype=np.bool_))
    """Per deployed district, whether the exposure it takes holds a tropical storm or hurricane
    warning day, so its warning-class sentence names storm warnings, not winter storm warnings
    alone (:meth:`~snowlight.predict.exposure.Exposure.has_tropical`); empty: none does."""
    usual_snow: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros((0, 0)))
    """(deployed districts, situations): the snow usual for the district on days of a classed
    situation's class (:mod:`snowlight.predict.forecast_adjust`), NaN where the forecast does
    not move that situation; empty: the forecast moves none."""
    snow_usual: npt.NDArray[np.float64] = field(default_factory=lambda: np.zeros((0, 0)))
    """As ``usual_snow``, with the district's ice days of the class taken as quiet: its usual
    snow alone, the snow line's second bar only (PHYS-R2-S1; never the snow term's anchor, the
    lead's ruling of Nov 1); NaN where none balances."""
    adjust_check: "AdjustCheck | None" = None
    """The plausibility check (G6) on the forecast adjustment's chances as published, averaged
    over each district's days (PHYS-R3-S3); ``None``: no adjustment."""

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
    thin: npt.NDArray[np.bool_] = field(default_factory=lambda: np.zeros((0, 0), dtype=np.bool_))
    """Whether each base names the nation for want of the region's days."""


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


def _check_true(rates: _Rates, rules: Rules, classed: Sequence[bool] = ()) -> None:
    """Every served base sentence is true of the recorded days of the place it names (a
    ``classed`` situation's base names no recorded days: it is not checked)."""
    if rules.almost_share is None or not rates.p.size:
        return
    true = says_true(points_of(rates.p), rates.named_y, rates.named_n, rules.almost_share)
    if classed:
        true |= np.asarray(classed, dtype=np.bool_)[None, :]
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
        thin=no_school.thin[rows],
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
    classed: Sequence[bool] = (),
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
        thin=pick(mine.thin, districts.thin),
    )
    _check_true(rates, rules, classed)
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
        thin=rates.thin,
        left_out=served.left_out,
        whole=rates.whole,
    )


def build_model(  # noqa: PLR0913, PLR0915 - the steps of one model, in order
    directory: DeployedDirectory,
    artifact: ModelArtifact,
    config: PredictConfig,
    zone_fallback: Callable[[float, float], str | None],
    learned: Learned | None = None,
    *,
    anchor: Anchor | None = None,
) -> ServeModel:
    """Every deployed district's rates per situation (see the module docstring), and every
    private school's of the contiguous states (:class:`PrivateServe`).

    ``zone_fallback(lon, lat)`` gives the zone of a district the model does not know.
    ``learned`` adds what the live-read days taught: its anchored situations are counted over
    the live days, the archive giving relative propensities only (:func:`_anchored_counts`).
    ``anchor``: each storm-class situation (``live_score.classes``) is served from its class's
    level instead (:mod:`snowlight.predict.anchor`: capture-corrected priors, the district's
    exposure, the live labels, the plausibility pull), never from an archive closure share;
    the private schools take the same levels with no private offset.

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
    position = places.position()
    rows = np.array([position[d] for d in deployed], dtype=np.int64)
    p_rate = np.array(no_school.p, dtype=np.float64)
    q_rate = np.array(delay.p, dtype=np.float64)
    own_rate = np.array(no_school.own, dtype=np.bool_)
    classed, standing, plausible, tropical = _classed_rates(
        anchor,
        places,
        states,
        frozenset(pseudo),
        rows,
        (p_rate, q_rate, own_rate),
        Grid(settings.floor, settings.ceiling),
    )
    p, q = publish_rates(p_rate, q_rate, settings.floor, settings.ceiling)
    named_y, named_n = named_counts(counts, no_school)
    whole = whole_weather(
        no_school, archive_counts if archive_counts is not None else counts, live_counts, anchored
    )
    effective = tuple(
        k if classed[k] else int(target)
        for k, target in enumerate(
            no_school.situation[0] if no_school.situation.shape[0] else range(len(SITUATION_KEYS))
        )
    )
    flags = tuple(bool(value) for value in classed)
    # The chain names a place only when its share is true; check it again on the served
    # neighbors and the published (floored) chance, so a false base sentence never ships.
    _check_true(
        _Rates(p[rows], q[rows], own_rate[rows], no_school.scope[rows], effective,
               named_y[rows], named_n[rows], whole[rows]),
        rules,
        flags,
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
    counties = places_county(places)
    usual_snow, snow_usual, adjust_check = _usual_snow(
        anchor,
        p[rows],
        [(places.districts[r], counties[r], _region(states[r])) for r in rows.tolist()],
        zones,
        Grid(settings.floor, settings.ceiling),
    )
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
            thin=no_school.thin[prow],
        )
        private = _private_model(
            served,
            districts=around,
            district_live=live,
            private=_private_chain(artifact, served, lon, lat, miles),
            artifact=artifact,
            near=private_near,
            classed=flags,
        )
        if classed.any():
            private = _classed_private(private, p[prow], q[prow], classed, tropical[prow])
    return ServeModel(
        directory=directory,
        artifact=artifact,
        time_zone=tuple(zones),
        neighbors=tuple(near.get(i, ()) for i in range(len(deployed))),
        eligible=tuple(eligible),
        p=p[rows],
        q=q[rows],
        q_rate=q_rate[rows],
        p_rate=p_rate[rows],
        own=own_rate[rows],
        scope=no_school.scope[rows],
        effective=effective,
        known=sum(1 for d in deployed if d in entry),
        records=tuple(_records(entry, learned, d) for d in deployed),
        named_y=named_y[rows],
        named_n=named_n[rows],
        anchored=live,
        private=private,
        whole=whole[rows],
        thin=np.where(classed[None, :], False, no_school.thin[rows]),
        classed=flags if classed.any() else (),
        standing=standing[rows],
        anchor=anchor,
        usual=tuple(
            plausible.levels[klass] if (klass := anchor.class_of(s.key)) is not None else 0.0
            for s in SITUATIONS
        )
        if anchor is not None and plausible is not None
        else (),
        plausible=plausible,
        tropical=tropical[rows],
        usual_snow=usual_snow,
        snow_usual=snow_usual,
        adjust_check=adjust_check,
    )


ORDERED: Final = frozenset({"snow_warning", "lake_snow", "ice", "blizzard"})
"""The winter warning situations an advisory day's chance is never over for the same forecast
(the class order, PHYS-R3-S1; a tropical storm or hurricane warning's hazard is not the
snow)."""


@dataclass(frozen=True, slots=True)
class AdjustCheck:
    """G6 (Addendum A item 5) on the forecast adjustment (PHYS-R3-S3): the national implied
    closures a winter with the adjusted chances as published, averaged over each deployed
    district's days and mornings of each class (:func:`snowlight.predict.forecast_adjust.
    expected`), every clause asserted; where one fails, no district is adjusted (the class
    levels serve) and the pass warns."""

    summary: Mapping[str, float]
    """:func:`snowlight.predict.anchor.implied_summary` of the adjusted means."""
    failing: tuple[str, ...]
    """The clauses that fail (:data:`snowlight.predict.anchor.CLAUSES` and ``district_max``)."""
    capped: int
    """Districts left unadjusted for ``district_max`` alone."""

    def line(self) -> str:
        """One log line."""
        said = self.summary
        text = (
            f"forecast adjustment plausibility: advisory mean "
            f"{said.get('advisory_mean', 0):.3f} p99 {said.get('advisory_p99', 0):.3f}, "
            f"advisory and warning mean {said.get('advisory_warning_mean', 0):.3f}, most "
            f"{said.get('district_max', 0):.2f}; {self.capped:,} districts at their class "
            f"levels for the most"
        )
        if self.failing:
            text += f"; FAILS {', '.join(self.failing)}: the class levels serve, no adjustment"
        return text


def _usual_snow(  # noqa: PLR0915 - each class's solve in order, then the plausibility check
    anchor: Anchor | None,
    p: Floats,
    places: Sequence[forecast_adjust.Place],
    zones: Sequence[str],
    grid: Grid,
) -> tuple[Floats, Floats, AdjustCheck | None]:
    """Each deployed district's usual snow per situation (:func:`snowlight.predict.
    forecast_adjust.usual_snow`): the forecast at which its adjusted chance is the situation's
    class level ``p``, calibrated on its own days of the class, solved for each distinct level
    (the situations of a class share one today, but each is solved at its own); NaN where a
    situation is not adjusted (the chain, cold, tropical, blizzard, no usual snow) and where
    the anchor carries no climate (empty: none adjusted).

    The plausibility check (G6) is held on the adjusted chances as published, averaged over
    each district's days (a class's days at its highest situation's average): a district whose
    days would then come to more closures a winter than ``district_max`` (and more than at its
    class levels) is not adjusted at all. Then every clause of G6 is asserted on the adjusted
    means (PHYS-R3-S3: the national advisory mean and p99, advisory and warning mean, and the
    most of any district); where one fails, no district is adjusted (:class:`AdjustCheck`).

    Also each one's usual snow alone (its ice days of the class taken as quiet,
    :func:`snowlight.predict.forecast_adjust.ice_as_quiet`), for the snow line's comparison
    only (PHYS-R2-S1). Each zone's even snow has its timing term in the solve
    (:func:`snowlight.predict.forecast_adjust.even_factor`, PHYS-R2-S2)."""
    if anchor is None or anchor.climate is None or anchor.adjust is None:
        return np.zeros((0, 0)), np.zeros((0, 0)), None
    settings = anchor.adjust
    climate = anchor.climate
    found = np.full(p.shape, np.nan)
    alone = np.full(p.shape, np.nan)
    scale = np.array([climate.scale(zone) for zone in zones])
    factors = {zone: forecast_adjust.even_factor(zone, settings) for zone in set(zones)}
    even = np.array([factors[zone] for zone in zones])
    level = np.full((len(places), len(CLASSES)), -np.inf)
    mean = np.full((len(places), len(CLASSES)), -np.inf)
    counts: dict[str, Floats] = {}
    solved: dict[tuple[str, bytes], Floats] = {}
    snow_alone: dict[tuple[str, bytes], Floats] = {}
    # The warning class first: an advisory day is never over the same district's warning day
    # for the same forecast (the class order, PHYS-R3-S1), so its solve takes their chances.
    warned: list[Floats] = []
    order = sorted(
        range(len(SITUATIONS)),
        key=lambda k: anchor.class_of(SITUATIONS[k].key) != "warning",
    )
    for k in order:
        situation = SITUATIONS[k]
        klass = anchor.class_of(situation.key)
        if klass is None:
            continue
        j = CLASSES.index(klass)
        level[:, j] = np.maximum(level[:, j], p[:, k])
        ordered = klass == "warning" and situation.key in ORDERED
        if klass not in settings.classes or situation.key in forecast_adjust.SKIP:
            mean[:, j] = np.maximum(mean[:, j], p[:, k])
            if ordered:
                warned.append(
                    np.broadcast_to(
                        p[:, k, None, None],
                        (len(places), forecast_adjust.CODES - 1, len(forecast_adjust.COLD_FEELS)),
                    )
                )
            continue
        if klass not in counts:
            counts[klass] = np.array(
                [climate.counts(klass, place, settings) for place in places]
            ).reshape(len(places), forecast_adjust.CODES - 1)
        most = (
            forecast_adjust.order_cap(p[:, k], warned)
            if klass == "advisory" and "warning" in settings.classes and warned
            else None
        )
        key = (klass, p[:, k].tobytes())
        if key not in solved:
            # The snow alone first (its ice days as quiet: the snow line's second bar,
            # PHYS-R2-S1), then the usual with its ice days. The snow term is NOT anchored at
            # the snow alone's (the lead's ruling of Nov 1, round 4 by hand: the anchor's flat
            # stretch let more snow lower the chance where ice is forecast; PHYS-R3-S1 (i) is a
            # documented limit until a total that stays monotone replaces it).
            snow_alone[key] = forecast_adjust.usual_snow(
                p[:, k],
                forecast_adjust.ice_as_quiet(counts[klass]),
                scale,
                klass,
                settings,
                even=even,
                most=most,
            )
            solved[key] = forecast_adjust.usual_snow(
                p[:, k],
                counts[klass],
                scale,
                klass,
                settings,
                even=even,
                alone=snow_alone[key] if settings.snow_amount else None,
                most=most,
            )
        usual = solved[key]
        # With ``snow_amount`` on, the snow alone's floor in the solve, as serving applies it.
        floor_at = snow_alone[key] if settings.snow_amount else None
        if ordered:
            warned.append(
                forecast_adjust.climate_chances(
                    p[:, k], usual, scale, klass, settings, even, floor_at
                )
            )
        days = forecast_adjust.expected(
            p[:, k],
            counts[klass],
            scale,
            usual,
            klass,
            settings,
            grid.floor,
            grid.ceiling,
            even=even,
            alone=floor_at,
            most=most,
        )
        mean[:, j] = np.maximum(mean[:, j], days)
        found[:, k] = usual
        alone[:, k] = np.where(np.isfinite(usual), snow_alone[key], np.nan)
    level = np.where(np.isfinite(level), level, np.nan)
    mean = np.where(np.isfinite(mean), mean, np.nan)
    days = np.array(
        [
            anchor.exposure.of(leaid, county)[0] or (np.nan,) * len(CLASSES)
            for leaid, county, _ in places
        ],
        dtype=np.float64,
    ).reshape(len(places), len(CLASSES))
    limit = anchor.settings.plausibility.district_max
    implied = np.nansum(days * mean, axis=1)
    over = (implied > limit + 1e-9) & (implied > np.nansum(days * level, axis=1) + 1e-9)
    found[over, :] = np.nan
    alone[over, :] = np.nan
    check = _adjust_check(
        anchor, np.where(over[:, None], level, mean), level, days, int(over.sum())
    )
    if check.failing:
        found[:] = np.nan
        alone[:] = np.nan
    return found, alone, check


def _adjust_check(
    anchor: Anchor, mean: Floats, level: Floats, days: Floats, capped: int
) -> AdjustCheck:
    """Every G6 clause on the adjusted means (districts by class: a class not adjusted at its
    level), over the districts whose days are known (PHYS-R3-S3). A clause fails where the
    adjusted chances break it and come to more than the class levels do (as ``district_max``
    is held per district): the class levels' own check is the anchor's."""
    rules = anchor.settings.plausibility
    level = np.nan_to_num(level)
    mean = np.where(np.isfinite(mean), mean, level)
    mask = np.isfinite(days).all(axis=1)
    known = np.nan_to_num(days)
    summary = implied_summary(mean, known, mask)
    held = implied_summary(level, known, mask)
    failing = [
        clause
        for clause in failing_clauses(mean, known, mask, rules)
        if summary[clause] > held[clause] + 1e-9
    ]
    if mask.any():
        most = (mean[mask] * known[mask]).sum(axis=1)
        at_level = (level[mask] * known[mask]).sum(axis=1)
        if bool(((most > rules.district_max + 1e-9) & (most > at_level + 1e-9)).any()):
            failing.append("district_max")
    return AdjustCheck(summary, tuple(failing), capped)


def _classed_rates(  # noqa: PLR0913, PLR0917 - the anchor, the places and their rates
    anchor: Anchor | None,
    places: Places,
    states: Sequence[str | None],
    pseudo: frozenset[str],
    rows: npt.NDArray[np.int64],
    rates: tuple[Floats, Floats, npt.NDArray[np.bool_]],
    grid: Grid,
) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.int8], Plausible | None, npt.NDArray[np.bool_]]:
    """Serve each storm-class situation from its class's level (``anchor``), in place in
    ``rates`` (chance of no school, delay rate, own record) per place: the situations so
    served, each place's standing in their class and what the plausibility check did (G6:
    every place with known days held to ``district_max``, the deployed districts (``rows``) to
    the national clauses, all on the chances as published on ``grid``, which publishing then
    keeps), and whether each place's exposure holds a tropical storm or hurricane warning day;
    a private school's pseudo-district takes its county's exposure."""
    p_rate, q_rate, own_rate = rates
    classed = np.zeros(len(SITUATION_KEYS), dtype=np.bool_)
    standing = np.zeros(p_rate.shape, dtype=np.int8)
    tropical = np.zeros(places.size, dtype=np.bool_)
    if anchor is None:
        return classed, standing, None, tropical
    units = [
        Unit(None if d in pseudo else d, county, _region(state))
        for d, state, county in zip(places.districts, states, places_county(places), strict=True)
    ]
    tropical[:] = [anchor.exposure.has_tropical(unit.leaid, unit.county) for unit in units]
    pull = np.zeros(places.size, dtype=np.bool_)
    pull[rows] = True
    served = anchor.rates(units, pull=pull, grid=grid)
    for k, situation in enumerate(SITUATIONS):
        klass = anchor.class_of(situation.key)
        if klass is None:
            continue
        j = CLASSES.index(klass)
        classed[k] = True
        p_rate[:, k] = served.p[:, j]
        q_rate[:, k] = served.q[j]
        standing[:, k] = served.standing[:, j]
        own_rate[:, k] = False
    return classed, standing, served.plausible, tropical


def places_county(places: Places) -> list[str | None]:
    """Each place's county FIPS, in :attr:`Places.districts` order."""
    names = places.counties
    return [names[int(code)] if code >= 0 else None for code in places.county.tolist()]


def _classed_private(
    private: PrivateServe,
    p: npt.NDArray[np.float64],
    q: npt.NDArray[np.float64],
    classed: npt.NDArray[np.bool_],
    tropical: npt.NDArray[np.bool_],
) -> PrivateServe:
    """The private schools with each classed situation served from the class level at the
    school's own place (its pseudo-district's rates ``p`` and ``q``, and whether its county's
    exposure holds a tropical warning day): no private offset."""
    use = classed[None, :]
    effective = tuple(k if classed[k] else e for k, e in enumerate(private.effective))
    return replace(
        private,
        p=np.where(use, p, private.p),
        q=np.where(use, q, private.q),
        own=np.where(use, False, private.own),
        effective=effective,
        of_private=tuple(False if classed[k] else v for k, v in enumerate(private.of_private)),
        live=tuple(False if classed[k] else v for k, v in enumerate(private.live)),
        thin=np.where(use, False, private.thin) if private.thin.size else private.thin,
        classed=tuple(bool(value) for value in classed),
        tropical=tropical,
    )


def with_terms(model: ServeModel, terms: TermsModel, announce: Mapping[str, int]) -> None:
    """Give a built model the reasons' terms and each deployed district's usual posting time
    (LEAID to minutes, :mod:`snowlight.predict.announce`)."""
    model.terms = terms
    model.announce = tuple(announce.get(leaid) for leaid in model.directory.district_ids)


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

type Earlier = tuple[float, PreviousChance | None, datetime, bool, bool, bool]
"""A unit's chance of no school on a day in the last file, its previous, that file's time,
whether that chance was served from its storm class's level (a ``class`` base), whether that
day was stormy then (it named forecast weather), and whether lines moved it off its base (on a
``class`` base only the forecast adjustment's do)."""


def _previous(last: PredictionsFile | None) -> dict[tuple[int, date], Earlier]:
    if last is None:
        return {}
    found: dict[tuple[int, date], Earlier] = {}
    for entry in last.districts:
        for day, item in zip(last.days, entry.days, strict=True):
            if isinstance(item, Forecast):
                found[(entry.district, day)] = (
                    item.p_no_school,
                    item.previous,
                    last.generated_at,
                    item.why.base.kind == "class",
                    bool(item.reasons),
                    bool(item.why.reasons),
                )
    return found


def _previous_schools(last: PredictionsFile | None) -> dict[tuple[int, date], Earlier]:
    if last is None:
        return {}
    found: dict[tuple[int, date], Earlier] = {}
    for entry in last.schools:
        for day, item in zip(last.days, last.outlook_of(entry), strict=True):
            if isinstance(item, Forecast):
                found[(entry.school, day)] = (
                    item.p_no_school,
                    item.previous,
                    last.generated_at,
                    item.why.base.kind == "class",
                    bool(item.reasons),
                    bool(item.why.reasons),
                )
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
    forecasts: Forecasts = NO_FORECASTS,
    posted: Neighbors = UNREAD,
    reasons: bool = False,
    announces: bool = False,
    outlook: "OutlookLines | None" = None,
    forecast_at: datetime | None = None,
    nights: Nights = NO_NIGHTS,
    adjust: bool = False,
    read_last: frozenset[tuple[int, date]] | None = None,
    noted: dict[tuple[int, date], "Noted"] | None = None,
) -> PredictionsFile:
    """The predictions file of one pass (see the module docstring): every district, and with
    ``private_classes`` (from :func:`unit_classes`) every served private school; ``fit``: what
    it leaves out to fit the size budget.

    ``reasons``: the districts' chances carry the reasons' terms (piece 3: the forecast read at
    the class snapshot, ``forecasts``, and the districts next door that posted, ``posted``),
    where ``fit`` allows; off, every chance is the base alone, as before piece 3. Private
    schools keep the base alone (each school's own amounts would make each outlook its own and
    overflow the shared table). ``announces``: each district's usual posting time, where known,
    is its forecasts' ``announces_at``. ``outlook``: the night-before outlook's chances and
    lines (S7-F, :mod:`snowlight.predict.outlook_serve`): a district-day with a line publishes
    the outlook's chance, its base the class issued's own (never on a day said open), and the
    file names the forecast's time, ``forecast_at``; a ``fit`` with no reasons carries no line
    (every chance the issued-alerts-only one, as with no outlook). ``nights``: the night charts
    the pass built (:mod:`snowlight.predict.night_serve`), each on its district's day where
    ``fit`` carries them, and the file names their cycle, ``night_at``; nothing here computes a
    night, so no chart code runs inside the file's making. ``adjust``: the forecast read at the
    class snapshot (``forecasts``) moves each advisory and warning day of a district within its
    class (advisory-sane L5, :mod:`snowlight.predict.forecast_adjust`), with its lines, where
    ``fit`` carries reasons, from the day's class snapshot on (9 PM the evening before); a
    district-day before it keeps its class level, and so does one with no forecast read, unless
    the last file holds its lines from the same snapshot at the same class level (a read that
    failed this pass gives the same snapshot's chance, never a swing to the class level and
    back); and so does every day where ``fit`` carries none. ``read_last``: the district-days
    whose forecast the pass that made ``last`` read (``None``: not known, as after a restart):
    a day at its class level in ``last`` that this pass's forecast moves shows no previous
    chance unless that pass read it too (S-R2-3: a read that failed, then one that worked, is
    not a change in the weather). ``noted``: where given, each adjusted district-day's class
    order cap and terms are noted in it (the frozen record reads it; nothing served does).

    Raises:
        TableError: the private schools' outlooks are more than the file may hold.
    """
    generated = now.astimezone(UTC).replace(microsecond=0)
    same = last if last is not None and last.directory == model.directory.stamp else None
    earlier = _previous(same) if fit.previous else {}
    kept = _kept(same, model) if adjust else {}
    after_sets = {
        day: (closed_on(previous_school_day(day)) or frozenset())
        if is_school_day(day)
        else frozenset()
        for day in days
    }
    entries: list[DistrictForecast] = []
    carried = 0
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
            extra = (
                DayInputs(forecasts.get(day, index), posted.get(day, index))
                if reasons and fit.reasons
                else None
            )
            usual = model.announce[index] if announces and model.announce else None
            line = outlook.lines.get((index, d)) if outlook is not None and fit.reasons else None
            moved_by, forecast_read, snapshot = (
                _adjusted(model, index, k, day, forecasts, situation, generated, kept, noted)
                if adjust and fit.reasons and line is None
                else (None, False, None)
            )
            outlooks.append(
                _forecast(
                    _Cell(
                        p=float(model.p[index, k]),
                        q=float(model.q[index, k]),
                        q_rate=float(model.q_rate[index, k]) if model.q_rate.size else None,
                        own=bool(model.own[index, k]),
                        scope=SCOPES[int(model.scope[index, k])],
                        counted=SITUATIONS[counted],
                        live=bool(model.anchored and model.anchored[counted]),
                        records=model.records[index] if fit.records else {},
                        of="districts",
                        whole=bool(model.whole[index, k]) if model.whole.size else False,
                        thin=bool(model.thin.size and model.thin[index, k]),
                        classed=bool(model.classed and model.classed[k]),
                        standing=STANDINGS[int(model.standing[index, k])]
                        if model.standing.size
                        else "usual",
                        usual=model.usual[k] if model.usual else None,
                        tropical=bool(model.tropical.size and model.tropical[index]),
                    ),
                    situation,
                    day,
                    earlier.get((index, day)),
                    generated,
                    said_open=said.district(day, index),
                    terms=model.terms if extra is not None else NO_TERMS,
                    extra=extra,
                    limits=(model.artifact.settings.floor, model.artifact.settings.ceiling),
                    announces=announces_at(usual, day, model.time_zone[index]),
                    outlook=None
                    if line is None or outlook is None
                    else (float(outlook.p[index, d]), float(outlook.delay[index, d]), line),
                    adjusted=moved_by,
                    forecast_read=forecast_read,
                    last_read=read_last is not None and (index, day) in read_last,
                    snapshot=snapshot,
                )
            )
            night = nights.get(day, index) if fit.nights else None
            made = outlooks[-1]
            if night is not None and isinstance(made, Forecast):
                outlooks[-1] = made.model_copy(update={"night": night})
                carried += 1
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
        forecast_at=forecast_at
        if forecast_at is not None and outlook is not None and outlook.lines and fit.reasons
        else None,
        night_at=nights.at if carried else None,
    )


type Kept = dict[tuple[int, date], tuple[tuple[int, str | None, str | None], Moved]]
"""Each district-day the last file moved by the forecast adjustment from its class snapshot on:
its class level (whole percent) with the alert or weather its base names, and its chance,
delay and lines."""

ADJUST_KINDS: Final = frozenset({"snow_total", "timing", "snow_hours", "ice", "wind_chill"})
"""The line kinds the forecast adjustment gives (:func:`snowlight.predict.forecast_adjust.
adjusted`)."""


def _kept(last: PredictionsFile | None, model: ServeModel) -> Kept:
    """The last file's adjusted district-days read at their class snapshot (the file made at or
    after it, so from the same snapshot's run), for a pass whose own read fails (PHYS-S7):
    the snapshot has not changed, so neither has what its read gives."""
    if last is None or len(last.districts) != len(model.time_zone):
        return {}
    found: Kept = {}
    for entry in last.districts:
        zone = model.time_zone[entry.district]
        for day, item in zip(last.days, entry.days, strict=True):
            if (
                not isinstance(item, Forecast)
                or item.why.base.kind != "class"
                or not item.why.reasons
                or not all(reason.kind in ADJUST_KINDS for reason in item.why.reasons)
                or last.generated_at < forecast_adjust.snapshot(day, zone)
            ):
                continue
            moved = Moved(
                p_no_school=item.p_no_school, p_delay=item.p_delay, reasons=item.why.reasons
            )
            base = item.why.base
            found[(entry.district, day)] = ((base.points, base.alert, base.weather), moved)
    return found


def _adjusted(  # noqa: PLR0913, PLR0917 - the model, the cell, the day and its forecast
    model: ServeModel,
    index: int,
    k: int,
    day: date,
    forecasts: Forecasts,
    situation: Situation,
    generated: datetime,
    kept: Kept,
    noted: dict[tuple[int, date], "Noted"] | None = None,
) -> tuple[Moved | None, bool, datetime | None]:
    """A district's storm-class day with the forecast on top of its class level
    (:func:`snowlight.predict.forecast_adjust.adjusted`), or ``None`` where the forecast does
    not move it: not an adjusted situation, before the day's class snapshot (9 PM the evening
    before on the school's clock: turn-on items 8 and 10), no forecast read, or no term worth
    a point; whether its forecast was read for the adjustment (adjusted or not, or the same
    snapshot's lines kept from the last file where this pass's read failed); and the class
    snapshot (``None`` where the day is not adjusted)."""
    anchor = model.anchor
    if anchor is None or anchor.adjust is None or not model.usual_snow.size:
        return None, False, None
    usual = float(model.usual_snow[index, k])
    klass = anchor.class_of(situation.key)
    if klass is None or not math.isfinite(usual):
        return None, False, None
    zone = model.time_zone[index]
    snapshot = forecast_adjust.snapshot(day, zone)
    if generated < snapshot:
        return None, False, snapshot
    p0 = float(model.p[index, k])
    found = forecasts.get(day, index)
    if found is None:
        last = kept.get((index, day))
        # The same snapshot's lines only for the same situation at the same level (PHYS-R2-S4):
        # a lake effect warning's lines are never a winter storm warning's at the same level.
        named = (
            round(p0 * 100),
            ALERT_KIND.get(situation.weather),
            None if situation.weather in ALERT_KIND else WEATHER_NAME.get(situation.weather),
        )
        if last is not None and last[0] == named:
            return last[1], True, snapshot
        return None, False, snapshot
    settings = model.artifact.settings
    cap = _order_cap(model, anchor, index, klass, day, zone, found)
    parts: list[forecast_adjust.TermParts] | None = None if noted is None else []
    moved = forecast_adjust.adjusted(
        p0,
        float(model.q_rate[index, k]) if model.q_rate.size else 0.0,
        klass,
        usual,
        found,
        day,
        zone,
        anchor.adjust,
        settings.floor,
        settings.ceiling,
        snow_usual=float(model.snow_usual[index, k]) if model.snow_usual.size else None,
        cap=cap,
        noted=parts,
    )
    if noted is not None:
        noted[(index, day)] = Noted(cap, parts[0] if parts else None)
    return moved, True, snapshot


@dataclass(frozen=True, slots=True)
class Noted:
    """What the file noted of an adjusted district-day for the frozen record: its class order
    cap and its terms (``None``: no term), as the file applied them."""

    cap: float | None
    parts: forecast_adjust.TermParts | None


@dataclass(frozen=True, slots=True)
class AdjustDetail:
    """What the forecast adjustment did with one district's storm-class day, for the frozen
    record (:mod:`snowlight.predict.frozen`): the serving class and its level (as published,
    ``p0``), the day's class snapshot, the forecast read (``None``: none this pass, or before
    the snapshot), its terms and the chance they give before rounding (``None``: no term)."""

    klass: str
    level: float
    snapshot: datetime
    forecast: forecast_values.DistrictForecast | None = None
    parts: forecast_adjust.TermParts | None = None
    raw: float | None = None


def adjust_detail(  # noqa: PLR0913, PLR0917 - the model, the cell, the day and its forecast
    model: ServeModel,
    index: int,
    k: int,
    day: date,
    forecasts: Forecasts,
    generated: datetime,
    noted: Mapping[tuple[int, date], Noted] | None = None,
) -> AdjustDetail | None:
    """:func:`_adjusted`'s inputs and terms for a district-day (``k`` its situation's
    position): the terms the file noted (``noted``), else worked out again from the same model
    and forecast; ``None`` where the day is not an adjusted one. Nothing served reads it."""
    anchor = model.anchor
    if anchor is None or anchor.adjust is None or not model.usual_snow.size:
        return None
    usual = float(model.usual_snow[index, k])
    klass = anchor.class_of(SITUATIONS[k].key)
    if klass is None or not math.isfinite(usual):
        return None
    zone = model.time_zone[index]
    snapshot = forecast_adjust.snapshot(day, zone)
    p0 = float(model.p[index, k])
    found = forecasts.get(day, index) if generated >= snapshot else None
    if found is None:
        return AdjustDetail(klass, p0, snapshot)
    kept = noted.get((index, day)) if noted is not None else None
    if kept is not None:
        parts = kept.parts
        raw = None if parts is None else forecast_adjust.chance_of(p0, parts)
        return AdjustDetail(klass, p0, snapshot, found, parts, raw)
    cap = _order_cap(model, anchor, index, klass, day, zone, found)
    parts, raw = forecast_adjust.terms_detail(
        p0, klass, usual, found, day, zone, anchor.adjust, cap, _alone(model, index, k)
    )
    return AdjustDetail(klass, p0, snapshot, found, parts, raw)


def exposure_offsets(model: ServeModel) -> npt.NDArray[np.float64]:
    """Each deployed district's offset per serving class (:data:`CLASSES` order) from its
    exposure and region (:meth:`snowlight.predict.anchor.Anchor.offsets`), as the class
    levels are made; NaN with no anchor. Read only by the frozen record."""
    ids = model.directory.district_ids
    found = np.full((len(ids), len(CLASSES)), np.nan, dtype=np.float64)
    anchor = model.anchor
    if anchor is None:
        return found
    entry = model.artifact.districts
    for i, leaid in enumerate(ids):
        known = entry.get(leaid)
        state = known.state if known is not None else state_of_leaid(leaid)
        county = known.county if known is not None else None
        found[i] = anchor.offsets(Unit(leaid, county, _region(state)))[0]
    return found


def _alone(model: ServeModel, index: int, k: int) -> float | None:
    """The district's usual snow alone for situation ``k`` (its ice days as quiet), ``None``
    where not known: the snow alone's floor (:func:`snowlight.predict.forecast_adjust.
    floor_lift`, with ``snow_amount`` on) and the snow line's second bar."""
    return float(model.snow_usual[index, k]) if model.snow_usual.size else None


def _order_cap(  # noqa: PLR0913, PLR0917 - the model, the district, its day and forecast
    model: ServeModel,
    anchor: Anchor,
    index: int,
    klass: str,
    day: date,
    zone: str,
    found: forecast_values.DistrictForecast,
) -> float | None:
    """On an advisory day, the lowest chance (unrounded) the same district's winter warning
    situations would have with the same forecast, which the advisory day's is never over (the
    class order, PHYS-R3-S1; as the solve counts it, :data:`ORDERED`); ``None`` otherwise."""
    settings = anchor.adjust
    if klass != "advisory" or settings is None or "warning" not in settings.classes:
        return None
    found_any: list[float] = []
    for k, situation in enumerate(SITUATIONS):
        if anchor.class_of(situation.key) != "warning" or situation.key not in ORDERED:
            continue
        p0 = float(model.p[index, k])
        usual = float(model.usual_snow[index, k])
        if situation.key in forecast_adjust.SKIP or not math.isfinite(usual):
            found_any.append(p0)
            continue
        found_any.append(
            forecast_adjust.raw_chance(
                p0, "warning", usual, found, day, zone, settings, _alone(model, index, k)
            )
        )
    return min(found_any) if found_any else None


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
                        of="private_schools"
                        if private.of_private[k] or bool(private.classed and private.classed[k])
                        else "districts",
                        whole=bool(private.whole[i, k]) if private.whole.size else False,
                        thin=bool(private.thin.size and private.thin[i, k]),
                        classed=bool(private.classed and private.classed[k]),
                        tropical=bool(private.tropical.size and private.tropical[i]),
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
        classed = bool(private.classed and private.classed[k])
        of: Of = "private_schools" if private.of_private[k] or classed else "districts"
        cells: set[tuple[float, float, bool, int, tuple[RecordDay, ...], bool, bool, bool]] = set()
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
                    bool(private.thin.size and private.thin[i, k]),
                    bool(private.tropical.size and private.tropical[i]),
                )
            )
        for p, q, own, scope, record, whole, thin, tropical in cells:
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
                thin=thin,
                classed=classed,
                tropical=tropical,
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
    thin: bool = False
    """The base names the nation for want of the region's days (never with ``live``: a
    situation counted over days read live names the nation's live record)."""
    q_rate: float | None = None
    """The delay rate among days with school, unrounded (``None``: taken from ``q``)."""
    classed: bool = False
    """The day is served from its storm class's level (:mod:`snowlight.predict.anchor`)."""
    standing: Standing = "usual"
    """The unit's standing in that class (a private school's is always usual)."""
    usual: float | None = None
    """The class's level at a usual district, which a standing is said against."""
    tropical: bool = False
    """The unit's exposure holds a tropical storm or hurricane warning day (a warning-class
    base says so: :func:`~snowlight.predict.why.class_base`)."""


def _forecast(  # noqa: PLR0913 - one unit, one day, and its last chance
    cell: _Cell,
    situation: Situation,
    day: date,
    earlier: Earlier | None,
    generated: datetime,
    *,
    said_open: bool = False,
    terms: TermsModel = NO_TERMS,
    extra: DayInputs | None = None,
    limits: tuple[float, float] = (FLOOR, 0.99),
    announces: datetime | None = None,
    outlook: tuple[float, float, OutlookReason] | None = None,
    adjusted: Moved | None = None,
    forecast_read: bool = False,
    snapshot: datetime | None = None,
    last_read: bool = False,
) -> Forecast:
    """One unit's forecast for one school day. ``said_open``: the unit said school is on that
    day, so its chance of no school is the floor and of a delay 0 (:mod:`snowlight.predict.
    opens`), with the line that takes the rest of the base away, and no previous chance: the
    line shows what the chance was and why it fell (contract C3; it keeps the file's worst
    case within budget). ``terms`` and ``extra``: the reasons on top of the base
    (:mod:`snowlight.predict.reasons`, never on a day said open); ``limits``: the published
    floor and ceiling; ``announces``: the unit's usual posting time that day. ``adjusted``:
    the day's chance and lines with the forecast on its class level (advisory-sane L5), never
    on a day said open; ``forecast_read``: its forecast was read for that (moved or not);
    ``snapshot``: its class snapshot, where the adjustment is on for it; ``last_read``: the
    pass that made the last file read its forecast too."""
    p, q = cell.p, cell.q
    floor = FLOOR if said_open else None
    lines = None
    if floor is None and outlook is not None:
        lines = Moved(p_no_school=outlook[0], p_delay=outlook[1], reasons=(outlook[2],))
    elif floor is None and adjusted is not None:
        lines = adjusted
    elif floor is None and extra is not None:
        lines = moved(
            p,
            q,
            situation.weather,
            cell.counted.weather,
            terms,
            extra,
            limits[0],
            limits[1],
            q_rate=cell.q_rate,
        )
    shown = floor if floor is not None else p if lines is None else lines.p_no_school
    record = record_for(cell.records.get(cell.counted.key, ()), day) if cell.own else None
    previous: PreviousChance | None = None
    if earlier is not None and not said_open:
        last_p, last_previous, last_at, last_classed, last_stormy, last_lines = earlier
        storm = situation.weather != WeatherClass.NONE
        # A storm-class day's chance moved by the forecast against one at its class level
        # with no forecast read (advisory-sane L5) is not a change in the weather: the forecast
        # arriving (the last file was made before the day's class snapshot, so nothing could
        # move it then) or this pass's read failing with no lines of the same snapshot to keep.
        # A class-level chance with lines is a moved one: no other line is said on a class base.
        # Kept where both files are from the snapshot on and both passes read it: a forecast
        # that moved the chance less than a point the pass before and moves it now is a change.
        # Where the last pass is not known to have read it (its read failed, or this process
        # did not make it), its class level may be a failed read's: no previous chance (S-R2-3).
        last_moved = last_classed and last_lines
        now_moved = lines is not None
        arrived = (
            now_moved
            and snapshot is not None
            and (last_at < snapshot or (not last_moved and not last_read))
        )
        lost = last_moved and not now_moved and not forecast_read
        unread_change = arrived or lost
        if (
            last_at >= generated
            or (last_classed != cell.classed and last_stormy and storm)
            or (cell.classed and last_classed and storm and unread_change)
        ):
            # A storm day's chance from the other method (the chain's before its class level
            # served, or the class level's after ``serve.anchor`` is turned off) is not an
            # earlier forecast: "Down from 93%" would read as the storm weakening, "Up from 7%"
            # as it worsening. A quiet day's chance before an alert came, or a storm day's
            # before it passed, is one: "Up from 3% at 5 PM" stays.
            previous = None
        elif round(last_p * 100) != round(shown * 100):
            previous = PreviousChance(p_no_school=last_p, at=last_at)
        elif last_previous is not None and last_previous.at < generated:
            previous = last_previous
    why = why_for(
        cell.counted,
        p,
        cell.own,
        cell.scope,
        situation,
        live=cell.live,
        of=cell.of,
        said_open=floor,
        whole=cell.whole,
        thin=cell.thin and not cell.live and not cell.classed,
        classed=cell.standing if cell.classed else None,
        usual=cell.usual,
        tropical=cell.tropical,
    )
    if lines is not None:
        why = Why(base=why.base, reasons=lines.reasons)
    weather = reasons_for(situation.weather)
    if outlook is not None and floor is None and outlook[2].f is not None:
        # The outlook's forecast is weather forecast (spec-f s. 8): snow, ice or cold.
        named = OUTLOOK_REASON[outlook[2].f[0]]
        weather = weather if named in weather else (*weather, named)
    return Forecast(
        state="forecast",
        p_no_school=shown,
        p_delay=0.0 if said_open else q if lines is None else lines.p_delay,
        reasons=weather,
        previous=previous,
        announces_at=announces,
        why=why,
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

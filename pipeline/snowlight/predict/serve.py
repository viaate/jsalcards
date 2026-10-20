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

Nothing here touches the network: the caller hands every input in.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Final, cast

import numpy as np
import numpy.typing as npt

from snowlight.directory.points import NO_DISTRICT, Points
from snowlight.predict.alerts_live import LiveEvent, UgcIndex
from snowlight.predict.artifact import SITUATION_KEYS, ModelArtifact, RecordDay
from snowlight.predict.calendar import forecast_days, is_school_day, previous_school_day
from snowlight.predict.config import PredictConfig
from snowlight.predict.geography import REGION_OF, neighbors, state_of_leaid
from snowlight.predict.labels import NO_SCHOOL, WEATHER_REASONS
from snowlight.predict.pool import (
    SCOPES,
    Level,
    Strengths,
    chain,
    delay_rules,
    level_counts,
    make_places,
    named_counts,
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
from snowlight.predict.why import reasons_for, record_for, sayable, why_for
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import DayTimeline
from snowlight.schemas.predictions import (
    DistrictForecast,
    Forecast,
    NoThreat,
    PredictionsFile,
    PreviousChance,
)

SCHEMA_VERSION: Final = 1
PRIVATE: Final = 0x01
CHARTER: Final = 0x02
VIRTUAL: Final = 0x04
_E6: Final = 1e-6
SITUATION_POSITION: Final = {item.key: i for i, item in enumerate(SITUATIONS)}


class ServeError(RuntimeError):
    """A pass cannot give a true file (the caller publishes nothing: fail dark)."""


@dataclass(frozen=True, slots=True)
class DeployedDirectory:
    """The deployed directory: its stamp, district ids and every school's point."""

    stamp: DirectoryStamp
    district_ids: tuple[str, ...]
    points: Points
    content_sha256: str | None = None
    """The deployed edition's content digest (two contents can share one stamp); ``None``
    when the folder named none (a local dry run)."""

    def __post_init__(self) -> None:
        if len(self.district_ids) != self.stamp.districts or len(self.points) != self.stamp.schools:
            raise ServeError("the directory's ids and points disagree with its stamp")
        if self.points.district_count != len(self.district_ids):
            raise ServeError("points.bin counts other districts than meta.json")


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

    @property
    def coverage(self) -> float:
        """The share of deployed districts the model knows."""
        total = len(self.directory.district_ids)
        return self.known / total if total else 0.0


def _strengths(artifact: ModelArtifact, outcome: str) -> Strengths:
    return Strengths(cast("dict[Level, dict[Group, float]]", artifact.strengths[outcome]))


def build_model(
    directory: DeployedDirectory,
    artifact: ModelArtifact,
    config: PredictConfig,
    zone_fallback: Callable[[float, float], str | None],
) -> ServeModel:
    """Every deployed district's rates per situation (see the module docstring).

    ``zone_fallback(lon, lat)`` gives the zone of a district the model does not know.

    Raises:
        ServeError: a deployed district has no time zone.
    """
    points = directory.points
    lon = points.lon_e6.astype(np.float64) * _E6
    lat = points.lat_e6.astype(np.float64) * _E6
    district = points.district.astype(np.int64)
    district[points.district == NO_DISTRICT] = -1
    deployed = directory.district_ids
    near = neighbors(lon, lat, district, config.serve.neighbor_miles)
    leaids = sorted(set(deployed) | set(artifact.districts))
    entry = artifact.districts
    states = [entry[d].state if d in entry else state_of_leaid(d) for d in leaids]
    places = make_places(
        leaids,
        region=[_region(state) for state in states],
        state=states,
        county=[entry[d].county if d in entry else None for d in leaids],
        neighbors={deployed[d]: [deployed[e] for e in es] for d, es in near.items()},
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
    counts = level_counts(places, y, n)
    no_school = chain(counts, _strengths(artifact, "no_school"), rules=rules)
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
    )
    p, q = publish_rates(no_school.p, delay.p, settings.floor, settings.ceiling)
    named_y, named_n = named_counts(counts, no_school)
    position = places.position()
    rows = np.array([position[d] for d in deployed], dtype=np.int64)
    # The chain names a place only when its share is true; check it again on the served
    # neighbors and the published (floored) chance, so a false base sentence never ships.
    if rules.almost_share is not None and rows.size:
        true = says_true(points_of(p[rows]), named_y[rows], named_n[rows], rules.almost_share)
        if not true.all():
            raise ServeError(
                f"{int((~true).sum())} served base sentences are not true of the recorded "
                "days of the place they name"
            )
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
        effective=tuple(int(k) for k in no_school.situation[0])
        if no_school.situation.shape[0]
        else tuple(range(len(SITUATION_KEYS))),
        known=sum(1 for d in deployed if d in entry),
        records=tuple(entry[d].record if d in entry else {} for d in deployed),
        named_y=named_y[rows],
        named_n=named_n[rows],
    )


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


def school_classes(  # noqa: PLR0913, PLR0917 - the model, the alerts and the day window
    model: ServeModel,
    events: Sequence[LiveEvent],
    ugcs: UgcIndex,
    days: Sequence[date],
    now: datetime,
    window: Window,
) -> npt.NDArray[np.int64]:
    """Each school's class per day, (schools, days), read in its district's zone (schools no
    district counts stay ``none``)."""
    points = model.directory.points
    school_zone = np.full(len(points), -1, dtype=np.int64)
    zone_names = sorted(set(model.time_zone))
    zone_index = {name: i for i, name in enumerate(zone_names)}
    for index, schools in enumerate(model.eligible):
        school_zone[schools] = zone_index[model.time_zone[index]]
    found = np.zeros((len(points), len(days)), dtype=np.int64)
    for item in events:
        weather = item.event.weather
        reached = ugcs.reached(item.ugcs)
        if weather is None or not reached.size:
            continue
        reached = reached[school_zone[reached] >= 0]
        for z, name in enumerate(zone_names):
            group = reached[school_zone[reached] == z]
            for d, day in enumerate(days):
                if group.size and counts(item.event, day, name, window, now):
                    found[group, d] = np.maximum(found[group, d], int(weather))
    return found


def district_classes(  # noqa: PLR0913, PLR0917 - the model, the alerts and the day window
    model: ServeModel,
    events: Sequence[LiveEvent],
    ugcs: UgcIndex,
    days: Sequence[date],
    now: datetime,
    window: Window,
    share: float,
) -> npt.NDArray[np.int64]:
    """Each deployed district's weather class per day, (districts, days), by the same
    covered-share rule as the history (:func:`snowlight.predict.situations.district_class`)."""
    by_school = school_classes(model, events, ugcs, days, now, window)
    found = np.zeros((len(model.eligible), len(days)), dtype=np.int64)
    for index, schools in enumerate(model.eligible):
        if not schools.size or not by_school[schools].any():
            continue
        for d in range(len(days)):
            mine = [WeatherClass(int(value)) for value in by_school[schools, d].tolist()]
            found[index, d] = int(district_class(mine, share))
    return found


type ClosedOn = Callable[[date], frozenset[int] | None]
"""The deployed districts that had no school for weather on a day, or ``None`` when not
published (then no district counts as the day after)."""


def _previous(
    last: PredictionsFile | None,
) -> dict[tuple[int, date], tuple[float, PreviousChance | None, datetime]]:
    if last is None:
        return {}
    found: dict[tuple[int, date], tuple[float, PreviousChance | None, datetime]] = {}
    for entry in last.districts:
        for day, item in zip(last.days, entry.days, strict=True):
            if isinstance(item, Forecast):
                found[(entry.district, day)] = (item.p_no_school, item.previous, last.generated_at)
    return found


def forecast_file(  # noqa: PLR0913 - the model, the classes, the days and two lookups
    model: ServeModel,
    classes: npt.NDArray[np.int64],
    days: Sequence[date],
    now: datetime,
    *,
    closed_on: ClosedOn,
    last: PredictionsFile | None,
) -> PredictionsFile:
    """The predictions file of one pass (see the module docstring)."""
    generated = now.astimezone(UTC).replace(microsecond=0)
    earlier = _previous(
        last if last is not None and last.directory == model.directory.stamp else None
    )
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
            outlooks.append(
                _forecast(model, index, situation, day, earlier.get((index, day)), generated)
            )
        entries.append(
            DistrictForecast(
                district=index,
                time_zone=model.time_zone[index],
                neighbors=model.neighbors[index],
                days=tuple(outlooks),
            )
        )
    return PredictionsFile(
        schema_version=SCHEMA_VERSION,
        generated_at=generated,
        directory=model.directory.stamp,
        days=tuple(days),
        districts=tuple(entries),
    )


def _forecast(  # noqa: PLR0913, PLR0917 - one district, one day, and its last chance
    model: ServeModel,
    index: int,
    situation: Situation,
    day: date,
    earlier: tuple[float, PreviousChance | None, datetime] | None,
    generated: datetime,
) -> Forecast:
    weather = situation.weather
    day_situation = situation
    k = SITUATION_POSITION[situation.key]
    situation = SITUATIONS[model.effective[k]]
    p = float(model.p[index, k])
    q = float(model.q[index, k])
    own = bool(model.own[index, k])
    scope = SCOPES[int(model.scope[index, k])]
    record = record_for(model.records[index].get(situation.key, ()), day) if own else None
    previous: PreviousChance | None = None
    if earlier is not None:
        last_p, last_previous, last_at = earlier
        if last_at >= generated:
            previous = None
        elif round(last_p * 100) != round(p * 100):
            previous = PreviousChance(p_no_school=last_p, at=last_at)
        elif last_previous is not None and last_previous.at < generated:
            previous = last_previous
    return Forecast(
        state="forecast",
        p_no_school=p,
        p_delay=q,
        reasons=reasons_for(weather),
        previous=previous,
        announces_at=None,
        buses_at=None,
        hours=None,
        why=why_for(situation, p, own, scope, day_situation),
        record=record,
        events=(),
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

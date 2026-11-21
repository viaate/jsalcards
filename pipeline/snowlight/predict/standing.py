"""The standing file (``predictions/standing/<stamp>.json``): every number the why's steps state
on a storm-class day (WHY-TRANSPARENT, docs/predict.md "The why, step by step").

:func:`build` makes it from what serving already holds (the class anchor's rates with each
hold's stage, the exposure, the forecast climate and its usual snow, the committed model's
records); :func:`guard` recomputes each unit's start from the file's own numbers and refuses a
file whose steps would not add to the chance served, or one over its budgets. A pass writes the
file only when its stamp is new (:func:`stamp_of`: the contents without ``generated_at``).

Per unit and class, whole points on the published grid: ``v0`` the level at its offset with no
hold, ``v1`` after the district pull or cap, ``v2`` after the national steps, ``v3`` as served.
The held stages are ``[v1 - v0, v2 - v1, v3 - v2]``, with a mask of the stages that moved the
chance at all (:data:`ACTED_DISTRICT`, :data:`ACTED_NATIONAL`: a stage that moved it under a
point shows as a "0" row); ``v0 - now`` splits between the region
delta and the exposure term by exact Shapley values on the chance scale, whole by
:func:`~snowlight.predict.shapley.whole_points`. The panel shows the standing as what is left:
``base.points - now - region - held``.
"""

import functools
import gzip
import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Final

import numpy as np
import numpy.typing as npt

from snowlight.predict import forecast_adjust
from snowlight.predict.anchor import (
    CLAUSES,
    Anchor,
    ClassFit,
    Grid,
    Unit,
    UnitRates,
    _nodes,
    sigmoid,
)
from snowlight.predict.artifact import SITUATION_KEYS, DistrictModel, ModelArtifact
from snowlight.predict.exposure import CLASSES
from snowlight.predict.forecast_values import DistrictForecast
from snowlight.predict.habit_record import FullRow, read_record_file
from snowlight.predict.shapley import whole_points
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.predictions import PlausibilityClause
from snowlight.schemas.standing import (
    FLAG_BORROWED,
    FLAG_CAPPED,
    FLAG_CLAMP,
    FLAG_MIXED,
    FLAG_ONE,
    FLAG_POOL_NONE,
    FLAG_POOL_REGION,
    PRIVATE_CAPPED,
    PRIVATE_TROPICAL,
    PrivateStanding,
    StandingFile,
    StandingHeld,
    StandingLevel,
    StandingLevels,
    StandingOwn,
    StandingRecord,
    StandingRecordFull,
    StandingRefs,
    StandingRegion,
    StandingRegionDelta,
    StandingRegionDeltas,
    StandingSnow,
    StandingSums,
)

type Floats = npt.NDArray[np.float64]

SNOW_CLASSES: Final = ("advisory", "warning")
"""The classes the forecast moves, each with its usual snow."""
SITUATION_OF: Final = {"advisory": "advisory", "warning": "snow_warning"}
"""The situation whose usual snow a class's columns give (a class's situations share it)."""
LEFT_OUT: Final = frozenset({"advisory_after"})
"""Situations the record leaves out: a day after an advisory day is not that day's record."""
PREFIX: Final = "predictions/standing/"
CLIP_EPS: Final = 1e-12
"""How near the clip a region delta is said to be at it."""
ACTED_EPS: Final = 1e-9
"""How far a hold's stage must move the chance to have acted."""
ACTED_DISTRICT: Final = 1
"""A held row's mask bit: the district pull or cap moved the chance."""
ACTED_NATIONAL: Final = 2
"""... the national steps moved it."""


def path_of(stamp: str) -> str:
    """The file's path under the data root."""
    return f"{PREFIX}{stamp}.json"


@dataclass(frozen=True, slots=True)
class Inputs:
    """What :func:`build` reads, as :func:`snowlight.predict.serve.build_model` holds it.
    Every per-district array is in deployed order (directory positions)."""

    anchor: Anchor
    rates: UnitRates
    units: Sequence[Unit]
    rows: npt.NDArray[np.int64]
    """Each deployed district's row in ``rates``."""
    private_rows: npt.NDArray[np.int64]
    """Each served private school's row in ``rates``, in ``latest.json`` ``schools`` order."""
    private_ids: Sequence[str | None]
    artifact: ModelArtifact
    district_ids: Sequence[str]
    mixed: npt.NDArray[np.bool_]
    one: npt.NDArray[np.bool_]
    places: Sequence[forecast_adjust.Place]
    zones: Sequence[str]
    p: Floats
    """The published chance per deployed district and situation."""
    usual_snow: Floats
    snow_usual: Floats
    grid: Grid
    full: Mapping[str, Mapping[str, FullRow]] = field(default_factory=dict)
    """Each LEAID's complete records by class (:func:`full_records`, records-mo): shown in
    place of its list record, never read by a chance (LR-9)."""


@dataclass(frozen=True, slots=True)
class Built:
    """The file (without its time) and what its guard checks it against."""

    file: StandingFile
    served: npt.NDArray[np.int64]
    """Whole points per deployed district and class, as served (``v3``)."""
    private_served: npt.NDArray[np.int64]
    """... per served private school."""
    regions: tuple[str | None, ...]
    """Each deployed district's region (the guard's delta)."""
    private_regions: tuple[str | None, ...]
    refused: tuple[str, ...] = ()
    """Units whose split could not be made (the file is refused)."""
    unsaid: tuple[str, ...] = ()
    """What a panel would show with no words for an input the model used (the file is refused):
    a shown usual snow whose zone weighs even snow off 1.0 (:func:`even_factor`, spec r5 2b),
    a private school's region part outside the advisory class (the private rows hold only that
    one)."""


def _whole(grid: Grid, p: Floats) -> npt.NDArray[np.int64]:
    return np.asarray(np.round(grid.round(p) * 100), dtype=np.int64)


def _season(name: str) -> int:
    return int(name.split("-", 1)[0])


def _ceil100(x: float) -> int:
    return math.ceil(round(x * 100, 6))


def _floor100(x: float) -> int:
    return math.floor(round(x * 100, 6))


def split(fit: ClassFit, alpha: float, delta: float, moved: float, total: int) -> tuple[int, int]:
    """``total`` whole points (``v0 - now``) split between the region delta and the exposure
    term ``moved`` by exact Shapley values on the chance scale: (region, standing).

    Raises:
        ValueError: no such split (the parts point against ``total``).
    """
    if delta == 0.0:
        return 0, total

    def level(o: float) -> float:
        return float(fit.level(o, alpha))

    region = 50.0 * ((level(delta) - level(0.0)) + (level(delta + moved) - level(moved)))
    standing = 50.0 * ((level(moved) - level(0.0)) + (level(delta + moved) - level(delta)))
    found = whole_points({"region": region, "standing": standing}, total)
    return found["region"], found["standing"]


def shown_usual(  # noqa: PLR0913, PLR0917 - the district's level, its usuals and the settings
    p0: float,
    usual: float,
    alone: float,
    klass: str,
    settings: forecast_adjust.AdjustSettings,
    day: date,
    zone: str,
) -> tuple[int, int | None, bool]:
    """The usual snow and the snow alone's floor as shown (hundredths), and whether the floor
    is clamped at a third of the usual: where ``ceil(b) < floor(u)`` both show, each inside the
    exact range; else ``u`` alone, to the nearest hundredth, moved one toward the exact ``u``
    where the chance there does not round to ``p0``."""
    ratio = settings.snow_amount_floor_ratio
    clamp = bool(settings.snow_amount and math.isfinite(alone) and alone < usual / ratio)
    if settings.snow_amount and math.isfinite(alone):
        held = min(max(alone, usual / ratio), usual)
        if _ceil100(held) < _floor100(usual):
            return _floor100(usual), _ceil100(held), clamp
    shown = round(usual * 100)
    if round(_chance_at(p0, shown / 100, usual, alone, klass, settings, day, zone), 2) != p0:
        shown += 1 if usual * 100 > shown else -1
    return shown, None, clamp


def _chance_at(  # noqa: PLR0913, PLR0917 - the level, the snow, its usuals and the settings
    p0: float,
    snow: float,
    usual: float,
    alone: float,
    klass: str,
    settings: forecast_adjust.AdjustSettings,
    day: date,
    zone: str,
) -> float:
    """The chance with ``snow`` inches and no ice or cold, before publishing rounds it."""
    forecast = DistrictForecast(code=1, snow=snow, ice=0.0, snow_commute=snow, snow_bus=snow)
    return forecast_adjust.raw_chance(
        p0, klass, usual, forecast, day, zone, settings, alone if math.isfinite(alone) else None
    )


def _pool(
    climate: forecast_adjust.Climate,
    klass: str,
    place: forecast_adjust.Place,
    settings: forecast_adjust.AdjustSettings,
) -> str:
    """Where a place's 10 more days come from, by :meth:`Climate.counts`' rule."""
    _, county, region_name = place
    pool = 0.0
    if county is not None and klass in climate.counties.get(county, {}):
        pool = float(sum(climate.counties[county][klass]))
    region = climate.regions.get(region_name or "", {})
    if pool < settings.county_min_days and klass in region:
        return "region" if sum(region[klass]) > 0 else "none"
    return "county" if pool > 0 else "none"


def record_of(model: DistrictModel | None, anchor: Anchor) -> dict[str, tuple[int, int, int]]:
    """A unit's record per class: no school, a late start and days the lists tell us about,
    summed over the class's situations (without :data:`LEFT_OUT`); only classes with days."""
    if model is None or model.y is None or model.n is None or model.yd is None:
        return {}
    found: dict[str, tuple[int, int, int]] = {}
    for klass in CLASSES:
        keys = [
            k
            for k, key in enumerate(SITUATION_KEYS)
            if key not in LEFT_OUT and anchor.class_of(key) == klass
        ]
        closed = sum(model.y[k] for k in keys)
        delayed = sum(model.yd[k] for k in keys)
        days = sum(model.n[k] for k in keys)
        if days > 0:
            found[klass] = (closed, delayed, days)
    return found


def _level(fit: ClassFit, alpha: float) -> float:
    return float(fit.level(0.0, alpha))


def build(inputs: Inputs, directory: DirectoryStamp, generated: datetime) -> Built:  # noqa: PLR0915 - every column in order
    """The standing file of a model (see the module docstring)."""
    anchor, rates, grid = inputs.anchor, inputs.rates, inputs.grid
    pull = rates.plausible.pull
    raw = rates.raw if rates.raw is not None else rates.p
    offsets = rates.offsets if rates.offsets is not None else np.zeros(rates.p.shape)
    deltas = rates.deltas if rates.deltas is not None else np.zeros(rates.p.shape)
    v0 = _whole(grid, raw)
    v1 = _whole(grid, pull.district_stage) if pull.district_stage is not None else v0
    v2 = _whole(grid, pull.national_stage) if pull.national_stage is not None else v1
    v3 = np.asarray(np.round(rates.p * 100), dtype=np.int64)
    pulled = pull.district_stage if pull.district_stage is not None else raw
    stepped = pull.national_stage if pull.national_stage is not None else pulled
    acted = (np.abs(pulled - raw) > ACTED_EPS) * ACTED_DISTRICT + (
        np.abs(stepped - pulled) > ACTED_EPS
    ) * ACTED_NATIONAL
    capped = pull.capped_mask if pull.capped_mask is not None else np.zeros(len(inputs.units), bool)
    alphas = rates.alpha or tuple(anchor.fits[k].alpha for k in CLASSES)
    now = [
        round(100 * float(grid.round(np.array(_level(anchor.fits[k], alphas[j])))))
        for j, k in enumerate(CLASSES)
    ]
    refused: list[str] = []
    unsaid: list[str] = []

    def region_points(r: int, j: int) -> int:
        total = int(v0[r, j]) - now[j]
        delta = float(deltas[r, j])
        try:
            return split(
                anchor.fits[CLASSES[j]], alphas[j], delta, float(offsets[r, j]) - delta, total
            )[0]
        except ValueError:
            refused.append(f"{inputs.units[r].leaid or 'private'} {CLASSES[j]}")
            return 0

    exposure = anchor.exposure
    count = len(inputs.district_ids)
    winter: list[tuple[float, float, float] | None] = []
    flags: list[int] = []
    region_rows: dict[str, list[tuple[int, int, int]]] = {k: [] for k in CLASSES}
    held_rows: dict[str, list[tuple[int, int, int, int, int]]] = {k: [] for k in CLASSES}
    record_rows: dict[str, list[tuple[int, int, int, int]]] = {k: [] for k in CLASSES}
    usual: dict[str, list[int | None]] = {k: [] for k in SNOW_CLASSES}
    alone: dict[str, list[int | None]] = {k: [] for k in SNOW_CLASSES}
    own: dict[str, list[int]] = {k: [] for k in SNOW_CLASSES}
    clipped = _clipped(anchor)
    climate, settings = anchor.climate, anchor.adjust
    day = date(2026, 1, 7)  # no period is named: the chance at a snow amount reads no hours
    even: dict[str, float] = {}
    for i in range(count):
        r = int(inputs.rows[i])
        unit = inputs.units[r]
        days, borrowed = exposure.of(unit.leaid, unit.county)
        winter.append(None if days is None else tuple(round(float(d), 1) for d in days))  # type: ignore[arg-type]
        bits = (
            (FLAG_BORROWED if borrowed and days is not None else 0)
            | (FLAG_MIXED if inputs.mixed[i] else 0)
            | (FLAG_ONE if inputs.one[i] else 0)
        )
        for j, klass in enumerate(CLASSES):
            if capped[r]:
                bits |= FLAG_CAPPED[klass]
            points = region_points(r, j)
            if points:
                region_rows[klass].append((i, points, int(unit.region in clipped[klass])))
            stages = (int(v1[r, j] - v0[r, j]), int(v2[r, j] - v1[r, j]), int(v3[r, j] - v2[r, j]))
            if any(stages) or acted[r, j]:
                held_rows[klass].append((i, *stages, int(acted[r, j])))
        for klass in SNOW_CLASSES:
            k = SITUATION_KEYS.index(SITUATION_OF[klass])
            u = float(inputs.usual_snow[i, k]) if inputs.usual_snow.size else math.nan
            if climate is None or settings is None or not math.isfinite(u):
                usual[klass].append(None)
                alone[klass].append(None)
                own[klass].append(0)
                continue
            leaid = inputs.places[i][0]
            own[klass].append(int(sum(climate.districts.get(leaid or "", {}).get(klass, ()))))
            pool = _pool(climate, klass, inputs.places[i], settings)
            bits |= FLAG_POOL_REGION[klass] if pool == "region" else 0
            bits |= FLAG_POOL_NONE[klass] if pool == "none" else 0
            b = float(inputs.snow_usual[i, k]) if inputs.snow_usual.size else math.nan
            shown, floor_at, clamp = shown_usual(
                float(inputs.p[i, k]), u, b, klass, settings, day, inputs.zones[i]
            )
            usual[klass].append(shown)
            alone[klass].append(floor_at)
            zone = inputs.zones[i]
            if zone not in even:
                even[zone] = forecast_adjust.even_factor(zone, settings)
            if even[zone] != 1.0:
                unsaid.append(f"district {i} {klass}: its usual snow weighs even snow {even[zone]}")
            bits |= FLAG_CLAMP[klass] if clamp else 0
        flags.append(bits)
        for klass, (closed, delayed, of) in record_of(
            inputs.artifact.districts.get(inputs.district_ids[i]), anchor
        ).items():
            record_rows[klass].append((i, closed, delayed, of))
    private = _private(inputs, (v0, v1, v2, v3), acted, capped, region_points, unsaid)
    levels = StandingLevels(
        **{
            klass: StandingLevel(
                prior=round(100 * _level(anchor.fits[klass], anchor.fits[klass].prior.alpha_mean)),
                fit=round(100 * _level(anchor.fits[klass], anchor.fits[klass].alpha)),
                now=now[j],
                storms=_storms(anchor.fits[klass]),
                q=round(anchor.fits[klass].q, 2),
                shrunk=_clauses(rates.shrunk_clauses if klass in rates.plausible.shrunk else ()),
                alpha=float(alphas[j]),
                tau=float(anchor.fits[klass].tau),
            )
            for j, klass in enumerate(CLASSES)
        }
    )
    body = StandingFile(
        schema_version=1,
        generated_at=generated,
        directory=directory,
        stamp="0" * 12,
        ref=StandingRefs(**{k: round(float(exposure.f_ref.get(k, 0.0)), 1) for k in CLASSES}),
        nodes=anchor.settings.nodes,
        winters=(_season(exposure.seasons[0]), _season(exposure.seasons[-1])),
        climate_winters=(_season(climate.seasons[0]), _season(climate.seasons[-1]))
        if climate is not None
        else (_season(exposure.seasons[0]), _season(exposure.seasons[-1])),
        record_winters=(inputs.artifact.training.seasons[0], inputs.artifact.training.seasons[-1]),
        climate_window="still_to_come"
        if climate is not None and climate.window == "still_to_come"
        else "whole",
        levels=levels,
        region_delta=StandingRegionDeltas(
            **{
                klass: tuple(
                    StandingRegionDelta.model_validate(
                        {"region": name, "delta": float(delta), "clipped": name in clipped[klass]}
                    )
                    for name, delta in sorted(anchor.deltas.get(klass, {}).items())
                    if delta != 0.0
                )
                for klass in CLASSES
            }
        ),
        winter=tuple(winter),
        flags=tuple(flags),
        usual=StandingSnow(**{k: tuple(v) for k, v in usual.items()}),
        alone=StandingSnow(**{k: tuple(v) for k, v in alone.items()}),
        own=StandingOwn(**{k: tuple(v) for k, v in own.items()}),
        region=StandingRegion(**{k: tuple(v) for k, v in region_rows.items()}),
        held=StandingHeld(**{k: tuple(v) for k, v in held_rows.items()}),
        held_clauses=_clauses(pull.first),
        record=StandingRecord(**{k: tuple(v) for k, v in record_rows.items()}),
        record_sum=StandingSums(**{k: _sum(v) for k, v in record_rows.items()}),
        record_full=_full_rows(inputs),
        private=private,
    )
    found = body.model_copy(update={"stamp": stamp_of(body)})
    return Built(
        file=found,
        served=v3[inputs.rows],
        private_served=v3[inputs.private_rows]
        if inputs.private_rows.size
        else np.zeros((0, 3), dtype=np.int64),
        regions=tuple(inputs.units[int(r)].region for r in inputs.rows),
        private_regions=tuple(inputs.units[int(r)].region for r in inputs.private_rows),
        refused=tuple(refused),
        unsaid=tuple(unsaid),
    )


def _full_rows(inputs: Inputs) -> StandingRecordFull:
    """Each deployed district's complete record rows, by class, in directory order."""
    rows: dict[str, list[tuple[int, int, int, int, int, int, int]]] = {k: [] for k in CLASSES}
    for i, leaid in enumerate(inputs.district_ids):
        for klass, row in sorted(inputs.full.get(leaid, {}).items()):
            rows[klass].append(
                (i, row.no_school, row.home, row.short, row.days, row.same100, row.winters)
            )
    return StandingRecordFull(**{k: tuple(v) for k, v in rows.items()})


@functools.cache
def full_records() -> Mapping[str, Mapping[str, FullRow]]:
    """Every state's committed complete records (``config/state-records.yaml``
    ``full_record``), each file checked by its pin, by LEAID and class; read once a process.

    Raises:
        StateRecordError: a file is missing or off its pin (:func:`full_records_read` is the
            pass's reader, which never raises).
        FullRecordError: a file does not read or add up.
    """
    from snowlight.predict import state_records  # noqa: PLC0415

    found: dict[str, dict[str, FullRow]] = {}
    for state in state_records.load().states.values():
        if state.full_record is None:
            continue
        data = state_records.read_derived(state, state.full_record.name)
        for row in read_record_file(data):
            found.setdefault(row.leaid, {})[row.kind] = row
    return found


def full_records_read(warn: Callable[[str], None]) -> Mapping[str, Mapping[str, FullRow]]:
    """:func:`full_records`, or none when a file is missing, off its pin or does not read: that
    is warned, the standing file then carries no ``record_full`` (every habit box keeps the
    lists' words) and nothing else in the pass changes, so a bad record file never stops it."""
    try:
        return full_records()
    except (ValueError, OSError) as error:  # StateRecordError and FullRecordError are ValueErrors
        warn(f"the complete records were not read, so no habit box shows one: {error}")
        return {}


def _storms(fit: ClassFit) -> int:
    return fit.ramp.storm_count if fit.ramp is not None else 0


def _clauses(names: Sequence[str]) -> tuple[PlausibilityClause, ...]:
    return tuple(PlausibilityClause(c) for c in names if c in (*CLAUSES, "district_max"))


def _sum(rows: Sequence[tuple[int, ...]]) -> tuple[int, int, int]:
    return (sum(r[1] for r in rows), sum(r[2] for r in rows), sum(r[3] for r in rows))


def _clipped(anchor: Anchor) -> dict[str, frozenset[str]]:
    """Per class, the regions whose delta hit the clip."""
    limit = anchor.settings.delta_strength * anchor.settings.delta_clip
    return {
        klass: frozenset(
            name
            for name, delta in anchor.deltas.get(klass, {}).items()
            if delta != 0.0 and abs(abs(delta) - limit) <= CLIP_EPS
        )
        for klass in CLASSES
    }


type Points = npt.NDArray[np.int64]


def _private(  # noqa: PLR0913, PLR0917 - the units' stages and the split
    inputs: Inputs,
    points: tuple[Points, Points, Points, Points],
    acted: Points,
    capped: npt.NDArray[np.bool_],
    region_points: Callable[[int, int], int],
    unsaid: list[str],
) -> PrivateStanding:
    """The private schools by distinct row (county exposure, region points, bits, holds). A
    school whose region moves a class other than the advisory one goes in ``unsaid``: its row
    holds the advisory part alone."""
    v0, v1, v2, v3 = points
    anchor = inputs.anchor
    rows: dict[tuple[object, ...], int] = {}
    table: list[tuple[tuple[float, float, float] | None, int, int]] = []
    held: dict[str, list[tuple[int, int, int, int, int]]] = {k: [] for k in CLASSES}
    record: dict[str, list[tuple[int, int, int, int]]] = {k: [] for k in CLASSES}
    of: list[int] = []
    for i, r in enumerate(inputs.private_rows.tolist()):
        unit = inputs.units[r]
        days, _ = anchor.exposure.of(unit.leaid, unit.county)
        shown = None if days is None else tuple(round(float(d), 1) for d in days)
        bits = PRIVATE_TROPICAL if anchor.exposure.has_tropical(unit.leaid, unit.county) else 0
        if capped[r]:
            bits |= sum(PRIVATE_CAPPED.values())
        region = region_points(r, CLASSES.index("advisory"))
        stages = tuple(
            (int(v1[r, j] - v0[r, j]), int(v2[r, j] - v1[r, j]), int(v3[r, j] - v2[r, j]))
            for j in range(len(CLASSES))
        )
        others = [region_points(r, j) for j in range(len(CLASSES)) if CLASSES[j] != "advisory"]
        if any(others):
            unsaid.append(f"private school {i}: a region part outside the advisory class")
        marks = tuple(int(acted[r, j]) for j in range(len(CLASSES)))
        key = (shown, region, bits, stages, marks, tuple(others))
        if key not in rows:
            rows[key] = len(table)
            table.append((shown, region, bits))  # type: ignore[arg-type]
            for j, klass in enumerate(CLASSES):
                if any(stages[j]) or marks[j]:
                    held[klass].append((rows[key], *stages[j], marks[j]))
        of.append(rows[key])
        school = inputs.private_ids[i]
        for klass, (closed, delayed, days_of) in record_of(
            inputs.artifact.private.get(school) if school is not None else None, anchor
        ).items():
            record[klass].append((i, closed, delayed, days_of))
    return PrivateStanding(
        rows=tuple(table),
        of=tuple(of),
        record=StandingRecord(**{k: tuple(v) for k, v in record.items()}),
        record_sum=StandingSums(**{k: _sum(v) for k, v in record.items()}),
        held=StandingHeld(**{k: tuple(v) for k, v in held.items()}),
    )


def stamp_of(found: StandingFile) -> str:
    """The first 12 hex digits of SHA-256 over the compact, key-sorted JSON of every field
    but ``generated_at`` and ``stamp``: a process start with nothing changed gives the same."""
    body = json.loads(found.to_json_bytes())
    body.pop("generated_at", None)
    body.pop("stamp", None)
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _level_of(alpha: float, tau: float, nodes: int, offset: float) -> float:
    z, w = _nodes(nodes)
    return float(sigmoid(alpha + offset + np.sqrt(2.0) * tau * z) @ w)


def guard(  # noqa: PLR0913, PLR0917 - the file, what it is checked against, the budgets
    built: Built,
    beta: float,
    offset: float,
    grid: Grid,
    raw_budget: int,
    gzip_budget: int,
) -> list[str]:
    """What is wrong with the file, from its own numbers only (``levels.alpha``, ``tau``,
    ``nodes``, ``region_delta``, ``winter``, ``ref``): every deployed district's and private
    row's start ``v0'`` with its holds must give the points served, each class's ``now`` its
    level at the middle exposure, each record sum its rows' sums, and the file must be within
    both budgets. Empty: write it."""
    found = built.file
    problems: list[str] = [f"no split for {unit}" for unit in built.refused]
    problems.extend(built.unsaid)
    data = found.to_json_bytes()
    packed = len(gzip.compress(data, compresslevel=9, mtime=0))
    if len(data) > raw_budget or packed > gzip_budget:
        problems.append(f"size {len(data):,} raw, {packed:,} gzip")
    levels = [getattr(found.levels, k) for k in CLASSES]
    refs = [getattr(found.ref, k) for k in CLASSES]
    deltas = [{d.region: d.delta for d in getattr(found.region_delta, k)} for k in CLASSES]
    cache: dict[tuple[int, float], int] = {}

    def start(j: int, days: Sequence[float] | None, region: str | None) -> int:
        o = deltas[j].get(region or "", 0.0)
        if days is not None:
            o += beta * -math.log((days[j] + offset) / (refs[j] + offset))
        key = (j, round(o, 12))
        if key not in cache:
            level = levels[j]
            value = _level_of(level.alpha, level.tau, found.nodes, o)
            cache[key] = round(100 * float(grid.round(np.array(value))))
        return cache[key]

    for j, level in enumerate(levels):
        if start(j, None, None) != level.now:
            problems.append(f"{CLASSES[j]}: now {level.now} is not its level")
    held = [{row[0]: row[1:4] for row in getattr(found.held, k)} for k in CLASSES]
    for i, days in enumerate(found.winter):
        for j in range(len(CLASSES)):
            stages = held[j].get(i, (0, 0, 0))
            if start(j, days, built.regions[i]) + sum(stages) != int(built.served[i, j]):
                problems.append(f"district {i} {CLASSES[j]}: its steps do not add up")
    private = found.private
    private_held = [{row[0]: row[1:4] for row in getattr(private.held, k)} for k in CLASSES]
    for s, row in enumerate(private.of):
        days = private.rows[row][0]
        for j in range(len(CLASSES)):
            stages = private_held[j].get(row, (0, 0, 0))
            if start(j, days, built.private_regions[s]) + sum(stages) != int(
                built.private_served[s, j]
            ):
                problems.append(f"private school {s} {CLASSES[j]}: its steps do not add up")
    for table, sums, who in (
        (found.record, found.record_sum, "districts"),
        (private.record, private.record_sum, "private schools"),
    ):
        for klass in CLASSES:
            if tuple(getattr(sums, klass)) != _sum(getattr(table, klass)):
                problems.append(f"{who} {klass}: the record sum is not its rows'")
    return problems[:20]

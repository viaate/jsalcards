"""The outlook on a serving pass (S7-F, spec-f s. 6 to 8; piece F3).

A pass with ``PREDICT_OUTLOOK`` shadow or on reads, for every deployed district and school day
before 05:00 local on that day, the class issued and the heads-up as rule D2 has them at the
pass (:func:`district_states`, from the pass's product log,
:class:`~snowlight.predict.alerts_live.ProductLog`), the slot of the pass in the district's
zone, and the bucket of the newest NDFD run that counts at the pass (at most 3 hours old), and
gives the outlook's chance (:func:`outlook_chances`): ``sum_c T(c) p_d(c)`` over the v3 rates
(the 05:00 record's, ``data/predict/model-f.json.gz``), through the one chance function
(:func:`snowlight.predict.outlook.chance`).

Where the outlook applies and moves the whole percent, the chance carries one ``outlook``
line (:class:`~snowlight.schemas.predictions.OutlookReason`): the base keeps its points (the
class issued's own rate, exactly the identity's), the line the rest. Its ``to`` is the class
whose term ``T(c) (p_d(c) - p_d(c0))`` is largest the way the points go, its ``share`` the raw
share of the cases counted (the cell ``like``) at the most specific place holding 20 nights or
more whose count of ``to`` is not zero, and its ``f`` the district's schools' least and most
of the forecast kind its bucket reads, rounded outward (true of every school).

Each of these rows gets the identity instead, the shipped issued-alerts-only chance with no
outlook line: no forecast run counts at the pass for its zone (the lead's decision on a stale
forecast, ``serve.forecast_stale: identity``), its bucket reads unknown, its forecast range
cannot be stated true of every school, or its own class has no rate (never a NaN chance:
the own-class guard before serving). The pass counts each in its line.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Final

import numpy as np
import numpy.typing as npt

from snowlight.predict import outlook as outlook_module
from snowlight.predict.alerts_live import LiveEvent, UgcIndex
from snowlight.predict.forecast_values import DistrictForecast, Forecasts
from snowlight.predict.geography import REGION_OF, state_of_leaid
from snowlight.predict.outlook import (
    C0_VALUES,
    CLASSES,
    LADDERS,
    QUIET,
    UNKNOWN,
    Outlook,
    OutlookMode,
    cell_index,
    chance,
)
from snowlight.predict.outlook_states import slot_at
from snowlight.predict.pool import SITUATION_INDEX
from snowlight.predict.serve import ServeModel, reached_by
from snowlight.predict.situations import (
    HeadsUp,
    Situation,
    WeatherClass,
    Window,
    district_class_from_counts,
    heads_up_strength,
    issued_counts,
)
from snowlight.schemas.predictions import (
    OUTLOOK_FEELS,
    OUTLOOK_HEADS_UPS,
    OUTLOOK_ICE,
    OUTLOOK_SNOW,
    OutlookReason,
)

type Ints = npt.NDArray[np.int64]
type Floats = npt.NDArray[np.float64]
type Bools = npt.NDArray[np.bool_]

NO_FORECAST: Final = -1
"""A district's bucket when no run was read for its zone."""
_WHOLE: Final = 100
WORDED_SHARE: Final = 0.5
"""The share of a district's schools the outlook's words say its class covers ("covers half of
X's schools", ``web/src/copy-chance.ts``): ``weather.covered_share`` must be it while the
outlook is shadow or on (a test holds the config to it, and the web's test holds its words)."""
_SCOPES: Final = ("state", "region", "nation")
_KIND_OF_LADDER: Final = (OUTLOOK_SNOW, OUTLOOK_ICE, OUTLOOK_FEELS)


@dataclass(frozen=True, slots=True)
class OutlookServe:
    """What the outlook serves from on a directory: the v3 rates as a serving model, ``T``,
    and each deployed district's place in ``T`` (its state's index, -1 for the nation's)."""

    rates: ServeModel
    outlook: Outlook
    state_index: Ints

    @classmethod
    def of(cls, rates: ServeModel, outlook: Outlook) -> "OutlookServe":
        """The outlook over ``rates`` (built from the v3 artifact's rates on the directory)."""
        entry = rates.artifact.districts
        index = {state: i for i, state in enumerate(outlook_module.STATES)}
        found = []
        for leaid in rates.directory.district_ids:
            state = entry[leaid].state if leaid in entry else state_of_leaid(leaid)
            found.append(index.get(state, -1) if state is not None else -1)
        return cls(rates, outlook, np.array(found, dtype=np.int64))


# --- the states at a moment ---------------------------------------------------------------------


def district_states(  # noqa: PLR0912, PLR0913, PLR0917 - the model, the events, the days, the rule
    model: ServeModel,
    events: Sequence[LiveEvent],
    ugcs: UgcIndex,
    days: Sequence[date],
    as_of: datetime,
    window: Window,
    share: float,
    heights: npt.NDArray[np.float64] | None = None,
    margin: float = 0.0,
) -> tuple[Ints, Ints]:
    """Each deployed district's class issued and heads-up per day at ``as_of`` under rule D2
    (:func:`~snowlight.predict.situations.issued_counts`), (districts, days) each: the
    strongest class (heads-up) covering, with stronger ones, ``share`` of its eligible
    schools. ``heights`` and ``margin`` as :func:`~snowlight.predict.serve.school_classes`
    (``None``: every alert reaches its whole zones, as the history counts them)."""
    points = model.directory.points
    school_zone = np.full(len(points), -1, dtype=np.int64)
    names = sorted(set(model.time_zone))
    zone_index = {name: i for i, name in enumerate(names)}
    for index, schools in enumerate(model.eligible):
        school_zone[schools] = zone_index[model.time_zone[index]]
    weather = np.zeros((len(points), len(days)), dtype=np.int64)
    strength = np.zeros((len(points), len(days)), dtype=np.int64)
    for item in events:
        given_class = item.event.weather
        given_heads = item.event.heads_up
        if given_class is None and given_heads is HeadsUp.NONE:
            continue
        reached, _unknown = reached_by(item, ugcs, heights, margin)
        reached = reached[school_zone[reached] >= 0] if reached.size else reached
        if not reached.size:
            continue
        for z, name in enumerate(names):
            group = reached[school_zone[reached] == z]
            if not group.size:
                continue
            for d, day in enumerate(days):
                if not issued_counts(item.event, day, name, window, as_of):
                    continue
                if given_class is not None:
                    weather[group, d] = np.maximum(weather[group, d], int(given_class))
                if given_heads is not HeadsUp.NONE:
                    found = heads_up_strength(int(given_heads))
                    strength[group, d] = np.maximum(strength[group, d], found)
    c0 = np.zeros((len(model.eligible), len(days)), dtype=np.int64)
    heads = np.zeros((len(model.eligible), len(days)), dtype=np.int64)
    top = heads_up_strength(int(HeadsUp.WINTER_STORM_WATCH))
    for index, schools in enumerate(model.eligible):
        if not schools.size:
            continue
        for d in range(len(days)):
            classes = weather[schools, d]
            if classes.any():
                covered = np.bincount(classes, minlength=CLASSES)
                c0[index, d] = int(
                    district_class_from_counts(covered.tolist(), schools.size, share)
                )
            strengths = strength[schools, d]
            if strengths.any():
                covered = np.bincount(strengths, minlength=top + 1)
                found = int(district_class_from_counts(covered.tolist(), schools.size, share))
                heads[index, d] = 0 if found == 0 else len(HeadsUp) - found
    return c0, heads


# --- the outlook's chance and its line -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Inputs:
    """One pass's outlook inputs, (deployed districts, days) each."""

    c0: Ints
    heads: Ints
    after: Bools
    """Whether the day follows a closing (the day after, for ``none`` and ``advisory``)."""
    slot: Ints
    """The pass's slot in each district's zone (0 from 05:00 on the day: the identity)."""
    bucket: Ints
    """The forecast's bucket code (0-13), or :data:`NO_FORECAST`."""
    forecasts: Forecasts
    days: tuple[date, ...]


@dataclass(slots=True)
class Chances:
    """The outlook's chances, (deployed districts, days) each, and the lines."""

    p: Floats
    """The chance of no school as published."""
    delay: Floats
    base: Floats
    """The identity: the class issued's own published chance (the base's)."""
    base_delay: Floats
    """The identity's chance of a delay."""
    applied: Bools
    """Whether the outlook moved the chance (a line goes with it)."""
    lines: dict[tuple[int, int], OutlookReason] = field(default_factory=dict)
    stale: int = 0
    """Rows before 05:00 with no warning issued whose zone had no forecast run counting."""
    unknown: int = 0
    """Rows whose forecast bucket read unknown."""
    unsaid: int = 0
    """Rows whose forecast range cannot be stated true of every school."""
    no_rate: int = 0
    """Rows whose own class has no rate (the guard before serving: no number is published)."""
    fell_back: int = 0
    """Rows the chance function gave the identity (``T`` weighs a class with no rate)."""
    run_time: datetime | None = None
    """The newest forecast run read (``None``: none)."""


def class_matrix(rates: Floats, after: Bools) -> Floats:
    """Each row's rate under each class (rows, classes) from a (rows, situations) table: the
    day after a closing counts for none and advisory only."""
    plain = np.array(
        [SITUATION_INDEX[Situation.of(WeatherClass(c), after=False).key] for c in range(CLASSES)]
    )
    later = np.array(
        [SITUATION_INDEX[Situation.of(WeatherClass(c), after=True).key] for c in range(CLASSES)]
    )
    columns = np.where(np.asarray(after, dtype=np.bool_)[:, None], later[None], plain[None])
    rows = np.arange(rates.shape[0])[:, None]
    return np.asarray(rates[rows, columns], dtype=np.float64)


def _floor_to(value: float, step: float) -> float:
    return math.floor(value / step + 1e-9) * step


def _ceil_to(value: float, step: float) -> float:
    return math.ceil(value / step - 1e-9) * step


def f_range(bucket: int, found: DistrictForecast | None) -> tuple[int, float, float] | None:
    """The line's ``f`` for a district at forecast ``bucket``: ``[kind, low, high]``, the
    district's deciding schools' least and most of the kind its bucket reads, rounded outward
    (whole inches of snow, hundredths of ice, whole degrees of feel), so the range holds every
    school. ``None`` when the bucket is quiet (the line says so) or the values were not all
    read (then the row gets the identity: nothing false is ever said).

    Raises:
        ValueError: ``bucket`` is not a forecast's (quiet, a ladder's, or unknown).
    """
    if bucket == QUIET:
        return None
    ladder = next((k for k, items in enumerate(LADDERS) if bucket in items), None)
    if ladder is None:
        raise ValueError(f"no forecast range for bucket {bucket}")
    kind = _KIND_OF_LADDER[ladder]
    if found is None:
        return None
    pairs = {
        OUTLOOK_SNOW: (found.snow_low, found.snow_high, 1.0),
        OUTLOOK_ICE: (found.ice_low, found.ice_high, 0.01),
        OUTLOOK_FEELS: (found.feels_low, found.feels_high, 1.0),
    }
    low, high, step = pairs[kind]
    if low is None or high is None or not (math.isfinite(low) and math.isfinite(high)):
        return None
    lo, hi = _floor_to(low, step), _ceil_to(high, step)
    if kind == OUTLOOK_ICE:
        return kind, round(max(lo, 0.0), 2), round(hi, 2)
    if kind == OUTLOOK_SNOW:
        return kind, float(max(round(lo), 0)), float(round(hi))
    return kind, float(round(lo)), float(round(hi))


def says(outlook: Outlook, cell: int, state: int, to: int) -> tuple[int, int] | None:
    """The scope (0 state, 1 region, 2 nation) and the whole-percent share a line says for
    ``to`` in ``cell`` at ``state`` (-1: the nation): the most specific place whose merged cell
    holds 20 nights or more (:meth:`~snowlight.predict.outlook.Outlook.says`), moving up while
    its raw count of ``to`` is zero (a share of none would say nothing of the cases that moved
    the chance); the share true of the raw count: 100 exactly when every case counted ended in
    ``to`` (said "in every case"), else between 1 and 99 (an exact percent rounds to it; 99 is
    said, as "almost every case", for 98.5% or more short of all, and 1, as "almost no case",
    only under 1.5%). ``None`` when no place counts ``to`` at all."""
    options: list[tuple[int, int, Floats]] = []
    if state >= 0:
        region = int(outlook_module.REGION_OF_STATE[state])
        options.append((0, int(outlook.nights_state[state, cell]), outlook.state[state, cell]))
        options.append((1, int(outlook.nights_region[region, cell]), outlook.region[region, cell]))
    options.append((2, int(outlook.nights_nation[cell]), outlook.nation[cell]))
    started = False
    for scope, nights, counts in options:
        if not started and scope < 2 and nights < outlook_module.MIN_NIGHTS:  # noqa: PLR2004
            continue
        started = True
        total = float(counts.sum())
        hit = float(counts[to])
        if total <= 0 or hit <= 0:
            continue
        if hit >= total:
            return scope, _WHOLE
        share = min(max(round(_WHOLE * hit / total), 1), _WHOLE - 1)
        return scope, int(share)
    return None


def outlook_chances(  # noqa: PLR0915 - the model, the inputs, the limits and the words
    serve: OutlookServe,
    inputs: Inputs,
    *,
    floor: float,
    ceiling: float,
    unsaid_identity: bool = True,
) -> Chances:
    """The outlook's chances and lines for every deployed district and day (see the module
    docstring). ``unsaid_identity``: a row whose forecast range cannot be stated gets the
    identity (the serving rule; the record keeps the same rule, so shadow is what on would
    show)."""
    rates = serve.rates
    p_table = rates.p_rate if rates.p_rate.size else rates.p
    q_table = rates.q_rate if rates.q_rate.size else rates.q
    districts, count = inputs.c0.shape
    out_p = np.zeros((districts, count))
    out_q = np.zeros((districts, count))
    out_base = np.zeros((districts, count))
    out_base_q = np.zeros((districts, count))
    applied = np.zeros((districts, count), dtype=np.bool_)
    found = Chances(out_p, out_q, out_base, out_base_q, applied)
    rows = np.arange(districts)
    states = serve.state_index
    read = [
        given.run_time
        for by_district in inputs.forecasts.by_day.values()
        for given in by_district.values()
        if given.run_time is not None
    ]
    found.run_time = max(read) if read else None
    t_state = serve.outlook.t_state()
    for d in range(count):
        c0 = inputs.c0[:, d].astype(np.int64)
        p_class = class_matrix(p_table, inputs.after[:, d])
        q_class = class_matrix(q_table, inputs.after[:, d])
        own = p_class[rows, c0]
        no_rate = ~np.isfinite(own) | ~np.isfinite(q_class[rows, c0])
        bucket = inputs.bucket[:, d]
        before = (inputs.slot[:, d] > 0) & (c0 < C0_VALUES)
        stale = before & (bucket == NO_FORECAST)
        unknown = before & (bucket == UNKNOWN)
        usable = before & (bucket >= 0) & (bucket != UNKNOWN) & ~no_rate
        ranges: dict[int, tuple[int, float, float] | None] = {}
        for i in np.flatnonzero(usable).tolist():
            given = inputs.forecasts.get(inputs.days[d], i)
            ranges[i] = f_range(int(bucket[i]), given)
            if unsaid_identity and ranges[i] is None and int(bucket[i]) != QUIET:
                usable[i] = False
                found.unsaid += 1
        found.stale += int(stale.sum())
        found.unknown += int(unknown.sum())
        found.no_rate += int(no_rate.sum())
        table = np.zeros((districts, CLASSES))
        if usable.any():
            where = np.flatnonzero(usable)
            table[where] = serve.outlook.distribution(
                inputs.slot[where, d],
                c0[where],
                inputs.heads[where, d],
                bucket[where],
                states[where],
                table=t_state,
            )
        safe_p = np.where(np.isfinite(p_class), p_class, np.nan)
        safe_c0 = np.where(no_rate, 0, c0)
        result = chance(
            safe_p,
            q_class,
            np.where(no_rate, WeatherClass.SNOW_WARNING.value, c0),
            table,
            usable,
            mode=OutlookMode.ON,
            floor=floor,
            ceiling=ceiling,
        )
        identity = chance(
            safe_p,
            q_class,
            np.where(no_rate, WeatherClass.SNOW_WARNING.value, c0),
            None,
            np.zeros(districts, dtype=np.bool_),
            mode=OutlookMode.ON,
            floor=floor,
            ceiling=ceiling,
        )
        found.fell_back += int(result.fell_back.sum())
        out_base[:, d] = np.where(no_rate, np.nan, identity.p)
        out_base_q[:, d] = np.where(no_rate, np.nan, identity.delay)
        out_p[:, d] = np.where(no_rate, np.nan, result.p)
        out_q[:, d] = np.where(no_rate, np.nan, result.delay)
        for i in np.flatnonzero(result.outlook).tolist():
            points = round(float(result.p[i]) * _WHOLE) - round(float(identity.p[i]) * _WHOLE)
            line = None
            if points:
                line = _line(serve, int(safe_c0[i]), i, d, inputs, p_class[i], table[i], points,
                             ranges.get(i))  # fmt: skip
            if line is None:
                # No line can say it: the identity, never a chance its sum does not explain.
                out_p[i, d], out_q[i, d] = identity.p[i], identity.delay[i]
                continue
            applied[i, d] = True
            found.lines[(i, d)] = line
    return found


def _line(  # noqa: PLR0913, PLR0917 - one row's state, rates, weights and words
    serve: OutlookServe,
    c0: int,
    i: int,
    d: int,
    inputs: Inputs,
    rates: Floats,
    weights: Floats,
    points: int,
    f: tuple[int, float, float] | None,
) -> OutlookReason | None:
    """The row's ``outlook`` line, or ``None`` when no class moved it the way it went or no
    place counts that class (then the row keeps the identity)."""
    sign = 1 if points > 0 else -1
    terms = np.where((weights > 0) & np.isfinite(rates), weights * (rates - rates[c0]), 0.0)
    terms[c0] = 0.0
    to = int(np.argmax(sign * terms))
    if sign * terms[to] <= 0:
        return None
    slot = int(inputs.slot[i, d])
    heads = int(inputs.heads[i, d])
    bucket = int(inputs.bucket[i, d])
    cell = cell_index(slot, c0, heads, bucket)
    said = says(serve.outlook, cell, int(serve.state_index[i]), to)
    if said is None:
        return None
    like = serve.outlook.likes[cell]
    return OutlookReason(
        kind="outlook",
        points=points,
        now=c0 * OUTLOOK_HEADS_UPS + heads,
        f=f,
        like=(like.low, like.high, like.heads),
        to=to,
        share=said[1],
        scope=said[0],
    )


def inputs_of(  # noqa: PLR0913, PLR0917 - the model, the states, the days, the forecasts, when
    model: ServeModel,
    c0: Ints,
    heads: Ints,
    after: Bools,
    days: Sequence[date],
    forecasts: Forecasts,
    now: datetime,
) -> Inputs:
    """The outlook inputs of a pass at ``now``: each district's slot in its zone, and its
    forecast bucket (:data:`NO_FORECAST` where its zone's forecast was not read)."""
    districts = len(model.time_zone)
    slot = np.zeros((districts, len(days)), dtype=np.int64)
    bucket = np.full((districts, len(days)), NO_FORECAST, dtype=np.int64)
    slots: dict[tuple[str, date], int] = {}
    for i, zone in enumerate(model.time_zone):
        for d, day in enumerate(days):
            key = (zone, day)
            if key not in slots:
                slots[key] = slot_at(day, zone, now)
            slot[i, d] = slots[key]
            given = forecasts.get(day, i)
            if given is not None:
                bucket[i, d] = given.code
    return Inputs(c0, heads, after, slot, bucket, forecasts, tuple(days))


def region_name(state: int) -> str | None:
    """The climate region of a state index (for reports)."""
    if state < 0:
        return None
    return REGION_OF.get(outlook_module.STATES[state])


def scope_name(scope: int) -> str:
    """``state``, ``region`` or ``nation``."""
    return _SCOPES[scope]


def after_rows(
    after_sets: Mapping[date, frozenset[int]], days: Sequence[date], districts: int
) -> Bools:
    """The day-after flags, (districts, days), from each day's set of districts that followed a
    closing (the pass's own sets, so the outlook and the file agree)."""
    found = np.zeros((districts, len(days)), dtype=np.bool_)
    for d, day in enumerate(days):
        members = [i for i in after_sets.get(day, frozenset()) if 0 <= i < districts]
        found[members, d] = True
    return found

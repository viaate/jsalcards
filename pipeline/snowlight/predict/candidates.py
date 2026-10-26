"""The tuning candidates (calc-research plan sec. 2; the tune-v3 lane): their inputs as known
at 21:00 the evening before, their levels and columns, and the candidate bases. Internal.

Every rule here is the pre-registered one (``docs/research/candidates-preregistration.md``),
fixed before any candidate was scored. Nothing a pass serves reads this module: a candidate
the archive does not veto waits for the live shadow behind :data:`SHADOW` (every switch off).

* **C2a**, the rain/snow line at 7 AM, a term (:func:`c2_columns`): on advisory and winter storm
  warning days with snow in the window, warm at 7 AM (32 F or more, a second step from 34 F)
  only takes away; a mixed type takes away when warm, adds when cold, and is free in between.
* **C2c**, the same columns from the 5 AM airport report, on the 05:00 labels.
* **C3**, timing (:func:`timing_level`): snow done overnight or ending in the early morning
  only takes away, mostly afternoon snow is free, snow through the school day is the
  reference; "ending in the early morning" only adds to the delay chance; and a gate keeps a
  snow term from taking away once the alert has begun (:func:`began_by_snapshot`).
* **C4**, amounts against what is normal there (:func:`c4_level`): the snow terms read the
  district's 21:00 bucket against its own (pooled) snowy nights instead of the nation's band.
* **C1** with **C2b**, a new base (:func:`level_rule_base`): a state, else a region, serves its
  own record when it has level support; on snow days the rate moves by the cold or warm
  record's log odds against the level's whole record.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.predict.pool import Floats, Ints, Rows, level_records
from snowlight.predict.situations import SITUATIONS, WeatherClass
from snowlight.predict.terms import UNKNOWN, Shape, Term

type Bools = npt.NDArray[np.bool_]
type Bound = tuple[float | None, float | None]

SNOW_CLASSES: Final = (int(WeatherClass.ADVISORY), int(WeatherClass.SNOW_WARNING))
"""The classes the C2 and C3 columns apply to (advisory, winter storm warning)."""

ADDS: Final[Bound] = (0.0, None)
TAKES: Final[Bound] = (None, 0.0)
FREE: Final[Bound] = (None, None)

# --- C2: temperature and type -------------------------------------------------------------------

COLD_BELOW: Final = 32.0
"""F: the freezing point."""
WARM_FROM: Final = 34.0
"""F: from R3's coastal airport readings (33-34 F at EWR and ISP on 2023-02-28, 33-37 F at
six stations on 2023-03-14)."""
COLD: Final = 0
NEAR: Final = 1
WARM: Final = 2
MIX_LIQUID: Final = 0.10
"""Inches of liquid in the window from which the snow-to-liquid test reads a mix."""
MIX_RATIO: Final = 5.0
"""Snow under this many times the liquid reads as rain or sleet in the mix (about 10 to 1 is
the common rule of thumb for snow)."""
MIX_WORDS: Final = ("w_sleet", "w_freezing_rain", "w_freezing_drizzle", "w_rain", "w_mix")
"""The alert's type flags (as of 21:00) that read as a mix."""
OBS_MIX: Final = ("rain", "sleet", "freezing", "drizzle", "mix")
"""The 5 AM report's flags that read as a mix (C2c)."""


def temperature_level(value: float | None) -> int:
    """Cold under 32 F, near from 32 to under 34 F, warm from 34 F; unknown when not given."""
    if value is None or math.isnan(value):
        return UNKNOWN
    if value < COLD_BELOW:
        return COLD
    return NEAR if value < WARM_FROM else WARM


def mixed_by_amounts(liquid: float, snow: float) -> bool:
    """A mix by the amounts: 0.10 in of liquid or more with snow under 5 times the liquid
    (False when either is not given)."""
    if math.isnan(liquid) or math.isnan(snow):
        return False
    return liquid >= MIX_LIQUID and snow < MIX_RATIO * liquid


C2_COLUMNS: Final = ("warm_32", "warm_34", "mixed_warm", "mixed_cold", "mixed_near")
C2_BOUNDS: Final[tuple[Bound, ...]] = (TAKES, TAKES, TAKES, ADDS, FREE)


def c2_columns(own: Ints, temperature: Ints, mixed: Bools, snow: Bools) -> Floats:
    """C2's five columns (rows, 5): on snow-class rows (``own``) with snow forecast and a known
    temperature level; the cold reference adds nothing."""
    on = np.isin(own, np.array(SNOW_CLASSES)) & snow & (temperature >= 0)
    found = np.zeros((own.size, len(C2_COLUMNS)))
    found[:, 0] = on & (temperature >= NEAR)
    found[:, 1] = on & (temperature == WARM)
    found[:, 2] = on & mixed & (temperature == WARM)
    found[:, 3] = on & mixed & (temperature == COLD)
    found[:, 4] = on & mixed & (temperature == NEAR)
    return found


# --- C3: timing ---------------------------------------------------------------------------------

BAND_EDGES: Final = (1.0, 7.0, 13.0)
"""Local hours on the school day where early morning, the school day and the afternoon start
(overnight is before 1 AM, the evening before included)."""
BANDS: Final = ("overnight", "early morning", "school day", "afternoon")
PERIOD_ENDS: Final = (6, 12, 18, 24)
"""The 6-hour periods read for timing: ending these hours after 00 UTC on the school day."""
DONE_SHARE: Final = 0.9
"""Snow this share or more before a band's end counts as done by then."""
AFTERNOON_SHARE: Final = 0.5
SCHOOL_DAY: Final = 0
DONE_OVERNIGHT: Final = 1
ENDS_EARLY: Final = 2
AFTERNOON: Final = 3
SNAPSHOT: Final = time(21, 0)


def band_of(hours: float) -> int:
    """The band of a moment ``hours`` after local midnight starting the school day."""
    return sum(hours >= edge for edge in BAND_EDGES)


def period_weights(day: date, zone: str, end: int) -> tuple[float, ...]:
    """How a 6-hour period ending ``end`` hours after 00 UTC on ``day`` splits over the local
    bands of ``day`` in ``zone``: all to the band holding most of its hours, half to each when
    split 3 and 3."""
    tz = ZoneInfo(zone)
    midnight = datetime.combine(day, time(0), tzinfo=tz)
    stop = datetime.combine(day, time(0), tzinfo=UTC) + timedelta(hours=end)
    counts = [0] * len(BANDS)
    for hour in range(6):
        middle = stop - timedelta(hours=6) + timedelta(hours=hour, minutes=30)
        counts[band_of((middle - midnight).total_seconds() / 3600.0)] += 1
    most = max(counts)
    winners = [i for i, count in enumerate(counts) if count == most]
    return tuple(1.0 / len(winners) if i in winners else 0.0 for i in range(len(BANDS)))


def snow_shares(day: date, zone: str, snow: Sequence[float]) -> tuple[float, ...] | None:
    """The share of the forecast snow (periods :data:`PERIOD_ENDS`) in each band, or ``None``
    when no snow is forecast or none is given."""
    shares = [0.0] * len(BANDS)
    total = 0.0
    for end, amount in zip(PERIOD_ENDS, snow, strict=True):
        if math.isnan(amount) or amount <= 0:
            continue
        total += amount
        for band, weight in enumerate(period_weights(day, zone, end)):
            shares[band] += weight * amount
    if total <= 0:
        return None
    return tuple(value / total for value in shares)


def timing_level(end_hours: float, shares: Sequence[float] | None) -> int:
    """C3's level from the alert's end (hours after local midnight starting the school day, as
    of 21:00; NaN: no alert or no end) and the snow's band shares."""
    ends = not math.isnan(end_hours)
    if (ends and end_hours <= BAND_EDGES[0]) or (shares is not None and shares[0] >= DONE_SHARE):
        return DONE_OVERNIGHT
    if (ends and end_hours <= BAND_EDGES[1]) or (
        shares is not None and shares[0] + shares[1] >= DONE_SHARE
    ):
        return ENDS_EARLY
    if shares is not None and shares[3] > AFTERNOON_SHARE:
        return AFTERNOON
    if shares is None and not ends:
        return UNKNOWN
    return SCHOOL_DAY


C3_COLUMNS: Final = ("done_overnight", "ends_early", "afternoon")
C3_BOUNDS: Final[tuple[Bound, ...]] = (TAKES, TAKES, FREE)
C3_DELAY_COLUMNS: Final = ("ends_early_delay",)
C3_DELAY_BOUNDS: Final[tuple[Bound, ...]] = (ADDS,)


def c3_columns(own: Ints, timing: Ints) -> Floats:
    """C3's three columns (rows, 3) on snow-class rows."""
    on = np.isin(own, np.array(SNOW_CLASSES))
    found = np.zeros((own.size, len(C3_COLUMNS)))
    found[:, 0] = on & (timing == DONE_OVERNIGHT)
    found[:, 1] = on & (timing == ENDS_EARLY)
    found[:, 2] = on & (timing == AFTERNOON)
    return found


def c3_delay_columns(own: Ints, timing: Ints) -> Floats:
    """C3's delay column (rows, 1): ending in the early morning, on snow-class rows."""
    return np.asarray(
        (np.isin(own, np.array(SNOW_CLASSES)) & (timing == ENDS_EARLY))[:, None], dtype=np.float64
    )


def local_hours(moment: datetime | None, day: date, zone: str) -> float:
    """Hours from local midnight starting ``day`` in ``zone`` to ``moment`` (NaN: none)."""
    if moment is None:
        return math.nan
    midnight = datetime.combine(day, time(0), tzinfo=ZoneInfo(zone))
    return (moment - midnight).total_seconds() / 3600.0


def began_by_snapshot(moment: datetime | None, day: date, zone: str) -> bool:
    """Whether the alert had begun by 21:00 local the evening before ``day``."""
    if moment is None:
        return False
    snapshot = datetime.combine(day - timedelta(days=1), SNAPSHOT, tzinfo=ZoneInfo(zone))
    return moment <= snapshot


# --- C4: amounts against the place's own snowy nights -----------------------------------------

BELOW_MOST: Final = 0
TYPICAL: Final = 1
ABOVE_MOST: Final = 2
FAR_ABOVE: Final = 3
MOST: Final = 0.5
FAR: Final = 0.9
CLIMATE_MIN_NIGHTS: Final = 20
"""Snowy nights a place needs for its own climate; fewer pools up to the state, region, nation."""
SNOW_BUCKETS: Final = 5
"""The forecast history's snow codes 1 to 5."""
C4_SHAPES: Final[Mapping[Term, Shape]] = {
    Term.SNOW_ADVISORY: Shape(6, TYPICAL, TYPICAL),
    Term.SNOW_STORM: Shape(6, 0, TYPICAL),
}
"""C4's snow terms: 0 on typical, steps above; the advisory term takes away below most, the
warning term only adds (as piece 3's)."""


def c4_level(bucket: int, climate: Floats) -> int:
    """C4's level of a 21:00 snow bucket ``bucket`` (0 to 5; negative: unknown) against a
    place's snowy nights by bucket (``climate``, buckets 1 to 5)."""
    total = float(climate.sum())
    if bucket < 0 or total <= 0:
        return UNKNOWN
    lower = float(climate[: max(bucket - 1, 0)].sum()) / total
    higher = float(climate[bucket:].sum()) / total
    if higher > MOST:
        return BELOW_MOST
    if lower > FAR:
        return FAR_ABOVE
    if lower > MOST:
        return ABOVE_MOST
    return TYPICAL


@dataclass(frozen=True, slots=True)
class Climate:
    """Snowy 21:00 nights by bucket: per district, state, region and the nation."""

    district: Mapping[str, Floats]
    state: Mapping[str, Floats]
    region: Mapping[str, Floats]
    nation: Floats

    def of(self, district: str, state: str | None, region: str | None) -> Floats:
        """The climate a district reads: its own with :data:`CLIMATE_MIN_NIGHTS` snowy nights,
        else its state's, its region's, the nation's."""
        for found in (
            self.district.get(district),
            None if state is None else self.state.get(state),
            None if region is None else self.region.get(region),
        ):
            if found is not None and found.sum() >= CLIMATE_MIN_NIGHTS:
                return found
        return self.nation


def season_counts(codes: pl.DataFrame) -> pl.DataFrame:
    """Snowy 21:00 nights (codes 1 to 5) by season, district and code, from the 21:00 codes
    (district, day, code)."""
    from snowlight.predict.calendar import season_of  # noqa: PLC0415

    kept = codes.filter(pl.col("code").is_between(1, SNOW_BUCKETS))
    return (
        kept.with_columns(
            pl.col("day").map_elements(season_of, return_dtype=pl.Int64).alias("season")
        )
        .group_by("season", "district", "code")
        .len()
    )


def climate_of(
    counts: pl.DataFrame,
    seasons: Sequence[int],
    state_of: Mapping[str, str | None],
    region_of: Mapping[str, str],
) -> Climate:
    """The climate from the snowy nights of ``seasons`` only (:func:`season_counts`)."""
    kept = counts.filter(pl.col("season").is_in(list(seasons)))
    district: dict[str, Floats] = {}
    for name, code, count in kept.select("district", "code", "len").iter_rows():
        district.setdefault(name, np.zeros(SNOW_BUCKETS))[int(code) - 1] += count
    state: dict[str, Floats] = {}
    region: dict[str, Floats] = {}
    nation = np.zeros(SNOW_BUCKETS)
    for name, found in district.items():
        nation += found
        where = state_of.get(name)
        if where is None:
            continue
        state.setdefault(where, np.zeros(SNOW_BUCKETS))[:] += found
        if where in region_of:
            region.setdefault(region_of[where], np.zeros(SNOW_BUCKETS))[:] += found
    return Climate(district, state, region, nation)


# --- C1 and C2b: the level rule and the split --------------------------------------------------

SPLIT_STRENGTH: Final = 8.0
"""How many days of the level's whole record a kind's rate is shrunk with (R3's state rate
strength)."""
KIND_UNKNOWN: Final = -1
KIND_COLD: Final = 0
KIND_WARM: Final = 1


def kind_of(temperature: Ints, mixed: Bools) -> Ints:
    """C2b's kind: cold (under 32 F, not mixed), warm or mixed (the rest with a known
    temperature), unknown."""
    cold = (temperature == COLD) & ~mixed
    known = np.where(cold, KIND_COLD, KIND_WARM)
    return np.where(temperature < 0, KIND_UNKNOWN, known).astype(np.int64)


def _logit(p: Floats) -> Floats:
    return np.asarray(np.log(p / (1 - p)), dtype=np.float64)


def _sigmoid(x: Floats) -> Floats:
    return np.asarray(1.0 / (1.0 + np.exp(-x)), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class Units:
    """Each row's state and region unit (-1: none)."""

    state: Ints
    region: Ints


TIERS: Final = ("state", "region", "nation")
"""The levels C1a serves (state, region) and C2b splits at (state, region, nation), by index."""
NO_TIER: Final = -1


@dataclass(frozen=True, slots=True)
class LevelRule:
    """C1a with C2b on every target row (:func:`level_rule`)."""

    p: Floats
    """The new unrounded chance."""
    served: Bools
    """Where C1a served a state or region record."""
    moved: Bools
    """Where C2b's split moved the rate."""
    served_tier: Ints
    """The level C1a served (index in :data:`TIERS`; :data:`NO_TIER`: none)."""
    split_tier: Ints
    """The level C2b split at (index in :data:`TIERS`; :data:`NO_TIER`: none)."""


type LevelSource = Callable[[int], tuple[Rows, Units, Ints, Ints]]
"""``source(season)``: the rows a target row of that season counts (its fold labels), their
units, kinds and day numbers."""


def _unit_pairs(
    part_units: Units, units: Units, part: int, rows: int
) -> tuple[tuple[Ints, Ints], ...]:
    """Per tier of :data:`TIERS`, (the targets' unit, the sources' unit); the nation is one unit."""
    nation = (np.zeros(part, np.int64), np.zeros(rows, np.int64))
    return ((part_units.state, units.state), (part_units.region, units.region), nation)


def level_rule(  # noqa: PLR0913, PLR0917 - the targets, their base and units, the sources
    target: Rows,
    target_units: Units,
    target_kind: Ints,
    base_raw: Floats,
    source: LevelSource,
    floor: float,
    ceiling: float,
) -> LevelRule:
    """C1a with C2b on every ``target`` row. ``base_raw`` is today's unrounded chance;
    ``source(season)`` gives the rows a row of that season counts (its fold labels), their
    units, kinds and day numbers. Rows of a class with no alert keep today's chance, and so
    does every row where no level qualifies."""
    found = base_raw.copy()
    served = np.zeros(len(target), dtype=np.bool_)
    moved = np.zeros(len(target), dtype=np.bool_)
    served_tier = np.full(len(target), NO_TIER, dtype=np.int64)
    split_tier = np.full(len(target), NO_TIER, dtype=np.int64)
    weather_of = np.array([int(item.weather) for item in SITUATIONS], dtype=np.int64)
    alert = weather_of[target.situation] > 0
    snow = np.isin(weather_of[target.situation], np.array(SNOW_CLASSES))
    for season in sorted(set(target.season.tolist())):
        mine = target.season == season
        rows, units, kinds, days = source(season)
        part = target.subset(mine)
        part_units = Units(target_units.state[mine], target_units.region[mine])
        pairs = _unit_pairs(part_units, units, len(part), len(rows))
        rate = np.full(int(mine.sum()), np.nan)
        tier_served = np.full(int(mine.sum()), NO_TIER, dtype=np.int64)
        for tier, (target_unit, source_unit) in enumerate(pairs[:2]):
            record = level_records(part, target_unit, rows, source_unit, days)
            take = np.isnan(rate) & record.supported
            rate[take] = record.rate[take]
            tier_served[take] = tier
        c1 = alert[mine] & ~np.isnan(rate)
        value = found[mine]
        value[c1] = np.clip(rate[c1], floor, ceiling)
        shift = np.zeros(value.size)
        done = np.zeros(value.size, dtype=np.bool_)
        tier_split = np.full(value.size, NO_TIER, dtype=np.int64)
        kind = target_kind[mine]
        for tier, (target_unit, source_unit) in enumerate(pairs):
            whole = level_records(part, target_unit, rows, source_unit, days)
            for k in (KIND_COLD, KIND_WARM):
                own = level_records(part, target_unit, rows, source_unit, days, kinds == k)
                take = snow[mine] & (kind == k) & ~done & own.supported
                r = np.clip(whole.rate[take], floor, ceiling)
                r_k = (own.y[take] + SPLIT_STRENGTH * r) / (own.n[take] + SPLIT_STRENGTH)
                shift[take] = _logit(np.clip(r_k, floor, ceiling)) - _logit(r)
                tier_split[take] = tier
                done |= take
        ok = ~np.isnan(value)
        value[ok] = _sigmoid(_logit(np.clip(value[ok], 1e-6, 1 - 1e-6)) + shift[ok])
        found[mine] = value
        served[mine] = c1
        moved[mine] = done & (shift != 0)
        served_tier[mine] = np.where(c1, tier_served, NO_TIER)
        split_tier[mine] = np.where(done & (shift != 0), tier_split, NO_TIER)
    return LevelRule(found, served, moved, served_tier, split_tier)


def level_rule_base(  # noqa: PLR0913, PLR0917 - the targets, their base and units, the sources
    target: Rows,
    target_units: Units,
    target_kind: Ints,
    base_raw: Floats,
    source: LevelSource,
    floor: float,
    ceiling: float,
) -> tuple[Floats, Bools, Bools]:
    """:func:`level_rule` as (the new unrounded chance, where C1a served a state or region
    record, where C2b moved it)."""
    found = level_rule(target, target_units, target_kind, base_raw, source, floor, ceiling)
    return found.p, found.served, found.moved


def level_dates(  # noqa: PLR0913, PLR0917 - the rule, its targets and sources, which, how many
    rule: LevelRule,
    target: Rows,
    target_units: Units,
    target_kind: Ints,
    source: LevelSource,
    keep: Bools,
    count: int = 3,
) -> list[int]:
    """P8 for a new base (plan sec. 2.5: "each other training date a served level rests on"):
    for every level a ``keep`` row's new chance rests on (the state or region record C1a
    serves it; the unit C2b splits it at, both that kind's record and the unit's whole one),
    the ``count`` training dates with the most of that record's rows (ties to the earlier
    date). Every such date once, the busiest first."""
    weight: dict[int, int] = {}
    for season in sorted(set(target.season[keep].tolist())):
        rows, units, kinds, days = source(season)
        mine = np.flatnonzero(keep & (target.season == season) & (rule.served | rule.moved))
        if not mine.size:
            continue
        pairs = _unit_pairs(target_units, units, len(target), len(rows))
        earlier = rows.season < season
        levels: set[tuple[int, int, int, int]] = set()
        for i in mine.tolist():
            situation = int(target.situation[i])
            if rule.served[i]:
                tier = int(rule.served_tier[i])
                levels.add((tier, int(pairs[tier][0][i]), situation, KIND_UNKNOWN))
            if rule.moved[i]:
                tier = int(rule.split_tier[i])
                unit = int(pairs[tier][0][i])
                levels.add((tier, unit, situation, KIND_UNKNOWN))
                levels.add((tier, unit, situation, int(target_kind[i])))
        for tier, unit, situation, kind in sorted(levels):
            used = earlier & (pairs[tier][1] == unit) & (rows.situation == situation)
            if kind != KIND_UNKNOWN:
                used &= kinds == kind
            numbers, rows_on = np.unique(days[used], return_counts=True)
            ranked = sorted(
                zip(numbers.tolist(), rows_on.tolist(), strict=True),
                key=lambda item: (-item[1], item[0]),
            )
            for number, n in ranked[:count]:
                weight[int(number)] = max(weight.get(int(number), 0), int(n))
    return [d for d, _n in sorted(weight.items(), key=lambda item: (-item[1], item[0]))]


# --- the shadow switches ------------------------------------------------------------------------

SHADOW: Final[Mapping[str, bool]] = {
    "c2a": False,
    "c2c": False,
    "c3": False,
    "c4": False,
    "c1_c2b": False,
}
"""The candidates' switches for S7-F F3's live shadow: every one off. Nothing serves a
candidate; F3 reads these to log a candidate's shadow chance beside the served one, and only
the lead turns one on (calc-research plan T5)."""


def shadow_on(name: str) -> bool:
    """Whether candidate ``name`` runs in the live shadow (never served)."""
    return SHADOW[name]


def shadow_chance(  # noqa: PLR0913, PLR0917 - the switch, the base, the columns, the fit and the clamp
    name: str,
    p_base: Floats,
    columns: Floats,
    weights: Sequence[float],
    floor: float,
    ceiling: float,
) -> Floats:
    """Candidate ``name``'s shadow chance: the published base moved by its columns' fitted
    weights, rounded and held within the floor and ceiling as a published chance is. With its
    switch off (:data:`SHADOW`, every one today) it is the base, unchanged: no candidate moves
    a chance until the lead turns its shadow on, and even then only the logged shadow, never the
    served chance."""
    if not shadow_on(name) or not len(weights):
        return p_base.copy()
    z = _logit(np.clip(p_base, 1e-6, 1 - 1e-6)) + columns @ np.asarray(weights, dtype=np.float64)
    return np.asarray(np.clip(np.round(_sigmoid(z), 2), floor, ceiling), dtype=np.float64)

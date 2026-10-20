"""The pooled rates: what districts did in each situation, borrowed up a chain of places.

Per situation ``k`` and outcome (spec c.1), an empirical-Bayes beta-binomial chain (the
intercept-only form of a hierarchical logistic model), with ``Y`` the labeled
district-days that closed and ``N`` all labeled district-days:

* nation: ``p_N = (Y + 1) / (N + 2)``;
* region: ``p_R = (Y_R + m_R p_N) / (N_R + m_R)``;
* state, county, nearby: each shrinks the same way to the level above, with its own ``m``.

The published rate (:class:`Rules`; the base sentence must stay literally true of the
place it names, the lead's addendum b):

* a level is **named** when it has ``level_min_days`` labeled days in ``k``, its own days
  hold at least half the weight (``n >= m``), and the sentence the website says for its
  published rate is true of its recorded days ``y`` of ``n`` (:func:`snowlight.predict.share.
  says_true`: "3 in 4" only of days that round to 75%, "more than 3 in 5" only above 60%,
  "almost never" only under ``almost_share``); the base is the most specific named level of
  nearby, county, state and region, else the nation, and ``p`` is that level's rate;
* the nation's rate is its record, ``Y / N``, so its sentence is true of it;
* **Own**, when the district has ``own_min_days`` or more labeled days in ``k`` and its own
  rate passes the same test: ``p = (y_d + m_d p_L) / (n_d + m_d)``, ``p_L`` the base;
* a situation the nation holds fewer than ``nation_min_days`` labeled days of (or whose
  nation sentence is not true of them) is **not modeled**: it publishes its fallback
  situation's rates, and its sentence says which recorded days it counts (lake effect snow
  takes the winter storm warning rates; the day after with no warning takes the plain
  day's).

The delay chance ``q = P(delayed | not no school)`` is pooled the same way over the
days that were not ``no_school``. Each ``m`` is chosen per level and class group from
the grid by leave-one-season-out log loss inside the training seasons
(:func:`tune`). Nothing here reads a file: the tables come from the labels.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final, Literal

import numpy as np
import numpy.typing as npt
import polars as pl
from scipy import sparse  # type: ignore[import-untyped]

from snowlight.predict.config import ModelSettings
from snowlight.predict.share import points_of, says_true
from snowlight.predict.situations import GROUPS, SITUATIONS, Group, Situation, WeatherClass

type Level = Literal["region", "state", "county", "nearby", "own"]
LEVELS: Final[tuple[Level, ...]] = ("region", "state", "county", "nearby", "own")
"""The levels below the nation, broadest first."""
type Scope = Literal["nearby", "county", "state", "region", "nation"]
SCOPES: Final[tuple[Scope, ...]] = ("nearby", "county", "state", "region", "nation")
"""The pooled levels a base can name, most specific first."""
type Outcome = Literal["no_school", "delay"]
OUTCOMES: Final[tuple[Outcome, ...]] = ("no_school", "delay")
SITUATION_INDEX: Final[dict[str, int]] = {item.key: i for i, item in enumerate(SITUATIONS)}
GROUP_INDEX: Final[npt.NDArray[np.int64]] = np.array(
    [GROUPS.index(item.group) for item in SITUATIONS], dtype=np.int64
)
_EPSILON: Final = 1e-6

type Floats = npt.NDArray[np.float64]
type Ints = npt.NDArray[np.int64]


def situation_of(weather: int, after: bool) -> Situation:
    """The situation of a labeled day."""
    return Situation.of(WeatherClass(weather), after)


@dataclass(frozen=True, slots=True)
class Places:
    """Each district's units in the chain, by district position."""

    districts: tuple[str, ...]
    """LEAIDs, sorted."""
    region: Ints
    state: Ints
    county: Ints
    """Unit index per district; -1 when unknown."""
    neighbors: sparse.csr_matrix
    """District-by-district adjacency (1 where the column is a neighbor of the row)."""
    regions: tuple[str, ...]
    states: tuple[str, ...]
    counties: tuple[str, ...]

    @property
    def size(self) -> int:
        """The number of districts."""
        return len(self.districts)

    def position(self) -> dict[str, int]:
        """LEAID to its position."""
        return {district: i for i, district in enumerate(self.districts)}


def _codes(values: Sequence[str | None]) -> tuple[Ints, tuple[str, ...]]:
    names = tuple(sorted({value for value in values if value is not None}))
    index = {name: i for i, name in enumerate(names)}
    codes = np.array([index[value] if value is not None else -1 for value in values], np.int64)
    return codes, names


def make_places(
    districts: Sequence[str],
    region: Sequence[str | None],
    state: Sequence[str | None],
    county: Sequence[str | None],
    neighbors: Mapping[str, Sequence[str]],
) -> Places:
    """The chain's units for ``districts`` (sorted by the caller), each list in that order."""
    order = list(districts)
    if order != sorted(order) or len(set(order)) != len(order):
        raise ValueError("districts must be sorted and unique")
    position = {district: i for i, district in enumerate(order)}
    rows: list[int] = []
    cols: list[int] = []
    for district, near in neighbors.items():
        if district not in position:
            continue
        for other in near:
            if other in position and other != district:
                rows.append(position[district])
                cols.append(position[other])
    size = len(order)
    matrix = sparse.csr_matrix(
        (np.ones(len(rows), dtype=np.float64), (rows, cols)), shape=(size, size)
    )
    matrix.data[:] = 1.0
    region_codes, regions = _codes(region)
    state_codes, states = _codes(state)
    county_codes, counties = _codes(county)
    return Places(
        tuple(order), region_codes, state_codes, county_codes, matrix, regions, states, counties
    )


@dataclass(frozen=True, slots=True)
class Tables:
    """Labeled counts by district, situation and season: closings ``y`` of days ``n``."""

    y: Floats
    """Shape (districts, situations, seasons)."""
    n: Floats
    seasons: tuple[int, ...]

    def total(self, keep: Sequence[int] | None = None) -> tuple[Floats, Floats]:
        """Counts summed over the seasons in ``keep`` (all when ``None``): (districts,
        situations)."""
        if keep is None:
            return self.y.sum(axis=2), self.n.sum(axis=2)
        mask = np.isin(np.array(self.seasons), np.array(list(keep)))
        return self.y[:, :, mask].sum(axis=2), self.n[:, :, mask].sum(axis=2)


@dataclass(frozen=True, slots=True)
class Rows:
    """Labeled district-days for fitting or scoring, by position."""

    district: Ints
    situation: Ints
    season: Ints
    y: Floats
    """1 for the outcome (no school, or a delay among days with school)."""

    def __len__(self) -> int:
        return int(self.district.shape[0])

    def subset(self, mask: npt.NDArray[np.bool_]) -> "Rows":
        """The rows ``mask`` keeps."""
        return Rows(self.district[mask], self.situation[mask], self.season[mask], self.y[mask])


def usable_labels(labels: pl.DataFrame, places: Places) -> pl.DataFrame:
    """The labels a fit uses, in their order: ``unknown`` dropped, districts ``places`` knows."""
    return labels.filter(
        pl.col("outcome").is_in(["no_school", "delayed", "open"])
        & pl.col("district").is_in(list(places.districts))
    )


def rows_from_labels(labels: pl.DataFrame, places: Places, outcome: Outcome) -> Rows:
    """The labeled rows of ``outcome``, in the order of :func:`usable_labels` (a delay row is
    a day that was not ``no_school``)."""
    position = places.position()
    known = usable_labels(labels, places)
    if outcome == "delay":
        known = known.filter(pl.col("outcome") != "no_school")
    target = "no_school" if outcome == "no_school" else "delayed"
    district = np.array([position[d] for d in known["district"].to_list()], dtype=np.int64)
    situation = np.array(
        [
            SITUATION_INDEX[situation_of(int(w), bool(a)).key]
            for w, a in zip(known["weather"].to_list(), known["after"].to_list(), strict=True)
        ],
        dtype=np.int64,
    )
    return Rows(
        district=district,
        situation=situation,
        season=known["season"].to_numpy().astype(np.int64),
        y=(known["outcome"] == target).to_numpy().astype(np.float64),
    )


def tables_from_rows(rows: Rows, places: Places, seasons: Sequence[int]) -> Tables:
    """Count ``rows`` by district, situation and season."""
    shape = (places.size, len(SITUATIONS), len(seasons))
    season_index = {season: i for i, season in enumerate(seasons)}
    index = np.array([season_index[s] for s in rows.season.tolist()], dtype=np.int64)
    y = np.zeros(shape)
    n = np.zeros(shape)
    np.add.at(y, (rows.district, rows.situation, index), rows.y)
    np.add.at(n, (rows.district, rows.situation, index), 1.0)
    return Tables(y, n, tuple(seasons))


def _group_sum(values: Floats, codes: Ints, units: int) -> Floats:
    """Sum (districts, situations) values into (units, situations); unknown codes dropped."""
    out = np.zeros((units, values.shape[1]))
    keep = codes >= 0
    np.add.at(out, codes[keep], values[keep])
    return out


@dataclass(frozen=True, slots=True)
class LevelCounts:
    """Counts at every level, per district and situation: each district's own region,
    state, county and nearby districts, the nation, and its own."""

    y: dict[str, Floats]
    n: dict[str, Floats]
    """Level (``nation`` and :data:`LEVELS`) to an array of shape (districts, situations)."""


def level_counts(places: Places, y: Floats, n: Floats) -> LevelCounts:
    """Spread district counts (districts, situations) up the chain and back to each district."""
    ys: dict[str, Floats] = {}
    ns: dict[str, Floats] = {}
    size = places.size
    for name, codes, units in (
        ("region", places.region, len(places.regions)),
        ("state", places.state, len(places.states)),
        ("county", places.county, len(places.counties)),
    ):
        unit_y, unit_n = _group_sum(y, codes, units), _group_sum(n, codes, units)
        known = codes >= 0
        ys[name] = np.where(known[:, None], unit_y[np.maximum(codes, 0)], 0.0)
        ns[name] = np.where(known[:, None], unit_n[np.maximum(codes, 0)], 0.0)
    ys["nearby"] = np.asarray(places.neighbors @ y)
    ns["nearby"] = np.asarray(places.neighbors @ n)
    ys["nation"] = np.broadcast_to(y.sum(axis=0), (size, y.shape[1])).copy()
    ns["nation"] = np.broadcast_to(n.sum(axis=0), (size, n.shape[1])).copy()
    ys["own"], ns["own"] = y, n
    return LevelCounts(ys, ns)


@dataclass(frozen=True, slots=True)
class Strengths:
    """The shrinkage strength ``m`` of each level, per class group."""

    m: dict[Level, dict[Group, float]]

    def array(self, level: Level) -> Floats:
        """``m`` of ``level`` per situation (in :data:`SITUATIONS` order)."""
        return np.array([self.m[level][item.group] for item in SITUATIONS], dtype=np.float64)

    def with_value(self, level: Level, group: Group, value: float) -> "Strengths":
        """A copy with one strength changed."""
        m = {name: dict(groups) for name, groups in self.m.items()}
        m[level][group] = value
        return Strengths(m)

    def as_json(self) -> dict[str, dict[str, float]]:
        """Level to group to ``m``."""
        return {level: dict(sorted(groups.items())) for level, groups in self.m.items()}

    @classmethod
    def uniform(cls, value: float) -> "Strengths":
        """Every strength ``value``."""
        return cls({level: dict.fromkeys(GROUPS, value) for level in LEVELS})


@dataclass(frozen=True, slots=True)
class Rules:
    """How the chain names and publishes a rate (spec c.1 and the lead's addendum b: the
    base sentence stays literally true of the place it names)."""

    own_min_days: int
    level_min_days: int
    nation_min_days: int = 0
    """A situation with fewer labeled days in the nation is not modeled: it takes its
    ``fallback`` situation's rates and sentence (:func:`effective_situations`)."""
    almost_share: float | None = None
    """A level is named only when its own days hold at least half the weight (``n >= m``)
    and the sentence for its published rate is true of its recorded days (:meth:`true_of`,
    "almost never" true under this share and "almost always" over one minus it); otherwise
    the base moves up the chain, to the nation. ``None``: the spec's first rule (the most
    specific level with ``level_min_days``, the region always)."""
    floor: float = 0.01
    ceiling: float = 0.99
    fallback: tuple[int, ...] = ()
    """Per situation (in :data:`SITUATIONS` order), the situation it falls back to, or -1."""

    def published(self, p: Floats) -> Floats:
        """The chance as published: hundredths within [floor, ceiling]."""
        return np.clip(np.round(p, 2), self.floor, self.ceiling)

    def true_of(self, rate: Floats, y: Floats, n: Floats) -> npt.NDArray[np.bool_]:
        """Whether the sentence for ``rate`` as published is true of ``y`` of ``n`` days."""
        if self.almost_share is None:
            return np.ones(np.shape(rate), dtype=np.bool_)
        return says_true(points_of(self.published(rate)), y, n, self.almost_share)

    def nation_rate(self, y: Floats, n: Floats) -> Floats:
        """The nation's rate: its record ``y / n`` under the truth rule (with
        ``nation_min_days`` or more days), else ``(y + 1) / (n + 2)``."""
        smoothed = (y + 1.0) / (n + 2.0)
        if self.almost_share is None:
            return smoothed
        backed = n >= max(self.nation_min_days, 1)
        raw = np.divide(y, n, out=np.zeros(np.shape(y)), where=n > 0)
        return np.where(backed, raw, smoothed)


def effective_situations(nation_y: Floats, nation_n: Floats, rules: Rules) -> Ints:
    """Per situation, the situation whose rates it publishes: itself when the nation holds
    ``nation_min_days`` labeled days of it and its rate is true of them, else its fallback's
    (followed until one is backed); -1 when none is (``nation_y`` and ``nation_n`` per
    situation)."""
    count = len(SITUATIONS)
    backed = nation_n >= max(rules.nation_min_days, 1)
    if rules.almost_share is not None:
        backed &= rules.true_of(rules.nation_rate(nation_y, nation_n), nation_y, nation_n)
    found = np.full(count, -1, dtype=np.int64)
    for k in range(count):
        seen: set[int] = set()
        j = k
        while j >= 0 and j not in seen:
            if backed[j]:
                found[k] = j
                break
            seen.add(j)
            j = rules.fallback[j] if j < len(rules.fallback) else -1
    return found


@dataclass(frozen=True, slots=True)
class Chain:
    """Rates along the chain for a set of (district, situation) cells."""

    rate: dict[str, Floats]
    """Level to its shrunk rate (``nation`` and :data:`LEVELS`)."""
    days: dict[str, Floats]
    """Level to its labeled days."""
    scope: npt.NDArray[np.int64]
    """Index in :data:`SCOPES` of the level the base names."""
    own: npt.NDArray[np.bool_]
    """Whether the district's own record is used."""
    p: Floats
    """The published rate, before rounding."""
    situation: Ints
    """The situation whose rates each cell publishes (its own, or its fallback's; -1 when
    none is backed: nothing may be published)."""


def chain(
    counts: LevelCounts,
    strengths: Strengths,
    *,
    rules: Rules,
    cells: tuple[Ints, Ints] | None = None,
    effective: Ints | None = None,
) -> Chain:
    """The chain for every (district, situation), or for ``cells`` = (districts, situations).

    ``effective`` maps each situation to the one whose rates it takes (default
    :func:`effective_situations` of these counts)."""
    nation_y = counts.y["nation"][0] if counts.y["nation"].shape[0] else np.zeros(len(SITUATIONS))
    nation_n = counts.n["nation"][0] if counts.n["nation"].shape[0] else np.zeros(len(SITUATIONS))
    mapping = effective_situations(nation_y, nation_n, rules) if effective is None else effective
    target = np.maximum(mapping, 0)
    if cells is None:
        shape = counts.y["own"].shape
        situation = np.broadcast_to(mapping, shape)

        def pick(values: Floats) -> Floats:
            return values[:, target]

    else:
        situation = mapping[cells[1]]

        def pick(values: Floats) -> Floats:
            return values[cells[0], target[cells[1]]]

    used = np.maximum(situation, 0)
    truth = rules.almost_share

    def true_of(rate: Floats, y: Floats, n: Floats, m: Floats) -> npt.NDArray[np.bool_]:
        if truth is None:
            return np.ones(rate.shape, dtype=np.bool_)
        return (n >= m) & rules.true_of(rate, y, n)

    rate: dict[str, Floats] = {}
    days: dict[str, Floats] = {}
    y, n = pick(counts.y["nation"]), pick(counts.n["nation"])
    rate["nation"] = rules.nation_rate(y, n)
    days["nation"] = n
    above = rate["nation"]
    if truth is None:
        scope = np.full(rate["nation"].shape, SCOPES.index("region"), dtype=np.int64)
    else:
        scope = np.full(rate["nation"].shape, SCOPES.index("nation"), dtype=np.int64)
    base = rate["nation"].copy()
    for level in ("region", "state", "county", "nearby"):
        m = strengths.array(level)[used]
        y, n = pick(counts.y[level]), pick(counts.n[level])
        rate[level] = (y + m * above) / (n + m)
        days[level] = n
        above = rate[level]
        if truth is None and level == "region":
            base = rate["region"].copy()
            continue
        qualified = (n >= level_min(rules, level)) & true_of(rate[level], y, n, m)
        scope = np.where(qualified, SCOPES.index(level), scope)
        base = np.where(qualified, rate[level], base)
    y, n = pick(counts.y["own"]), pick(counts.n["own"])
    m = strengths.array("own")[used]
    rate["own"] = (y + m * base) / (n + m)
    days["own"] = n
    own = (n >= rules.own_min_days) & true_of(rate["own"], y, n, m)
    p = np.where(own, rate["own"], base)
    return Chain(rate, days, scope, own, p, np.asarray(situation, dtype=np.int64))


def named_counts(counts: LevelCounts, found: Chain) -> tuple[Floats, Floats]:
    """The recorded days ``y`` of ``n`` of the level each cell's base names (its own record,
    or the scope's), in the situation it publishes, for a chain over every cell."""
    target = np.maximum(found.situation, 0)
    rows = np.arange(target.shape[0])[:, None]
    y = np.zeros(target.shape)
    n = np.zeros(target.shape)
    for index, scope in enumerate(SCOPES):
        mask = ~found.own & (found.scope == index)
        y = np.where(mask, counts.y[scope][rows, target], y)
        n = np.where(mask, counts.n[scope][rows, target], n)
    y = np.where(found.own, counts.y["own"][rows, target], y)
    n = np.where(found.own, counts.n["own"][rows, target], n)
    return y, n


def make_rules(  # noqa: PLR0913 - every setting of the rule
    *,
    own_min_days: int,
    level_min_days: int,
    nation_min_days: int,
    almost_share: float | None,
    floor: float,
    ceiling: float,
    fallback: Mapping[str, str],
) -> Rules:
    """:class:`Rules` from the settings, ``fallback`` by situation key.

    Raises:
        ValueError: a fallback names an unknown situation.
    """
    order = [SITUATION_INDEX.get(fallback[item.key], -2) if item.key in fallback else -1
             for item in SITUATIONS]  # fmt: skip
    if -2 in order:  # noqa: PLR2004 - the unknown marker
        raise ValueError(f"a fallback names an unknown situation: {dict(fallback)}")
    return Rules(
        own_min_days=own_min_days,
        level_min_days=level_min_days,
        nation_min_days=nation_min_days,
        almost_share=almost_share,
        floor=floor,
        ceiling=ceiling,
        fallback=tuple(order),
    )


def rules_of(settings: ModelSettings) -> Rules:
    """The chain's rules from the model settings."""
    return make_rules(
        own_min_days=settings.own_min_days,
        level_min_days=settings.level_min_days,
        nation_min_days=settings.nation_min_days,
        almost_share=settings.almost_share,
        floor=settings.floor,
        ceiling=settings.ceiling,
        fallback=settings.fallback,
    )


def delay_rules(rules: Rules) -> Rules:
    """The delay chance's rules: the same days, with no sentence to keep true (the why never
    states a delay rate) and no fallback of its own (it follows the no-school situation)."""
    return replace(rules, almost_share=None, nation_min_days=0, fallback=())


def level_min(rules: Rules, level: str) -> int:
    """The labeled days a level needs to be named."""
    return rules.nation_min_days if level == "nation" else rules.level_min_days


def log_loss(p: Floats, y: Floats) -> float:
    """Mean log loss."""
    q = np.clip(p, _EPSILON, 1 - _EPSILON)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def predict_rows(  # noqa: PLR0913 - the rows, their counts and the chain rules
    rows: Rows,
    places: Places,
    tables: Tables,
    strengths: Strengths,
    keep: Sequence[int],
    *,
    rules: Rules,
) -> Chain:
    """The chain for ``rows`` from the counts of the seasons in ``keep`` only."""
    y, n = tables.total(keep)
    counts = level_counts(places, y, n)
    return chain(counts, strengths, rules=rules, cells=(rows.district, rows.situation))


def loso_counts(places: Places, tables: Tables, seasons: Sequence[int]) -> dict[int, LevelCounts]:
    """For each season of ``seasons``, the level counts of the others (leave one season out)."""
    found: dict[int, LevelCounts] = {}
    for season in seasons:
        y, n = tables.total([s for s in seasons if s != season])
        found[season] = level_counts(places, y, n)
    return found


def loso_predictions(
    rows: Rows,
    counts: Mapping[int, LevelCounts],
    strengths: Strengths,
    *,
    rules: Rules,
) -> Floats:
    """Each row predicted from the counts that leave its season out (``counts``, from
    :func:`loso_counts`); a row of a season not in ``counts`` stays NaN."""
    p = np.full(len(rows), np.nan)
    for season, level in counts.items():
        mask = rows.season == season
        if not mask.any():
            continue
        part = rows.subset(mask)
        found = chain(level, strengths, rules=rules, cells=(part.district, part.situation))
        p[mask] = found.p
    return p


@dataclass(slots=True)
class Tuned:
    """The strengths chosen, and the log loss of each try."""

    strengths: Strengths
    trials: list[tuple[str, str, float, float]] = field(default_factory=list)
    """(level, group, m, log loss)."""


def tune(  # noqa: PLR0913 - the rows, their counts, the grid and the chain settings
    rows: Rows,
    places: Places,
    tables: Tables,
    seasons: Sequence[int],
    grid: Iterable[float],
    *,
    rules: Rules,
    sweeps: int = 2,
    start: float = 8.0,
) -> Tuned:
    """Choose each level's ``m`` per class group from ``grid`` by leave-one-season-out log
    loss over ``rows`` of ``seasons``, one level at a time, broadest first, ``sweeps`` times.

    A group or a level without rows keeps ``start``. Ties go to the smaller ``m``.
    """
    values = sorted(set(grid))
    tuned = Tuned(Strengths.uniform(start))
    inside = rows.subset(np.isin(rows.season, np.array(list(seasons))))
    if len(seasons) < 2 or not len(inside):  # noqa: PLR2004 - one season leaves none out
        return tuned
    group_of_row = GROUP_INDEX[inside.situation]
    counts = loso_counts(places, tables, seasons)
    for _sweep in range(sweeps):
        for level in LEVELS:
            for g, group in enumerate(GROUPS):
                mask = group_of_row == g
                if not mask.any():
                    continue
                part = inside.subset(mask)
                best: tuple[float, float] | None = None
                for value in values:
                    trial = tuned.strengths.with_value(level, group, value)
                    p = loso_predictions(part, counts, trial, rules=rules)
                    held = ~np.isnan(p)
                    loss = log_loss(p[held], part.y[held]) if held.any() else 0.0
                    tuned.trials.append((level, group, value, loss))
                    if best is None or loss < best[1] - 1e-12:
                        best = (value, loss)
                if best is not None:
                    tuned.strengths = tuned.strengths.with_value(level, group, best[0])
    return tuned


def publish_rates(
    p_no_school: Floats, q_delay: Floats, floor: float, ceiling: float
) -> tuple[Floats, Floats]:
    """The published chances: ``p_no_school`` rounded to hundredths within [floor, ceiling];
    ``p_delay = round((1 - p_no_school) * q, 2)``, so the two never sum above 1."""
    no_school = np.clip(np.round(p_no_school, 2), floor, ceiling)
    delay = np.round((1.0 - no_school) * q_delay, 2)
    return no_school, np.minimum(delay, np.round(1.0 - no_school, 2))

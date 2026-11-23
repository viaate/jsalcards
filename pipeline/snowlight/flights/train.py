"""Fitting the flight chances on history and testing them on the held-out year (D6).

``snowlight flights train`` reads the compact BTS tables and the NBS rows kept in RAM
(``/dev/shm/flights``), and writes the model file (:data:`snowlight.flights.artifact.MODEL_FILE`)
and the held-out report. Every number in the report comes from this module and the data it
names.

The split: the test year is the newest 12 posted BTS months (:func:`split`). The usual rates come
from every BTS month before it (2015 on); the regressions from the NBS runs before it (mid 2020
on). Nothing of the test year is used in fitting or in choosing a setting.

The gates (LR-H1): where a chance is published, after a storm or not, is set on the validation
year (the 12 months before the test year) by a fit on the years before it
(:func:`fit_and_gate`); the model is then fitted on every year before the test year with those
gates fixed, and the test year scores the published choice once.
"""

import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import numpy as np
import polars as pl

from snowlight.flights import model as fm
from snowlight.flights.airports import Airport, current_code
from snowlight.flights.bts import Month, kept_months, scan
from snowlight.flights.features import BLOCK_COLUMNS, block_features, with_hubs
from snowlight.flights.obs import OBSERVED_COLUMNS, with_observed
from snowlight.flights.spans import carrier_weather, weather_days

DAY_COLUMNS: Final = BLOCK_COLUMNS


@dataclass(frozen=True, slots=True)
class Split:
    """The held-out test year and what comes before it."""

    test_first: date
    test_last: date
    """The last day of the test year (included)."""

    def before(self, column: str = "day") -> pl.Expr:
        """Rows before the test year."""
        return pl.col(column) < self.test_first

    def inside(self, column: str = "day") -> pl.Expr:
        """Rows in the test year."""
        return (pl.col(column) >= self.test_first) & (pl.col(column) <= self.test_last)


def validation_of(cut: Split) -> Split:
    """The validation year: the 12 months before the test year."""
    first = date(cut.test_first.year - 1, cut.test_first.month, cut.test_first.day)
    return Split(test_first=first, test_last=cut.test_first - timedelta(days=1))


def split(newest: Month) -> Split:
    """The test year ending with the newest posted month."""
    first = newest.back(11).first
    after = newest.next().first
    return Split(test_first=first, test_last=date.fromordinal(after.toordinal() - 1))


def zones(airports: Sequence[Airport]) -> pl.DataFrame:
    """Each airport's bulletin station, code, time zone and latitude."""
    return pl.DataFrame(
        {
            "station": [a.icao for a in airports],
            "apt": [a.code for a in airports],
            "tz": [a.tz for a in airports],
            "lat": [a.lat for a in airports],
        }
    )


def outcomes(root: Path, table: str) -> pl.LazyFrame:
    """A ``dep`` or ``arr`` table summed over carriers, codes current; an airline's own
    non-weather days (:data:`snowlight.flights.spans.CARRIER_NOT_WEATHER`) are left out before
    the sum."""
    return (
        scan(root, table)
        .filter(carrier_weather())
        .with_columns(current_code("apt"))
        .group_by("apt", "day", "block")
        .agg(pl.col("n").sum(), pl.col("canc").sum(), pl.col("late").sum())
    )


def forecast_features(
    nbs_rows: pl.LazyFrame, airports: Sequence[Airport], flags: pl.LazyFrame | None = None
) -> pl.DataFrame:
    """Block features of every run, with the hubs' weather, the weather observed before the run
    (``flags``: hourly report flags, :func:`snowlight.flights.obs.with_observed`), latitude and
    lead class: built a year of runs at a time (every part is per run), so the history fits in
    memory."""
    z = zones(airports)
    years = nbs_rows.select(pl.col("run").dt.year().unique()).collect().to_series().sort()
    small = [
        *BLOCK_COLUMNS,
        *OBSERVED_COLUMNS,
        "hub_snow",
        "hub_storm",
        "day_snow",
        "day_ice",
        "day_storm",
        "lead",
    ]
    stations = observed_stations(airports)
    parts = []
    for year in years.to_list():
        rows = nbs_rows.filter(pl.col("run").dt.year() == year)
        features = block_features(rows, z.select("station", "apt", "tz")).collect()
        features = with_hubs(features, fm.HUBS)
        features = with_observed(features.lazy(), flags, stations).collect()
        parts.append(
            features.join(z.select("apt", "lat"), on="apt")
            .with_columns(
                *[pl.col(name).cast(pl.Float32) for name in small],
                pl.col("lat").cast(pl.Float32),
            )
            .drop("end")
        )
    if not parts:
        return pl.DataFrame()
    return pl.concat(parts)


def observed_stations(airports: Sequence[Airport]) -> pl.DataFrame:
    """Each airport's weather report station (``station``) and code (``apt``)."""
    return pl.DataFrame({"station": [a.wx for a in airports], "apt": [a.code for a in airports]})


def day_features(features: pl.DataFrame) -> pl.DataFrame:
    """Per airport, run and day: the day's weather from its five blocks (only days the run covers
    whole), and its lead class (the same for every block of a day and run)."""
    return (
        features.group_by("apt", "run", "day")
        .agg(
            pl.len().alias("blocks"),
            pl.col("lead").min(),
            pl.col("lead_class").first(),
            pl.col("lat").first(),
            pl.col("snow").sum(),
            pl.col("ice").sum(),
            pl.col("p_snow").max(),
            pl.col("p_zr").max(),
            pl.col("thunder").max(),
            pl.col("wind").max(),
            pl.col("gust").max(),
            pl.col("vis").min(),
            pl.col("cig").min(),
            pl.col("tmp").min(),
            pl.col("snow_before").sort_by("block").first(),
            pl.col("ice_before").sort_by("block").first(),
            pl.col("hub_snow").sum(),
            pl.col("hub_storm").max(),
            pl.col("day_snow").first(),
            pl.col("day_ice").first(),
            pl.col("day_storm").first(),
            pl.col("pre_snow").first(),
            pl.col("pre_ice").first(),
            *[pl.col(name).first() for name in OBSERVED_COLUMNS],
        )
        .filter(pl.col("blocks") == 5)  # noqa: PLR2004 - a whole day
    )


@dataclass(slots=True)
class Tables:
    """Everything the fit and the test read."""

    split: Split
    base: dict[str, pl.DataFrame]
    """``dep`` and ``arr``: usual rates by airport, block and month (:func:`model.base_rates`)."""
    rough: pl.DataFrame
    blocks: dict[str, pl.DataFrame]
    """``dep`` and ``arr``: block features joined to outcomes and the usual rates."""
    days: pl.DataFrame
    base_years: int | None = None
    """The usual rates' window in years (``None``: every posted year)."""
    usual_window: tuple[date, date] | None = None
    """The first and last day the test year's usual rates (and the live files' usual rates,
    from the same model) average over; non-weather spans left out (R6-S4)."""


BASE_YEARS: Final = (3, 5, None)
"""How many years before a cut the usual rates read (``None``: every posted year), chosen on the
validation year (:func:`choose_base_years`), never on the test year."""


def _window(cut: date, years: int | None) -> pl.Expr:
    before = (pl.col("day") < cut) & weather_days()
    if years is None:
        return before
    return before & (pl.col("day") >= date(cut.year - years, cut.month, cut.day))


def _with_base(features: pl.LazyFrame, happened: pl.LazyFrame, base: pl.DataFrame) -> pl.LazyFrame:
    return (
        features.join(happened, on=["apt", "day", "block"])
        .with_columns(pl.col("day").dt.month().cast(pl.Int8).alias("moy"))
        .join(
            base.lazy().select("apt", "block", "moy", "canc", "late"),
            on=["apt", "block", "moy"],
            suffix="_base",
        )
    )


def periods(cut: Split, first: date) -> list[date]:
    """The starts of the 12-month periods from the test year back to the one holding ``first``:
    each row's usual rate comes from the years before its own period (:func:`by_period`), so no
    row's usual rate holds its own outcome or anything after it."""
    starts = [cut.test_first]
    while starts[-1] > first:
        last = starts[-1]
        starts.append(date(last.year - 1, last.month, last.day))
    return starts


def period_of(starts: Sequence[date]) -> pl.Expr:
    """Each row's period start (``None`` before the oldest)."""
    expr: pl.Expr = pl.lit(None, dtype=pl.Date)
    for start in sorted(starts):
        expr = pl.when(pl.col("day") >= start).then(pl.lit(start)).otherwise(expr)
    return expr.alias("period")


def by_period(
    rates: Callable[[pl.LazyFrame], pl.DataFrame],
    happened: pl.LazyFrame,
    starts: Sequence[date],
    years: int | None,
) -> pl.DataFrame:
    """Usual rates for each period, from the ``years`` before its start, with ``period``."""
    return pl.concat(
        [
            rates(happened.filter(_window(start, years))).with_columns(
                pl.lit(start).alias("period")
            )
            for start in starts
        ]
    )


def _with_period_base(
    features: pl.LazyFrame, happened: pl.LazyFrame, base: pl.DataFrame, starts: Sequence[date]
) -> pl.LazyFrame:
    return (
        features.join(happened, on=["apt", "day", "block"])
        .with_columns(pl.col("day").dt.month().cast(pl.Int8).alias("moy"), period_of(starts))
        .join(
            base.lazy().select("apt", "block", "moy", "period", "canc", "late"),
            on=["apt", "block", "moy", "period"],
            suffix="_base",
        )
    )


def choose_base_years(features: pl.DataFrame, happened: pl.LazyFrame, cut: Split) -> int | None:
    """The usual rates' window that scores best on the validation year (the 12 months before the
    test year): for each choice, rates from before the validation year, a lead-1 departure
    cancel fit on the rows before it, and its Brier score on the validation year."""
    start = date(cut.test_first.year - 1, cut.test_first.month, cut.test_first.day)
    lead1 = features.lazy().filter(pl.col("lead_class") == 1)
    best: tuple[float, int | None] | None = None
    for years in BASE_YEARS:
        base = fm.base_rates(happened.filter(_window(start, years)))
        rows = _with_base(lead1, happened, base).filter(weather_days()).collect()
        fit_rows = rows.filter(pl.col("day") < start)
        check = rows.filter((pl.col("day") >= start) & cut.before())
        if fit_rows.is_empty() or check.is_empty():
            continue
        x, events, trials, _ = _rows(fit_rows, "dep_canc")
        if events.sum() <= 0:
            continue
        model = fm.fit(x, events, trials)
        x2, events2, trials2, base2 = _rows(check, "dep_canc")
        brier = fm.score(model.predict(x2), base2, events2, trials2).brier
        if best is None or brier < best[0]:
            best = (brier, years)
    return None if best is None else best[1]


def assemble(
    bts_root: Path,
    nbs_rows: pl.LazyFrame,
    airports: Sequence[Airport],
    flags: pl.LazyFrame | None = None,
) -> Tables:
    """Join the forecast features (and the weather observed before each run, from ``flags``) to
    what happened and to the usual rates: every row's usual rate from the years before its own
    12-month period (:func:`periods`), the test year's from the years before the test year."""
    newest = kept_months(bts_root)[-1]
    cut = split(newest)
    features = forecast_features(nbs_rows, airports, flags)
    years = choose_base_years(features, outcomes(bts_root, "dep"), cut)
    first = features.get_column("day").min() if len(features) else cut.test_first
    starts = periods(cut, first if isinstance(first, date) else cut.test_first)
    base: dict[str, pl.DataFrame] = {}
    blocks: dict[str, pl.DataFrame] = {}
    for table in ("dep", "arr"):
        happened = outcomes(bts_root, table)
        every = by_period(fm.base_rates, happened, starts, years)
        base[table] = every.filter(pl.col("period") == cut.test_first).drop("period")
        blocks[table] = _with_period_base(features.lazy(), happened, every, starts).collect()
    dep_days = fm.airport_days(outcomes(bts_root, "dep"))
    rough_every = by_period(fm.rough_rates, outcomes(bts_root, "dep"), starts, years)
    rough = rough_every.filter(pl.col("period") == cut.test_first).drop("period")
    days = (
        day_features(features)
        .lazy()
        .join(dep_days, on=["apt", "day"])
        .with_columns(pl.col("day").dt.month().cast(pl.Int8).alias("moy"), period_of(starts))
        .join(
            rough_every.lazy().select("apt", "moy", "period", pl.col("rough").alias("rough_base")),
            on=["apt", "moy", "period"],
        )
        .collect()
    )
    oldest = kept_months(bts_root)[0].first
    usual_first = (
        max(oldest, date(cut.test_first.year - years, cut.test_first.month, cut.test_first.day))
        if years
        else oldest
    )
    return Tables(
        split=cut,
        base=base,
        rough=rough,
        blocks=blocks,
        days=days,
        base_years=years,
        usual_window=(usual_first, cut.test_first - timedelta(days=1)),
    )


def _rows(
    frame: pl.DataFrame, target: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Design matrix, events, trials and the usual chance for one target."""
    if target == "rough":
        framed = frame.with_columns(pl.col("rough_base").alias("base"))
        events = framed.get_column("rough").cast(pl.Float64).to_numpy()
        trials = np.ones(len(framed))
    else:
        kind = target.split("_")[1]
        framed = frame.with_columns(pl.col(f"{kind}_base").alias("base"))
        events = framed.get_column(kind).cast(pl.Float64).to_numpy()
        trials = framed.get_column("n").cast(pl.Float64).to_numpy()
    base = framed.get_column("base").to_numpy().astype(np.float64)
    return fm.design(framed), events, trials, base


def _seen(frame: pl.DataFrame, target: str) -> tuple[np.ndarray, np.ndarray]:
    """Each row's share that happened and its flights (the under-said count,
    :func:`snowlight.flights.model.score`): for the rough-day chance, the day's cancelled
    share and departures."""
    if target == "rough":
        n = frame.get_column("n").cast(pl.Float64).to_numpy()
        canc = frame.get_column("canc").cast(pl.Float64).to_numpy()
    else:
        kind = target.split("_")[1]
        n = frame.get_column("n").cast(pl.Float64).to_numpy()
        canc = frame.get_column(kind).cast(pl.Float64).to_numpy()
    return np.divide(canc, n, out=np.zeros_like(canc), where=n > 0), n


def stormy(frame: pl.DataFrame) -> np.ndarray:
    """Each row's after-storm flag (:func:`snowlight.flights.model.after_storm`)."""
    if frame.is_empty():
        return np.zeros(0, dtype=bool)
    return frame.select(fm.after_storm_expr()).to_series().to_numpy().astype(bool)


def _frame_of(tables: Tables, target: str) -> pl.DataFrame:
    if target == "rough":
        return tables.days
    return tables.blocks[target.split("_", maxsplit=1)[0]]


def train(
    tables: Tables,
    exclude: tuple[date, date] | None = None,
    inputs: Sequence[str] = fm.FEATURES,
    before: date | None = None,
) -> fm.Model:
    """Fit every target and lead on the rows before the test year (or before ``before``: the
    validation year's first day, for the fit that sets the gates) and outside ``exclude`` (a
    span left out so its days can be shown as never seen), with ``inputs`` (the groups chosen
    on the validation year, :func:`choose_inputs`)."""
    model = fm.Model(inputs=tuple(inputs))
    keep = fm.columns(model.inputs)
    end = tables.split.test_first if before is None else min(before, tables.split.test_first)
    for target in fm.TARGETS:
        frame = _frame_of(tables, target).filter((pl.col("day") < end) & weather_days())
        if exclude is not None:
            frame = frame.filter((pl.col("day") < exclude[0]) | (pl.col("day") > exclude[1]))
        for lead in fm.leads():
            part = frame.filter(pl.col("lead_class") == lead)
            x, events, trials, _ = _rows(part, target)
            if trials.sum() <= 0 or events.sum() <= 0:
                continue
            model.fitted[(target, lead)] = fm.fit(x[:, keep], events, trials)
    return model


@dataclass(frozen=True, slots=True)
class Tested:
    """The held-out test of one target and lead."""

    target: str
    lead: int
    split: tuple[date, date]
    pooled: fm.Score
    """The model's chances at every airport (the regression's own test)."""
    reliability: list[dict[str, float]]
    airports: dict[str, fm.Score]
    as_published: fm.Score = field(default_factory=lambda: fm.combined(()))
    """What the files would have shown: the model's chance where it passed, else the usual
    rate."""
    confirmed: fm.Score = field(default_factory=lambda: fm.combined(()))
    """The skill out of selection (:func:`snowlight.flights.model.confirmed`)."""
    reliability_published: list[dict[str, float]] = field(default_factory=list)
    """The reliability of what the files would have shown."""
    after_storm: fm.Score = field(default_factory=lambda: fm.combined(()))
    """The rows after an observed storm at the airports that passed, pooled
    (:func:`snowlight.flights.model.after_storm_ok`)."""
    after_lower: float = float("-inf")
    """The lower 90% bound of :attr:`after_storm`'s skill by days
    (:func:`snowlight.flights.model.skill_lower`)."""
    usual: fm.Score = field(default_factory=lambda: fm.combined(()))
    """The usual rates' own score on the test year (said = the usual rate), so the report shows
    how far the dated average sits from the year scored (R6-S4)."""
    after_out: fm.Score = field(default_factory=lambda: fm.combined(()))
    """The rows after an observed storm scored out of selection: the airports the even weeks
    chose on their odd-week rows, and the reverse (R6-S2). The gate needs this and
    :attr:`after_storm` both to pass."""
    after_out_lower: float = float("-inf")
    """The lower 90% bound of :attr:`after_out`'s skill by days."""
    chosen: tuple[int, int] = (0, 0)
    """Airports the even weeks and the odd weeks chose."""
    reliability_shown: list[dict[str, float]] = field(default_factory=list)
    """The reliability of the model's chances that the files would have shown (the usual-rate
    cells left out)."""
    reliability_after: list[dict[str, float]] = field(default_factory=list)
    """The reliability of the model's chances after an observed storm at the airports that
    passed (what :func:`snowlight.flights.model.after_storm_ok` gates)."""
    shown_by_month: list[tuple[str, float, float, float]] = field(default_factory=list)
    """Per month of the test year: the units, the expected and the seen events of the model's
    chances shown (so one storm's misses are not hidden in the year's sum)."""
    after_shown: bool | None = None
    """Whether the files show the model's chance after a storm for this target and lead: the
    gate as set on the validation year (``None``: read from this test's own scores)."""
    with_not_weather: fm.Score | None = None
    """The pooled test with the :data:`snowlight.flights.spans.NOT_WEATHER` spans of the test
    year put back in."""
    published_with_not_weather: fm.Score | None = None
    """:attr:`as_published` with those spans put back in: on their days too, the chance where
    it passed (after a storm only where :attr:`after_shown`), else the usual rate."""
    confirmed_with_not_weather: fm.Score | None = None
    """:attr:`confirmed` with those spans put back in: the airports each half of the weather
    days chose, scored on every row of the other half, their non-weather days too."""


def _halves(frame: pl.DataFrame) -> np.ndarray:
    """Each row's half of the test year: 0 for an even ISO week, 1 for an odd one."""
    return (frame.get_column("day").dt.week().to_numpy() % 2).astype(np.int64)


def gate_on_validation(
    tables: Tables, inputs: Sequence[str] = fm.FEATURES
) -> tuple[fm.Model, list[Tested]]:
    """Step 1 of :func:`fit_and_gate` alone: the fit on the years before the validation year,
    gated and scored there. A candidate (a span, an input, a winter tried) is judged on this,
    so choosing among candidates never scores the test year (H2: it is read once, for the
    model published).

    Out: the gating fit and the validation year's tests."""
    window = validation_of(tables.split)
    gating = train(tables, inputs=inputs, before=window.test_first)
    return gating, evaluate(tables, gating, window=window)


def fit_and_gate(
    tables: Tables, inputs: Sequence[str] = fm.FEATURES
) -> tuple[fm.Model, list[Tested], list[Tested]]:
    """LR-H1: set every gate on the validation year, never on the test year.

    1. Fit on the years before the validation year and set the gates on it (:func:`evaluate`):
       per airport, the halves, the under-said drop, the target's skill out of selection, and
       the after-storm gate.
    2. Fit on every year before the test year, with those gates fixed.
    3. Score the test year once, as published (the split-week out-of-selection figures there
       are a second view only; they set nothing).

    Out: the published model, the validation year's tests (of the gating fit) and the test
    year's."""
    gating, validated = gate_on_validation(tables, inputs)
    model = train(tables, inputs=inputs)
    model.published = dict(gating.published)
    model.after = dict(gating.after)
    tested = evaluate(tables, model, set_gates=False)
    return model, validated, tested


def evaluate(  # noqa: PLR0912, PLR0915 - one target and lead's test, gate and views
    tables: Tables, model: fm.Model, window: Split | None = None, *, set_gates: bool = True
) -> list[Tested]:
    """Test every target and lead on ``window`` (the held-out year by default), and, with
    ``set_gates``, set the model's gate there: an airport's chance passes on the whole year and
    on each half (even and odd ISO weeks), and only where the target and lead's skill out of
    selection is at least :data:`snowlight.flights.model.MIN_TARGET_SKILL`; the days after an
    observed storm show it only where those rows, pooled over the airports that passed, pass
    too. Without ``set_gates`` the model's gates are read as they are (fixed on the validation
    year, :func:`fit_and_gate`) and only scored."""
    span = tables.split if window is None else window
    out: list[Tested] = []
    for target in fm.TARGETS:
        every = _frame_of(tables, target).filter(span.inside())
        frame = every.filter(weather_days())
        for lead in fm.leads():
            part = frame.filter(pl.col("lead_class") == lead)
            if (target, lead) not in model.fitted or part.is_empty():
                continue
            x, events, trials, base = _rows(part, target)
            seen, size = _seen(part, target)
            p = model.chance(target, lead, x)
            apts = part.get_column("apt").to_numpy()
            half = _halves(part)
            storm = stormy(part)
            scored = _scorer(p, base, events, trials, seen, size)

            by_airport: dict[str, fm.Score] = {}
            halves: dict[str, tuple[fm.Score, fm.Score]] = {}
            for code in np.unique(apts):
                mask = apts == code
                by_airport[str(code)] = scored(mask)
                halves[str(code)] = (scored(mask & (half == 0)), scored(mask & (half == 1)))
            sure, chose_even, chose_odd = fm.confirmed(
                target,
                {code: pair[0] for code, pair in halves.items()},
                {code: pair[1] for code, pair in halves.items()},
            )
            chose_even_codes = {c for c, pair in halves.items() if fm.passes(target, pair[0])}
            chose_odd_codes = {c for c, pair in halves.items() if fm.passes(target, pair[1])}
            target_ok = sure.units > 0 and sure.skill >= fm.MIN_TARGET_SKILL
            passed = np.zeros(len(part), dtype=bool)
            if set_gates:
                for code, test in by_airport.items():
                    ok = target_ok and fm.passes(target, test, halves[code])
                    model.published[(code, target, lead)] = ok
                    if ok:
                        passed |= apts == code
                # Pooled over the airports that passed, no bin of the chances shown says too low.
                for code in fm.drop_under_said(p, events, trials, apts, passed & ~storm):
                    model.published[(code, target, lead)] = False
                    passed &= apts != code
            else:
                for code in by_airport:
                    if model.is_published(code, target, lead):
                        passed |= apts == code
            days = part.get_column("day").to_numpy()
            rows_after = passed & storm
            after = scored(rows_after)
            lower = fm.skill_lower(
                p[rows_after],
                base[rows_after],
                events[rows_after],
                trials[rows_after],
                days[rows_after],
            )
            # Out of selection (R6-S2): the airports the even weeks chose, scored on their odd-week
            # rows after a storm, and the reverse, so the rows that chose an airport never score
            # its after-storm gate. The gate needs both that score and the shown rows to pass.
            rows_out = (
                storm
                & target_ok
                & (
                    ((half == 1) & np.isin(apts, sorted(chose_even_codes)))
                    | ((half == 0) & np.isin(apts, sorted(chose_odd_codes)))
                )
            )
            after_out = scored(rows_out)
            lower_out = fm.skill_lower(
                p[rows_out], base[rows_out], events[rows_out], trials[rows_out], days[rows_out]
            )
            if set_gates:
                model.after[(target, lead)] = fm.after_storm_ok(
                    after_out, lower_out
                ) and fm.after_storm_ok(after, lower)
            shown_mask = passed & (~storm | model.after.get((target, lead), False))
            shown = np.where(shown_mask, p, base)
            whole = every.filter(pl.col("lead_class") == lead)
            put_back = published_back = confirmed_back = None
            if len(whole) > len(part):
                xa, ea, ta, ba = _rows(whole, target)
                sa, na = _seen(whole, target)
                pa = model.chance(target, lead, xa)
                back = _scorer(pa, ba, ea, ta, sa, na)
                apts_all = whole.get_column("apt").to_numpy()
                half_all = _halves(whole)
                passed_all = np.isin(apts_all, sorted({str(c) for c in apts[passed]}))
                shown_all = passed_all & (~stormy(whole) | model.after.get((target, lead), False))
                put_back = back(np.ones(len(whole), dtype=bool))
                published_back = back(np.ones(len(whole), dtype=bool), np.where(shown_all, pa, ba))
                confirmed_back = back(
                    (half_all == 1) & np.isin(apts_all, sorted(chose_even_codes))
                    | (half_all == 0) & np.isin(apts_all, sorted(chose_odd_codes))
                )
            everything = np.ones(len(part), dtype=bool)
            out.append(
                Tested(
                    target=target,
                    lead=lead,
                    split=(span.test_first, span.test_last),
                    pooled=scored(everything),
                    reliability=fm.reliability(p, events, trials),
                    airports=by_airport,
                    as_published=scored(everything, shown),
                    confirmed=sure,
                    chosen=(chose_even, chose_odd),
                    with_not_weather=put_back,
                    published_with_not_weather=published_back,
                    confirmed_with_not_weather=confirmed_back,
                    after_shown=model.after.get((target, lead), False),
                    reliability_published=fm.reliability(shown, events, trials),
                    after_storm=after,
                    after_lower=lower,
                    after_out=after_out,
                    usual=scored(everything, base),
                    after_out_lower=lower_out,
                    reliability_shown=fm.reliability(
                        p[shown_mask], events[shown_mask], trials[shown_mask]
                    ),
                    reliability_after=fm.reliability(
                        p[passed & storm], events[passed & storm], trials[passed & storm]
                    ),
                    shown_by_month=_by_month(part, shown_mask, p, events, trials),
                )
            )
    return out


def _by_month(
    part: pl.DataFrame,
    mask: np.ndarray,
    p: np.ndarray,
    events: np.ndarray,
    trials: np.ndarray,
) -> list[tuple[str, float, float, float]]:
    """Per month: the units, expected and seen events of the rows in ``mask``."""
    days = part.get_column("day").to_numpy()
    labels = np.array([f"{d.year}-{d.month:02d}" for d in days.astype("datetime64[D]").tolist()])
    out: list[tuple[str, float, float, float]] = []
    for label in sorted(set(labels[mask].tolist())):
        inside = mask & (labels == label)
        out.append(
            (
                label,
                float(trials[inside].sum()),
                float((p[inside] * trials[inside]).sum()),
                float(events[inside].sum()),
            )
        )
    return out


def _scorer(  # noqa: PLR0913, PLR0917 - one target and lead's rows
    p: np.ndarray,
    base: np.ndarray,
    events: np.ndarray,
    trials: np.ndarray,
    seen: np.ndarray,
    size: np.ndarray,
) -> Callable[..., fm.Score]:
    """The test of a subset of one target and lead's rows (a mask), with the model's chances or
    others given (``chances``)."""

    def scored(mask: np.ndarray, chances: np.ndarray | None = None) -> fm.Score:
        said = p if chances is None else chances
        return fm.score(said[mask], base[mask], events[mask], trials[mask], seen[mask], size[mask])

    return scored


def block_chances(tables: Tables, model: fm.Model, table: str) -> pl.DataFrame:
    """The lead-1 cancel chance and usual rate of every block in the test year (``dep`` or
    ``arr``): ``apt``, ``day``, ``block``, ``p``, ``usual``, and ``shown`` (what the files would
    have shown: ``p`` where the airport's chance passed, else ``usual``)."""
    target = f"{table}_canc"
    rows = tables.blocks[table].filter(
        tables.split.inside() & weather_days() & (pl.col("lead_class") == 1)
    )
    if rows.is_empty() or (target, 1) not in model.fitted:
        return pl.DataFrame(
            schema={
                "apt": pl.String,
                "day": pl.Date,
                "block": pl.Int8,
                "p": pl.Float64,
                "usual": pl.Float64,
                "shown": pl.Float64,
            }
        )
    x, _, _, base = _rows(rows, target)
    p = model.chance(target, 1, x)
    apts = rows.get_column("apt").to_list()
    storm = stormy(rows)
    passed = np.asarray(
        [model.shows(code, target, 1, stormy=bool(s)) for code, s in zip(apts, storm, strict=True)]
    )
    return rows.select("apt", "day", "block").with_columns(
        pl.Series("p", p), pl.Series("usual", base), pl.Series("shown", np.where(passed, p, base))
    )


def flight_test(tables: Tables, model: fm.Model, legs: pl.LazyFrame) -> dict[str, float]:
    """A flight's cancel chance in the test year as the higher of its departure block's chance at
    one end and its arrival block's at the other (one cancelled flight counts at both ends),
    against the same rule on the usual rates: flights, cancelled, the Brier score of the model's
    chances, of what the files would have shown (``brier_published``) and of the usual rates."""
    dep = block_chances(tables, model, "dep").rename(
        {
            "apt": "dep_apt",
            "day": "dep_day",
            "block": "dep_block",
            "p": "p_dep",
            "usual": "u_dep",
            "shown": "s_dep",
        }
    )
    arr = block_chances(tables, model, "arr").rename(
        {
            "apt": "arr_apt",
            "day": "arr_day",
            "block": "arr_block",
            "p": "p_arr",
            "usual": "u_arr",
            "shown": "s_arr",
        }
    )
    joined = (
        legs.with_columns(current_code("dep_apt"), current_code("arr_apt"))
        .filter(pl.col("dep_day").is_between(tables.split.test_first, tables.split.test_last))
        .filter(carrier_weather("dep_day"))
        .join(dep.lazy(), on=["dep_apt", "dep_day", "dep_block"])
        .join(arr.lazy(), on=["arr_apt", "arr_day", "arr_block"])
        .with_columns(
            pl.max_horizontal("p_dep", "p_arr").alias("p"),
            pl.max_horizontal("u_dep", "u_arr").alias("u"),
            pl.max_horizontal("s_dep", "s_arr").alias("s"),
            pl.col("cancelled").cast(pl.Float64).alias("y"),
        )
        .select(
            pl.len().alias("flights"),
            pl.col("y").sum().alias("cancelled"),
            ((pl.col("p") - pl.col("y")) ** 2).mean().alias("brier"),
            ((pl.col("s") - pl.col("y")) ** 2).mean().alias("brier_published"),
            ((pl.col("u") - pl.col("y")) ** 2).mean().alias("brier_usual"),
        )
        .collect()
    )
    row = joined.row(0, named=True)
    return {key: float(value or 0.0) for key, value in row.items()}


VALIDATION_CHECKS: Final = (("dep_canc", 1), ("dep_late", 1), ("rough", 1))


VALIDATION_GROUPS: Final = ("day_", "pre_", "obs_")
"""The input groups each checked on the validation year: the whole-day inputs, the run's snow
and ice before the block's day, and the weather observed before the run."""


def validation_day_features(tables: Tables) -> list[tuple[str, str, int, float, float]]:
    """The check behind each input group (:data:`VALIDATION_GROUPS`), made on the validation
    year (the 12 months before the test year), never on the test year: per group, target and
    lead, the validation Brier score of a fit on the rows before it with every input and without
    that group's."""
    start = date(tables.split.test_first.year - 1, tables.split.test_first.month, 1)
    out: list[tuple[str, str, int, float, float]] = []
    for (target, lead), group in itertools.product(VALIDATION_CHECKS, VALIDATION_GROUPS):
        keep = [i for i, name in enumerate(fm.FEATURES) if not name.startswith(group)]
        frame = _frame_of(tables, target).filter(weather_days() & (pl.col("lead_class") == lead))
        fit_rows = frame.filter(pl.col("day") < start)
        check = frame.filter((pl.col("day") >= start) & tables.split.before())
        if fit_rows.is_empty() or check.is_empty():
            continue
        x, events, trials, _ = _rows(fit_rows, target)
        x2, events2, trials2, base2 = _rows(check, target)
        every = fm.fit(x, events, trials).predict(x2)
        fewer = fm.fit(x[:, keep], events, trials).predict(x2[:, keep])
        out.append(
            (
                group,
                target,
                lead,
                fm.score(every, base2, events2, trials2).brier,
                fm.score(fewer, base2, events2, trials2).brier,
            )
        )
    return out


def choose_inputs(
    checks: Sequence[tuple[str, str, int, float, float]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The model's inputs from the checks on the validation year
    (:func:`validation_day_features`), never from the test year: a group stays only when its
    Brier score with it is lower than without it on every check (the main published target
    among them), and a group with no check is left out. Out: the inputs, and the groups left
    out."""
    left = tuple(
        group
        for group in VALIDATION_GROUPS
        if not any(g == group for g, *_ in checks)
        or any(every >= fewer for g, _, _, every, fewer in checks if g == group)
    )
    return fm.without(left), left


def validation_chosen(
    tables: Tables, inputs: Sequence[str]
) -> list[tuple[str, int, float, float, float]]:
    """The chosen inputs themselves scored on the validation year (never the test year), per
    check of :data:`VALIDATION_CHECKS`: the validation Brier score of a fit on the rows before it
    with the chosen inputs, with every input, and with the chosen inputs but the whole-day ones
    (``day_*``)."""
    start = date(tables.split.test_first.year - 1, tables.split.test_first.month, 1)
    chosen = fm.columns(tuple(inputs))
    no_day = fm.columns(tuple(name for name in inputs if not name.startswith("day_")))
    out: list[tuple[str, int, float, float, float]] = []
    for target, lead in VALIDATION_CHECKS:
        frame = _frame_of(tables, target).filter(weather_days() & (pl.col("lead_class") == lead))
        fit_rows = frame.filter(pl.col("day") < start)
        check = frame.filter((pl.col("day") >= start) & tables.split.before())
        if fit_rows.is_empty() or check.is_empty():
            continue
        x, events, trials, _ = _rows(fit_rows, target)
        x2, events2, trials2, base2 = _rows(check, target)
        briers = [
            fm.score(
                fm.fit(x[:, keep], events, trials).predict(x2[:, keep]), base2, events2, trials2
            ).brier
            for keep in (chosen, list(range(len(fm.FEATURES))), no_day)
        ]
        out.append((target, lead, briers[0], briers[1], briers[2]))
    return out


def confirm_inputs(
    inputs: tuple[str, ...], scored: Sequence[tuple[str, int, float, float, float]]
) -> tuple[str, ...]:
    """The inputs the model is fitted on: the chosen ones (:func:`choose_inputs`) when, scored
    together on the validation year (:func:`validation_chosen`), they are no worse than every
    input and no worse than the same without the whole-day inputs on every check; else the
    alternative that is no worse than both others on every check, else every input."""
    no_day = tuple(name for name in inputs if not name.startswith("day_"))
    for at, names in enumerate((inputs, fm.FEATURES, no_day)):
        if all(
            (mine, every, fewer)[at] <= min(mine, every, fewer) for *_, mine, every, fewer in scored
        ):
            return names
    return fm.FEATURES

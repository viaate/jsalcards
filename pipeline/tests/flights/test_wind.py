"""The windy-days check (snowlight.flights.wind): band edges, the day bootstrap, the verdict."""

from datetime import UTC, date, datetime
from typing import cast

import numpy as np
import polars as pl

from snowlight.flights import model as fm
from snowlight.flights import wind
from snowlight.flights.artifact import Artifact


def _bands_of(gust: float | None) -> list[str]:
    frame = pl.DataFrame({"gust": [gust]}, schema={"gust": pl.Float64})
    return [
        band.name
        for band in wind.BANDS
        if frame.select(band.holds(pl.col("gust")).fill_null(value=False)).item()
    ]


def test_band_edges() -> None:
    assert _bands_of(0.0) == ["under 30 kt"]
    assert _bands_of(29.9) == ["under 30 kt"]
    assert _bands_of(30.0) == ["30-34 kt"]
    assert _bands_of(34.9) == ["30-34 kt"]
    assert _bands_of(35.0) == ["35 kt or more"]
    assert _bands_of(44.9) == ["35 kt or more"]
    assert _bands_of(45.0) == ["35 kt or more", "45 kt or more"]
    assert _bands_of(None) == []


def test_the_day_bootstrap_is_fixed_and_draws_whole_days() -> None:
    days = np.array([1, 1, 2, 3, 3, 4, 5, 6])
    events = np.array([3.0, 1.0, 0.0, 2.0, 2.0, 0.0, 1.0, 1.0])
    expected = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    first = wind.ratio_interval(days, events, expected)
    assert first == wind.ratio_interval(days, events, expected)
    low, high = first
    assert low < 10 / 8 < high
    # One day holds every event: a draw without it says none, so the interval reaches 0.
    low, high = wind.ratio_interval(
        np.arange(10), np.array([10.0] + [0.0] * 9), np.ones(10), draws=2000
    )
    assert low == 0.0
    assert high > 1.0
    # The blocks of a day go together: splitting a day into blocks never narrows the interval
    # as if they were days of their own.
    whole = wind.ratio_interval(np.repeat(np.arange(5), 4), np.tile([4.0, 0, 0, 0], 5), np.ones(20))
    assert whole[0] == whole[1] == 1.0
    assert all(np.isnan(wind.ratio_interval(np.array([]), np.array([]), np.array([]))))
    assert all(np.isnan(wind.ratio_interval(np.array([1]), np.array([1.0]), np.array([0.0]))))


def _line(**changes: object) -> wind.Line:
    values: dict[str, object] = {
        "path": "forecast",
        "group": wind.PASSED,
        "target": "dep_canc",
        "band": wind.STRONG,
        "blocks": 500,
        "days": 30,
        "said": 0.02,
        "happened": 0.03,
        "ratio": 1.5,
        "low": 1.16,
        "high": 1.9,
        "log_loss": 0.1,
        "log_loss_usual": 0.12,
        "brier": 0.02,
        "brier_usual": 0.021,
    }
    values.update(changes)
    return wind.Line(**values)  # type: ignore[arg-type]


def test_the_verdict_rule() -> None:
    assert wind.verdict([_line()])[0]
    assert wind.verdict([_line(target="dep_late")])[0]
    assert "dep_canc 1.50 (1.16-1.90)" in wind.verdict([_line()])[1]
    assert not wind.verdict([_line(days=29)])[0]
    assert not wind.verdict([_line(low=1.15)])[0]
    assert not wind.verdict([_line(target="arr_canc")])[0]
    assert not wind.verdict([_line(path="observed")])[0]
    assert not wind.verdict([_line(group=wind.SIX)])[0]
    assert not wind.verdict([_line(band="30-34 kt")])[0]
    assert not wind.verdict([_line(band="45 kt or more")])[0]
    told, why = wind.verdict([_line(low=0.8, ratio=1.1)])
    assert not told
    assert why == (
        "not shown too low: dep_canc 1.10 (0.80-1.90) on 30 days; "
        "too few days to tell: dep_late on 0 days"
    )
    both = [_line(low=0.8, ratio=1.1), _line(target="dep_late", low=0.9, ratio=1.2, days=40)]
    assert wind.verdict(both) == (
        False,
        "not shown too low: dep_canc 1.10 (0.80-1.90) on 30 days; "
        "dep_late 1.20 (0.90-1.90) on 40 days",
    )


def test_the_verdict_never_says_not_too_low_on_too_few_days() -> None:
    # Under MIN_DAYS days, or no rows at all, on a checked line: too few days to tell.
    thin = [_line(days=29, low=0.8), _line(target="dep_late", low=0.9, ratio=1.2, days=40)]
    assert wind.verdict(thin) == (
        False,
        "not shown too low: dep_late 1.20 (0.90-1.90) on 40 days; "
        "too few days to tell: dep_canc 1.50 (0.80-1.90) on 29 days",
    )
    nan = float("nan")
    empty = _line(blocks=0, days=0, ratio=nan, low=nan, high=nan)
    told, why = wind.verdict([empty, _line(target="dep_late", days=1, low=nan, high=nan)])
    assert not told
    assert why == "too few days to tell: dep_canc - (-) on 0 days; dep_late 1.50 (-) on 1 day"
    assert "not shown too low" not in why
    assert wind.verdict([]) == (
        False,
        "too few days to tell: dep_canc on 0 days; dep_late on 0 days",
    )
    # A thin line whose interval lies above the bar is still too few days, not too low.
    assert wind.verdict([_line(days=29)]) == (
        False,
        "too few days to tell: dep_canc 1.50 (1.16-1.90) on 29 days; dep_late on 0 days",
    )


def test_the_measures_of_one_line() -> None:
    rows = pl.DataFrame(
        {
            "day": [date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 2)],
            "p": [0.1, 0.1, 0.2],
            "base": [0.05, 0.05, 0.05],
            "events": [2.0, 0.0, 6.0],
            "trials": [10.0, 10.0, 20.0],
        }
    )
    found = wind.line(rows, "forecast", wind.PASSED, "dep_canc", wind.STRONG)
    assert (found.blocks, found.days) == (3, 2)
    assert np.isclose(found.said, 6 / 40)
    assert np.isclose(found.happened, 8 / 40)
    assert np.isclose(found.ratio, 8 / 6)
    brier = (2 * 0.9**2 + 8 * 0.1**2 + 10 * 0.1**2 + 6 * 0.8**2 + 14 * 0.2**2) / 40
    assert np.isclose(found.brier, brier)
    assert found.log_loss_usual > found.log_loss
    empty = wind.line(rows.clear(), "forecast", wind.PASSED, "dep_canc", wind.STRONG)
    assert empty.blocks == 0
    assert np.isnan(empty.ratio)
    assert np.isnan(empty.said)


def test_a_line_on_too_few_days_has_no_interval() -> None:
    def rows(days: int) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "day": [date(2026, 1, 1 + d) for d in range(days)],
                "p": [0.1] * days,
                "base": [0.05] * days,
                "events": [float(d % 3) for d in range(days)],
                "trials": [10.0] * days,
            }
        )

    for count in (1, 2, wind.INTERVAL_DAYS - 1):
        thin = wind.line(rows(count), "forecast", wind.PASSED, "dep_canc", wind.STRONG)
        assert thin.days == count
        assert np.isfinite(thin.ratio)
        assert np.isnan(thin.low)
        assert np.isnan(thin.high)
        table = wind.markdown([thin])
        assert f"| {thin.ratio:.2f} (-) |" in table
    enough = wind.line(rows(wind.INTERVAL_DAYS), "forecast", wind.PASSED, "dep_canc", wind.STRONG)
    assert np.isfinite(enough.low)
    assert np.isfinite(enough.high)
    assert f"({enough.low:.2f}-{enough.high:.2f})" in wind.markdown([enough])


def test_the_split_tells_a_missed_forecast_from_a_low_model() -> None:
    scored = pl.DataFrame(
        {
            "apt": ["AAA", "AAA", "AAA", "AAA", "AAA", "JFK"],
            "day": [date(2026, 1, d) for d in (1, 2, 3, 4, 5, 6)],
            "block": [0] * 6,
            "target": ["dep_late"] * 6,
            "p": [0.1] * 6,
            "base": [0.05] * 6,
            "events": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "trials": [10.0] * 6,
            "passed": [True, True, True, True, True, False],
            "gust_fc": [10.0, 32.0, 40.0, 40.0, 40.0, 50.0],
            "gust_obs": [36.0, 50.0, 35.0, 20.0, None, 40.0],
        }
    )
    found = {(item.group, item.target, item.band): item for item in wind.splits(scored)}
    assert all(item.path == wind.SPLIT for item in found.values())
    assert len(found) == 2 * len(wind.TARGETS) * len(wind.SPLITS)
    passed = {
        band: item.blocks
        for (group, target, band), item in found.items()
        if group == wind.PASSED and target == "dep_late"
    }
    assert passed == {
        "seen 35 kt or more, forecast under 30 kt": 1,
        "seen 35 kt or more, forecast 30-34 kt": 1,
        "seen 35 kt or more, forecast 35 kt or more": 1,
        "forecast 35 kt or more, seen under 30 kt": 1,  # the block without a report is in none
    }
    hit = found[(wind.PASSED, "dep_late", "seen 35 kt or more, forecast 35 kt or more")]
    assert np.isclose(hit.ratio, 3.0)
    six = found[(wind.SIX, "dep_late", "seen 35 kt or more, forecast 35 kt or more")]
    assert six.blocks == 1
    assert np.isclose(six.ratio, 6.0)
    table = wind.markdown(wind.splits(scored))
    assert "**Seen against forecast, airports that passed**" in table
    assert "**Seen against forecast, EWR JFK LGA PHL BOS DCA**" in table
    assert "| dep_late | seen 35 kt or more, forecast 30-34 kt | 1 | 1 |" in table
    assert "Forecast gust" not in table


def test_the_airports_left_out_by_the_data_are_named() -> None:
    model = cast(fm.Model, _Model())
    passed = wind.left_out(model, ["AAA", "BBB"])
    assert passed == {target: ["AAA"] for target in wind.TARGETS}
    assert wind.left_out_note(["AAA", "BBB"], passed) == (
        "No hourly reports in this backtest's data for 2 airports, left out; of them, passed at "
        "lead 1: dep_canc AAA; dep_late AAA; arr_canc AAA; arr_late AAA."
    )
    assert wind.left_out_note(["BBB"], wind.left_out(model, ["BBB"])).endswith(": none.")


class _Model:
    """The parts of a model the scoring reads: a chance of 0.3 everywhere, AAA passed (not
    after a storm), BBB did not."""

    fitted = dict.fromkeys(((t, 1) for t in wind.TARGETS), None)

    def chance(self, target: str, lead: int, x: np.ndarray) -> np.ndarray:  # noqa: ARG002 - the model's own arguments
        return np.full(len(x), 0.3)

    def is_published(self, airport: str, target: str, lead: int) -> bool:  # noqa: ARG002 - the model's own arguments
        return airport == "AAA"

    def shows(self, airport: str, target: str, lead: int, *, stormy: bool) -> bool:  # noqa: ARG002 - the model's own arguments
        return airport == "AAA" and not stormy


def _rows(
    frame: pl.DataFrame, target: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    kind = target.split("_")[1]
    return (
        np.zeros((frame.height, 1)),
        frame.get_column(kind).cast(pl.Float64).to_numpy(),
        frame.get_column("n").cast(pl.Float64).to_numpy(),
        frame.get_column(f"{kind}_base").to_numpy(),
    )


def test_scored_rows_show_what_the_files_would_have() -> None:
    frame = pl.DataFrame(
        {
            "apt": ["AAA", "AAA", "BBB", "AAA"],
            "day": [date(2026, 1, 1)] * 4,
            "block": [0, 1, 0, 2],
            "lead_class": [1, 1, 1, 2],
            "gust": [40.0, None, 50.0, 40.0],
            "gust_obs": [None, 36.0, 20.0, 40.0],
            "n": [10, 10, 10, 10],
            "canc": [1, 2, 3, 4],
            "late": [2, 3, 4, 5],
            "canc_base": [0.01, 0.01, 0.02, 0.01],
            "late_base": [0.1, 0.1, 0.2, 0.1],
            "storm": [False, True, False, False],
        }
    )
    scored = wind.scored_rows(
        {"dep": frame, "arr": frame},
        cast(fm.Model, _Model()),
        _rows,
        lambda f: f.get_column("storm").to_numpy(),
    )
    assert scored.height == 12  # three lead-1 blocks, four outcomes
    canc = scored.filter(pl.col("target") == "dep_canc").sort("apt", "block")
    assert canc.get_column("p").to_list() == [0.3, 0.01, 0.02]  # after a storm, BBB: usual
    assert canc.get_column("passed").to_list() == [True, True, False]
    assert canc.get_column("gust_fc").to_list() == [40.0, 0.0, 50.0]
    assert canc.get_column("gust_obs").to_list() == [None, 36.0, 20.0]
    found = wind.lines(scored)
    assert len(found) == len(wind.PATHS) * 2 * len(wind.TARGETS) * len(wind.BANDS)
    strong = next(
        item
        for item in found
        if (item.path, item.group, item.target, item.band)
        == ("forecast", wind.PASSED, "dep_canc", wind.STRONG)
    )
    assert strong.blocks == 1  # BBB did not pass; AAA's other block has no forecast gust
    observed = next(
        item
        for item in found
        if (item.path, item.group, item.target, item.band)
        == ("observed", wind.PASSED, "dep_canc", wind.STRONG)
    )
    assert observed.blocks == 1
    assert np.isclose(observed.said, 0.01)
    table = wind.markdown(found)
    assert "**Forecast gust, airports that passed**" in table
    assert "**Observed gust, EWR JFK LGA PHL BOS DCA**" in table
    # Only the lines with blocks: forecast under 30 kt and 35 kt or more, observed 35 kt or more.
    assert table.count("| dep_canc |") == 3
    assert "| dep_canc | 35 kt or more | 1 | 1 |" in table
    assert "| 45 kt or more |" not in table
    assert not wind.scored_rows(
        {"dep": frame.clear(), "arr": frame.clear()},
        cast(fm.Model, _Model()),
        _rows,
        lambda f: f.get_column("storm").to_numpy(),
    ).height


def test_observed_peaks_fall_in_local_blocks() -> None:
    hourly = pl.DataFrame(
        {
            "station": ["JFK", "JFK", "JFK", "JFK", "XXX"],
            "hour": [
                datetime(2026, 1, 2, 3, tzinfo=UTC),  # 22:00 Jan 1 in New York: night of Jan 1
                datetime(2026, 1, 2, 9, tzinfo=UTC),  # 04:00 Jan 2: still the night of Jan 1
                datetime(2026, 1, 2, 10, tzinfo=UTC),  # 05:00 Jan 2: early of Jan 2
                datetime(2026, 7, 2, 16, tzinfo=UTC),  # 12:00 EDT: afternoon
                datetime(2026, 1, 2, 3, tzinfo=UTC),
            ],
            "gust": [30.0, None, 41.0, None, 60.0],
            "wind": [12.0, 36.0, 20.0, 15.0, 30.0],
        }
    )
    stations = pl.DataFrame({"station": ["JFK"], "apt": ["JFK"], "tz": ["America/New_York"]})
    peaks = wind.observed_peaks(hourly.lazy(), stations).sort("day", "block")
    assert peaks.rows() == [
        ("JFK", date(2026, 1, 1), 4, 36.0),
        ("JFK", date(2026, 1, 2), 0, 41.0),
        ("JFK", date(2026, 7, 2), 2, 15.0),
    ]
    assert wind.observed_peaks(hourly.lazy(), stations.clear()).is_empty()


def test_base_frame_reads_the_published_usual_rates() -> None:
    rates = [[0.01 * (block + 1) + 0.001 * month for month in range(12)] for block in range(5)]
    late = [[0.1] * 12 for _ in range(5)]
    artifact = Artifact(
        model=fm.Model(),
        test_first=date(2025, 10, 1),
        test_last=date(2026, 9, 30),
        base={"dep": {"AAA": {"canc": rates, "late": late}}},
        national={"dep": {"canc": late, "late": late}},
    )
    frame = wind.base_frame(artifact, "dep", ["AAA", "ZZZ"])
    assert frame.height == 2 * 5 * 12
    row = frame.filter((pl.col("apt") == "AAA") & (pl.col("block") == 2) & (pl.col("moy") == 3))
    assert np.isclose(row.get_column("canc_base").item(), 0.032)
    national = frame.filter(pl.col("apt") == "ZZZ").get_column("canc_base").unique().to_list()
    assert national == [0.1]
    year = pl.DataFrame({"day": [date(2025, 9, 30), date(2025, 10, 1), date(2026, 9, 30)]})
    assert year.filter(wind.in_year(date(2025, 10, 1), date(2026, 9, 30))).height == 2

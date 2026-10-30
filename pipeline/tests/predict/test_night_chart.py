"""The night chart's rule (``predict/night_chart.py``), option (iv): hourly NBM snowfall, least
bars, the outward range, the heaviest span and the show conditions. Every amount is made up."""

import json
import math
import os
from datetime import UTC, date, datetime, time, timedelta
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from snowlight.predict.ndfd import INCHES_PER_METRE
from snowlight.predict.night_chart import (
    NightInputs,
    ceil_tenths,
    floor_tenths,
    half_value,
    heavy_span,
    night,
    outward,
)
from snowlight.schemas.predictions import NightSnow, check_night, night_window

NY = "America/New_York"
DAY = date(2026, 1, 27)
PASS = datetime.combine(DAY - timedelta(days=1), time(21, 7), tzinfo=ZoneInfo(NY))


def _inputs(snow: list[list[float]] | np.ndarray, moment: datetime = PASS) -> NightInputs:
    start, end = night_window(moment, NY)
    return NightInputs(DAY, NY, start, end, np.asarray(snow, dtype=np.float64))


def _steady(hours: int, rates: list[float]) -> np.ndarray:
    return np.array([rates] * hours, dtype=np.float64)


def test_nine_bars_at_nine_pm_eastern() -> None:
    inputs = _inputs(_steady(9, [0.3, 0.35, 0.4]))
    assert inputs.hours == 9
    found = night(inputs)
    assert found is not None
    assert len(found.least) == 9
    assert found.least[0] == 0.3
    assert found.least[-1] == 2.7
    assert (found.low, found.high) == (2.0, 4.0)
    check_night(found, DAY, NY, PASS.astimezone(UTC))


def _exact(mm: np.ndarray) -> tuple[list[Fraction], Fraction, Fraction, tuple[int, int] | None]:
    """The rule of spec 4.8 on exact inches (whole millimetres over 25.4, as fractions): the
    least bars, the range and the heaviest span, with no float anywhere."""
    hours, schools = mm.shape
    running = np.cumsum(mm.astype(np.int64), axis=0)
    inch = Fraction(254, 10)

    def floor10(v: int) -> Fraction:
        return Fraction(math.floor(Fraction(v) / inch * 10), 10)

    def ceil10(v: int) -> Fraction:
        return Fraction(math.ceil(Fraction(v) / inch * 10), 10)

    least = [floor10(int(running[h].min())) for h in range(hours)]
    lo, hi = int(running[-1].min()), int(running[-1].max())
    if ceil10(hi) < 2:
        low, high = floor10(lo), ceil10(hi)
    else:
        low = Fraction(math.floor(Fraction(lo) / inch))
        high = Fraction(math.ceil(Fraction(hi) / inch))
    heavy = None
    if hours >= 3 and Fraction(lo) / inch >= Fraction(1, 2):
        best = []
        for k in range(schools):
            sums = [int(mm[h : h + 3, k].sum()) for h in range(hours - 2)]
            best.append(sums.index(max(sums)))
        first, last = min(best), max(best) + 3
        if last - first in {3, 4}:
            before = least[first - 1] if first > 0 else Fraction(0)
            if (least[last - 1] - before) / (last - first) >= Fraction(3, 2) * least[-1] / hours:
                heavy = (first, last)
    return least, low, high, heavy


def _from_mm(mm: np.ndarray) -> np.ndarray:
    # As nbm.sample gives them: NBM's metres converted to inches, never rounded one by one.
    return (mm / 1000.0) * INCHES_PER_METRE


def test_the_rule_on_whole_millimetres_is_the_rule_on_exact_inches() -> None:
    # Critic r1 B1: NBM's amounts are whole mm, so totals land exactly on 5.0 or 10.0 in (127
    # and 254 mm) on storm nights. Every bar, range end and heaviest span equals the rule on the
    # exact fractions, whatever the float sum's noise.
    rng = np.random.default_rng(7)
    checked = 0
    for trial in range(3000):
        hours = int(rng.integers(1, 14))
        schools = int(rng.integers(1, 30))
        mm = rng.poisson(rng.uniform(0.5, 12.0), size=(hours, schools)).astype(np.int64)
        if trial % 3 == 0:  # a school on an exact inch or tenth step
            target = int(rng.choice([127, 254, 51, 38, 76, 508]))
            column = rng.multinomial(target, np.full(hours, 1 / hours))
            mm[:, 0] = column
        start = datetime(2026, 1, 27, 12, tzinfo=UTC) - timedelta(hours=hours)
        found = night(NightInputs(DAY, NY, start, start + timedelta(hours=hours), _from_mm(mm)))
        if found is None:
            continue
        least, low, high, heavy = _exact(mm)
        assert [Fraction(v).limit_denominator(10) for v in found.least] == least
        assert Fraction(found.low).limit_denominator(10) == low
        assert Fraction(found.high).limit_denominator(10) == high
        assert found.heavy == heavy
        checked += 1
    assert checked > 1000


@pytest.mark.parametrize("total_mm", [127, 254])
def test_a_school_with_exactly_five_or_ten_inches_reads_five_or_ten(total_mm: int) -> None:
    # 13 hours that sum to 127 or 254 mm in the split critic r1 found drifting below or above.
    split = np.full(13, total_mm // 13)
    split[: total_mm % 13] += 1
    mm = np.stack([split, split + np.eye(13, dtype=np.int64)[12] * 30], axis=1)  # 2nd school more
    start = datetime(2026, 1, 27, 12, tzinfo=UTC) - timedelta(hours=13)
    found = night(NightInputs(DAY, NY, start, start + timedelta(hours=13), _from_mm(mm)))
    assert found is not None
    inches = total_mm / 25.4
    assert found.least[-1] == inches  # 5.0 or 10.0, never 4.9 or 9.9
    assert found.low == inches  # "5 to 7 in", never "4 to 7 in"
    one = night(NightInputs(DAY, NY, start, start + timedelta(hours=13), _from_mm(mm[:, :1])))
    assert one is not None
    assert (one.low, one.high) == (inches, inches)  # "10 in", never "10 to 11 in"
    # A school at exactly 0.5 in still counts for the heaviest span's floor.
    half = np.zeros((9, 1), dtype=np.int64)
    half[4:7, 0] = [4, 5, 4]  # 13 mm
    assert night_heavy_floor_holds(half)


def night_heavy_floor_holds(mm: np.ndarray) -> bool:
    least = floor_tenths(np.cumsum(_from_mm(mm), axis=0).min(axis=1))
    return heavy_span(_from_mm(mm), least) is not None


def test_least_is_the_floor_of_the_least_running_total_never_falling() -> None:
    rng = np.random.default_rng(7)
    for _ in range(200):
        hours = int(rng.integers(1, 14))
        snow = _from_mm(rng.poisson(rng.gamma(0.6, 12.0), size=(hours, int(rng.integers(1, 40)))))
        start = datetime(2026, 1, 27, 12, tzinfo=UTC) - timedelta(hours=hours)
        found = night(NightInputs(DAY, NY, start, start + timedelta(hours=hours), snow))
        if found is None:
            continue
        running = np.cumsum(snow, axis=0)
        least = np.array(found.least)
        assert (np.diff(least) >= 0).all()
        assert (least[:, None] <= running + 1e-5).all()
        totals = running[-1]
        assert found.low <= totals.min() + 1e-5
        assert totals.max() <= found.high + 1e-5
        assert found.low <= found.least[-1] <= found.high
        if found.high >= 2.0:
            assert found.low == int(found.low)
            assert found.high == int(found.high)


def test_the_range_rounds_outward_in_tenths_under_two_inches_and_whole_from_two() -> None:
    assert outward(1.13, 1.71) == (1.1, 1.8)
    assert outward(1.1, 1.7) == (1.1, 1.7)
    assert outward(1.2, 1.95) == (1.0, 2.0)
    assert outward(1.2, 1.9) == (1.2, 1.9)
    assert outward(6.2, 8.4) == (6.0, 9.0)
    # The snap: float noise never adds a step.
    assert outward(0.1 + 0.2, 3.0000000001) == (0.0, 3.0)
    assert outward(4.999998, 10.000002) == (5.0, 10.0)  # whole-mm sums, critic r1 B1
    assert floor_tenths(np.array([0.30000000000000004, 0.29999999999]))[0] == 0.3
    assert ceil_tenths(np.array([1.7000000000000002]))[0] == 1.7


def test_the_half_value_is_the_most_half_the_schools_reach() -> None:
    assert half_value(np.array([0.5, 1.0, 1.2, 3.0])) == 1.2
    assert half_value(np.array([0.5, 1.0, 1.2])) == 1.0
    assert half_value(np.array([2.0])) == 2.0


def test_no_chart_when_half_the_schools_get_under_an_inch() -> None:
    assert night(_inputs(_steady(9, [0.05, 0.1, 0.1, 0.3]))) is None
    assert night(_inputs(_steady(9, [0.05, 0.1, 0.12, 0.3]))) is not None


def test_no_chart_when_a_school_is_not_read() -> None:
    snow = _steady(9, [0.3, 0.35, 0.4])
    snow[4, 1] = np.nan
    assert night(_inputs(snow)) is None


def test_no_chart_past_the_contract_bounds() -> None:
    assert night(_inputs(_steady(9, [12.0, 12.0]))) is None  # 108 in
    assert night(_inputs(_steady(9, [10.0, 10.0]))) is not None


def test_no_chart_when_the_hours_do_not_match_the_window() -> None:
    assert night(_inputs(_steady(8, [0.5, 0.5]))) is None
    assert night(_inputs(np.zeros((9, 0)))) is None


def test_the_last_hour_left_is_one_bar() -> None:
    late = datetime.combine(DAY, time(5, 30), tzinfo=ZoneInfo(NY))
    found = night(_inputs(_steady(1, [1.2, 1.5]), late))
    assert found == NightSnow(least=(1.2,), low=1.2, high=1.5)
    check_night(found, DAY, NY, late.astimezone(UTC))


def _storm(peak: int, schools: int = 3, base: float = 0.1, burst: float = 1.0) -> np.ndarray:
    snow = np.full((9, schools), base)
    snow[peak : peak + 3] = burst
    return snow


def test_heaviest_span_when_every_school_agrees() -> None:
    found = night(_inputs(_storm(4)))
    assert found is not None
    assert found.heavy == (4, 7)


def test_heaviest_span_of_four_hours_when_schools_are_an_hour_apart() -> None:
    snow = _storm(4)
    snow[:, 2] = _storm(5)[:, 0]
    found = night(_inputs(snow))
    assert found is not None
    assert found.heavy == (4, 8)


def test_no_heaviest_span_past_four_hours() -> None:
    snow = _storm(2)
    snow[:, 2] = _storm(5)[:, 0]
    found = night(_inputs(snow))
    assert found is not None
    assert found.heavy is None


def test_no_heaviest_span_when_a_school_gets_under_half_an_inch() -> None:
    snow = _storm(4)
    snow[:, 0] = 0.05
    snow[0, 0] = 0.0
    found = night(_inputs(snow))
    assert found is not None
    assert found.heavy is None


def test_no_heaviest_span_in_steady_snow() -> None:
    found = night(_inputs(_steady(9, [0.4, 0.5])))
    assert found is not None
    assert found.heavy is None


def test_the_rate_test_takes_the_rounded_bars() -> None:
    # Des Moines (critic 3, B2): a 3-hour rise of 1.5 in against 3.7 in over 9 hours is under
    # 1.5 times the mean rate, so no key.
    least = np.array([0.3, 0.7, 1.0, 1.4, 1.8, 2.3, 2.8, 3.3, 3.7])
    snow = np.diff(np.concatenate([[0.0], least]))[:, None]
    assert heavy_span(snow, least) is None
    # A burst passes: 3.3 in over hours 2 to 5 against 1.5 times a mean of 4.6 in over 9 hours.
    least = np.array([0.2, 0.5, 1.6, 2.8, 3.8, 4.3, 4.5, 4.6, 4.6])
    snow = np.diff(np.concatenate([[0.0], least]))[:, None]
    assert heavy_span(snow, least) == (2, 5)


def test_ties_take_the_earliest_hours() -> None:
    snow = np.full((9, 2), 0.2)
    snow[1:4] = 1.0
    snow[5:8] = 1.0
    assert heavy_span(snow, floor_tenths(np.cumsum(snow, axis=0).min(axis=1))) is None
    snow = np.full((9, 2), 0.2)
    snow[1:4] = 1.0
    snow[5:8, 1] = 1.0
    snow[5:8, 0] = 0.9
    found = heavy_span(snow, floor_tenths(np.cumsum(snow, axis=0).min(axis=1)))
    assert found is None  # one school 1 to 4, the other 1 to 4 too, but the far run is not


@pytest.mark.parametrize("hours", [3, 4])
def test_short_windows_still_name_a_span_inside_them(hours: int) -> None:
    moment = datetime.combine(DAY, time(7 - hours, 30), tzinfo=ZoneInfo(NY)) - timedelta(hours=1)
    snow = np.full((hours, 2), 0.1)
    snow[:3] = 1.0
    found = night(_inputs(snow, moment))
    assert found is not None
    assert found.heavy in (None, (0, 3))


GOLDEN = Path(__file__).parent / "golden" / "night_chart.json"
GOLDEN_ZONES = (
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Phoenix",
    "America/Los_Angeles",
)
GOLDEN_CLOCKS = (
    (-1, time(8)),
    (-1, time(17, 7)),
    (-1, time(21, 7)),
    (0, time(0, 7)),
    (0, time(3, 7)),
)


def _golden_snow(k: int, hours: int) -> np.ndarray:
    rate = (0.12, 0.3, 0.6)[k % 3]
    snow = np.array([[rate, rate * 1.2, rate * 1.5]] * hours)
    if k % 2 == 0 and hours >= 6:  # a burst of 3 hours, an hour apart at the third school
        at = hours // 2 - 1
        snow[at : at + 3, :2] += 1.0
        snow[at + 1 : at + 4, 2] += 1.0
    return _from_mm(np.round(snow * 25.4))  # whole millimetres, as NBM gives


def night_chart_json() -> bytes:
    """About 30 nights in every zone, winter and summer, each with what the web must rebuild
    from it: its window, its bar count, its lit instants, its heaviest hours and its mode."""
    rows = []
    k = 0
    for day in (DAY, date(2026, 7, 14)):
        for zone in GOLDEN_ZONES:
            for offset, clock in GOLDEN_CLOCKS:
                if day.month == 7 and clock not in (time(21, 7), time(3, 7)):
                    continue
                moment = datetime.combine(
                    day + timedelta(days=offset), clock, tzinfo=ZoneInfo(zone)
                )
                start, end = night_window(moment, zone)
                hours = round((end - start) / timedelta(hours=1))
                found = night(NightInputs(day, zone, start, end, _golden_snow(k, hours)))
                k += 1
                if found is None:
                    continue
                generated = moment.astimezone(UTC)
                cycle = generated.replace(minute=0) - timedelta(hours=1)
                check_night(found, day, zone, generated)
                heavy = found.heavy
                first = start.astimezone(UTC)
                rows.append(
                    {
                        "zone": zone,
                        "day": day.isoformat(),
                        "generated_at": f"{generated:%Y-%m-%dT%H:%M:%SZ}",
                        "night_at": f"{cycle:%Y-%m-%dT%H:%M:%SZ}",
                        "night": found.to_json_value(),
                        "start": f"{start.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}",
                        "end": f"{end.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}",
                        "instants": len(found.least) + 1,
                        "lit": [] if heavy is None else list(range(heavy[0] + 1, heavy[1] + 1)),
                        "heavy_from": None
                        if heavy is None
                        else f"{first + heavy[0] * timedelta(hours=1):%Y-%m-%dT%H:%M:%SZ}",
                        "heavy_to": None
                        if heavy is None
                        else f"{first + heavy[1] * timedelta(hours=1):%Y-%m-%dT%H:%M:%SZ}",
                        "tenths": found.high < 2,
                    }
                )
    lines = ",\n".join(json.dumps(row, separators=(",", ":")) for row in rows)
    return f"[\n{lines}\n]\n".encode()


def test_the_golden_nights_are_what_the_rule_says() -> None:
    # web/src/data/tests/night.contract.test.ts rebuilds each night's window, bars, lit instants
    # and heaviest hours from this file, and draws its chart.
    data = night_chart_json()
    rows = json.loads(data)
    assert len(rows) >= 25
    assert any(row["night"].get("heavy") for row in rows)
    assert any(not row["night"].get("heavy") for row in rows)
    assert any(row["tenths"] for row in rows)
    assert any(not row["tenths"] for row in rows)
    if os.environ.get("SNOWLIGHT_WRITE_GOLDEN") == "1":
        GOLDEN.write_bytes(data)
    assert GOLDEN.read_bytes() == data

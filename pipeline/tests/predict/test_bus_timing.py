"""The bus hour timing term (predict-next BUS-TIMING): the reader's snow before 07:00 local
(``snow_bus``) is each school's own, never over the window's snow and only growing with it; the
bus hour splits each zone's periods as the spec says in standard and daylight time; off, the
terms are L5's bit for bit; on, more snow, ice or cold, or snow moved before the bus hour,
never lowers the chance; even snow has no timing part in the lower 48 at any snapshot to the
bus hour, so their even factors are exactly 1; the settings are checked; each place's days
still average its class level; and the timing line names a period only on its side of the bus
hour."""

import hashlib
import itertools
import math
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import pytest

from predict import test_forecast_adjust as base
from predict import world
from snowlight.predict import anchor as an
from snowlight.predict import forecast_adjust as fa
from snowlight.predict import forecast_history as history
from snowlight.predict import forecast_live, live_switch, ndfd, serve
from snowlight.predict.artifact import ARTIFACT_PATH, ModelArtifact
from snowlight.predict.exposure import Exposure
from snowlight.predict.forecast_values import (
    DistrictForecast,
    SnowPart,
    bus_share,
    commute_share,
)
from snowlight.predict.geography import REGION_OF
from snowlight.predict.serve import SITUATION_POSITION
from snowlight.predict.situations import SITUATIONS

REGISTERED = fa.AdjustSettings.of(base.CONFIG)
"""As committed (predict-next TIMING-AUTO): no timing, ``o`` 1.0."""
SWITCH = live_switch.rules(base.CONFIG)["bus_timing"]
ON_ARM = live_switch.arm_settings(base.CONFIG, SWITCH, "on")
"""The live switch's on arm: the bus term at its fit ``o`` (0.95), as BUS-TIMING served it."""
BUS = replace(ON_ARM, timing_bus=True)
"""The bus hour term on, at the on arm's ``o`` and the registered ``F``."""
OFF = replace(REGISTERED, timing_bus=False)
"""L5's timing, the snow amount term as registered."""
STANDARD = date(2026, 1, 14)
DAYLIGHT = date(2026, 3, 16)
LOWER_48 = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")
ZONES = (*LOWER_48, "America/Anchorage", "Pacific/Honolulu")


def at_nine(day: date, zone: str) -> datetime:
    return fa.snapshot(day, zone)


def window(
    zone: str, day: date, amounts: Sequence[float], at: datetime | None = None
) -> DistrictForecast:
    """A one-school district's forecast at ``at`` (its 9 PM snapshot by default): ``amounts``
    inches in each window period still to come, with its commute and before-bus snow as the
    reader takes them for one school."""
    at = at_nine(day, zone) if at is None else at
    ends = [end for end in ndfd.window_ends(day) if end > at]
    parts = tuple(
        SnowPart(max(end - ndfd.PERIOD, at), end, float(amount))
        for end, amount in zip(ends, amounts, strict=True)
    )
    snow = float(sum(amounts))
    return DistrictForecast(
        code=max(int(ndfd.snow_bucket(np.array([snow]))[0]), 0),
        ice=0.0,
        feels=25,
        run_time=at,
        snow=snow,
        snow_parts=parts,
        snow_commute=sum(p.snow * commute_share(p.start, p.end, day, zone) for p in parts),
        snow_bus=sum(p.snow * bus_share(p.start, p.end, day, zone) for p in parts),
    )


def even(zone: str, day: date, snow: float, at: datetime | None = None) -> DistrictForecast:
    """``snow`` inches even through the window's hours still to come at ``at``."""
    at = at_nine(day, zone) if at is None else at
    ends = [end for end in ndfd.window_ends(day) if end > at]
    hours = [(end - max(end - ndfd.PERIOD, at)).total_seconds() for end in ends]
    return window(zone, day, [snow * h / sum(hours) for h in hours], at)


def read(
    zone: str, day: date, amounts: Sequence[np.ndarray], at: datetime | None = None
) -> list[DistrictForecast | None]:
    """Each district's forecast through the live reader, as :func:`base.read_districts` for any
    school day: ``amounts[d]`` is district ``d``'s schools by the window's three periods, read
    at ``at`` (the class snapshot by default) from a run issued half an hour before it."""
    district = np.concatenate(
        [np.full(len(item), d, dtype=np.int64) for d, item in enumerate(amounts)]
    )
    stacked = np.concatenate(list(amounts))
    count = stacked.shape[0]
    leaids = tuple(f"{d:07d}" for d in range(len(amounts)))
    schools = history.Schools(
        lat=np.full(count, 40.0),
        lon=np.full(count, -90.0),
        district=district,
        districts=leaids,
        zone_of_district=(zone,) * len(amounts),
    )
    when = fa.snapshot(day, zone) if at is None else at
    run = ndfd.Run(when - timedelta(minutes=30), {}, when - timedelta(minutes=20))
    values = history.RunValues(run)
    ends = ndfd.window_ends(day)
    values.snow = {end: stacked[:, k].copy() for k, end in enumerate(ends)}
    values.ice = {end: np.zeros(count) for end in ends}
    values.feels = {ndfd.bus_time(day, zone): np.full(count, 25.0)}
    found = forecast_live.forecasts(
        schools,
        {leaid: d for d, leaid in enumerate(leaids)},
        (day,),
        datetime.combine(day, time(14), tzinfo=UTC),
        lambda _d: [run],
        lambda _r, _d: values,
        0.5,
        moment=None if at is None else lambda _d, _z: when,
    )
    return [found.get(day, d) for d in range(len(amounts))]


def total(  # noqa: PLR0913, PLR0917 - the forecast, the place and the settings
    found: DistrictForecast,
    usual: float,
    klass: str,
    day: date,
    zone: str,
    settings: fa.AdjustSettings,
    alone: float | None = None,
    most: float | None = None,
) -> float:
    parts = fa.term_parts(found, usual, klass, day, zone, settings, alone, most)
    return 0.0 if parts is None else sum(parts.bounded)


# --- the reader ---------------------------------------------------------------------------------


def test_the_bus_hour_is_7_am_on_the_school_s_clock() -> None:
    assert time(7, 0) == ndfd.BUS_HOUR
    start = datetime(2026, 1, 14, 6, tzinfo=UTC)
    assert bus_share(start, start + ndfd.PERIOD, STANDARD, "America/New_York") == 1.0
    assert bus_share(start, start, STANDARD, "America/New_York") == 0.0


@pytest.mark.parametrize("zone", ZONES)
def test_snow_bus_is_each_school_s_own_and_never_over_the_snow(zone: str) -> None:
    for day in (STANDARD, DAYLIGHT):
        # One school: its periods' snow before the bus hour, each taken even through it.
        one = read(zone, day, [np.array([[1.0, 2.0, 3.0]])])[0]
        assert one is not None
        assert one.snow_bus is not None
        assert one.snow is not None
        by_parts = sum(p.snow * bus_share(p.start, p.end, day, zone) for p in one.snow_parts)
        assert one.snow_bus == pytest.approx(by_parts, abs=1e-3)  # parts kept to 4 places
        assert 0 < one.snow_bus <= one.snow
        # Many schools: never over the snow, and it grows with any school's snow in any period.
        rng = np.random.default_rng(23)
        for count in (2, 3, 5, 7):
            schools = rng.choice(np.array([0.0, 0.2, 1.0, 3.0, 8.0]), size=(count, 3))
            was = read(zone, day, [schools])[0]
            assert was is not None
            assert was.snow is not None
            assert was.snow_bus is not None
            assert was.snow_bus <= was.snow + 1e-12
            for school, period in itertools.product(range(count), range(3)):
                more = schools.copy()
                more[school, period] += 2.0
                now = read(zone, day, [more])[0]
                assert now is not None
                assert now.snow_bus is not None
                assert now.snow_bus >= was.snow_bus - 1e-12, (count, school, period)
                assert now.snow_bus <= (now.snow or 0.0) + 1e-12
    # A school with no value leaves the district unread, never as no snow.
    missing = read(zone, STANDARD, [np.array([[1.0, 2.0, 0.0], [np.nan, np.nan, np.nan]])])[0]
    assert missing is not None
    assert missing.snow is None
    assert missing.snow_bus is None


@pytest.mark.parametrize(
    ("zone", "day", "end_hour", "share"),
    [
        ("America/New_York", STANDARD, 18, 0.0),
        ("America/New_York", DAYLIGHT, 12, 5 / 6),
        ("America/New_York", DAYLIGHT, 18, 0.0),
        ("America/Chicago", STANDARD, 18, 1 / 6),
        ("America/Chicago", DAYLIGHT, 18, 0.0),
        ("America/Denver", STANDARD, 18, 2 / 6),
        ("America/Denver", DAYLIGHT, 18, 1 / 6),
        ("America/Los_Angeles", STANDARD, 18, 3 / 6),
        ("America/Los_Angeles", DAYLIGHT, 18, 2 / 6),
        ("America/Anchorage", STANDARD, 18, 4 / 6),
        ("America/Anchorage", DAYLIGHT, 18, 3 / 6),
        ("Pacific/Honolulu", STANDARD, 18, 5 / 6),
        ("Pacific/Honolulu", DAYLIGHT, 18, 5 / 6),
    ],
)
def test_the_bus_hour_splits_each_zone_s_periods(
    zone: str, day: date, end_hour: int, share: float
) -> None:
    end = datetime.combine(day, time(end_hour), tzinfo=UTC)
    assert bus_share(end - ndfd.PERIOD, end, day, zone) == pytest.approx(share, abs=1e-12)


# --- off: L5 bit for bit ------------------------------------------------------------------------

L5_DIGEST = "ec9c4f0a7d24112d436735e2320595dd63480145b25ff526e1af1e431e5ca2c3"
"""The digest of :func:`l5_grid` at 2272745 (the head before BUS-TIMING), with the registered
settings and with the snow amount term off."""


def l5_grid(
    settings_list: Sequence[fa.AdjustSettings],
    extra: Callable[[tuple[SnowPart, ...], date, str], float] | None = None,
) -> str:
    """Every term, bound, weighed snow, even weight, line value and named period over a grid of
    zones, standard and daylight time, periods' snow, ice, cold, usuals, classes and floors,
    and each zone's even factor, as one digest (rounded to 12 places)."""
    digest = hashlib.sha256()
    for settings in settings_list:
        for zone in ZONES:
            digest.update(repr(round(fa.even_factor(zone, settings), 12)).encode())
            for day in (STANDARD, DAYLIGHT):
                at = fa.snapshot(day, zone)
                ends = [end for end in ndfd.window_ends(day) if end > at]
                for amounts in itertools.product((0.0, 0.3, 2.0, 6.0), repeat=len(ends)):
                    parts = tuple(
                        SnowPart(max(end - ndfd.PERIOD, at), end, amount)
                        for end, amount in zip(ends, amounts, strict=True)
                    )
                    snow = sum(amounts)
                    commute = sum(p.snow * commute_share(p.start, p.end, day, zone) for p in parts)
                    before = None if extra is None else extra(parts, day, zone)
                    for ice, feels in ((0.0, 25), (0.1, -10)):
                        found = DistrictForecast(
                            code=max(int(ndfd.snow_bucket(np.array([snow]))[0]), 0),
                            ice=ice,
                            feels=feels,
                            snow=snow,
                            snow_parts=parts,
                            snow_commute=commute,
                            snow_bus=before,
                        )
                        for usual, klass, half in itertools.product(
                            (0.5, 2.0, 5.0), ("advisory", "warning"), (False, True)
                        ):
                            alone = usual * 0.5 if half else None
                            tp = fa.term_parts(found, usual, klass, day, zone, settings, alone)
                            dt = fa.day_terms(found, usual, klass, day, zone, settings, alone)
                            if tp is None or dt is None:
                                digest.update(b"none")
                                continue
                            values = [*tp.raw, *tp.bounded, tp.weighted, tp.low, tp.high]
                            values.append(-1 if tp.even is None else tp.even)
                            digest.update(repr([round(v, 12) for v in values]).encode())
                            lines = sorted((str(k), round(v, 12)) for k, v in dt.values.items())
                            digest.update(repr(lines).encode())
                            named = None if dt.period is None else (dt.period.start, dt.period.end)
                            digest.update(repr((named, dt.heaviest)).encode())
    return digest.hexdigest()


def test_off_the_terms_are_l5_s_bit_for_bit() -> None:
    settings = [OFF, replace(OFF, snow_amount=False)]
    assert l5_grid(settings) == L5_DIGEST
    # Off, the snow before the bus hour and the bus settings change nothing.
    other = [replace(item, timing_after_bus=0.3, timing_bus_share_max=0.5) for item in settings]

    def before(parts: tuple[SnowPart, ...], day: date, zone: str) -> float:
        return sum(p.snow * bus_share(p.start, p.end, day, zone) for p in parts)

    assert l5_grid(other, before) == L5_DIGEST


# --- on: safety ---------------------------------------------------------------------------------

O_GRID = (0.0, 0.5, 0.95, 1.0)


@pytest.mark.parametrize("zone", ZONES)
def test_on_more_snow_ice_or_cold_or_snow_moved_before_the_bus_never_lowers(zone: str) -> None:
    # Districts of 1 to 7 deciding schools through the reader, standard and daylight time:
    # snow added to any period at one school or at every school, snow moved to a period more
    # before the bus hour at every school, more ice and more cold never lower the day's total,
    # for every o, usual, class, floor and class order cap.
    rng = np.random.default_rng(7)
    for day, count in itertools.product((STANDARD, DAYLIGHT), (1, 3, 7)):
        at = fa.snapshot(day, zone)
        ends = ndfd.window_ends(day)
        share = [
            bus_share(max(end - ndfd.PERIOD, at), end, day, zone) if end > at else -1.0
            for end in ends
        ]
        for _ in range(2):
            schools = rng.choice(np.array([0.0, 0.1, 0.5, 1.0, 3.0, 8.0, 30.0]), size=(count, 3))
            changed = []
            for period in range(3):
                one, every = schools.copy(), schools.copy()
                one[rng.integers(count), period] += 2.0
                every[:, period] += 2.0
                changed += [one, every]
            for early, late in itertools.permutations(range(3), 2):
                if share[early] > share[late] >= 0:
                    # The same snow still to come, moved (a period under way counts its part).
                    moved = schools.copy()
                    kept = ndfd.still_to_come(ends[late], at) / ndfd.still_to_come(ends[early], at)
                    moved[:, early] += moved[:, late] * kept
                    moved[:, late] = 0.0
                    changed.append(moved)
            found = read(zone, day, [schools, *changed])
            was = found[0]
            assert was is not None
            for o, usual, klass, half, most in itertools.product(
                O_GRID, (0.3, 1.5, 6.0), ("advisory", "warning"), (False, True), (None, 0.3, -0.2)
            ):
                settings = replace(BUS, timing_after_bus=o)
                alone = usual / 2 if half else None
                before = total(was, usual, klass, day, zone, settings, alone, most)
                for now in found[1:]:
                    assert now is not None
                    after = total(now, usual, klass, day, zone, settings, alone, most)
                    assert after >= before - 1e-12, (day, count, o, usual, klass, most)
                for ice, feels in ((0.1, 25), (0.25, 25), (0.0, 5), (0.0, -20)):
                    colder = replace(was, ice=ice, feels=feels)
                    after = total(colder, usual, klass, day, zone, settings, alone, most)
                    assert after >= before - 1e-12, (day, count, o, ice, feels)


@pytest.mark.parametrize("zone", LOWER_48)
def test_even_snow_has_no_timing_part_in_the_lower_48_at_any_snapshot_to_the_bus_hour(
    zone: str,
) -> None:
    for day, o in itertools.product((STANDARD, DAYLIGHT), O_GRID):
        settings = replace(BUS, timing_after_bus=o)
        nine = fa.snapshot(day, zone)
        hour = 0
        while nine + timedelta(hours=hour) <= ndfd.bus_time(day, zone) - timedelta(hours=1):
            at = nine + timedelta(hours=hour)
            hour += 1
            for snow, klass in itertools.product((0.3, 2.0, 8.0), ("advisory", "warning")):
                found = even(zone, day, snow, at)
                parts = fa.term_parts(found, 2.0, klass, day, zone, settings)
                assert parts is not None
                assert parts.raw[1] == pytest.approx(0.0, abs=1e-12), (day, o, at, snow)
                moved = fa.adjusted(0.3, 0.1, klass, 2.0, found, day, zone, settings, 0.01, 0.99)
                kinds = set() if moved is None else {line.kind for line in moved.reasons}
                assert not kinds & {"timing", "snow_hours"}, (day, o, at, snow)


@pytest.mark.parametrize("zone", LOWER_48)
def test_even_snow_at_the_usual_reads_usual_through_the_reader_at_any_snapshot(zone: str) -> None:
    # BT1-R1-S4: even snow at the solved usual amount (s == u) reads usual: through the live
    # reader, 1 to 6 schools, at 9 PM and every hourly snapshot to 6 AM, in standard and
    # daylight time, the snow and timing terms sum to 0 and no snow or timing line is written.
    rng = np.random.default_rng(29)
    for day in (STANDARD, DAYLIGHT):
        nine = fa.snapshot(day, zone)
        hour = 0
        while nine + timedelta(hours=hour) <= ndfd.bus_time(day, zone) - timedelta(hours=1):
            at = nine + timedelta(hours=hour)
            hour += 1
            for count in (1, 3, 6):
                totals = rng.choice([0.3, 1.0, 2.5, 6.0, 14.0], size=count)
                # Equal snow in each 6-hour period: even through every hour of the window.
                (found,) = read(zone, day, [np.repeat(totals[:, None] / 3.0, 3, axis=1)], at)
                assert found is not None
                assert found.snow is not None
                assert found.snow > 0.0
                usual = float(found.snow)
                for klass in ("advisory", "warning"):
                    parts = fa.term_parts(found, usual, klass, day, zone, BUS)
                    assert parts is not None
                    where = (day, at, count, klass)
                    assert abs(parts.raw[0] + parts.raw[1]) <= 1e-6, where
                    assert abs(parts.bounded[0] + parts.bounded[1]) <= 1e-6, where
                    moved = fa.adjusted(0.3, 0.1, klass, usual, found, day, zone, BUS, 0.01, 0.99)
                    kinds = set() if moved is None else {line.kind for line in moved.reasons}
                    assert not kinds & {"snow_total", "timing", "snow_hours"}, where


def test_the_even_factors_by_zone() -> None:
    for zone in LOWER_48:
        assert fa.even_factor(zone, BUS) == 1.0
    assert fa.even_factor("America/Anchorage", BUS) == pytest.approx(1.0013, abs=5e-5)
    assert fa.even_factor("Pacific/Honolulu", BUS) == pytest.approx(1.0055, abs=5e-5)
    # L5's, for the record: the West's, Alaska's and Hawaii's were inflated far more.
    assert fa.even_factor("America/Los_Angeles", OFF) == pytest.approx(1.0205, abs=5e-5)
    assert fa.even_factor("America/Anchorage", OFF) == pytest.approx(1.0570, abs=5e-5)
    assert fa.even_factor("Pacific/Honolulu", OFF) == pytest.approx(1.0606, abs=5e-5)


def test_bus_settings_out_of_range_are_refused_and_o_1_is_no_timing() -> None:
    for key, value in (
        ("timing_bus", "on"),
        ("timing_after_bus", -0.1),
        ("timing_after_bus", 1.01),
        ("timing_bus_share_max", 0.0),
        ("timing_bus_share_max", 1.2),
        ("timing_after_bus", "high"),
    ):
        block = dict(base.CONFIG.live_score["forecast_adjustment"])
        block[key] = value
        bad = base.CONFIG.model_copy(
            update={"live_score": {**base.CONFIG.live_score, "forecast_adjustment": block}}
        )
        with pytest.raises(ValueError, match=key):
            fa.AdjustSettings.of(bad)
    block = dict(base.CONFIG.live_score["forecast_adjustment"])
    block.update(timing_bus=True, timing_after_bus=1.0, timing_bus_share_max=1.0)
    none = fa.AdjustSettings.of(
        base.CONFIG.model_copy(
            update={"live_score": {**base.CONFIG.live_score, "forecast_adjustment": block}}
        )
    )
    for zone in ZONES:
        assert fa.even_factor(zone, none) == 1.0
        for amounts in ((4.0, 0.0, 0.0), (0.0, 0.0, 4.0), (0.0, 4.0, 0.0)):
            found = window(zone, STANDARD, amounts[: len(window_ends(STANDARD, zone))])
            parts = fa.term_parts(found, 2.0, "warning", STANDARD, zone, none)
            assert parts is not None
            assert parts.raw[1] == 0.0
            assert parts.weighted == found.snow


@pytest.mark.parametrize("zone", ZONES)
def test_as_committed_no_timing_serves_in_every_zone(zone: str) -> None:
    # TIMING-AUTO decision 1: o 1.0 with the bus term's reader: even factor 1, the timing
    # part 0 and no timing line, whatever the hours of the snow, in every zone and both classes.
    assert REGISTERED.timing_bus is True
    assert REGISTERED.timing_after_bus == 1.0
    assert fa.even_factor(zone, REGISTERED) == 1.0
    periods = len(window_ends(STANDARD, zone))
    for where in range(periods):
        for snow in (0.5, 2.0, 6.0):
            found = window(zone, STANDARD, [snow if m == where else 0.0 for m in range(periods)])
            for klass in ("advisory", "warning"):
                parts = fa.term_parts(found, 2.0, klass, STANDARD, zone, REGISTERED)
                assert parts is not None
                assert parts.raw[1] == 0.0
                assert parts.weighted == found.snow
                moved = fa.adjusted(
                    0.3, 0.1, klass, 2.0, found, STANDARD, zone, REGISTERED, 0.01, 0.99
                )
                kinds = set() if moved is None else {line.kind for line in moved.reasons}
                assert "timing" not in kinds


def window_ends(day: date, zone: str) -> list[datetime]:
    at = fa.snapshot(day, zone)
    return [end for end in ndfd.window_ends(day) if end > at]


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("klass", ["advisory", "warning"])
def test_on_each_place_s_days_still_average_its_class_level(zone: str, klass: str) -> None:
    counts = np.array([[20.0, 10, 8, 4, 2, 1] + [0.0] * 7, [5.0, 2, 10, 10, 5, 2] + [0.0] * 7])
    scale = np.ones(2)
    p0 = np.array([0.12, 0.45])
    factor = np.full(2, fa.even_factor(zone, BUS))
    alone = fa.usual_snow(p0, fa.ice_as_quiet(counts), scale, klass, BUS, even=factor)
    usual = fa.usual_snow(p0, counts, scale, klass, BUS, even=factor, alone=alone)
    assert np.isfinite(usual).all()
    terms = fa.climate_terms(usual, scale, klass, BUS, factor, alone)
    weight = (counts / counts.sum(axis=1, keepdims=True))[:, :, None] * fa.cold_mix(counts)
    z0 = np.log(p0 / (1 - p0))[:, None, None]
    mean = (weight / (1 + np.exp(-(z0 + terms)))).sum(axis=(1, 2))
    assert mean == pytest.approx(p0, abs=1e-6)
    shown = fa.expected(p0, counts, scale, usual, klass, BUS, 0.0, 1.0, even=factor, alone=alone)
    assert shown == pytest.approx(p0, abs=0.005)


# --- the timing line ----------------------------------------------------------------------------


def named(zone: str, day: date, amounts: Sequence[float], klass: str = "warning") -> fa.Terms:
    found = window(zone, day, amounts)
    terms = fa.day_terms(found, 2.0, klass, day, zone, BUS)
    assert terms is not None
    return terms


def splits(zone: str, day: date) -> list[tuple[float, ...]]:
    count = len(window_ends(day, zone))
    return [
        amounts
        for amounts in itertools.product((0.0, 0.5, 2.0, 6.0), repeat=count)
        if sum(amounts) > 0
    ]


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("day", [STANDARD, DAYLIGHT])
def test_a_timing_line_names_a_period_only_on_its_side_of_the_bus_hour(
    zone: str, day: date
) -> None:
    for amounts in splits(zone, day):
        terms = named(zone, day, amounts)
        if terms.period is None:
            continue
        share = bus_share(terms.period.start, terms.period.end, day, zone)
        if terms.values[fa.Term.TIMING] > 0:
            assert share > fa.BUS_SIDE, (amounts, terms.period)
        else:
            assert share < 1 - fa.BUS_SIDE, (amounts, terms.period)


def test_the_named_line_per_zone_at_the_split_period() -> None:
    def the_last(zone: str) -> list[SnowPart]:
        found = []
        for amounts in splits(zone, STANDARD):
            terms = named(zone, STANDARD, amounts)
            if terms.period is not None and terms.period.end.hour == 18:
                found.append(terms.period)
                assert (terms.values[fa.Term.TIMING] > 0) == (zone == "Pacific/Honolulu")
        return found

    # Central: its 12-18Z (1/6 before 7 AM) is never named by a line that raises, and is named
    # by one that lowers where it holds the heaviest snow after the bus hour.
    assert the_last("America/Chicago")
    late = named("America/Chicago", STANDARD, (0.0, 0.0, 6.0))
    assert late.values[fa.Term.TIMING] < 0
    assert late.period is not None
    assert late.period.end.hour == 18
    # Pacific and Alaska standard time: half or more before 7 AM, and not more than half
    # after: named by neither.
    assert the_last("America/Los_Angeles") == []
    assert the_last("America/Anchorage") == []
    # Hawaii: 5/6 before 7 AM, over the capped even weight: may be named by a line that raises.
    hawaii = named("Pacific/Honolulu", STANDARD, (0.0, 6.0))
    assert hawaii.values[fa.Term.TIMING] > 0
    assert hawaii.period is not None
    assert hawaii.period.end.hour == 18
    assert math.isfinite(hawaii.values[fa.Term.SNOW])


def test_the_registered_block_holds_the_bus_settings() -> None:
    block = base.CONFIG.live_score["forecast_adjustment"]
    assert block["timing_bus"] is True  # BT-1: the within-date test passes at o 0.95
    # TIMING-AUTO: no timing serves (o 1.0); the live switch's on arm is the bus term's 0.95
    assert block["timing_after_bus"] == 1.0
    assert block["timing_bus_share_max"] == pytest.approx(0.8)
    assert REGISTERED.timing_after_bus == 1.0
    assert (SWITCH.default, SWITCH.arm_off, SWITCH.arm_on) == ("off", 1.0, 0.95)
    assert (SWITCH.arm_block, SWITCH.arm_key) == ("forecast_adjustment", "timing_after_bus")
    assert ON_ARM.timing_after_bus == pytest.approx(0.95)
    assert replace(ON_ARM, timing_after_bus=1.0) == REGISTERED
    assert world.utc("2026-01-14T12:00:00") == ndfd.bus_time(STANDARD, "America/New_York")


# --- the served path ----------------------------------------------------------------------------

OWNER = {"1300120": (0.16, 0.49), "3605850": (0.06, 0.38), "2008310": (0.1158, 0.4586)}
"""The owner's table's districts with an advisory row and their class levels: Atlanta, Buffalo
and the typical advisory district (the median advisory usual at the national levels)."""


@pytest.mark.parametrize("arm", ["off", "on"])
def test_through_the_served_path_with_the_bus_term_an_advisory_day_is_held_by_the_class_order(
    arm: str,
) -> None:
    # BT1-R1-B1: the owner's table read an advisory day under its snow warning alone, but
    # serving caps it with serve._order_cap over every winter warning situation, and a blizzard
    # warning keeps its class's level (fa.SKIP): with the bus hour term as registered, through
    # serve._order_cap, an advisory day is never over the district's warning class level nor
    # over any warning situation's chance for the same forecast, more snow never lowers it,
    # and Atlanta's advisory reads its warning level in each of the table's cells.
    # TIMING-AUTO: at both of the switch's arms (off: no timing, as committed; on: o 0.95).
    settings = REGISTERED if arm == "off" else ON_ARM
    artifact = ModelArtifact.from_bytes(ARTIFACT_PATH.read_bytes())
    climate = fa.load()
    leaids = sorted(OWNER)
    places = [
        (d, artifact.districts[d].county, REGION_OF.get(artifact.districts[d].state or ""))
        for d in leaids
    ]
    zones = [artifact.districts[d].time_zone or base.EAST for d in leaids]
    anchor = replace(
        an.fit(
            an.AnchorSettings.of(base.CONFIG), Exposure((), {}, {}, {}, {}, {}), an.NO_LABELS, {}
        ),
        climate=climate,
        adjust=settings,
    )
    assert anchor.class_of("blizzard") == "warning"
    assert "blizzard" in serve.ORDERED
    assert "blizzard" in fa.SKIP
    p = np.full((len(leaids), len(SITUATIONS)), 0.05)
    for k, situation in enumerate(SITUATIONS):
        klass = anchor.class_of(situation.key)
        for i, leaid in enumerate(leaids):
            advisory, warning = OWNER[leaid]
            p[i, k] = {"advisory": advisory, "warning": warning, "cold": 0.1}.get(klass or "", 0.05)
    usual, alone, _check = serve._usual_snow(anchor, p, places, zones, an.Grid(0.01, 0.99))
    built, _anchor = base.adjusting_model(base.NATION)
    model = replace(built, p=p, usual_snow=usual, snow_usual=alone, anchor=anchor)

    def published(i: int, key: str, found: DistrictForecast) -> float:
        k = SITUATION_POSITION[key]
        p0, u = float(p[i, k]), float(usual[i, k])
        if key in fa.SKIP or not math.isfinite(u):
            return p0
        klass = anchor.class_of(key)
        assert klass is not None
        cap = serve._order_cap(model, anchor, i, klass, STANDARD, zones[i], found)
        moved = fa.adjusted(
            p0, 0.1, klass, u, found, STANDARD, zones[i], settings, 0.01, 0.99,
            snow_usual=float(alone[i, k]), cap=cap,
        )  # fmt: skip
        return p0 if moved is None else moved.p_no_school

    over = falls = checked = 0
    for i, leaid in enumerate(leaids):
        zone = zones[i]
        level = OWNER[leaid][1]
        periods = len(window_ends(STANDARD, zone))
        # None: even through the window; j: all of it in period j.
        for where in (None, *range(periods)):
            row = []
            for snow in (0.0, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0):
                found = (
                    even(zone, STANDARD, snow)
                    if where is None
                    else window(
                        zone, STANDARD, [snow if m == where else 0.0 for m in range(periods)]
                    )
                )
                chance = published(i, "advisory", found)
                warnings = [published(i, key, found) for key in sorted(serve.ORDERED)]
                # Published to the whole percent, as the class level and the warnings' chances are.
                over += round(chance, 2) > min(round(level, 2), round(min(warnings), 2))
                row.append(chance)
                checked += 1
            falls += sum(b < a - 1e-12 for a, b in itertools.pairwise(row))
            if leaid == "1300120":  # Atlanta: its warning level, 49%, from 4 in on
                assert [round(c * 100) for c in row[4:]] == [49] * 4
    assert (over, falls) == (0, 0)
    assert checked == 8 * sum(1 + len(window_ends(STANDARD, z)) for z in zones)

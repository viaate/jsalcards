"""The why's steps on storm-class days (WHY-TRANSPARENT): the standing file and the forecast
step's fields, checked against the model that serves them. Every number a step states must be
a field, and the steps must add to the chance shown."""

import gzip
import itertools
import math
import random
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest

from predict import world
from predict.test_forecast_adjust import DAY, NATION, SETTINGS, forecast
from snowlight.predict import anchor as an
from snowlight.predict import cli, labels, serve, standing
from snowlight.predict import forecast_adjust as fa
from snowlight.predict.artifact import SITUATION_KEYS
from snowlight.predict.config import PredictConfig
from snowlight.predict.exposure import CLASSES, Exposure, Tally
from snowlight.predict.forecast_values import Forecasts
from snowlight.predict.serve import SITUATION_POSITION, ServeModel, build_model, forecast_file
from snowlight.predict.situations import Situation, WeatherClass
from snowlight.schemas.predictions import ClassBase, Forecast, PredictionsFile
from snowlight.schemas.standing import (
    FLAG_BORROWED,
    FLAG_CLAMP,
    FLAG_ONE,
    FLAG_POOL_NONE,
    FLAG_POOL_REGION,
    StandingFile,
)
from snowlight.schemas.vocab import Reason, Status

CONFIG = PredictConfig.load()
WEB = Path(__file__).resolve().parents[3] / "web" / "src"
EXPOSURE = Exposure(
    seasons=("2015-16", "2024-25"),
    districts={
        "2000004": (5.0, 0.5, 0.0),
        "2900001": (8.0, 3.2, 1.0),
        "2900002": (2.0, 0.0, 0.0),
    },
    counties={"29095": (5.0, 0.5, 0.0)},
    f_ref={"advisory": 4.0, "warning": 1.4, "cold": 0.3},
    nation={"advisory": Tally(495, 667, 200, 20), "warning": Tally(1027, 1071, 200, 20)},
    regions={"advisory": {"ohio_valley": Tally(160, 180, 60, 6)}},
)
"""Own days for three districts, a county's middle for the fourth, none for Utah's; an
advisory region delta for Missouri's districts."""
CLIMATE = replace(NATION, districts={"2900001": {"advisory": (3, 4, 2) + (0,) * 10}}, counties={})
DAYS = (date(2026, 1, 14), date(2026, 1, 15))
AT = world.utc("2026-01-14T03:07:00")
"""After 9 PM on the evening before the first day everywhere: its forecast counts; the
second day's waits for its own snapshot."""


def _model(climate: fa.Climate = CLIMATE, settings: fa.AdjustSettings = SETTINGS) -> ServeModel:
    anchor = an.fit(an.AnchorSettings.of(CONFIG), EXPOSURE, an.NO_LABELS, {})
    anchor = replace(anchor, climate=climate, adjust=settings)
    return build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor
    )


def _file(model: ServeModel, weather: WeatherClass, forecasts: Forecasts) -> PredictionsFile:
    """Every district and every private school in ``weather`` on both days."""
    classes = np.full((len(world.DISTRICTS), 2), int(weather), dtype=np.int64)
    assert model.private is not None
    private = np.full((len(model.private), 2), int(weather), dtype=np.int64)
    built = model.steps
    assert built is not None
    return forecast_file(
        model, classes, DAYS, AT, closed_on=lambda _d: None, last=None, forecasts=forecasts,
        adjust=True, standing=built.file.stamp, private_classes=private,
    )  # fmt: skip


CLASS_OF = {
    "winter_storm_warning": "warning",
    "winter_weather_advisory": "advisory",
    "ice_storm_warning": "warning",
    "blizzard_warning": "warning",
    "extreme_cold_warning": "cold",
    "advisory": "advisory",
    "cold": "cold",
    "lake_snow": "warning",
    "tropical": "warning",
}
"""A class day's class by its base's alert or weather, as web/src/app/steps.ts reads it."""


def _class_of(base: ClassBase) -> str:
    named = base.alert if base.alert is not None else base.weather
    assert named is not None
    return CLASS_OF[str(named)]


def check_steps(  # noqa: PLR0913, PLR0917 - the two files, the regions and the solve's numbers
    made: PredictionsFile,
    found: StandingFile,
    regions: Sequence[str | None],
    private_regions: Sequence[str | None],
    beta: float,
    offset: float,
    grid: an.Grid,
) -> tuple[int, int]:
    """For every class district-day and private class school-day of ``made``, the steps the
    panel shows from ``found`` add up: the start ``v0`` at the unit's offset from the file's own
    numbers (``levels``, ``nodes``, ``ref``, ``winter``, ``region_delta``) with its holds is the
    published base, so ``now + standing + region + held`` is the base with the standing
    derived on its own (``v0 - now - region``); the base and the lines are the chance shown;
    the region and the standing are each within a point of their exact Shapley parts and
    never on the other side of them by more than half a point. The counts of each checked."""
    assert made.standing == found.stamp
    refs = {k: getattr(found.ref, k) for k in CLASSES}
    deltas = {k: {d.region: d.delta for d in getattr(found.region_delta, k)} for k in CLASSES}
    z, w = an._nodes(found.nodes)

    def level(klass: str, o: float) -> float:
        lv = getattr(found.levels, klass)
        return 100 * float(an.sigmoid(lv.alpha + o + np.sqrt(2.0) * lv.tau * z) @ w)

    def one(  # noqa: PLR0913, PLR0917 - the unit's numbers
        day: Forecast,
        klass: str,
        days: Sequence[float] | None,
        region_name: str | None,
        region: int,
        held: int,
    ) -> None:
        base = day.why.base
        assert isinstance(base, ClassBase)
        j = CLASSES.index(klass)
        now = getattr(found.levels, klass).now
        delta = deltas[klass].get(region_name or "", 0.0)
        moved = (
            0.0 if days is None else beta * -math.log((days[j] + offset) / (refs[klass] + offset))
        )
        v0 = round(100 * float(grid.round(np.array(level(klass, delta + moved) / 100))))
        standing_points = v0 - now - region
        assert now + standing_points + region + held == base.points, (klass, days, region_name)
        assert base.points + sum(r.points for r in day.why.reasons) == round(100 * day.p_no_school)
        exact_region = 0.5 * (
            (level(klass, delta) - level(klass, 0.0))
            + (level(klass, delta + moved) - level(klass, moved))
        )
        exact_standing = 0.5 * (
            (level(klass, moved) - level(klass, 0.0))
            + (level(klass, delta + moved) - level(klass, delta))
        )
        assert abs(region - exact_region) <= 1.0
        assert abs(standing_points - exact_standing) <= 1.0
        for shown, exact in ((region, exact_region), (standing_points, exact_standing)):
            assert not (exact > 0.5 and shown < 0)
            assert not (exact < -0.5 and shown > 0)

    def rows(table: object, klass: str) -> dict[int, tuple[int, ...]]:
        return {row[0]: tuple(row[1:]) for row in getattr(table, klass)}

    districts = schools = 0
    for entry in made.districts:
        i = entry.district
        for day in entry.days:
            if not (isinstance(day, Forecast) and isinstance(day.why.base, ClassBase)):
                continue
            klass = _class_of(day.why.base)
            region = rows(found.region, klass).get(i, (0, 0))[0]
            held = sum(rows(found.held, klass).get(i, (0, 0, 0, 0))[:3])
            one(day, klass, found.winter[i], regions[i], region, held)
            districts += 1
    private = found.private
    for k, school in enumerate(made.schools):
        row = private.of[k]
        days, advisory_region, _bits = private.rows[row]
        for index in school.days:
            day = made.outlooks[index]
            if not (isinstance(day, Forecast) and isinstance(day.why.base, ClassBase)):
                continue
            assert day.why.base.of == "private_schools"
            klass = _class_of(day.why.base)
            region = advisory_region if klass == "advisory" else 0
            held = sum(rows(private.held, klass).get(row, (0, 0, 0, 0))[:3])
            one(day, klass, days, private_regions[k], region, held)
            schools += 1
    return districts, schools


@pytest.fixture(scope="module")
def model() -> ServeModel:
    return _model()


def _guard(built: standing.Built) -> list[str]:
    settings = an.AnchorSettings.of(CONFIG)
    return standing.guard(
        built, settings.beta, settings.offset, an.Grid(0.01, 0.99), 4_000_000, 600_000
    )


def _class_days(made: PredictionsFile) -> list[tuple[int, int, Forecast]]:
    return [
        (entry.district, d, day)
        for entry in made.districts
        for d, day in enumerate(entry.days)
        if isinstance(day, Forecast) and isinstance(day.why.base, ClassBase)
    ]


def test_every_class_day_adds_up_from_the_file_alone(model: ServeModel) -> None:
    """For 100% of the class district-days and private class school-days (:func:`check_steps`),
    and the start at each unit's offset is the anchor's own (the file's level from the model's
    fit)."""
    built = model.steps
    assert built is not None
    assert model.anchor is not None
    assert model.private is not None
    assert _guard(built) == []
    found = built.file
    settings = an.AnchorSettings.of(CONFIG)
    heavy = Forecasts({DAYS[0]: {i: forecast(6.0) for i in range(len(world.DISTRICTS))}})
    for weather in (WeatherClass.ADVISORY, WeatherClass.SNOW_WARNING, WeatherClass.COLD):
        made = _file(model, weather, heavy)
        assert len(_class_days(made)) == 2 * len(world.DISTRICTS)
        assert len(made.schools) == len(model.private) > 0
        counted = check_steps(
            made, found, built.regions, built.private_regions, settings.beta, settings.offset,
            an.Grid(0.01, 0.99),
        )  # fmt: skip
        assert counted == (2 * len(world.DISTRICTS), 2 * len(model.private))
        first = _class_days(made)[0][2].why.base
        assert isinstance(first, ClassBase)
        klass = _class_of(first)
        j = CLASSES.index(klass)
        level = getattr(found.levels, klass)
        fit = model.anchor.fits[klass]
        held = {row[0]: sum(row[1:4]) for row in getattr(found.held, klass)}
        for i, _d, day in _class_days(made):
            artifact = world.model().districts[world.DISTRICTS[i]]
            unit = an.Unit(world.DISTRICTS[i], artifact.county, serve._region(artifact.state))
            offset = model.anchor.offsets(unit)[0][j]
            v0 = round(100 * float(an.Grid(0.01, 0.99).round(fit.level(offset, level.alpha))))
            assert v0 + held.get(i, 0) == day.why.base.points


def test_each_winter_ref_and_record_is_the_model_s(model: ServeModel) -> None:
    """``winter`` is Exposure.of, bit 1 exactly where borrowed, ``ref`` the f_ref, the record
    the committed model's y, yd and n by class (no advisory_after), and the sums its rows'."""
    built = model.steps
    assert built is not None
    found = built.file
    artifact = world.model()
    for i, leaid in enumerate(world.DISTRICTS):
        days, borrowed = EXPOSURE.of(leaid, artifact.districts[leaid].county)
        assert found.winter[i] == (None if days is None else tuple(days))
        assert bool(found.flags[i] & FLAG_BORROWED) == (borrowed and days is not None)
    assert (found.ref.advisory, found.ref.warning, found.ref.cold) == (4.0, 1.4, 0.3)
    assert found.winters == (2015, 2024)
    assert found.climate_winters == (2018, 2025)
    assert found.record_winters == (2023, 2024)
    assert found.climate_window == "whole"
    one = artifact.districts[world.DISTRICTS[1]]
    assert one.y is not None
    assert one.yd is not None
    assert one.n is not None
    k = SITUATION_KEYS.index("snow_warning")
    assert found.record.warning[0][0] == 1
    assert found.record.warning[0][1:] == (one.y[k], one.yd[k], one.n[k])
    for klass in CLASSES:
        rows = getattr(found.record, klass)
        assert tuple(getattr(found.record_sum, klass)) == (
            sum(r[1] for r in rows),
            sum(r[2] for r in rows),
            sum(r[3] for r in rows),
        )
        assert all(r[1] + r[2] <= r[3] for r in rows)


def test_the_region_step_is_said_where_it_moves_a_point(model: ServeModel) -> None:
    """Missouri's advisory days carry the region delta; its points are the Shapley share."""
    built = model.steps
    assert built is not None
    assert model.anchor is not None
    assert model.anchor.deltas["advisory"]
    deltas = built.file.region_delta.advisory
    assert [d.region for d in deltas] == ["ohio_valley"]
    rows = {row[0] for row in built.file.region.advisory}
    assert rows <= {1, 2, 3}


def test_usual_snow_and_its_floor_show_inside_the_exact_ones(model: ServeModel) -> None:
    """Each shown u and b by the one rounding rule: where b shows, both are inside the exact
    range; else the chance at the shown u rounds to the published start. ``own`` is the
    district's own climate days and the pool bits Climate.counts' rule."""
    built = model.steps
    assert built is not None
    assert model.anchor is not None
    found = built.file
    k = SITUATION_POSITION["advisory"]
    for i in range(len(world.DISTRICTS)):
        u = float(model.usual_snow[i, k])
        shown = found.usual.advisory[i]
        if not math.isfinite(u):
            assert shown is None
            continue
        assert shown is not None
        b = found.alone.advisory[i]
        p0 = float(model.p[i, k])
        zone = model.time_zone[i]
        if b is None:
            at_u = standing._chance_at(
                p0, shown / 100, u, float(model.snow_usual[i, k]), "advisory", SETTINGS,
                DAYS[0], zone,
            )  # fmt: skip
            assert round(at_u, 2) == p0
        else:
            assert b < shown <= math.floor(u * 100 + 1e-6)
        assert found.own.advisory[i] == (9 if world.DISTRICTS[i] == "2900001" else 0)
        assert not found.flags[i] & FLAG_POOL_NONE["advisory"]
        assert found.flags[i] & FLAG_POOL_REGION["advisory"]  # no county mix: the region's
        assert not found.flags[i] & FLAG_CLAMP["advisory"]  # snow_amount is off here


def test_a_feel_just_under_the_cold_start_reads_as_its_raised_degree(model: ServeModel) -> None:
    """The cold counts on the feel rounded to whole degrees below chill_from (15 F), and the why
    raises the read to whole degrees: 14.3 F rounds to 14, so the cold counts, and reads 15,
    which the file takes (on Nov 19 a 15 here failed the file and every pass went dark)."""
    noted: dict[tuple[int, date], serve.Noted] = {}
    forecasts = Forecasts({DAYS[0]: {0: replace(forecast(6.27, feels=14), feels_read=14.3)}})
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    made = forecast_file(
        model, classes, DAYS, AT, closed_on=lambda _d: None, last=None, forecasts=forecasts,
        adjust=True, noted=noted,
    )  # fmt: skip
    read = {entry.district: entry.days[0] for entry in made.districts}[0]
    assert isinstance(read, Forecast)
    parts = noted[(0, DAYS[0])].parts
    assert parts is not None
    assert parts.raw[3] > 0
    assert read.why.feels == 15


def test_the_forecast_step_says_what_it_read(model: ServeModel) -> None:
    """Read: ``snow`` floored to tenths of the term's snow, the cold where it counts; the day
    whose snapshot has not come: ``fc`` 0; no forecast read: ``fc`` 2; an unknown code:
    ``fc`` 3; the reasons left out to fit: ``fc`` 1."""
    noted: dict[tuple[int, date], serve.Noted] = {}
    forecasts = Forecasts(
        {
            DAYS[0]: {
                0: replace(forecast(6.27, feels=-3), feels_read=-3.4),
                1: forecast(0.0),
                2: forecast(3.0, code=13),
            }
        }
    )
    classes = np.full((len(world.DISTRICTS), 2), int(WeatherClass.ADVISORY), dtype=np.int64)
    made = forecast_file(
        model, classes, DAYS, AT, closed_on=lambda _d: None, last=None, forecasts=forecasts,
        adjust=True, noted=noted,
    )  # fmt: skip
    first = {entry.district: entry.days[0] for entry in made.districts}
    second = {entry.district: entry.days[1] for entry in made.districts}
    read = first[0]
    assert isinstance(read, Forecast)
    parts = noted[(0, DAYS[0])].parts
    assert parts is not None
    assert read.why.snow == 6.2
    assert read.why.snow <= parts.snow < read.why.snow + 0.1
    assert read.why.feels == -3
    assert read.why.fc is None
    quiet = first[1]
    assert isinstance(quiet, Forecast)
    assert quiet.why.snow == 0.0
    unknown = first[2]
    assert isinstance(unknown, Forecast)
    assert unknown.why.fc == 3
    assert unknown.why.snow is None
    missing = first[3]
    assert isinstance(missing, Forecast)
    assert missing.why.fc == 2
    for day in second.values():
        assert isinstance(day, Forecast)
        assert day.why.fc == 0
    assert isinstance(first[4], Forecast)
    assert first[4].why.fc == 0  # Utah's 9 PM is an hour later
    fitted = forecast_file(
        model, classes, DAYS, AT, closed_on=lambda _d: None, last=None, forecasts=forecasts,
        adjust=True, fit=serve.Fit.NO_REASONS,
    )  # fmt: skip
    for entry in fitted.districts:
        first_day, next_day = entry.days
        assert isinstance(first_day, Forecast)
        assert isinstance(next_day, Forecast)
        waits = fa.snapshot(DAYS[0], model.time_zone[entry.district]) > AT
        # 0 comes before 1 by the order: a day before its snapshot says it waits.
        assert (first_day.why.fc, next_day.why.fc) == (0 if waits else 1, 0)
        assert not first_day.why.reasons
    off = forecast_file(
        model, classes, DAYS, AT, closed_on=lambda _d: None, last=None, forecasts=forecasts,
        adjust=False,
    )  # fmt: skip
    assert all(
        isinstance(day, Forecast) and day.why.fc == 7
        for entry in off.districts
        for day in entry.days
    )


def test_the_left_out_order_and_causes(model: ServeModel) -> None:
    """``fc`` by the order 7, 5, 4, 8, 9, 0: each cause the usual snow's solve records."""
    k = SITUATION_POSITION["advisory"]
    situation = Situation.of(WeatherClass.ADVISORY, False)
    for cause in (4, 5, 8, 9):
        usual = model.usual_snow.copy()
        usual[0, k] = math.nan
        causes = model.usual_cause.copy()
        causes[0, k] = cause
        moved = replace(model, usual_snow=usual, usual_cause=causes)
        early = AT - timedelta(hours=12)  # before the snapshot: the cause still comes first
        found = serve.left_out(moved, 0, k, DAYS[0], situation, early, adjust=True)
        assert found == serve.Read(fc=cause)
    assert serve.left_out(model, 0, k, DAYS[0], situation, AT, adjust=False) == serve.Read(fc=7)
    late = serve.left_out(model, 0, k, DAYS[1], situation, AT, adjust=True)
    assert late == serve.Read(fc=0)
    cold = Situation.of(WeatherClass.COLD, False)
    assert (
        serve.left_out(model, 0, SITUATION_POSITION["cold"], DAYS[0], cold, AT, adjust=True) is None
    )
    # No 9 PM forecasts of a class's days anywhere it looks: cause 8.
    empty = replace(NATION, regions={})
    built = _model(empty)
    assert set(built.usual_cause[:, k].tolist()) == {8}
    assert set(built.usual_cause[:, SITUATION_POSITION["cold"]].tolist()) == {-1}


def test_the_guard_refuses_a_file_whose_steps_do_not_add(model: ServeModel) -> None:
    """A wrong winter, alpha, tau, held stage or record sum is refused (no file is written,
    the latest file names no stamp, every panel keeps today's why)."""
    built = model.steps
    assert built is not None
    found = built.file
    winter = list(found.winter)
    winter[0] = (9.9, 9.9, 9.9)
    level = found.levels.advisory
    held = found.held.model_copy(update={"advisory": ((0, 1, 0, 0, 1),)})
    sums = found.record_sum.model_copy(update={"warning": (99, 0, 99)})
    for wrong in (
        found.model_copy(update={"winter": tuple(winter)}),
        found.model_copy(
            update={
                "levels": found.levels.model_copy(
                    update={"advisory": level.model_copy(update={"alpha": level.alpha + 0.5})}
                )
            }
        ),
        found.model_copy(
            update={
                "levels": found.levels.model_copy(
                    update={"advisory": level.model_copy(update={"tau": level.tau * 2})}
                )
            }
        ),
        found.model_copy(update={"held": held}),
        found.model_copy(update={"record_sum": sums}),
    ):
        assert _guard(replace(built, file=wrong)), wrong
    assert _guard(built) == []
    settings = an.AnchorSettings.of(CONFIG)
    assert standing.guard(built, settings.beta, settings.offset, an.Grid(0.01, 0.99), 10, 10)


def test_the_stamp_leaves_out_the_time_and_follows_every_number(model: ServeModel) -> None:
    built = model.steps
    assert built is not None
    found = built.file
    later = found.model_copy(update={"generated_at": datetime(2026, 2, 1, tzinfo=UTC)})
    assert standing.stamp_of(later) == found.stamp
    level = found.levels.warning
    moved = found.model_copy(
        update={
            "levels": found.levels.model_copy(
                update={"warning": level.model_copy(update={"now": level.now + 1})}
            )
        }
    )
    assert standing.stamp_of(moved) != found.stamp
    assert _model().steps is not None
    assert _model().steps.file.stamp == found.stamp  # type: ignore[union-attr]


def test_a_model_with_one_deciding_school_says_so(model: ServeModel) -> None:
    built = model.steps
    assert built is not None
    for i, schools in enumerate(model.eligible):
        assert bool(built.file.flags[i] & FLAG_ONE) == (schools.size == 1)


GROWN = math.ceil(19_139 * 1.05)
"""The deployed districts and 5% more."""


def _widest(random_digits: bool, *, held: bool) -> bytes:
    """The standing file at its widest (every column at its widest, every flag bit, every
    region, the record and private rows at their most), as random digits where asked."""
    rng = random.Random(5)  # noqa: S311 - reproducible widths, not a secret

    def tenths() -> float:
        return round(rng.uniform(100, 999.9), 1) if random_digits else 999.9

    def usual() -> int:
        return rng.randrange(1000, 3000) if random_digits else 3000

    def points() -> int:
        return -rng.randrange(10, 100) if random_digits else -100

    count = GROWN
    winter = tuple((tenths(), tenths(), tenths()) for _ in range(count))
    flags = (4095,) * count
    snow = {
        "advisory": tuple(usual() for _ in range(count)),
        "warning": tuple(usual() for _ in range(count)),
    }
    alone = {
        "advisory": tuple(u - 1 for u in snow["advisory"]),
        "warning": tuple(u - 1 for u in snow["warning"]),
    }
    own = {
        "advisory": tuple(rng.randrange(100, 999) for _ in range(count)),
        "warning": tuple(rng.randrange(100, 999) for _ in range(count)),
    }
    # A region delta enters the advisory class alone (anchor.DELTA_CLASSES).
    region = {"advisory": tuple((i, points(), 1) for i in range(count)), "warning": (), "cold": ()}
    stages = {
        k: tuple((i, points(), points(), points(), 3) for i in range(count)) if held else ()
        for k in CLASSES
    }
    rows = math.ceil(1_400 * 1.05)
    record = {
        k: tuple((i, 333, 333, 999) for i in range(0, count, max(1, count // rows)))
        for k in CLASSES
    }
    private_rows = tuple(((tenths(), tenths(), tenths()), points(), 15) for _ in range(3300))
    level = {"prior": 100, "fit": 100, "now": 100, "storms": 9999, "q": 0.99,
             "shrunk": ("advisory_mean", "advisory_p99", "advisory_warning_mean"),
             "alpha": -2.123456789012345, "tau": 1.512345678901234}  # fmt: skip
    body = {
        "schema_version": 1,
        "generated_at": "2026-11-18T20:07:00Z",
        "directory": {"generated_on": "2026-10-24", "schools": 118211, "districts": count},
        "stamp": "0" * 12,
        "ref": {"advisory": 99.9, "warning": 99.9, "cold": 99.9},
        "nodes": 999,
        "winters": [2015, 2024],
        "climate_winters": [2018, 2025],
        "record_winters": [2015, 2025],
        "climate_window": "still_to_come",
        "levels": dict.fromkeys(CLASSES, level),
        "region_delta": {
            k: [
                {"region": r, "delta": -0.123456789012345, "clipped": True}
                for r in (
                    "northeast",
                    "upper_midwest",
                    "ohio_valley",
                    "southeast",
                    "northern_rockies",
                    "south",
                    "southwest",
                    "northwest",
                    "west",
                )
            ]
            for k in CLASSES
        },
        "winter": winter,
        "flags": flags,
        "usual": snow,
        "alone": alone,
        "own": own,
        "region": region,
        "held": stages,
        "held_clauses": ["advisory_mean", "advisory_p99", "advisory_warning_mean", "district_max"],
        "record": record,
        "record_sum": dict.fromkeys(CLASSES, (9_999_999, 9_999_999, 9_999_999)),
        "private": {
            "rows": private_rows,
            "of": tuple(rng.randrange(3300) for _ in range(math.ceil(22_031 * 1.05))),
            "record": record,
            "record_sum": dict.fromkeys(CLASSES, (9_999_999, 9_999_999, 9_999_999)),
            "held": {
                k: tuple((i, points(), points(), points(), 3) for i in range(3300)) if held else ()
                for k in CLASSES
            },
        },
    }
    return StandingFile.model_validate(body, strict=False).to_json_bytes()


def test_the_standing_file_fits_its_budgets_at_its_widest() -> None:
    """At its widest it is under the raw budget; with random digits and no hold under the
    gzip budget; with every held stage on every unit the gzip budget refuses it (the guard
    then writes no file and every panel keeps today's why)."""
    serve_settings = CONFIG.serve
    widest = _widest(False, held=True)
    assert len(widest) <= serve_settings.standing_budget_raw_bytes
    loose = _widest(True, held=False)
    assert len(loose) <= serve_settings.standing_budget_raw_bytes
    assert (
        len(gzip.compress(loose, compresslevel=9, mtime=0))
        <= serve_settings.standing_budget_gzip_bytes
    )
    worst = _widest(True, held=True)
    assert (
        len(gzip.compress(worst, compresslevel=9, mtime=0))
        > serve_settings.standing_budget_gzip_bytes
    )
    # The quadrature at the configured nodes (999 only widens the number): still over.
    found = StandingFile.model_validate_json(worst).model_copy(
        update={"nodes": an.AnchorSettings.of(CONFIG).nodes}
    )
    schools = len(found.private.of)
    refused = _guard(
        standing.Built(
            file=found,
            served=np.zeros((GROWN, 3), dtype=np.int64),
            private_served=np.zeros((schools, 3), dtype=np.int64),
            regions=(None,) * GROWN,
            private_regions=(None,) * schools,
        )
    )
    assert any(problem.startswith("size ") for problem in refused), refused[:3]


def _rule() -> str:
    """The habit rule as the How Snowlight guesses page says it (web/src/copy-how.ts, the section
    "A district's habit"): the panel itself leaves it there (WHY-PLAIN)."""
    words = (WEB / "copy-how.ts").read_text()
    found = re.search(r"section\('A district\u2019s habit', \[\n(.*?)\n    \]\)", words, re.S)
    assert found
    return found[1]


SHARE_WORDS = {0.5: "half", 0.1: "1 in 10"}
"""The label shares in OWN-rule's words."""


def test_own_rule_says_what_the_labels_count() -> None:
    """The habit rule's words (the How page) state ``labels.outcome_of``'s shares and
    ``weather_positive``'s reasons:
    no school at ``no_school_share`` closed or remote (25% closed + 25% remote + 50% late is no
    school), a late start at ``delayed_share`` (a named non-weather late start is left out),
    school only at most ``open_max_share`` lit with anything (an early dismissal included)."""
    settings = CONFIG.labels
    rule = _rule()
    closed, late, open_ = (
        SHARE_WORDS[settings.no_school_share],
        SHARE_WORDS[settings.delayed_share],
        SHARE_WORDS[round(settings.open_max_share, 2)],
    )
    for text in (
        "For no school and late starts, we count only closings for the weather or with no "
        "reason given.",
        f"A day counts as no school when at least {closed} of its main schools were closed or "
        "remote.",
        f"It counts as a late start when at least {late} of them started late.",
        f"It counts as school when at most {open_} of them were closed, remote, late or let out "
        "early. Here any reason counts.",
        "Other days are left out.",
    ):
        assert text in rule, text
    storm = WeatherClass.SNOW_WARNING
    lit = {
        "a": labels.LitStatus(Status.CLOSED, Reason.WINTER_STORM),
        "b": labels.LitStatus(Status.REMOTE, None),
        "c": labels.LitStatus(Status.DELAYED, Reason.WINTER_STORM),
        "d": labels.LitStatus(Status.DELAYED, None),
    }
    mixed = labels.shares(("a", "b", "c", "d"), lit, storm)
    assert labels.outcome_of(mixed, True, settings) is labels.Outcome.NO_SCHOOL
    power = {s: labels.LitStatus(Status.DELAYED, Reason.POWER_OUTAGE) for s in ("a", "b")}
    other = labels.shares(("a", "b"), power, storm)
    assert other.delayed == 0.0
    assert labels.outcome_of(other, True, settings) is labels.Outcome.UNKNOWN  # left out
    schools = tuple(str(n) for n in range(20))
    for out, outcome in ((2, labels.Outcome.OPEN), (3, labels.Outcome.UNKNOWN)):
        early = {
            s: labels.LitStatus(Status.EARLY_DISMISSAL, Reason.WINTER_STORM) for s in schools[:out]
        }
        assert labels.outcome_of(labels.shares(schools, early, storm), True, settings) is outcome
    late_half = {s: labels.LitStatus(Status.DELAYED, None) for s in schools[:10]}
    assert labels.outcome_of(labels.shares(schools, late_half, storm), True, settings) is (
        labels.Outcome.DELAYED
    )
    assert labels.outcome_of(labels.shares(schools, {}, storm), False, settings) is (
        labels.Outcome.UNKNOWN  # no full morning list: left out
    )


def test_the_rule_numbers_the_steps_state_are_the_config_s() -> None:
    """Each fixed number the words state is the setting the model uses. The panel states none
    of them since WHY-PLAIN; the How Snowlight guesses page (web/src/copy-how.ts) states these,
    and no longer states the usual snow's cap, the class plausibility numbers or the region's
    share in numbers (lead ruling on SPEC WHY-PLAIN r2)."""
    words = (WEB / "copy-how.ts").read_text()
    adjust = fa.AdjustSettings.of(CONFIG)
    plausible = an.AnchorSettings.of(CONFIG).plausibility
    zero_at = adjust.chill_from - adjust.chill_max / adjust.chill_per_degree
    for setting, text in (
        (adjust.shrink_days, "We add {} days from its county or part of the country"),
        (CONFIG.serve.elevation_margin_feet, "at schools up to {} feet below"),
        (adjust.chill_from, "Each degree under {} degrees at 7 AM adds a bit"),
        (zero_at, "down to {} degrees."),
        (adjust.ice_snow * 0.1, "Each 0.1 inch of ice counts like {} inches of snow."),
        (plausible.district_max, "add up to more than {} days off a winter"),
    ):  # fmt: skip
        shown = f"{round(setting, 6):g}"
        assert text.format(shown) in words, text.format(shown)
    assert adjust.snow_amount_floor_ratio == 3.0  # "It is never under a third of the usual amount."
    assert "It is never under a third of the usual amount." in words


def test_a_shown_usual_snow_weighs_even_snow_at_one(model: ServeModel) -> None:
    """Wherever a panel shows u, its zone's even factor is 1.0 (the panel has no words for
    another: spec r5 2b); a zone off 1.0 makes the guard refuse the file."""
    built = model.steps
    assert built is not None
    for klass in standing.SNOW_CLASSES:
        for i, shown in enumerate(getattr(built.file.usual, klass)):
            if shown is not None:
                assert fa.even_factor(model.time_zone[i], SETTINGS) == 1.0
    uneven = replace(SETTINGS, timing_bus=True, timing_after_bus=0.5, timing_bus_share_max=0.05)
    assert {fa.even_factor(zone, uneven) for zone in model.time_zone} != {1.0}
    off = _model(settings=uneven).steps
    assert off is not None
    assert any("weighs even snow" in problem for problem in _guard(off))


def test_a_private_region_part_outside_the_advisory_class_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The private rows hold the advisory region part alone: a school whose region moves
    another class makes the guard refuse the file."""
    plain = _model()
    assert plain.steps is not None
    assert plain.anchor is not None
    assert _guard(plain.steps) == []
    warning = plain.anchor.fits["warning"]
    real = standing.split

    def split(
        fit: an.ClassFit, alpha: float, delta: float, moved: float, total: int
    ) -> tuple[int, int]:
        if fit.prior == warning.prior and fit.alpha == warning.alpha:
            return 1, total - 1  # a region part in the warning class
        return real(fit, alpha, delta, moved, total)

    monkeypatch.setattr(standing, "split", split)
    moved = _model().steps
    assert moved is not None
    assert any("outside the advisory class" in problem for problem in _guard(moved))


def test_each_held_state_is_what_held_the_total() -> None:
    """``held`` by what held the total, over a grid of classes, usuals, snows alone, snows, ice
    and cold: "floor" exactly where the floor lifted it and no bound held, "low" and "high"
    exactly where the bounded total differs from the raw one, "cap" where the class order's cap
    lowers it; at "low" and "floor" the chance with no ice and no cold is the same (the net
    row's words); a planted day like Creekside's gives "high"."""
    settings = fa.AdjustSettings.of(CONFIG)
    zone = "America/New_York"
    seen: set[str | None] = set()
    grid = itertools.product(
        (("warning", 0.45), ("advisory", 0.10)),
        (0.9, 1.77, 5.09),
        (None, 0.25, 0.8),
        (0.0, 0.3, 1.0, 2.0, 3.9, 6.0, 12.0, 25.0),
        (0.0, 0.1),
        (25, 5, -10),
    )
    for (klass, p0), usual, share, snow, ice, feels in grid:
        alone = None if share is None else usual * share
        day = forecast(snow, ice=ice, feels=feels)
        parts = fa.term_parts(day, usual, klass, DAY, zone, settings, alone)
        if parts is None:
            continue
        seen.add(parts.held)
        total, bounded = sum(parts.raw), sum(parts.bounded)
        assert (parts.held == "low") == (bounded > total + fa.HELD_EPS)
        assert (parts.held == "high") == (bounded < total - fa.HELD_EPS)
        floor = abs(bounded - total) <= fa.HELD_EPS and parts.lift > fa.HELD_EPS
        assert (parts.held == "floor") == floor
        if parts.held in {"low", "floor"}:
            bare = replace(day, ice=0.0, feels=None)
            with_both = fa.raw_chance(p0, klass, usual, day, DAY, zone, settings, alone)
            without = fa.raw_chance(p0, klass, usual, bare, DAY, zone, settings, alone)
            assert round(with_both, 2) == round(without, 2)
        capped = fa.term_parts(day, usual, klass, DAY, zone, settings, alone, most=parts.low)
        assert capped is not None
        if bounded > parts.low + fa.HELD_EPS and parts.held != "low":
            assert capped.held == "cap"
    assert {"low", "high", "floor", None} <= seen
    creekside = fa.term_parts(forecast(3.9, feels=13), 1.7659, "warning", DAY, zone, settings)
    assert creekside is not None
    assert creekside.held == "high"


def test_a_hold_that_moves_the_chance_under_a_point_is_a_row() -> None:
    """A plausibility pull that acts is a held row with its mask, even where it moves the
    chance under a whole point; the file's steps still add up."""
    plaus = an.AnchorSettings.of(CONFIG).plausibility
    tight = replace(an.AnchorSettings.of(CONFIG), plausibility=replace(plaus, district_max=1.0))
    fitted = an.fit(tight, EXPOSURE, an.NO_LABELS, {})
    anchor = replace(fitted, climate=CLIMATE, adjust=SETTINGS)
    built = build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor
    ).steps
    assert built is not None
    rows = [row for k in CLASSES for row in getattr(built.file.held, k)]
    assert rows
    assert all(row[4] & standing.ACTED_DISTRICT for row in rows if row[1])
    assert all(row[4] or any(row[1:4]) for row in rows)
    assert _guard(built) == []


class _Host:
    def __init__(self, held: dict[str, bytes], *, fails: bool = False) -> None:
        self.held, self.fails, self.reads = held, fails, list[str]()

    def read(self, key: str) -> bytes | None:
        self.reads.append(key)
        if self.fails:
            raise OSError(key)
        return self.held.get(key)


def test_a_stamp_goes_up_once_and_is_sent_only_with_its_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The standing file goes up with the first file that names its stamp, never again once
    the host holds it (a process start uploads nothing again), and where the host cannot be
    read it goes up; the stamp counts as sent only where its file went up with it or before."""
    key = "v1/predictions/latest.json"
    path = "v1/predictions/standing/abcdef012345.json"
    made = SimpleNamespace(standing="abcdef012345")
    checked = {1: ("abcdef012345", b"{}")}
    fresh = SimpleNamespace(standing_sent=None, standing_checked=checked, host=_Host({}))
    run = cast(cli.Pass, fresh)
    assert cli._standing_extra(run, key, cast(PredictionsFile, made)) == {path: b"{}"}
    assert fresh.host.reads == [path]
    held = SimpleNamespace(standing_sent=None, standing_checked=checked, host=_Host({path: b"x"}))
    assert cli._standing_extra(cast(cli.Pass, held), key, cast(PredictionsFile, made)) == {}
    assert held.standing_sent == "abcdef012345"
    assert "already up" in capsys.readouterr().out
    broken = SimpleNamespace(
        standing_sent=None, standing_checked=checked, host=_Host({}, fails=True)
    )
    assert cli._standing_extra(cast(cli.Pass, broken), key, cast(PredictionsFile, made)) == {
        path: b"{}"
    }
    gone = SimpleNamespace(standing_sent=None, standing_checked={2: None}, host=_Host({}))
    assert cli._standing_extra(cast(cli.Pass, gone), key, cast(PredictionsFile, made)) == {}
    cli._sent_standing(cast(cli.Pass, gone), cast(PredictionsFile, made), {})
    assert gone.standing_sent is None
    assert "named but its file is not in hand" in capsys.readouterr().err
    cli._sent_standing(cast(cli.Pass, fresh), cast(PredictionsFile, made), {path: b"{}"})
    assert fresh.standing_sent == "abcdef012345"

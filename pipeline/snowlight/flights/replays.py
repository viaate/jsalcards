"""Past storm days for the demo (D14): what the model would have said the evening before (the
lead-1 run) next to what happened, always marked as a past day.

A day in the held-out test year is replayed with the model as published (``apart``: test year). A
day before it, such as MCI on Jan 5, 2025, is replayed with a separate fit that leaves its whole
winter out (``apart``: left out), on usual rates from the years before that winter's 12-month
period (:func:`snowlight.flights.train.periods`): the model's weights never saw it either way.
Two choices were made on the validation year, which holds that winter: the usual rates' window
length and which input groups the model uses (:data:`snowlight.flights.build.LEFT_OUT_DAYS`).

Either way the airport's own gate (the held-out test of the published model) decides what is
shown, exactly as the live files do: where its chance did not pass, the replay shows the usual
rate with its bit set, never the model's number. Every block comes from the one run of the
evening before (lead class 1).
"""

from collections.abc import Sequence
from datetime import date, datetime

import polars as pl

from snowlight.flights import model as fm
from snowlight.flights.blocks import BLOCKS
from snowlight.flights.live import per_mille, why_of
from snowlight.flights.spans import weather_days
from snowlight.flights.train import Tables, _rows, stormy
from snowlight.schemas.flights import (
    FlightsHeld,
    FlightsReplay,
    FlightsReplayIndex,
    FlightsReplaySummary,
)


def storm_days(
    tables: Tables, busy: Sequence[str], gate: fm.Model, count: int = 6
) -> list[tuple[str, date]]:
    """The worst rough days of the test year at busy airports whose lead-1 departure cancel
    chance passed the held-out test: the most departures cancelled, at most one per date, ties
    broken by more departures and then by code (the same set on every run). A day in a
    non-weather span (:data:`snowlight.flights.spans.NOT_WEATHER`) is never a past storm."""
    passed = [code for code in busy if gate.is_published(code, "dep_canc", 1)]
    days = (
        tables.days.filter(
            tables.split.inside() & weather_days() & pl.col("apt").is_in(passed) & pl.col("rough")
        )
        .unique(["apt", "day"])
        .with_columns((pl.col("canc") / pl.col("n")).alias("share"))
        .sort(["share", "n", "apt", "day"], descending=[True, True, False, False])
    )
    out: list[tuple[str, date]] = []
    seen: set[date] = set()
    for row in days.iter_rows(named=True):
        if row["day"] in seen:
            continue
        seen.add(row["day"])
        out.append((row["apt"], row["day"]))
        if len(out) == count:
            break
    return out


def replay(  # noqa: PLR0913, PLR0917 - one day, its models and how it was kept apart
    tables: Tables,
    model: fm.Model,
    code: str,
    day: date,
    held: FlightsHeld,
    generated_at: datetime,
    gate: fm.Model | None = None,
) -> FlightsReplay | None:
    """One past day's replay from its lead-1 run; ``None`` when that run or the day's flights are
    not in the tables. ``model`` gives the chances; ``gate`` (the published model; ``model``
    itself when not given) decides where the usual rate is shown instead."""
    gate = gate if gate is not None else model
    blocks = tables.blocks["dep"].filter(
        (pl.col("apt") == code) & (pl.col("day") == day) & (pl.col("lead_class") == 1)
    )
    if blocks.is_empty():
        return None
    run = blocks.get_column("run").min()
    blocks = blocks.filter(pl.col("run") == run).sort("block")
    whole = tables.days.filter(
        (pl.col("apt") == code) & (pl.col("day") == day) & (pl.col("run") == run)
    )
    if whole.is_empty():
        return None
    said: list[int | None] = [None] * len(BLOCKS)
    departures = [0] * len(BLOCKS)
    cancelled = [0] * len(BLOCKS)
    mask = 0
    x, _, _, base = _rows(blocks, "dep_canc")
    chances = model.chance("dep_canc", 1, x)
    storm = stormy(blocks)
    for index, row in enumerate(blocks.iter_rows(named=True)):
        block = int(row["block"])
        departures[block] = int(row["n"])
        cancelled[block] = int(row["canc"])
        if not gate.shows(code, "dep_canc", 1, stormy=bool(storm[index])):
            said[block] = per_mille(float(base[index]))
            mask |= 1 << block
        else:
            said[block] = per_mille(float(chances[index]))
    xr, _, _, rough_base = _rows(whole, "rough")
    rough_usual = not gate.shows(code, "rough", 1, stormy=bool(stormy(whole)[0]))
    rough = float(rough_base[0]) if rough_usual else float(model.chance("rough", 1, xr)[0])
    worst = whole.row(0, named=True)
    return FlightsReplay(
        schema_version=1,
        generated_at=generated_at,
        id=f"{code}-{day.isoformat()}",
        code=code,
        day=day,
        apart=held,
        run=run if isinstance(run, datetime) else generated_at,
        said=(said[0], said[1], said[2], said[3], said[4]),
        said_usual=mask,
        departures=(departures[0], departures[1], departures[2], departures[3], departures[4]),
        cancelled=(cancelled[0], cancelled[1], cancelled[2], cancelled[3], cancelled[4]),
        rough_said=per_mille(rough),
        rough_usual=rough_usual,
        why=why_of(worst),
    )


def index(replays: Sequence[FlightsReplay], generated_at: datetime) -> FlightsReplayIndex:
    """The index of the replays."""
    return FlightsReplayIndex(
        schema_version=1,
        generated_at=generated_at,
        replays=tuple(
            FlightsReplaySummary(
                id=r.id,
                code=r.code,
                day=r.day,
                apart=r.apart,
                said=r.rough_said,
                cancelled=round(1000 * sum(r.cancelled) / max(1, sum(r.departures))),
            )
            for r in replays
        ),
    )

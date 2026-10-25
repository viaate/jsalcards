"""The term levels of every labeled district-day, as the term fit and backtest v2 read them.

* Forecast (snow, ice, cold): the forecast history's code of the district at 21:00 the
  evening before (sample 13 of :mod:`snowlight.predict.forecast_history`, ``code_filled``: a
  cell with no value of an element reads as nothing forecast of it, as the live pass reads
  it), split by :func:`snowlight.predict.terms.levels_of`. A day the history does not hold (the
  school years before 2018-19, a night with no run) is unknown.
* Neighbors: at the day's snapshot (:mod:`snowlight.predict.posts`), the share of the
  district's neighbors a list had shown closed or remote; a day with no snapshot is unknown.

Neighbors are the serving pass's: every other district with a school within the neighbor
distance of one of the district's schools, nearest first, at most 12
(:func:`snowlight.predict.geography.neighbors`), from the training directory.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl

from snowlight.predict.geography import neighbors as near_districts
from snowlight.predict.posts import neighbor_share
from snowlight.predict.terms import UNKNOWN, Term, levels_of, neighbor_level

SNAPSHOT_SAMPLE: Final = 13
CODES_GLOB: Final = "codes-*.parquet"

type Ints = npt.NDArray[np.int64]


def forecast_codes(folder: Path, sample: int = SNAPSHOT_SAMPLE) -> pl.DataFrame:
    """(district, day, code) at ``sample`` from the forecast history's code files."""
    files = sorted(folder.glob(CODES_GLOB))
    if not files:
        return pl.DataFrame(schema={"district": pl.String, "day": pl.Date, "code": pl.Int8})
    return (
        pl.scan_parquet(files)
        .filter(pl.col("sample") == sample)
        .select("district", pl.col("night").alias("day"), pl.col("code_filled").alias("code"))
        .collect()
    )


def training_neighbors(
    table: pl.DataFrame, schools: pl.DataFrame, miles: float
) -> dict[str, tuple[str, ...]]:
    """Each training district's neighbors, nearest first (the serving pass's rule)."""
    districts = table["district"].to_list()
    position = {district: i for i, district in enumerate(districts)}
    located = schools.filter(pl.col("district_id").is_not_null())
    owner = np.array([position.get(d, -1) for d in located["district_id"].to_list()], np.int64)
    found = near_districts(
        located["lon"].to_numpy().astype(np.float64),
        located["lat"].to_numpy().astype(np.float64),
        owner,
        miles,
    )
    return {districts[d]: tuple(districts[e] for e in es) for d, es in found.items()}


def term_levels(
    usable: pl.DataFrame,
    codes: pl.DataFrame,
    snapshots: pl.DataFrame,
    posts: pl.DataFrame,
    neighbors: Mapping[str, Sequence[str]],
) -> dict[Term, Ints]:
    """Every term's level for each row of ``usable`` (the labels a fit uses, in order)."""
    code_of = {
        (district, day): int(code)
        for district, day, code in codes.select("district", "day", "code").iter_rows()
        if code is not None
    }
    snapshot_of: dict[tuple[str, date], datetime] = {
        (district, day): at
        for district, day, at in snapshots.select("district", "day", "snapshot_at").iter_rows()
        if at is not None
    }
    closed: dict[date, dict[str, datetime]] = defaultdict(dict)
    for unit, day, at in posts.select("unit", "day", "first_no_school").iter_rows():
        if at is not None:
            closed[day][unit] = at
    snow: list[int] = []
    ice: list[int] = []
    cold: list[int] = []
    near: list[int] = []
    for district, day in usable.select("district", "day").iter_rows():
        s, i, c = levels_of(code_of.get((district, day)))
        snow.append(s)
        ice.append(i)
        cold.append(c)
        at = snapshot_of.get((district, day))
        if at is None:
            near.append(UNKNOWN)
            continue
        share, _posted = neighbor_share(neighbors.get(district, ()), closed.get(day, {}), at)
        near.append(neighbor_level(share))
    snow_level = np.array(snow, dtype=np.int64)
    return {
        Term.SNOW_ADVISORY: snow_level,
        Term.SNOW_STORM: snow_level.copy(),
        Term.ICE: np.array(ice, dtype=np.int64),
        Term.COLD: np.array(cold, dtype=np.int64),
        Term.NEIGHBORS: np.array(near, dtype=np.int64),
    }

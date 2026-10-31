"""How often each district gets each storm class, and the archive's region tallies of each class
(advisory-sane L3, Addendum A items 2 and 5): ``data/predict/exposure.json.gz``.

A district's exposure ``f`` to a class is its school days of that class a winter, averaged over
the registered winters (``live_score.standing.seasons``, 2015-16 to 2024-25), from the weather
history (``weather.parquet``: one row per district and alert day, the class of the day). The
classes are the serving classes of ``live_score.classes``: ``advisory`` (winter weather, freezing
rain and lake effect snow advisories), ``warning`` (winter storm, lake effect snow, ice storm,
blizzard and tropical warnings) and ``cold`` (extreme cold warnings).

The history classes the districts that have eligible schools (``districts.parquet``
``eligible``); a district with none (a charter or virtual district) has no history of its own,
so it takes the median exposure of its county's districts (``from_county``), else none.

It also lists the districts with any tropical storm or hurricane warning day in those winters
(``tropical``), and the counties with such a district: a warning-class sentence names the class
by them (``ClassBase.tropical``: "storm warnings" where the district gets tropical ones, "winter
storm warnings" where it never has), never a tropical storm for a district that has had none.

The file also keeps, per class, the archive's labeled days of the nation and of each NOAA region
(closed ``y`` of ``n``, the distinct dates and the busiest date's days), the only archive counts
the class anchor reads (:func:`snowlight.predict.anchor.region_delta`): never a level, only a
relative region delta where :func:`snowlight.predict.pool.level_supported` holds.

Codes and counts only: NCES LEAIDs, county FIPS, NOAA region names and day counts.
"""

import gzip
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Final

import polars as pl

from snowlight.predict.config import PIPELINE_ROOT
from snowlight.predict.geography import REGION_OF

EXPOSURE_PATH: Final = PIPELINE_ROOT / "data" / "predict" / "exposure.json.gz"
SCHEMA_VERSION: Final = 1
CLASSES: Final = ("advisory", "warning", "cold")
"""The serving classes, in the order of each district's numbers."""
CLASS_OF_WEATHER: Final[Mapping[int, str]] = {
    1: "advisory",
    2: "warning",
    3: "cold",
    4: "warning",
    5: "warning",
    6: "warning",
    7: "warning",
}
"""The serving class of each history weather class (:class:`~snowlight.predict.situations.
WeatherClass`: advisory 1, tropical 2, cold 3, lake snow 4, snow warning 5, ice 6, blizzard 7),
as ``live_score.classes`` registers it."""
TROPICAL: Final = 2
"""The history weather class of a tropical storm or hurricane warning day."""
_TENTHS: Final = 10
_SEASON_MONTH: Final = 8
"""A school day from August on is in the winter that starts that year."""


def season_of(day: date) -> int:
    """The winter a school day is in, by its first year (2024 for 2024-25)."""
    return day.year if day.month >= _SEASON_MONTH else day.year - 1


def season_years(seasons: Sequence[str]) -> tuple[int, int]:
    """The first and last winter of ``["2015-16", "2024-25"]``, by first year.

    Raises:
        ValueError: they are not two winters, first to last.
    """
    if len(seasons) != 2:  # noqa: PLR2004 - first and last
        raise ValueError(f"seasons are a first and a last winter, not {list(seasons)}")
    first, last = (int(item.split("-", 1)[0]) for item in seasons)
    if last < first:
        raise ValueError(f"the last winter {last} is before the first {first}")
    return first, last


@dataclass(frozen=True, slots=True)
class Tally:
    """Archive labeled days of a class at one place: ``y`` closed of ``n``, on ``dates`` dates,
    the busiest date holding ``busiest`` of them."""

    y: int
    n: int
    dates: int
    busiest: int


@dataclass(frozen=True, slots=True)
class Exposure:
    """The exposure file, read."""

    seasons: tuple[str, ...]
    districts: Mapping[str, tuple[float, float, float]]
    """LEAID to its days a winter of each class (:data:`CLASSES` order), from its own history."""
    counties: Mapping[str, tuple[float, float, float]]
    """County FIPS to the median of its districts' (for districts with no history)."""
    f_ref: Mapping[str, float]
    """Per class, the national median of ``f`` over districts with at least one day of it."""
    nation: Mapping[str, Tally]
    regions: Mapping[str, Mapping[str, Tally]]
    """Class to NOAA region to its archive tally."""
    tropical: frozenset[str] = frozenset()
    """The LEAIDs with any tropical storm or hurricane warning day in the winters."""
    tropical_counties: frozenset[str] = frozenset()
    """The county FIPS with any such district."""

    def of(self, leaid: str | None, county: str | None) -> tuple[tuple[float, ...] | None, bool]:
        """A unit's days a winter per class and whether they are its county's (``None``: not
        known, the unit takes the reference)."""
        if leaid is not None and leaid in self.districts:
            return self.districts[leaid], False
        if county is not None and county in self.counties:
            return self.counties[county], True
        return None, False

    def has_tropical(self, leaid: str | None, county: str | None) -> bool:
        """Whether the exposure a unit takes (:meth:`of`: its own, else its county's) holds any
        tropical storm or hurricane warning day; false where it is not known."""
        if leaid is not None and leaid in self.districts:
            return leaid in self.tropical
        if county is not None and county in self.counties:
            return county in self.tropical_counties
        return False


def _tally(value: object) -> Tally:
    if not isinstance(value, list) or len(value) != 4:  # noqa: PLR2004 - y, n, dates, busiest
        raise ValueError(f"a tally is [y, n, dates, busiest], not {value!r}")
    y, n, dates, busiest = (int(item) for item in value)
    return Tally(y, n, dates, busiest)


def _numbers(value: object) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != len(CLASSES):
        raise ValueError(f"a district's exposure is {len(CLASSES)} numbers, not {value!r}")
    a, w, c = (int(item) / _TENTHS for item in value)
    return a, w, c


def load(path: Path = EXPOSURE_PATH) -> Exposure:
    """Read the exposure file.

    Raises:
        OSError: it cannot be read.
        ValueError: it is not one.
    """
    return parse(json.loads(gzip.decompress(path.read_bytes())), path.name)


def parse(body: object, name: str = "exposure") -> Exposure:
    """An exposure file's body (:func:`build`), read.

    Raises:
        ValueError: it is not one.
        KeyError: it lacks a part.
    """
    if not isinstance(body, dict) or body.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{name}: not an exposure file of schema {SCHEMA_VERSION}")
    if tuple(body["classes"]) != CLASSES:
        raise ValueError(f"{name}: classes {body['classes']} are not {list(CLASSES)}")
    # Required: with no list, a coastal district's warning sentence would name winter storms
    # alone; a file without it does not read, and the pass serves the class levels alone.
    tropical = body["tropical"]
    if not isinstance(tropical, dict) or not all(
        isinstance(tropical.get(key), list) for key in ("districts", "counties")
    ):
        raise ValueError(f"{name}: tropical is not its districts and counties")
    return Exposure(
        seasons=tuple(str(item) for item in body["seasons"]),
        districts={str(k): _numbers(v) for k, v in body["districts"].items()},
        counties={str(k): _numbers(v) for k, v in body["counties"].items()},
        f_ref={str(k): float(v) for k, v in body["f_ref"].items()},
        nation={str(k): _tally(v) for k, v in body["nation"].items()},
        regions={
            str(c): {str(r): _tally(v) for r, v in found.items()}
            for c, found in body["regions"].items()
        },
        tropical=frozenset(str(item) for item in tropical["districts"]),
        tropical_counties=frozenset(str(item) for item in tropical["counties"]),
    )


def _tenths(value: float) -> int:
    return round(value * _TENTHS)


def build(
    weather: pl.DataFrame, districts: pl.DataFrame, labels: pl.DataFrame, seasons: Sequence[str]
) -> dict[str, object]:
    """The exposure file's body from the weather history (``district``, ``day``, ``weather``),
    the history's districts (``district``, ``state``, ``county``, ``eligible``) and the
    archive's labels (``district``, ``day``, ``outcome``, ``weather``)."""
    first, last = season_years(seasons)
    winters = last - first + 1
    known = districts.filter(pl.col("eligible") > 0)
    within = weather.with_columns(
        season=pl.when(pl.col("day").dt.month() >= _SEASON_MONTH)
        .then(pl.col("day").dt.year())
        .otherwise(pl.col("day").dt.year() - 1),
        klass=pl.col("weather").cast(pl.Int64).replace_strict(CLASS_OF_WEATHER, default=None),
    ).filter(pl.col("season").is_between(first, last) & pl.col("klass").is_not_null())
    days = within.group_by("district", "klass").len()
    stormy = {
        str(leaid)
        for leaid in within.filter(pl.col("weather").cast(pl.Int64) == TROPICAL)["district"]
    }
    count: dict[str, dict[str, int]] = {}
    for leaid, klass, n in days.iter_rows():
        count.setdefault(str(leaid), {})[str(klass)] = int(n)
    own: dict[str, list[int]] = {}
    by_county: dict[str, list[list[int]]] = {}
    tropical: set[str] = set()
    tropical_counties: set[str] = set()
    for leaid, county in known.select("district", "county").iter_rows():
        found = count.get(str(leaid), {})
        values = [_tenths(found.get(c, 0) / winters) for c in CLASSES]
        own[str(leaid)] = values
        if str(leaid) in stormy:
            tropical.add(str(leaid))
        if county is not None:
            by_county.setdefault(str(county), []).append(values)
            if str(leaid) in stormy:
                tropical_counties.add(str(county))
    counties = {
        county: [round(median(v[i] for v in values)) for i in range(len(CLASSES))]
        for county, values in sorted(by_county.items())
    }
    f_ref: dict[str, float] = {}
    for i, klass in enumerate(CLASSES):
        some = [v[i] / _TENTHS for v in own.values() if v[i] > 0]
        f_ref[klass] = round(float(median(some)), 4) if some else 0.0
    nation, regions = archive_tallies(labels, districts)
    return {
        "schema_version": SCHEMA_VERSION,
        "seasons": list(seasons),
        "classes": list(CLASSES),
        "f_ref": f_ref,
        "districts": dict(sorted(own.items())),
        "counties": counties,
        "tropical": {"districts": sorted(tropical), "counties": sorted(tropical_counties)},
        "nation": {c: [t.y, t.n, t.dates, t.busiest] for c, t in nation.items()},
        "regions": {
            c: {r: [t.y, t.n, t.dates, t.busiest] for r, t in sorted(found.items())}
            for c, found in regions.items()
        },
    }


def _tally_of(rows: pl.DataFrame) -> Tally:
    if rows.is_empty():
        return Tally(0, 0, 0, 0)
    per_day = rows.group_by("day").len()
    return Tally(
        y=int((rows["outcome"] == "no_school").sum()),
        n=rows.height,
        dates=per_day.height,
        busiest=int(per_day["len"].max()),  # type: ignore[arg-type]
    )


def archive_tallies(
    labels: pl.DataFrame, districts: pl.DataFrame
) -> tuple[dict[str, Tally], dict[str, dict[str, Tally]]]:
    """Per class, the archive's labeled days (no school, delayed or open) of the nation and of
    each NOAA region (by the district's state)."""
    states = districts.select("district", "state")
    rows = (
        labels.filter(pl.col("outcome").is_in(["no_school", "delayed", "open"]))
        .with_columns(
            klass=pl.col("weather").cast(pl.Int64).replace_strict(CLASS_OF_WEATHER, default=None)
        )
        .filter(pl.col("klass").is_not_null())
        .join(states, on="district", how="left")
        .with_columns(
            region=pl.col("state").replace_strict(dict(REGION_OF), default=None),
        )
    )
    nation: dict[str, Tally] = {}
    regions: dict[str, dict[str, Tally]] = {}
    for klass in CLASSES:
        mine = rows.filter(pl.col("klass") == klass)
        nation[klass] = _tally_of(mine)
        regions[klass] = {
            str(region): _tally_of(mine.filter(pl.col("region") == region))
            for region in sorted({r for r in mine["region"].to_list() if r is not None})
        }
    return nation, regions


def write(body: Mapping[str, object], path: Path = EXPOSURE_PATH) -> int:
    """Write the file (gzip, no timestamp, so the same inputs give the same bytes); its size."""
    data = gzip.compress(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode(),
        compresslevel=9,
        mtime=0,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)

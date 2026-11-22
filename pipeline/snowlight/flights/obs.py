"""The weather that came: hourly airport weather reports from the IEM ASOS archive, reduced to the
five weather kinds of an airport's own record (D8).

Source (public, no key): ``https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py``, routine
hourly reports, many stations a request, times in UTC. A report counts for the hour it was made
in after adding 10 minutes, so the 06:53 report describes the 07:00 hour.

Each hour gets the worst of its reports' flags:

* ``frz``: freezing rain or drizzle, or ice pellets (``FZRA``, ``FZDZ``, ``PL``);
* ``snow``: snow that is falling, not blowing or drifting (``SN`` without ``BL`` or ``DR``);
* ``thunder``: thunder at or near the airport (``TS``, ``VCTS``);
* ``fog``: a ceiling under 500 feet or visibility under 1 mile;
* ``wind``: wind of 30 knots or gusts of 40 knots or more.

An airport block (:mod:`snowlight.flights.blocks`) has the kind of its worst hours: freezing rain
(1 hour or more), else snow (2 hours or more), else thunder (1 hour or more), else low clouds and
fog (2 hours or more), else strong wind (1 hour or more), else none.
"""

import io
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Final

import polars as pl

ASOS_URL: Final = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
FIELDS: Final = (
    "sknt",
    "gust",
    "vsby",
    "skyc1",
    "skyc2",
    "skyc3",
    "skyl1",
    "skyl2",
    "skyl3",
    "wxcodes",
)
FLAGS: Final = ("frz", "snow", "thunder", "fog", "wind")

FOG_CEILING_FEET: Final = 500
FOG_VISIBILITY_MILES: Final = 1.0
WIND_KNOTS: Final = 30
GUST_KNOTS: Final = 40


class Kind(IntEnum):
    """The weather kind of an airport block (D8), worst first."""

    NONE = 0
    FRZ = 1
    SNOW = 2
    THUNDER = 3
    FOG = 4
    WIND = 5


KINDS: Final = (Kind.FRZ, Kind.SNOW, Kind.THUNDER, Kind.FOG, Kind.WIND)
MIN_HOURS: Final[dict[Kind, int]] = {
    Kind.FRZ: 1,
    Kind.SNOW: 2,
    Kind.THUNDER: 1,
    Kind.FOG: 2,
    Kind.WIND: 1,
}


def request_url(stations: Sequence[str], year: int, month: int) -> str:
    """One month of routine reports for ``stations``, UTC."""
    end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)  # noqa: PLR2004
    return _url(
        stations,
        datetime(year, month, 1, tzinfo=UTC),
        datetime(end_year, end_month, 1, tzinfo=UTC),
    )


def window_url(stations: Sequence[str], start: datetime, end: datetime) -> str:
    """The routine reports for ``stations`` from ``start`` to ``end`` (UTC, to the minute): the
    same request as the history's (:func:`request_url`), over a span of hours (the live job's
    observed-before inputs, :func:`before_runs`)."""
    return _url(stations, start.astimezone(UTC), end.astimezone(UTC))


def _url(stations: Sequence[str], start: datetime, end: datetime) -> str:
    parts = [f"station={station}" for station in stations]
    parts += [f"data={name}" for name in FIELDS]
    parts += [
        f"year1={start.year}",
        f"month1={start.month}",
        f"day1={start.day}",
        *([f"hour1={start.hour}", f"minute1={start.minute}"] if start.hour or start.minute else []),
        f"year2={end.year}",
        f"month2={end.month}",
        f"day2={end.day}",
        *([f"hour2={end.hour}", f"minute2={end.minute}"] if end.hour or end.minute else []),
        "tz=Etc/UTC",
        "format=onlycomma",
        "latlon=no",
        "missing=M",
        "trace=T",
        "direct=no",
        "report_type=3",
    ]
    return f"{ASOS_URL}?{'&'.join(parts)}"


def _number(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.Float64, strict=False)


FIRST_YEAR: Final = 1990
LAST_YEAR: Final = 2200
"""The years a report's time may lie in (:func:`hourly_flags`); any other is not read."""


def hourly_flags(reports: pl.LazyFrame) -> pl.LazyFrame:
    """Each station hour's flags (UTC hour start ``hour``) from raw reports (all text)."""
    ceiling = pl.min_horizontal(
        *[
            pl.when(pl.col(f"skyc{i}").str.strip_chars().is_in(["BKN", "OVC", "VV"]))
            .then(_number(f"skyl{i}"))
            .otherwise(None)
            for i in (1, 2, 3)
        ]
    )
    codes = pl.col("wxcodes").fill_null("")
    snow = codes.str.contains(r"(^|\s)[-+]?(?:SH|TS)?(?:RA|DZ)?SN")
    valid = pl.col("valid").str.to_datetime("%Y-%m-%d %H:%M", time_zone="UTC", strict=False)
    return (
        # A time that does not convert, or lies outside the years of reports, is that row's
        # alone: the other rows are read.
        reports.with_columns(valid.alias("hour"))
        .filter(pl.col("hour").dt.year().is_between(FIRST_YEAR, LAST_YEAR))
        .with_columns((pl.col("hour") + pl.duration(minutes=10)).dt.truncate("1h"))
        .with_columns(
            codes.str.contains(r"FZRA|FZDZ|(^|\s)[-+]?PL").alias("frz"),
            snow.alias("snow"),
            codes.str.contains("TS").alias("thunder"),
            (
                (ceiling < FOG_CEILING_FEET).fill_null(value=False)
                | (_number("vsby") < FOG_VISIBILITY_MILES).fill_null(value=False)
            ).alias("fog"),
            (
                (_number("sknt") >= WIND_KNOTS).fill_null(value=False)
                | (_number("gust") >= GUST_KNOTS).fill_null(value=False)
            ).alias("wind"),
        )
        .group_by("station", "hour")
        .agg(*[pl.col(flag).any() for flag in FLAGS])
    )


REPORT_COLUMNS: Final = ("station", "valid", *FIELDS)


class ReportsError(ValueError):
    """A downloaded request is not the table of reports (an error text, a cut-off body)."""


def reduce_csv(path: Path) -> pl.DataFrame:
    """The hourly flags of one downloaded request.

    Raises:
        ReportsError: the file is not the table of reports.
    """
    return reduce_bytes(path.read_bytes())


def reduce_bytes(data: bytes) -> pl.DataFrame:
    """The hourly flags of one request's body.

    Raises:
        ReportsError: the body is not the table of reports (the archive answers an error as a
            text such as ``#ERROR: ...``, with a 200).
    """
    head = data[:4096].decode("utf-8", "replace").splitlines()
    names = head[0].split(",") if head else []
    if any(name not in names for name in REPORT_COLUMNS):
        raise ReportsError(f"not the table of reports: {(head[0] if head else '')[:80]!r}")
    try:
        reports = pl.read_csv(
            io.BytesIO(data), infer_schema=False, truncate_ragged_lines=True
        ).lazy()
        return hourly_flags(reports).collect().sort("station", "hour")
    except (pl.exceptions.PolarsError, OverflowError, ValueError) as error:
        raise ReportsError(f"the table of reports does not read: {error}") from error


OBSERVED_COLUMNS: Final = ("obs_snow", "obs_snow_old", "obs_frz")
"""The weather that came before a run (:func:`before_runs`), in hours."""
OBSERVED_HOURS: Final = 48
"""How far back before a run the observed-before inputs look."""


def before_runs(flags: pl.LazyFrame, stations: pl.DataFrame, runs: pl.LazyFrame) -> pl.LazyFrame:
    """The weather that came at each airport before each 00Z run, known when the run is issued:
    the hours with falling snow in the 24 hours before the run (``obs_snow``) and in the 24
    before those (``obs_snow_old``), and the hours with freezing rain or ice pellets in the 48
    hours before it (``obs_frz``). An hour counts by the UTC day its reports count for
    (:func:`hourly_flags`), so the history and the live job (the same request over 49 hours,
    :func:`window_url`) count the same hours. Hours without a report count as none.

    ``flags``: hourly flags; ``stations``: ``station`` and ``apt``; ``runs``: ``apt`` and
    ``run`` (00Z). Out: ``apt``, ``run`` and :data:`OBSERVED_COLUMNS` (``Float64``).
    """
    daily = (
        flags.with_columns(pl.col("hour").dt.date().alias("date"))
        .join(stations.lazy().select("station", "apt"), on="station")
        .group_by("apt", "date")
        .agg(
            pl.col("snow").sum().cast(pl.Float64).alias("snow_h"),
            pl.col("frz").sum().cast(pl.Float64).alias("frz_h"),
        )
    )
    keyed = runs.select("apt", "run").unique().with_columns(pl.col("run").dt.date().alias("rd"))
    one = daily.select(
        "apt",
        (pl.col("date") + pl.duration(days=1)).alias("rd"),
        pl.col("snow_h").alias("obs_snow"),
        pl.col("frz_h").alias("frz_1"),
    )
    two = daily.select(
        "apt",
        (pl.col("date") + pl.duration(days=2)).alias("rd"),
        pl.col("snow_h").alias("obs_snow_old"),
        pl.col("frz_h").alias("frz_2"),
    )
    return (
        keyed.join(one, on=["apt", "rd"], how="left")
        .join(two, on=["apt", "rd"], how="left")
        .select(
            "apt",
            "run",
            pl.col("obs_snow").fill_null(0.0),
            pl.col("obs_snow_old").fill_null(0.0),
            (pl.col("frz_1").fill_null(0.0) + pl.col("frz_2").fill_null(0.0)).alias("obs_frz"),
        )
    )


def with_observed(
    features: pl.LazyFrame, flags: pl.LazyFrame | None, stations: pl.DataFrame
) -> pl.LazyFrame:
    """Block (or day) features with the observed-before inputs of their run (:func:`before_runs`;
    zeros without ``flags``, for made-up worlds with no reports)."""
    if flags is None:
        return features.with_columns(*[pl.lit(0.0).alias(name) for name in OBSERVED_COLUMNS])
    found = before_runs(flags, stations, features.select("apt", "run"))
    return features.join(found, on=["apt", "run"], how="left").with_columns(
        *[pl.col(name).fill_null(0.0) for name in OBSERVED_COLUMNS]
    )


def block_kinds(flags: pl.LazyFrame, zones: pl.DataFrame) -> pl.LazyFrame:
    """Each airport block's weather kind.

    ``flags``: hourly flags (:func:`hourly_flags`); ``zones``: ``station``, ``apt`` and ``tz``
    per airport. Out: ``apt``, ``day`` (block day), ``block``, ``kind`` (:class:`Kind`), and how
    many hours each flag held.
    """
    from snowlight.flights.bts import _block_expr  # noqa: PLC0415 - one block rule

    parts = []
    for tz, group in zones.group_by("tz"):
        local = (
            flags.join(group.lazy().select("station", "apt"), on="station")
            .with_columns(pl.col("hour").dt.convert_time_zone(str(tz[0])).alias("local"))
            .with_columns(
                pl.col("local").dt.hour().alias("lh"), pl.col("local").dt.date().alias("cd")
            )
            .with_columns(
                _block_expr(pl.col("lh")).alias("block"),
                (pl.col("cd") - pl.duration(days=(pl.col("lh") < 5).cast(pl.Int32))).alias(  # noqa: PLR2004
                    "day"
                ),
            )
            .drop("local", "lh", "cd")
        )
        parts.append(local)
    counted = (
        pl.concat(parts)
        .group_by("apt", "day", "block")
        .agg(*[pl.col(flag).sum().cast(pl.Int16).alias(flag) for flag in FLAGS])
    )
    kind = pl.lit(int(Kind.NONE))
    for which in reversed(KINDS):
        flag = which.name.lower()
        kind = pl.when(pl.col(flag) >= MIN_HOURS[which]).then(int(which)).otherwise(kind)
    return counted.with_columns(kind.cast(pl.Int8).alias("kind"))

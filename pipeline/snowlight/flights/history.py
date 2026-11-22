"""Fetching the history into RAM, re-runnable: whatever is already kept is skipped.

* :func:`fetch_bts`: BTS months, reduced to the compact tables (:mod:`snowlight.flights.bts`);
  the raw zip and CSV are deleted once reduced;
* :func:`fetch_nbs`: 00Z NBS bulletins, kept as our airports' rows only (one parquet per day);
* :func:`fetch_obs`: hourly weather reports, kept as hourly flags (one parquet per month).

Each takes a ``get`` (url to bytes, ``None`` when not there) so tests run without the network,
fetches one file at a time, and says what it did through ``log``.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

import polars as pl

from snowlight.flights import bts, nbs, obs
from snowlight.flights.fetch import FetchError

type Get = Callable[[str], bytes | None]
type Log = Callable[[str], None]
type OutOfTime = Callable[[], bool]


def _never() -> bool:
    return False


GROUP: int = 20
"""Weather stations per hourly-report request."""


def fetch_bts(  # noqa: PLR0913 - the source, the stores, the months, the log and the clock
    get: Get,
    root: Path,
    scratch: Path,
    months: Sequence[bts.Month],
    log: Log,
    *,
    out_of_time: OutOfTime = _never,
) -> list[bts.Month]:
    """Fetch and reduce every month of ``months`` not kept yet, until ``out_of_time``; the
    months newly kept."""
    added: list[bts.Month] = []
    for month in months:
        if bts.has_month(root, month):
            continue
        if out_of_time():
            break
        try:
            body = get(month.url())
        except FetchError as error:
            log(f"flights history: BTS {month.key} failed ({error})")
            continue
        if body is None:
            log(f"flights history: BTS {month.key} not posted")
            continue
        scratch.mkdir(parents=True, exist_ok=True)
        archive = scratch / f"{month.key}.zip"
        archive.write_bytes(body)
        try:
            bts.write_month(root, month, bts.reduce_zip(archive, scratch))
        except Exception as error:  # a body that does not read is that month's alone
            log(f"flights history: BTS {month.key} did not read ({type(error).__name__}: {error})")
            continue
        finally:
            archive.unlink(missing_ok=True)
        added.append(month)
        log(f"flights history: BTS {month.key} kept")
    return added


def newest_posted(get: Get, after: bts.Month, limit: int = 3) -> bts.Month | None:
    """The newest BTS month posted after ``after`` (probing up to ``limit`` months), if any."""
    found: bts.Month | None = None
    month = after
    for _ in range(limit):
        month = month.next()
        try:
            if get(month.url()) is None:
                break
        except FetchError:
            break
        found = month
    return found


def nbs_frame(runs: Sequence[nbs.StationRun]) -> pl.DataFrame:
    """Station runs as the rows kept per day."""
    from snowlight.flights.live import rows_of  # noqa: PLC0415 - one row layout

    return rows_of(runs)


def fetch_nbs(  # noqa: PLR0913 - the source, the store, the stations, the span and the clock
    get: Get,
    root: Path,
    wanted: frozenset[str],
    *,
    first: date,
    last: date,
    log: Log,
    out_of_time: OutOfTime = _never,
) -> int:
    """Fetch every 00Z bulletin from ``last`` back to ``first`` not kept yet, until
    ``out_of_time``; how many were."""
    root.mkdir(parents=True, exist_ok=True)
    kept = 0
    day = last
    while day >= first:
        target = root / f"{day.isoformat()}.parquet"
        run = datetime(day.year, day.month, day.day, tzinfo=UTC)
        day -= timedelta(days=1)
        if target.exists():
            continue
        if out_of_time():
            break
        try:
            body = get(nbs.run_url(run))
        except FetchError as error:
            log(f"flights history: NBS {run:%Y-%m-%d} failed ({error})")
            continue
        if body is None:
            continue
        try:
            frame = nbs_frame(list(nbs.parse(body.decode("ascii", "replace"), wanted, run)))
        except Exception as error:  # a bulletin that does not read is that day's alone
            log(f"flights history: NBS {run:%Y-%m-%d} did not read ({type(error).__name__})")
            continue
        if frame.is_empty():
            # A cut-off or error body: never kept as a day with no rows, so it is asked again.
            log(f"flights history: NBS {run:%Y-%m-%d} had none of our stations")
            continue
        part = target.with_suffix(".part")
        frame.write_parquet(part, compression="zstd")
        part.replace(target)
        kept += 1
    log(f"flights history: NBS {kept} runs kept")
    return kept


KEPT: Final = (
    ("bts", "*.parquet"),
    ("nbs", "*.parquet"),
    ("obs", "*.parquet"),
    ("archive", "*.json"),
)
"""The folders of the history cache and the files each one keeps (:func:`kept_files`)."""


def kept_files(raw: Path) -> frozenset[str]:
    """Every history file kept under ``raw`` (the BTS tables, bulletins and reports, and the
    monthly job's copy of each day's archive snapshot, from
    :func:`snowlight.flights.monthly.keep_archive`): the cache holds something new exactly
    when this changed."""
    return frozenset(
        path.relative_to(raw).as_posix()
        for folder, pattern in KEPT
        if (raw / folder).is_dir()
        for path in (raw / folder).rglob(pattern)
    )


def fetch_obs(  # noqa: PLR0913 - the source, the store, the stations, the months and the clock
    get: Get,
    root: Path,
    stations: Sequence[str],
    months: Sequence[bts.Month],
    log: Log,
    *,
    out_of_time: OutOfTime = _never,
) -> int:
    """Fetch the hourly reports of every month not kept yet (all of a month's station groups, or
    none of it), until ``out_of_time``; how many months were kept."""
    root.mkdir(parents=True, exist_ok=True)
    groups = [list(stations[i : i + GROUP]) for i in range(0, len(stations), GROUP)]
    kept = 0
    for month in months:
        target = root / f"{month.key}.parquet"
        if target.exists():
            continue
        if out_of_time():
            break
        parts: list[pl.DataFrame] = []
        for group in groups:
            try:
                body = get(obs.request_url(group, month.year, month.month))
            except FetchError as error:
                log(f"flights history: reports {month.key} failed ({error})")
                break
            if body is None:
                break
            try:
                parts.append(obs.reduce_bytes(body))
            except obs.ReportsError as error:
                log(f"flights history: reports {month.key} did not read ({error})")
                break
        else:
            pl.concat(parts).write_parquet(target, compression="zstd")
            kept += 1
    log(f"flights history: reports {kept} months kept")
    return kept

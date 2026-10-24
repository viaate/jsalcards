"""Build the school elevation table from Terrarium terrain tiles.

Each school is read in the zoom-``zoom`` tile holding its point (one tile read once for all
its schools); a tile that cannot be read leaves its schools with no height. The tiles are
read concurrently (``workers`` processes, each decoding the tiles it fetched); a fetch is
tried ``attempts`` times. Nothing here is written but the table.
"""

import hashlib
import os
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Final

import httpx

from snowlight.elevation.table import Row, Table
from snowlight.elevation.terrarium import FEET_PER_METER, TileError, decode, sample, tile_of

DEFAULT_URL: Final = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
DEFAULT_ZOOM: Final = 11
USER_AGENT: Final = "snowlight-elevation/1 (+https://github.com/viaate/jsalcards)"
_TIMEOUT: Final = 30.0
_OK: Final = 200
_GONE: Final = frozenset({403, 404})

type Fetch = Callable[[str], bytes | None]
"""Reads one tile's bytes by URL; ``None``: the host has no such tile."""


@dataclass(frozen=True, slots=True)
class TileJob:
    """One tile and the pixel positions of its schools."""

    url: str
    key: str
    pixels: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class TileResult:
    """One tile's schools' heights in feet (``None`` each when the tile was not read), and
    the SHA-256 of its bytes (``None``: not read)."""

    key: str
    feet: tuple[int | None, ...]
    sha256: str | None
    problem: str | None = None


class _HttpFetch:
    """Reads tiles over HTTPS, trying each ``attempts`` times (one client per process)."""

    def __init__(self, attempts: int) -> None:
        self.attempts = attempts
        self.client: httpx.Client | None = None

    def __call__(self, url: str) -> bytes | None:  # pragma: no cover - the network
        if self.client is None:
            self.client = httpx.Client(
                headers={"User-Agent": USER_AGENT},
                timeout=_TIMEOUT,
                follow_redirects=True,
                verify=os.environ.get("SSL_CERT_FILE") or True,
            )
        last = "no attempt"
        for attempt in range(self.attempts):
            try:
                response = self.client.get(url)
            except httpx.HTTPError as error:
                last = type(error).__name__
            else:
                if response.status_code == _OK:
                    return response.content
                if response.status_code in _GONE:
                    return None
                last = f"HTTP {response.status_code}"
            time.sleep(min(2.0**attempt, 10.0))
        raise OSError(f"{url}: {last}")


_PROCESS_FETCH: list[Fetch] = []


def _init_worker(attempts: int) -> None:  # pragma: no cover - runs in the worker processes
    _PROCESS_FETCH.clear()
    _PROCESS_FETCH.append(_HttpFetch(attempts))


def read_tile(job: TileJob, fetch: Fetch) -> TileResult:
    """Read one tile and its schools' heights (rounded to whole feet)."""
    try:
        data = fetch(job.url)
    except OSError as error:
        return TileResult(job.key, tuple(None for _ in job.pixels), None, str(error))
    if data is None:
        return TileResult(job.key, tuple(None for _ in job.pixels), None, "no such tile")
    digest = hashlib.sha256(data).hexdigest()
    try:
        meters = decode(data)
    except TileError as error:
        return TileResult(job.key, tuple(None for _ in job.pixels), None, str(error))
    feet = tuple(round(sample(meters, px, py) * FEET_PER_METER) for px, py in job.pixels)
    return TileResult(job.key, feet, digest)


def _read_in_worker(job: TileJob) -> TileResult:  # pragma: no cover - the worker processes
    return read_tile(job, _PROCESS_FETCH[0])


@dataclass(frozen=True, slots=True)
class Built:
    """A table, the tiles it read, and what could not be read."""

    table: Table
    tiles: int
    problems: tuple[str, ...]


def jobs_for(
    lon_e6: Sequence[int], lat_e6: Sequence[int], url: str, zoom: int
) -> tuple[list[TileJob], list[tuple[str, int]]]:
    """The tiles to read (sorted by key) and, per school position, its tile key and its
    index among that tile's pixels."""
    pixels: dict[str, list[tuple[float, float]]] = defaultdict(list)
    where: list[tuple[str, int]] = []
    for lon, lat in zip(lon_e6, lat_e6, strict=True):
        x, y, px, py = tile_of(lon * 1e-6, lat * 1e-6, zoom)
        key = f"{zoom}/{x}/{y}"
        where.append((key, len(pixels[key])))
        pixels[key].append((px, py))
    jobs = [
        TileJob(url.format(z=key.split("/")[0], x=key.split("/")[1], y=key.split("/")[2]), key,
                tuple(items))
        for key, items in sorted(pixels.items())
    ]  # fmt: skip
    return jobs, where


def build_table(  # noqa: PLR0913 - the schools, the source and how to read it
    school_ids: Sequence[str],
    lon_e6: Sequence[int],
    lat_e6: Sequence[int],
    *,
    url: str = DEFAULT_URL,
    zoom: int = DEFAULT_ZOOM,
    workers: int = 0,
    attempts: int = 4,
    fetch: Fetch | None = None,
    progress: Callable[[int, int], object] | None = None,
) -> Built:
    """The elevation table of the schools at these points.

    ``workers`` 0 reads every tile in this process with ``fetch`` (default HTTPS); more
    reads them in that many processes (HTTPS only).

    Raises:
        ValueError: the ids are not one per point, or repeat.
    """
    if not len(school_ids) == len(lon_e6) == len(lat_e6):
        raise ValueError("one id per point")
    if len(set(school_ids)) != len(school_ids):
        raise ValueError("a school id repeats")
    jobs, where = jobs_for(lon_e6, lat_e6, url, zoom)
    results: dict[str, TileResult] = {}
    if workers <= 0:
        reader = fetch if fetch is not None else _HttpFetch(attempts)
        for done, job in enumerate(jobs, start=1):
            results[job.key] = read_tile(job, reader)
            if progress is not None:
                progress(done, len(jobs))
    else:  # pragma: no cover - the worker processes read over HTTPS
        with ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(attempts,)) as pool:
            for done, result in enumerate(pool.map(_read_in_worker, jobs, chunksize=8), start=1):
                results[result.key] = result
                if progress is not None:
                    progress(done, len(jobs))
    lines = sorted(f"{key} {item.sha256}" for key, item in results.items() if item.sha256)
    tiles_sha256 = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    rows = sorted(
        (
            Row(school, lon, lat, results[key].feet[index])
            for school, lon, lat, (key, index) in zip(
                school_ids, lon_e6, lat_e6, where, strict=True
            )
        ),
        key=lambda row: row.school,
    )
    problems = tuple(
        f"{key}: {item.problem}" for key, item in sorted(results.items()) if item.problem
    )
    return Built(Table(url, zoom, tiles_sha256, tuple(rows)), len(jobs), problems)

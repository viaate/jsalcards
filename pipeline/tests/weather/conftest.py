"""Shared fixtures for the weather tests.

Every file in ``fixtures/`` is a verbatim slice of a real source file (see
``fixtures/provenance.json`` and ``make_fixtures.py``). What is synthetic here
is only the plumbing: an in-memory HTTP server (:class:`FakeServer`) that serves
those slices at their real URLs, a fixed clock, and the boundary release lists
built from the slices (their MD5 sums are computed from the slice bytes; their
valid dates are the ones the NWS pages list). Archive days and snapshot times a
test does not examine are served the no-rows and no-events slices
(:meth:`Kit.serve_days_without_rows`), which claim nothing about the real days.

Test modules cannot import this file under ``--import-mode=importlib``; they
reach these helpers through the fixtures below.
"""

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from snowlight.sources.nws.alerts import ACTIVE_URL
from snowlight.sources.nws.boundaries import (
    PAGES,
    BoundaryCatalog,
    BoundaryKind,
    BoundaryRelease,
)
from snowlight.sources.nws.http import HttpCache
from snowlight.sources.nws.iem import day_url, range_url, snapshot_url
from snowlight.weather.build import archive_codes
from snowlight.weather.hazards import CONUS_STATES

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://www.weather.gov/source/gis/Shapefiles"
# The time the fixture feed was generated (its "updated" field).
FEED_TIME = datetime(2026, 9, 25, 0, 9, 38, tzinfo=UTC)
RELEASE_DATES = {
    "z_18mr25": date(2025, 3, 18),
    "z_16ap26": date(2026, 4, 16),
    "c_18mr25": date(2025, 3, 18),
    "c_16ap26": date(2026, 4, 16),
}
IEM_DAYS = (date(2024, 5, 21), date(2025, 1, 21), date(2025, 1, 22), date(2026, 1, 26))
IEM_SNAPSHOTS = (datetime(2024, 4, 30, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC))
IEM_RANGES = (
    ("HGX", "FL", "W", date(2024, 4, 1), date(2024, 6, 1)),
    ("LCH", "FL", "W", date(2024, 4, 1), date(2024, 6, 1)),
    ("LSX", "FL", "W", date(2024, 4, 1), date(2024, 6, 1)),
    ("BTV", "WS", "W", date(2024, 12, 1), date(2025, 2, 1)),
)


def snapshot_fixture(at: datetime) -> str:
    """The fixture name of the snapshot slice for ``at``."""
    return f"iem-snapshot-{at:%Y-%m-%dT%H%M}Z.json"


def range_fixture(wfo: str, phenomena: str, significance: str, first: date, end: date) -> str:
    """The fixture name of a range file slice."""
    return f"iem-range-{wfo}-{phenomena}.{significance}-{first}_{end}.zip"


def fixture_bytes(name: str) -> bytes:
    """Return the bytes of a real fixture slice."""
    return (FIXTURES / name).read_bytes()


def release_url(stem: str) -> str:
    """Return the real URL of a boundary release file."""
    folder = "WSOM" if stem.startswith("z_") else "County"
    return f"{BASE}/{folder}/{stem}.zip"


@dataclass
class Reply:
    """A scripted answer: status, body and headers."""

    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class FakeServer:
    """Serves fixture bytes by exact URL; supports ETags and scripted failures."""

    files: dict[str, bytes] = field(default_factory=dict)
    etags: dict[str, str] = field(default_factory=dict)
    scripted: dict[str, list[Reply]] = field(default_factory=dict)
    hits: Counter[str] = field(default_factory=Counter)
    requests: list[httpx.Request] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.hits[url] += 1
        self.requests.append(request)
        queue = self.scripted.get(url)
        if queue:
            reply = queue.pop(0)
            return httpx.Response(reply.status, content=reply.body, headers=reply.headers)
        if url not in self.files:
            return httpx.Response(404)
        etag = self.etags.get(url)
        if etag is not None and request.headers.get("If-None-Match") == etag:
            return httpx.Response(304, headers={"ETag": etag})
        headers = {"Content-Length": str(len(self.files[url]))}
        if etag is not None:
            headers["ETag"] = etag
        return httpx.Response(200, content=self.files[url], headers=headers)

    def queue(
        self, url: str, status: int, body: bytes = b"", headers: dict[str, str] | None = None
    ) -> None:
        """Answer the next request for ``url`` with this reply instead of the file."""
        self.scripted.setdefault(url, []).append(Reply(status, body, headers or {}))

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@dataclass
class Clock:
    """A settable clock for the cache."""

    now: datetime = FEED_TIME

    def __call__(self) -> datetime:
        return self.now


def _release(stem: str) -> BoundaryRelease:
    data = fixture_bytes(f"{stem}.zip")
    kind: BoundaryKind = "zone" if stem.startswith("z_") else "county"
    return BoundaryRelease(
        kind=kind,
        valid_from=RELEASE_DATES[stem],
        url=release_url(stem),
        md5=hashlib.md5(data, usedforsecurity=False).hexdigest(),
        records=None,
    )


def fixture_releases() -> dict[BoundaryKind, list[BoundaryRelease]]:
    """The release lists for the fixture slices."""
    return {
        "zone": [_release("z_18mr25"), _release("z_16ap26")],
        "county": [_release("c_18mr25"), _release("c_16ap26")],
    }


@dataclass
class Kit:
    """Everything a test needs to run the weather code against the fixtures offline."""

    server: FakeServer
    clock: Clock
    cache_dir: Path
    sleeps: list[float] = field(default_factory=list)

    def cache(self, attempts: int = 4) -> HttpCache:
        return HttpCache(
            self.server.client(), attempts=attempts, sleep=self.sleeps.append, clock=self.clock
        )

    def catalog(self, cache: HttpCache | None = None) -> BoundaryCatalog:
        return BoundaryCatalog(cache or self.cache(), self.cache_dir, fixture_releases())

    def serve_days_without_rows(self, first: date, last: date) -> None:
        """Serve the no-rows slice for the days in ``first..last``, and the no-events
        slice for the snapshots at their midnights, where there is no fixture."""
        codes = archive_codes()
        day = first
        while day <= last:
            url = day_url(day, codes, CONUS_STATES)
            self.server.files.setdefault(url, fixture_bytes("iem-no-rows.zip"))
            midnight = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
            self.server.files.setdefault(
                snapshot_url(midnight), fixture_bytes("iem-snapshot-no-events.json")
            )
            day += timedelta(days=1)


@pytest.fixture
def server() -> FakeServer:
    """A server holding every fixture at its real URL."""
    fake = FakeServer()
    fake.files[ACTIVE_URL] = fixture_bytes("active.geojson")
    fake.etags[ACTIVE_URL] = 'W/"fixture-etag"'
    for kind, url in PAGES.items():
        name = "PublicZones" if kind == "zone" else "Counties"
        fake.files[url] = fixture_bytes(f"{name}.table.html")
    for stem in RELEASE_DATES:
        fake.files[release_url(stem)] = fixture_bytes(f"{stem}.zip")
    codes = archive_codes()
    for day in IEM_DAYS:
        fake.files[day_url(day, codes, CONUS_STATES)] = fixture_bytes(f"iem-{day}.zip")
    for at in IEM_SNAPSHOTS:
        fake.files[snapshot_url(at)] = fixture_bytes(snapshot_fixture(at))
    for spec in IEM_RANGES:
        fake.files[range_url(*spec)] = fixture_bytes(range_fixture(*spec))
    return fake


@pytest.fixture
def kit(server: FakeServer, tmp_path: Path) -> Kit:
    """The fixture server, a clock set to the feed time, and an empty cache directory."""
    return Kit(server, Clock(), tmp_path / "cache")


@pytest.fixture
def offline(kit: Kit, monkeypatch: pytest.MonkeyPatch) -> Kit:
    """Route the ``alerts`` command and build helpers to the fixture server and releases."""

    def catalog(cache: HttpCache, cache_dir: Path) -> BoundaryCatalog:
        return BoundaryCatalog(cache, cache_dir, fixture_releases())

    def cache() -> HttpCache:
        return HttpCache(kit.server.client(), sleep=kit.sleeps.append, clock=kit.clock)

    monkeypatch.setattr("snowlight.weather.build.BoundaryCatalog", catalog)
    monkeypatch.setattr("snowlight.weather.cli.BoundaryCatalog", catalog)
    monkeypatch.setattr("snowlight.weather.cli._cache", cache)
    return kit

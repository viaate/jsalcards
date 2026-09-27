"""Shared fixtures for the closure-weights tests.

Every file in ``fixtures/`` is a verbatim slice of a real source file (see
``fixtures/provenance.json`` and ``make_fixtures.py``). What is synthetic here is
only the plumbing: an in-memory HTTP server that serves those slices at their
real URLs, a fixed clock, and the county release built from the county slice
(its MD5 and record count are computed from the slice, its valid date is the one
the NWS page lists).

Test modules cannot import this file under ``--import-mode=importlib``; they reach
these helpers through the fixtures below.
"""

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from snowlight.sources.nws.boundaries import BoundaryRelease
from snowlight.sources.nws.http import HttpCache
from snowlight.sources.nws.iem import day_url
from snowlight.weather.hazards import CONUS_STATES
from snowlight.weights import archive, build, crosscheck, markets, outlines, zones
from snowlight.weights.cache import WeightsCache
from snowlight.weights.codes import code_pairs

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
YEARS = {2018: "iem-2018-2019.csv", 2021: "iem-2021-2022.csv", 2024: "iem-2024-2025.csv"}
RELEASES = ("bp02ap19", "bp10oc19", "bp05mr24", "bp10se24", "bp16ap26")
DAYS = tuple(date(2025, 1, 30) + timedelta(days=n) for n in range(10))
UGCS_VALID = datetime(2019, 1, 15, 12, tzinfo=UTC)


def fixture_bytes(name: str) -> bytes:
    """Return the bytes of a real fixture slice."""
    return (FIXTURES / name).read_bytes()


def county_release() -> BoundaryRelease:
    """The county release for the county slice (MD5 and record count of the slice)."""
    data = fixture_bytes("c_16ap26.zip")
    return BoundaryRelease(
        kind="county",
        valid_from=zones.COUNTY_RELEASE.valid_from,
        url=zones.COUNTY_RELEASE.url,
        md5=hashlib.md5(data, usedforsecurity=False).hexdigest(),
        records=12,
    )


@dataclass
class FakeServer:
    """Serves fixture bytes by exact URL and counts the requests."""

    files: dict[str, bytes] = field(default_factory=dict)
    hits: Counter[str] = field(default_factory=Counter)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.hits[url] += 1
        if url not in self.files:
            return httpx.Response(404)
        body = self.files[url]
        return httpx.Response(200, content=body, headers={"Content-Length": str(len(body))})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@dataclass
class Kit:
    """Everything a test needs to run the weights code against the fixtures offline."""

    server: FakeServer
    cache_dir: Path
    now: datetime = NOW

    def http(self) -> HttpCache:
        return HttpCache(self.server.client(), attempts=1, sleep=lambda _: None, clock=self.clock)

    def clock(self) -> datetime:
        return self.now

    def cache(self) -> WeightsCache:
        return WeightsCache(self.http(), self.cache_dir, siblings=())

    @staticmethod
    def bytes(name: str) -> bytes:
        """Return the bytes of a fixture slice."""
        return fixture_bytes(name)

    @staticmethod
    def text(name: str) -> str:
        """Return a fixture slice as text."""
        return fixture_bytes(name).decode("utf-8")

    @staticmethod
    def path(name: str) -> Path:
        """Return where a fixture slice is."""
        return FIXTURES / name

    @staticmethod
    def county_release() -> BoundaryRelease:
        """The county release describing the county slice."""
        return county_release()

    releases = RELEASES
    days = DAYS


def serve_all(fake: FakeServer) -> None:
    """Put every fixture at its real URL."""
    for year, name in YEARS.items():
        fake.files[archive.year_url(year)] = fixture_bytes(name)
    for name in RELEASES:
        fake.files[zones.release_url(name)] = fixture_bytes(f"{name}.dbx")
    fake.files[zones.COUNTY_RELEASE.url] = fixture_bytes("c_16ap26.zip")
    for day in DAYS:
        url = day_url(day, code_pairs(), CONUS_STATES)
        fake.files[url] = fixture_bytes(f"iem-day-{day.isoformat()}.zip")
    fake.files[crosscheck.ugcs_url(UGCS_VALID)] = fixture_bytes("ugcs-2019-01-15.json")
    fake.files[markets.DMA_CROSSWALK_URL] = fixture_bytes("usa-tvdma-county.csv")
    fake.files[markets.COUNTY_GAZETTEER_URL] = fixture_bytes("2025_Gaz_counties_national.zip")
    fake.files[markets.CT_CROSSWALK_URL] = fixture_bytes("ct_cou_to_cousub_crosswalk.xlsx")
    fake.files[build.ALERT_TYPES_URL] = fixture_bytes("alert-types.json")
    for year in (2018, 2019, 2021):
        valid = outlines.outline_valid(year)
        fake.files[outlines.outlines_url(valid)] = fixture_bytes(f"ugcs-{valid:%Y-%m-%d}.geojson")


@pytest.fixture
def server() -> FakeServer:
    """A server holding every fixture at its real URL."""
    fake = FakeServer()
    serve_all(fake)
    return fake


@pytest.fixture
def kit(server: FakeServer, tmp_path: Path) -> Kit:
    """The fixture server, a clock set to 2026-09-26 and an empty cache directory."""
    return Kit(server, tmp_path / "cache")

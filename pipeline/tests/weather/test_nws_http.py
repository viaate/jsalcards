"""Tests for the provenance-recording HTTP cache (served by the in-memory fixture server)."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from snowlight.sources.nws.alerts import ACTIVE_URL
from snowlight.sources.nws.http import (
    USER_AGENT,
    ChecksumMismatchError,
    FetchError,
    HttpCache,
    NotFoundError,
    Provenance,
    iso_utc,
    make_client,
    md5_file,
    parse_iso_utc,
    sha256_file,
    sidecar_path,
)

if TYPE_CHECKING:
    from weather.conftest import Kit

URL = ACTIVE_URL


def test_user_agent_names_the_repository() -> None:
    assert "github.com/viaate/jsalcards" in USER_AGENT
    with make_client() as client:
        assert client.headers["User-Agent"] == USER_AGENT


def test_fetch_downloads_once_and_records_provenance(kit: "Kit") -> None:
    dest = kit.cache_dir / "active.geojson"
    body = kit.server.files[URL]
    with kit.cache() as cache:
        first = cache.fetch(URL, dest)
        second = cache.fetch(URL, dest)
    assert (first.downloaded, second.downloaded) == (True, False)
    assert dest.read_bytes() == body
    assert first.provenance.sha256 == hashlib.sha256(body).hexdigest() == sha256_file(dest)
    assert first.provenance.retrieved_at == iso_utc(kit.clock.now)
    assert first.provenance.etag == 'W/"fixture-etag"'
    assert kit.server.hits[URL] == 1
    sidecar = json.loads(sidecar_path(dest).read_text())
    assert sidecar == first.provenance.as_json()
    assert Provenance.from_json(sidecar) == first.provenance


def test_conditional_request_confirms_an_unchanged_copy(kit: "Kit") -> None:
    dest = kit.cache_dir / "active.geojson"
    with kit.cache() as cache:
        first = cache.fetch(URL, dest, max_age=timedelta(0), accept="application/geo+json")
        kit.clock.now += timedelta(minutes=5)
        again = cache.fetch(URL, dest, max_age=timedelta(0), accept="application/geo+json")
    assert again.not_modified is True
    assert again.downloaded is False
    assert again.provenance.retrieved_at == first.provenance.retrieved_at
    assert again.provenance.checked_at == iso_utc(kit.clock.now)
    last = kit.server.requests[-1]
    assert last.headers["If-None-Match"] == 'W/"fixture-etag"'
    assert last.headers["Accept"] == "application/geo+json"
    assert json.loads(sidecar_path(dest).read_text())["checked_at"] == iso_utc(kit.clock.now)


def test_max_age_trusts_a_recent_copy_and_replaces_a_changed_one(kit: "Kit") -> None:
    dest = kit.cache_dir / "active.geojson"
    with kit.cache() as cache:
        cache.fetch(URL, dest, max_age=timedelta(hours=1))
        kit.clock.now += timedelta(minutes=30)
        assert cache.fetch(URL, dest, max_age=timedelta(hours=1)).downloaded is False
        assert kit.server.hits[URL] == 1
        kit.clock.now += timedelta(hours=1)
        kit.server.files[URL] = b'{"type": "FeatureCollection", "features": []}'
        kit.server.etags[URL] = 'W/"changed"'
        changed = cache.fetch(URL, dest, max_age=timedelta(hours=1))
    assert changed.downloaded is True
    assert dest.read_bytes() == kit.server.files[URL]
    assert changed.provenance.etag == 'W/"changed"'


def test_last_modified_is_sent_back(kit: "Kit") -> None:
    url = "https://www.weather.gov/gis/Counties"
    kit.server.queue(
        url, 200, b"<table></table>", {"Last-Modified": "Tue, 03 Mar 2026 15:17:30 GMT"}
    )
    kit.server.queue(url, 304)
    dest = kit.cache_dir / "Counties.html"
    with kit.cache() as cache:
        cache.fetch(url, dest)
        confirmed = cache.fetch(url, dest, max_age=timedelta(0))
    assert confirmed.not_modified is True
    assert kit.server.requests[-1].headers["If-Modified-Since"] == "Tue, 03 Mar 2026 15:17:30 GMT"


def test_tampered_or_mislabelled_copies_are_fetched_again(kit: "Kit") -> None:
    dest = kit.cache_dir / "active.geojson"
    with kit.cache() as cache:
        cache.fetch(URL, dest)
        dest.write_bytes(b"tampered")
        assert cache.fetch(URL, dest).downloaded is True
        sidecar_path(dest).write_text("{not json")
        assert cache.fetch(URL, dest).downloaded is True
        record = json.loads(sidecar_path(dest).read_text())
        sidecar_path(dest).write_text(json.dumps({**record, "url": URL + "&x=1"}))
        assert cache.fetch(URL, dest).downloaded is True
        sidecar_path(dest).write_text(json.dumps({**record, "bytes": "many"}))
        assert cache.cached(URL, dest) is None
        sidecar_path(dest).write_text(json.dumps([1, 2]))
        assert cache.cached(URL, dest) is None
        sidecar_path(dest).write_text(json.dumps({"url": URL}))
        assert cache.cached(URL, dest) is None
        sidecar_path(dest).write_text(json.dumps({**record, "checked_at": "yesterday"}))
        assert cache.fetch(URL, dest, max_age=timedelta(days=1)).not_modified is True


def test_published_md5_is_checked(kit: "Kit") -> None:
    url = "https://www.weather.gov/source/gis/Shapefiles/WSOM/z_16ap26.zip"
    body = kit.server.files[url]
    good = hashlib.md5(body, usedforsecurity=False).hexdigest()
    dest = kit.cache_dir / "z.zip"
    with kit.cache() as cache:
        with pytest.raises(ChecksumMismatchError, match="does not match"):
            cache.fetch(url, dest, expected_md5="0" * 32)
        assert not dest.exists()
        fetched = cache.fetch(url, dest, expected_md5=good.upper())
        assert fetched.downloaded is True
        assert md5_file(dest) == good
        assert cache.fetch(url, dest, expected_md5=good).downloaded is False
        # A cached copy that does not match a newly listed checksum is not trusted.
        with pytest.raises(ChecksumMismatchError):
            cache.fetch(url, dest, expected_md5="f" * 32)
    assert dest.read_bytes() == body


def test_retryable_answers_are_retried_with_backoff(kit: "Kit") -> None:
    kit.server.queue(URL, 503, b"busy", {"Retry-After": "7"})
    kit.server.queue(URL, 429, b"slow down", {"Retry-After": "soon"})
    kit.server.queue(URL, 200, b"x" * 10, {"Content-Length": "20"})
    with kit.cache() as cache:
        fetched = cache.fetch(URL, kit.cache_dir / "a.json")
    assert fetched.downloaded is True
    assert kit.sleeps == [7.0, 4.0, 8.0]
    assert kit.server.hits[URL] == 4


def test_giving_up_names_the_url(kit: "Kit") -> None:
    for status in (500, 502, 200):
        kit.server.queue(URL, status)
    with kit.cache(attempts=3) as cache, pytest.raises(FetchError, match="giving up") as info:
        cache.fetch(URL, kit.cache_dir / "a.json")
    assert "empty response body" in str(info.value.__cause__)
    assert kit.sleeps == [2.0, 4.0]


def test_transport_errors_are_retried(kit: "Kit") -> None:
    calls: list[int] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("reset", request=request)
        return kit.server.handler(request)

    client = httpx.Client(transport=httpx.MockTransport(flaky))
    with HttpCache(client, sleep=kit.sleeps.append, clock=kit.clock) as cache:
        assert cache.fetch(URL, kit.cache_dir / "a.json").downloaded is True
    assert len(calls) == 2


@pytest.mark.parametrize(("status", "error"), [(404, NotFoundError), (410, NotFoundError)])
def test_missing_resources_fail_at_once(kit: "Kit", status: int, error: type[Exception]) -> None:
    kit.server.queue(URL, status)
    with kit.cache() as cache, pytest.raises(error):
        cache.fetch(URL, kit.cache_dir / "a.json")
    assert kit.server.hits[URL] == 1


def test_refusals_fail_at_once(kit: "Kit") -> None:
    kit.server.queue(URL, 403, b"no")
    with kit.cache() as cache, pytest.raises(FetchError, match="HTTP 403"):
        cache.fetch(URL, kit.cache_dir / "a.json")
    assert kit.server.hits[URL] == 1
    assert list(kit.cache_dir.iterdir()) == []


def test_only_https_is_fetched(kit: "Kit") -> None:
    with kit.cache() as cache, pytest.raises(ValueError, match="only https"):
        cache.fetch("http://api.weather.gov/alerts/active", kit.cache_dir / "a.json")


def test_timestamps_round_trip() -> None:
    moment = parse_iso_utc("2026-09-24T23:43:14+00:00")
    assert iso_utc(moment) == "2026-09-24T23:43:14Z"
    assert parse_iso_utc("2026-09-24T17:42:00-06:00") == parse_iso_utc("2026-09-24T23:42:00Z")
    with pytest.raises(ValueError, match="no UTC offset"):
        parse_iso_utc("2026-09-24T23:43:14")


def test_sidecar_sits_next_to_the_file(tmp_path: Path) -> None:
    assert sidecar_path(tmp_path / "a.zip") == tmp_path / "a.zip.provenance.json"

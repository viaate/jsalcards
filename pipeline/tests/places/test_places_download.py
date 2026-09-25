"""Tests for the checksummed download cache (served by an in-memory fake server)."""

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from snowlight.places.download import (
    DownloadError,
    SourceCache,
    SourceMissingError,
    cache_path_for,
    make_client,
    sha256_file,
)
from snowlight.sources.census.zcta_county import ZCTA_COUNTY_URL

if TYPE_CHECKING:
    from conftest import FakeServer

URL = ZCTA_COUNTY_URL


def _cache(server: "FakeServer", root: Path, *, revalidate: bool = False) -> SourceCache:
    return SourceCache(root, server.client(), revalidate=revalidate, sleep=lambda _s: None)


def test_fetch_downloads_once_then_serves_the_verified_copy(
    server: "FakeServer", tmp_path: Path
) -> None:
    body = server.files[URL]
    with _cache(server, tmp_path) as cache:
        first = cache.fetch(URL)
        second = cache.fetch(URL)
    assert first.path == tmp_path.joinpath("www2.census.gov", *URL.split("/")[3:])
    assert first.path.read_bytes() == body
    assert first.sha256 == hashlib.sha256(body).hexdigest() == sha256_file(first.path)
    assert (first.from_cache, second.from_cache) == (False, True)
    assert second.retrieved_at == first.retrieved_at
    assert server.hits[URL] == 1
    sidecar = json.loads(first.path.with_name(first.path.name + ".provenance.json").read_text())
    assert sidecar == first.provenance()
    assert sidecar["etag"]
    assert sidecar["last_modified"]
    assert [p.name for p in first.path.parent.iterdir() if p.name.endswith(".part")] == []


def test_tampered_or_mislabeled_cache_is_downloaded_again(
    server: "FakeServer", tmp_path: Path
) -> None:
    with _cache(server, tmp_path) as cache:
        path = cache.fetch(URL).path
        path.write_bytes(b"tampered")
        assert cache.fetch(URL).from_cache is False
        sidecar = path.with_name(path.name + ".provenance.json")
        sidecar.write_text("{not json")
        assert cache.fetch(URL).from_cache is False
        meta = json.loads(sidecar.read_text())
        sidecar.write_text(json.dumps({**meta, "url": URL + ".old"}))
        assert cache.fetch(URL).from_cache is False
        sidecar.write_text(json.dumps({**meta, "etag": 5, "last_modified": None}))
        kept = cache.fetch(URL)
    assert kept.from_cache is True
    assert kept.etag is None
    assert path.read_bytes() == server.files[URL]
    assert server.hits[URL] == 4


def test_revalidate_keeps_unchanged_files_and_replaces_changed_ones(
    server: "FakeServer", tmp_path: Path
) -> None:
    with _cache(server, tmp_path) as cache:
        original = cache.fetch(URL)
    with _cache(server, tmp_path, revalidate=True) as cache:
        unchanged = cache.fetch(URL)
        server.files[URL] = server.files[URL] + b"revised\n"
        changed = cache.fetch(URL)
    assert unchanged.from_cache is True
    assert unchanged.sha256 == original.sha256
    assert changed.from_cache is False
    assert changed.sha256 == hashlib.sha256(server.files[URL]).hexdigest()
    assert server.hits[URL] == 3


def test_transient_failures_are_retried(server: "FakeServer", tmp_path: Path) -> None:
    replies = iter([503, "drop", 200])

    def flaky(request: httpx.Request) -> httpx.Response:
        reply = next(replies)
        if reply == "drop":
            raise httpx.ConnectError("connection reset", request=request)
        assert isinstance(reply, int)
        return httpx.Response(reply, content=b"x" if reply == 200 else b"", request=request)

    server.overrides[URL] = flaky
    sleeps: list[float] = []
    with SourceCache(tmp_path, server.client(), sleep=sleeps.append) as cache:
        fetched = cache.fetch(URL)
    assert fetched.path.read_bytes() == b"x"
    assert sleeps == [2.0, 4.0]


def test_truncated_bodies_fail_after_every_attempt(server: "FakeServer", tmp_path: Path) -> None:
    server.overrides[URL] = lambda request: httpx.Response(
        200, content=b"abc", headers={"Content-Length": "10"}, request=request
    )
    with _cache(server, tmp_path) as cache, pytest.raises(DownloadError, match="4 attempts"):
        cache.fetch(URL)
    assert server.hits[URL] == 4
    assert not cache_path_for(tmp_path, URL).exists()


@pytest.mark.parametrize(
    ("status", "message"), [(404, "HTTP 404"), (410, "HTTP 410"), (403, "HTTP 403"), (200, "empty")]
)
def test_permanent_failures_are_not_retried(
    server: "FakeServer", tmp_path: Path, status: int, message: str
) -> None:
    server.overrides[URL] = lambda request: httpx.Response(status, request=request)
    with _cache(server, tmp_path) as cache, pytest.raises(DownloadError, match=message):
        cache.fetch(URL)
    assert server.hits[URL] == 1


def test_get_text_records_pages_and_retries(server: "FakeServer", tmp_path: Path) -> None:
    page = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    replies = iter([502, 200])
    server.overrides[page] = lambda request: httpx.Response(
        next(replies), content=b"<a href='x/'>x</a>", request=request
    )
    with _cache(server, tmp_path) as cache:
        assert cache.get_text(page) == "<a href='x/'>x</a>"
        consulted = cache.pages_consulted
    assert [c.url for c in consulted] == [page]
    assert consulted[0].as_json()["sha256"] == hashlib.sha256(b"<a href='x/'>x</a>").hexdigest()
    server.overrides[page] = lambda request: httpx.Response(503, request=request)
    with _cache(server, tmp_path) as cache, pytest.raises(DownloadError, match="attempts"):
        cache.get_text(page)


@pytest.mark.parametrize(
    "url",
    [
        "http://www2.census.gov/a.zip",
        "https://www2.census.gov/",
        "https://www2.census.gov/a/../b.zip",
        "https://www2.census.gov/a.zip?x=1",
    ],
)
def test_cache_path_refuses_unsafe_urls(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValueError, match=r"only https URLs|does not name a file"):
        cache_path_for(tmp_path, url)


def test_make_client_verifies_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    with make_client() as client:
        assert client.headers["User-Agent"].startswith("snowlight-pipeline/")
        assert client.follow_redirects is True


def test_revalidate_without_validators_downloads_again(
    server: "FakeServer", tmp_path: Path
) -> None:
    seen: list[dict[str, str]] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append({k: v for k, v in request.headers.items() if k.startswith("if-")})
        return httpx.Response(200, content=server.files[URL], request=request)

    with _cache(server, tmp_path) as cache:
        path = cache.fetch(URL).path
    sidecar = path.with_name(path.name + ".provenance.json")
    meta = json.loads(sidecar.read_text())
    sidecar.write_text(json.dumps({**meta, "etag": None}))
    server.overrides[URL] = record
    with _cache(server, tmp_path, revalidate=True) as cache:
        assert cache.fetch(URL).from_cache is False
    sidecar.write_text(json.dumps({**meta, "last_modified": None}))
    with _cache(server, tmp_path, revalidate=True) as cache:
        cache.fetch(URL)
    assert seen == [
        {"if-modified-since": meta["last_modified"]},
        {"if-none-match": meta["etag"]},
    ]


def test_missing_files_raise_source_missing(server: "FakeServer", tmp_path: Path) -> None:
    with _cache(server, tmp_path) as cache, pytest.raises(SourceMissingError, match="404"):
        cache.get_text("https://www2.census.gov/no/such/dir/")

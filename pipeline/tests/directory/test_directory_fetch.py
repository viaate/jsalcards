"""Tests for the cached, checksummed NCES downloader."""

import hashlib
import io
import json
import zipfile
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest

from snowlight.directory.build import fetch_sources
from snowlight.directory.config import Source, load_config
from snowlight.sources.nces.fetch import (
    SIDECAR_SUFFIX,
    DownloadError,
    FileCache,
    RefusedError,
    SourceChangedError,
    SourceMissingError,
    cache_path,
    make_client,
    sha256_file,
)

URL = "https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PRIVATESCH_2324.zip"
# Synthetic payload: these tests exercise transport behaviour, not NCES content. It
# starts with the zip magic, as an unpinned .zip URL must answer with a zip.
PAYLOAD = b"PK\x03\x04synthetic payload for download tests"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
NEWER_URL = "https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PRIVATESCH_2425.zip"
# A synthetic stand-in for the page a server shows during maintenance.
MAINTENANCE_PAGE = b"<!DOCTYPE html><html><body>Scheduled maintenance</body></html>"


def _real_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("synthetic.txt", "synthetic member for download tests\n")
    return buffer.getvalue()


def _page(body: bytes = MAINTENANCE_PAGE) -> httpx.Response:
    return _ok(body, headers={"Content-Type": "text/html; charset=utf-8"})


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


class Recorder:
    """Answers each request with the next scripted response and records it."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, _request: httpx.Request) -> httpx.Response:
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _ok(body: bytes = PAYLOAD, headers: Mapping[str, str] | None = None) -> httpx.Response:
    sent = {"Content-Length": str(len(body)), **(headers or {})}
    return httpx.Response(200, content=body, headers=sent)


def test_cache_path_maps_host_and_path(tmp_path: Path) -> None:
    assert cache_path(tmp_path, URL) == tmp_path.joinpath(
        "nces.ed.gov", "programs", "edge", "data", "EDGE_GEOCODE_PRIVATESCH_2324.zip"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://nces.ed.gov/a.zip",
        "https://nces.ed.gov/",
        "https://nces.ed.gov/a/../b.zip",
        "https://nces.ed.gov/a.zip?x=1",
    ],
)
def test_cache_path_refuses_unsafe_urls(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValueError, match=r"https|file"):
        cache_path(tmp_path, url)


def test_download_writes_file_and_provenance_sidecar(tmp_path: Path) -> None:
    recorder = Recorder(
        _ok(headers={"ETag": '"abc"', "Last-Modified": "Wed, 27 Aug 2025 15:38:22 GMT"})
    )
    with FileCache(tmp_path, _client(httpx.MockTransport(recorder))) as cache:
        fetched = cache.fetch(URL, PAYLOAD_SHA)
    assert fetched.path.read_bytes() == PAYLOAD
    assert fetched.sha256 == PAYLOAD_SHA == sha256_file(fetched.path)
    assert not fetched.from_cache
    sidecar = json.loads(Path(str(fetched.path) + SIDECAR_SUFFIX).read_text())
    assert sidecar == fetched.provenance()
    assert sidecar["url"] == URL
    assert sidecar["etag"] == '"abc"'
    assert sidecar["last_modified"] == "Wed, 27 Aug 2025 15:38:22 GMT"
    assert sidecar["retrieved_at"].endswith("Z")
    assert [p.name for p in fetched.path.parent.iterdir() if p.name.endswith(".part")] == []


def test_cached_file_is_reused_without_a_request(tmp_path: Path) -> None:
    first = Recorder(_ok())
    with FileCache(tmp_path, _client(httpx.MockTransport(first))) as cache:
        original = cache.fetch(URL, PAYLOAD_SHA)
    second = Recorder()
    with FileCache(tmp_path, _client(httpx.MockTransport(second))) as cache:
        again = cache.fetch(URL, PAYLOAD_SHA)
    assert second.calls == 0
    assert again.from_cache
    assert again.retrieved_at == original.retrieved_at
    assert again.sha256 == PAYLOAD_SHA


def test_corrupted_cache_is_downloaded_again(tmp_path: Path) -> None:
    with FileCache(tmp_path, _client(httpx.MockTransport(Recorder(_ok())))) as cache:
        fetched = cache.fetch(URL)
    fetched.path.write_bytes(b"tampered")
    recorder = Recorder(_ok())
    with FileCache(tmp_path, _client(httpx.MockTransport(recorder))) as cache:
        again = cache.fetch(URL)
    assert recorder.calls == 1
    assert again.path.read_bytes() == PAYLOAD


@pytest.mark.parametrize(
    "sidecar",
    ["not json", json.dumps({"url": URL}), json.dumps({"url": "https://x/y", "sha256": "0"})],
)
def test_bad_or_foreign_sidecar_means_no_cache_hit(tmp_path: Path, sidecar: str) -> None:
    path = cache_path(tmp_path, URL)
    path.parent.mkdir(parents=True)
    path.write_bytes(PAYLOAD)
    Path(str(path) + SIDECAR_SUFFIX).write_text(sidecar)
    with FileCache(tmp_path, _client(httpx.MockTransport(Recorder()))) as cache:
        assert cache.cached(URL) is None


def test_cached_copy_with_other_pin_is_not_used(tmp_path: Path) -> None:
    with FileCache(tmp_path, _client(httpx.MockTransport(Recorder(_ok())))) as cache:
        cache.fetch(URL)
        assert cache.cached(URL, "0" * 64) is None
        assert cache.cached(URL, PAYLOAD_SHA) is not None


def test_pinned_checksum_mismatch_raises_and_keeps_cache_clean(tmp_path: Path) -> None:
    recorder = Recorder(_ok(b"a different file"))
    with (
        FileCache(tmp_path, _client(httpx.MockTransport(recorder))) as cache,
        pytest.raises(SourceChangedError, match="changed upstream"),
    ):
        cache.fetch(URL, PAYLOAD_SHA)
    assert list(cache_path(tmp_path, URL).parent.iterdir()) == []


def test_missing_file_raises_source_missing(tmp_path: Path) -> None:
    recorder = Recorder(httpx.Response(404))
    with (
        FileCache(tmp_path, _client(httpx.MockTransport(recorder))) as cache,
        pytest.raises(SourceMissingError, match="404"),
    ):
        cache.fetch(URL)
    assert recorder.calls == 1


def test_refused_request_is_not_retried(tmp_path: Path) -> None:
    recorder = Recorder(httpx.Response(403))
    with (
        FileCache(tmp_path, _client(httpx.MockTransport(recorder))) as cache,
        pytest.raises(RefusedError, match="403"),
    ):
        cache.fetch(URL)
    assert recorder.calls == 1


def test_transient_failures_are_retried(tmp_path: Path) -> None:
    sleeps: list[float] = []
    recorder = Recorder(
        httpx.ConnectError("reset"),
        httpx.Response(503),
        _ok(PAYLOAD, headers={"Content-Length": "999"}),
        _ok(),
    )
    with FileCache(tmp_path, _client(httpx.MockTransport(recorder)), sleep=sleeps.append) as cache:
        fetched = cache.fetch(URL)
    assert recorder.calls == 4
    assert sleeps == [2.0, 4.0, 8.0]
    assert fetched.path.read_bytes() == PAYLOAD


def test_gives_up_after_attempts(tmp_path: Path) -> None:
    recorder = Recorder(*[httpx.Response(500) for _ in range(3)])
    with (
        FileCache(
            tmp_path, _client(httpx.MockTransport(recorder)), attempts=3, sleep=lambda _: None
        ) as cache,
        pytest.raises(DownloadError, match="giving up"),
    ):
        cache.fetch(URL)
    assert recorder.calls == 3


def test_make_client_uses_ssl_cert_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    with make_client() as client:
        assert client.follow_redirects
        assert client.headers["User-Agent"].startswith("snowlight-pipeline/")


def _cache_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def test_unpinned_zip_url_serving_a_web_page_is_not_published(tmp_path: Path) -> None:
    recorder = Recorder(_page())
    with (
        FileCache(tmp_path, _client(httpx.MockTransport(recorder))) as cache,
        pytest.raises(SourceMissingError, match=r"served a web page, not the file; maintenance\?"),
    ):
        cache.fetch(NEWER_URL)
    assert recorder.calls == 1
    assert _cache_files(tmp_path) == []


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (MAINTENANCE_PAGE, "application/zip"),
        (b"", "application/zip"),
        (PAYLOAD, "text/html"),
    ],
)
def test_unpinned_zip_url_needs_zip_bytes_and_no_html_type(
    tmp_path: Path, body: bytes, content_type: str
) -> None:
    recorder = Recorder(_ok(body, headers={"Content-Type": content_type}))
    with (
        FileCache(tmp_path, _client(httpx.MockTransport(recorder))) as cache,
        pytest.raises(SourceMissingError, match="not the file"),
    ):
        cache.fetch(NEWER_URL)
    assert _cache_files(tmp_path) == []


def test_pinned_url_serving_a_web_page_still_fails_loudly(tmp_path: Path) -> None:
    recorder = Recorder(_page())
    with (
        FileCache(tmp_path, _client(httpx.MockTransport(recorder))) as cache,
        pytest.raises(SourceChangedError, match="changed upstream"),
    ):
        cache.fetch(URL, PAYLOAD_SHA)
    assert _cache_files(tmp_path) == []


def test_real_zip_passes_unpinned_and_is_reused(tmp_path: Path) -> None:
    body = _real_zip()
    recorder = Recorder(_ok(body, headers={"Content-Type": "application/x-zip-compressed"}))
    with FileCache(tmp_path, _client(httpx.MockTransport(recorder))) as cache:
        fetched = cache.fetch(NEWER_URL)
        again = cache.fetch(NEWER_URL)
    assert fetched.path.read_bytes() == body
    assert zipfile.is_zipfile(fetched.path)
    assert again.from_cache
    assert recorder.calls == 1


def test_cached_web_page_under_unpinned_zip_url_is_not_reused(tmp_path: Path) -> None:
    path = cache_path(tmp_path, NEWER_URL)
    path.parent.mkdir(parents=True)
    path.write_bytes(MAINTENANCE_PAGE)
    sidecar = {
        "bytes": len(MAINTENANCE_PAGE),
        "etag": None,
        "last_modified": None,
        "retrieved_at": "2026-10-21T17:00:00Z",
        "sha256": hashlib.sha256(MAINTENANCE_PAGE).hexdigest(),
        "url": NEWER_URL,
    }
    Path(str(path) + SIDECAR_SUFFIX).write_text(json.dumps(sidecar))
    recorder = Recorder(_page())
    with FileCache(tmp_path, _client(httpx.MockTransport(recorder))) as cache:
        assert cache.cached(NEWER_URL) is None
        with pytest.raises(SourceMissingError, match="web page"):
            cache.fetch(NEWER_URL)
    assert recorder.calls == 1


def test_build_falls_back_to_the_pinned_release_when_the_newer_one_is_a_web_page(
    tmp_path: Path,
) -> None:
    body = _real_zip()
    real = load_config()
    newer, pinned = real.sources["private_school_geocodes"].candidates
    assert newer.url == NEWER_URL
    assert newer.sha256 is None
    assert pinned.url == URL
    source = Source(
        title="private school geocodes",
        candidates=[newer, pinned.model_copy(update={"sha256": hashlib.sha256(body).hexdigest()})],
    )
    config = real.model_copy(update={"sources": {"private_school_geocodes": source}})
    answers = {NEWER_URL: _page(), URL: _ok(body)}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return answers[str(request.url)]

    logged: list[str] = []
    with FileCache(tmp_path, _client(httpx.MockTransport(handler))) as cache:
        fetched = fetch_sources(config, cache, logged.append)
    got = fetched["private_school_geocodes"]
    assert seen == [NEWER_URL, URL]
    assert got.candidate.url == URL
    assert got.file.path.read_bytes() == body
    assert [skip["url"] for skip in got.skipped] == [NEWER_URL]
    assert "served a web page" in got.skipped[0]["result"]
    assert "is not published" in logged[0]
    assert not cache_path(tmp_path, NEWER_URL).exists()

"""Checksummed, cached HTTPS downloads of official source files.

Every file the places build reads is fetched through :class:`SourceCache`. A
download is streamed to a temporary file next to its destination while its
SHA-256 is computed, checked against ``Content-Length`` when the server sends
one, and then renamed into place together with a sidecar
``<name>.provenance.json`` that records where and when it came from::

    {"bytes": 1234, "etag": "...", "last_modified": "...", "retrieved_at": "2026-09-24T23:12:01Z",
     "sha256": "...", "url": "https://..."}

A cached file is reused only when its sidecar exists, names the same URL and
its recorded SHA-256 matches the bytes on disk; anything else is downloaded
again. With ``revalidate=True`` a cached file is confirmed with a conditional
request (``If-None-Match`` / ``If-Modified-Since``); a ``304 Not Modified``
keeps the cached bytes and a ``200`` replaces them.

TLS verification always uses the CA bundle named by ``SSL_CERT_FILE`` when it
is set (the session proxy and GitHub Actions both rely on this); it is never
disabled.
"""

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

import httpx

from snowlight import __version__
from snowlight.output import write_bytes_atomic

USER_AGENT = f"snowlight-pipeline/{__version__} (+https://github.com/viaate/jsalcards)"
_CHUNK = 1 << 20
_SIDECAR_SUFFIX = ".provenance.json"
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_MISSING_STATUS = frozenset({404, 410})


class DownloadError(RuntimeError):
    """Raised when a source file cannot be fetched intact."""


class SourceMissingError(DownloadError):
    """Raised when the server says the file does not exist (HTTP 404 or 410)."""


@dataclass(frozen=True, slots=True)
class FetchedFile:
    """A source file on disk and the provenance of its bytes."""

    url: str
    path: Path
    sha256: str
    size: int
    retrieved_at: str
    etag: str | None
    last_modified: str | None
    from_cache: bool

    def provenance(self) -> dict[str, str | int | None]:
        """Return the JSON-ready provenance record kept in internal manifests."""
        return {
            "bytes": self.size,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "retrieved_at": self.retrieved_at,
            "sha256": self.sha256,
            "url": self.url,
        }


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of the file at ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now_iso() -> str:
    """Return the current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_client(timeout: float = 120.0) -> httpx.Client:
    """Return an HTTPS client that verifies TLS against ``SSL_CERT_FILE`` when set."""
    verify: str | bool = os.environ.get("SSL_CERT_FILE") or True
    return httpx.Client(
        verify=verify,
        timeout=httpx.Timeout(timeout, connect=30.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def cache_path_for(root: Path, url: str) -> Path:
    """Map ``url`` to its location under ``root``: ``<root>/<host>/<path>``.

    Raises:
        ValueError: for a non-HTTPS URL or one whose path could escape ``root``.
    """
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"only https URLs are fetched: {url!r}")
    segments = [s for s in parts.path.split("/") if s]
    if not segments or any(s in {".", ".."} for s in segments) or parts.query:
        raise ValueError(f"URL does not name a file: {url!r}")
    return root.joinpath(parts.hostname, *segments)


@contextmanager
def _temp_beside(path: Path) -> Iterator[Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    os.close(fd)
    tmp = Path(name)
    try:
        yield tmp
    finally:
        tmp.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class ConsultedPage:
    """A page read to discover releases (not cached, not a data source)."""

    url: str
    retrieved_at: str
    sha256: str

    def as_json(self) -> dict[str, str]:
        """Return the JSON-ready record kept in internal manifests."""
        return {"retrieved_at": self.retrieved_at, "sha256": self.sha256, "url": self.url}


class SourceCache:
    """Downloads files once into ``root`` and serves verified copies afterwards."""

    def __init__(
        self,
        root: Path,
        client: httpx.Client,
        *,
        revalidate: bool = False,
        attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.root = root
        self.client = client
        self.revalidate = revalidate
        self.attempts = attempts
        self._sleep = sleep
        self.pages_consulted: list[ConsultedPage] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.client.close()

    def get_text(self, url: str) -> str:
        """Fetch a small page (a directory listing) without caching it.

        Each page read is remembered in :attr:`pages_consulted` for the manifest.
        """
        response = self._request("GET", url, headers={})
        self.pages_consulted.append(
            ConsultedPage(url, utc_now_iso(), hashlib.sha256(response.content).hexdigest())
        )
        return response.text

    def fetch(self, url: str) -> FetchedFile:
        """Return the verified local copy of ``url``, downloading it when needed."""
        path = cache_path_for(self.root, url)
        cached = self._load_cached(url, path)
        if cached is not None and not self.revalidate:
            return cached
        headers: dict[str, str] = {}
        if cached is not None:
            if cached.etag:
                headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                headers["If-Modified-Since"] = cached.last_modified
        return self._download(url, path, headers, cached)

    def _load_cached(self, url: str, path: Path) -> FetchedFile | None:
        sidecar = path.with_name(path.name + _SIDECAR_SUFFIX)
        if not path.is_file() or not sidecar.is_file():
            return None
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            recorded = str(meta["sha256"])
            recorded_url = str(meta["url"])
            retrieved_at = str(meta["retrieved_at"])
        except (ValueError, KeyError, TypeError):
            return None
        if recorded_url != url or sha256_file(path) != recorded:
            return None
        etag, modified = meta.get("etag"), meta.get("last_modified")
        return FetchedFile(
            url=url,
            path=path,
            sha256=recorded,
            size=path.stat().st_size,
            retrieved_at=retrieved_at,
            etag=etag if isinstance(etag, str) else None,
            last_modified=modified if isinstance(modified, str) else None,
            from_cache=True,
        )

    def _download(
        self, url: str, path: Path, headers: dict[str, str], cached: FetchedFile | None
    ) -> FetchedFile:
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            if attempt:
                self._sleep(min(2.0**attempt, 30.0))
            try:
                return self._download_once(url, path, headers, cached)
            except (httpx.TransportError, _RetryableStatusError, _TruncatedError) as exc:
                last_error = exc
        raise DownloadError(f"giving up on {url} after {self.attempts} attempts") from last_error

    def _download_once(
        self, url: str, path: Path, headers: dict[str, str], cached: FetchedFile | None
    ) -> FetchedFile:
        with self.client.stream("GET", url, headers=headers) as response:
            if response.status_code == httpx.codes.NOT_MODIFIED and cached is not None:
                return cached
            _raise_for_status(url, response)
            expected = response.headers.get("Content-Length")
            digest = hashlib.sha256()
            size = 0
            with _temp_beside(path) as tmp:
                with tmp.open("wb") as handle:
                    for chunk in response.iter_bytes(_CHUNK):
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                encoded = response.headers.get("Content-Encoding", "identity")
                if expected is not None and encoded == "identity" and int(expected) != size:
                    raise _TruncatedError(f"{url}: got {size} of {expected} bytes")
                if size == 0:
                    raise DownloadError(f"{url}: empty response body")
                fetched = FetchedFile(
                    url=url,
                    path=path,
                    sha256=digest.hexdigest(),
                    size=size,
                    retrieved_at=utc_now_iso(),
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    from_cache=False,
                )
                tmp.chmod(0o644)
                tmp.replace(path)
        sidecar = path.with_name(path.name + _SIDECAR_SUFFIX)
        text = json.dumps(fetched.provenance(), indent=2, sort_keys=True) + "\n"
        write_bytes_atomic(sidecar, text.encode("utf-8"))
        return fetched

    def _request(self, method: str, url: str, headers: dict[str, str]) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            if attempt:
                self._sleep(min(2.0**attempt, 30.0))
            try:
                response = self.client.request(method, url, headers=headers)
                _raise_for_status(url, response)
            except (httpx.TransportError, _RetryableStatusError) as exc:
                last_error = exc
                continue
            return response
        raise DownloadError(f"giving up on {url} after {self.attempts} attempts") from last_error


class _RetryableStatusError(RuntimeError):
    pass


class _TruncatedError(RuntimeError):
    pass


def _raise_for_status(url: str, response: httpx.Response) -> None:
    if response.status_code in _RETRYABLE_STATUS:
        raise _RetryableStatusError(f"{url}: HTTP {response.status_code}")
    if response.status_code in _MISSING_STATUS:
        raise SourceMissingError(f"{url}: HTTP {response.status_code}")
    if response.status_code != httpx.codes.OK:
        raise DownloadError(f"{url}: HTTP {response.status_code}")

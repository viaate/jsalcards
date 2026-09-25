"""Cached, checksummed HTTPS downloads of NCES source files.

A download streams to a temporary file beside its destination while its SHA-256
is computed. The byte count is checked against ``Content-Length`` when the
server sends one, then the file is renamed into place next to a sidecar
``<name>.provenance.json``::

    {"bytes": 30448565, "etag": "...", "last_modified": "Fri, 19 Dec 2025 23:56:44 GMT",
     "retrieved_at": "2026-09-24T23:20:11Z", "sha256": "...", "url": "https://nces.ed.gov/..."}

A cached file is reused, with no network request, only when its sidecar names the
same URL and the SHA-256 of the bytes on disk equals the recorded one (and the
pinned one, when the caller pins a checksum). Anything else is downloaded again.
A pinned checksum that a fresh download does not match raises
:class:`SourceChangedError` and leaves the cache untouched, so a silently revised
upstream file can never slip into a build.

TLS is always verified, against the CA bundle named by ``SSL_CERT_FILE`` when it
is set.
"""

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

import httpx

from snowlight import __version__

USER_AGENT = f"snowlight-pipeline/{__version__}"
SIDECAR_SUFFIX = ".provenance.json"
_CHUNK = 1 << 20
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_MISSING_STATUS = frozenset({404, 410})


class DownloadError(RuntimeError):
    """A source file could not be fetched intact."""


class SourceMissingError(DownloadError):
    """The server answered that the file does not exist (HTTP 404 or 410)."""


class SourceChangedError(DownloadError):
    """The downloaded bytes do not match the checksum pinned in the config."""


class RefusedError(DownloadError):
    """The server refused the request with a status that retrying will not fix."""


@dataclass(frozen=True, slots=True)
class Retrieved:
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


def make_client(timeout: float = 300.0) -> httpx.Client:
    """Return an HTTPS client that verifies TLS against ``SSL_CERT_FILE`` when set."""
    verify: str | bool = os.environ.get("SSL_CERT_FILE") or True
    return httpx.Client(
        verify=verify,
        timeout=httpx.Timeout(timeout, connect=30.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def cache_path(root: Path, url: str) -> Path:
    """Map ``url`` to ``<root>/<host>/<path>``.

    Raises:
        ValueError: for a URL that is not HTTPS, has a query, or could escape ``root``.
    """
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"only https URLs are fetched: {url!r}")
    segments = [s for s in parts.path.split("/") if s]
    if not segments or any(s in {".", ".."} for s in segments) or parts.query:
        raise ValueError(f"URL does not name a file: {url!r}")
    return root.joinpath(parts.hostname, *segments)


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + SIDECAR_SUFFIX)


class FileCache:
    """Downloads each URL once into ``root`` and serves verified copies afterwards."""

    def __init__(
        self,
        root: Path,
        client: httpx.Client,
        *,
        attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.root = root
        self.client = client
        self.attempts = attempts
        self._sleep = sleep

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.client.close()

    def cached(self, url: str, expected_sha256: str | None = None) -> Retrieved | None:
        """Return the verified cached copy of ``url``, or ``None`` if there is none."""
        path = cache_path(self.root, url)
        sidecar = _sidecar(path)
        if not path.is_file() or not sidecar.is_file():
            return None
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            recorded = str(meta["sha256"])
            recorded_url = str(meta["url"])
            retrieved_at = str(meta["retrieved_at"])
        except (ValueError, KeyError, TypeError):
            return None
        if recorded_url != url:
            return None
        if expected_sha256 is not None and recorded != expected_sha256:
            return None
        if sha256_file(path) != recorded:
            return None
        etag, modified = meta.get("etag"), meta.get("last_modified")
        return Retrieved(
            url=url,
            path=path,
            sha256=recorded,
            size=path.stat().st_size,
            retrieved_at=retrieved_at,
            etag=etag if isinstance(etag, str) else None,
            last_modified=modified if isinstance(modified, str) else None,
            from_cache=True,
        )

    def fetch(self, url: str, expected_sha256: str | None = None) -> Retrieved:
        """Return the verified local copy of ``url``, downloading it when needed.

        Raises:
            SourceMissingError: the server says the file does not exist.
            SourceChangedError: the fresh bytes do not match ``expected_sha256``.
            RefusedError: the server refused the request (for example HTTP 403).
            DownloadError: the file could not be fetched intact after retries.
        """
        hit = self.cached(url, expected_sha256)
        if hit is not None:
            return hit
        path = cache_path(self.root, url)
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            if attempt:
                self._sleep(min(2.0**attempt, 30.0))
            try:
                return self._download_once(url, path, expected_sha256)
            except (SourceMissingError, SourceChangedError, RefusedError):
                raise
            except (httpx.TransportError, DownloadError) as error:
                last_error = error
        raise DownloadError(f"giving up on {url} after {self.attempts} attempts") from last_error

    def _download_once(self, url: str, path: Path, expected_sha256: str | None) -> Retrieved:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
        tmp = Path(tmp_name)
        try:
            retrieved_at = utc_now_iso()
            digest = hashlib.sha256()
            size = 0
            with os.fdopen(fd, "wb") as handle, self.client.stream("GET", url) as response:
                if response.status_code in _MISSING_STATUS:
                    raise SourceMissingError(f"{url} answered HTTP {response.status_code}")
                if response.status_code != httpx.codes.OK:
                    message = f"{url} answered HTTP {response.status_code}"
                    if response.status_code in _RETRYABLE_STATUS:
                        raise DownloadError(message)
                    raise RefusedError(message)
                declared = response.headers.get("Content-Length")
                for chunk in response.iter_bytes(_CHUNK):
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
            if declared is not None and int(declared) != size:
                raise DownloadError(f"{url}: got {size} bytes, server declared {declared}")
            sha256 = digest.hexdigest()
            if expected_sha256 is not None and sha256 != expected_sha256:
                raise SourceChangedError(
                    f"{url} changed upstream: SHA-256 {sha256}, config pins {expected_sha256}. "
                    "Review the new file, then update the pin in config/directory.yaml."
                )
            tmp.chmod(0o644)
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
        record = Retrieved(
            url=url,
            path=path,
            sha256=sha256,
            size=size,
            retrieved_at=retrieved_at,
            etag=etag,
            last_modified=last_modified,
            from_cache=False,
        )
        text = json.dumps(record.provenance(), indent=2, sort_keys=True) + "\n"
        _sidecar(path).write_text(text, encoding="utf-8")
        return record

"""HTTPS fetches for weather sources, with a checksummed cache that records provenance.

Every file this package reads from the network goes through :class:`HttpCache`.
A download is streamed to a temporary file beside its destination while its
SHA-256 (and MD5, when the publisher lists one to check against) is computed,
checked against ``Content-Length`` when the body was not content-encoded, and
renamed into place next to a sidecar ``<name>.provenance.json``::

    {"bytes": 1563001, "checked_at": "2026-09-24T23:45:02Z", "etag": "W/\\"90dd...\\"",
     "last_modified": null, "retrieved_at": "2026-09-24T23:43:17Z",
     "sha256": "...", "url": "https://api.weather.gov/alerts/active?..."}

``retrieved_at`` is when the bytes on disk were downloaded; ``checked_at`` is the
last time the server confirmed them (the download itself, or a later
``304 Not Modified``).

A cached copy is used only when its sidecar names the same URL and the SHA-256 of
the bytes on disk equals the recorded one. How long it is trusted without asking
the server again is the caller's ``max_age``:

* ``None``: forever. For versioned files whose name changes with their content.
* a duration: until ``checked_at`` is that old, then a conditional request
  (``If-None-Match`` / ``If-Modified-Since``) either confirms the copy (``304``)
  or replaces it (``200``). ``timedelta(0)`` asks every time.

Requests carry a User-Agent that names this repository, as the NWS API requires.
TLS is always verified, against the CA bundle named by ``SSL_CERT_FILE`` when it
is set. Transport errors, ``408``/``425``/``429`` and ``5xx`` answers are retried
with backoff (honouring a short ``Retry-After``); other statuses fail at once.
"""

import hashlib
import json
import os
import ssl
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self

import httpx

from snowlight import __version__
from snowlight.output import JSONValue, write_bytes_atomic

USER_AGENT = f"snowlight-pipeline/{__version__} (+https://github.com/viaate/jsalcards)"
SIDECAR_SUFFIX = ".provenance.json"
_CHUNK = 1 << 20
_RETRYABLE = frozenset({408, 425, 429, 500, 502, 503, 504})
_MISSING = frozenset({404, 410})
_MAX_RETRY_AFTER = 60.0

type Clock = Callable[[], datetime]


class FetchError(RuntimeError):
    """A source could not be fetched intact."""


class NotFoundError(FetchError):
    """The server answered that the resource does not exist (HTTP 404 or 410)."""


class ChecksumMismatchError(FetchError):
    """The downloaded bytes do not match the checksum the publisher lists."""


class _RetryableError(FetchError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def iso_utc(moment: datetime) -> str:
    """Format an aware datetime as ``YYYY-MM-DDTHH:MM:SSZ`` in UTC."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(text: str) -> datetime:
    """Parse a timestamp written by :func:`iso_utc` (or any ISO 8601 with an offset)."""
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"timestamp has no UTC offset: {text!r}")
    return moment.astimezone(UTC)


def system_clock() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a cached file came from and when."""

    url: str
    sha256: str
    size: int
    retrieved_at: str
    checked_at: str
    etag: str | None
    last_modified: str | None

    def as_json(self) -> dict[str, JSONValue]:
        """Return the JSON-ready record written to the sidecar and to internal manifests."""
        return {
            "bytes": self.size,
            "checked_at": self.checked_at,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "retrieved_at": self.retrieved_at,
            "sha256": self.sha256,
            "url": self.url,
        }

    @classmethod
    def from_json(cls, data: object) -> "Provenance | None":
        """Rebuild a record from a sidecar, or return ``None`` if it is malformed."""
        if not isinstance(data, dict):
            return None
        try:
            url, sha, size = data["url"], data["sha256"], data["bytes"]
            retrieved = data["retrieved_at"]
        except KeyError:
            return None
        checked = data.get("checked_at", retrieved)
        etag, modified = data.get("etag"), data.get("last_modified")
        texts = (url, sha, retrieved, checked)
        if not all(isinstance(value, str) for value in texts) or not isinstance(size, int):
            return None
        return cls(
            url=str(url),
            sha256=str(sha),
            size=size,
            retrieved_at=str(retrieved),
            checked_at=str(checked),
            etag=etag if isinstance(etag, str) else None,
            last_modified=modified if isinstance(modified, str) else None,
        )


@dataclass(frozen=True, slots=True)
class CachedFile:
    """A verified local copy of a remote file.

    Attributes:
        path: where the bytes are.
        provenance: the URL, checksum and times recorded for these bytes.
        downloaded: whether this call transferred the bytes (``False`` for a cache
            hit or a ``304``).
        not_modified: whether this call's conditional request was answered ``304``.
    """

    path: Path
    provenance: Provenance
    downloaded: bool
    not_modified: bool = False


def make_client(timeout: float = 120.0) -> httpx.Client:
    """Return an HTTPS client that names this repository and verifies TLS.

    The CA bundle named by ``SSL_CERT_FILE`` is used when it is set (the session
    proxy and CI rely on it); otherwise httpx's default bundle.
    """
    bundle = os.environ.get("SSL_CERT_FILE")
    verify: ssl.SSLContext | bool = ssl.create_default_context(cafile=bundle) if bundle else True
    return httpx.Client(
        verify=verify,
        timeout=httpx.Timeout(timeout, connect=30.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of the file at ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    """Return the hex MD5 of the file at ``path`` (only to compare with a published sum)."""
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def sidecar_path(path: Path) -> Path:
    """Return the provenance sidecar path for the cached file at ``path``."""
    return path.with_name(path.name + SIDECAR_SUFFIX)


def _request_headers(cached: CachedFile | None, accept: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if accept:
        headers["Accept"] = accept
    if cached is not None and cached.provenance.etag:
        headers["If-None-Match"] = cached.provenance.etag
    if cached is not None and cached.provenance.last_modified:
        headers["If-Modified-Since"] = cached.provenance.last_modified
    return headers


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    try:
        seconds = float(value)
    except ValueError:
        return None
    return min(max(seconds, 0.0), _MAX_RETRY_AFTER)


class HttpCache:
    """Fetches URLs into caller-chosen paths and serves verified copies afterwards."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        clock: Clock = system_clock,
    ) -> None:
        self.client = client
        self.attempts = attempts
        self._sleep = sleep
        self._clock = clock

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.client.close()

    def now(self) -> datetime:
        """Return the cache's notion of the current time (UTC)."""
        return self._clock()

    def cached(self, url: str, dest: Path) -> CachedFile | None:
        """Return the verified copy of ``url`` at ``dest``, or ``None`` if there is none."""
        sidecar = sidecar_path(dest)
        if not dest.is_file() or not sidecar.is_file():
            return None
        try:
            record = Provenance.from_json(json.loads(sidecar.read_text(encoding="utf-8")))
        except ValueError:
            return None
        if record is None or record.url != url or sha256_file(dest) != record.sha256:
            return None
        return CachedFile(dest, record, downloaded=False)

    def fetch(
        self,
        url: str,
        dest: Path,
        *,
        max_age: timedelta | None = None,
        expected_md5: str | None = None,
        accept: str | None = None,
    ) -> CachedFile:
        """Return a verified local copy of ``url`` at ``dest``, downloading when needed.

        Args:
            url: the HTTPS URL to fetch.
            dest: where the file lives in the cache.
            max_age: how long a cached copy is trusted without asking the server
                (see the module docstring); ``None`` trusts it forever.
            expected_md5: the MD5 the publisher lists for the file; a download
                that does not match raises :class:`ChecksumMismatchError` and
                leaves any cached copy untouched.
            accept: an ``Accept`` header to send.

        Raises:
            NotFoundError: the server says the resource does not exist.
            ChecksumMismatchError: the bytes do not match ``expected_md5``.
            FetchError: the resource could not be fetched intact after retries.
        """
        if not url.startswith("https://"):
            raise ValueError(f"only https URLs are fetched: {url!r}")
        if expected_md5 is not None:
            expected_md5 = expected_md5.lower()
        cached = self.cached(url, dest)
        # A copy recorded before the publisher listed a checksum must match it too.
        if cached is not None and expected_md5 is not None and md5_file(dest) != expected_md5:
            cached = None
        if cached is not None and self._fresh(cached, max_age):
            return cached
        headers = _request_headers(cached, accept)
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                return self._fetch_once(url, dest, headers, cached, expected_md5)
            except (NotFoundError, ChecksumMismatchError):
                raise
            except _RetryableError as error:
                last_error = error
                delay = error.retry_after
            except (httpx.TransportError, httpx.DecodingError) as error:
                last_error = error
                delay = None
            if attempt + 1 < self.attempts:
                self._sleep(delay if delay is not None else min(2.0 ** (attempt + 1), 30.0))
        raise FetchError(f"giving up on {url} after {self.attempts} attempts") from last_error

    def _fresh(self, cached: CachedFile, max_age: timedelta | None) -> bool:
        if max_age is None:
            return True
        try:
            checked = parse_iso_utc(cached.provenance.checked_at)
        except ValueError:
            return False
        return self.now() - checked < max_age

    def _fetch_once(
        self,
        url: str,
        dest: Path,
        headers: dict[str, str],
        cached: CachedFile | None,
        expected_md5: str | None,
    ) -> CachedFile:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self.client.stream("GET", url, headers=headers) as response:
            status = response.status_code
            if status == httpx.codes.NOT_MODIFIED and cached is not None:
                return self._confirm(cached)
            if status in _MISSING:
                raise NotFoundError(f"{url} answered HTTP {status}")
            if status in _RETRYABLE:
                raise _RetryableError(f"{url} answered HTTP {status}", _retry_after(response))
            if status != httpx.codes.OK:
                raise FetchError(f"{url} answered HTTP {status}")
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{dest.name}.", suffix=".part", dir=dest.parent
            )
            tmp = Path(tmp_name)
            try:
                sha, md5, size = hashlib.sha256(), hashlib.md5(usedforsecurity=False), 0
                with os.fdopen(fd, "wb") as handle:
                    for chunk in response.iter_bytes(_CHUNK):
                        handle.write(chunk)
                        sha.update(chunk)
                        md5.update(chunk)
                        size += len(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                declared = response.headers.get("Content-Length")
                encoded = response.headers.get("Content-Encoding", "identity") != "identity"
                if declared is not None and not encoded and int(declared) != size:
                    raise _RetryableError(f"{url}: got {size} bytes, server declared {declared}")
                if size == 0:
                    raise _RetryableError(f"{url}: empty response body")
                if expected_md5 is not None and md5.hexdigest() != expected_md5:
                    raise ChecksumMismatchError(
                        f"{url}: MD5 {md5.hexdigest()} does not match the listed {expected_md5}"
                    )
                stamp = iso_utc(self.now())
                record = Provenance(
                    url=url,
                    sha256=sha.hexdigest(),
                    size=size,
                    retrieved_at=stamp,
                    checked_at=stamp,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                )
                tmp.chmod(0o644)
                tmp.replace(dest)
            finally:
                tmp.unlink(missing_ok=True)
        self._write_sidecar(dest, record)
        return CachedFile(dest, record, downloaded=True)

    def _confirm(self, cached: CachedFile) -> CachedFile:
        record = replace(cached.provenance, checked_at=iso_utc(self.now()))
        self._write_sidecar(cached.path, record)
        return CachedFile(cached.path, record, downloaded=False, not_modified=True)

    @staticmethod
    def _write_sidecar(dest: Path, record: Provenance) -> None:
        text = json.dumps(record.as_json(), indent=2, sort_keys=True) + "\n"
        write_bytes_atomic(sidecar_path(dest), text.encode("utf-8"))

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

A server can answer HTTP 200 with a web page in place of a file (nces.ed.gov does
during scheduled maintenance). For an unpinned ``.zip`` URL, a body that does not
start with the zip magic ``PK\x03\x04`` or comes as ``text/html`` raises
:class:`SourceMissingError`, so a caller with older candidates falls back to them;
the body is never cached, and a cached copy that is not a zip is not reused. A
pinned URL needs no such check: its checksum already refuses any other body, with
:class:`SourceChangedError`.

With a :class:`~snowlight.sources.mirror.Mirror`, a file the cache does not hold
is read from the data mirror, never from its origin, and only when its URL is
pinned: an unpinned URL is :class:`SourceMissingError` (the mirror serves pinned
files only, so a caller with older pinned candidates falls back to them), and a
pinned file the mirror lacks is a plain :class:`DownloadError`, never "not
published".

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
from snowlight.sources.mirror import Mirror, MirrorError, fetch_pinned

USER_AGENT = f"snowlight-pipeline/{__version__}"
SIDECAR_SUFFIX = ".provenance.json"
_CHUNK = 1 << 20
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_MISSING_STATUS = frozenset({404, 410})
_ZIP_MAGIC = b"PK\x03\x04"


class DownloadError(RuntimeError):
    """A source file could not be fetched intact."""


class SourceMissingError(DownloadError):
    """The server answered that the file does not exist (HTTP 404 or 410).

    Also raised when an unpinned zip URL answers with a web page instead of the file.
    """


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
    mirror: str | None = None
    """The data mirror URL the bytes came from, when not from ``url`` itself."""

    def provenance(self) -> dict[str, str | int | None]:
        """Return the JSON-ready provenance record kept in internal manifests."""
        record: dict[str, str | int | None] = {
            "bytes": self.size,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "retrieved_at": self.retrieved_at,
            "sha256": self.sha256,
            "url": self.url,
        }
        if self.mirror is not None:
            record["mirror"] = self.mirror
        return record


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


def _wants_zip_check(url: str, expected_sha256: str | None) -> bool:
    """True for an unpinned URL that names a ``.zip`` file."""
    return expected_sha256 is None and urlsplit(url).path.lower().endswith(".zip")


def _starts_as_zip(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(_ZIP_MAGIC)) == _ZIP_MAGIC


class FileCache:
    """Downloads each URL once into ``root`` and serves verified copies afterwards."""

    def __init__(  # noqa: PLR0913 - where, how, and from which mirror
        self,
        root: Path,
        client: httpx.Client,
        *,
        attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        mirror: Mirror | None = None,
        log: Callable[[str], object] = lambda _line: None,
    ) -> None:
        self.root = root
        self.client = client
        self.attempts = attempts
        self._sleep = sleep
        self.mirror = mirror
        self._log = log

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
        if sha256_file(path) != recorded or (
            _wants_zip_check(url, expected_sha256) and not _starts_as_zip(path)
        ):
            return None
        etag, modified = meta.get("etag"), meta.get("last_modified")
        mirror = meta.get("mirror")
        return Retrieved(
            url=url,
            path=path,
            sha256=recorded,
            size=path.stat().st_size,
            retrieved_at=retrieved_at,
            etag=etag if isinstance(etag, str) else None,
            last_modified=modified if isinstance(modified, str) else None,
            from_cache=True,
            mirror=mirror if isinstance(mirror, str) else None,
        )

    def fetch(self, url: str, expected_sha256: str | None = None) -> Retrieved:
        """Return the verified local copy of ``url``, downloading it when needed.

        Raises:
            SourceMissingError: the server says the file does not exist, or serves a
                web page with HTTP 200 for an unpinned zip URL.
            SourceChangedError: the fresh bytes do not match ``expected_sha256``.
            RefusedError: the server refused the request (for example HTTP 403).
            DownloadError: the file could not be fetched intact after retries, or
                the data mirror does not hold it.
        """
        if self.mirror is not None:
            return self._fetch_mirrored(self.mirror, url, expected_sha256)
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

    def _fetch_mirrored(self, mirror: Mirror, url: str, expected_sha256: str | None) -> Retrieved:
        if expected_sha256 is None:
            raise SourceMissingError(
                f"{url} is not pinned, and the data mirror serves pinned files only"
            )
        pin = mirror.pin(url)
        if pin is None or pin.sha256 != expected_sha256:
            raise RefusedError(f"{url}: the data mirror's pin set does not pin {expected_sha256}")
        hit = self.cached(url, expected_sha256)
        if hit is not None:
            return hit
        try:
            copy = fetch_pinned(
                self.client,
                mirror,
                pin,
                cache_path(self.root, url),
                attempts=self.attempts,
                sleep=self._sleep,
                log=self._log,
            )
        except MirrorError as error:
            raise DownloadError(str(error)) from error
        return Retrieved(
            url=url,
            path=copy.path,
            sha256=copy.sha256,
            size=copy.size,
            retrieved_at=copy.retrieved_at,
            etag=None,
            last_modified=None,
            from_cache=False,
            mirror=copy.mirror_url,
        )

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
                content_type = response.headers.get("Content-Type", "")
                head = b""
                for chunk in response.iter_bytes(_CHUNK):
                    if len(head) < len(_ZIP_MAGIC):
                        head = (head + chunk)[: len(_ZIP_MAGIC)]
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
            if _wants_zip_check(url, expected_sha256) and (
                head != _ZIP_MAGIC or "html" in content_type.lower()
            ):
                shown = content_type or "no content type"
                raise SourceMissingError(
                    f"{url} served a web page, not the file; maintenance? "
                    f"(HTTP 200, {shown}, {size} bytes)"
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

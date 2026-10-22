"""The data mirror: the pinned NCES and Census files, served from a GitHub release.

Deploys read every external file the directory and places builds need from a
release of this repository, never from nces.ed.gov or census.gov. The release
for a pin set is tagged ``data-mirror-<digest>``, where the digest covers every
pinned URL with its SHA-256, so a new pin means a new release and an old release
never changes under a deploy. Each file is an asset named after the last segment
of its origin URL. ``.github/workflows/data-mirror.yml`` seeds the release from
the origins (``snowlight mirror seed``); it is the only job that contacts them.

A file read from the mirror is checked against its pin exactly like one read
from its origin, and kept in the same download cache under its origin URL, with
the mirror URL recorded beside it. A pinned file the mirror does not hold is a
:class:`MirrorMissingError`, never a "not published" answer: a deploy must not
fall back to an older release because the mirror is behind.

One pin has another form. The Census LSAD code list is a web page whose bytes
differ on every load (it embeds per-request tokens), so no checksum of the page
can be pinned. It is pinned, seeded and served as :func:`lsad_table_page`: the
code table alone, written the same way every time, which the places build reads
exactly as it reads the full page.
"""

import hashlib
import html
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from snowlight.sources.census import CensusFormatError
from snowlight.sources.census.lsad import parse_lsad_codes

ENV_ROOT = "SNOWLIGHT_MIRROR"
ENV_WAIT = "SNOWLIGHT_MIRROR_WAIT"
ENV_REQUIRE = "SNOWLIGHT_REQUIRE_MIRROR"
"""Set to ``1`` in a deploy: a build with no mirror root then refuses to run (exit 2)
instead of reading the origins."""
TAG_PREFIX = "data-mirror-"
SIDECAR_SUFFIX = ".provenance.json"
_CHUNK = 1 << 20
_ASSET_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_MISSING_STATUS = frozenset({404, 410})
_LSAD_HEADER = ("LSAD", "LSAD Description", "Associated Geographic Entity")


class MirrorError(RuntimeError):
    """The mirror cannot serve a file intact (it is not pinned, or did not arrive)."""


class MirrorMissingError(MirrorError):
    """The mirror release does not hold a pinned file (yet)."""


class PinMismatchError(MirrorError):
    """A file read from the mirror does not match its pin."""


class Form(StrEnum):
    """How a pinned file is checked."""

    FILE = "file"
    """The SHA-256 of the file's bytes."""
    LSAD_TABLE = "lsad-table"
    """The SHA-256 of :func:`lsad_table_page` of the page's code table."""


@dataclass(frozen=True, slots=True)
class Pin:
    """One pinned origin file."""

    url: str
    sha256: str
    form: Form = Form.FILE

    @property
    def asset(self) -> str:
        """The release asset name: the last segment of the origin URL."""
        return asset_name(self.url)

    def matches(self, path: Path) -> bool:
        """Whether the file at ``path`` is this pin's file."""
        return pinned_digest(path, self.form) == self.sha256


def asset_name(url: str) -> str:
    """Return the asset name for ``url``.

    Raises:
        ValueError: if the URL is not https or its last segment is not a plain file name.
    """
    parts = urlsplit(url)
    name = parts.path.rsplit("/", 1)[-1]
    if parts.scheme != "https" or parts.query or not name or not set(name) <= _ASSET_CHARS:
        raise ValueError(f"no mirror asset name for {url!r}")
    return name


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of the file at ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def lsad_table_page(page: str) -> bytes:
    """Return the LSAD code table of ``page`` as a minimal page, the same bytes every time.

    :func:`parse_lsad_codes` reads it back to the very codes it read from ``page``.

    Raises:
        CensusFormatError: if ``page`` has no LSAD code table.
    """
    rows = ["".join(f"<th>{name}</th>" for name in _LSAD_HEADER)]
    for code in parse_lsad_codes(page):
        cells = (code.code, code.description, ", ".join(sorted(code.entities)))
        rows.append("".join(f"<td>{html.escape(cell, quote=False)}</td>" for cell in cells))
    body = "\n".join(f"<tr>{row}</tr>" for row in rows)
    return f"<!doctype html>\n<table>\n{body}\n</table>\n".encode()


def pinned_digest(path: Path, form: Form) -> str | None:
    """Return the digest of the file at ``path`` that a pin of ``form`` records.

    ``None`` when the file cannot have that form (an LSAD page with no code table).
    """
    if form is Form.FILE:
        return sha256_file(path)
    try:
        return sha256_bytes(lsad_table_page(path.read_text(encoding="utf-8")))
    except (CensusFormatError, UnicodeDecodeError):
        return None


def pin_set_tag(pins: Iterable[Pin]) -> str:
    """Return the release tag of a pin set: ``data-mirror-`` and 12 hex digits."""
    lines = sorted(f"{pin.url} {pin.sha256} {pin.form.value}\n" for pin in pins)
    return TAG_PREFIX + sha256_bytes("".join(lines).encode())[:12]


def check_pin_set(pins: Iterable[Pin]) -> tuple[Pin, ...]:
    """Return the pins sorted by URL, each URL once.

    Raises:
        ValueError: when one URL carries two pins or two URLs share an asset name.
    """
    by_url: dict[str, Pin] = {}
    for pin in pins:
        if by_url.setdefault(pin.url, pin) != pin:
            raise ValueError(f"{pin.url} is pinned twice, differently")
    assets: dict[str, str] = {}
    for url, pin in by_url.items():
        other = assets.setdefault(pin.asset, url)
        if other != url:
            raise ValueError(f"{url} and {other} would share the mirror asset {pin.asset}")
    return tuple(by_url[url] for url in sorted(by_url))


@dataclass(frozen=True, slots=True)
class Mirror:
    """A mirror release: where it is and which pins it holds."""

    root: str
    """The releases download root, e.g. ``https://github.com/<owner>/<repo>/releases/download``."""
    pins: tuple[Pin, ...]
    wait_seconds: float = 0.0
    """How long to wait for a pinned file the release does not hold yet."""
    poll_seconds: float = 30.0
    release: str | None = None
    """Another release's tag to read (an earlier pin set's), in place of this pin set's."""

    def __post_init__(self) -> None:
        if not self.root.startswith("https://") or urlsplit(self.root).query:
            raise ValueError(f"the mirror root must be an https URL: {self.root!r}")
        if self.release is not None and not (
            self.release.startswith(TAG_PREFIX) and set(self.release) <= _ASSET_CHARS
        ):
            raise ValueError(f"not a data mirror release tag: {self.release!r}")
        if not (self.wait_seconds >= 0 and self.poll_seconds > 0):
            raise ValueError("the mirror's wait must be >= 0 and its poll interval > 0")
        object.__setattr__(self, "pins", check_pin_set(self.pins))

    @property
    def tag(self) -> str:
        """The release tag read: :attr:`release`, else this pin set's."""
        return self.release if self.release is not None else pin_set_tag(self.pins)

    @property
    def base_url(self) -> str:
        """The URL of the release's assets, ending in ``/``."""
        return f"{self.root.rstrip('/')}/{self.tag}/"

    def pin(self, url: str) -> Pin | None:
        """Return the pin of the origin ``url``, or ``None`` when it is not pinned."""
        return next((pin for pin in self.pins if pin.url == url), None)

    def url_for(self, pin: Pin) -> str:
        """Return the mirror URL of a pinned file."""
        return self.base_url + pin.asset


def wait_from_env(default: float = 0.0) -> float:
    """Return :data:`ENV_WAIT` as seconds, or ``default`` when unset or empty."""
    text = os.environ.get(ENV_WAIT, "").strip()
    if not text:
        return default
    seconds = float(text)
    if not seconds >= 0:
        raise ValueError(f"{ENV_WAIT} must be a number of seconds, got {text!r}")
    return seconds


@dataclass(frozen=True, slots=True)
class MirrorCopy:
    """A pinned file just read from the mirror into the download cache."""

    path: Path
    sha256: str
    size: int
    retrieved_at: str
    mirror_url: str


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_sidecar(path: Path, record: dict[str, object]) -> None:
    """Write the provenance sidecar ``<name>.provenance.json`` of a cached file."""
    sidecar = path.with_name(path.name + SIDECAR_SUFFIX)
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{sidecar.name}.", suffix=".tmp", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    Path(tmp_name).replace(sidecar)


class _RetryError(Exception):
    pass


class _MissingError(Exception):
    pass


def fetch_pinned(  # noqa: PLR0913 - the file, where it goes, and how patiently
    client: httpx.Client,
    mirror: Mirror,
    pin: Pin,
    dest: Path,
    *,
    attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], object] = lambda _line: None,
) -> MirrorCopy:
    """Download ``pin`` from the mirror to ``dest`` and write its sidecar.

    The sidecar names the origin URL, so the cache serves the file to later runs
    as that URL's file, and records the mirror URL it came from.

    Raises:
        MirrorMissingError: the release does not hold the file, after waiting up to
            ``mirror.wait_seconds`` for it.
        PinMismatchError: the file does not match its pin.
        MirrorError: the file could not be read intact after ``attempts`` tries.
    """
    source = mirror.url_for(pin)
    waited = 0.0
    tries = 0
    last: Exception | None = None
    while tries < attempts:
        if tries:
            sleep(min(2.0**tries, 30.0))
        try:
            return _fetch_once(client, source, pin, dest)
        except _MissingError as error:
            if waited >= mirror.wait_seconds:
                raise MirrorMissingError(
                    f"the mirror release {mirror.tag} does not hold {pin.asset} ({error}); "
                    "data-mirror.yml seeds it from the pins"
                ) from None
            log(f"the mirror release {mirror.tag} does not hold {pin.asset} yet; waiting")
            pause = min(mirror.poll_seconds, mirror.wait_seconds - waited)
            sleep(pause)
            waited += pause
        except (_RetryError, httpx.TransportError) as error:
            last = error
            tries += 1
    raise MirrorError(f"giving up on {source} after {attempts} attempts: {last}") from last


def _fetch_once(client: httpx.Client, source: str, pin: Pin, dest: Path) -> MirrorCopy:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".part", dir=dest.parent)
    tmp = Path(tmp_name)
    try:
        retrieved_at = _utc_now_iso()
        with os.fdopen(fd, "wb") as handle, client.stream("GET", source) as response:
            status = response.status_code
            if status in _MISSING_STATUS:
                raise _MissingError(f"HTTP {status}")
            if status in _RETRYABLE_STATUS:
                raise _RetryError(f"{source} answered HTTP {status}")
            if status != httpx.codes.OK:
                raise MirrorError(f"{source} answered HTTP {status}")
            declared = response.headers.get("Content-Length")
            size = 0
            for chunk in response.iter_bytes(_CHUNK):
                handle.write(chunk)
                size += len(chunk)
        if declared is not None and int(declared) != size:
            raise _RetryError(f"{source}: got {size} bytes, server declared {declared}")
        if not pin.matches(tmp):
            raise PinMismatchError(
                f"{source} does not match the pin of {pin.url} ({pin.form.value} {pin.sha256})"
            )
        sha256 = sha256_file(tmp)
        tmp.chmod(0o644)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    write_sidecar(
        dest,
        {
            "bytes": size,
            "etag": None,
            "last_modified": None,
            "mirror": source,
            "retrieved_at": retrieved_at,
            "sha256": sha256,
            "url": pin.url,
        },
    )
    return MirrorCopy(dest, sha256, size, retrieved_at, source)

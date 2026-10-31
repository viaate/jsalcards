"""Where the live files go: a folder, an S3-style bucket (Cloudflare R2), or a GitHub Pages repo.

Every publisher takes the files of one publish as a whole (:meth:`Publisher.write`)
and can read one back (:meth:`Publisher.read`), so the gate compares against what
the host really holds (spec S5). Every key is checked first (:func:`check_key`):
only ``v1/`` and ``v1-shadow/`` keys of JSON files are ever written (T15b).

* :class:`DirPublisher` writes a folder, atomically per file: tests, dry runs, and
  a Pages deploy step that uploads the folder.
* :class:`R2Publisher` PUTs each file to a bucket with an AWS Signature Version 4
  (:func:`sign`), on the existing httpx dependency; it is checked against AWS's
  published examples (T21). It is the publisher for the later move to Cloudflare.
* :class:`GitHubPublisher` commits the files to a branch of a GitHub repository in
  one commit (the Git Data API), whose Pages workflow then deploys them: the
  owner's host for now (viaate/snowlight-live). The branch moves only by a fast
  forward from the commit read, so a second writer's commit is never overwritten.
  Two workflows write that repository (predict.yml its predictions, live-ingest.yml
  the closings), each its own files: when the other moved the branch first, the
  commit is built again on the new head (its files kept), up to
  :attr:`GitHubPublisher.attempts` times, then the publish fails.

A write can be guarded (:func:`guarded_write`, :class:`WriteGuard`): it is refused
when one file the host holds says so (the hold ``snowlight live blank`` sets). The
GitHub publisher reads that file in the very commit it builds on, so the check and the
fast forward are one step; the folder and the bucket read it just before writing.

None of them logs a file's contents; errors name the key, the HTTP status and GitHub's
reason (a fixed code, the rate-limit counts and reset, the retry wait, the request id), never a
response body.

**When GitHub refuses** (:func:`refusal_of`, :class:`HostRefusal`): every error answer but a
contents 404 (no such file) and the PATCH 422 (another writer moved the branch first) logs one
warning with GitHub's reason, and a rate limit (primary or secondary) sets a time before which
:class:`GitHubPublisher` sends nothing at all: every call raises :class:`HostRefusedError` at
once, whoever makes it (the pass, an edition blank, the alerts, the overrides, predict). The
token's 5,000 calls an hour are shared with everything acting as its user, so a reader that
keeps calling while refused only spends what is left. The first answer after that clears it.

**Fewer calls**: a read at the branch sends ``If-None-Match`` with the ETag it kept (GitHub
answers 304, which costs nothing, while the file is unchanged); a read at a commit sha is
never sent twice; each file written is kept with its git blob sha, which is GitHub's ETag;
and a commit on the head this process made itself needs neither the head commit nor its
guard read (both are known).
"""

import hashlib
import hmac
import logging
import re
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import quote

import httpx

from snowlight import __version__
from snowlight.output import write_bytes_atomic

USER_AGENT: Final = f"snowlight-pipeline/{__version__} (+https://github.com/viaate/jsalcards)"
PREFIXES: Final = ("v1", "v1-shadow", "v1-rehearse")
"""The only top folders a publisher writes: the live files, their shadow copies, and the
switch drill's (E8)."""
_KEY: Final = re.compile(r"(?:v1|v1-shadow|v1-rehearse)(?:/[a-z0-9][a-z0-9._-]*)+\.json")
CONTENT_TYPE: Final = "application/json; charset=utf-8"
DEFAULT_MESSAGE: Final = "Publish the live files"
CACHE_CONTROL: Final = "public, max-age=15, stale-while-revalidate=15"
"""Spec 9.1: the edge and the browser keep a copy at most 15 s, then revalidate."""
EMPTY_SHA256: Final = hashlib.sha256(b"").hexdigest()
TIMEOUT: Final = httpx.Timeout(20.0)
LOG: Final = logging.getLogger(__name__)


class PublishError(RuntimeError):
    """A publish or a read-back failed.

    ``written`` lists the keys a host that writes file by file had already written
    before the failure (in the order given); nothing else is known to be published.
    """

    def __init__(self, message: str, *, written: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.written = written


class KeyRefusedError(PublishError):
    """A key outside ``v1/`` and ``v1-shadow/`` (T15b)."""


class GuardRefusedError(PublishError):
    """The write's guard refused it: nothing was written."""


class MovedError(PublishError):
    """Another writer moved the branch first (not a fast forward): nothing was written."""


# --- what GitHub says when it refuses -------------------------------------------------------

BACKOFF_FIRST: Final = timedelta(seconds=60)
"""A secondary rate limit that names no wait: wait this long, doubling on each repeat ..."""
BACKOFF_MAX: Final = timedelta(minutes=15)
"""... up to this."""
REFUSED_MIN: Final = timedelta(seconds=10)
REFUSED_MAX: Final = timedelta(minutes=61)
"""A refusal's wait is never shorter or longer than these after the answer (a reset an
hour ahead, plus a little skew)."""
RATE_LIMITS: Final = frozenset({"primary_rate_limit", "secondary_rate_limit"})
_PHRASES: Final = (
    ("secondary rate limit", "secondary_rate_limit"),
    ("abuse detection", "secondary_rate_limit"),  # GitHub's older words for it
    ("rate limit", "primary_rate_limit"),
    ("resource not accessible", "no_permission"),
    ("bad credentials", "bad_credentials"),
)
"""Fixed phrases of the body's ``message`` that name the reason (the words are never kept)."""


@dataclass(frozen=True, slots=True)
class HostRate:
    """GitHub's ``x-ratelimit-*`` headers of one answer (counts and the reset only)."""

    limit: int | None
    remaining: int | None
    used: int | None
    resource: str | None
    reset: datetime | None
    """When the window resets, on GitHub's clock."""

    def text(self) -> str:
        """``0 of 5000 left, used 5000, core, resets 17:31:15Z``."""
        parts = [
            f"{_count(self.remaining)} of {_count(self.limit)} left",
            f"used {_count(self.used)}",
            self.resource or "-",
        ]
        if self.reset is not None:
            parts.append(f"resets {clock_text(self.reset)}")
        return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class HostRefusal:
    """Why GitHub refused one call: a fixed code, counts, times and the request id only
    (never the body's words)."""

    status: int
    reason: str
    """``primary_rate_limit``, ``secondary_rate_limit``, ``bad_credentials``,
    ``no_permission``, ``forbidden``, ``not_found``, ``conflict``, ``unprocessable``,
    ``server`` or ``other``."""
    rate: HostRate | None = None
    retry_after: float | None = None
    """``retry-after``, in seconds."""
    request_id: str | None = None
    """``x-github-request-id``."""
    needs: str | None = None
    """``x-accepted-github-permissions`` (``contents=write``, say)."""
    at: datetime | None = None
    """The answer's ``Date``."""
    until: datetime | None = None
    """On the local clock: nothing is sent before it (``None``: no rate limit, no wait)."""
    backoff: timedelta | None = None
    """The wait a secondary limit that named none was given (it doubles on each repeat)."""

    def text(self) -> str:
        """``primary_rate_limit; 0 of 5000 left, used 5000, core, resets 17:31:15Z; request
        40BC:27D4F6``."""
        parts = [self.reason]
        if self.rate is not None and (self.rate.limit is not None or self.rate.reset):
            parts.append(self.rate.text())
        if self.retry_after is not None:
            parts.append(f"retry after {self.retry_after:g} s")
        if self.needs:
            parts.append(f"needs {self.needs}")
        if self.request_id:
            parts.append(f"request {self.request_id}")
        return "; ".join(parts)


class HostRefusedError(PublishError):
    """GitHub refused a call (or a call was not sent while it refuses): the error's text is
    the step, the status and :meth:`HostRefusal.text`."""

    def __init__(self, message: str, refusal: HostRefusal) -> None:
        super().__init__(message)
        self.refusal = refusal

    @property
    def rate_limited(self) -> bool:
        """The host asked to be left alone until :attr:`HostRefusal.until`."""
        return self.refusal.until is not None


def _count(value: int | None) -> str:
    return "-" if value is None else str(value)


def clock_text(moment: datetime) -> str:
    """``17:31:15Z``."""
    return moment.astimezone(UTC).strftime("%H:%M:%SZ")


def _int(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text.strip())
    except ValueError:
        return None


def rate_of(response: httpx.Response) -> HostRate | None:
    """The rate headers of an answer, or ``None`` when it has none."""
    headers = response.headers
    if not any(name in headers for name in ("x-ratelimit-limit", "x-ratelimit-remaining")):
        return None
    reset = _int(headers.get("x-ratelimit-reset"))
    return HostRate(
        limit=_int(headers.get("x-ratelimit-limit")),
        remaining=_int(headers.get("x-ratelimit-remaining")),
        used=_int(headers.get("x-ratelimit-used")),
        resource=_token_text(headers.get("x-ratelimit-resource")),
        reset=None if reset is None else datetime.fromtimestamp(reset, UTC),
    )


def _token_text(text: str | None, size: int = 64) -> str | None:
    """A header value that is a code or an id: letters, digits and ``:=,._-`` only."""
    if text is None:
        return None
    kept = re.sub(r"[^A-Za-z0-9:=,._-]", "", text)[:size]
    return kept or None


def _retry_after(text: str | None, at: datetime | None) -> float | None:
    """``retry-after`` in seconds (it may also be an HTTP date)."""
    if text is None:
        return None
    try:
        return max(0.0, float(text.strip()))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None or at is None:
        return None
    return max(0.0, (moment - at).total_seconds())


def _message(response: httpx.Response) -> str:
    """The body's ``message``, lower case, to match fixed phrases against (never kept)."""
    try:
        body = response.json()
    except ValueError:
        return ""
    message = body.get("message") if isinstance(body, dict) else None
    return message.lower() if isinstance(message, str) else ""


def _phrase(response: httpx.Response) -> str | None:
    """The reason the body's ``message`` names by one of the fixed phrases (the words
    themselves are dropped here)."""
    lowered = _message(response)
    return next((code for phrase, code in _PHRASES if phrase in lowered), None)


def _no_commit(response: httpx.Response) -> bool:
    """A contents 404 that says GitHub does not know the commit asked for (a replica behind
    a fresh head), not that the file is missing in it."""
    return "no commit found" in _message(response)


_FIXED: Final[Mapping[int, str]] = {
    401: "bad_credentials",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "unprocessable",
    429: "secondary_rate_limit",
}


def _reason(status: int, phrase: str | None, rate: HostRate | None, retry: float | None) -> str:
    """The fixed code of an error answer: a 403 or a 429 is a rate limit when no call is
    left, the body says so, or it names a wait (a 429 always is)."""
    forbidden = status == httpx.codes.FORBIDDEN
    if forbidden or status == httpx.codes.TOO_MANY_REQUESTS:
        if rate is not None and rate.remaining == 0:
            return "primary_rate_limit"
        if phrase in RATE_LIMITS:
            return str(phrase)
        if retry is not None:
            return "secondary_rate_limit"
    if phrase == "bad_credentials" or (forbidden and phrase == "no_permission"):
        return phrase
    if status >= httpx.codes.INTERNAL_SERVER_ERROR:
        return "server"
    return _FIXED.get(status, "other")


def refusal_of(
    response: httpx.Response, now: datetime, previous: HostRefusal | None = None
) -> HostRefusal:
    """Why GitHub refused (``response`` is a 4xx or a 5xx), and until when nothing is sent,
    by GitHub's rules: ``Date`` + ``retry-after`` when it names one; else, with no call
    left, the reset + 1 s; else, for a rate limit, 60 s doubling on each repeat
    (``previous``) up to 15 minutes. GitHub's times are moved onto the local clock (``now``,
    when the answer came) by the answer's ``Date``, and the wait is kept within 10 s and
    61 min. Any other answer waits for nothing (``until`` is ``None``)."""
    status = response.status_code
    at = server_time(response)
    rate = rate_of(response)
    retry = _retry_after(response.headers.get("retry-after"), at)
    needs = _token_text(response.headers.get("x-accepted-github-permissions"))
    reason = _reason(status, _phrase(response), rate, retry)
    skew = timedelta(0) if at is None else now - at
    until: datetime | None = None
    backoff: timedelta | None = None
    if reason in RATE_LIMITS:
        if retry is not None:
            until = (at or now) + skew + timedelta(seconds=retry)
        elif rate is not None and rate.remaining == 0 and rate.reset is not None:
            until = rate.reset + timedelta(seconds=1) + skew
        else:
            last = previous.backoff if previous is not None else None
            backoff = BACKOFF_FIRST if last is None else min(last * 2, BACKOFF_MAX)
            until = now + backoff
        until = min(max(until, now + REFUSED_MIN), now + REFUSED_MAX)
        if until.microsecond:  # a whole second, never earlier than GitHub said
            until = until.replace(microsecond=0) + timedelta(seconds=1)
    return HostRefusal(
        status=status,
        reason=reason,
        rate=rate,
        retry_after=retry,
        request_id=_token_text(response.headers.get("x-github-request-id")),
        needs=needs,
        at=at,
        until=until,
        backoff=backoff,
    )


def host_refused_until(host: object, now: datetime) -> datetime | None:
    """Until when ``host`` sends nothing (it refused for a rate limit), or ``None``: a host
    that never refuses so (a folder, a bucket) never waits."""
    refused = getattr(host, "refused_until", None)
    if not callable(refused):
        return None
    found = refused(now)
    return found if isinstance(found, datetime) else None


@dataclass(frozen=True, slots=True)
class WriteGuard:
    """Refuse a write when the file the host holds at ``key`` (``None``: none) ``refuses``."""

    key: str
    refuses: Callable[[bytes | None], bool]


def guarded_write(host: "Publisher", files: Mapping[str, bytes], guard: WriteGuard) -> None:
    """``host.write(files)``, unless ``guard`` refuses (:class:`GuardRefusedError`). A host
    that can check the guard in the write itself (``write_guarded``) does so.

    Raises:
        PublishError: the host failed, or the guard refused.
    """
    own = getattr(host, "write_guarded", None)
    if callable(own):
        own(files, guard)
        return
    if guard.refuses(host.read(guard.key)):
        raise GuardRefusedError(f"{guard.key} refuses the write")
    host.write(files)


def check_key(key: str) -> str:
    """Return ``key`` when a publisher may write it.

    Raises:
        KeyRefusedError: it is not a lower-case ``.json`` path under ``v1/`` or
            ``v1-shadow/`` (no empty, dot-led or ``..`` segment, no leading slash).
    """
    if not _KEY.fullmatch(key) or ".." in key:
        raise KeyRefusedError(f"refused key {key!r}: only v1/ and v1-shadow/ JSON files")
    return key


def server_time(response: httpx.Response) -> datetime | None:
    """The time a response's ``Date`` header gives, or ``None``."""
    text = response.headers.get("date")
    if not text:
        return None
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return moment.astimezone(UTC) if moment.tzinfo is not None else None


class Publisher(Protocol):
    """A host for the live files.

    A host reached over HTTP also keeps ``server_time``: the ``Date`` of its last
    answer, a clock the gate can check the box's own against (G12c).
    """

    def read(self, key: str) -> bytes | None:
        """The file the host holds at ``key``, or ``None`` when there is none."""
        ...

    def write(self, files: Mapping[str, bytes]) -> None:
        """Publish every file (key to bytes), in the order given, or raise
        :class:`PublishError` (with the keys already written)."""
        ...


@dataclass(frozen=True, slots=True)
class DirPublisher:
    """Writes the files under a folder, each atomically."""

    root: Path

    def read(self, key: str) -> bytes | None:
        path = self.root / check_key(key)
        return path.read_bytes() if path.is_file() else None

    def write(self, files: Mapping[str, bytes]) -> None:
        for key in files:
            check_key(key)
        written: list[str] = []
        for key, body in files.items():
            try:
                write_bytes_atomic(self.root / key, body)
            except OSError as error:
                raise PublishError(
                    f"write {key}: {type(error).__name__}", written=tuple(written)
                ) from error
            written.append(key)


# --- AWS Signature Version 4 ----------------------------------------------------------------

_UNRESERVED: Final = "-_.~"


def _encode(text: str, *, keep_slash: bool = False) -> str:
    """URI-encode as SigV4 wants: every byte but ``A-Za-z0-9-_.~`` (and ``/`` in a path)."""
    return quote(text, safe=_UNRESERVED + ("/" if keep_slash else ""))


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.digest(key, text.encode("utf-8"), "sha256")


def signing_key(secret_key: str, day: str, region: str, service: str) -> bytes:
    """The SigV4 signing key for a ``YYYYMMDD`` day, region and service."""
    key = _hmac(f"AWS4{secret_key}".encode(), day)
    key = _hmac(key, region)
    key = _hmac(key, service)
    return _hmac(key, "aws4_request")


@dataclass(frozen=True, slots=True)
class Credentials:
    """An access key pair (never in a repr)."""

    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    region: str = "auto"
    service: str = "s3"


def canonical_request(
    method: str,
    path: str,
    query: Mapping[str, str],
    headers: Mapping[str, str],
    payload_sha256: str,
) -> tuple[str, str]:
    """The SigV4 canonical request, and its signed-headers list.

    ``path`` is the raw (not yet encoded) path; it is encoded once, as S3 wants.
    """
    pairs = sorted((_encode(name), _encode(value)) for name, value in query.items())
    canonical_query = "&".join(f"{name}={value}" for name, value in pairs)
    folded = {name.strip().lower(): " ".join(value.split()) for name, value in headers.items()}
    names = sorted(folded)
    canonical_headers = "".join(f"{name}:{folded[name]}\n" for name in names)
    signed = ";".join(names)
    text = "\n".join(
        [
            method,
            _encode(path, keep_slash=True),
            canonical_query,
            canonical_headers,
            signed,
            payload_sha256,
        ]
    )
    return text, signed


def sign(  # noqa: PLR0913 - the parts of one signed request
    method: str,
    path: str,
    query: Mapping[str, str],
    headers: Mapping[str, str],
    payload_sha256: str,
    *,
    credentials: Credentials,
    now: datetime,
) -> str:
    """The ``Authorization`` header of a SigV4 request.

    ``headers`` must already hold every header to sign, ``x-amz-date`` (``now``)
    included.
    """
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    scope = f"{day}/{credentials.region}/{credentials.service}/aws4_request"
    request, signed = canonical_request(method, path, query, headers, payload_sha256)
    to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            stamp,
            scope,
            hashlib.sha256(request.encode("utf-8")).hexdigest(),
        ]
    )
    key = signing_key(credentials.secret_key, day, credentials.region, credentials.service)
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        f"AWS4-HMAC-SHA256 Credential={credentials.access_key}/{scope}, "
        f"SignedHeaders={signed}, Signature={signature}"
    )


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class R2Publisher:
    """PUTs each file to ``<endpoint>/<bucket>/<key>`` (path style), signed with SigV4.

    ``keys`` checks every key (:func:`check_key` for the public bucket); the private
    state store gives its own (:func:`snowlight.live.state.check_state_key`). The
    endpoint is HTTPS, or plain HTTP on the loopback address only (a local stub).
    """

    endpoint: str
    """``https://<account>.r2.cloudflarestorage.com`` (or any S3-style endpoint)."""
    bucket: str
    credentials: Credentials
    client: httpx.Client
    now: Callable[[], datetime] = _now
    cache_control: str = CACHE_CONTROL
    content_type: str = CONTENT_TYPE
    keys: Callable[[str], str] = check_key
    server_time: datetime | None = None

    def _url(self, key: str) -> httpx.URL:
        if not self.endpoint.startswith(("https://", "http://127.0.0.1:")):
            raise PublishError("the bucket endpoint is not HTTPS")
        return httpx.URL(f"{self.endpoint.rstrip('/')}/{self.bucket}/{key}")

    def headers(self, method: str, key: str, body: bytes) -> dict[str, str]:
        """The exact headers of a request for ``key`` (``Authorization`` included)."""
        url = self._url(key)
        moment = self.now()
        digest = hashlib.sha256(body).hexdigest()
        headers = {
            "host": url.netloc.decode("ascii"),
            "x-amz-content-sha256": digest,
            "x-amz-date": moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"),
        }
        if method == "PUT":
            headers["content-type"] = self.content_type
            headers["cache-control"] = self.cache_control
        headers["authorization"] = sign(
            method,
            f"/{self.bucket}/{key}",
            {},
            headers,
            digest,
            credentials=self.credentials,
            now=moment,
        )
        return headers

    def read(self, key: str) -> bytes | None:
        self.keys(key)
        response = self._send("GET", key, b"")
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        if response.status_code != httpx.codes.OK:
            raise PublishError(f"read {key}: HTTP {response.status_code}")
        return response.content

    def write(self, files: Mapping[str, bytes]) -> None:
        for key in files:
            self.keys(key)
        written: list[str] = []
        for key, body in files.items():
            try:
                response = self._send("PUT", key, body)
            except PublishError as error:
                raise PublishError(str(error), written=tuple(written)) from error
            if response.status_code != httpx.codes.OK:
                raise PublishError(
                    f"put {key}: HTTP {response.status_code}", written=tuple(written)
                )
            written.append(key)

    def _send(self, method: str, key: str, body: bytes) -> httpx.Response:
        headers = self.headers(method, key, body)
        headers.pop("host")
        try:
            response = self.client.request(
                method, self._url(key), headers=headers, content=body or None, timeout=TIMEOUT
            )
        except httpx.HTTPError as error:
            raise PublishError(f"{method.lower()} {key}: {type(error).__name__}") from error
        self.server_time = server_time(response) or self.server_time
        return response


# --- GitHub (Pages of a separate repository) --------------------------------------------------

RAW: Final = "application/vnd.github.raw+json"
SHAS_KEPT: Final = 16
"""How many commit shas the reads at a sha are kept for (each never changes)."""
_SHA: Final = re.compile(r"[0-9a-f]{40}")


def blob_etag(body: bytes) -> str:
    """GitHub's ETag of a file's raw contents: its git blob sha, quoted."""
    header = b"blob %d\0" % len(body)
    return f'"{hashlib.sha1(header + body, usedforsecurity=False).hexdigest()}"'


@dataclass(frozen=True, slots=True)
class _Own:
    """The branch head this process made last: its tree, and the guard files it holds."""

    head: str
    tree: str
    known: Mapping[str, bytes | None]


@dataclass(slots=True)
class GitHubPublisher:
    """Commits the files of a publish to one branch, in one commit, by a fast forward.

    The repository's own Pages workflow deploys each push (spec 9.1 H2; S8-A measured
    push to visible at about 20-40 s). ``token`` needs ``contents: write`` on that
    repository only. While GitHub refuses for a rate limit nothing is sent (see the module).
    """

    repository: str
    """``owner/name``."""
    token: str = field(repr=False)
    client: httpx.Client
    branch: str = "main"
    api: str = "https://api.github.com"
    message: str = DEFAULT_MESSAGE
    """The next write's commit message; every write goes back to :attr:`default_message`
    after it, so a pass's message never sticks to a later write (an ``alerts.json`` commit,
    say)."""
    default_message: str = DEFAULT_MESSAGE
    """The message of a write nothing named (a live-read process names its run in it)."""
    server_time: datetime | None = None
    attempts: int = 3
    """How many times a commit is built when another writer keeps moving the branch."""
    now: Callable[[], datetime] = _now
    """The local clock (a refusal's wait is measured on it)."""
    rate: HostRate | None = None
    """The rate headers of the last answer that had them."""
    refusal: HostRefusal | None = None
    """The last refusal, until an answer clears it."""
    _refused_since: datetime | None = field(default=None, init=False, repr=False)
    _kept: dict[tuple[str, str], tuple[str, bytes]] = field(
        default_factory=dict, init=False, repr=False
    )
    _at_sha: "OrderedDict[str, dict[str, bytes | None]]" = field(
        default_factory=OrderedDict, init=False, repr=False
    )
    _own: _Own | None = field(default=None, init=False, repr=False)

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        return {
            "Accept": accept,
            "Authorization": f"Bearer {self.token}",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def refused_until(self, now: datetime) -> datetime | None:
        """Until when nothing is sent (GitHub refused for a rate limit), or ``None``."""
        refusal = self.refusal
        if refusal is None or refusal.until is None or now >= refusal.until:
            return None
        return refusal.until

    def _call(  # noqa: PLR0913 - one request and what it is for
        self,
        method: str,
        path: str,
        *,
        what: str,
        body: object = None,
        accept: str | None = None,
        etag: str | None = None,
        expected: tuple[int, ...] = (),
    ) -> httpx.Response:
        """Send one request, unless GitHub refused until later (:class:`HostRefusedError`
        at once). An error answer outside ``expected`` logs GitHub's reason as a warning and
        is kept in :attr:`refusal`; the caller raises."""
        held = self.refused_until(self.now())
        if held is not None and self.refusal is not None:
            raise HostRefusedError(
                f"{what}: not sent, host refused until {clock_text(held)} ({self.refusal.reason})",
                self.refusal,
            )
        url = f"{self.api.rstrip('/')}/repos/{self.repository}/{path}"
        headers = self._headers(accept or "application/vnd.github+json")
        if etag is not None:
            headers["If-None-Match"] = etag
        try:
            response = self.client.request(method, url, headers=headers, json=body, timeout=TIMEOUT)
        except httpx.HTTPError as error:
            where = path.split("?", maxsplit=1)[0]
            raise PublishError(f"{method} {where}: {type(error).__name__}") from error
        # GitHub's times are moved onto the local clock as of the answer (its Date is no
        # older than that): a slow answer never shortens the wait it names
        now = self.now()
        self.server_time = server_time(response) or self.server_time
        rate = rate_of(response)
        if rate is not None:
            self.rate = rate
        status = response.status_code
        if status >= httpx.codes.BAD_REQUEST and status not in expected:
            found = refusal_of(response, now, self.refusal)
            LOG.warning("live host refused %s: HTTP %d (%s)", what, status, found.text())
            if self.refusal is None:
                self._refused_since = now
            self.refusal = found
            return response
        if status >= httpx.codes.BAD_REQUEST:
            LOG.debug("live host %s: HTTP %d (%s)", what, status, refusal_of(response, now).text())
        cleared = self.refusal
        if cleared is not None:
            since = self._refused_since or now
            if cleared.until is not None:
                waited = round((now - since).total_seconds())
                LOG.info("live host answers again after %d s", waited)
            else:  # an error answer that named no wait (a plain 403, a 5xx)
                LOG.info("live host answers (after HTTP %d, %s)", cleared.status, cleared.reason)
            self.refusal, self._refused_since = None, None
        return response

    def _error(self, what: str, response: httpx.Response) -> HostRefusedError:
        refusal = self.refusal
        if refusal is None or refusal.status != response.status_code:
            refusal = refusal_of(response, self.now())
        return HostRefusedError(f"{what}: HTTP {response.status_code} ({refusal.text()})", refusal)

    def _json(self, response: httpx.Response, what: str) -> dict[str, object]:
        if not response.is_success:
            raise self._error(what, response)
        try:
            value = response.json()
        except ValueError as error:
            raise PublishError(f"{what}: not JSON") from error
        if not isinstance(value, dict):
            raise PublishError(f"{what}: not an object")
        return value

    @staticmethod
    def _sha(value: object, what: str) -> str:
        if not isinstance(value, str) or not _SHA.fullmatch(value):
            raise PublishError(f"{what}: no commit or tree id")
        return value

    def read(self, key: str) -> bytes | None:
        return self._read_at(key, self.branch)

    def _read_at(self, key: str, ref: str) -> bytes | None:
        """The file at ``ref``: at a commit sha it is read once (it never changes); at the
        branch it is asked with the ETag kept, and a 304 gives the bytes kept."""
        check_key(key)
        what = f"read {key}"
        if _SHA.fullmatch(ref):
            at = self._at_sha.get(ref)
            if at is not None and key in at:
                self._at_sha.move_to_end(ref)
                return at[key]
        kept = None if _SHA.fullmatch(ref) else self._kept.get((key, ref))
        response = self._call(
            "GET",
            f"contents/{quote(key)}?ref={quote(ref)}",
            what=what,
            accept=RAW,
            etag=None if kept is None else kept[0],
            expected=(httpx.codes.NOT_FOUND,),
        )
        status = response.status_code
        if status == httpx.codes.NOT_MODIFIED and kept is not None:
            return kept[1]
        if status == httpx.codes.NOT_FOUND:
            data = None
        elif status == httpx.codes.OK:
            data = response.content
        elif status >= httpx.codes.BAD_REQUEST:
            raise self._error(what, response)
        else:
            raise PublishError(f"{what}: HTTP {status}")
        if _SHA.fullmatch(ref):
            self._keep_at(key, ref, data, response)
        else:
            etag = response.headers.get("etag")
            if data is not None and etag:
                self._kept[(key, ref)] = (etag, data)
            else:
                self._kept.pop((key, ref), None)
        return data

    def _keep_at(self, key: str, sha: str, data: bytes | None, response: httpx.Response) -> None:
        """Keep the file read at commit ``sha`` (it never changes there), unless GitHub did
        not know that commit yet: then nothing is known of the file, so the next read at it
        asks again (and a guard read so is not carried on to the heads made on it)."""
        if data is None and _no_commit(response):
            LOG.info("read %s at %s: GitHub does not know the commit yet", key, sha[:12])
            return
        self._at_sha.setdefault(sha, {})[key] = data
        self._at_sha.move_to_end(sha)
        while len(self._at_sha) > SHAS_KEPT:
            self._at_sha.popitem(last=False)

    def write(self, files: Mapping[str, bytes]) -> None:
        self._commit(files, None)

    def write_guarded(self, files: Mapping[str, bytes], guard: WriteGuard) -> None:
        """:meth:`write`, refused when ``guard``'s file in the commit it builds on refuses
        (a writer that moved the branch after that read fails the fast forward)."""
        check_key(guard.key)
        self._commit(files, guard)

    def _commit(self, files: Mapping[str, bytes], guard: WriteGuard | None) -> None:
        try:
            for key in files:
                check_key(key)
            if not files:
                return
            for attempt in range(1, max(1, self.attempts) + 1):
                try:
                    self._commit_once(files, guard)
                except MovedError:
                    if attempt >= self.attempts:
                        raise
                else:
                    return
        finally:
            self.message = self.default_message

    def _base(self, head: str, guard: WriteGuard | None) -> tuple[str, dict[str, bytes | None]]:
        """The tree of ``head`` and the guard files known there, the guard's checked. On the
        head this process made last both are known (no other writer moved the branch); on
        any other, the guard is read in that commit and the commit is read."""
        own = self._own if self._own is not None and self._own.head == head else None
        known = {} if own is None else dict(own.known)
        if guard is not None:
            found = known[guard.key] if guard.key in known else self._read_at(guard.key, head)
            if guard.refuses(found):
                raise GuardRefusedError(f"{guard.key} refuses the write")
            if guard.key not in known and self._knows(guard.key, head):
                # carried to the heads this process makes on it only when GitHub answered
                # for that commit (a 404 from a replica that did not know it is read again)
                known[guard.key] = found
        if own is not None:
            return own.tree, known
        commit = self._json(
            self._call("GET", f"git/commits/{head}", what="read commit"), "read commit"
        )
        tree = commit.get("tree")
        return self._sha(tree.get("sha") if isinstance(tree, dict) else None, "read commit"), known

    def _knows(self, key: str, sha: str) -> bool:
        """Whether the file at ``key`` in commit ``sha`` was read (it is kept)."""
        return key in self._at_sha.get(sha, {})

    def _commit_once(self, files: Mapping[str, bytes], guard: WriteGuard | None) -> None:
        """One commit on the branch's head, with the guard read in that very commit."""
        branch = quote(self.branch)
        ref = self._json(
            self._call("GET", f"git/ref/heads/{branch}", what="read branch"), "read branch"
        )
        target = ref.get("object")
        head = self._sha(target.get("sha") if isinstance(target, dict) else None, "read branch")
        base, known = self._base(head, guard)
        try:
            entries = [
                {"path": key, "mode": "100644", "type": "blob", "content": body.decode("utf-8")}
                for key, body in sorted(files.items())
            ]
        except UnicodeDecodeError as error:
            raise PublishError("a live file is not UTF-8 text") from error
        made = self._json(
            self._call(
                "POST",
                "git/trees",
                what="write tree",
                body={"base_tree": base, "tree": entries},
            ),
            "write tree",
        )
        new_tree = self._sha(made.get("sha"), "write tree")
        if new_tree == base:
            self._own = _Own(head, base, known)
            return  # the branch already holds these files
        created = self._json(
            self._call(
                "POST",
                "git/commits",
                what="write commit",
                body={"message": self.message, "tree": new_tree, "parents": [head]},
            ),
            "write commit",
        )
        new_head = self._sha(created.get("sha"), "write commit")
        moved = self._call(
            "PATCH",
            f"git/refs/heads/{branch}",
            what="move branch",
            body={"sha": new_head, "force": False},
            expected=(httpx.codes.UNPROCESSABLE_ENTITY,),
        )
        if moved.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
            raise MovedError("move branch: another writer moved it first (not a fast forward)")
        self._json(moved, "move branch")
        known.update({key: files[key] for key in files if key in known})
        self._own = _Own(new_head, new_tree, known)
        for key, body in files.items():
            self._kept[(key, self.branch)] = (blob_etag(body), body)

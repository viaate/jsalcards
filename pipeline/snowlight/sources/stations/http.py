"""Polite HTTP for station pages: robots.txt, rate limits, conditional requests, retries.

Every live request to a station goes through :class:`PoliteClient`, which

* sends a User-Agent that names this repository (:data:`USER_AGENT`), whose first
  word, ``snowlight-pipeline``, is the product token robots.txt rules are matched on;
* reads each origin's robots.txt first (cached for at most 24 hours, as RFC 9309
  allows) and records its verdict for every URL requested, redirect hops included
  (:class:`RobotsVerdict`, kept with the read). A disallowed URL is still read: the
  project owner decided on 2026-09-26 to read closings pages and data files even
  where robots.txt disallows them, so the verdict is a record, not a gate;
* waits between requests to one host: at least the caller's interval, and at
  least the host's ``Crawl-delay`` when its robots.txt sets one (a pacing floor
  whether or not the file allows the URL);
* makes conditional requests: the ETag and Last-Modified of the last full answer
  are sent back, and a ``304 Not Modified`` returns the stored body (checked
  against its SHA-256) instead of downloading it again;
* reads a service that answers only POST (``Station.data_post``: a read-only alert
  service a station's page calls by script) by posting the page script's own JSON
  body, with no conditional request and no redirect followed;
* reads robots.txt itself, and wherever it redirects (``/robots.txt/Default.aspx``
  on SharpSchool sites), without consulting robots.txt for those requests;
* times out (10 s to connect, 30 s to read) and retries transport errors, ``408``,
  ``425``, ``429`` and ``5xx`` answers with exponential backoff, honouring a
  ``Retry-After`` up to five minutes (a longer one ends the attempt);
* follows at most five redirects, only to http(s) URLs, and never downgrades
  from https to http;
* never works around a refusal: a ``403`` (or any other answer that is not a
  success, a redirect or a retryable status) ends the attempt, and a
  ``Retry-After`` longer than five minutes ends it too; a host that answered ``403``
  to a page or file, or ``401`` or ``403`` to its robots.txt (but for Amazon S3's
  ``AccessDenied`` for a file its bucket does not hold), has refused the project,
  so nothing more is asked of it for the rest of the run (:meth:`PoliteClient.refused`:
  another address on the same host, a category page beside a list that answered 403,
  and the page whose robots.txt was refused are not tried);
* reads at most 10 MiB of any body.

TLS is always verified, against ``SSL_CERT_FILE`` when it is set.
"""

import hashlib
import json
import os
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from snowlight import __version__
from snowlight.output import write_bytes_atomic
from snowlight.sources.stations.robots import Robots, RobotsState

USER_AGENT = f"snowlight-pipeline/{__version__} (+https://github.com/viaate/jsalcards)"
ROBOTS_TTL = timedelta(hours=24)
DEFAULT_HOST_INTERVAL = 5.0
MAX_BODY = 10 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_RETRY_AFTER = 300.0
MAX_BACKOFF = 60.0
_RETRYABLE = frozenset({408, 425, 429, 500, 502, 503, 504})
_REDIRECTS = frozenset({301, 302, 303, 307, 308})

type Clock = Callable[[], datetime]
type Monotonic = Callable[[], float]
type Sleep = Callable[[float], None]


class FetchError(RuntimeError):
    """A URL could not be read; ``status`` is the last HTTP status, if any."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class RobotsVerdict:
    """What a site's robots.txt says about one URL for the project's User-Agent.

    Recorded with every read; the project owner's decision of 2026-09-26 is to read
    closings pages and data files even where robots.txt disallows them.
    """

    url: str
    state: RobotsState
    allowed: bool
    rule: str
    crawl_delay: float | None


def system_clock() -> datetime:
    """Return the current time in UTC, in whole seconds (as the internal records keep it)."""
    return datetime.now(UTC).replace(microsecond=0)


def iso_utc(moment: datetime) -> str:
    """Format an aware datetime as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_client() -> httpx.Client:
    """Return an HTTP client that verifies TLS and does not follow redirects itself."""
    bundle = os.environ.get("SSL_CERT_FILE")
    verify: ssl.SSLContext | bool = ssl.create_default_context(cafile=bundle) if bundle else True
    return httpx.Client(
        verify=verify,
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
    )


@dataclass(frozen=True, slots=True)
class Fetched:
    """One successful read of a URL."""

    url: str
    final_url: str
    status: int
    body: bytes
    sha256: str
    fetched_at: datetime
    not_modified: bool
    content_type: str | None
    etag: str | None
    last_modified: str | None
    robots: tuple[RobotsVerdict, ...] = ()
    """robots.txt's verdict on each URL requested (the URL, then each redirect hop)."""


@dataclass(frozen=True, slots=True)
class _Stored:
    etag: str | None
    last_modified: str | None
    sha256: str
    content_type: str | None
    final_url: str


class ConditionalStore:
    """The last full body of each URL, with the validators to ask for it conditionally."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _paths(self, url: str) -> tuple[Path, Path]:
        host = urlsplit(url).hostname or "unknown"
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        base = self.root / host / key
        return base.with_suffix(".body"), base.with_suffix(".json")

    def load(self, url: str) -> tuple[_Stored, bytes] | None:
        """Return the stored validators and body for ``url``, if intact."""
        body_path, meta_path = self._paths(url)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = body_path.read_bytes()
        except (OSError, ValueError):
            return None
        if not isinstance(meta, dict) or meta.get("url") != url:
            return None
        sha = hashlib.sha256(body).hexdigest()
        if meta.get("sha256") != sha:
            return None
        stored = _Stored(
            etag=meta.get("etag") if isinstance(meta.get("etag"), str) else None,
            last_modified=meta.get("last_modified")
            if isinstance(meta.get("last_modified"), str)
            else None,
            sha256=sha,
            content_type=meta.get("content_type")
            if isinstance(meta.get("content_type"), str)
            else None,
            final_url=str(meta.get("final_url") or url),
        )
        return stored, body

    def save(self, fetched: Fetched) -> None:
        """Keep ``fetched`` as the latest full body of its URL."""
        body_path, meta_path = self._paths(fetched.url)
        write_bytes_atomic(body_path, fetched.body)
        meta = {
            "content_type": fetched.content_type,
            "etag": fetched.etag,
            "fetched_at": iso_utc(fetched.fetched_at),
            "final_url": fetched.final_url,
            "last_modified": fetched.last_modified,
            "sha256": fetched.sha256,
            "url": fetched.url,
        }
        text = json.dumps(meta, indent=2, sort_keys=True) + "\n"
        write_bytes_atomic(meta_path, text.encode("utf-8"))


def _retry_after(response: httpx.Response, now: datetime) -> float | None:
    value = response.headers.get("Retry-After", "").strip()
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - now).total_seconds(), 0.0)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


@dataclass(frozen=True, slots=True)
class Timing:
    """The clocks and the sleep a client uses (replaced in tests)."""

    clock: Clock = system_clock
    monotonic: Monotonic = time.monotonic
    sleep: Sleep = time.sleep


class PoliteClient:
    """Reads station URLs within their robots.txt, their rate limits and ours."""

    def __init__(
        self,
        client: httpx.Client,
        store: ConditionalStore,
        *,
        host_interval: float = DEFAULT_HOST_INTERVAL,
        attempts: int = 4,
        timing: Timing | None = None,
    ) -> None:
        self.client = client
        self.store = store
        self.user_agent = USER_AGENT
        self.host_interval = host_interval
        self.attempts = attempts
        timing = timing or Timing()
        self._clock = timing.clock
        self._monotonic = timing.monotonic
        self._sleep = timing.sleep
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, tuple[datetime, Robots]] = {}
        self._refused: dict[str, str] = {}

    def refused(self, url: str) -> str | None:
        """The address on ``url``'s host that answered 403 earlier in this run (its robots.txt
        answering 401 or 403 too), or None."""
        return self._refused.get((urlsplit(url).hostname or "").lower())

    def _not_refused(self, target: str) -> None:
        earlier = self.refused(target)
        if earlier is not None:
            raise FetchError(
                f"{target}: not requested: its host answered HTTP 403 to {earlier} "
                "earlier in this run (a refusal is not worked around)",
                httpx.codes.FORBIDDEN,
            )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.client.close()

    # Rate limiting -----------------------------------------------------------------

    def _pace(self, url: str, interval: float, *, robots: bool = False) -> None:
        host = (urlsplit(url).hostname or "").lower()
        # A request made to read robots.txt (the file, or wherever it redirects:
        # SharpSchool sites send /robots.txt on to /robots.txt/Default.aspx) is paced
        # without consulting robots.txt, which is what it is reading.
        skip = robots or _is_robots(url)
        delay = None if skip else self.robots_for(url).crawl_delay(self.user_agent)
        wait_for = max(interval, self.host_interval, delay or 0.0)
        last = self._last_request.get(host)
        if last is not None:
            remaining = last + wait_for - self._monotonic()
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[host] = self._monotonic()

    # robots.txt ----------------------------------------------------------------------

    def robots_for(self, url: str) -> Robots:
        """Return the robots.txt that governs ``url``, reading it if needed."""
        origin = _origin(url)
        cached = self._robots.get(origin)
        now = self._clock()
        if cached is not None and now - cached[0] < ROBOTS_TTL:
            return cached[1]
        robots = self._read_robots(origin)
        self._robots[origin] = (now, robots)
        return robots

    def _read_robots(self, origin: str) -> Robots:
        target = f"{origin}/robots.txt"
        for _hop in range(MAX_REDIRECTS + 1):
            try:
                response = self._request(target, {}, interval=0.0, robots=True)
            except FetchError:
                # Retries exhausted on a 5xx, a 408/425/429 or a network failure: the
                # file is unreachable, so nothing on the site may be fetched.
                return Robots.for_status(503)
            if response.status_code in _REDIRECTS and "location" in response.headers:
                target = urljoin(target, response.headers["location"])
                if urlsplit(target).scheme not in {"http", "https"}:
                    return Robots.for_status(503)
                continue
            if 200 <= response.status_code < 300:  # noqa: PLR2004
                return Robots.from_bytes(response.content)
            if response.status_code in {
                httpx.codes.UNAUTHORIZED,
                httpx.codes.FORBIDDEN,
            } and not _s3_missing_key(response):
                # A host that refuses its robots.txt to the project's User-Agent has refused
                # the project: nothing more is asked of it in the run.
                self._refused[(urlsplit(target).hostname or "").lower()] = target
            return Robots.for_status(response.status_code)
        return Robots.for_status(404)  # RFC 9309 2.3.1.2: too many redirects is unavailable

    def check_robots(self, url: str) -> tuple[bool, str]:
        """Return whether ``url``'s robots.txt allows it for our User-Agent, and the rule."""
        return self.robots_for(url).decide(url, self.user_agent)

    def robots_verdict(self, url: str) -> RobotsVerdict:
        """Return robots.txt's verdict on ``url`` (reading the file if needed)."""
        robots = self.robots_for(url)
        allowed, rule = robots.decide(url, self.user_agent)
        return RobotsVerdict(
            url=url,
            state=robots.state,
            allowed=allowed,
            rule=rule,
            crawl_delay=robots.crawl_delay(self.user_agent),
        )

    # Fetching ------------------------------------------------------------------------

    def _request(
        self,
        url: str,
        headers: dict[str, str],
        *,
        interval: float,
        post: bytes | None = None,
        robots: bool = False,
    ) -> httpx.Response:
        last_error: str | None = None
        last_status: int | None = None
        for attempt in range(self.attempts):
            self._pace(url, interval, robots=robots)
            wait: float | None = None
            try:
                response = self._send(url, headers, post)
            except (httpx.TransportError, httpx.DecodingError) as error:
                last_error = f"{type(error).__name__}: {error}"
            else:
                if response.status_code not in _RETRYABLE:
                    return response
                last_status = response.status_code
                last_error = f"HTTP {response.status_code}"
                wait = _retry_after(response, self._clock())
                if wait is not None and wait > MAX_RETRY_AFTER:
                    raise FetchError(f"{url}: asked to wait {wait:.0f} s", last_status)
            if attempt + 1 < self.attempts:
                self._sleep(wait if wait is not None else min(2.0 ** (attempt + 1), MAX_BACKOFF))
        raise FetchError(f"{url}: {last_error} after {self.attempts} attempts", last_status)

    def _send(self, url: str, headers: dict[str, str], post: bytes | None = None) -> httpx.Response:
        method = "GET" if post is None else "POST"
        if post is not None:
            headers = {**headers, "Content-Type": "application/json; charset=utf-8"}
        with self.client.stream(method, url, headers=headers, content=post) as response:
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BODY:
                    raise FetchError(f"{url}: body larger than {MAX_BODY} bytes")
                chunks.append(chunk)
            # The chunks are already decoded, so the rebuilt response must not claim
            # a content encoding (httpx would try to decode them a second time).
            kept = [
                (name, value)
                for name, value in response.headers.multi_items()
                if name.lower() not in {"content-encoding", "content-length", "transfer-encoding"}
            ]
            return httpx.Response(
                response.status_code,
                headers=kept,
                content=b"".join(chunks),
                request=response.request,
            )

    def fetch(self, url: str, *, interval: float = 0.0, post: bytes | None = None) -> Fetched:
        """Read ``url`` politely and return its body.

        robots.txt is read for every URL requested and its verdict returned with the
        body (:attr:`Fetched.robots`); a URL it disallows is read all the same (the
        project owner's decision of 2026-09-26), within its ``Crawl-delay``.

        With ``post`` (a JSON body), the URL is a read-only service that answers only
        POST (``Station.data_post``): the body is posted as ``application/json``, with
        no conditional request and no redirect followed; the answer is still kept in
        the store (for fixtures), never sent back as a validator.

        Raises:
            FetchError: the URL could not be read (``status`` says how it ended).
        """
        stored = self.store.load(url) if post is None else None
        headers: dict[str, str] = {}
        if stored is not None:
            if stored[0].etag:
                headers["If-None-Match"] = stored[0].etag
            if stored[0].last_modified:
                headers["If-Modified-Since"] = stored[0].last_modified
        target = url
        verdicts: list[RobotsVerdict] = []
        for _hop in range(MAX_REDIRECTS + 1):
            self._not_refused(target)
            verdicts.append(self.robots_verdict(target))
            self._not_refused(target)  # its robots.txt may have just answered 401 or 403
            response = self._request(
                target, headers if target == url else {}, interval=interval, post=post
            )
            status = response.status_code
            if status in _REDIRECTS and post is not None:
                raise FetchError(f"{target}: a POST answered with a redirect", status)
            if status in _REDIRECTS and "location" in response.headers:
                following = urljoin(target, response.headers["location"])
                scheme = urlsplit(following).scheme
                if scheme not in {"http", "https"} or (
                    urlsplit(target).scheme == "https" and scheme == "http"
                ):
                    raise FetchError(f"{target}: refused redirect to {following}", status)
                target = following
                continue
            fetched_at = self._clock()
            if status == httpx.codes.NOT_MODIFIED and stored is not None and target == url:
                meta, body = stored
                return Fetched(
                    url=url,
                    final_url=meta.final_url,
                    status=status,
                    body=body,
                    sha256=meta.sha256,
                    fetched_at=fetched_at,
                    not_modified=True,
                    content_type=meta.content_type,
                    etag=response.headers.get("ETag") or meta.etag,
                    last_modified=response.headers.get("Last-Modified") or meta.last_modified,
                    robots=tuple(verdicts),
                )
            if status == httpx.codes.FORBIDDEN:
                self._refused[(urlsplit(target).hostname or "").lower()] = target
            if status != httpx.codes.OK:
                raise FetchError(f"{target}: HTTP {status}", status)
            body = response.content
            fetched = Fetched(
                url=url,
                final_url=target,
                status=status,
                body=body,
                sha256=hashlib.sha256(body).hexdigest(),
                fetched_at=fetched_at,
                not_modified=False,
                content_type=response.headers.get("Content-Type"),
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
                robots=tuple(verdicts),
            )
            self.store.save(fetched)
            return fetched
        raise FetchError(f"{url}: more than {MAX_REDIRECTS} redirects")


_S3_DENIED = b"<Code>AccessDenied</Code>"


def _s3_missing_key(response: httpx.Response) -> bool:
    """Whether a 403 is Amazon S3's answer for a key its bucket does not hold.

    S3 answers ``AccessDenied`` (403) for a key that does not exist when the bucket does
    not let the public list it, so a bucket with no robots.txt answers 403 to it while
    serving its files (KULR's ticker bucket, read 2026-09-27): that is no refusal of the
    project, and robots.txt is unavailable (RFC 9309: unrestricted)."""
    return response.status_code == httpx.codes.FORBIDDEN and _S3_DENIED in response.content[:512]


def _is_robots(url: str) -> bool:
    return urlsplit(url).path == "/robots.txt"

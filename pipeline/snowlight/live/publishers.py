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

None of them logs a file's contents; errors name the key and the HTTP status only.
"""

import hashlib
import hmac
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import quote

import httpx

from snowlight import __version__
from snowlight.output import write_bytes_atomic

USER_AGENT: Final = f"snowlight-pipeline/{__version__} (+https://github.com/viaate/jsalcards)"
PREFIXES: Final = ("v1", "v1-shadow")
"""The only top folders a publisher writes: the live files and their shadow copies."""
_KEY: Final = re.compile(r"(?:v1|v1-shadow)(?:/[a-z0-9][a-z0-9._-]*)+\.json")
CONTENT_TYPE: Final = "application/json; charset=utf-8"
CACHE_CONTROL: Final = "public, max-age=15, stale-while-revalidate=15"
"""Spec 9.1: the edge and the browser keep a copy at most 15 s, then revalidate."""
EMPTY_SHA256: Final = hashlib.sha256(b"").hexdigest()
TIMEOUT: Final = httpx.Timeout(20.0)


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


@dataclass(slots=True)
class GitHubPublisher:
    """Commits the files of a publish to one branch, in one commit, by a fast forward.

    The repository's own Pages workflow deploys each push (spec 9.1 H2; S8-A measured
    push to visible at about 20-40 s). ``token`` needs ``contents: write`` on that
    repository only.
    """

    repository: str
    """``owner/name``."""
    token: str = field(repr=False)
    client: httpx.Client
    branch: str = "main"
    api: str = "https://api.github.com"
    message: str = "Publish the live files"
    server_time: datetime | None = None
    attempts: int = 3
    """How many times a commit is built when another writer keeps moving the branch."""

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        return {
            "Accept": accept,
            "Authorization": f"Bearer {self.token}",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _call(
        self, method: str, path: str, *, body: object = None, accept: str | None = None
    ) -> httpx.Response:
        url = f"{self.api.rstrip('/')}/repos/{self.repository}/{path}"
        try:
            response = self.client.request(
                method,
                url,
                headers=self._headers(accept or "application/vnd.github+json"),
                json=body,
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as error:
            where = path.split("?", maxsplit=1)[0]
            raise PublishError(f"{method} {where}: {type(error).__name__}") from error
        self.server_time = server_time(response) or self.server_time
        return response

    def _json(self, response: httpx.Response, what: str) -> dict[str, object]:
        if not response.is_success:
            raise PublishError(f"{what}: HTTP {response.status_code}")
        try:
            value = response.json()
        except ValueError as error:
            raise PublishError(f"{what}: not JSON") from error
        if not isinstance(value, dict):
            raise PublishError(f"{what}: not an object")
        return value

    @staticmethod
    def _sha(value: object, what: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
            raise PublishError(f"{what}: no commit or tree id")
        return value

    def read(self, key: str) -> bytes | None:
        return self._read_at(key, self.branch)

    def _read_at(self, key: str, ref: str) -> bytes | None:
        check_key(key)
        response = self._call(
            "GET",
            f"contents/{quote(key)}?ref={quote(ref)}",
            accept="application/vnd.github.raw+json",
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        if response.status_code != httpx.codes.OK:
            raise PublishError(f"read {key}: HTTP {response.status_code}")
        return response.content

    def write(self, files: Mapping[str, bytes]) -> None:
        self._commit(files, None)

    def write_guarded(self, files: Mapping[str, bytes], guard: WriteGuard) -> None:
        """:meth:`write`, refused when ``guard``'s file in the commit it builds on refuses
        (a writer that moved the branch after that read fails the fast forward)."""
        check_key(guard.key)
        self._commit(files, guard)

    def _commit(self, files: Mapping[str, bytes], guard: WriteGuard | None) -> None:
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

    def _commit_once(self, files: Mapping[str, bytes], guard: WriteGuard | None) -> None:
        """One commit on the branch's head, with the guard read in that very commit."""
        ref = self._json(self._call("GET", f"git/ref/heads/{quote(self.branch)}"), "read branch")
        target = ref.get("object")
        head = self._sha(target.get("sha") if isinstance(target, dict) else None, "read branch")
        if guard is not None and guard.refuses(self._read_at(guard.key, head)):
            raise GuardRefusedError(f"{guard.key} refuses the write")
        commit = self._json(self._call("GET", f"git/commits/{head}"), "read commit")
        tree = commit.get("tree")
        base = self._sha(tree.get("sha") if isinstance(tree, dict) else None, "read commit")
        try:
            entries = [
                {"path": key, "mode": "100644", "type": "blob", "content": body.decode("utf-8")}
                for key, body in sorted(files.items())
            ]
        except UnicodeDecodeError as error:
            raise PublishError("a live file is not UTF-8 text") from error
        made = self._json(
            self._call("POST", "git/trees", body={"base_tree": base, "tree": entries}), "write tree"
        )
        new_tree = self._sha(made.get("sha"), "write tree")
        if new_tree == base:
            return  # the branch already holds these files
        created = self._json(
            self._call(
                "POST",
                "git/commits",
                body={"message": self.message, "tree": new_tree, "parents": [head]},
            ),
            "write commit",
        )
        new_head = self._sha(created.get("sha"), "write commit")
        moved = self._call(
            "PATCH",
            f"git/refs/heads/{quote(self.branch)}",
            body={"sha": new_head, "force": False},
        )
        if moved.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
            raise MovedError("move branch: another writer moved it first (not a fast forward)")
        self._json(moved, "move branch")

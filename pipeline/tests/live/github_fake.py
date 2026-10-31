"""A SYNTHETIC GitHub repository for the live host's tests (grown from ``test_publishers.Repo``).

It answers the Git Data API and the Contents API as GitHub does for what the live host uses:
contents reads honour ``?ref=`` (the branch or a commit sha), carry the file's git blob sha
as the quoted ETag and answer ``If-None-Match`` with 304; every answer carries the rate
headers, a ``Date`` from the test's clock and a request id. :meth:`GitHubFake.refuse` refuses
every request in a window, by that clock, as GitHub's primary limit, its secondary limit or a
plain 403 does; :meth:`GitHubFake.commit_other` moves the head as predict.yml does. Every
request is logged with its time and whether it counted against the primary limit (all but a
304). Every file and message is SYNTHETIC.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import format_datetime
from typing import Literal

import httpx

from snowlight.live.publishers import GitHubPublisher

REPOSITORY = "viaate/snowlight-synthetic"
API = "https://api.synthetic.example"
TOKEN = "synthetic-live-token"  # noqa: S105 - a test value
USER_ID = "1234567"
"""The SYNTHETIC user id GitHub's primary-limit message names (it must never be logged)."""
PRIMARY_MESSAGE = (
    f"API rate limit exceeded for user ID {USER_ID}. If you reach out to GitHub Support for "
    "help, please include the request ID SYNTHETIC and timestamp SYNTHETIC."
)
SECONDARY_MESSAGE = (
    "You have exceeded a secondary rate limit. Please wait a few minutes before you try again."
)
LIMIT = 5000

type Kind = Literal["primary", "secondary", "secondary-bare", "plain", "server"]


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()


def blob_sha(body: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(body) + body, usedforsecurity=False).hexdigest()


@dataclass(frozen=True)
class Request:
    """One request the fake answered."""

    at: datetime
    method: str
    path: str
    status: int

    @property
    def counted(self) -> bool:
        """Counted against the primary limit (a 304 is free)."""
        return self.status != httpx.codes.NOT_MODIFIED

    @property
    def write(self) -> bool:
        return self.method in {"POST", "PATCH"}

    def __str__(self) -> str:
        return f"{self.method} {self.path}"


@dataclass
class Armed:
    """A refusal that starts at a request to come (see :meth:`GitHubFake.refuse_from`)."""

    route: str
    length: timedelta
    kind: Kind
    body: str | None = None
    skip: int = 0

    def fires(self, route: str, request: httpx.Request) -> bool:
        """Whether ``request`` starts the refusal (each match before it counts down)."""
        if not route.startswith(self.route):
            return False
        if self.body is not None and self.body.encode() not in request.read():
            return False
        if self.skip > 0:
            self.skip -= 1
            return False
        return True


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    kind: Kind


@dataclass
class GitHubFake:
    """The SYNTHETIC repository (see the module)."""

    clock: Callable[[], datetime]
    head: str = field(default_factory=lambda: _sha("commit-0"))
    trees: dict[str, dict[str, bytes]] = field(default_factory=dict)
    commits: dict[str, str] = field(default_factory=dict)
    parents: dict[str, list[str]] = field(default_factory=dict)
    log: list[Request] = field(default_factory=list)
    windows: list[Window] = field(default_factory=list)
    armed: list[Armed] = field(default_factory=list)
    """Refusals that start at a request to come (:meth:`refuse_from`)."""
    uploads: list[tuple[datetime, dict[str, bytes]]] = field(default_factory=list)
    """Each commit that moved the branch: when, and the files it changed."""
    race: Callable[[], None] | None = None
    """Called as a PATCH arrives, before it is answered (another writer, ``live blank``)."""
    tokens: set[str] = field(default_factory=set)
    secondary_wait: int | None = 60
    """The ``retry-after`` of a secondary limit (``secondary-bare`` sends none)."""
    planned: list[tuple[datetime, dict[str, bytes]]] = field(default_factory=list)
    """Other writers' commits, each landed before the first request at or after its time."""

    def __post_init__(self) -> None:
        tree = _sha("tree-0")
        self.trees.setdefault(tree, {})
        self.commits.setdefault(self.head, tree)
        self.parents.setdefault(self.head, [])

    # --- the test's side ---------------------------------------------------------------------

    def refuse(self, start: datetime, end: datetime, kind: Kind = "primary") -> None:
        """Refuse every request in [start, end), by the clock."""
        self.windows.append(Window(start, end, kind))

    def refuse_from(
        self,
        route: str,
        length: timedelta,
        kind: Kind = "primary",
        *,
        body: str | None = None,
        skip: int = 0,
    ) -> None:
        """Refuse for ``length`` from the first request whose ``METHOD path`` starts with
        ``route`` (and whose body holds ``body``, when given), after ``skip`` such
        requests."""
        self.armed.append(Armed(route, length, kind, body, skip))

    def tree(self, sha: str | None = None) -> dict[str, bytes]:
        return self.trees[self.commits[sha or self.head]]

    def commit_other(self, files: dict[str, bytes]) -> str:
        """Another writer's commit on the head (predict.yml's predictions, ``live blank``)."""
        made = {**self.tree(), **files}
        tree = _sha(json.dumps(sorted((k, v.decode()) for k, v in made.items())))
        self.trees[tree] = made
        head = _sha(f"other {tree} {self.head}")
        self.commits[head] = tree
        self.parents[head] = [self.head]
        self.head = head
        return head

    def later(self, when: datetime, files: dict[str, bytes]) -> None:
        """Another writer commits ``files`` at ``when`` (predict.yml at :07 and :37)."""
        self.planned.append((when, files))

    def publisher(self, now: Callable[[], datetime] | None = None) -> GitHubPublisher:
        """A :class:`GitHubPublisher` on this fake, on ``now`` (the fake's clock when not
        given)."""
        return GitHubPublisher(
            repository=REPOSITORY,
            token=TOKEN,
            client=httpx.Client(transport=httpx.MockTransport(self)),
            api=API,
            now=now or self.clock,
        )

    def sent(self, start: datetime | None = None, end: datetime | None = None) -> list[Request]:
        """The requests answered in [start, end)."""
        return [
            one
            for one in self.log
            if (start is None or one.at >= start) and (end is None or one.at < end)
        ]

    # --- GitHub's side -----------------------------------------------------------------------

    def _used(self, now: datetime) -> int:
        hour = now.replace(minute=0, second=0, microsecond=0)
        return sum(1 for one in self.log if one.at >= hour and one.counted)

    def _headers(self, now: datetime, *, remaining: int | None = None) -> dict[str, str]:
        used = min(LIMIT, self._used(now) + 1)
        reset = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return {
            "date": format_datetime(now, usegmt=True),
            "x-github-request-id": f"SYNT:{len(self.log):06X}",
            "x-ratelimit-limit": str(LIMIT),
            "x-ratelimit-remaining": str(LIMIT - used if remaining is None else remaining),
            "x-ratelimit-used": str(used),
            "x-ratelimit-resource": "core",
            "x-ratelimit-reset": str(int(reset.timestamp())),
        }

    def _window(self, now: datetime, route: str, request: httpx.Request) -> Window | None:
        for armed in list(self.armed):
            if armed.fires(route, request):
                self.armed.remove(armed)
                self.windows.append(Window(now, now + armed.length, armed.kind))
        return next((w for w in self.windows if w.start <= now < w.end), None)

    def _refusal(self, now: datetime, window: Window) -> httpx.Response:
        headers = self._headers(now)
        if window.kind == "primary":
            headers.update(
                {
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-used": str(LIMIT),
                    "x-ratelimit-reset": str(int(window.end.timestamp())),
                }
            )
            return httpx.Response(403, headers=headers, json={"message": PRIMARY_MESSAGE})
        if window.kind in {"secondary", "secondary-bare"}:
            if window.kind == "secondary" and self.secondary_wait is not None:
                headers["retry-after"] = str(self.secondary_wait)
            return httpx.Response(403, headers=headers, json={"message": SECONDARY_MESSAGE})
        if window.kind == "server":
            return httpx.Response(502, headers=headers, json={"message": "SYNTHETIC outage"})
        headers["x-accepted-github-permissions"] = "contents=write"
        return httpx.Response(
            403, headers=headers, json={"message": "Resource not accessible by SYNTHETIC token"}
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        now = self.clock()
        for planned in [one for one in self.planned if one[0] <= now]:
            self.planned.remove(planned)
            self.commit_other(planned[1])
        path = request.url.path.removeprefix(f"/repos/{REPOSITORY}/")
        self.tokens.add(request.headers.get("authorization", ""))
        window = self._window(now, f"{request.method} {path}", request)
        if window is not None:
            response = self._refusal(now, window)
        else:
            response = self._answer(request, path, now)
        self.log.append(Request(now, request.method, path, response.status_code))
        return response

    def _answer(  # noqa: PLR0911 - one per route
        self, request: httpx.Request, path: str, now: datetime
    ) -> httpx.Response:
        headers = self._headers(now)
        if request.method == "GET" and path == "git/ref/heads/main":
            return httpx.Response(200, headers=headers, json={"object": {"sha": self.head}})
        if request.method == "GET" and path.startswith("git/commits/"):
            sha = path.rsplit("/", 1)[1]
            body = {"sha": sha, "tree": {"sha": self.commits[sha]}}
            return httpx.Response(200, headers=headers, json=body)
        if request.method == "POST" and path == "git/trees":
            body = json.loads(request.read())
            files = dict(self.trees[body["base_tree"]])
            for entry in body["tree"]:
                files[entry["path"]] = entry["content"].encode()
            sha = _sha(json.dumps(sorted((k, v.decode()) for k, v in files.items())))
            self.trees[sha] = files
            return httpx.Response(201, headers=headers, json={"sha": sha})
        if request.method == "POST" and path == "git/commits":
            body = json.loads(request.read())
            sha = _sha(f"{body['tree']}{body['parents']}")
            self.commits[sha] = body["tree"]
            self.parents[sha] = list(body["parents"])
            return httpx.Response(201, headers=headers, json={"sha": sha})
        if request.method == "PATCH" and path == "git/refs/heads/main":
            if self.race is not None:
                self.race()
            body = json.loads(request.read())
            new = body["sha"]
            if body["force"] is not False or self.head not in self.parents[new]:
                return httpx.Response(
                    422, headers=headers, json={"message": "Update is not a fast forward"}
                )
            before = self.tree()
            self.head = new
            changed = {k: v for k, v in self.tree().items() if before.get(k) != v}
            self.uploads.append((now, changed))
            return httpx.Response(200, headers=headers, json={"object": {"sha": new}})
        if request.method == "GET" and path.startswith("contents/"):
            assert request.headers["accept"] == "application/vnd.github.raw+json"
            key = path.removeprefix("contents/")
            ref = request.url.params.get("ref", "main")
            sha = self.head if ref == "main" else ref
            files = self.tree(sha)
            if key not in files:
                return httpx.Response(404, headers=headers, json={"message": "Not Found"})
            etag = f'"{blob_sha(files[key])}"'
            if request.headers.get("if-none-match") == etag:
                return httpx.Response(304, headers={**headers, "etag": etag})
            return httpx.Response(200, headers={**headers, "etag": etag}, content=files[key])
        return httpx.Response(500, headers=headers)

"""The directory edition the deployed site serves, read exactly or not at all.

The preview build dates the directory from the edition the site serves now
(:func:`snowlight.directory.build.choose_generated_on`). An edition read from an
earlier deploy than the live one could give changed content a date that already
names other content, so this reader returns an edition only from a source that is
provably the live deploy, and otherwise fails: a failed preview leaves the site
as it is, which is always safe. What each failure means and how to clear it is
in docs/deployed-edition.md.

A plain GET of ``<site>/data/schools/edition.json`` is not such a source. GitHub
Pages serves the site through Fastly, which ignores the query string and the
request's ``Cache-Control``/``Pragma`` headers, and keeps a copy for
``max-age=600`` seconds, a 404 for longer (one was served 1,602 seconds old on
2026-10-13). A "cache-busting" query therefore busts nothing. The live ingest
(S8-D) reads the same file through the same CDN and needs the same check
(:func:`fetched_after`) before it trusts a read as current.

The reader takes the edition from:

1. **The live deploy's artifact.** Pages serves the newest deployment of the
   ``github-pages`` environment whose latest status is ``success``. When the
   newest deployment is that one, its workflow run's ``github-pages`` artifact
   holds exactly the files the site serves. The edition is made from the
   artifact's own ``data/schools/meta.<hash>.json`` and ``points.<hash>.bin``
   (:func:`snowlight.schemas.directory.written_edition`), and when the artifact
   also holds ``data/schools/edition.json`` that file must name them. A deploy
   that predates editions so still has one: the artifact never answers "none
   deployed".
2. **The CDN, when its copy is younger than every deployment change.** The CDN
   fetched its copy from Pages at ``Date - Age``. Only a copy fetched at least
   :data:`SETTLE` after the newest deployment last changed (its creation, its
   last update, each status, and the end of its workflow run) is the live one;
   an older copy is refused and asked for again until the CDN fetches a new one,
   for up to :data:`MAX_WAIT`. This path is taken when the artifact cannot be
   read (it expires a day after the deploy, or it is not laid out as a Pages
   build of this site) or the newest deployment did not succeed (a failed or
   cancelled deploy may still have gone live). The edition is checked as the
   artifact's is: it must name the ``meta.<hash>.json`` and ``points.<hash>.bin``
   the CDN serves the page, found where the page finds them, in the list of data
   files its scripts carry (web/tools/data-files.ts), from a copy of
   ``index.html`` fetched after the same moment. A fresh 404 for the edition
   means "none deployed" only when nothing was ever deployed, or when the newest
   deployment's commit provably predates editions (:data:`EDITIONS_MARKER` is
   not in its tree); any other 404 is an error, since it may be an origin's
   passing 404 that the CDN keeps for ten minutes or more.

An ``edition.json`` that names another directory than the one beside it, from
either source, is :class:`EditionMismatchError`. It lasts as long as that deploy
is the newest: no source ever lets it through, so it can never date a build.

A newest deployment that never settled (it stays queued or in progress, or has
no status at all) is read as ended once its workflow run has ended. When it
names no run, or its run is gone, it is read as ended :data:`STUCK_AFTER` after
its last change, and as in progress before that.

Anything else (a deploy in progress, an API error or an answer of the wrong
shape, a 5xx after retries, a redirect off HTTPS, a body that is not an
edition) is an error.
"""

import hashlib
import io
import re
import tarfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, NoReturn

import httpx
from pydantic import ValidationError

from snowlight.schemas.directory import DirectoryEdition, written_edition

DATA_DIR = "data/"
EDITION_PATH = f"{DATA_DIR}schools/edition.json"
INDEX_PATH = "index.html"
# The directory as staged (web/scripts/stage-data.mjs): each name carries the
# first 10 hex digits of the file's SHA-256 (web/src/data/paths.ts).
_DIRECTORY_FILE = re.compile(
    r"data/schools/(meta\.([0-9a-f]{10})\.json|points\.([0-9a-f]{10})\.bin)"
)
HASH_DIGITS = 10
# The directory's files in the list of data files the page's scripts carry, as
# published under data/ (web/tools/data-files.ts; Vite writes its strings in
# backquotes, as `Object.freeze([`schools/meta.8c21509b53.json`, ...])`).
_LISTED_DIRECTORY_FILE = re.compile(
    r"""["'`]schools/(meta\.[0-9a-f]{10}\.json|points\.[0-9a-f]{10}\.bin)["'`]"""
)
# index.html's module scripts, and the chunks each script loads. Vite names a
# chunk "./<name>-<hash>.js" relative to the script that imports it, and
# "assets/<name>-<hash>.js" relative to the site in the list of a dynamic
# import's dependencies (__vite__mapDeps), which is how the entry reaches the
# data-files chunk.
_SCRIPT_TAG = re.compile(r"<script\b([^>]*)>", re.IGNORECASE)
_MODULE_TYPE = re.compile(r"""\btype\s*=\s*["']module["']""", re.IGNORECASE)
_SOURCE = re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_RELATIVE_CHUNK = re.compile(r"""["'`](\./[A-Za-z0-9_.-]+\.js)["'`]""")
_SITE_CHUNK = re.compile(r"""["'`](assets/[A-Za-z0-9_.-]+\.js)["'`]""")
# index.html is about 10 kB and the site's scripts about 50, of up to 2 MB each.
MAX_PAGE_BYTES = 1024 * 1024
MAX_SCRIPT_BYTES = 16 * 1024 * 1024
MAX_SCRIPTS = 400
PAGES_ENVIRONMENT = "github-pages"
PAGES_ARTIFACT = "github-pages"
# The tar file actions/upload-pages-artifact puts in its artifact.
ARTIFACT_TAR = "artifact.tar"
# A file in the tree of every commit whose build stages schools/edition.json, and
# one in the tree of every build of the site: a commit with the second and not
# the first predates editions.
EDITIONS_MARKER = "web/scripts/edition.mjs"
SITE_MARKER = "web/index.html"
# How long after the newest deployment's last change a CDN copy must have been
# fetched: for the deploy to reach every Pages origin, and for clock skew. Not
# yet measured (spec §9.1 lists deploy-to-visible as unknown; S8-A measures it).
SETTLE = timedelta(seconds=120)
# How long after its last change an unsettled deployment with no workflow run to
# ask is taken to have ended: far past the deploy job's 10-minute timeout.
STUCK_AFTER = timedelta(hours=1)
# How long to wait for the CDN to fetch a copy younger than the newest deployment.
MAX_WAIT = timedelta(minutes=15)
POLL = timedelta(seconds=30)
# Tries for a CDN or API answer that is neither a 200 nor a 404 (a 5xx, a timeout).
TRIES = 5
RETRY_PAUSE = timedelta(seconds=10)
# An edition is about 150 bytes; anything much larger is not one.
MAX_EDITION_BYTES = 64 * 1024
# meta.json is about 5.5 MB and points.bin 1.5 MB for 118,000 schools.
MAX_DIRECTORY_BYTES = 64 * 1024 * 1024
# Deployment states after which nothing more happens to a deployment.
SETTLED_STATES = frozenset({"success", "failure", "error", "inactive"})
_RUN_URL = re.compile(r"/actions/runs/(\d+)(?:/|$)")
# What taking apart an API answer of the wrong shape raises.
_SHAPE_ERRORS = (KeyError, IndexError, TypeError, ValueError, AttributeError)


class DeployedEditionError(RuntimeError):
    """The edition the site serves could not be known for certain."""


class DeployInProgressError(DeployedEditionError):
    """The newest deployment has not settled: until it does, the one before it is served."""


class EditionMismatchError(DeployedEditionError):
    """The live deploy's ``edition.json`` names another directory than the one beside it.

    ``claimed`` is what that ``edition.json`` says, and ``made`` the edition of the
    ``meta.json`` and ``points.bin`` beside it.
    """

    def __init__(self, message: str, *, claimed: DirectoryEdition, made: DirectoryEdition):
        super().__init__(message)
        self.claimed = claimed
        self.made = made

    def past_both(self) -> DirectoryEdition:
        """An edition dated the later of the two, whose digest no directory has.

        Given to the build as the previous edition, it dates any directory the day
        after that date, or the build date when later
        (:func:`snowlight.directory.build.choose_generated_on`): a date neither the
        deployed ``meta.json`` nor its ``edition.json`` has used, so no stamp can
        name two contents. This is the recovery docs/deployed-edition.md names; it
        is never published.
        """
        return DirectoryEdition(
            schema_version=1,
            generated_on=max(self.claimed.generated_on, self.made.generated_on),
            schools=self.made.schools,
            districts=self.made.districts,
            content_sha256="0" * 64,
        )


@dataclass(frozen=True, slots=True)
class DeployedEdition:
    """What the site serves: ``data`` is its ``edition.json``, ``None`` when it has none."""

    data: bytes | None
    source: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LiveDeployment:
    """The newest ``github-pages`` deployment, as the Deployments API records it.

    ``changed_at`` is the last time anything about it changed, and ``sha`` the
    commit it was built from.
    """

    state: str
    changed_at: datetime
    run_id: int | None
    sha: str | None


@dataclass(frozen=True, slots=True)
class DirectoryFiles:
    """The directory files a deploy serves (from its artifact, or the CDN), by published path."""

    meta_path: str
    meta: bytes
    points_path: str
    points: bytes
    edition: bytes | None


@dataclass(slots=True)
class Reader:
    """Reads the deployed edition; the clients and the clock are given, for tests.

    ``max_wait`` bounds the wait for a fresh CDN copy; a caller with a start-up
    budget (the live ingest) can give a shorter one and fail sooner.
    """

    site_url: str
    repository: str
    api: httpx.Client
    cdn: httpx.Client
    max_wait: timedelta = MAX_WAIT
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    sleep: Callable[[float], None] = time.sleep
    notes: list[str] = field(default_factory=list)

    def read(self) -> DeployedEdition:
        """Return the edition the site serves.

        Raises:
            DeployedEditionError: it cannot be known for certain.
        """
        if not self.site_url.startswith("https://"):
            raise DeployedEditionError(f"the site URL is not HTTPS: {self.site_url!r}")
        live = self.newest_deployment()
        if live is None:
            # Nothing was ever deployed; the CDN must agree.
            return self.from_cdn(None, None)
        if live.state not in SETTLED_STATES:
            live = self.ended(live)
        if live.state != "success":
            self.notes.append(
                f"the newest deploy ended {live.state!r}: whether it went live is not "
                "recorded, so the CDN is read"
            )
        elif live.run_id is None:
            self.notes.append("the live deploy names no workflow run, so the CDN is read")
        elif (from_artifact := self.from_artifact(live.run_id)) is not None:
            return from_artifact
        return self.from_cdn(live.changed_at, live.sha)

    # The Deployments, Actions and Contents APIs.

    def _api_json(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        *,
        missing_ok: bool = False,
    ) -> Any:
        """The JSON at ``path``; ``None`` for a 404 when ``missing_ok``."""
        response = self._get(self.api, path, params=params)
        if missing_ok and response.status_code == httpx.codes.NOT_FOUND:
            return None
        if response.status_code != httpx.codes.OK:
            raise DeployedEditionError(f"GitHub API {path}: HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as error:
            raise DeployedEditionError(f"GitHub API {path}: not JSON") from error

    def newest_deployment(self) -> LiveDeployment | None:
        """The newest ``github-pages`` deployment, or ``None`` when there is none."""
        deployments = self._api_json(
            f"/repos/{self.repository}/deployments",
            {"environment": PAGES_ENVIRONMENT, "per_page": 1},
        )
        if not isinstance(deployments, list):
            raise DeployedEditionError("GitHub API: the deployments are not a list")
        if not deployments:
            return None
        try:
            newest = deployments[0]
            deployment_id = int(newest["id"])
            times = [_api_time(newest["created_at"]), _api_time(newest["updated_at"])]
            sha = newest.get("sha")
        except _SHAPE_ERRORS as error:
            _wrong_shape("the newest deployment", error)
        if not isinstance(sha, str) or not sha:
            sha = None
        statuses = self._api_json(
            f"/repos/{self.repository}/deployments/{deployment_id}/statuses", {"per_page": 100}
        )
        if not isinstance(statuses, list):
            raise DeployedEditionError(
                f"GitHub API: deployment {deployment_id}'s statuses are not a list"
            )
        if not statuses:
            # Just created, or stuck before its first status: unsettled, naming no run.
            return LiveDeployment("no status", max(times), None, sha)
        try:
            times += [_api_time(status["created_at"]) for status in statuses]
            latest = max(
                statuses, key=lambda status: (_api_time(status["created_at"]), int(status["id"]))
            )
            state = latest["state"]
            if not isinstance(state, str):
                raise TypeError(f"its state is {state!r}")
            run = _RUN_URL.search(str(latest.get("log_url") or latest.get("target_url") or ""))
        except _SHAPE_ERRORS as error:
            _wrong_shape(f"a status of deployment {deployment_id}", error)
        return LiveDeployment(
            state=state,
            changed_at=max(times),
            run_id=None if run is None else int(run.group(1)),
            sha=sha,
        )

    def ended(self, live: LiveDeployment) -> LiveDeployment:
        """``live``, unsettled, as read once it can change no more; an error before that.

        A run cancelled while it deployed can leave its deployment's last status
        unsettled for good, whether or not the deploy went live. Once the run has
        ended, the deployment can change no more: it is then read as ended when
        the run ended, and the site through the CDN. With no run to ask (none is
        named, or it was deleted), it is read as ended :data:`STUCK_AFTER` after
        its last change.
        """
        run = None
        if live.run_id is not None:
            run = self._api_json(
                f"/repos/{self.repository}/actions/runs/{live.run_id}", missing_ok=True
            )
        if run is None:
            return self._stuck(live)
        try:
            status, conclusion = run["status"], run.get("conclusion")
            if status != "completed":
                raise DeployInProgressError(
                    f"a deploy is in progress (its state is {live.state!r}); run again after it"
                )
            ended_at = max(live.changed_at, _api_time(run["updated_at"]))
        except _SHAPE_ERRORS as error:
            _wrong_shape(f"workflow run {live.run_id}", error)
        self.notes.append(
            f"the newest deploy stayed {live.state!r}, but its run ended {conclusion!r}"
        )
        return LiveDeployment(f"run {conclusion}", ended_at, live.run_id, live.sha)

    def _stuck(self, live: LiveDeployment) -> LiveDeployment:
        why = "names no workflow run" if live.run_id is None else f"its run {live.run_id} is gone"
        settled = live.changed_at + STUCK_AFTER
        if self.now() < settled:
            raise DeployInProgressError(
                f"a deploy is in progress (its state is {live.state!r} and it {why}); "
                f"run again after {settled:%Y-%m-%dT%H:%M}Z"
            )
        self.notes.append(
            f"the newest deploy stayed {live.state!r} and {why}: it is taken to have ended "
            f"by {settled:%Y-%m-%dT%H:%M}Z"
        )
        return LiveDeployment(f"stuck {live.state}", settled, live.run_id, live.sha)

    def predates_editions(self, sha: str | None) -> bool:
        """Whether commit ``sha`` is a build of the site from before editions."""
        if sha is None:
            return False
        contents = f"/repos/{self.repository}/contents"
        marker = self._api_json(f"{contents}/{EDITIONS_MARKER}", {"ref": sha}, missing_ok=True)
        if marker is not None:
            return False
        site = self._api_json(f"{contents}/{SITE_MARKER}", {"ref": sha}, missing_ok=True)
        if site is None:
            raise DeployedEditionError(f"commit {sha} is not a build of the site")
        return True

    def from_artifact(self, run_id: int) -> DeployedEdition | None:
        """The edition of run ``run_id``'s Pages artifact; ``None`` when it cannot be read.

        Raises:
            DeployedEditionError: the artifact was read, and it is not a directory
                this build can date from.
            EditionMismatchError: its edition.json names another directory than
                the one beside it.
        """
        try:
            listing = self._api_json(
                f"/repos/{self.repository}/actions/runs/{run_id}/artifacts",
                {"name": PAGES_ARTIFACT},
            )
            artifacts = [
                artifact
                for artifact in listing["artifacts"]
                if artifact["name"] == PAGES_ARTIFACT and artifact["expired"] is False
            ]
            if len(artifacts) != 1:
                self.notes.append(
                    f"run {run_id} has no readable {PAGES_ARTIFACT} artifact (it lasts a "
                    "day), so the CDN is read"
                )
                return None
            response = self._get(self.api, str(artifacts[0]["archive_download_url"]))
            if response.status_code != httpx.codes.OK:
                raise DeployedEditionError(f"artifact download: HTTP {response.status_code}")
            files = directory_in_artifact(response.content)
        except (DeployedEditionError, *_SHAPE_ERRORS) as error:
            self.notes.append(f"the live deploy's artifact could not be read ({error})")
            return None
        source = f"the artifact of run {run_id}, the live deploy"
        made = _edition_of_files(files, source)
        if files.edition is None:
            self.notes.append(
                f"the live deploy predates editions: its edition is made from {files.meta_path} "
                f"and {files.points_path}"
            )
            return DeployedEdition(made.to_json_bytes(), source, tuple(self.notes))
        return DeployedEdition(
            _named_beside(files.edition, files, made, source), source, tuple(self.notes)
        )

    # The CDN.

    def from_cdn(self, changed_at: datetime | None, sha: str | None) -> DeployedEdition:
        """The edition from the CDN, from a copy fetched after ``changed_at`` + SETTLE.

        ``changed_at`` is ``None`` when nothing was ever deployed; ``sha`` is the
        commit the newest deployment was built from. An edition is taken only once
        it names the directory the CDN serves the page (:meth:`page_directory`).

        Raises:
            EditionMismatchError: it names another directory.
        """
        deadline = self.now() + self.max_wait
        response = self._fresh(EDITION_PATH, changed_at, deadline)
        source = f"the CDN, a copy fetched {fetched_at(response):%Y-%m-%dT%H:%M:%S}Z"
        if response.status_code == httpx.codes.OK:
            edition = _checked(response.content, source)
            files = self.page_directory(changed_at, deadline)
            made = _edition_of_files(files, source)
            return DeployedEdition(
                _named_beside(edition, files, made, source), source, tuple(self.notes)
            )
        if changed_at is None:
            return DeployedEdition(None, source, tuple(self.notes))
        if not self.predates_editions(sha):
            raise DeployedEditionError(
                f"{self._site_url(EDITION_PATH)} is a 404, but the newest deploy (commit {sha}) "
                "is not provably from before editions: the 404 may be an origin's passing one, "
                "which the CDN keeps"
            )
        self.notes.append(f"the newest deploy's commit {sha} predates editions")
        return DeployedEdition(None, source, tuple(self.notes))

    def _site_url(self, path: str) -> httpx.URL:
        return httpx.URL(self.site_url.rstrip("/") + "/").join(path)

    def _fresh(self, path: str, changed_at: datetime | None, deadline: datetime) -> httpx.Response:
        """The CDN's answer for ``path``, a 200 or a 404 from a copy fetched after
        ``changed_at`` + SETTLE, asked for again until ``deadline``."""
        url = self._site_url(path)
        while True:
            response = self._cdn_get(url)
            if response.status_code not in (httpx.codes.OK, httpx.codes.NOT_FOUND):
                raise DeployedEditionError(f"{url}: HTTP {response.status_code}")
            fetched = fetched_at(response)
            headers = ", ".join(
                f"{name} {response.headers[name]}"
                for name in ("age", "date", "x-cache", "last-modified")
                if name in response.headers
            )
            self.notes.append(f"CDN {path}: HTTP {response.status_code} ({headers})")
            if changed_at is None or fetched_after(response, changed_at + SETTLE):
                return response
            if self.now() >= deadline:
                raise DeployedEditionError(
                    f"the CDN's copy of {url} is from {fetched:%H:%M:%S}Z, before the last "
                    f"deploy settled ({changed_at + SETTLE:%H:%M:%S}Z), and no newer copy "
                    f"came within {self.max_wait}"
                )
            self.sleep(POLL.total_seconds())

    def _cdn_get(self, url: httpx.URL) -> httpx.Response:
        """GET ``url`` from the CDN: only a file of the site, answered by the site itself."""
        site = self._site_url("")
        if url.scheme != "https" or url.host != site.host:
            raise DeployedEditionError(f"{url} is not on the site {site}")
        response = self._get(self.cdn, str(url))
        if response.url.scheme != "https" or response.url.host != site.host:
            raise DeployedEditionError(
                f"{url} was redirected off HTTPS or off the site: {response.url}"
            )
        return response

    def _cdn_file(self, url: httpx.URL, limit: int) -> bytes:
        response = self._cdn_get(url)
        if response.status_code != httpx.codes.OK:
            raise DeployedEditionError(f"{url}: HTTP {response.status_code}")
        if len(response.content) > limit:
            raise DeployedEditionError(f"{url} is larger than {limit} bytes")
        return response.content

    def page_directory(self, changed_at: datetime | None, deadline: datetime) -> DirectoryFiles:
        """The ``meta.<hash>.json`` and ``points.<hash>.bin`` the CDN serves the page.

        The page reads the directory files named in the list of data files its
        scripts carry, so they are found there: from a copy of ``index.html``
        fetched after ``changed_at`` + SETTLE, through its module scripts and the
        chunks they import (all on the site, each named by Vite for its content,
        so any copy of one is the same), to the one meta and one points named.
        Each must be named by its bytes, as staging names it.

        Raises:
            DeployedEditionError: the page names no such pair, or not one of each.
        """
        page = self._fresh(INDEX_PATH, changed_at, deadline)
        if page.status_code != httpx.codes.OK:
            raise DeployedEditionError(f"{page.url}: HTTP {page.status_code}")
        if len(page.content) > MAX_PAGE_BYTES:
            raise DeployedEditionError(f"{page.url} is larger than {MAX_PAGE_BYTES} bytes")
        html = page.content.decode("utf-8", errors="replace")
        queue = [
            page.url.join(source[1])
            for tag in _SCRIPT_TAG.finditer(html)
            if _MODULE_TYPE.search(tag[1]) and (source := _SOURCE.search(tag[1]))
        ]
        if not queue:
            raise DeployedEditionError(f"{page.url} names no module script")
        seen: set[httpx.URL] = set()
        listed: set[str] = set()
        while queue:
            script = queue.pop()
            if script in seen:
                continue
            seen.add(script)
            if len(seen) > MAX_SCRIPTS:
                raise DeployedEditionError(f"{page.url} loads more than {MAX_SCRIPTS} scripts")
            text = self._cdn_file(script, MAX_SCRIPT_BYTES).decode("utf-8", errors="replace")
            listed.update(_LISTED_DIRECTORY_FILE.findall(text))
            queue.extend(script.join(chunk) for chunk in _RELATIVE_CHUNK.findall(text))
            queue.extend(self._site_url(chunk) for chunk in _SITE_CHUNK.findall(text))
        metas = sorted(name for name in listed if name.startswith("meta."))
        points = sorted(name for name in listed if name.startswith("points."))
        if len(metas) != 1 or len(points) != 1:
            raise DeployedEditionError(
                f"the page at {page.url} does not name one schools/meta.<hash>.json and one "
                f"points.<hash>.bin: it names {metas + points or 'none'}"
            )
        found: list[tuple[str, bytes]] = []
        for name in (metas[0], points[0]):
            path = f"{DATA_DIR}schools/{name}"
            data = self._cdn_file(self._site_url(path), MAX_DIRECTORY_BYTES)
            if hashlib.sha256(data).hexdigest()[:HASH_DIGITS] != name.split(".")[1]:
                raise DeployedEditionError(f"{path} on the CDN is not named by its bytes")
            found.append((path, data))
        (meta_path, meta), (points_path, points_bytes) = found
        return DirectoryFiles(meta_path, meta, points_path, points_bytes, None)

    def _get(
        self, client: httpx.Client, url: str, params: dict[str, str | int] | None = None
    ) -> httpx.Response:
        """GET ``url``, again after a transport error or an HTTP 5xx or 429."""
        problem = ""
        for attempt in range(TRIES):
            if attempt:
                self.sleep(RETRY_PAUSE.total_seconds())
            try:
                response = client.get(url, params=params)
            except httpx.HTTPError as error:
                problem = f"{type(error).__name__}: {error}"
                continue
            if response.status_code < httpx.codes.INTERNAL_SERVER_ERROR and (
                response.status_code != httpx.codes.TOO_MANY_REQUESTS
            ):
                return response
            problem = f"HTTP {response.status_code}"
        raise DeployedEditionError(f"{url}: {problem} after {TRIES} tries")


def fetched_at(response: httpx.Response) -> datetime:
    """When the CDN fetched the copy it answered with: its ``Date`` less its ``Age``.

    Raises:
        DeployedEditionError: the answer lacks either header.
    """
    try:
        date = parsedate_to_datetime(response.headers["date"])
        age = int(response.headers["age"])
    except (KeyError, ValueError, TypeError) as error:
        raise DeployedEditionError(
            f"{response.url}: no Date and Age to tell how old the copy is"
        ) from error
    if date.tzinfo is None:
        date = date.replace(tzinfo=UTC)
    return date - timedelta(seconds=age)


def fetched_after(response: httpx.Response, moment: datetime) -> bool:
    """Whether the CDN fetched the copy in ``response`` at or after ``moment``."""
    return fetched_at(response) >= moment


def directory_in_artifact(archive: bytes) -> DirectoryFiles:
    """The directory files of a Pages artifact (a zip of ``artifact.tar``).

    The artifact must be a build of this site laid out as Pages serves it:
    ``index.html`` at its root, and one ``data/schools/meta.<hash>.json`` and one
    ``points.<hash>.bin``, each named by its own bytes. ``edition`` is ``None``
    when it has no ``data/schools/edition.json``.

    Raises:
        DeployedEditionError: the archive is not such an artifact.
    """
    found: dict[str, tuple[str, bytes]] = {}
    edition: bytes | None = None
    index = False
    try:
        with (
            zipfile.ZipFile(io.BytesIO(archive)) as outer,
            outer.open(ARTIFACT_TAR) as inner,
            tarfile.open(fileobj=inner, mode="r|*") as tar,
        ):
            for member in tar:
                name = member.name.removeprefix("./")
                index = index or (name == INDEX_PATH and member.isfile())
                if name == EDITION_PATH:
                    edition = _member_bytes(tar, member, MAX_EDITION_BYTES)
                elif (match := _DIRECTORY_FILE.fullmatch(name)) is not None:
                    kind = "meta" if match[2] is not None else "points"
                    if kind in found:
                        raise DeployedEditionError(f"the artifact has two {kind} files")
                    data = _member_bytes(tar, member, MAX_DIRECTORY_BYTES)
                    if hashlib.sha256(data).hexdigest()[:HASH_DIGITS] != (match[2] or match[3]):
                        raise DeployedEditionError(
                            f"{name} in the artifact is not named by its bytes"
                        )
                    found[kind] = (name, data)
    except (zipfile.BadZipFile, KeyError, tarfile.TarError, OSError) as error:
        raise DeployedEditionError(f"not a Pages artifact: {error}") from error
    if not index or set(found) != {"meta", "points"}:
        raise DeployedEditionError(
            f"not laid out as a Pages build of the site: {INDEX_PATH}, "
            "data/schools/meta.<hash>.json and points.<hash>.bin are not all at its root"
        )
    (meta_path, meta), (points_path, points) = found["meta"], found["points"]
    return DirectoryFiles(meta_path, meta, points_path, points, edition)


def _member_bytes(tar: tarfile.TarFile, member: tarfile.TarInfo, limit: int) -> bytes:
    if not member.isfile() or member.size > limit:
        raise DeployedEditionError(f"{member.name} in the artifact is not a file of its size")
    handle = tar.extractfile(member)
    if handle is None:
        raise DeployedEditionError(f"{member.name} in the artifact is unreadable")
    return handle.read()


def _edition_of_files(files: DirectoryFiles, source: str) -> DirectoryEdition:
    try:
        return written_edition(files.meta, files.points)
    except ValueError as error:  # pydantic's ValidationError is a ValueError too
        raise DeployedEditionError(
            f"{files.meta_path} in {source} is not a directory this build can date from ({error})"
        ) from error


def _named_beside(
    edition: bytes, files: DirectoryFiles, made: DirectoryEdition, source: str
) -> bytes:
    """``edition``, once it is an edition that names ``made``, the edition of ``files``.

    The one check both sources make: the artifact's ``edition.json`` against the
    directory in the artifact, and the CDN's against the directory the CDN serves.

    Raises:
        EditionMismatchError: it names another directory.
    """
    data = _checked(edition, source)
    claimed = DirectoryEdition.from_json_bytes(data)
    if claimed != made:
        raise EditionMismatchError(
            f"{EDITION_PATH} in {source} does not name the {files.meta_path} and "
            f"{files.points_path} beside it: it says {claimed.generated_on}, {claimed.schools} "
            f"schools, {claimed.districts} districts, digest {claimed.content_sha256[:12]}; "
            f"they are {made.generated_on}, {made.schools}, {made.districts}, "
            f"{made.content_sha256[:12]}",
            claimed=claimed,
            made=made,
        )
    return data


def _checked(data: bytes, source: str) -> bytes:
    if len(data) > MAX_EDITION_BYTES:
        raise DeployedEditionError(f"{EDITION_PATH} from {source} is too large to be an edition")
    try:
        DirectoryEdition.from_json_bytes(data)
    except ValidationError as error:
        raise DeployedEditionError(
            f"{EDITION_PATH} from {source} is not an edition ({error.error_count()} problem(s))"
        ) from error
    return data


def _api_time(text: object) -> datetime:
    if not isinstance(text, str):
        raise DeployedEditionError(f"GitHub API: {text!r} is not a time")
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise DeployedEditionError(f"GitHub API: {text!r} is not a time") from error
    if moment.tzinfo is None:
        raise DeployedEditionError(f"GitHub API: {text!r} has no time zone")
    return moment


def _wrong_shape(what: str, error: BaseException) -> NoReturn:
    raise DeployedEditionError(
        f"GitHub API: {what} is of an unexpected shape ({type(error).__name__}: {error})"
    ) from error

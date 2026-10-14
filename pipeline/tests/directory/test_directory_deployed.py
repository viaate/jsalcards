"""Reading the edition the deployed site serves: exactly, or not at all."""

import hashlib
import io
import json
import ssl
import tarfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from snowlight.cli import main
from snowlight.directory import cli as cli_module
from snowlight.directory import deployed as deployed_module
from snowlight.directory import points
from snowlight.directory.build import choose_generated_on
from snowlight.directory.deployed import (
    EDITIONS_MARKER,
    MAX_WAIT,
    SETTLE,
    SITE_MARKER,
    STUCK_AFTER,
    TRIES,
    DeployedEditionError,
    Reader,
    directory_in_artifact,
    fetched_at,
)
from snowlight.output import dumps_json
from snowlight.schemas.directory import DirectoryEdition, written_edition

SITE = "https://snowlight.example"
REPO = "owner/site"
SHA = "5e" * 20
DEPLOYED_AT = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[3]


# A synthetic directory (test data only): six schools, two districts.
NAMES = [f"Synthetic School {letter}" for letter in "ABCDEF"]
META: dict[str, Any] = {
    "schema_version": 1,
    "count": 6,
    "ids": ["000000000001", "000000000002", "000000000003", "000000000004", "0000000A", "0000000B"],
    "names": NAMES,
    "districts": {"ids": ["0000001", "0000002"], "names": ["District One", "District Two"]},
    "school_years": {"public": "2024-2025", "private": "2023-2024"},
}


def example_points() -> bytes:
    return points.encode(
        lon_e6=[-86_100_000, -86_200_000, -86_300_000, -111_000_000, -111_100_000, -86_400_000],
        lat_e6=[34_100_000, 34_200_000, 34_300_000, 33_400_000, 33_500_000, 34_400_000],
        district=[0, 0, 1, 1, points.NO_DISTRICT, points.NO_DISTRICT],
        kind=[0, 2, 0, 4, 1, 1],
        district_count=2,
    )


def _meta(day: str = "2026-10-12", **change: Any) -> bytes:
    """meta.json of the synthetic directory, written as the build writes it."""
    return dumps_json({**META, "generated_on": day, **change})


def _hashed(path: str, data: bytes) -> str:
    stem, suffix = path.rsplit(".", 1)
    return f"{stem}.{hashlib.sha256(data).hexdigest()[:10]}.{suffix}"


def _site(
    meta: bytes | None = None, *, edition: bytes | None = None, prefix: str = "./"
) -> dict[str, bytes]:
    """A Pages build of the site: index.html, its directory and, given, its edition."""
    meta = _meta() if meta is None else meta
    points = example_points()
    files = {
        f"{prefix}index.html": b"<!doctype html>",
        f"{prefix}{_hashed('data/schools/meta.json', meta)}": meta,
        f"{prefix}{_hashed('data/schools/points.bin', points)}": points,
        f"{prefix}data/schools/details/0.0123456789.json": b"[]",
    }
    if edition is not None:
        files[f"{prefix}data/schools/edition.json"] = edition
    return files


OTHER_META = _meta("2026-10-11")
# What the CDN serves in these tests: NEW, the live deploy's directory, and OLD,
# an earlier deploy's edition of other content.
NEW_META = _meta("2026-10-13")
OLD_META = _meta(names=["Synthetic School Z", *NAMES[1:]])
NEW = written_edition(NEW_META, example_points())
OLD = written_edition(OLD_META, example_points())
ENTRY = "assets/index-Ab12Cd34.js"


def _listed(*names: str) -> bytes:
    """A data-files chunk as Vite writes it (web/tools/data-files.ts), listing ``names``.

    As on the live site on 2026-10-14: ``var e=Object.freeze([`schools/meta.8c21509b53.json`,
    ...]);export{e as t};``.
    """
    listed = ",".join(f"`{name}`" for name in names).encode()
    return b"var e=Object.freeze([" + listed + b"]);export{e as t};"


def _cdn_site(meta: bytes = NEW_META, base: str = "/") -> dict[str, bytes]:
    """The site as the CDN serves it under ``base``, but its edition.json: index.html, its
    scripts, which list the data files the page reads, and the directory they name."""
    points = example_points()
    meta_name = _hashed("meta.json", meta)
    points_name = _hashed("points.bin", points)
    return {
        f"{base}index.html": (
            b"<!doctype html><script>window.x=1</script>"
            b'<script type="module" crossorigin src="' + f"{base}{ENTRY}".encode() + b'"></script>'
        ),
        # As Vite writes the entry: the data-files chunk reached through the list of a
        # dynamic import's dependencies, relative to the site, another chunk relative
        # to the entry.
        f"{base}{ENTRY}": (
            b"const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["
            b'"assets/data-files-Xy98Zw76.js","assets/main-Bb11Cc22.css"])))=>i.map(i=>d[i]);'
            b"const a=()=>import(`./AreaPanel-Qr56St78.js`);"
        ),
        f"{base}assets/data-files-Xy98Zw76.js": _listed(
            f"schools/{meta_name}", f"schools/{points_name}", "search-index.0123456789.bin"
        ),
        # A chunk that imports one already read: each is read once.
        f"{base}assets/AreaPanel-Qr56St78.js": b'import{t}from"./index-Ab12Cd34.js";',
        f"{base}data/schools/{meta_name}": meta,
        f"{base}data/schools/{points_name}": points,
    }


def _edition_of_site(meta: bytes | None = None) -> bytes:
    return written_edition(_meta() if meta is None else meta, example_points()).to_json_bytes()


def _artifact(files: dict[str, bytes], directories: tuple[str, ...] = ()) -> bytes:
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w") as tar:
        for name in directories:
            entry = tarfile.TarInfo(name)
            entry.type = tarfile.DIRTYPE
            tar.addfile(entry)
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as outer:
        outer.writestr("artifact.tar", tar_bytes.getvalue())
    return archive.getvalue()


@dataclass
class Clock:
    """A clock that moves only when the reader sleeps."""

    at: datetime = DEPLOYED_AT + timedelta(minutes=3)
    slept: list[float] = field(default_factory=list)

    def now(self) -> datetime:
        return self.at

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.at += timedelta(seconds=seconds)


@dataclass
class Pages:
    """GitHub's API and the CDN in front of Pages, as a test sets them up."""

    clock: Clock
    deployments: Any = field(default_factory=list)
    statuses: Any = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    archive: bytes = b""
    # Each CDN answer: (status, body, when the CDN fetched its copy).
    cdn_answers: Callable[[Clock], tuple[int, bytes, datetime]] | None = None
    cdn_redirect: str | None = None
    # The rest of the site on the CDN, and when the CDN fetched its copy of a file.
    cdn_site: dict[str, bytes] = field(default_factory=_cdn_site)
    page_fetched: Callable[[Clock], datetime] = field(default=lambda clock: clock.at)
    api_failures: int = 0
    # The workflow run behind the deployment; None when it was deleted.
    run: Any = field(default_factory=lambda: {"status": "in_progress"})
    # The files in the deployed commit's tree, for the Contents API.
    tree: set[str] = field(default_factory=lambda: {SITE_MARKER, EDITIONS_MARKER})
    calls: list[str] = field(default_factory=list)

    def deploy(self, state: str = "success", at: datetime = DEPLOYED_AT, run: int = 7) -> None:
        self.deployments = [
            {
                "id": 1,
                "sha": SHA,
                "created_at": _iso(at - timedelta(seconds=15)),
                "updated_at": _iso(at),
            }
        ]
        run_url = f"https://github.com/{REPO}/actions/runs/{run}/job/99"
        self.statuses = [
            {"id": 2, "state": state, "created_at": _iso(at), "log_url": run_url},
            {"id": 1, "state": "in_progress", "created_at": _iso(at - timedelta(seconds=10))},
        ]

    def api(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"api {path}")
        if self.api_failures:
            self.api_failures -= 1
            return httpx.Response(502)
        if path == f"/repos/{REPO}/deployments":
            assert request.url.params["environment"] == "github-pages"
            assert request.headers["authorization"] == "Bearer token"
        contents = f"/repos/{REPO}/contents/"
        if path.startswith(contents):
            assert request.url.params["ref"] == SHA
            found = path.removeprefix(contents) in self.tree
            return httpx.Response(200, json={"type": "file"}) if found else httpx.Response(404)
        answers: dict[str, Any] = {
            f"/repos/{REPO}/deployments": self.deployments,
            f"/repos/{REPO}/deployments/1/statuses": self.statuses,
            f"/repos/{REPO}/actions/runs/7": self.run,
            f"/repos/{REPO}/actions/runs/7/artifacts": {"artifacts": self.artifacts},
        }
        if path == "/download":
            return httpx.Response(200, content=self.archive)
        if answers.get(path) is not None:
            return httpx.Response(200, json=answers[path])
        return httpx.Response(404)

    def cdn(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"cdn {request.url}")
        if self.cdn_redirect is not None and request.url.scheme == "https":
            return httpx.Response(301, headers={"location": self.cdn_redirect})
        assert "authorization" not in request.headers
        if request.url.path.endswith("/data/schools/edition.json"):
            assert self.cdn_answers is not None
            status, body, fetched = self.cdn_answers(self.clock)
        elif request.url.path in self.cdn_site:
            status, body = 200, self.cdn_site[request.url.path]
            fetched = self.page_fetched(self.clock)
        else:
            status, body, fetched = 404, b"Not Found", self.clock.at
        age = int((self.clock.at - fetched).total_seconds())
        headers = {"date": format_datetime(self.clock.at, usegmt=True), "age": str(age)}
        return httpx.Response(status, content=body, headers=headers)

    def reader(self) -> Reader:
        api = httpx.Client(
            base_url="https://api.example",
            headers={"Authorization": "Bearer token"},
            transport=httpx.MockTransport(self.api),
        )
        cdn = httpx.Client(transport=httpx.MockTransport(self.cdn), follow_redirects=True)
        return Reader(SITE, REPO, api, cdn, now=self.clock.now, sleep=self.clock.sleep)

    def cdn_reads(self) -> int:
        return len([call for call in self.calls if call.startswith("cdn")])


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def pages() -> Pages:
    return Pages(Clock())


def _with_artifact(pages: Pages, files: dict[str, bytes], *, expired: bool = False) -> None:
    pages.artifacts = [
        {
            "name": "github-pages",
            "expired": expired,
            "archive_download_url": "https://api.example/download",
        }
    ]
    pages.archive = _artifact(files)


def _stale_then_fresh(
    refuse_until: datetime, stale_fetch: datetime
) -> Callable[[Clock], tuple[int, bytes, datetime]]:
    """A CDN that serves OLD from a copy fetched at ``stale_fetch`` until ``refuse_until``,
    then NEW from a copy it fetches then."""

    def answers(clock: Clock) -> tuple[int, bytes, datetime]:
        if clock.at < refuse_until:
            return 200, OLD.to_json_bytes(), stale_fetch
        return 200, NEW.to_json_bytes(), clock.at

    return answers


# The live deploy's artifact.


def test_the_live_deploys_artifact_is_read(pages: Pages) -> None:
    pages.deploy()
    edition = _edition_of_site()
    _with_artifact(pages, _site(edition=edition))
    found = pages.reader().read()
    assert found.data == edition
    assert found.source == "the artifact of run 7, the live deploy"
    assert pages.cdn_reads() == 0


def test_an_artifact_without_an_edition_is_dated_from_its_own_directory(pages: Pages) -> None:
    """A live deploy from before editions still names its directory: never "none deployed".

    So the first build with editions keeps the deployed date for the same content,
    and dates changed content past it, never back to a date that names other content.
    """
    pages.deploy()
    later = _meta("2026-10-14")
    _with_artifact(pages, _site(later))
    found = pages.reader().read()
    assert found.data == _edition_of_site(later)
    assert any("the live deploy predates editions" in note for note in found.notes)
    deployed = DirectoryEdition.from_json_bytes(found.data)
    assert deployed.generated_on == date(2026, 10, 14)
    build_day = date(2026, 10, 12)
    same = choose_generated_on(deployed.content_sha256, 6, 2, build_day, deployed)
    assert same.generated_on == "2026-10-14"
    changed = choose_generated_on("c" * 64, 6, 2, build_day, deployed)
    assert changed.generated_on == "2026-10-15"
    assert pages.cdn_reads() == 0


def test_an_artifact_edition_that_names_another_directory_is_an_error(pages: Pages) -> None:
    pages.deploy()
    other = _edition_of_site(_meta(names=["Other", *NAMES[1:]]))
    _with_artifact(pages, _site(edition=other))
    with pytest.raises(DeployedEditionError, match="does not name the data/schools/meta"):
        pages.reader().read()
    _with_artifact(pages, _site(edition=b'{"schools":17}'))
    with pytest.raises(DeployedEditionError, match="is not an edition"):
        pages.reader().read()


@pytest.mark.parametrize(
    "files",
    [
        pytest.param(_site(edition=_edition_of_site(), prefix="./dist/"), id="under a prefix"),
        pytest.param(
            {name: data for name, data in _site().items() if "points" not in name},
            id="no points",
        ),
        pytest.param(
            {name: data for name, data in _site().items() if "index" not in name},
            id="no index",
        ),
        pytest.param(
            {**_site(), f"./{_hashed('data/schools/meta.json', OTHER_META)}": OTHER_META},
            id="two metas",
        ),
        pytest.param(
            {
                name.replace(name.split(".")[-2], "0" * 10) if "meta" in name else name: data
                for name, data in _site().items()
            },
            id="misnamed meta",
        ),
    ],
)
def test_an_artifact_not_laid_out_as_the_site_is_read_through_the_cdn(
    pages: Pages, files: dict[str, bytes]
) -> None:
    """An artifact laid out otherwise is never taken to mean "none deployed"."""
    pages.deploy(at=DEPLOYED_AT - timedelta(hours=2))
    _with_artifact(pages, files)
    pages.cdn_answers = lambda clock: (200, NEW.to_json_bytes(), clock.at)
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    assert found.source.startswith("the CDN")
    assert any("artifact could not be read" in note for note in found.notes)
    # And a 404 from the CDN, the deploy being from a build with editions, is an error.
    pages.cdn_answers = lambda clock: (404, b"", clock.at)
    with pytest.raises(DeployedEditionError, match="not provably from before editions"):
        pages.reader().read()


def test_an_expired_artifact_is_never_downloaded(pages: Pages) -> None:
    pages.deploy(at=DEPLOYED_AT - timedelta(days=2))
    _with_artifact(pages, _site(edition=_edition_of_site()), expired=True)
    pages.cdn_answers = lambda clock: (200, NEW.to_json_bytes(), clock.at)
    found = pages.reader().read()
    assert "api /download" not in pages.calls
    assert found.data == NEW.to_json_bytes()
    assert found.source.startswith("the CDN")


def test_an_unreadable_artifact_falls_back_to_a_fresh_cdn_copy(pages: Pages) -> None:
    pages.deploy(at=DEPLOYED_AT - timedelta(hours=2))
    _with_artifact(pages, {})
    pages.archive = b"not a zip"
    pages.cdn_answers = lambda clock: (200, NEW.to_json_bytes(), clock.at)
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    assert any("artifact could not be read (not a Pages artifact" in n for n in found.notes)


def test_a_failed_artifact_download_falls_back_to_the_cdn(pages: Pages) -> None:
    pages.deploy(at=DEPLOYED_AT - timedelta(hours=2))
    _with_artifact(pages, _site(edition=_edition_of_site()))
    pages.artifacts[0]["archive_download_url"] = "https://api.example/gone"
    pages.cdn_answers = lambda clock: (200, NEW.to_json_bytes(), clock.at)
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    assert any("artifact download: HTTP 404" in note for note in found.notes)


def test_an_artifact_whose_directory_cannot_be_read_is_an_error(pages: Pages) -> None:
    """The live deploy's own files say nothing this build can date from: no guess is made."""
    pages.deploy()
    _with_artifact(pages, _site(b'{"schema_version":1}'))
    with pytest.raises(DeployedEditionError, match="is not a directory this build can date"):
        pages.reader().read()
    # A meta.json written otherwise than the build writes it has no digest to compare.
    _with_artifact(pages, _site(json.dumps({**META, "generated_on": "2026-10-12"}).encode()))
    with pytest.raises(DeployedEditionError, match="date is not written once"):
        pages.reader().read()
    assert pages.cdn_reads() == 0


def test_directory_in_artifact_refuses_what_is_not_an_artifact() -> None:
    with pytest.raises(DeployedEditionError, match="not a Pages artifact"):
        directory_in_artifact(b"not a zip")
    with pytest.raises(DeployedEditionError, match="not a file of its size"):
        directory_in_artifact(_artifact(_site(edition=b"x" * 70_000)))
    files = directory_in_artifact(_artifact(_site(edition=b"{}", prefix="")))
    assert files.edition == b"{}"
    assert files.meta == _meta()
    assert files.points == example_points()
    assert files.meta_path.startswith("data/schools/meta.")


# The CDN: only a copy fetched after the newest deployment last changed.


def test_a_cdn_copy_from_before_the_last_deploy_is_never_used(pages: Pages) -> None:
    """The stale-edge case: the CDN still holds the edition of the deploy before the live one.

    Read as current, its older date would let the next changed directory take the
    live deploy's date, one stamp for two contents. The reader waits for a copy the
    CDN fetched after the deploy settled, and fails if none comes.
    """
    pages.deploy(state="success")
    # The artifact has expired, so the CDN is read.
    stale_fetch = DEPLOYED_AT - timedelta(minutes=4)
    pages.cdn_answers = lambda _clock: (200, OLD.to_json_bytes(), stale_fetch)
    with pytest.raises(DeployedEditionError, match="before the last deploy settled"):
        pages.reader().read()
    assert pages.clock.at - (DEPLOYED_AT + timedelta(minutes=3)) >= MAX_WAIT
    # A caller with a start-up budget can wait less.
    pages.clock.at = start = DEPLOYED_AT + timedelta(minutes=3)
    reader = pages.reader()
    reader.max_wait = timedelta(minutes=2)
    with pytest.raises(DeployedEditionError, match="no newer copy came within 0:02:00"):
        reader.read()
    assert timedelta(minutes=2) <= pages.clock.at - start < timedelta(minutes=3)
    # Had the stale copy been used, the changed directory would have reused the live stamp.
    live = choose_generated_on(NEW.content_sha256, 6, 2, date(2026, 10, 13), OLD)
    assert live.generated_on == NEW.generated_on.isoformat()
    third = choose_generated_on("c" * 64, 6, 2, date(2026, 10, 13), OLD)
    assert third.generated_on == NEW.generated_on.isoformat()
    assert choose_generated_on("c" * 64, 6, 2, date(2026, 10, 13), NEW).generated_on == (
        "2026-10-14"
    )


def test_a_copy_fetched_before_the_deploy_settled_is_refused(pages: Pages) -> None:
    """A copy fetched after the deploy's last status but within SETTLE of it may predate it.

    The deploy succeeded at T with no readable artifact; the CDN's copy was fetched
    at T+60s, before every Pages origin need serve the deploy. It is refused, and
    the copy the CDN fetches later is used.
    """
    pages.deploy()
    early = DEPLOYED_AT + timedelta(seconds=60)
    assert early < DEPLOYED_AT + SETTLE
    pages.cdn_answers = _stale_then_fresh(DEPLOYED_AT + timedelta(minutes=4), early)
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    assert pages.cdn_reads() > 1
    assert "age 120" in found.notes[1]


@pytest.mark.parametrize("later", ["the deployment's updated_at", "a status"])
def test_a_copy_from_before_the_deployments_last_change_is_refused(
    pages: Pages, later: str
) -> None:
    """The deployment's updated_at can be later than its last status, and the other way
    round: the latest of all of them counts."""
    pages.deploy()
    updated = DEPLOYED_AT + timedelta(minutes=5)
    if later == "a status":
        pages.statuses[0]["created_at"] = _iso(updated)
    else:
        pages.deployments[0]["updated_at"] = _iso(updated)
    pages.clock.at = DEPLOYED_AT + timedelta(minutes=6)
    copy = DEPLOYED_AT + timedelta(minutes=3)
    assert copy >= DEPLOYED_AT + SETTLE
    pages.cdn_answers = _stale_then_fresh(updated + SETTLE + timedelta(minutes=1), copy)
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    assert pages.cdn_reads() > 1


def test_a_copy_from_before_a_cancelled_run_ended_is_refused(pages: Pages) -> None:
    """A run cancelled with its deployment in progress: the deploy may go live until it ends."""
    pages.deploy(state="in_progress")
    ended = DEPLOYED_AT + timedelta(minutes=5)
    pages.run = {"status": "completed", "conclusion": "cancelled", "updated_at": _iso(ended)}
    pages.clock.at = DEPLOYED_AT + timedelta(minutes=6)
    copy = DEPLOYED_AT + timedelta(minutes=3)
    assert copy >= DEPLOYED_AT + SETTLE
    pages.cdn_answers = _stale_then_fresh(ended + SETTLE + timedelta(minutes=1), copy)
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    assert pages.cdn_reads() > 1
    assert any("its run ended 'cancelled'" in note for note in found.notes)


def test_the_reader_waits_for_a_fresh_cdn_copy(pages: Pages) -> None:
    pages.deploy(state="failure")
    # The CDN holds its copy for ten minutes, then fetches the live one.
    pages.cdn_answers = _stale_then_fresh(
        DEPLOYED_AT + timedelta(minutes=8), DEPLOYED_AT - timedelta(minutes=2)
    )
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    assert found.source.startswith("the CDN, a copy fetched 2026-10-13T09:08")
    assert sum(pages.clock.slept) >= 5 * 60
    assert any("ended 'failure'" in note for note in found.notes)


def test_a_fresh_404_means_none_deployed_only_before_editions(pages: Pages) -> None:
    """After editions ship one always exists: a 404 may be an origin's passing one."""
    pages.deploy(at=DEPLOYED_AT - timedelta(days=8))
    pages.cdn_answers = lambda clock: (404, b"Not Found", clock.at - timedelta(minutes=27))
    # The deployed commit's build stages edition.json: the 404 proves nothing.
    with pytest.raises(DeployedEditionError, match="not provably from before editions"):
        pages.reader().read()
    # A commit from before editions: none is deployed.
    pages.tree = {SITE_MARKER}
    found = pages.reader().read()
    assert found.data is None
    assert any("run 7 has no readable github-pages artifact" in note for note in found.notes)
    assert f"the newest deploy's commit {SHA} predates editions" in found.notes
    # A commit that is no build of the site (or is gone) proves nothing either.
    pages.tree = set()
    with pytest.raises(DeployedEditionError, match="is not a build of the site"):
        pages.reader().read()
    # Nor does a deployment that names no commit.
    pages.tree = {SITE_MARKER}
    del pages.deployments[0]["sha"]
    with pytest.raises(DeployedEditionError, match="not provably from before editions"):
        pages.reader().read()


def test_the_markers_are_in_this_tree() -> None:
    """The commit that builds this reader stages editions: its markers must exist."""
    assert (REPO_ROOT / EDITIONS_MARKER).is_file()
    assert (REPO_ROOT / SITE_MARKER).is_file()
    stage = (REPO_ROOT / "web/scripts/stage-data.mjs").read_text(encoding="utf-8")
    assert "from './edition.mjs'" in stage


def test_nothing_ever_deployed(pages: Pages) -> None:
    pages.cdn_answers = lambda clock: (404, b"", clock.at)
    assert pages.reader().read().data is None


# Deployments that did not settle.


def test_a_deploy_in_progress_is_an_error(pages: Pages) -> None:
    pages.deploy(state="in_progress")
    with pytest.raises(DeployedEditionError, match="a deploy is in progress"):
        pages.reader().read()


def test_a_deploy_whose_run_ended_unsettled_is_read_through_the_cdn(pages: Pages) -> None:
    """A run cancelled mid-deploy can leave the deployment in progress for good.

    Its deploy may or may not have gone live, so the CDN is read, from a copy
    fetched after the run ended; refusing instead would stop every later preview.
    """
    pages.deploy(state="in_progress")
    ended = DEPLOYED_AT + timedelta(minutes=1)
    pages.run = {"status": "completed", "conclusion": "cancelled", "updated_at": _iso(ended)}
    pages.cdn_answers = _stale_then_fresh(
        ended + timedelta(minutes=6), ended - timedelta(seconds=30)
    )
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    assert any("its run ended 'cancelled'" in note for note in found.notes)


@pytest.mark.parametrize("stuck", ["no status", "run deleted", "no run named"])
def test_a_stuck_deploy_is_read_as_ended_an_hour_on(pages: Pages, stuck: str) -> None:
    """A deployment with no run to ask can stay unsettled for good; only a deploy changes
    the newest deployment, and the reader runs before any deploy. So it is read as
    ended STUCK_AFTER after its last change, and through a CDN copy fetched after that."""
    pages.deploy(state="queued")
    if stuck == "no status":
        pages.statuses = []
    elif stuck == "run deleted":
        pages.run = None
    else:
        for status in pages.statuses:
            status.pop("log_url", None)
    with pytest.raises(DeployedEditionError, match=r"in progress .* run again after"):
        pages.reader().read()
    settled = DEPLOYED_AT + STUCK_AFTER
    pages.clock.at = settled + timedelta(minutes=1)
    # A copy fetched while the deploy might still have gone live is refused.
    pages.cdn_answers = _stale_then_fresh(
        settled + SETTLE + timedelta(minutes=1), settled - timedelta(minutes=1)
    )
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    assert pages.cdn_reads() > 1
    assert any("it is taken to have ended" in note for note in found.notes)


# Failures.


@pytest.mark.parametrize("status", [500, 503, 429])
def test_a_failing_cdn_is_retried_then_an_error(pages: Pages, status: int) -> None:
    pages.deploy(at=DEPLOYED_AT - timedelta(days=1))
    pages.cdn_answers = lambda clock: (status, b"", clock.at)
    with pytest.raises(DeployedEditionError, match=f"HTTP {status} after {TRIES} tries"):
        pages.reader().read()
    assert pages.cdn_reads() == TRIES


def test_a_passing_cdn_failure_is_ridden_out(pages: Pages) -> None:
    pages.deploy(at=DEPLOYED_AT - timedelta(days=1))
    answers = iter([(503, b""), (503, b""), (200, NEW.to_json_bytes())])

    def answer(clock: Clock) -> tuple[int, bytes, datetime]:
        status, body = next(answers)
        return status, body, clock.at

    pages.cdn_answers = answer
    assert pages.reader().read().data == NEW.to_json_bytes()


@pytest.mark.parametrize("status", [403, 401, 410])
def test_any_other_cdn_answer_is_an_error(pages: Pages, status: int) -> None:
    pages.deploy(at=DEPLOYED_AT - timedelta(days=1))
    pages.cdn_answers = lambda clock: (status, b"", clock.at)
    with pytest.raises(DeployedEditionError, match=f"HTTP {status}"):
        pages.reader().read()


def test_a_redirect_off_https_is_an_error(pages: Pages) -> None:
    pages.deploy(at=DEPLOYED_AT - timedelta(days=1))
    pages.cdn_redirect = "http://snowlight.example/data/schools/edition.json"
    pages.cdn_answers = lambda clock: (200, NEW.to_json_bytes(), clock.at)
    with pytest.raises(DeployedEditionError, match="redirected off HTTPS"):
        pages.reader().read()


def test_a_body_that_is_not_an_edition_is_an_error(pages: Pages) -> None:
    pages.deploy(at=DEPLOYED_AT - timedelta(days=1))
    pages.cdn_answers = lambda clock: (200, b"<!doctype html><title>Moved</title>", clock.at)
    with pytest.raises(DeployedEditionError, match="is not an edition"):
        pages.reader().read()


def test_a_cdn_body_too_large_for_an_edition_is_an_error(pages: Pages) -> None:
    pages.deploy(at=DEPLOYED_AT - timedelta(days=1))
    pages.cdn_answers = lambda clock: (200, b" " * 70_000, clock.at)
    with pytest.raises(DeployedEditionError, match="too large to be an edition"):
        pages.reader().read()


def test_a_cdn_answer_without_age_is_an_error(pages: Pages) -> None:
    pages.deploy(at=DEPLOYED_AT - timedelta(days=1))

    def no_age(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=NEW.to_json_bytes())

    reader = pages.reader()
    reader.cdn = httpx.Client(transport=httpx.MockTransport(no_age))
    with pytest.raises(DeployedEditionError, match="no Date and Age"):
        reader.read()


def test_api_failures_are_retried_then_an_error(pages: Pages) -> None:
    pages.deploy()
    edition = _edition_of_site()
    _with_artifact(pages, _site(edition=edition))
    pages.api_failures = 2
    assert pages.reader().read().data == edition
    pages.api_failures = TRIES
    with pytest.raises(DeployedEditionError, match="HTTP 502 after"):
        pages.reader().read()


def test_a_site_that_is_not_https_is_an_error(pages: Pages) -> None:
    reader = pages.reader()
    reader.site_url = "http://snowlight.example"
    with pytest.raises(DeployedEditionError, match="not HTTPS"):
        reader.read()


def _no_state(pages: Pages) -> None:
    del pages.statuses[0]["state"]


def _no_id(pages: Pages) -> None:
    del pages.deployments[0]["id"]


def _bad_time(pages: Pages) -> None:
    pages.statuses[0]["created_at"] = "yesterday"


def _time_not_text(pages: Pages) -> None:
    pages.deployments[0]["created_at"] = 5


def _naive_time(pages: Pages) -> None:
    pages.deployments[0]["updated_at"] = "2026-10-13T09:00:00"


def _run_not_object(pages: Pages) -> None:
    pages.statuses[0]["state"] = "in_progress"
    pages.run = ["completed"]


def _run_without_end(pages: Pages) -> None:
    pages.statuses[0]["state"] = "in_progress"
    pages.run = {"status": "completed", "conclusion": "cancelled"}


def _deployment_not_object(pages: Pages) -> None:
    pages.deployments = ["deployment"]


def _statuses_not_list(pages: Pages) -> None:
    pages.statuses = {"message": "x"}


def _deployments_not_list(pages: Pages) -> None:
    pages.deployments = {"message": "x"}


def _state_not_text(pages: Pages) -> None:
    pages.statuses[0]["state"] = 3


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (_no_state, "a status of deployment 1 is of an unexpected shape"),
        (_state_not_text, "a status of deployment 1 is of an unexpected shape"),
        (_no_id, "the newest deployment is of an unexpected shape"),
        (_deployment_not_object, "the newest deployment is of an unexpected shape"),
        (_bad_time, "'yesterday' is not a time"),
        (_naive_time, "has no time zone"),
        (_time_not_text, "5 is not a time"),
        (_run_not_object, "workflow run 7 is of an unexpected shape"),
        (_run_without_end, "workflow run 7 is of an unexpected shape"),
        (_statuses_not_list, "deployment 1's statuses are not a list"),
        (_deployments_not_list, "the deployments are not a list"),
    ],
)
def test_an_api_answer_of_the_wrong_shape_is_an_error(
    pages: Pages, change: Callable[[Pages], None], problem: str
) -> None:
    """A malformed answer is a one-line error, never a traceback."""
    pages.deploy()
    change(pages)
    with pytest.raises(DeployedEditionError, match=problem):
        pages.reader().read()


def test_an_api_refusal_or_a_body_that_is_not_json_is_an_error(pages: Pages) -> None:
    reader = pages.reader()
    reader.api = httpx.Client(
        base_url="https://api.example",
        transport=httpx.MockTransport(lambda _request: httpx.Response(403)),
    )
    with pytest.raises(DeployedEditionError, match="HTTP 403"):
        reader.read()
    reader.api = httpx.Client(
        base_url="https://api.example",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"<html>")),
    )
    with pytest.raises(DeployedEditionError, match="not JSON"):
        reader.read()


def test_a_deploy_that_names_no_run_is_read_through_the_cdn(pages: Pages) -> None:
    pages.deploy(at=DEPLOYED_AT - timedelta(hours=2))
    for status in pages.statuses:
        status.pop("log_url", None)
    pages.cdn_answers = lambda clock: (200, NEW.to_json_bytes(), clock.at)
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    assert "the live deploy names no workflow run, so the CDN is read" in found.notes


# Only the artifact of a deploy that succeeded.


def _not_a_success(pages: Pages, how: str) -> None:
    """Make the newest deployment, two hours old, one that did not end in success."""
    at = DEPLOYED_AT - timedelta(hours=2)
    if how in ("failure", "error", "inactive"):
        pages.deploy(state=how, at=at)
        return
    # The deployment stayed in progress; its run ended, or is gone.
    pages.deploy(state="in_progress", at=at)
    if how == "run deleted":
        pages.run = None
    else:
        conclusion = how.removeprefix("run ")
        ended = _iso(at + timedelta(minutes=1))
        pages.run = {"status": "completed", "conclusion": conclusion, "updated_at": ended}


@pytest.mark.parametrize(
    "how",
    ["failure", "error", "inactive", "run cancelled", "run failure", "run success", "run deleted"],
)
def test_a_deploy_that_did_not_succeed_is_never_read_from_its_artifact(
    pages: Pages, how: str
) -> None:
    """Its artifact is the build it tried to deploy, not what the site serves.

    A failed or cancelled deploy may or may not have gone live, so the reader asks
    the CDN for a copy younger than the deployment. Here the failed deploy's own
    build is readable and names another directory than the one the CDN serves:
    reading it would date the next build from a deploy the site may not serve.
    """
    _not_a_success(pages, how)
    _with_artifact(pages, _site(edition=_edition_of_site()))
    pages.cdn_answers = lambda clock: (200, NEW.to_json_bytes(), clock.at)
    found = pages.reader().read()
    assert not [call for call in pages.calls if "/artifacts" in call or "/download" in call]
    assert found.data == NEW.to_json_bytes()
    assert found.source.startswith("the CDN")


def test_the_latest_status_counts_in_whatever_order_the_api_lists_them(pages: Pages) -> None:
    pages.deploy()
    # Oldest first: the in_progress status (id 1), then success (id 2).
    pages.statuses.reverse()
    _with_artifact(pages, _site(edition=_edition_of_site()))
    assert pages.reader().read().source == "the artifact of run 7, the live deploy"
    # Two statuses in one second: the higher id is the later one.
    pages.statuses[0]["created_at"] = pages.statuses[1]["created_at"]
    assert pages.reader().read().source == "the artifact of run 7, the live deploy"


def test_only_one_artifact_named_github_pages_is_read(pages: Pages) -> None:
    """Two Pages artifacts, or one of another name: no guess at which the site serves."""
    pages.deploy(at=DEPLOYED_AT - timedelta(hours=2))
    _with_artifact(pages, _site(edition=_edition_of_site()))
    pages.cdn_answers = lambda clock: (200, NEW.to_json_bytes(), clock.at)
    one = pages.artifacts[0]
    for artifacts in ([one, dict(one)], [{**one, "name": "github-pages-preview"}]):
        pages.artifacts = artifacts
        pages.calls = []
        found = pages.reader().read()
        assert "api /download" not in pages.calls
        assert found.source.startswith("the CDN")
        assert "run 7 has no readable github-pages artifact" in found.notes[0]


def test_a_deployment_changed_after_its_run_ended_counts_its_change(pages: Pages) -> None:
    """A cancelled run's deployment updated later: the later of the two times counts."""
    pages.deploy(state="in_progress")
    ended = DEPLOYED_AT + timedelta(minutes=1)
    updated = DEPLOYED_AT + timedelta(minutes=5)
    pages.run = {"status": "completed", "conclusion": "cancelled", "updated_at": _iso(ended)}
    pages.deployments[0]["updated_at"] = _iso(updated)
    pages.clock.at = DEPLOYED_AT + timedelta(minutes=6)
    # Fetched after the run ended and settled, but before the deployment's change settled.
    copy = ended + SETTLE + timedelta(minutes=1)
    assert copy < updated + SETTLE
    pages.cdn_answers = _stale_then_fresh(updated + SETTLE + timedelta(minutes=1), copy)
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    assert pages.cdn_reads() > 1


def test_a_directory_file_larger_than_the_cap_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    meta, points_bytes = _meta(), example_points()
    largest = max(len(meta), len(points_bytes))
    monkeypatch.setattr(deployed_module, "MAX_DIRECTORY_BYTES", largest)
    assert directory_in_artifact(_artifact(_site(meta))).meta == meta
    monkeypatch.setattr(deployed_module, "MAX_DIRECTORY_BYTES", largest - 1)
    with pytest.raises(DeployedEditionError, match="not a file of its size"):
        directory_in_artifact(_artifact(_site(meta)))


def test_index_html_must_be_a_file() -> None:
    files = {name: data for name, data in _site().items() if "index" not in name}
    with pytest.raises(DeployedEditionError, match="not laid out as a Pages build"):
        directory_in_artifact(_artifact(files, directories=("./index.html",)))


def test_a_date_without_a_zone_is_read_as_utc() -> None:
    """RFC 5322 writes an unknown zone as -0000; Python reads that as a naive time."""
    request = httpx.Request("GET", f"{SITE}/data/schools/edition.json")
    headers = {"date": "Tue, 13 Oct 2026 09:05:00 -0000", "age": "60"}
    response = httpx.Response(200, headers=headers, request=request)
    assert fetched_at(response) == datetime(2026, 10, 13, 9, 4, tzinfo=UTC)


def test_a_transport_error_is_retried(pages: Pages) -> None:
    pages.deploy(at=DEPLOYED_AT - timedelta(days=1))
    failures = [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")]

    def flaky(request: httpx.Request) -> httpx.Response:
        if failures:
            raise failures.pop(0)
        return pages.cdn(request)

    pages.cdn_answers = lambda clock: (200, NEW.to_json_bytes(), clock.at)
    reader = pages.reader()
    reader.cdn = httpx.Client(transport=httpx.MockTransport(flaky))
    assert reader.read().data == NEW.to_json_bytes()
    assert pages.clock.slept == [10.0, 10.0]


# The command.


def test_cli_writes_the_edition_or_removes_a_stale_file(
    pages: Pages,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pages.deploy()
    edition = _edition_of_site()
    _with_artifact(pages, _site(edition=edition))
    monkeypatch.setattr(cli_module, "Reader", lambda **_kwargs: pages.reader())
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    out = tmp_path / "edition.json"
    argv = ["directory", "deployed-edition", "--site", SITE, "--out", str(out)]
    assert main([*argv, "--repository", REPO]) == 0
    assert out.read_bytes() == edition
    assert "Deployed edition from the artifact of run 7" in capsys.readouterr().out
    # A deploy from before editions, its artifact gone: none deployed.
    pages.artifacts = []
    pages.tree = {SITE_MARKER}
    pages.cdn_answers = lambda clock: (404, b"", clock.at)
    assert main([*argv, "--repository", REPO]) == 0
    assert not out.exists()
    assert "No schools/edition.json is deployed" in capsys.readouterr().out
    # The recovery flag on such a read says there is nothing to date past.
    assert main([*argv, "--repository", REPO, "--date-past-mismatch"]) == 0
    assert not out.exists()
    printed = capsys.readouterr().out
    assert "--date-past-mismatch: nothing to date past, no edition is deployed" in printed
    assert "names its directory" not in printed
    pages.deploy(state="queued")
    out.write_bytes(json.dumps({"left": "over"}).encode())
    assert main([*argv, "--repository", REPO]) == 1
    assert "error: a deploy is in progress" in capsys.readouterr().err
    assert not out.exists()
    monkeypatch.delenv("GITHUB_TOKEN")
    assert main([*argv, "--repository", REPO]) == 1
    assert "needs GITHUB_TOKEN" in capsys.readouterr().err


def test_cli_gives_the_reader_its_own_clients_and_wait(
    pages: Pages,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The command's real clients: the token goes to the API alone, and redirects are followed.

    GitHub answers an artifact download with a redirect to blob storage on another
    host, which must be followed without the token. The CDN never sees the token.
    """
    real_client = httpx.Client
    sent: list[httpx.Request] = []

    def route(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.host == "blob.example":
            return httpx.Response(200, content=pages.archive)
        if request.url.host != "api.example":
            return pages.cdn(request)
        if request.url.path == "/download":
            return httpx.Response(302, headers={"location": "https://blob.example/a.zip?sig=1"})
        return pages.api(request)

    def client(**kwargs: Any) -> httpx.Client:
        return real_client(**kwargs, transport=httpx.MockTransport(route))

    made: list[dict[str, Any]] = []

    def reader(**kwargs: Any) -> Reader:
        made.append(kwargs)
        return Reader(**kwargs, now=pages.clock.now, sleep=pages.clock.sleep)

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(cli_module, "Reader", reader)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    out = tmp_path / "edition.json"
    argv = [
        *("directory", "deployed-edition", "--site", SITE, "--out", str(out)),
        *("--repository", REPO, "--api-url", "https://api.example"),
    ]
    pages.deploy()
    edition = _edition_of_site()
    _with_artifact(pages, _site(edition=edition))
    assert main(argv) == 0
    assert out.read_bytes() == edition
    assert "Deployed edition from the artifact of run 7" in capsys.readouterr().out
    assert made[-1]["max_wait"] == MAX_WAIT
    (blob,) = [request for request in sent if request.url.host == "blob.example"]
    assert "authorization" not in blob.headers
    assert all(
        request.headers["authorization"] == "Bearer token"
        for request in sent
        if request.url.host == "api.example"
    )
    # Its artifact gone, the CDN is read, without the token.
    sent.clear()
    pages.artifacts = []
    pages.cdn_answers = lambda clock: (200, NEW.to_json_bytes(), clock.at)
    assert main(argv) == 0
    assert out.read_bytes() == NEW.to_json_bytes()
    cdn = [request for request in sent if request.url.host == "snowlight.example"]
    assert cdn
    assert not any("authorization" in request.headers for request in cdn)
    # A shorter wait for a fresh copy, and a failed read prints the reader's notes.
    pages.cdn_answers = lambda _clock: (200, OLD.to_json_bytes(), DEPLOYED_AT)
    capsys.readouterr()
    assert main([*argv, "--max-wait", "60"]) == 1
    assert made[-1]["max_wait"] == timedelta(seconds=60)
    err = capsys.readouterr().err
    assert "  run 7 has no readable github-pages artifact" in err
    assert "  CDN data/schools/edition.json: HTTP 200 (age " in err
    assert "no newer copy came within 0:01:00" in err
    assert not out.exists()


@pytest.mark.parametrize("wait", ["0", "-5", "soon", "inf", "nan", "86400.5", "1e20"])
def test_cli_max_wait_must_be_seconds_above_zero_and_at_most_a_day(
    wait: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["directory", "deployed-edition", "--site", SITE, "--out", str(tmp_path / "e.json")]
    with pytest.raises(SystemExit) as stopped:
        main([*argv, "--max-wait", wait])
    assert stopped.value.code == 2
    assert "not a number of seconds above zero and at most 86400" in capsys.readouterr().err


def test_cli_max_wait_takes_a_whole_day(
    pages: Pages, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[dict[str, Any]] = []

    def reader(**kwargs: Any) -> Reader:
        made.append(kwargs)
        return pages.reader()

    monkeypatch.setattr(cli_module, "Reader", reader)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    pages.cdn_answers = lambda clock: (404, b"", clock.at)
    argv = ["directory", "deployed-edition", "--site", SITE, "--out", str(tmp_path / "e.json")]
    assert main([*argv, "--repository", REPO, "--max-wait", "86400"]) == 0
    assert made[-1]["max_wait"] == timedelta(days=1)


def _cli_clients(monkeypatch: pytest.MonkeyPatch, pages: Pages) -> list[dict[str, Any]]:
    """Record the keyword arguments of each httpx.Client the command makes."""
    real_client = httpx.Client
    made: list[dict[str, Any]] = []

    def client(**kwargs: Any) -> httpx.Client:
        if "transport" in kwargs:  # the test's own clients, in pages.reader()
            return real_client(**kwargs)
        made.append(kwargs)
        return real_client(transport=httpx.MockTransport(pages.cdn))

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(cli_module, "Reader", lambda **_kwargs: pages.reader())
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    return made


def test_cli_verifies_tls_with_the_bundle_in_ssl_cert_file(
    pages: Pages,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """httpx no longer reads SSL_CERT_FILE: the command builds the context from it, for both
    clients, so a proxy's CA bundle is trusted; without it, the default trust store."""
    certifi = pytest.importorskip("certifi")
    bundle = Path(certifi.where())
    made = _cli_clients(monkeypatch, pages)
    pages.cdn_answers = lambda clock: (404, b"", clock.at)
    argv = ["directory", "deployed-edition", "--site", SITE, "--out", str(tmp_path / "e.json")]
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    assert main([*argv, "--repository", REPO]) == 0
    assert len(made) == 2
    certificates = bundle.read_text(encoding="utf-8").count("BEGIN CERTIFICATE")
    assert certificates > 0
    for kwargs in made:
        context = kwargs["verify"]
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname
        assert len(context.get_ca_certs()) == certificates
    made.clear()
    monkeypatch.delenv("SSL_CERT_FILE")
    assert main([*argv, "--repository", REPO]) == 0
    assert [kwargs["verify"] for kwargs in made] == [True, True]
    # A bundle that cannot be read is a one-line error, and nothing is read.
    made.clear()
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing.pem"))
    capsys.readouterr()
    assert main([*argv, "--repository", REPO]) == 1
    assert "error: SSL_CERT_FILE" in capsys.readouterr().err
    assert made == []


def test_cli_date_past_mismatch_dates_past_a_mismatching_edition_and_nothing_else(
    pages: Pages,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The recovery the runbook names, given by hand: only for an edition that names
    another directory, and then an edition that dates the build past both."""
    monkeypatch.setattr(cli_module, "Reader", lambda **_kwargs: pages.reader())
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    out = tmp_path / "edition.json"
    argv = ["directory", "deployed-edition", "--site", SITE, "--out", str(out), "--repository"]
    claimed = OLD.model_copy(update={"generated_on": date(2026, 10, 20)})
    _expired(pages, claimed.to_json_bytes())
    # Without the flag: an error, no file.
    assert main([*argv, REPO]) == 1
    assert "does not name the data/schools/meta." in capsys.readouterr().err
    assert not out.exists()
    # With it: the edition past both.
    assert main([*argv, REPO, "--date-past-mismatch"]) == 0
    written = DirectoryEdition.from_json_bytes(out.read_bytes())
    assert written.generated_on == date(2026, 10, 20)
    assert written.content_sha256 == "0" * 64
    printed = capsys.readouterr().out
    assert "Recovery (--date-past-mismatch)" in printed
    assert "dated 2026-10-20 that no directory matches" in printed
    built = choose_generated_on(NEW.content_sha256, 6, 2, date(2026, 10, 14), written)
    assert built.generated_on == "2026-10-21"
    # Every other failure still fails, and leaves no file.
    pages.cdn_answers = lambda _clock: (200, NEW.to_json_bytes(), DEPLOYED_AT - timedelta(days=3))
    assert main([*argv, REPO, "--date-past-mismatch", "--max-wait", "60"]) == 1
    assert "before the last deploy settled" in capsys.readouterr().err
    assert not out.exists()
    pages.cdn_answers = lambda clock: (200, b"{}", clock.at)
    assert main([*argv, REPO, "--date-past-mismatch"]) == 1
    assert "is not an edition" in capsys.readouterr().err
    assert not out.exists()
    # An edition that names its directory is written as it is, flag or not.
    pages.cdn_answers = lambda clock: (200, NEW.to_json_bytes(), clock.at)
    assert main([*argv, REPO, "--date-past-mismatch"]) == 0
    assert out.read_bytes() == NEW.to_json_bytes()
    assert "the deployed edition names its directory" in capsys.readouterr().out


# The CDN's edition must name the directory the CDN serves the page.


def _expired(pages: Pages, edition: bytes) -> None:
    """A live deploy two days old, its artifact expired: the CDN is read, serving ``edition``."""
    pages.deploy(at=DEPLOYED_AT - timedelta(days=2))
    _with_artifact(pages, _site(NEW_META, edition=edition), expired=True)
    pages.cdn_answers = lambda clock: (200, edition, clock.at)


def test_a_cdn_edition_is_taken_once_it_names_the_pages_directory(pages: Pages) -> None:
    _expired(pages, NEW.to_json_bytes())
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    assert found.source.startswith("the CDN")
    meta_name = _hashed("meta.json", NEW_META)
    # Each file once: the page, its scripts (one imported twice), the directory.
    read = [call.removeprefix(f"cdn {SITE}") for call in pages.calls if call.startswith("cdn")]
    assert sorted(read) == sorted(
        [
            "/data/schools/edition.json",
            "/index.html",
            f"/{ENTRY}",
            "/assets/data-files-Xy98Zw76.js",
            "/assets/AreaPanel-Qr56St78.js",
            f"/data/schools/{meta_name}",
            f"/data/schools/{_hashed('points.bin', example_points())}",
        ]
    )


@pytest.mark.parametrize(
    "claimed",
    [
        pytest.param(OLD, id="other content"),
        pytest.param(NEW.model_copy(update={"generated_on": date(2026, 10, 14)}), id="other date"),
        pytest.param(NEW.model_copy(update={"schools": 7}), id="other count"),
    ],
)
def test_an_edition_that_names_another_directory_is_refused_from_either_source(
    pages: Pages, claimed: DirectoryEdition
) -> None:
    """The live deploy's edition.json names another directory than the one beside it.

    While its artifact can be read, the artifact says so; once it has expired, the
    CDN's copy of the same files says the same. So the refusal lasts as long as that
    deploy is the newest, and never turns into a build dated from the wrong edition.
    """
    pages.deploy()
    _with_artifact(pages, _site(NEW_META, edition=claimed.to_json_bytes()))
    pages.cdn_answers = lambda clock: (200, claimed.to_json_bytes(), clock.at)
    with pytest.raises(deployed_module.EditionMismatchError) as from_artifact:
        pages.reader().read()
    assert "in the artifact of run 7, the live deploy does not name" in str(from_artifact.value)
    assert pages.cdn_reads() == 0
    # A day on, the artifact has expired.
    pages.clock.at += timedelta(days=1)
    pages.artifacts[0]["expired"] = True
    with pytest.raises(deployed_module.EditionMismatchError) as from_cdn:
        pages.reader().read()
    assert "in the CDN, a copy fetched" in str(from_cdn.value)
    for error in (from_artifact.value, from_cdn.value):
        assert (error.claimed, error.made) == (claimed, NEW)
        assert isinstance(error, DeployedEditionError)


def test_the_recovery_edition_dates_any_directory_past_both(pages: Pages) -> None:
    claimed = OLD.model_copy(update={"generated_on": date(2026, 10, 20)})
    _expired(pages, claimed.to_json_bytes())
    with pytest.raises(deployed_module.EditionMismatchError) as refused:
        pages.reader().read()
    past = refused.value.past_both()
    assert past.generated_on == date(2026, 10, 20)
    assert past.content_sha256 == "0" * 64
    assert (past.schools, past.districts) == (NEW.schools, NEW.districts)
    # Whatever the build's content, even the content either one names, a date neither used.
    for digest in (NEW.content_sha256, OLD.content_sha256, "c" * 64):
        for build_day, dated in ((date(2026, 10, 14), "2026-10-21"), (date(2026, 11, 2), None)):
            choice = choose_generated_on(digest, 6, 2, build_day, past)
            assert choice.generated_on == (dated or build_day.isoformat())
    # The deployed meta.json the later one.
    later = NEW.model_copy(update={"generated_on": date(2026, 10, 25)})
    error = deployed_module.EditionMismatchError("x", claimed=claimed, made=later)
    assert error.past_both().generated_on == date(2026, 10, 25)


def test_the_page_is_read_from_a_copy_fetched_after_the_deploy(pages: Pages) -> None:
    """index.html names the directory the page reads, so its copy must be the live one too."""
    pages.deploy(state="failure")
    pages.cdn_answers = lambda clock: (200, NEW.to_json_bytes(), clock.at)
    fresh_from = DEPLOYED_AT + timedelta(minutes=9)
    pages.page_fetched = lambda clock: (
        clock.at if clock.at >= fresh_from else DEPLOYED_AT - timedelta(minutes=1)
    )
    found = pages.reader().read()
    assert found.data == NEW.to_json_bytes()
    pages_read = [call for call in pages.calls if call.endswith("/index.html")]
    assert len(pages_read) > 1
    assert pages.clock.at >= fresh_from
    # A copy of the page that never gets younger than the deploy: an error.
    pages.clock.at = DEPLOYED_AT + timedelta(minutes=3)
    pages.page_fetched = lambda _clock: DEPLOYED_AT - timedelta(minutes=1)
    with pytest.raises(DeployedEditionError, match=r"copy of .*/index.html is from 08:59:00Z"):
        pages.reader().read()


def test_a_site_under_a_base_path_is_read_there(pages: Pages) -> None:
    pages.cdn_site = _cdn_site(base="/site/")
    _expired(pages, NEW.to_json_bytes())
    reader = pages.reader()
    reader.site_url = "https://snowlight.example/site"
    assert reader.read().data == NEW.to_json_bytes()
    assert f"cdn https://snowlight.example/site/{ENTRY}" in pages.calls


def _replace_in(path: str, old: bytes, new: bytes) -> Callable[[dict[str, bytes]], None]:
    def change(site: dict[str, bytes]) -> None:
        assert old in site[path]
        site[path] = site[path].replace(old, new)

    return change


def _drop(path: str) -> Callable[[dict[str, bytes]], None]:
    def change(site: dict[str, bytes]) -> None:
        del site[path]

    return change


def _list_also(name: str) -> Callable[[dict[str, bytes]], None]:
    def change(site: dict[str, bytes]) -> None:
        site["/assets/AreaPanel-Qr56St78.js"] += b'["' + name.encode() + b'"]'

    return change


def _misnamed_meta(site: dict[str, bytes]) -> None:
    (path,) = [path for path in site if "/meta." in path]
    site[path] = OLD_META


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (_replace_in("/index.html", b'type="module" ', b""), "names no module script"),
        (_drop("/assets/data-files-Xy98Zw76.js"), "data-files-Xy98Zw76.js: HTTP 404"),
        (
            _replace_in("/assets/data-files-Xy98Zw76.js", b"`schools/meta.", b"`schools/mota."),
            r"does not name one .* it names \['points\.",
        ),
        (_list_also("schools/meta.0123456789.json"), "does not name one"),
        (_list_also("schools/points.0123456789.bin"), "does not name one"),
        (_misnamed_meta, "on the CDN is not named by its bytes"),
        (
            _replace_in("/index.html", b'src="/assets', b'src="https://elsewhere.example/assets'),
            "is not on the site",
        ),
        (
            _replace_in("/index.html", b'src="/assets', b'src="http://snowlight.example/assets'),
            "is not on the site",
        ),
    ],
)
def test_a_page_that_does_not_name_one_directory_is_an_error(
    pages: Pages, change: Callable[[dict[str, bytes]], None], problem: str
) -> None:
    _expired(pages, NEW.to_json_bytes())
    change(pages.cdn_site)
    with pytest.raises(DeployedEditionError, match=problem):
        pages.reader().read()


def test_the_page_must_be_a_200(pages: Pages) -> None:
    _expired(pages, NEW.to_json_bytes())
    del pages.cdn_site["/index.html"]
    with pytest.raises(DeployedEditionError, match=r"index.html: HTTP 404"):
        pages.reader().read()


def test_the_entry_may_name_its_type_after_its_source(pages: Pages) -> None:
    _expired(pages, NEW.to_json_bytes())
    pages.cdn_site["/index.html"] = f"<script src='/{ENTRY}' TYPE='module'></script>".encode()
    assert pages.reader().read().data == NEW.to_json_bytes()


@pytest.mark.parametrize(
    ("cap", "size", "problem"),
    [
        ("MAX_PAGE_BYTES", lambda site: len(site["/index.html"]), "index.html is larger than"),
        (
            "MAX_SCRIPT_BYTES",
            lambda site: max(len(data) for path, data in site.items() if path.endswith(".js")),
            "is larger than",
        ),
        ("MAX_SCRIPTS", lambda _site: 3, "loads more than 2 scripts"),
        (
            "MAX_DIRECTORY_BYTES",
            lambda site: max(len(data) for path, data in site.items() if "/data/" in path),
            "is larger than",
        ),
    ],
)
def test_the_pages_files_are_capped(
    pages: Pages,
    monkeypatch: pytest.MonkeyPatch,
    cap: str,
    size: Callable[[dict[str, bytes]], int],
    problem: str,
) -> None:
    _expired(pages, NEW.to_json_bytes())
    limit = size(pages.cdn_site)
    monkeypatch.setattr(deployed_module, cap, limit)
    assert pages.reader().read().data == NEW.to_json_bytes()
    monkeypatch.setattr(deployed_module, cap, limit - 1)
    with pytest.raises(DeployedEditionError, match=problem):
        pages.reader().read()


def test_a_page_redirected_off_the_site_is_an_error(pages: Pages) -> None:
    _expired(pages, NEW.to_json_bytes())
    real = pages.cdn

    def moved(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/index.html":
            return httpx.Response(302, headers={"location": "https://elsewhere.example/"})
        return real(request)

    reader = pages.reader()
    reader.cdn = httpx.Client(transport=httpx.MockTransport(moved), follow_redirects=True)
    with pytest.raises(DeployedEditionError, match="redirected off HTTPS or off the site"):
        reader.read()

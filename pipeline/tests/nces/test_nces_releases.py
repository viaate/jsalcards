"""The weekly NCES release check, against mocked NCES and GitHub answers."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from snowlight.cli import main
from snowlight.directory.config import load_config
from snowlight.places.pins import load_places_pins
from snowlight.sources.nces import cli as nces_cli
from snowlight.sources.nces.releases import (
    CCD_FILES_URL,
    CCD_LOOKUP_URL,
    ISSUE_TITLE,
    USER_AGENT,
    Finding,
    IssueError,
    Verdict,
    check_ccd,
    file_issue,
    issue_body,
    issue_urls,
    make_client,
    probe_file,
    probe_targets,
)

NEXT = "https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PUBLICSCH_2526.zip"
LANDING = "https://nces.ed.gov/programs/edge/home"
ZIP = b"PK\x03\x04"
MAINTENANCE = b"<html><body>NCES is down for maintenance</body></html>"
CCD_NEW = "https://nces.ed.gov/ccd/Data/zip/ccd_sch_029_2526_w_0a_050626.zip"

type Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _answer(status: int, body: bytes = b"", kind: str = "") -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Range"] == "bytes=0-3"
        headers = {"Content-Type": kind} if kind else {}
        return httpx.Response(status, content=body, headers=headers)

    return handler


@pytest.mark.parametrize(
    ("handler", "verdict", "detail"),
    [
        (_answer(206, ZIP, "application/x-zip-compressed"), Verdict.PUBLISHED, "a zip"),
        (_answer(200, ZIP + b"rest of the file"), Verdict.PUBLISHED, "HTTP 200"),
        (_answer(200, MAINTENANCE, "text/html"), Verdict.NOT_PUBLISHED, "a web page"),
        (_answer(206, ZIP, "text/html; charset=utf-8"), Verdict.NOT_PUBLISHED, "a web page"),
        (_answer(404, b"Not Found", "text/html"), Verdict.NOT_PUBLISHED, "HTTP 404"),
        (_answer(410), Verdict.NOT_PUBLISHED, "HTTP 410"),
        (_answer(403), Verdict.UNKNOWN, "HTTP 403"),
        (_answer(503), Verdict.UNKNOWN, "HTTP 503"),
    ],
)
def test_only_a_zip_is_published(handler: Handler, verdict: Verdict, detail: str) -> None:
    finding = probe_file(_client(handler), "public_school_geocodes", NEXT)
    assert finding.verdict is verdict
    assert detail in finding.detail


def test_a_redirect_to_a_landing_page_is_not_published() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == NEXT:
            return httpx.Response(302, headers={"Location": LANDING})
        return httpx.Response(
            200, content=b"<html>EDGE home</html>", headers={"Content-Type": "text/html"}
        )

    finding = probe_file(_client(handler), "public_school_geocodes", NEXT)
    assert finding.verdict is Verdict.NOT_PUBLISHED
    assert finding.detail == "a web page (text/html) after a redirect"


def test_a_redirect_to_the_file_is_published() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == NEXT:
            return httpx.Response(302, headers={"Location": NEXT + "?cdn=1"})
        return httpx.Response(206, content=ZIP)

    finding = probe_file(_client(handler), "public_school_geocodes", NEXT)
    assert finding.verdict is Verdict.PUBLISHED


def test_a_timeout_is_unknown_never_not_published() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    finding = probe_file(_client(handler), "public_school_geocodes", NEXT)
    assert finding.verdict is Verdict.UNKNOWN
    assert finding.detail == "timed out"

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert probe_file(_client(refused), "x", NEXT).verdict is Verdict.UNKNOWN


def test_the_probes_ask_for_the_next_two_school_years() -> None:
    targets = probe_targets(load_config(), load_places_pins())
    base = "https://nces.ed.gov/programs/edge/data/"
    assert targets == [
        ("public_school_geocodes", base + "EDGE_GEOCODE_PUBLICSCH_2526.zip"),
        ("public_school_geocodes", base + "EDGE_GEOCODE_PUBLICSCH_2627.zip"),
        ("public_lea_geocodes", base + "EDGE_GEOCODE_PUBLICLEA_2526.zip"),
        ("public_lea_geocodes", base + "EDGE_GEOCODE_PUBLICLEA_2627.zip"),
        # The newest pinned private release is 2023-24; 2024-25 is not pinned yet.
        ("private_school_geocodes", base + "EDGE_GEOCODE_PRIVATESCH_2425.zip"),
        ("private_school_geocodes", base + "EDGE_GEOCODE_PRIVATESCH_2526.zip"),
        ("pss", "https://nces.ed.gov/surveys/pss/zip/pss2425_pu_csv.zip"),
        ("pss", "https://nces.ed.gov/surveys/pss/zip/pss2526_pu_csv.zip"),
        ("grf", base + "GRF26.zip"),
        ("grf", base + "GRF27.zip"),
    ]


def _ccd_server(files: dict[int, list[str]], lookup: object | None = None) -> httpx.Client:
    years = [
        {"schoolYearShort": None, "id": 0, "name": "Select a Year"},
        {"schoolYearShort": "2025", "id": 40, "name": "2025 - 2026"},
        {"schoolYearShort": "2024", "id": 39, "name": "2024 - 2025"},
        {"schoolYearShort": "2023", "id": 38, "name": "2023 - 2024"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == CCD_LOOKUP_URL:
            return httpx.Response(
                200, json=lookup if lookup is not None else {"schoolYears": years}
            )
        for year_id, urls in files.items():
            if url == CCD_FILES_URL.format(year_id=year_id):
                groups = [{"titleGroups": [{"files": [{"fileURL": u} for u in urls]}]}]
                return httpx.Response(200, json={"selectionGroupModels": groups})
        assert year_id != 38  # the years before the pins are never asked for
        return httpx.Response(404)

    return _client(handler)


def test_ccd_reports_later_years_and_versions_only() -> None:
    files = {
        39: [
            "https://nces.ed.gov/ccd/Data/zip/ccd_sch_029_2425_w_1a_073025.zip",  # the pin
            "https://nces.ed.gov/ccd/Data/zip/ccd_sch_052_2425_l_1b_101525.zip",  # newer version
            "https://nces.ed.gov/ccd/Data/zip/ccd_sch_033_2425_l_2a_073025.zip",  # not pinned
        ],
        40: [CCD_NEW, "https://nces.ed.gov/ccd/Data/zip/ccd_lea_029_2526_w_0a_050626.zip"],
    }
    findings = check_ccd(_ccd_server(files), load_config())
    assert [(f.family, f.url) for f in findings] == [
        ("ccd_directory", CCD_NEW),
        ("ccd_membership", "https://nces.ed.gov/ccd/Data/zip/ccd_sch_052_2425_l_1b_101525.zip"),
    ]
    assert findings[0].detail == "listed: school year 2025-26, version 0a"
    assert check_ccd(_ccd_server({39: [], 40: []}), load_config()) == []


def test_a_ccd_list_that_is_not_json_is_unknown() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=MAINTENANCE, headers={"Content-Type": "text/html"})

    (finding,) = check_ccd(_client(handler), load_config())
    assert finding.verdict is Verdict.UNKNOWN
    assert "not JSON (text/html)" in finding.detail
    (shapeless,) = check_ccd(_ccd_server({}, lookup=["no", "years"]), load_config())
    assert shapeless.verdict is Verdict.UNKNOWN


class GitHub:
    """The issues API of one repository."""

    def __init__(self, issues: list[dict[str, object]]) -> None:
        self.issues = issues
        self.writes: list[tuple[str, str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=self.issues)
        body = json.loads(request.content)
        self.writes.append((request.method, request.url.path, body))
        return httpx.Response(201, json={"number": 7, **body})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def test_the_issue_is_opened_once_then_updated() -> None:
    body = "the list\n"
    github = GitHub([{"number": 3, "title": ISSUE_TITLE, "body": "x", "pull_request": {}}])
    assert file_issue(github.client(), "o/r", body) == "opened issue #7"
    assert github.writes == [("POST", "/repos/o/r/issues", {"title": ISSUE_TITLE, "body": body})]
    github = GitHub([{"number": 5, "title": ISSUE_TITLE, "body": "older list\n"}])
    assert file_issue(github.client(), "o/r", body) == "updated issue #5"
    assert github.writes == [("PATCH", "/repos/o/r/issues/5", {"body": body})]
    github = GitHub([{"number": 5, "title": ISSUE_TITLE, "body": body}])
    assert file_issue(github.client(), "o/r", body) == "issue #5 already lists these files"
    assert github.writes == []


def _listing(*urls: str) -> str:
    return issue_body([Finding("x", url, Verdict.PUBLISHED, "listed") for url in urls]) or ""


def test_a_closed_issue_reopens_only_for_files_it_did_not_list() -> None:
    old, new = "https://h/a.zip", "https://h/b.zip"
    closed = {"number": 4, "title": ISSUE_TITLE, "body": _listing(old), "state": "closed"}
    assert issue_urls(_listing(old, new)) == {old, new}
    # The same file, reworded or alone: the owner's close stands, week after week.
    github = GitHub([closed])
    result = file_issue(github.client(), "o/r", _listing(old).replace("listed", "seen"))
    assert result == "issue #4 was closed with these files listed; not reopened"
    assert github.writes == []
    # A file the closed issue never listed reopens it; no second issue.
    github = GitHub([closed, {**closed, "number": 2, "body": ""}])
    body = _listing(old, new)
    assert file_issue(github.client(), "o/r", body).startswith("reopened issue #4")
    assert github.writes == [("PATCH", "/repos/o/r/issues/4", {"body": body, "state": "open"})]
    # An open issue wins over closed ones.
    github = GitHub([closed, {**closed, "number": 9, "state": "open", "body": body}])
    assert file_issue(github.client(), "o/r", body) == "issue #9 already lists these files"


def test_the_issue_search_covers_closed_issues() -> None:
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return httpx.Response(403)
        asked.append(str(request.url.params.get("state")))
        return httpx.Response(200, json=[])

    with pytest.raises(IssueError):
        file_issue(httpx.Client(transport=httpx.MockTransport(handler)), "o/r", "x\n")
    assert asked == ["all"]


def test_nothing_new_is_no_issue() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    finding = probe_file(_client(handler), "pss", NEXT)
    assert issue_body([finding]) is None


def test_cli_files_the_issue_only_when_something_is_published(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    published: set[str] = set()
    asked: list[str] = []

    def nces(request: httpx.Request) -> httpx.Response:
        asked.append(request.headers["User-Agent"])
        url = str(request.url)
        if url == CCD_LOOKUP_URL:
            return httpx.Response(200, json={"schoolYears": []})
        if url in published:
            return httpx.Response(206, content=ZIP)
        return httpx.Response(404)

    github = GitHub([])
    monkeypatch.setattr(nces_cli, "make_client", lambda: _client(nces))
    monkeypatch.setattr(nces_cli, "github_client", lambda _token: github.client())
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    report = tmp_path / "report.json"
    assert main(["nces", "check", "--issue", "--report", str(report)]) == 0
    assert "nothing newer than the pins is published" in capsys.readouterr().out
    assert github.writes == []
    assert {r["verdict"] for r in json.loads(report.read_text(encoding="utf-8"))} == {
        "not published"
    }
    assert asked
    with make_client() as polite:
        assert polite.headers["User-Agent"] == USER_AGENT
    assert "snowlightmap.com" in USER_AGENT
    published.add("https://nces.ed.gov/programs/edge/data/GRF26.zip")
    assert main(["nces", "check", "--issue"]) == 0
    assert "opened issue #7" in capsys.readouterr().out
    (write,) = github.writes
    assert "GRF26.zip" in str(write[2])
    monkeypatch.delenv("GITHUB_TOKEN")
    assert main(["nces", "check", "--issue"]) == 1
    assert main(["nces", "check"]) == 0


def test_a_blind_check_fails_the_job(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every probe UNKNOWN (NCES blocks the runner): exit 1, so the check never goes quiet."""

    def blocked(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    monkeypatch.setattr(nces_cli, "make_client", lambda: _client(blocked))
    assert main(["nces", "check"]) == 1
    assert "::error::NCES release check could not tell for any" in capsys.readouterr().out

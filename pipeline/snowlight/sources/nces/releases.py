"""The weekly NCES release check: has NCES published files newer than the pins?

For each pinned NCES file family it asks NCES, read only and politely, about the
next two school years (two, because the private school survey is biennial):

* EDGE geocode, Private School Survey and GRF files have predictable names, so each
  next name gets one small ranged GET. Only a zip answer counts as published: a 404
  or 410, a web page served with HTTP 200 (NCES's maintenance page), and a redirect
  to a landing page all mean "not published".
* CCD file names carry their release date, so CCD files are looked up in the JSON
  list behind NCES's CCD data files page instead: a pinned CCD file has a newer
  release when that list names the same file for a later school year, or a later
  version for the same year.

An answer that settles nothing (a timeout, a refusal, a server error, a list that
is not JSON) is "unknown", reported as such and never as "not published". The
check changes no pin and no deploy: it reports, and ``--issue`` opens or updates
one GitHub issue, :data:`ISSUE_TITLE`, when something new is published.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum

import httpx

from snowlight import __version__
from snowlight.directory.config import DirectoryConfig
from snowlight.places.grf import grf_release
from snowlight.places.pins import PlacesPins

USER_AGENT = f"snowlight-release-check/{__version__} (+https://snowlightmap.com)"
ISSUE_TITLE = "New NCES release available"
_ISSUE_LINE = re.compile(r"^- [^:\n]+: (\S+) \(", re.MULTILINE)
CCD_LOOKUP_URL = "https://nces.ed.gov/ccd/datatables/api/Lookup/"
CCD_FILES_URL = "https://nces.ed.gov/ccd/datatables/api/File/0/0/{year_id}/0/0/0"
_ZIP_MAGIC = b"PK\x03\x04"
_YEARS_AHEAD = 2
_MISSING = frozenset({404, 410})
_SCHOOL_YEAR = re.compile(r"(?<![0-9])(\d{2})(\d{2})(?=[_.])")
_GRF = re.compile(r"GRF(\d{2})\.zip$")
_CCD = re.compile(r"ccd_sch_(\d{3})_(\d{2})(\d{2})_[a-z]_(\d)([a-z])_\d{6}\.zip$")


class Verdict(StrEnum):
    """What NCES's answer says about a file."""

    PUBLISHED = "published"
    NOT_PUBLISHED = "not published"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Finding:
    """One file NCES was asked about, or one CCD list that was read."""

    family: str
    url: str
    verdict: Verdict
    detail: str


def make_client(timeout: float = 30.0) -> httpx.Client:
    """An HTTPS client with the check's User-Agent that follows redirects."""
    return httpx.Client(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def _next_school_years(url: str) -> list[str]:
    """``url`` with its school year (``2425``) moved one and two years on."""
    name = url.rsplit("/", 1)[1]
    matches = [m for m in _SCHOOL_YEAR.finditer(name) if int(m.group(2)) == int(m.group(1)) + 1]
    if len(matches) != 1:
        return []
    match = matches[0]
    start = int(match.group(1))
    head = url[: len(url) - len(name)]
    return [
        head
        + name[: match.start()]
        + f"{(start + n) % 100:02d}{(start + n + 1) % 100:02d}"
        + name[match.end() :]
        for n in range(1, _YEARS_AHEAD + 1)
    ]


def _newest_pinned(config: DirectoryConfig) -> Iterator[tuple[str, str]]:
    for key, source in config.sources.items():
        pinned = [c.url for c in source.candidates if c.sha256 is not None]
        if pinned:
            yield key, pinned[0]


def probe_targets(config: DirectoryConfig, places: PlacesPins) -> list[tuple[str, str]]:
    """``(family, url)`` of every predictable next-year file of the pinned families."""
    targets: list[tuple[str, str]] = []
    for key, url in _newest_pinned(config):
        if _CCD.search(url) is None:
            targets.extend((key, next_url) for next_url in _next_school_years(url))
    for n in range(1, _YEARS_AHEAD + 1):
        targets.append(("grf", grf_release(places.grf_year + n).url))
    return targets


def ccd_pins(config: DirectoryConfig) -> dict[str, tuple[str, int, tuple[int, str]]]:
    """Each pinned CCD file: ``{number: (family, first year, (version, letter))}``."""
    pins: dict[str, tuple[str, int, tuple[int, str]]] = {}
    for key, url in _newest_pinned(config):
        match = _CCD.search(url)
        if match is not None:
            year = 2000 + int(match.group(2))
            pins[match.group(1)] = (key, year, (int(match.group(4)), match.group(5)))
    return pins


def probe_file(client: httpx.Client, family: str, url: str) -> Finding:
    """Ask for the first bytes of ``url``; only a zip is published."""
    try:
        with client.stream("GET", url, headers={"Range": "bytes=0-3"}) as response:
            status = response.status_code
            kind = response.headers.get("Content-Type", "")
            head = b""
            if status in {200, 206}:
                for chunk in response.iter_bytes():
                    head += chunk
                    if len(head) >= len(_ZIP_MAGIC):
                        break
            moved = " after a redirect" if response.history else ""
    except httpx.TimeoutException:
        return Finding(family, url, Verdict.UNKNOWN, "timed out")
    except httpx.TransportError as error:
        return Finding(family, url, Verdict.UNKNOWN, f"no answer ({type(error).__name__})")
    if status in _MISSING:
        return Finding(family, url, Verdict.NOT_PUBLISHED, f"HTTP {status}{moved}")
    if status not in {200, 206}:
        return Finding(family, url, Verdict.UNKNOWN, f"HTTP {status}{moved}")
    if head[: len(_ZIP_MAGIC)] != _ZIP_MAGIC or "html" in kind.lower():
        shown = kind or "no content type"
        return Finding(family, url, Verdict.NOT_PUBLISHED, f"a web page ({shown}){moved}")
    return Finding(family, url, Verdict.PUBLISHED, f"HTTP {status}, a zip{moved}")


def _get_json(client: httpx.Client, url: str) -> object:
    """The JSON at ``url``.

    Raises:
        ValueError: with what came back instead.
    """
    try:
        response = client.get(url)
    except httpx.TimeoutException:
        raise ValueError("timed out") from None
    except httpx.TransportError as error:
        raise ValueError(f"no answer ({type(error).__name__})") from None
    if response.status_code != httpx.codes.OK:
        raise ValueError(f"HTTP {response.status_code}")
    try:
        return json.loads(response.content)
    except ValueError:
        kind = response.headers.get("Content-Type") or "no content type"
        raise ValueError(f"not JSON ({kind})") from None


def _file_urls(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "fileURL" and isinstance(item, str):
                yield item
            else:
                yield from _file_urls(item)
    elif isinstance(value, list):
        for item in value:
            yield from _file_urls(item)


def _ccd_year_ids(lookup: object, first_year: int) -> list[int]:
    if not isinstance(lookup, dict):
        raise ValueError("the CCD lookup has no school years")
    years = lookup.get("schoolYears")
    if not isinstance(years, list):
        raise ValueError("the CCD lookup has no school years")
    ids: list[int] = []
    for year in years:
        if not isinstance(year, dict):
            continue
        short, year_id = year.get("schoolYearShort"), year.get("id")
        known = isinstance(short, str) and short.isdigit() and isinstance(year_id, int)
        if known and int(str(short)) >= first_year:
            ids.append(int(str(year_id)))
    return sorted(ids)


def check_ccd(client: httpx.Client, config: DirectoryConfig) -> list[Finding]:
    """The CCD files NCES lists that are newer than the pinned ones."""
    pins = ccd_pins(config)
    if not pins:
        return []
    first_year = min(year for _family, year, _version in pins.values())
    try:
        year_ids = _ccd_year_ids(_get_json(client, CCD_LOOKUP_URL), first_year)
        listed: set[str] = set()
        for year_id in year_ids:
            listed.update(_file_urls(_get_json(client, CCD_FILES_URL.format(year_id=year_id))))
    except ValueError as error:
        return [Finding("ccd", CCD_LOOKUP_URL, Verdict.UNKNOWN, f"the CCD file list: {error}")]
    findings: list[Finding] = []
    for url in sorted(listed):
        match = _CCD.search(url)
        if match is None or match.group(1) not in pins:
            continue
        family, pinned_year, pinned_version = pins[match.group(1)]
        year = 2000 + int(match.group(2))
        version = (int(match.group(4)), match.group(5))
        if (year, version) > (pinned_year, pinned_version):
            school_year = f"{year}-{(year + 1) % 100:02d}"
            detail = f"listed: school year {school_year}, version {version[0]}{version[1]}"
            findings.append(Finding(family, url, Verdict.PUBLISHED, detail))
    return findings


def check(client: httpx.Client, config: DirectoryConfig, places: PlacesPins) -> list[Finding]:
    """Every finding: the predictable files probed, then the CCD list."""
    findings = [probe_file(client, family, url) for family, url in probe_targets(config, places)]
    return findings + check_ccd(client, config)


def issue_body(findings: list[Finding]) -> str | None:
    """The issue text listing the published files, or ``None`` when there are none."""
    new = [f for f in findings if f.verdict is Verdict.PUBLISHED]
    if not new:
        return None
    lines = ["NCES has published files newer than the ones the site is built from:", ""]
    lines += [f"- {f.family}: {f.url} ({f.detail})" for f in new]
    lines += [
        "",
        "Nothing changes until a reviewer pins a new file in pipeline/config/directory.yaml "
        'or pipeline/config/places.yaml: docs/deployed-edition.md, "Bumping a pinned source '
        'file". The weekly check (.github/workflows/nces-check.yml) updates this issue and '
        "never opens a second one.",
    ]
    return "\n".join(lines) + "\n"


class IssueError(RuntimeError):
    """The GitHub issue could not be read or written."""


def _github(client: httpx.Client, method: str, url: str, body: object = None) -> httpx.Response:
    response = client.request(method, url, json=body)
    if response.status_code >= httpx.codes.BAD_REQUEST:
        raise IssueError(f"{method} {url}: HTTP {response.status_code}")
    return response


def issue_urls(body: str) -> set[str]:
    """The file URLs an issue body from :func:`issue_body` lists."""
    return {match.group(1) for match in _ISSUE_LINE.finditer(body)}


def _our_issues(client: httpx.Client, api: str) -> list[dict[str, object]]:
    """Every issue (open or closed, never a pull request) titled :data:`ISSUE_TITLE`."""
    ours: list[dict[str, object]] = []
    for page in range(1, 11):
        issues = _github(client, "GET", f"{api}?state=all&per_page=100&page={page}").json()
        if not isinstance(issues, list):
            raise IssueError("the issue list is not a list")
        ours += [
            issue
            for issue in issues
            if isinstance(issue, dict)
            and issue.get("title") == ISSUE_TITLE
            and "pull_request" not in issue
        ]
        if len(issues) < 100:  # noqa: PLR2004 - one full page
            break
    return ours


def _number(issue: dict[str, object]) -> int:
    number = issue.get("number")
    return number if isinstance(number, int) else 0


def file_issue(client: httpx.Client, repository: str, body: str) -> str:
    """Open the issue, or update the open one; never a second. Returns what was done.

    A closed issue (the owner dismissed it, or bumped the pins) is reopened only when
    the check finds a file it did not list; the same files never reopen it.
    """
    api = f"https://api.github.com/repos/{repository}/issues"
    ours = _our_issues(client, api)
    open_issues = [issue for issue in ours if issue.get("state", "open") == "open"]
    if open_issues:
        found = max(open_issues, key=_number)
        number = _number(found)
        if found.get("body") == body:
            return f"issue #{number} already lists these files"
        _github(client, "PATCH", f"{api}/{number}", {"body": body})
        return f"updated issue #{number}"
    if ours:
        closed = max(ours, key=_number)
        number = _number(closed)
        listed = closed.get("body")
        if issue_urls(body) <= issue_urls(listed if isinstance(listed, str) else ""):
            return f"issue #{number} was closed with these files listed; not reopened"
        _github(client, "PATCH", f"{api}/{number}", {"body": body, "state": "open"})
        return f"reopened issue #{number}: NCES published files it did not list"
    created = _github(client, "POST", api, {"title": ISSUE_TITLE, "body": body}).json()
    return f"opened issue #{created.get('number')}"

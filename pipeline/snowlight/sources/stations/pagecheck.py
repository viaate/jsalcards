"""Page checks: which list file each station's closings page loads today.

A Gray closings page rarely holds its list: an Arc page's script fetches the
station's GSync export (sometimes a sister station's), and some pages frame a
NewsTicker or BTI file on ``webpubcontent.gray.tv`` or a station ``ftp2`` host, or
load a NewsTicker XML file. The live poller must read the file the page shows, not
an export the station stopped writing years ago, so each station's ``data_url`` is
set from a check of the page in a real browser:

1. ``snowlight stations pagecheck targets`` prints, for every active station with a
   closings page, ``{"id", "urls": [page_url], "user_agent"}``;
2. ``pagecheck.cjs`` (next to this module) opens each page in headless Chromium with
   the project's User-Agent and records every request, response and frame;
3. ``snowlight stations pagecheck apply DIR`` reads those records and, for each
   station whose page loaded a list file (:data:`LIST_FILE`, answering 200), sets
   ``data_url`` to that file (a framed or script-loaded file before an S3 export,
   since the export is then not what the page shows), records the check as the
   station's ``page_check`` and the file as a list file and archive URL. A station
   whose page loaded no list file, or could not be opened, is reported for review
   and left unchanged: whether it has no list, or shares a sister station's page,
   is a judgment its evidence must record.

The page's own requests decide; nothing is inferred from a page's markup.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from snowlight.sources.stations.http import USER_AGENT
from snowlight.sources.stations.registry import (
    PageCheck,
    PlatformFile,
    Registry,
    Station,
    StationStatus,
)

EXPORT = re.compile(
    r"^https://s3\.amazonaws\.com/grayfilestore-[a-z0-9]+/closingsData/closings_[A-Z0-9]+\.json$"
)
LIST_FILE = re.compile(
    r"^https?://(?:"
    r"s3\.amazonaws\.com/grayfilestore-[a-z0-9]+/closingsData/closings_[A-Z0-9]+\.json"
    r"|webpubcontent\.gray\.tv/(?!gray/)[a-z0-9]+/[^?]+\.(?:html?|xml)"
    r"|www\.[a-z0-9.-]+/app/closings/closings\.xml"
    r"|ftp2\.[a-z0-9.-]+/[^?]+\.(?:html?|xml)"
    r")$",
    re.IGNORECASE,
)
"""The closings list files a Gray page has been seen to load (without their query)."""
CLOSINGS_PAGE = re.compile(r"/weather/closings|closings-and-delays|closings-live", re.IGNORECASE)
METHOD = (
    "Opened in headless Chromium with the project's User-Agent by pagecheck.cjs; images, "
    "media and fonts not loaded; waited 12 s, scrolled to the end and waited 5 s more, "
    "recording every request and response. loads: the closings list files the page "
    "requested that answered 200, without the cache-busting query the page adds."
)
MAX_SHOWS = 300


class PageCheckError(ValueError):
    """A page-check record is not in the shape pagecheck.cjs writes."""


def strip_query(url: str) -> str:
    """Return ``url`` without its query and fragment."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def targets(registry: Registry, platforms: Iterable[str] = ("gray",)) -> list[dict[str, Any]]:
    """Return the pages to check: every active station of ``platforms`` with a page."""
    wanted = set(platforms)
    return [
        {"id": station.id, "urls": [station.page_url], "user_agent": USER_AGENT}
        for station in registry.active()
        if station.platform in wanted and station.page_url
    ]


def read_pages(folder: Path) -> dict[str, list[dict[str, Any]]]:
    """Read ``folder/pages/*.json``: each station's page records (a list, or one record)."""
    pages: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((folder / "pages").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data if isinstance(data, list) else [data]
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str):
                raise PageCheckError(f"{path.name}: a record has no station id")
            pages.setdefault(record["id"], []).append(record)
    return pages


@dataclass(frozen=True, slots=True)
class Decision:
    """What one station's page check shows."""

    station_id: str
    loads: tuple[str, ...]
    data_url: str | None
    loaded_by: str | None
    """``frame`` (a document the page framed) or ``script`` (fetched by script)."""
    check: PageCheck | None
    note: str


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _time(text: str) -> datetime:
    moment = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    return moment.replace(microsecond=0)


def _shows(record: Mapping[str, Any], loads: Sequence[str]) -> str:
    frames = [f for f in record.get("frames", []) if strip_query(str(f.get("url"))) in loads]
    if frames:
        text = _clean(str(frames[0].get("text", "")))
        return f"The framed list: {text}"[:MAX_SHOWS] if text else "The framed list, blank."
    main = [f for f in record.get("frames", []) if f.get("url") == record.get("final_url")]
    text = _clean(str(main[0].get("text", ""))) if main else ""
    for pattern in (
        r"Types All States All (.{0,240}?)(?: Closings Admin Help| U\.S\. Privacy|$)",
        r"((?:No|There are no) (?:active )?closings[^.]{0,80}\.)",
    ):
        found = re.search(pattern, text)
        if found:
            return f"The page's closings area: {found.group(1).strip()}"[:MAX_SHOWS]
    return f"The page's text began: {text[:200]}" if text else "The page showed no text."


def _loaded(record: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return (list file URL, resource type) for each list file that answered 200."""
    found: dict[str, str] = {}
    for response in record.get("responses", []):
        url = strip_query(str(response.get("url", "")))
        if response.get("status") == 200 and LIST_FILE.match(url) and url not in found:  # noqa: PLR2004
            found[url] = str(response.get("type"))
    return list(found.items())


def decide(station: Station, records: Sequence[Mapping[str, Any]]) -> Decision:
    """Read one station's page records: the list file its closings page loads, if any."""
    opened = [
        r
        for r in records
        if not r.get("error") and CLOSINGS_PAGE.search(str(r.get("final_url") or ""))
    ]
    if not opened:
        return Decision(station.id, (), None, None, None, "no closings page could be opened")
    record = opened[-1]
    loaded = _loaded(record)
    loads = tuple(url for url, _type in loaded)
    final = str(record["final_url"])
    method = METHOD
    if strip_query(final) != strip_query(str(record["url"])):
        method = f"Opened {record['url']}, which redirected to {final}. {METHOD}"
    check = PageCheck(
        checked_at=_time(str(record["started"])),
        page=final,
        loads=loads,
        shows=_shows(record, loads) or "The page showed no text.",
        method=method,
    )
    if not loads:
        return Decision(station.id, (), None, None, check, "the page loaded no list file")
    others = [(url, kind) for url, kind in loaded if not EXPORT.match(url)]
    url, kind = others[0] if others else loaded[0]
    loaded_by = "frame" if kind == "document" else "script"
    return Decision(station.id, loads, url, loaded_by, check, "loads")


def apply(content: PlatformFile, decisions: Mapping[str, Decision]) -> PlatformFile:
    """Set ``data_url`` and ``page_check`` from each decision that found a list file."""
    stations = []
    for station in content.stations:
        decision = decisions.get(station.id)
        if (
            decision is None
            or decision.data_url is None
            or decision.check is None
            or station.status is not StationStatus.ACTIVE
        ):
            stations.append(station.model_dump(mode="json"))
            continue
        data = station.model_dump(mode="json")
        if station.export_url is None and station.data_url and EXPORT.match(station.data_url):
            data["export_url"] = station.data_url  # kept for the archive reader
            if station.data_url not in data["archive_urls"]:
                data["archive_urls"].append(station.data_url)
        data["data_url"] = decision.data_url
        data["page_check"] = decision.check.model_dump(mode="json")
        if not EXPORT.match(decision.data_url):
            if decision.data_url not in data["archive_urls"]:
                data["archive_urls"].append(decision.data_url)
            if decision.data_url not in {item["url"] for item in data["list_files"]}:
                verb = "frames" if decision.loaded_by == "frame" else "loads"
                data["list_files"].append(
                    {
                        "url": decision.data_url,
                        "loaded_by": decision.loaded_by,
                        "seen": (
                            f"the live page {decision.check.page} {verb} it (page check "
                            f"{decision.check.checked_at.strftime('%Y-%m-%dT%H:%M:%SZ')})"
                        ),
                    }
                )
        stations.append(data)
    return PlatformFile.model_validate_json(
        json.dumps({"platform": content.platform.model_dump(mode="json"), "stations": stations})
    )


def review(registry: Registry, decisions: Mapping[str, Decision]) -> list[str]:
    """Say which active stations the check leaves for review (no list file found)."""
    lines = []
    for station in registry.active():
        decision = decisions.get(station.id)
        if decision is None or station.status is not StationStatus.ACTIVE:
            continue
        if decision.data_url is None:
            lines.append(f"{station.id}: {decision.note}; left unchanged for review")
    return lines

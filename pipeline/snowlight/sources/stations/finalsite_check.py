"""Finalsite page checks: the page-pops address each district homepage asks for, seen in a browser.

A Finalsite station is read through its homepage (see
:mod:`snowlight.sources.stations.finalsite`): the poller reads the homepage, the
adapter reads its ``data-pageid`` and the poller follows it to that page's page pops.
What the homepage asks for is recorded, per station, from a check of the page in a
real browser (the page's own requests decide, nothing is inferred from its markup):

1. ``python -m snowlight.sources.stations.finalsite_check targets`` prints, for every
   active Finalsite station, ``{"id", "urls": [page_url], "user_agent"}``;
2. ``finalsite_pagecheck.cjs`` (next to this module) opens each homepage in headless
   Chromium with the project's User-Agent and records the page's ``data-pageid``
   and every page-pops request with its answer;
3. ``python -m snowlight.sources.stations.finalsite_check apply DIR [--write]`` reads
   those records. A station whose homepage opened at its own address, names a
   numeric ``data-pageid``, and asked for exactly one page-pops address, the one of
   that ID on the page's own site, answering 200, gets that check as its
   ``page_check`` (``loads``: that address), the address as a list file (loaded by
   script) and archive URL, and no ``data_url``: the live poller then reads the
   homepage and :func:`snowlight.sources.stations.fetch.page_check_mismatch` holds
   each read to the address the check saw. Any other record is reported for review
   and the station is left unchanged.
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from snowlight.sources.stations.finalsite import page_pops_path
from snowlight.sources.stations.http import USER_AGENT
from snowlight.sources.stations.model import ShapeError
from snowlight.sources.stations.registry import (
    DEFAULT_REGISTRY_DIR,
    PageCheck,
    PlatformFile,
    Registry,
    StationStatus,
    load_registry,
    write_platform_file,
)

PLATFORM = "finalsite"
METHOD = (
    "Opened in headless Chromium with the project's User-Agent by finalsite_pagecheck.cjs; "
    "images, media and fonts not loaded; waited up to 20 s for the page's page-pops request "
    "and 3 s more, recording the body's data-pageid and every /fs/pages/<id>/page-pops "
    "request with its answer. loads: the page-pops address the page's script requested, "
    "answering 200."
)
_OK = 200


@dataclass(frozen=True, slots=True)
class Decision:
    """What one station's browser record says: its check, or why it is left for review."""

    station_id: str
    check: PageCheck | None
    note: str


def targets(registry: Registry) -> list[dict[str, Any]]:
    """Return the homepages to check: every active Finalsite station's ``page_url``."""
    return [
        {"id": station.id, "urls": [station.page_url], "user_agent": USER_AGENT}
        for station in sorted(registry.stations.values(), key=lambda s: s.id)
        if station.platform == PLATFORM
        and station.status is StationStatus.ACTIVE
        and station.page_url is not None
    ]


def _identity(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return (parts.hostname or "").lower(), parts.path.rstrip("/") or "/"


def _time(stamp: str) -> datetime:
    when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return when.astimezone(UTC).replace(microsecond=0)


def decide(station_id: str, page_url: str, record: Mapping[str, Any]) -> Decision:
    """Read one homepage's browser record: the page-pops address it asked for, if one."""
    if record.get("error"):
        return Decision(station_id, None, f"the page did not open: {record['error']}")
    final = str(record.get("final_url") or "")
    if _identity(final) != _identity(page_url):
        return Decision(station_id, None, f"the page ended at {final}, not {page_url}")
    body_id = str(record.get("body_pageid") or "")
    try:
        path = page_pops_path(body_id)
    except ShapeError:
        return Decision(station_id, None, f"the page's body data-pageid is {body_id!r}")
    asked = sorted({str(r["url"]).split("?")[0] for r in record.get("responses", [])})
    answered = [r for r in record.get("responses", []) if r.get("status") == _OK and "sha256" in r]
    if len(asked) != 1 or len(answered) != 1:
        return Decision(station_id, None, f"the page asked for {asked or 'no page pops'}")
    (address,) = asked
    expected = f"{urlsplit(final).scheme}://{urlsplit(final).netloc}{path}"
    if address != expected:
        return Decision(station_id, None, f"the page asked for {address}, not {expected}")
    response = answered[0]
    pops = record.get("pops_in_page")
    shows = (
        f'Title {record.get("title")!r}; body data-pageid="{body_id}"; its script fetched '
        f"{path} (HTTP 200, {response.get('bytes')} bytes, SHA-256 "
        f"{str(response.get('sha256'))[:16]}…) and the page then held {pops} page pop(s)."
    )
    check = PageCheck(
        checked_at=_time(str(record["started"])),
        page=final,
        loads=(address,),
        shows=shows,
        method=METHOD,
    )
    return Decision(station_id, check, "loads")


def read_records(folder: Path) -> dict[str, Mapping[str, Any]]:
    """Return each station's last page record under ``folder/pages``."""
    records: dict[str, Mapping[str, Any]] = {}
    for path in sorted((folder / "pages").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        pages = data.get("pages") or []
        if pages:
            records[str(data["id"])] = pages[-1]
    return records


def apply(content: PlatformFile, decisions: Mapping[str, Decision]) -> PlatformFile:
    """Read each checked station through its homepage: page check, list file, no data URL."""
    stations = []
    for station in content.stations:
        data = station.model_dump(mode="json")
        decision = decisions.get(station.id)
        if decision is None or decision.check is None:
            stations.append(data)
            continue
        check = decision.check
        (address,) = check.loads
        data["data_url"] = None
        data["page_check"] = check.model_dump(mode="json")
        if address not in data["archive_urls"]:
            data["archive_urls"].append(address)
        stamp = check.checked_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        data["list_files"] = [item for item in data["list_files"] if item["url"] != address]
        data["list_files"].append(
            {
                "url": address,
                "loaded_by": "script",
                "seen": (
                    f"the live homepage {check.page} asks for it from its body data-pageid "
                    f"(page check {stamp})"
                ),
            }
        )
        stations.append(data)
    return PlatformFile.model_validate_json(
        json.dumps({"platform": content.platform.model_dump(mode="json"), "stations": stations})
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Print the targets, or apply a folder of browser records to ``finalsite.yaml``."""
    parser = argparse.ArgumentParser(prog="finalsite_check", description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("targets", help="print the homepages to check, as JSON")
    apply_p = actions.add_parser("apply", help="set each station's page check from records")
    apply_p.add_argument("records", type=Path)
    apply_p.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_DIR)
    apply_p.add_argument("--write", action="store_true", help="rewrite finalsite.yaml")
    args = parser.parse_args(argv)
    if args.action == "targets":
        sys.stdout.write(json.dumps(targets(load_registry()), indent=1) + "\n")
        return 0
    registry = load_registry(args.registry)
    records = read_records(args.records)
    content = registry.files[PLATFORM]
    decisions: dict[str, Decision] = {}
    for station in content.stations:
        record = records.get(station.id)
        if station.page_url is None or station.status is not StationStatus.ACTIVE:
            continue
        if record is None:
            decisions[station.id] = Decision(station.id, None, "no browser record")
            continue
        decisions[station.id] = decide(station.id, station.page_url, record)
    for decision in decisions.values():
        if decision.check is None:
            sys.stdout.write(f"{decision.station_id}: {decision.note}; left unchanged for review\n")
    checked = sum(1 for d in decisions.values() if d.check is not None)
    sys.stdout.write(
        f"{checked} of {len(decisions)} homepages ask for their page pops as recorded\n"
    )
    if args.write:
        write_platform_file(args.registry, apply(content, decisions))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Test fixtures for the network-owned, Emergency Closing Center and FlashAlert adapters.

The fixtures live in ``pipeline/tests/stations/fixtures/networks/``, with their own
``PROVENANCE.json`` (one :class:`~snowlight.sources.stations.fixtures.FixtureEntry`
per file, the model the other fixture folders use) and a ``README.md`` rendered
from it. Every file is a real response body, cut with one of :data:`SLICERS`
(deterministic: slicing a slice changes nothing, and a slice reads exactly as its
original does, which :func:`make_entry` checks).

Live bodies come from a capture log: ``capture`` reads each URL once through
:class:`~snowlight.sources.stations.http.PoliteClient` (the repository's
User-Agent, robots.txt read and its verdict recorded, per-host pacing, retries with
backoff, no workaround of a refusal), keeps each body under the log's folder and
appends one JSON line per URL to ``captures.jsonl``::

    {"url", "final_url", "status", "fetched_at", "sha256", "bytes", "file",
     "content_type", "last_modified", "not_modified",
     "robots": [{"url", "state", "allowed", "rule", "crawl_delay"}, ...]}

``add`` slices one logged body into a fixture (its SHA-256 checked against the log
first). Archived bodies come from the archive-captures workflow's snapshot
artifacts (``snapshots/manifest.jsonl`` beside the raw ``id_`` bodies):
``add-archived`` finds the capture asked for, checks the body against the
manifest's SHA-256 and slices it; its provenance records the capture the archive
actually served (timestamp and original URL), the ``id_`` URL that serves those
bytes, and when the runner downloaded them. An archived body may be a list file of
another station in the same vendor format (a Gray station's NewsTicker file, KPTV's
copy of FlashAlert's region 1 report): its ``source_id`` is that station, and its
note says which adapter's format it shows.

Usage (from ``pipeline/``)::

    uv run python -m snowlight.sources.stations.network_fixtures capture --out DIR URL...
    uv run python -m snowlight.sources.stations.network_fixtures add --log DIR/captures.jsonl \\
        --url URL --file nbc-owned/wbts-route-live.json --source nbc-owned-wbts \\
        --adapter nbc-owned --slice none [--note TEXT]
    uv run python -m snowlight.sources.stations.network_fixtures add-archived \\
        --artifacts .cache/stations/artifacts --timestamp 20240115042338 \\
        --url https://webpubcontent.gray.tv/kptv/closings/schoolclosures.html \\
        --file flashalert/kptv-copy-20240131153828.html --source gray-kptv \\
        --adapter flashalert --slice none [--note TEXT]
    uv run python -m snowlight.sources.stations.network_fixtures readme
"""

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from pydantic import TypeAdapter

from snowlight.output import write_bytes_atomic
from snowlight.sources.stations import abc_owned, archive, ecc, nbc_owned
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.fixtures import FixtureEntry, Origin, expected_from
from snowlight.sources.stations.http import (
    ConditionalStore,
    FetchError,
    PoliteClient,
    iso_utc,
    make_client,
)
from snowlight.sources.stations.model import ReadMode, ShapeError
from snowlight.sources.stations.network_markup import (
    element_end,
    iframe_tags,
    minimal_document,
    text_of,
)
from snowlight.sources.stations.registry import PIPELINE_ROOT

DEFAULT_FOLDER = PIPELINE_ROOT / "tests" / "stations" / "fixtures" / "networks"
DEFAULT_CACHE = PIPELINE_ROOT / ".cache" / "stations" / "live"
PROVENANCE_FILE = "PROVENANCE.json"
README_FILE = "README.md"
LOG_FILE = "captures.jsonl"
WAYBACK = "https://web.archive.org/web/{stamp}id_/{url}"
_OPTIONS_TAG = re.compile(
    r"<(?P<tag>[a-z]+)\b[^>]*\bdata-school-closings-options=(?:'[^']*'|\"[^\"]*\")[^>]*>",
    re.IGNORECASE,
)
_CBS_FRAME_TAG = re.compile(
    r"<iframe\b[^>]*?\b(?:data-src|src)\s*=\s*\"https?://[^\"]*SchoolClosings[^\"]*\"[^>]*>",
    re.IGNORECASE,
)
_FOX_FRAME_SRC = re.compile(r"\bsrc=\"https?://[^\"]*closings?[^\"]*\.html?", re.IGNORECASE)
_FOX_PROTECTED_DATA = re.compile(r"<input\b[^>]*\bname=\"_data\"[^>]*>", re.IGNORECASE)
_FOX_SECTION_OPEN = re.compile(r"<div\b[^>]*\bclass=\"wrap single-closings\"[^>]*>", re.IGNORECASE)

type Slicer = Callable[[bytes], bytes]


def _whole(body: bytes) -> bytes:
    """A list file or route is kept whole, decoded: every part is list or format marker."""
    return decode(body)


def slice_fox_page(body: bytes) -> bytes:
    """Keep a FOX closings page's closings frame (the ``<iframe>`` naming the list file).

    An older page without one keeps what it has instead: a WordPress.com protected
    embed's ``_data`` field (the frame, base64-encoded) or the page's closings
    section (``div.single-closings``, which then says nothing is listed).
    """
    html = text_of(decode(body))
    tags = [tag for tag in iframe_tags(html) if _FOX_FRAME_SRC.search(tag)]
    if not tags:
        tags = [match.group(0) for match in _FOX_PROTECTED_DATA.finditer(html)]
    if not tags:
        section = _FOX_SECTION_OPEN.search(html)
        if section is not None:
            tags = [html[section.start() : element_end(html, section.start(), "div")]]
    if not tags:
        raise ShapeError("no closings frame to keep")
    return minimal_document(tags)


def slice_cbs_page(body: bytes) -> bytes:
    """Keep a CBS closings page's widget element (its opening tag) or its closings frame."""
    html = text_of(decode(body))
    options = [match.group(0) + f"</{match.group('tag')}>" for match in _OPTIONS_TAG.finditer(html)]
    frames = [match.group(0) + "</iframe>" for match in _CBS_FRAME_TAG.finditer(html)]
    if not options and not frames:
        raise ShapeError("no closings widget or frame to keep")
    return minimal_document(options or frames)


SLICERS: Mapping[str, Slicer] = {
    "none": _whole,
    "abc-otv-v1": abc_owned.slice_page,
    "nbc-page-v1": nbc_owned.slice_page,
    "fox-page-v1": slice_fox_page,
    "cbs-page-v1": slice_cbs_page,
    "ecc-legacy-v1": ecc.slice_legacy_page,
}
"""Slicing methods by name. A method's output never changes once fixtures use it."""

_ENTRIES = TypeAdapter(list[FixtureEntry])


def load_entries(folder: Path) -> list[FixtureEntry]:
    """Read ``PROVENANCE.json`` from the fixtures folder (empty when there is none)."""
    path = folder / PROVENANCE_FILE
    if not path.is_file():
        return []
    return _ENTRIES.validate_json(path.read_bytes())


def make_entry(
    file: str, origin: Origin, original: bytes, method: str, note: str = ""
) -> tuple[FixtureEntry, bytes]:
    """Slice ``original`` and describe the fixture it becomes.

    Raises:
        ValueError: the slice does not read as the original does (variant, state, names).
    """
    sliced = SLICERS[method](original)
    if SLICERS[method](sliced) != sliced:
        raise ValueError(f"{file}: the {method} slice is not stable under slicing again")
    expected = expected_from(origin.adapter, sliced)
    if expected_from(origin.adapter, original) != expected:
        raise ValueError(f"{file}: the {method} slice does not read as the original does")
    entry = FixtureEntry.model_validate(
        {
            "file": file,
            "source_id": origin.source_id,
            "adapter": origin.adapter,
            "mode": origin.mode,
            "url": origin.url,
            "captured_at": origin.captured_at,
            "archive_url": origin.archive_url,
            "retrieved_at": origin.retrieved_at,
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "original_bytes": len(original),
            "slice": method,
            "sha256": hashlib.sha256(sliced).hexdigest(),
            "bytes": len(sliced),
            "expected": expected,
            "note": note,
        }
    )
    return entry, sliced


def render_readme(entries: Sequence[FixtureEntry]) -> str:
    """Render the folder's README from its provenance records."""
    lines = [
        "# Network-owned station, Emergency Closing Center and FlashAlert fixtures",
        "",
        "Every file here is real. Live fixtures are bodies read from the station's (or",
        "FlashAlert's, or the Emergency Closing Center's) server with the project's",
        "User-Agent by `python -m snowlight.sources.stations.network_fixtures capture`,",
        "which reads robots.txt first and records its verdict; the SHA-256 is of the body",
        "as read (it cannot be downloaded again as it was). Archived fixtures are Wayback",
        "Machine `id_` captures (the bytes the server sent when the archive read the file),",
        "downloaded on GitHub's runners by `.github/workflows/archive-captures.yml`; to",
        "check one, download its capture URL without decoding it and compare the original",
        "SHA-256. Pages are sliced to the parts the adapter reads with the method named",
        "below (`snowlight.sources.stations.network_fixtures.SLICERS`); list files and",
        "routes are kept whole (`none`, decoded). The exact names each adapter reads are",
        "in `PROVENANCE.json`.",
        "",
        "The terms of the ABC, NBC, FOX and CBS station sites and of the Emergency Closing",
        "Center's data host forbid automated reading; they are recorded in",
        "`pipeline/config/sources/` with the project owner's decisions to read the closings",
        "lists anyway (terms: 2026-09-25; robots.txt, whose verdict on each URL is recorded",
        "in the registry and in every read's health: 2026-09-26). FlashAlert's feed page",
        "allows periodic pulls.",
        "",
        "Most archived fixtures are the stations' own pages and files on storm days (the",
        "ABC pages from 2017 to 2026 in both designs, the Emergency Closing Center's data",
        "file, FlashAlert's region reports). Archived files from other stations (a Gray",
        "station's NewsTicker or SC file, KPTV's FTP copy of FlashAlert's region 1 report)",
        "are in the vendor formats these stations' files use; each note says so. The tests",
        "check the rows against the raw markup itself (`test_network_archived.py`), not",
        "only against the names recorded here.",
        "",
        "This file is generated from `PROVENANCE.json`; edit that, not this.",
        "",
        "| File | Source | Adapter | URL | Captured (UTC) | Retrieved (UTC) | Original SHA-256"
        " | Slice | Variant | State | Rows |",
        "|---|---|---|---|---|---|---|---|---|---|---:|",
    ]
    for entry in entries:
        capture = f" ([capture]({entry.archive_url}))" if entry.archive_url else ""
        lines.append(
            f"| `{entry.file}` | {entry.source_id} ({entry.mode.value}) | {entry.adapter}"
            f" | {entry.url}{capture} | {entry.captured_at:%Y-%m-%d %H:%M:%S}"
            f" | {entry.retrieved_at:%Y-%m-%d %H:%M:%S}"
            f" | `{entry.original_sha256[:16]}…` ({entry.original_bytes} bytes) | {entry.slice}"
            f" | {entry.expected.variant} | {entry.expected.state.value} | {entry.expected.rows} |"
        )
    notes = [entry for entry in entries if entry.note]
    if notes:
        lines += ["", "Notes:", ""]
        lines += [f"- `{entry.file}`: {entry.note}" for entry in notes]
    return "\n".join(lines) + "\n"


def write_fixtures(folder: Path, entries: Sequence[tuple[FixtureEntry, bytes]]) -> None:
    """Add or replace fixtures, then rewrite ``PROVENANCE.json`` and ``README.md``."""
    current = {entry.file: entry for entry in load_entries(folder)}
    for entry, body in entries:
        write_bytes_atomic(folder / entry.file, body)
        current[entry.file] = entry
    write_index(folder, [current[name] for name in sorted(current)])


def write_index(folder: Path, entries: Sequence[FixtureEntry]) -> None:
    """Write ``PROVENANCE.json`` and ``README.md`` for ``entries``."""
    data = [entry.model_dump(mode="json") for entry in entries]
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    write_bytes_atomic(folder / PROVENANCE_FILE, text.encode("utf-8"))
    write_bytes_atomic(folder / README_FILE, render_readme(entries).encode("utf-8"))


# Capturing live bodies -----------------------------------------------------------------


def _file_name(url: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[-1]).strip("_")[:120]
    return f"{stem}_{hashlib.sha256(url.encode()).hexdigest()[:10]}.body"


def capture(client: PoliteClient, urls: Sequence[str], out: Path) -> list[dict[str, object]]:
    """Read each URL once and log it (see the module docstring); return the log lines."""
    out.mkdir(parents=True, exist_ok=True)
    logged: list[dict[str, object]] = []
    for url in urls:
        try:
            fetched = client.fetch(url)
        except FetchError as error:
            record: dict[str, object] = {"url": url, "error": str(error), "status": error.status}
        else:
            name = _file_name(url)
            write_bytes_atomic(out / name, fetched.body)
            record = {
                "url": url,
                "final_url": fetched.final_url,
                "status": fetched.status,
                "fetched_at": iso_utc(fetched.fetched_at),
                "sha256": fetched.sha256,
                "bytes": len(fetched.body),
                "file": name,
                "content_type": fetched.content_type,
                "last_modified": fetched.last_modified,
                "not_modified": fetched.not_modified,
                "robots": [
                    {
                        "url": verdict.url,
                        "state": verdict.state.value,
                        "allowed": verdict.allowed,
                        "rule": verdict.rule,
                        "crawl_delay": verdict.crawl_delay,
                    }
                    for verdict in fetched.robots
                ],
            }
        with (out / LOG_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        logged.append(record)
    return logged


def logged_body(log: Path, url: str) -> tuple[dict[str, object], bytes]:
    """Return the last successful log line for ``url`` and its body, checked."""
    found: dict[str, object] | None = None
    for line in log.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("url") == url and "sha256" in record:
            found = record
    if found is None:
        raise KeyError(f"{url} was not captured in {log}")
    body = (log.parent / str(found["file"])).read_bytes()
    if hashlib.sha256(body).hexdigest() != found["sha256"]:
        raise ValueError(f"{found['file']}: the body does not match its logged SHA-256")
    return found, body


def archived_body(root: Path, timestamp: str, url: str) -> tuple[archive.SnapshotRecord, bytes]:
    """Find the downloaded capture of ``url`` asked for at ``timestamp``, checked."""
    for manifest in archive.find_manifests(root):
        for record in archive.read_manifest(manifest):
            if record.timestamp != timestamp or record.url != url or record.file is None:
                continue
            body = (manifest.parent.parent / record.file).read_bytes()
            if hashlib.sha256(body).hexdigest() != record.sha256:
                raise ValueError(f"{record.file}: the body does not match its manifest SHA-256")
            return record, body
    raise KeyError(f"no downloaded capture of {url} at {timestamp} under {root}")


def _stamp(value: str) -> str:
    return archive.capture_time(value).strftime("%Y-%m-%dT%H:%M:%SZ")


# Command line ----------------------------------------------------------------------------


def _add(args: argparse.Namespace) -> None:
    record, body = logged_body(args.log, args.url)
    origin = Origin(
        source_id=args.source,
        adapter=args.adapter,
        mode=ReadMode.LIVE,
        url=args.url,
        captured_at=str(record["fetched_at"]),
        archive_url=None,
        retrieved_at=str(record["fetched_at"]),
    )
    write_fixtures(args.folder, [make_entry(args.file, origin, body, args.slice, args.note)])


def _add_archived(args: argparse.Namespace) -> None:
    record, body = archived_body(args.artifacts, args.timestamp, args.url)
    served = record.final_timestamp or record.timestamp
    original = record.final_original or record.url
    origin = Origin(
        source_id=args.source,
        adapter=args.adapter,
        mode=ReadMode.ARCHIVE,
        url=original,
        captured_at=_stamp(served),
        archive_url=WAYBACK.format(stamp=served, url=original),
        retrieved_at=record.retrieved_at or _stamp(served),
    )
    write_fixtures(args.folder, [make_entry(args.file, origin, body, args.slice, args.note)])


def main(argv: Sequence[str] | None = None) -> int:
    """Run the fixture tool (see the module docstring)."""
    parser = argparse.ArgumentParser(prog="network_fixtures")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    actions = parser.add_subparsers(dest="action", required=True)
    capture_p = actions.add_parser("capture")
    capture_p.add_argument("--out", type=Path, required=True)
    capture_p.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    capture_p.add_argument("urls", nargs="+")
    for name in ("add", "add-archived"):
        sub = actions.add_parser(name)
        if name == "add":
            sub.add_argument("--log", type=Path, required=True)
        else:
            sub.add_argument("--artifacts", type=Path, required=True)
            sub.add_argument("--timestamp", required=True)
        sub.add_argument("--url", required=True)
        sub.add_argument("--file", required=True)
        sub.add_argument("--source", required=True)
        sub.add_argument("--adapter", required=True)
        sub.add_argument("--slice", default="none", choices=sorted(SLICERS))
        sub.add_argument("--note", default="")
    actions.add_parser("readme")
    args = parser.parse_args(argv)
    try:
        if args.action == "capture":
            client = PoliteClient(make_client(), ConditionalStore(args.cache))
            try:
                for record in capture(client, args.urls, args.out):
                    print(json.dumps(record, sort_keys=True))  # noqa: T201 - command output
            finally:
                client.close()
        elif args.action == "add":
            _add(args)
        elif args.action == "add-archived":
            _add_archived(args)
        else:
            write_index(args.folder, load_entries(args.folder))
    except (KeyError, ValueError, OSError, ShapeError) as error:
        print(f"network_fixtures {args.action}: {error}", file=sys.stderr)  # noqa: T201
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

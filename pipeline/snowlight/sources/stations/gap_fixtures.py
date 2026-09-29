"""Test fixtures for the gap-state adapters: real bodies, sliced, with their provenance.

The adapters are :mod:`~snowlight.sources.stations.cowles` (Cowles Montana
Media's closures ticker and the station pages that frame it),
:mod:`~snowlight.sources.stations.flathead` (the Flathead County superintendent's
closures page), :mod:`~snowlight.sources.stations.coesheet` (the Shasta and
Trinity county offices' closure sheets and the pages that frame them),
:mod:`~snowlight.sources.stations.gohsep` (Louisiana GOHSEP's parish school
closures layer), :mod:`~snowlight.sources.stations.apptegy` (school districts'
Apptegy homepages and their alert banners, and their older Nuxt 2, Schoolwires and
Campus Suite forms, :mod:`~snowlight.sources.stations.nuxt2`,
:mod:`~snowlight.sources.stations.schoolwires` and
:mod:`~snowlight.sources.stations.campussuite`),
:mod:`~snowlight.sources.stations.smartsites`,
:mod:`~snowlight.sources.stations.finalsite`,
:mod:`~snowlight.sources.stations.edlio` (school districts' Edlio homepage alerts),
:mod:`~snowlight.sources.stations.schoolblocks` (SchoolBlocks organization alerts),
:mod:`~snowlight.sources.stations.pasco` (Pasco County Schools' homepage banner),
:mod:`~snowlight.sources.stations.alsde` (the Alabama State Department of Education's
statewide closures list) and :mod:`~snowlight.sources.stations.npg` (KQ2's closings
file, St. Joseph, Missouri). Their
fixtures live in ``pipeline/tests/stations/fixtures/gaps/`` with their own
``PROVENANCE.json`` (one
:class:`~snowlight.sources.stations.fixtures.FixtureEntry` per file, the model every
part's fixtures use) and a ``README.md`` rendered from it. Every file is a real
response body, cut with one of :data:`SLICERS` (deterministic: slicing a slice
changes nothing, and a slice reads exactly as its original does). Real bodies an
adapter must refuse are kept under ``errors/`` with their provenance in
``PROVENANCE.errors.json``.

Live bodies come from a capture log: ``capture`` reads each URL once through
:class:`~snowlight.sources.stations.http.PoliteClient` (the repository's
User-Agent, robots.txt read and its verdict recorded, per-host pacing, retries
with backoff, no workaround of a refusal), keeps each body under the log's folder
and appends one JSON line per URL to ``captures.jsonl``::

    {"url", "final_url", "status", "fetched_at", "sha256", "bytes", "file",
     "content_type", "etag", "last_modified", "not_modified",
     "robots": [[url, state, allowed, rule, crawl_delay], ...]}

Archived bodies come from the archive-captures workflow's snapshot artifacts
(``snapshots/manifest.jsonl`` beside the raw ``id_`` bodies; see
:mod:`snowlight.sources.stations.archive`); their provenance records the capture
the archive actually served, the ``id_`` URL that serves those bytes, and when the
runner downloaded them.

Usage (from ``pipeline/``)::

    uv run python -m snowlight.sources.stations.gap_fixtures capture --out DIR URL...
    uv run python -m snowlight.sources.stations.gap_fixtures add --log DIR/captures.jsonl \\
        --url URL --file cowles/ticker-live-20260927.html --source cowles-kulr --slice cowles-v1
    uv run python -m snowlight.sources.stations.gap_fixtures add-archived --artifacts DIR \\
        --timestamp 20240113120000 --url URL --file cowles/ticker-20240113.html \\
        --source cowles-kulr --slice cowles-v1
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Annotated

from pydantic import StringConstraints, TypeAdapter

from snowlight.output import write_bytes_atomic
from snowlight.schemas.base import InternalModel
from snowlight.schemas.internal import Sha256, SourceId
from snowlight.schemas.scalars import Count, UtcInstant
from snowlight.sources.stations import (
    alsde,
    apptegy,
    archive,
    campussuite,
    coesheet,
    cowles,
    edlio,
    finalsite,
    flathead,
    npg,
    pasco,
    schoolblocks,
    schoolwires,
)
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.body import decode
from snowlight.sources.stations.fixtures import Expected, FixtureEntry, Origin
from snowlight.sources.stations.http import (
    ConditionalStore,
    FetchError,
    PoliteClient,
    iso_utc,
    make_client,
)
from snowlight.sources.stations.model import ReadMode, ShapeError
from snowlight.sources.stations.registry import PIPELINE_ROOT

DEFAULT_FOLDER = PIPELINE_ROOT / "tests" / "stations" / "fixtures" / "gaps"
PROVENANCE_FILE = "PROVENANCE.json"
ERRORS_FILE = "PROVENANCE.errors.json"
README_FILE = "README.md"
LOG_FILE = "captures.jsonl"

SLICERS: Mapping[str, Callable[[bytes], bytes]] = {
    "none": decode,
    "apptegy-v1": apptegy.slice_body,
    "apptegy-v2": apptegy.slice_body_v2,
    "schoolwires-v1": schoolwires.slice_body,
    "pasco-v1": pasco.slice_body,
    "coesheet-v1": coesheet.slice_body,
    "cowles-v1": cowles.slice_body,
    "flathead-v1": flathead.slice_body,
    "edlio-v1": edlio.slice_body,
    "schoolblocks-v1": schoolblocks.slice_body,
    "campussuite-v1": campussuite.slice_body,
    "alsde-v1": alsde.slice_body,
    "npg-v1": npg.slice_body,
    "finalsite-v1": finalsite.slice_body,
}
"""Slicing methods by name. A method's output never changes once fixtures use it."""


class ErrorFixture(InternalModel):
    """A real body an adapter refuses, and why it must."""

    file: Annotated[str, StringConstraints(pattern=r"^errors/[a-z0-9._-]+$")]
    source_id: SourceId
    adapter: str
    url: Annotated[str, StringConstraints(pattern=r"^https?://")]
    captured_at: UtcInstant
    archive_url: (
        Annotated[str, StringConstraints(pattern=r"^https://web\.archive\.org/")] | None
    ) = None
    sha256: Sha256
    bytes: Count
    reason: str


_ENTRIES = TypeAdapter(list[FixtureEntry])
_ERRORS = TypeAdapter(list[ErrorFixture])


class CaptureError(ValueError):
    """A capture log or artifact does not hold the body asked for, or holds another."""


def capture(client: PoliteClient, urls: Sequence[str], out: Path) -> list[dict[str, object]]:
    """Read each URL once and log it (see the module docstring); return the log lines."""
    out.mkdir(parents=True, exist_ok=True)
    lines: list[dict[str, object]] = []
    for url in urls:
        record: dict[str, object]
        try:
            fetched = client.fetch(url)
        except FetchError as error:
            record = {"url": url, "error": str(error), "status": error.status}
        else:
            key = hashlib.sha256(url.encode()).hexdigest()[:16]
            name = f"{key}-{fetched.fetched_at:%Y%m%d%H%M%S}.body"
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
                "etag": fetched.etag,
                "last_modified": fetched.last_modified,
                "not_modified": fetched.not_modified,
                "robots": [
                    [v.url, v.state.value, v.allowed, v.rule, v.crawl_delay] for v in fetched.robots
                ],
            }
        with (out / LOG_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        lines.append(record)
    return lines


def logged_body(log: Path, url: str) -> tuple[dict[str, object], bytes]:
    """Return the last successful log line for ``url`` and its body, checked by SHA-256."""
    found: dict[str, object] | None = None
    for line in log.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("url") == url and record.get("file"):
            found = record
    if found is None:
        raise CaptureError(f"the log has no body for {url}")
    body = (log.parent / str(found["file"])).read_bytes()
    if hashlib.sha256(body).hexdigest() != found["sha256"]:
        raise CaptureError(f"{found['file']}: SHA-256 differs from the log")
    return found, body


def archived_body(root: Path, timestamp: str, url: str) -> tuple[Origin, bytes]:
    """Return the provenance and raw bytes of the capture asked for as ``timestamp`` ``url``.

    Raises:
        CaptureError: no manifest under ``root`` names the capture, it was not
            downloaded, or the body on disk is not the one the manifest recorded.
    """
    matching = [
        (manifest, record)
        for manifest in archive.find_manifests(root)
        for record in archive.read_manifest(manifest)
        if record.timestamp == timestamp and record.url == url
    ]
    if not matching:
        raise CaptureError(f"no manifest under {root} holds the capture {timestamp} {url}")
    manifest, record = min(matching, key=lambda item: item[1].file is None)
    if record.file is None or record.sha256 is None or record.retrieved_at is None:
        raise CaptureError(f"the capture {timestamp} {url} was not downloaded: {record.error}")
    body = (manifest.parent.parent / record.file).read_bytes()
    if hashlib.sha256(body).hexdigest() != record.sha256:
        raise CaptureError(f"{record.file}: SHA-256 differs from the manifest")
    stamp = record.final_timestamp or record.timestamp
    original = record.final_original or record.url
    origin = Origin(
        source_id="",
        adapter="",
        mode=ReadMode.ARCHIVE,
        url=original,
        captured_at=iso_utc(archive.capture_time(stamp)),
        archive_url=f"https://web.archive.org/web/{stamp}id_/{original}",
        retrieved_at=record.retrieved_at,
    )
    return origin, body


def expected_from(adapter: str, body: bytes) -> Expected:
    """Run ``adapter`` over ``body`` and describe what it read."""
    listing = adapter_for(adapter)(body)
    return Expected(
        variant=listing.variant,
        state=listing.state,
        rows=len(listing.rows),
        names=tuple(row.name for row in listing.rows),
    )


def make_entry(
    file: str, origin: Origin, original: bytes, method: str, note: str = ""
) -> tuple[FixtureEntry, bytes]:
    """Slice ``original`` and describe the fixture it becomes.

    Raises:
        ValueError: the slice does not read as the original does, or slicing the
            slice changes it.
    """
    sliced = SLICERS[method](original)
    expected = expected_from(origin.adapter, sliced)
    if expected_from(origin.adapter, original) != expected:
        raise ValueError(f"{file}: the {method} slice does not read as the original does")
    if SLICERS[method](sliced) != sliced:
        raise ValueError(f"{file}: slicing the {method} slice again changes it")
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


def load_entries(folder: Path) -> list[FixtureEntry]:
    """Read ``PROVENANCE.json`` (empty when there is none)."""
    path = folder / PROVENANCE_FILE
    return _ENTRIES.validate_json(path.read_bytes()) if path.is_file() else []


def load_errors(folder: Path) -> list[ErrorFixture]:
    """Read ``PROVENANCE.errors.json`` (empty when there is none)."""
    path = folder / ERRORS_FILE
    return _ERRORS.validate_json(path.read_bytes()) if path.is_file() else []


def _dump(items: Sequence[InternalModel]) -> bytes:
    data = [item.model_dump(mode="json") for item in items]
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_fixtures(
    folder: Path,
    entries: Sequence[tuple[FixtureEntry, bytes]] = (),
    errors: Sequence[tuple[ErrorFixture, bytes]] = (),
) -> None:
    """Add or replace fixtures, then rewrite both provenance files and the README."""
    current = {entry.file: entry for entry in load_entries(folder)}
    for entry, body in entries:
        write_bytes_atomic(folder / entry.file, body)
        current[entry.file] = entry
    refused = {item.file: item for item in load_errors(folder)}
    for item, body in errors:
        write_bytes_atomic(folder / item.file, body)
        refused[item.file] = item
    ordered = [current[name] for name in sorted(current)]
    failures = [refused[name] for name in sorted(refused)]
    write_bytes_atomic(folder / PROVENANCE_FILE, _dump(ordered))
    write_bytes_atomic(folder / ERRORS_FILE, _dump(failures))
    readme = render_readme(ordered, failures, folder)
    write_bytes_atomic(folder / README_FILE, readme.encode("utf-8"))


_INTRO = """\
# Gap-state adapter fixtures (Cowles, Flathead County, county sheets, GOHSEP, district sites)

Every file here is a real response body, live or archived.

Live bodies were read once from the source's server (or the file its closings
page frames) with the pipeline's own client,
`snowlight.sources.stations.http.PoliteClient`, as `gap_fixtures capture` does:
the repository's User-Agent, robots.txt read first and its verdict recorded,
per-host pacing. A live body cannot be downloaded again as it was: its SHA-256 is
the one the capture log recorded when it was read.

Archived bodies are Wayback Machine `id_` captures (the bytes the source served
when the archive read the page), downloaded on GitHub's runners by
`.github/workflows/archive-captures.yml` and added with `gap_fixtures
add-archived`. `Captured` is when the archive read the page (the capture the
archive served, which may be near rather than at the one asked for) and
`Retrieved` when the runner downloaded it. The original SHA-256 is of the bytes as
the archive sent them (a page served gzip-encoded is still gzip): download the
capture link without decoding it, confirm the SHA-256, slice it, and compare bytes.

Bodies are cut with the method named below
(`snowlight.sources.stations.gap_fixtures.SLICERS`): a station page keeps only
the frame naming its list file, the Flathead County page keeps its "Last Updated"
line, its notice card and its closures tables with their headings, a sheet's table
view keeps each cell's text and span, an Apptegy district homepage keeps only its
`__NUXT_DATA__` state (whole), a Finalsite homepage keeps its title, its `<body>`
tag with every attribute (its `data-pageid`) and any page-pop collection it holds,
and list files (the ticker, a sheet's CSV, the GOHSEP layer's query answer, a Smart
Sites alerts file, a Finalsite page-pops answer) are kept whole. Slicing a
slice changes nothing, and a slice reads exactly as its original did (the same
variant, state and row names). Full SHA-256 values and the exact names the adapter
reads are in `PROVENANCE.json`.

This file is generated from the provenance files; edit those, not this.

## Adapter fixtures
"""
_HEADER = (
    "| File | Source | URL | Captured (UTC) | Retrieved (UTC) | Original SHA-256 | Slice"
    " | Variant | State | Rows |",
    "|---|---|---|---|---|---|---|---|---|---:|",
)


GENERATOR_FILE = "PROVENANCE.generator.json"
"""Real list files of the generator an adapter reads, from another operator's station.

Kept in ``generator/`` to test a populated form no archived capture of the source
itself shows (Cowles' ticker has no capture); each record says why. They are not
fixtures of any registered source, so they prove nothing about coverage.
"""


def _generator_section(folder: Path | None) -> list[str]:
    path = folder / "generator" / GENERATOR_FILE if folder is not None else None
    if path is None or not path.is_file():
        return []
    lines = [
        "",
        "## Generator files (`generator/`)",
        "",
        "Real list files of the same generator from another operator's station, used only to",
        "test a populated form; not evidence for any source.",
        "",
        "| File | URL | Captured (UTC) | Retrieved (UTC) | Original SHA-256 | Rows | Why |",
        "|---|---|---|---|---|---:|---|",
    ]
    for name, item in sorted(json.loads(path.read_text(encoding="utf-8")).items()):
        lines.append(
            f"| `generator/{name}` | {item['url']} ([capture]({item['archive_url']}))"
            f" | {item['captured_at']} | {item['retrieved_at']}"
            f" | `{str(item['original_sha256'])[:16]}…` | {item['rows']} | {item['why']} |"
        )
    return lines


def render_readme(
    entries: Sequence[FixtureEntry],
    errors: Sequence[ErrorFixture],
    folder: Path | None = None,
) -> str:
    """Render the README from the provenance records (and ``folder``'s generator files)."""
    lines = [*_INTRO.splitlines(), "", *_HEADER]
    for entry in entries:
        archived = f" ([capture]({entry.archive_url}))" if entry.archive_url else ""
        lines.append(
            f"| `{entry.file}` | {entry.source_id} ({entry.mode.value}) | {entry.url}{archived}"
            f" | {entry.captured_at:%Y-%m-%d %H:%M:%S} | {entry.retrieved_at:%Y-%m-%d %H:%M:%S}"
            f" | `{entry.original_sha256[:16]}…` ({entry.original_bytes} bytes) | {entry.slice}"
            f" | {entry.expected.variant} | {entry.expected.state.value} | {entry.expected.rows} |"
        )
    notes = [entry for entry in entries if entry.note]
    if notes:
        lines += ["", "Notes:", ""]
        lines += [f"- `{entry.file}`: {entry.note}" for entry in notes]
    if errors:
        lines += [
            "",
            "## Bodies the adapters refuse (`errors/`)",
            "",
            "Kept whole. Each must raise `ShapeError` in its adapter.",
            "",
            "| File | Source | URL | Captured (UTC) | SHA-256 | Why it is refused |",
            "|---|---|---|---|---|---|",
        ]
        for item in errors:
            archived = f" ([capture]({item.archive_url}))" if item.archive_url else ""
            lines.append(
                f"| `{item.file}` | {item.source_id} | {item.url}{archived}"
                f" | {item.captured_at:%Y-%m-%d %H:%M:%S} | `{item.sha256[:16]}…` | {item.reason} |"
            )
    lines += _generator_section(folder)
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gap_fixtures", description=__doc__.split("\n")[0])
    actions = parser.add_subparsers(dest="action", required=True)
    capture_p = actions.add_parser("capture", help="read URLs once and log the bodies")
    capture_p.add_argument("--out", type=Path, required=True)
    capture_p.add_argument("urls", nargs="+")
    for name in ("add", "add-error", "add-archived", "add-archived-error"):
        add_p = actions.add_parser(name, help=f"{name} one logged or archived body")
        if name.startswith("add-archived"):
            add_p.add_argument("--artifacts", type=Path, required=True)
            add_p.add_argument("--timestamp", required=True, help="the capture asked for")
        else:
            add_p.add_argument("--log", type=Path, required=True)
        add_p.add_argument("--url", required=True)
        add_p.add_argument("--file", required=True)
        add_p.add_argument("--source", required=True, help="the registry source id")
        add_p.add_argument("--adapter", help="defaults to the source id's platform adapter")
        add_p.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
        if name.endswith("error"):
            add_p.add_argument("--reason", required=True)
        else:
            add_p.add_argument("--slice", default="none", choices=sorted(SLICERS))
            add_p.add_argument("--note", default="")
    return parser


def _adapter(args: argparse.Namespace) -> str:
    return str(args.adapter) if args.adapter else str(args.source).split("-", 1)[0]


def _refused(args: argparse.Namespace, adapter: str, body: bytes, origin: Origin) -> ErrorFixture:
    try:
        adapter_for(adapter)(body)
    except ShapeError:
        pass
    else:
        raise CaptureError(f"{args.url}: the {adapter} adapter reads it; not a refused body")
    return ErrorFixture.model_validate(
        {
            "file": args.file,
            "source_id": args.source,
            "adapter": adapter,
            "url": origin.url,
            "captured_at": origin.captured_at,
            "archive_url": origin.archive_url,
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
            "reason": args.reason,
        }
    )


def _origin(args: argparse.Namespace, adapter: str) -> tuple[Origin, bytes]:
    if args.action.startswith("add-archived"):
        found, body = archived_body(args.artifacts, args.timestamp, args.url)
        return replace(found, source_id=args.source, adapter=adapter), body
    record, body = logged_body(args.log, args.url)
    origin = Origin(
        source_id=args.source,
        adapter=adapter,
        mode=ReadMode.LIVE,
        url=args.url,
        captured_at=str(record["fetched_at"]),
        archive_url=None,
        retrieved_at=str(record["fetched_at"]),
    )
    return origin, body


def main(argv: Sequence[str] | None = None, client: PoliteClient | None = None) -> int:
    """Run the command line (see the module docstring)."""
    args = _parser().parse_args(argv)
    if args.action == "capture":
        own = client or PoliteClient(make_client(), ConditionalStore(args.out / "cache"))
        try:
            lines = capture(own, args.urls, args.out)
        finally:
            if client is None:
                own.close()
        for line in lines:
            sys.stdout.write(f"{line['url']}: {line.get('status')} {line.get('bytes', '')}\n")
        return 0
    adapter = _adapter(args)
    try:
        origin, body = _origin(args, adapter)
        if args.action.endswith("error"):
            item = _refused(args, adapter, body, origin)
            write_fixtures(args.folder, errors=[(item, body)])
            sys.stdout.write(f"{item.file}: kept as a refused body\n")
            return 0
        entry, sliced = make_entry(args.file, origin, body, args.slice, args.note)
        write_fixtures(args.folder, entries=[(entry, sliced)])
    except (CaptureError, archive.ArchiveError, ValueError, KeyError, OSError) as error:
        sys.stderr.write(f"gap_fixtures {args.action} failed: {error}\n")
        return 1
    sys.stdout.write(
        f"{entry.file}: {entry.expected.variant}, {entry.expected.state.value}, "
        f"{entry.expected.rows} rows (captured {iso_utc(entry.captured_at)})\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

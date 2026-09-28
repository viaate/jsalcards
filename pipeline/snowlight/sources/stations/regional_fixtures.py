"""Test fixtures for part 3b's regional and group adapters: real bodies, sliced, with provenance.

The adapters are :mod:`~snowlight.sources.stations.sinclair`,
:mod:`~snowlight.sources.stations.allen`, :mod:`~snowlight.sources.stations.cox`,
:mod:`~snowlight.sources.stations.graham`, :mod:`~snowlight.sources.stations.hubbard`,
:mod:`~snowlight.sources.stations.wtop`, :mod:`~snowlight.sources.stations.spectrum`,
:mod:`~snowlight.sources.stations.news12`, :mod:`~snowlight.sources.stations.townsquare`,
:mod:`~snowlight.sources.stations.delaware`, :mod:`~snowlight.sources.stations.wveis`,
:mod:`~snowlight.sources.stations.newsticker` (the RIBA list), and
:mod:`~snowlight.sources.stations.wral`, :mod:`~snowlight.sources.stations.lockwood`,
:mod:`~snowlight.sources.stations.whdh`, :mod:`~snowlight.sources.stations.heritage`,
:mod:`~snowlight.sources.stations.eventdelay`, :mod:`~snowlight.sources.stations.blox`,
:mod:`~snowlight.sources.stations.weatherthreat`, the county offices' lists,
:mod:`~snowlight.sources.stations.santacruzcoe` and :mod:`~snowlight.sources.stations.hcoe`,
and KXXO's page, :mod:`~snowlight.sources.stations.radio`.

Their fixtures live in ``pipeline/tests/stations/fixtures/regional/`` with their
own ``PROVENANCE.json`` (one :class:`~snowlight.sources.stations.fixtures.FixtureEntry`
per file, the model every part's fixtures use) and a ``README.md`` rendered from
it. Every file is a real response body, cut with one of :data:`SLICERS`
(deterministic: slicing a slice changes nothing, and a slice reads exactly as its
original does). Bodies an adapter must refuse (a real body in no shape it reads)
are kept under ``errors/`` with their provenance in ``PROVENANCE.errors.json``.

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

    uv run python -m snowlight.sources.stations.regional_fixtures capture --out DIR URL...
    uv run python -m snowlight.sources.stations.regional_fixtures add --log DIR/captures.jsonl \\
        --url URL --file sinclair/wach-live-20260927.html --source sinclair-wach --slice sinclair-v1
    uv run python -m snowlight.sources.stations.regional_fixtures add-archived --artifacts DIR \\
        --timestamp 20250106120000 --url URL --file sinclair/wjla-20250106.html \\
        --source sinclair-wjla --slice sinclair-v1
    uv run python -m snowlight.sources.stations.regional_fixtures add-error --log ... --url URL \\
        --file errors/kyuu-ld-live-20260927.html --source sinclair-kyuu-ld --reason TEXT
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
    allen,
    archive,
    blox,
    cox,
    delaware,
    eventdelay,
    graham,
    hcoe,
    heritage,
    hubbard,
    lockwood,
    ncpr,
    news12,
    newsticker,
    radio,
    santacruzcoe,
    sinclair,
    spectrum,
    townsquare,
    weatherthreat,
    whdh,
    wral,
    wtop,
    wveis,
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

DEFAULT_FOLDER = PIPELINE_ROOT / "tests" / "stations" / "fixtures" / "regional"
PROVENANCE_FILE = "PROVENANCE.json"
ERRORS_FILE = "PROVENANCE.errors.json"
README_FILE = "README.md"
LOG_FILE = "captures.jsonl"

SLICERS: Mapping[str, Callable[[bytes], bytes]] = {
    "none": decode,
    "sinclair-v1": sinclair.slice_body,
    "allen-v1": allen.slice_body,
    "cox-v1": cox.slice_body,
    "graham-v1": graham.slice_body,
    "heritage-v1": heritage.slice_body,
    "hubbard-v1": hubbard.slice_body,
    "wtop-v1": wtop.slice_body,
    "whdh-v1": whdh.slice_body,
    "spectrum-v1": spectrum.slice_body,
    "news12-v1": news12.slice_body,
    "ncpr-v1": ncpr.slice_body,
    "townsquare-v1": townsquare.slice_body,
    "delaware-v1": delaware.slice_body,
    "wveis-v1": wveis.slice_body,
    "newsticker-v1": newsticker.slice_body,
    "wral-v1": wral.slice_body,
    "lockwood-v1": lockwood.slice_body,
    "eventdelay-v1": eventdelay.slice_body_v1,
    "eventdelay-v2": eventdelay.slice_body,
    "blox-v1": blox.slice_body,
    "weatherthreat-v1": weatherthreat.slice_body,
    "santacruzcoe-v1": santacruzcoe.slice_body,
    "hcoe-v1": hcoe.slice_body,
    "radio-v1": radio.slice_body,
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
    write_bytes_atomic(folder / README_FILE, render_readme(ordered, failures).encode("utf-8"))


_INTRO = """\
# Regional and group adapter fixtures (Sinclair, Allen, Cox, Graham, Hubbard and the rest)

Every file here is a real response body, live or archived.

Live bodies were read once from the station's server (or the file its closings
page frames or loads) with the pipeline's own client,
`snowlight.sources.stations.http.PoliteClient`, as `regional_fixtures capture`
does: the repository's User-Agent, robots.txt read first and its verdict recorded,
per-host pacing. Some of these files sit where robots.txt disallows them (the
Sinclair `/resources/ftptransfer/` files, most Allen `ftp2` hosts, WVEIS): the
project owner decided on 2026-09-26 to read closings pages and files regardless,
and the verdicts are in the registry and in every read's health. A live body
cannot be downloaded again as it was: its SHA-256 is the one the capture log
recorded when it was read.

Archived bodies are Wayback Machine `id_` captures (the bytes the station served
when the archive read the page), downloaded on GitHub's runners by
`.github/workflows/archive-captures.yml` and added with `regional_fixtures
add-archived`. `Captured` is when the archive read the page (the capture the
archive served, which may be near rather than at the one asked for) and
`Retrieved` when the runner downloaded it. The original SHA-256 is of the bytes as
the archive sent them (a page the station served gzip-encoded is still gzip):
download the capture link without decoding it, confirm the SHA-256, slice it, and
compare bytes.

Several platforms' terms forbid reading their sites with software; they are
recorded in `pipeline/config/sources/` with the project owner's decision
(2026-09-25) to read the closings lists anyway.

Bodies are cut with the method named below
(`snowlight.sources.stations.regional_fixtures.SLICERS`): a page keeps only the
part its adapter reads (the frame or loader naming its list file, the content
cache entry, the closings block or table; WTOP's data line keeps each posting's
fields the adapter reads and drops the rest of the WordPress post), and list
files are kept whole. Slicing a slice changes nothing, and a slice reads exactly
as its original did (the same variant, state and row names). Full SHA-256 values
and the exact names the adapter reads are in `PROVENANCE.json`.

This file is generated from the provenance files; edit those, not this.

## Adapter fixtures
"""
_HEADER = (
    "| File | Source | URL | Captured (UTC) | Retrieved (UTC) | Original SHA-256 | Slice"
    " | Variant | State | Rows |",
    "|---|---|---|---|---|---|---|---|---|---:|",
)


def render_readme(entries: Sequence[FixtureEntry], errors: Sequence[ErrorFixture]) -> str:
    """Render the README from the provenance records."""
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
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="regional_fixtures", description=__doc__.split("\n")[0])
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
    if args.adapter:
        return str(args.adapter)
    platform = str(args.source).split("-", 1)[0]
    return "newsticker" if platform == "riba" else platform


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
        sys.stderr.write(f"regional_fixtures {args.action} failed: {error}\n")
        return 1
    sys.stdout.write(
        f"{entry.file}: {entry.expected.variant}, {entry.expected.state.value}, "
        f"{entry.expected.rows} rows (captured {iso_utc(entry.captured_at)})\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

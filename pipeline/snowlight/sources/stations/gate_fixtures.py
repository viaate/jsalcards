"""Test fixtures for the coverage gate's readers: real bodies, sliced, with their provenance.

The coverage gate (piece s4) adds readers for forms of district homepages that
the archive holds from before the districts' current sites
(:mod:`~snowlight.sources.stations.wcm`, Web Community Manager announcements
apps), which the Apptegy, Smart Sites and Finalsite adapters read. Their fixtures
live in ``pipeline/tests/stations/fixtures/gate/`` with their own
``PROVENANCE.json`` (one :class:`~snowlight.sources.stations.fixtures.FixtureEntry`
per file, the model every part's fixtures use) and a ``README.md`` rendered from
it; real bodies an adapter must refuse are kept under ``errors/`` with
``PROVENANCE.errors.json``.

Bodies are read and kept the way :mod:`~snowlight.sources.stations.gap_fixtures`
keeps them (the same capture log, the same archived-body check against the
workflow's manifest, the same entry model): every file is a real response body,
cut with one of :data:`SLICERS` (deterministic: slicing a slice changes nothing,
and a slice reads exactly as its original does).

A body the live fetch read (``stations fetch``, which keeps each answer in its
conditional-request store and records its time and SHA-256 in the run manifest) is
added with ``add-fetched``: needed for an answer to a POST (``Station.data_post``),
which ``gap_fixtures capture`` (GET only) cannot read.

Usage (from ``pipeline/``)::

    uv run python -m snowlight.sources.stations.gate_fixtures add-archived \\
        --artifacts .cache/stations/artifacts --timestamp 20201030135632 \\
        --url https://www.clarkecountyschools.org/ --file wcm/clarke-20201030.html \\
        --source finalsite-clarke-al --slice wcm-v1
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from pydantic import TypeAdapter

from snowlight.output import write_bytes_atomic
from snowlight.schemas.base import InternalModel
from snowlight.sources.stations import (
    archive,
    cowles,
    district_homepage,
    edlio,
    elementor,
    fixtures,
    gap_fixtures,
    googlesites,
    group_fixtures,
    homepage,
    http,
    nisd,
    sharpschool,
    tegna,
    wcm,
)
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.fixtures import FixtureEntry, Origin
from snowlight.sources.stations.gap_fixtures import (
    CaptureError,
    ErrorFixture,
    archived_body,
    expected_from,
    logged_body,
)
from snowlight.sources.stations.gap_markup import html_text
from snowlight.sources.stations.http import iso_utc
from snowlight.sources.stations.model import ReadMode, ShapeError
from snowlight.sources.stations.registry import PIPELINE_ROOT

DEFAULT_FOLDER = PIPELINE_ROOT / "tests" / "stations" / "fixtures" / "gate"
PROVENANCE_FILE = "PROVENANCE.json"
ERRORS_FILE = "PROVENANCE.errors.json"
README_FILE = "README.md"


def _with_text(slicer: Callable[[bytes], bytes]) -> Callable[[bytes], bytes]:
    """A slicer that keeps what ``slicer`` keeps and the page's closing lines as paragraphs."""

    def cut(body: bytes) -> bytes:
        sliced = slicer(body).decode()
        blocks = homepage.text_blocks(html_text(body))
        if not blocks or blocks in sliced:
            return sliced.encode()
        return sliced.replace("</body>", f"{blocks}</body>", 1).encode()

    return cut


SLICERS: Mapping[str, Callable[[bytes], bytes]] = {
    **gap_fixtures.SLICERS,
    "gray-page-v4": fixtures.SLICERS["gray-page-v4"],
    "nexstar-v4": group_fixtures.SLICERS["nexstar-v4"],
    "wcm-v1": wcm.slice_body,
    "wcm-v2": wcm.slice_body_v2,
    "googlesites-v1": googlesites.slice_body,
    "nisd-v1": nisd.slice_body,
    "sharpschool-v1": sharpschool.slice_body,
    "sharpschool-v2": sharpschool.slice_body_v2,
    "elementor-v1": elementor.slice_body,
    "tegna-v3": tegna.slice_body_v3,
    "cowles-v2": cowles.slice_body_v2,
    "sharpschool-v3": sharpschool.slice_body_v3,
    "edlio-v2": edlio.slice_body_v2,
    "homepage-text-v1": homepage.slice_body,
    "district-homepage-v1": district_homepage.slice_body,
    "district-homepage-v2": district_homepage.slice_body_v2,
    "wcm-v3": _with_text(wcm.slice_body_v2),
    "finalsite-v2": _with_text(gap_fixtures.SLICERS["finalsite-v1"]),
}
"""Slicing methods by name: the gap-state part's, the framework's Gray page cut and part 2's
Nexstar cut (for station pages this part proved), and this part's. Never changed once used."""

_ENTRIES = TypeAdapter(list[FixtureEntry])
_ERRORS = TypeAdapter(list[ErrorFixture])


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
# Coverage gate fixtures (older forms of district homepages)

Every file here is a real response body, live or archived.

Archived bodies are Wayback Machine `id_` captures (the bytes the site served
when the archive read the page), downloaded on GitHub's runners by
`.github/workflows/archive-captures.yml` and added with `gate_fixtures
add-archived`. `Captured` is when the archive read the page (the capture the
archive served, which may be near rather than at the one asked for) and
`Retrieved` when the runner downloaded it. The original SHA-256 is of the bytes as
the archive sent them (a page served gzip-encoded is still gzip): download the
capture link without decoding it, confirm the SHA-256, slice it, and compare bytes.
Live bodies were read once with the pipeline's own client
(`snowlight.sources.stations.http.PoliteClient`, as `gap_fixtures capture` does:
the repository's User-Agent, robots.txt read first and its verdict recorded).

Bodies are cut with the method named below
(`snowlight.sources.stations.gate_fixtures.SLICERS`): a Web Community Manager
homepage (`wcm-v1`) keeps its title and each announcements app it holds, in the
app's module wrapper, without scripts or styles (`wcm-v2` also keeps the one script
call that loads the site's on-screen alert file, alone in a `<script>` element); an
on-screen alert file is kept whole (`none`); a Google Sites homepage
(`googlesites-v1`) keeps the site's name and its view header with only the
announcement banner; a SharpSchool homepage (`sharpschool-v1`) keeps its title and
its hero slider, or only the alert component's element when it has no slider
(`sharpschool-v2` also keeps a WordPress homepage's Smart Slider sliders, without
scripts, styles or images); a
station page this part proved is cut with its own part's method
(`gray-page-v4`, `nexstar-v4`); a TEGNA closings page that links to its list
elsewhere keeps the raw-HTML module holding the link, and the closings article it
links to keeps its title, its "Updated:" line and its article body (`tegna-v3`,
which cuts every page `tegna-v2` cuts the same way). Round 3's readers: a Cowles
section page (`cowles-v2`) keeps the section's body class and the closings article or
the story cards it shows, without scripts, styles or images; a SharpSchool homepage
(`sharpschool-v3`) keeps its title, its hero slider or banner rotator, its alert
component's element and each closing line of its text; an Edlio homepage
(`edlio-v2`) keeps what `edlio-v1` keeps and each closing line of its text, and so
do `wcm-v3` (of `wcm-v2`) and `finalsite-v2` (of `finalsite-v1`); a page
read by its text (`homepage-text-v1`) keeps its title and its closing lines (and its
site alert module, without scripts, when it has one); a Utah
district homepage (`district-homepage-v1`) keeps its title, its alert loader's marker
or its alerts section, and its closing lines (an alert file is kept whole), and
`district-homepage-v2` the same with a news card's posting stamp under its line. Closing
lines are kept as paragraphs, one per line the closure-text check finds
(`snowlight.sources.stations.homepage.text_blocks`). Slicing a slice changes nothing,
and a slice reads exactly as its original did (the same variant, state and row
names). Full SHA-256 values and the exact names the adapter reads are in
`PROVENANCE.json`.

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


def fetched_body(manifest: Path, cache_dir: Path, url: str) -> tuple[dict[str, object], bytes]:
    """The fetch's last read of ``url`` (its manifest record) and the body it kept.

    Raises:
        CaptureError: the manifest has no read of ``url``, or the stored body is not
            the one the run read (another read replaced it since).
    """
    data = json.loads(manifest.read_text(encoding="utf-8"))
    reads = [
        snap
        for snap in data.get("snapshots", [])
        if isinstance(snap, dict) and snap.get("url") == url and snap.get("sha256")
    ]
    if not reads:
        raise CaptureError(f"the run manifest has no read of {url}")
    record = reads[-1]
    stored = http.ConditionalStore(cache_dir).load(url)
    if stored is None or hashlib.sha256(stored[1]).hexdigest() != record["sha256"]:
        raise CaptureError(f"{url}: the stored body is not the one the run read")
    return record, stored[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gate_fixtures", description=__doc__.split("\n")[0])
    actions = parser.add_subparsers(dest="action", required=True)
    fetched_p = actions.add_parser("add-fetched", help="add one body the live fetch read")
    fetched_p.add_argument("--manifest", type=Path, required=True, help="the run's manifest.json")
    fetched_p.add_argument("--cache-dir", type=Path, required=True, help="the fetch's store")
    fetched_p.add_argument("--url", required=True)
    fetched_p.add_argument("--file", required=True)
    fetched_p.add_argument("--source", required=True, help="the registry source id")
    fetched_p.add_argument("--adapter", help="defaults to the source id's platform adapter")
    fetched_p.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    fetched_p.add_argument("--slice", default="none", choices=sorted(SLICERS))
    fetched_p.add_argument("--note", default="")
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


def _origin(args: argparse.Namespace, adapter: str) -> tuple[Origin, bytes]:
    if args.action.startswith("add-archived"):
        found, body = archived_body(args.artifacts, args.timestamp, args.url)
        return replace(found, source_id=args.source, adapter=adapter), body
    if args.action == "add-fetched":
        record, body = fetched_body(args.manifest, args.cache_dir, args.url)
    else:
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


def refused(args: argparse.Namespace, adapter: str, body: bytes, origin: Origin) -> ErrorFixture:
    """Describe a body the adapter must refuse (raises when the adapter reads it)."""
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line (see the module docstring)."""
    args = _parser().parse_args(argv)
    adapter = _adapter(args)
    try:
        origin, body = _origin(args, adapter)
        if args.action.endswith("error"):
            item = refused(args, adapter, body, origin)
            write_fixtures(args.folder, errors=[(item, body)])
            sys.stdout.write(f"{item.file}: kept as a refused body\n")
            return 0
        entry, sliced = make_entry(args.file, origin, body, args.slice, args.note)
        write_fixtures(args.folder, entries=[(entry, sliced)])
    except (CaptureError, archive.ArchiveError, ValueError, KeyError, OSError) as error:
        sys.stderr.write(f"gate_fixtures {args.action} failed: {error}\n")
        return 1
    sys.stdout.write(
        f"{entry.file}: {entry.expected.variant}, {entry.expected.state.value}, "
        f"{entry.expected.rows} rows (captured {iso_utc(entry.captured_at)})\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

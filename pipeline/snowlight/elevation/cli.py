"""The ``snowlight elevation`` command: build the school elevation table, and check its pin.

``snowlight elevation build --directory DIR --out FILE`` reads ``meta.json`` and
``points.bin`` from ``DIR`` (a directory build's schools folder), reads every school's height
from the terrain tiles ``config/elevation.yaml`` names, and writes the table, its report
(``--report``: counts, SHA-256, asset name) and the table block to pin. It fails when more
than ``--max-unknown`` of the schools have no height (tiles that could not be read).
``.github/workflows/elevation.yml`` runs it; nothing else reads the tiles.

``snowlight elevation pinned --table FILE [--directory DIR]`` says whether a table is the
one pinned (exit 0) or not (exit 1); exit 3 when it is not, though built from the very
directory the pinned one was (``DIR``'s content digest is the pin's ``directory_sha256``): the
table does not rebuild the same, which the workflow refuses.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from snowlight.elevation.build import build_table
from snowlight.elevation.pins import DEFAULT_PINS_PATH, asset_name, load_pins
from snowlight.elevation.table import Table, TableError
from snowlight.predict.inputs import read_local
from snowlight.predict.publish import DarkError

EXIT_UNREAD = 2
EXIT_NOT_REBUILT = 3
"""``pinned``: the table differs from the pin built from the same directory."""


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _err(line: str) -> None:
    sys.stderr.write(line + "\n")


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add the ``elevation`` command."""
    parser = subparsers.add_parser(
        "elevation", help="build the school elevation table the predict pass reads"
    )
    commands = parser.add_subparsers(title="elevation commands", metavar="<step>")
    build = commands.add_parser("build", help="read every school's height from terrain tiles")
    build.add_argument("--directory", type=Path, required=True, help="meta.json and points.bin")
    build.add_argument("--out", type=Path, required=True, help="the table file to write")
    build.add_argument("--report", type=Path, help="write the counts and digest as JSON")
    build.add_argument("--pins", type=Path, default=DEFAULT_PINS_PATH)
    build.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    build.add_argument(
        "--max-unknown",
        type=float,
        default=0.001,
        help="fail when more than this share of schools has no height",
    )
    build.set_defaults(handler=run_build)
    pinned = commands.add_parser("pinned", help="whether a table file is the pinned one")
    pinned.add_argument("--table", type=Path, required=True)
    pinned.add_argument("--pins", type=Path, default=DEFAULT_PINS_PATH)
    pinned.add_argument(
        "--directory", type=Path, help="the directory the table was built from (meta.json)"
    )
    pinned.set_defaults(handler=run_pinned)


def pin_block(
    url: str, sha256: str, schools: int, unknown: int, directory_sha256: str | None = None
) -> str:
    """The ``table`` block of ``config/elevation.yaml`` for a table at ``url``."""
    return (
        "table:\n"
        f'  url: "{url}"\n'
        f'  sha256: "{sha256}"\n'
        f"  schools: {schools}\n"
        f"  unknown: {unknown}\n"
        + (f'  directory_sha256: "{directory_sha256}"\n' if directory_sha256 else "")
    )


def run_build(args: argparse.Namespace) -> int:  # pragma: no cover - the terrain tiles
    """Build the table (see the module docstring)."""
    pins = load_pins(args.pins)
    try:
        directory = read_local(args.directory)
    except DarkError as error:
        _err(f"elevation: the directory does not read ({error})")
        return EXIT_UNREAD
    if directory.school_ids is None:
        _err("elevation: the directory names no school ids")
        return EXIT_UNREAD
    points = directory.points

    def progress(done: int, total: int) -> None:
        if done % 1000 == 0 or done == total:
            _out(f"elevation: {done:,} of {total:,} tiles")

    built = build_table(
        directory.school_ids,
        points.lon_e6.tolist(),
        points.lat_e6.tolist(),
        url=pins.source.url,
        zoom=pins.source.zoom,
        workers=args.workers,
        progress=progress,
    )
    data = built.table.to_bytes()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    sha256 = hashlib.sha256(data).hexdigest()
    schools, unknown = len(built.table.rows), built.table.unknown
    for problem in built.problems[:20]:
        _err(f"elevation: {problem}")
    report = {
        "schools": schools,
        "unknown": unknown,
        "tiles": built.tiles,
        "unread_tiles": len(built.problems),
        "sha256": sha256,
        "asset": asset_name(sha256),
        "bytes": len(data),
        "tiles_sha256": built.table.tiles_sha256,
        "directory_sha256": directory.content_sha256,
    }
    if args.report is not None:
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    _out(
        f"elevation: {schools:,} schools, {unknown:,} with no height, {built.tiles:,} tiles "
        f"({len(built.problems):,} unread), {len(data):,} bytes, sha256 {sha256}"
    )
    if unknown > args.max_unknown * schools:
        _err(f"elevation: {unknown:,} schools have no height, more than {args.max_unknown:.1%}")
        return 1
    return 0


def run_pinned(args: argparse.Namespace) -> int:
    """Exit 0 when the table file is the pinned table, 1 when not (or none is pinned), 3 when
    not though built from the pinned table's directory (see the module docstring)."""
    pins = load_pins(args.pins)
    data = args.table.read_bytes()
    try:
        table = Table.from_bytes(data)
    except TableError as error:
        _err(f"elevation: {error}")
        return EXIT_UNREAD
    sha256 = hashlib.sha256(data).hexdigest()
    if pins.table is None:
        _out(f"elevation: no table is pinned; this one is {sha256}")
        return 1
    same = (
        pins.table.sha256 == sha256
        and pins.table.schools == len(table.rows)
        and pins.table.unknown == table.unknown
    )
    _out(
        f"elevation: this table is {'the pinned one' if same else 'not the pinned one'} "
        f"({sha256}; pinned {pins.table.sha256})"
    )
    if same:
        return 0
    if pins.table.directory_sha256 is not None and args.directory is not None:
        try:
            built_from = read_local(args.directory).content_sha256
        except (DarkError, OSError) as error:
            _err(f"elevation: the directory does not read ({error})")
            return EXIT_UNREAD
        if built_from == pins.table.directory_sha256:
            _out(
                "elevation: it was built from the pinned table's directory "
                f"({built_from}), so the table does not rebuild the same"
            )
            return EXIT_NOT_REBUILT
    return 1

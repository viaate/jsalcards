"""The site's reader decodes exactly what the pipeline writes.

``web/src/types/generated/consumer.check.ts`` is the TypeScript reader that
``npm run check`` compiles against the generated types. Here Node runs it (with
its built-in type stripping) on bytes the Python models wrote, and every decoded
row must equal what :meth:`ClosingsFile.closings` decodes. The status lookup
must also show a school as open only where live/covered.json covers it.

Node 22.6 or later is needed; with an older Node these tests are skipped, and the
type check in ``npm run check`` still covers the reader's types.
"""

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from schemas.helpers import example_path
from schemas.synthetic import synthetic_closings, synthetic_closings_across_time_zones
from snowlight.schemas.export import REPO_ROOT
from snowlight.schemas.live import Closing, ClosingsFile, CoveredFile

GENERATED = REPO_ROOT / "web" / "src" / "types" / "generated"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

DRIVER = """
import { readFileSync } from 'node:fs';
const { decodeDay, readRow, rowOf, statusOn } = await import('./consumer.ts');
const read = (path) => JSON.parse(readFileSync(path, 'utf8'));
const closings = read(process.argv[2]);
const rows = [];
for (const group of closings.days) {
  const day = decodeDay(group);
  for (let row = 0; row < day.schools.length; row += 1) {
    const school = day.schools[row];
    if (rowOf(day, school) !== row) throw new Error(`rowOf(${school}) is not ${row}`);
    const read = readRow(closings, day, row);
    rows.push([
      school, group.day, read.status, read.announcedAt?.toISOString() ?? null,
      read.reason, read.shiftMinutes, read.clock,
    ]);
  }
}
const lookups = [];
if (process.argv[3] !== undefined) {
  const meta = read(process.argv[3]);
  const covered = read(process.argv[4]);
  for (const day of closings.days.map((group) => group.day)) {
    for (let school = 0; school < meta.count; school += 1) {
      const found = statusOn(school, day, meta, closings, covered);
      lookups.push([school, day, found === null || found === 'open' ? found : found.status]);
    }
  }
}
process.stdout.write(JSON.stringify({ rows, lookups }));
"""


def _reader(tmp_path: Path) -> Path:
    """The consumer and the types it imports, laid out so Node can load them."""
    folder = tmp_path / "reader"
    folder.mkdir()
    shutil.copy(GENERATED / "index.ts", folder / "index.ts")
    source = (GENERATED / "consumer.check.ts").read_text(encoding="utf-8")
    assert source.count("from './index';") == 2
    (folder / "consumer.ts").write_text(
        source.replace("from './index';", "from './index.ts';"), encoding="utf-8"
    )
    (folder / "drive.mjs").write_text(DRIVER, encoding="utf-8")
    return folder


def _decode_in_node(tmp_path: Path, closings: Path, *lookup: Path) -> Any:
    assert NODE is not None
    folder = _reader(tmp_path)
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            NODE,
            "--experimental-strip-types",
            "--no-warnings",
            str(folder / "drive.mjs"),
            str(closings),
            *map(str, lookup),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0 and (
        "strip-types" in result.stderr or "Unknown file extension" in result.stderr
    ):
        pytest.skip("this Node cannot run TypeScript; npm run check still type-checks it")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _expected(document: ClosingsFile) -> list[list[Any]]:
    def clock(row: Closing) -> str | None:
        if row.clock_minute is None:
            return None
        return f"{row.clock_minute // 60}:{row.clock_minute % 60:02d}"

    return [
        [
            row.school,
            row.day.isoformat(),
            int(row.status),
            None
            if row.announced_at is None
            else row.announced_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            None if row.reason is None else int(row.reason),
            row.shift_minutes,
            clock(row),
        ]
        for row in document.closings()
    ]


def test_the_reader_decodes_the_example_and_shows_open_only_where_covered(
    tmp_path: Path,
) -> None:
    closings = ClosingsFile.from_json_bytes(example_path("closings").read_bytes())
    covered = CoveredFile.from_json_bytes(example_path("covered").read_bytes())
    decoded = _decode_in_node(
        tmp_path,
        example_path("closings"),
        example_path("school-directory"),
        example_path("covered"),
    )
    assert decoded["rows"] == _expected(closings)
    status = {(row.school, row.day.isoformat()): int(row.status) for row in closings.closings()}
    expected = [
        [
            school,
            group.day.isoformat(),
            status.get((school, group.day.isoformat()), "open" if covered.covers(school) else None),
        ]
        for group in closings.days
        for school in range(closings.directory.schools)
    ]
    assert decoded["lookups"] == expected
    assert [school for school, _, found in expected if found is None] == [4]
    assert [found for _, _, found in expected].count("open") == 4


PAYLOADS: dict[str, Callable[[], ClosingsFile]] = {
    "today-and-tomorrow": lambda: synthetic_closings(30_000),
    "across-time-zones": lambda: synthetic_closings_across_time_zones(30_000),
}


@pytest.mark.parametrize("name", sorted(PAYLOADS))
def test_the_reader_decodes_sixty_thousand_rows_as_written(tmp_path: Path, name: str) -> None:
    document = PAYLOADS[name]()
    path = tmp_path / "closings.json"
    path.write_bytes(document.to_json_bytes())
    decoded = _decode_in_node(tmp_path, path)
    assert len(decoded["rows"]) == 60_000
    assert decoded["rows"] == _expected(document)

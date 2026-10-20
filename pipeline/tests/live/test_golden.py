"""T17, the pipeline half: the golden closings file, written by the publisher from a SYNTHETIC
storm, and its rows file, which web/src/data/tests/closings.contract.test.ts reads back.

Set SNOWLIGHT_WRITE_GOLDEN=1 to write them again after a deliberate change.
"""

import json
import os
from datetime import timedelta
from pathlib import Path

from live.world import ALPHA_DISTRICT, ALPHA_SCHOOL, World, at, row
from snowlight.live.edition import EditionState, EditionVerdict
from snowlight.live.publish import CLOSINGS, Exit, LivePublisher, Mode
from snowlight.live.publishers import DirPublisher
from snowlight.output import JSONValue, dumps_json
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import ClosingsFile

GOLDEN = Path(__file__).parent / "golden"
NAME = "synthetic_closings"
NOW = at("2026-11-17 11:05")
STAMP = DirectoryStamp.model_validate({"generated_on": "2026-10-14", "schools": 11, "districts": 6})


def _storm() -> World:
    """A SYNTHETIC storm morning with every status kind, a delay's times and a next day."""
    world = World()
    world.read(NOW - timedelta(days=1), [])
    # read a day apart: no "Posted" time for this row (its interval is a day long), and its
    # stated day keeps every reading in the interval the same
    eastern = row("SYNTHETIC Eastern School", "Remote learning Nov 17 due to snow")
    world.read(NOW - timedelta(minutes=10), [eastern])
    world.read(
        NOW,
        [
            row(ALPHA_SCHOOL, "Closed due to snow"),
            row(ALPHA_DISTRICT, "Closed tomorrow due to snow"),
            row("SYNTHETIC Pacific School", "2 hour delay due to snow"),
            eastern,
            row("SYNTHETIC Split School", "Early dismissal due to snow"),
        ],
    )
    return world


def _rows(file: ClosingsFile) -> list[JSONValue]:
    return [
        {
            "school": closing.school,
            "day": closing.day.isoformat(),
            "status": int(closing.status),
            "announced_at": None
            if closing.announced_at is None
            else closing.announced_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reason": None if closing.reason is None else int(closing.reason),
            "shift_minutes": closing.shift_minutes,
            "clock_minute": closing.clock_minute,
        }
        for closing in sorted(file.closings(), key=lambda item: (item.day, item.school))
    ]


def written(tmp_path: Path) -> tuple[bytes, bytes]:
    world = _storm()
    publisher = LivePublisher(
        host=DirPublisher(tmp_path / "host"),
        directory=world.dir,
        state_dir=tmp_path / "state",
        internal_dir=tmp_path / "internal",
        mode=Mode.ON,
    )
    verdict = EditionVerdict(EditionState.EQUAL, NOW, stamp=STAMP, deployed=STAMP)
    report = publisher.publish(world.publish(NOW), now=NOW, healthy_share=1.0, edition=verdict)
    assert report.exit is Exit.OK
    data = (tmp_path / "host" / "v1" / CLOSINGS).read_bytes()
    file = ClosingsFile.from_json_bytes(data)
    pretty = json.dumps(json.loads(data), indent=2, sort_keys=True).encode() + b"\n"
    rows = json.dumps(_rows(file), indent=2, sort_keys=True).encode() + b"\n"
    return pretty, rows


def test_t17_the_golden_file_is_what_the_publisher_writes(tmp_path: Path) -> None:
    pretty, rows = written(tmp_path)
    golden, golden_rows = GOLDEN / f"{NAME}.json", GOLDEN / f"{NAME}.rows.json"
    if os.environ.get("SNOWLIGHT_WRITE_GOLDEN") == "1":
        GOLDEN.mkdir(exist_ok=True)
        golden.write_bytes(pretty)
        golden_rows.write_bytes(rows)
    assert golden.read_bytes() == pretty
    assert golden_rows.read_bytes() == rows


def test_t17_the_golden_file_covers_every_kind_and_both_days() -> None:
    file = ClosingsFile.from_json_bytes(
        dumps_json(json.loads((GOLDEN / f"{NAME}.json").read_text()))
    )
    closings = file.closings()
    assert {closing.status.name for closing in closings} == {
        "CLOSED",
        "DELAYED",
        "REMOTE",
        "EARLY_DISMISSAL",
    }
    assert len({closing.day for closing in closings}) == 2
    assert any(closing.shift_minutes and closing.clock_minute for closing in closings)
    assert any(closing.announced_at is not None for closing in closings)
    assert any(closing.announced_at is None for closing in closings)
    assert file.directory == STAMP

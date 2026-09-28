"""Shared fixtures for the listed-coverage tests.

The files under ``fixtures/`` are real: rows, reads and roster bodies sliced from
the files the pipeline read (see ``fixtures/PROVENANCE.json``). Anything made up
for a test is built in the test itself and named SYNTHETIC there.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from snowlight.listed.evidence import ListRow, section_of, utc_text
from snowlight.listed.located import stated_places
from snowlight.listed.scope import Context

FIXTURES = Path(__file__).parent / "fixtures"
DIRECTORY = Path(__file__).resolve().parents[2] / "out" / "internal" / "directory"
"""The school directory ``snowlight directory build`` writes (never committed)."""

needs_directory = pytest.mark.skipif(
    not (DIRECTORY / "schools.parquet").exists(), reason="the NCES directory is not built here"
)


def _lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def fixture_rows() -> list[ListRow]:
    """The real Kansas City (and guard) rows, each tied to its recorded read.

    The fixture holds only some rows of each read, so they are tied here by
    source and read time, as :func:`snowlight.listed.evidence.load_rows` ties
    them, without its whole-read count check.
    """
    reads = {
        (str(r["source_id"]), utc_text(str(r["fetched_at"]))): r
        for r in _lines(FIXTURES / "kc" / "reads.jsonl")
    }
    rows: list[ListRow] = []
    for item in _lines(FIXTURES / "kc" / "rows.jsonl"):
        read = reads[(str(item["source_id"]), utc_text(str(item["fetched_at"])))]
        extra = item["raw_extra"]
        assert isinstance(extra, dict)
        rows.append(
            ListRow(
                source_id=str(item["source_id"]),
                mode=str(read["mode"]),
                fetched_at=utc_text(str(item["fetched_at"])),
                read_sha256=str(read["sha256"]),
                variant=str(read["variant"]),
                name=str(item["raw_name"]),
                status=str(item["raw_status"]),
                section=section_of(str(read["variant"]), extra),
                places=stated_places(str(read["variant"]), extra),
            )
        )
    return rows


def fixture_contexts() -> dict[str, Context]:
    """Each fixture station's registry context (``fixtures/kc/contexts.json``)."""
    data = json.loads((FIXTURES / "kc" / "contexts.json").read_text(encoding="utf-8"))
    return {
        station: Context(
            market=station,
            states=tuple(item["states"]),
            counties=tuple(item["counties"]) if item["counties"] is not None else None,
        )
        for station, item in data.items()
    }


@pytest.fixture(scope="session")
def kc_rows() -> list[ListRow]:
    """The real rows of ``fixtures/kc``."""
    return fixture_rows()


@pytest.fixture(scope="session")
def contexts() -> dict[str, Context]:
    """The fixture stations' registry contexts."""
    return fixture_contexts()


@pytest.fixture
def rows_named(kc_rows: list[ListRow]) -> Callable[[str, str], list[ListRow]]:
    """The fixture rows of one station with one name."""

    def pick(station: str, name: str) -> list[ListRow]:
        found = [row for row in kc_rows if row.source_id == station and row.name == name]
        assert found, f"no fixture row {station!r} {name!r}"
        return found

    return pick

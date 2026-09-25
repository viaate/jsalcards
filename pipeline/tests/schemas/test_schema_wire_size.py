"""The live closings file stays small: 30,000 affected schools in at most 400 KB gzipped.

Each of the 30,000 distinct schools has a row for today and a row for tomorrow,
the most rows a school can have (a multi-day storm). The payloads are synthetic
(see :mod:`schemas.synthetic`) and built as worst cases for compression. Sizes are
measured on the exact bytes ``to_json_bytes`` writes, at gzip level 6 (what static
hosts typically serve) and level 9.
"""

import gzip
import json
import time
from collections import Counter
from collections.abc import Callable

import pytest

from schemas.synthetic import (
    SYNTHETIC_DIRECTORY_SIZE,
    SYNTHETIC_GENERATED_AT,
    SYNTHETIC_TODAY,
    SYNTHETIC_TOMORROW,
    synthetic_closings,
    synthetic_closings_across_time_zones,
    synthetic_stamp,
)
from snowlight.schemas.live import ClosingsFile, CoveredFile, ranges_from_indices
from snowlight.schemas.vocab import Status

AFFECTED = 30_000
DAYS_PER_SCHOOL = 2
BUDGET_GZIP_BYTES = 400_000

PAYLOADS: dict[str, Callable[[], ClosingsFile]] = {
    # Every status, reason and time at random, each school today and tomorrow.
    "today-and-tomorrow": lambda: synthetic_closings(AFFECTED),
    # The same, spread over the three local days a file can hold at night.
    "across-time-zones": lambda: synthetic_closings_across_time_zones(AFFECTED),
    # Every row a delay or early dismissal, with a random shift and clock time.
    "all-delays-and-dismissals": lambda: synthetic_closings(
        AFFECTED, statuses=(Status.DELAYED, Status.EARLY_DISMISSAL)
    ),
}


@pytest.fixture(scope="module", params=sorted(PAYLOADS))
def payload(request: pytest.FixtureRequest) -> tuple[str, bytes]:
    name: str = request.param
    return name, PAYLOADS[name]().to_json_bytes()


@pytest.fixture(scope="module")
def closings_bytes() -> bytes:
    return synthetic_closings(AFFECTED).to_json_bytes()


def test_thirty_thousand_schools_over_two_days_fit_the_budget(
    payload: tuple[str, bytes], capsys: pytest.CaptureFixture[str]
) -> None:
    name, data = payload
    level6 = len(gzip.compress(data, compresslevel=6, mtime=0))
    level9 = len(gzip.compress(data, compresslevel=9, mtime=0))
    with capsys.disabled():
        print(  # noqa: T201 - the measurement is the point of this test
            f"\nclosings.json {name}, {AFFECTED:,} schools x {DAYS_PER_SCHOOL} days: "
            f"{len(data):,} bytes, {level6:,} gzip -6, {level9:,} gzip -9 "
            f"(budget {BUDGET_GZIP_BYTES:,})"
        )
    assert level6 <= BUDGET_GZIP_BYTES
    assert level9 <= level6


def test_payloads_are_what_they_claim(payload: tuple[str, bytes]) -> None:
    name, data = payload
    document = ClosingsFile.from_json_bytes(data)
    rows = document.closings()
    per_school = Counter(row.school for row in rows)
    assert len(per_school) == AFFECTED
    assert set(per_school.values()) == {DAYS_PER_SCHOOL}
    assert len(rows) == AFFECTED * DAYS_PER_SCHOOL
    assert len(document.days) == (3 if name == "across-time-zones" else 2)
    if name == "all-delays-and-dismissals":
        assert all(row.shift_minutes is not None for row in rows)
        assert all(row.clock_minute is not None for row in rows)
    else:
        assert set(Counter(row.status for row in rows)) == set(Status)
        assert sum(row.reason is None for row in rows) > 0


def test_today_and_tomorrow_are_stated_once(closings_bytes: bytes) -> None:
    value = json.loads(closings_bytes)
    assert [group["day"] for group in value["days"]] == [
        SYNTHETIC_TODAY.isoformat(),
        SYNTHETIC_TOMORROW.isoformat(),
    ]
    assert closings_bytes.count(f'"{SYNTHETIC_TODAY.isoformat()}"'.encode()) == 1
    assert all(len(group["gaps"]) == AFFECTED for group in value["days"])


def test_serialization_is_deterministic(closings_bytes: bytes) -> None:
    assert synthetic_closings(AFFECTED).to_json_bytes() == closings_bytes


def test_row_order_is_the_documents_not_the_callers(closings_bytes: bytes) -> None:
    document = ClosingsFile.from_json_bytes(closings_bytes)
    rows = document.closings()
    shuffled = rows[1::2] + rows[::2]
    again = ClosingsFile.encode(
        reversed(shuffled), generated_at=SYNTHETIC_GENERATED_AT, directory=synthetic_stamp()
    )
    assert again == document


def test_validating_sixty_thousand_rows_is_quick(closings_bytes: bytes) -> None:
    started = time.perf_counter()
    ClosingsFile.from_json_bytes(closings_bytes)
    assert time.perf_counter() - started < 2.0


def test_covered_file_for_a_full_directory_is_tiny() -> None:
    # Every other school covered: the worst case for runs.
    covered = CoveredFile(
        schema_version=1,
        generated_at=SYNTHETIC_GENERATED_AT,
        directory=synthetic_stamp(),
        ranges=ranges_from_indices(range(0, SYNTHETIC_DIRECTORY_SIZE, 2)),
    )
    size = len(gzip.compress(covered.to_json_bytes(), compresslevel=6, mtime=0))
    assert size <= BUDGET_GZIP_BYTES

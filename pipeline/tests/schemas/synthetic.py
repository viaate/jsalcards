"""Synthetic documents for the size and property tests. Nothing here is real data.

:func:`synthetic_closings` builds a worst case for compression rather than a
typical storm: schools drawn uniformly from a 120,000-school directory (a real
storm clusters them by state, which compresses better), and every value of every
row drawn at random on its own, including the row for the second day, where a
real school mostly repeats its first day's status, reason and time. Statuses are
uniform over the four codes, reasons uniform over the eight codes and none, the
announcement a random second in the three days before ``generated_at``, and every
delay and early dismissal states both a random shift and a random clock time.
"""

import random
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import Closing, ClosingsFile
from snowlight.schemas.vocab import SHIFTED, Reason, Status

SYNTHETIC_DIRECTORY_SIZE = 120_000
SYNTHETIC_DISTRICTS = 13_500
# 13:05 UTC is 08:05 in New York and 05:05 in Los Angeles: every school's local
# today is January 12 and its tomorrow January 13.
SYNTHETIC_GENERATED_AT = datetime(2027, 1, 12, 13, 5, 17, tzinfo=UTC)
SYNTHETIC_TODAY = date(2027, 1, 12)
SYNTHETIC_TOMORROW = date(2027, 1, 13)
ANNOUNCED_WINDOW = timedelta(days=3)
REASONS: tuple[Reason | None, ...] = (None, *Reason)


def synthetic_stamp(schools: int = SYNTHETIC_DIRECTORY_SIZE) -> DirectoryStamp:
    """A directory stamp for a synthetic directory of ``schools`` schools."""
    return DirectoryStamp(
        generated_on=date(2026, 9, 24), schools=schools, districts=SYNTHETIC_DISTRICTS
    )


def synthetic_row(
    rng: random.Random,
    school: int,
    day: date,
    *,
    generated_at: datetime = SYNTHETIC_GENERATED_AT,
    statuses: Sequence[Status] = tuple(Status),
) -> Closing:
    """One synthetic row with every field drawn at random."""
    status = rng.choice(statuses)
    shifted = status in SHIFTED
    seconds = rng.randint(0, int(ANNOUNCED_WINDOW.total_seconds()))
    return Closing(
        school=school,
        day=day,
        status=status,
        announced_at=generated_at - timedelta(seconds=seconds),
        reason=rng.choice(REASONS),
        shift_minutes=rng.randint(30, 240) if shifted else None,
        clock_minute=rng.randint(540, 840) if shifted else None,
    )


def synthetic_schools(count: int, seed: int) -> list[int]:
    """``count`` distinct school indexes drawn uniformly from the synthetic directory."""
    rng = random.Random(seed)  # noqa: S311 - synthetic test data, not cryptography
    return rng.sample(range(SYNTHETIC_DIRECTORY_SIZE), count)


def synthetic_rows(
    count: int,
    seed: int,
    *,
    days: Sequence[date] = (SYNTHETIC_TODAY, SYNTHETIC_TOMORROW),
    statuses: Sequence[Status] = tuple(Status),
) -> list[Closing]:
    """A row on each of ``days`` for each of ``count`` distinct random schools."""
    rng = random.Random(seed + 1)  # noqa: S311 - synthetic test data
    return [
        synthetic_row(rng, school, day, statuses=statuses)
        for school in synthetic_schools(count, seed)
        for day in days
    ]


def synthetic_closings(
    count: int,
    seed: int = 20270112,
    *,
    statuses: Sequence[Status] = tuple(Status),
) -> ClosingsFile:
    """A synthetic ``live/closings.json``: ``count`` schools, each today and tomorrow."""
    return ClosingsFile.encode(
        synthetic_rows(count, seed, statuses=statuses),
        generated_at=SYNTHETIC_GENERATED_AT,
        directory=synthetic_stamp(),
    )


# 06:30 UTC is 01:30 in New York and 22:30 the day before in Los Angeles, so the
# East's today is the West's tomorrow and the file holds three local days.
SYNTHETIC_SPLIT_AT = datetime(2027, 1, 12, 6, 30, 41, tzinfo=UTC)


def synthetic_closings_across_time_zones(count: int, seed: int = 20270112) -> ClosingsFile:
    """``count`` schools, each today and tomorrow, half in the East and half in the West.

    Eastern schools have rows for January 12 and 13, western ones for January 11
    and 12: three day groups, the most a file can hold.
    """
    rng = random.Random(seed + 2)  # noqa: S311 - synthetic test data
    west = (SYNTHETIC_TODAY - timedelta(days=1), SYNTHETIC_TODAY)
    east = (SYNTHETIC_TODAY, SYNTHETIC_TOMORROW)
    rows = [
        synthetic_row(rng, school, day, generated_at=SYNTHETIC_SPLIT_AT)
        for school in synthetic_schools(count, seed)
        for day in rng.choice((west, east))
    ]
    return ClosingsFile.encode(rows, generated_at=SYNTHETIC_SPLIT_AT, directory=synthetic_stamp())

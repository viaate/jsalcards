"""The five local time blocks of a day, and which block and day a local clock time falls in.

A block's day is the local date it starts on: the night block of a date runs from 21:00 that
date to 05:00 the next morning, so a departure at 00:30 on the 6th is in the night of the 5th
(what people call "tonight" on the 5th).
"""

from datetime import date, timedelta
from enum import IntEnum
from typing import Final


class Block(IntEnum):
    """A local time block (D6): early 5-9, morning 9-12, afternoon 12-17, evening 17-21,
    night 21-5."""

    EARLY = 0
    MORNING = 1
    AFTERNOON = 2
    EVENING = 3
    NIGHT = 4


BLOCKS: Final = tuple(Block)
"""Every block, in the day's order."""

STARTS: Final[dict[Block, int]] = {
    Block.EARLY: 5,
    Block.MORNING: 9,
    Block.AFTERNOON: 12,
    Block.EVENING: 17,
    Block.NIGHT: 21,
}
"""Each block's first local hour."""

HOURS: Final[dict[Block, tuple[int, ...]]] = {
    Block.EARLY: (5, 6, 7, 8),
    Block.MORNING: (9, 10, 11),
    Block.AFTERNOON: (12, 13, 14, 15, 16),
    Block.EVENING: (17, 18, 19, 20),
    Block.NIGHT: (21, 22, 23, 0, 1, 2, 3, 4),
}
"""The local hours of each block (the night's last five are on the next calendar date)."""

DAY_START_HOUR: Final = 5
"""A block day begins at 05:00 local."""


def block_of_hour(hour: int) -> Block:
    """The block a local hour (0-23) falls in."""
    if not 0 <= hour <= 23:  # noqa: PLR2004 - the hours of a day
        raise ValueError(f"not an hour of the day: {hour}")
    for block in (Block.NIGHT, Block.EVENING, Block.AFTERNOON, Block.MORNING, Block.EARLY):
        if hour >= STARTS[block]:
            return block
    return Block.NIGHT


def block_day(calendar_day: date, hour: int) -> date:
    """The block day of a local clock time: the calendar date, or the day before before 05:00."""
    return calendar_day - timedelta(days=1) if hour < DAY_START_HOUR else calendar_day


def hhmm_hour(hhmm: int) -> int:
    """The hour of a BTS clock time such as 1640 (2400 is midnight)."""
    if not 0 <= hhmm <= 2400:  # noqa: PLR2004 - BTS writes midnight as 2400
        raise ValueError(f"not a clock time: {hhmm}")
    return (hhmm // 100) % 24

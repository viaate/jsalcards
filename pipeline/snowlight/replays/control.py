"""The D+7 control: the captures that fed a day must light nothing a week later.

The control re-runs the day's steps over the same captures (those in D's
window) with the target day set to D+7. Any school lit then would mean a date
was resolved wrongly somewhere, so the day bar (A5) asks for 0. The date-range
gate (every stated date within six days after the capture) already rules D+7
out, so the control also reports how many rows the reader gave an entry for
D+7 before the gates, for the critic to read.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

CONTROL_DAYS: Final = 7


@dataclass(frozen=True, slots=True)
class ControlResult:
    """What the D+7 control lit."""

    day: date
    target: date
    lit: int
    """Schools lit for the target day (must be 0)."""
    entries: int
    """Rows the reader gave an entry for the target day, before the claim gates (a district row
    that names part of the district counts, though it lights none of its schools)."""

    @property
    def passed(self) -> bool:
        """Whether the control lit nothing."""
        return self.lit == 0


type Lighter = Callable[[date], tuple[int, int]]
"""Runs the day's steps over D's captures for a target day: (schools lit, rows with an entry)."""


def control_day(day: date, light: Lighter) -> ControlResult:
    """Run the D+7 control for ``day`` with ``light`` (see :data:`Lighter`)."""
    target = day + timedelta(days=CONTROL_DAYS)
    lit, entries = light(target)
    return ControlResult(day=day, target=target, lit=lit, entries=entries)

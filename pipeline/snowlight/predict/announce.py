"""When a district usually posts its decision: the forecast's ``announces_at`` (S7 spec, piece 3).

From the archive (:mod:`snowlight.predict.posts`): each day a list's own posted or updated
stamp says when one of the district's rows was posted (``posted_at``). The time of day is kept
as minutes from midnight of the school day, local, when it falls between 18:00 the evening
before and the end of the morning read window (a stamp the morning before, or a day earlier,
is a district deciding a day ahead, which this time does not describe). With at least
:data:`MIN_DAYS` such days, the district's usual time is their median (the lower middle day
of an even count, so it is a time the district did post at); otherwise it has none and
``announces_at`` stays null.

Serving puts that time on each school day in the district's zone. Only the minutes are kept,
by LEAID: no list, no text.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

MIN_DAYS: Final = 3
EVENING_FROM: Final = -6 * 60
"""18:00 the evening before, in minutes from the school day's midnight."""


def minutes_of(posted: datetime, day: date, zone: str) -> int:
    """``posted`` as whole minutes from midnight of ``day`` in ``zone`` (negative: the evening
    before)."""
    local = posted.astimezone(ZoneInfo(zone))
    return (local.date() - day).days * 1440 + local.hour * 60 + local.minute


def usual_minutes(
    posts: Iterable[tuple[str, date, datetime]],
    zone_of: Mapping[str, str],
    until: time,
    min_days: int = MIN_DAYS,
) -> dict[str, int]:
    """Each district's usual posting time (see the module docstring), from (district, day,
    posted at) rows; one row per district and day (the earliest stamp of that day)."""
    end = until.hour * 60 + until.minute
    by_district: dict[str, dict[date, int]] = defaultdict(dict)
    for district, day, posted in posts:
        zone = zone_of.get(district)
        if zone is None:
            continue
        minute = minutes_of(posted, day, zone)
        if not EVENING_FROM <= minute < end:
            continue
        mine = by_district[district]
        mine[day] = min(minute, mine.get(day, minute))
    found: dict[str, int] = {}
    for district, days in sorted(by_district.items()):
        if len(days) < min_days:
            continue
        ordered = sorted(days.values())
        found[district] = ordered[(len(ordered) - 1) // 2]
    return found


def announces_at(minutes: int | None, day: date, zone: str) -> datetime | None:
    """The instant a district usually posts for ``day`` (``None`` without a usual time)."""
    if minutes is None:
        return None
    midnight = datetime.combine(day, time(), tzinfo=ZoneInfo(zone))
    return (midnight + timedelta(minutes=minutes)).astimezone(UTC)

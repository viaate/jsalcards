"""The neighbors term live: the districts next door already posted closed or remote (S7 spec,
piece 3).

The term was trained on the archive's snapshots (:mod:`snowlight.predict.posts`): the share
of a district's neighbors (the file's ``neighbors``, nearest first, at most 12) that had
canceled by the morning pass, for a district that had posted nothing by then. A pass reads the
same share from ``live/closings.json`` by the same rule (:func:`snowlight.predict.posts.
counts_as_no_school`, :func:`snowlight.predict.posts.no_school_at`): a neighbor has canceled
when at least ``share`` (the label's no-school share, half) of its eligible schools have a
closed or remote row for the day with a weather reason or none named; one building closed
for a water main break is not its district canceling. The district's own share is not read
once any of its eligible schools has a row (any status, as training drops a district at its
first status of any kind): its level is unknown and the term adds nothing.

A closings file for another directory, one older than ``max_age`` or from the future, or none
at all says nothing: every level is unknown (no neighbors line), never "none posted".
"""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import numpy.typing as npt

from snowlight.predict.posts import counts_as_no_school
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import ClosingsFile
from snowlight.schemas.vocab import Status


@dataclass(frozen=True, slots=True)
class Posted:
    """One district's neighbors that posted closed or remote for a day."""

    share: float
    """Of its neighbors (0 with none)."""
    status: Status
    """The status most of them posted (closed on a tie)."""
    districts: tuple[int, ...]
    """The neighbors that posted :attr:`status`, nearest first."""


@dataclass(frozen=True, slots=True)
class Neighbors:
    """What the closings file says of each district's neighbors, by day."""

    by_day: Mapping[date, Mapping[int, Posted]] = field(default_factory=dict)
    read: bool = False
    """Whether a usable closings file was read (else every share is unknown)."""

    def get(self, day: date, district: int) -> Posted | None:
        """A district's neighbors that posted on ``day`` (``None``: unknown)."""
        if not self.read:
            return None
        return self.by_day.get(day, {}).get(district)


UNREAD = Neighbors()


def _canceled(
    closings: ClosingsFile,
    day: date,
    owner: npt.NDArray[np.int64],
    eligible: Sequence[npt.NDArray[np.int64]],
    share: float,
) -> tuple[dict[int, Counter[Status]], set[int]]:
    """The districts that canceled ``day`` by the label's rule, with their schools' statuses
    counted, and every district with a row of any status."""
    counted: dict[int, Counter[Status]] = {}
    posted_any: set[int] = set()
    for group in closings.days:
        if group.day != day:
            continue
        for school, status, reason in zip(
            group.schools(), group.statuses, group.reasons, strict=True
        ):
            district = int(owner[school]) if school < owner.size else -1
            if district < 0:
                continue
            posted_any.add(district)
            if counts_as_no_school(status, reason):
                counted.setdefault(district, Counter())[status] += 1
    canceled = {
        district: tally
        for district, tally in counted.items()
        if sum(tally.values()) >= max(1, math.ceil(share * eligible[district].size - 1e-9))
    }
    return canceled, posted_any


def neighbors_posted(  # noqa: PLR0913 - the file, the directory's units and the rule's settings
    closings: ClosingsFile | None,
    *,
    stamp: DirectoryStamp,
    eligible: Sequence[npt.NDArray[np.int64]],
    neighbors: Sequence[Sequence[int]],
    days: Sequence[date],
    now: datetime,
    max_age: timedelta,
    share: float = 0.5,
) -> Neighbors:
    """Each district's :class:`Posted` on ``days`` (see the module docstring); a district that
    posted itself has none (unknown)."""
    if (
        closings is None
        or closings.directory != stamp
        or closings.generated_at > now
        or now - closings.generated_at > max_age
    ):
        return UNREAD
    owner = np.full(stamp.schools, -1, dtype=np.int64)
    for index, schools in enumerate(eligible):
        owner[schools] = index
    by_day: dict[date, dict[int, Posted]] = {}
    for day in days:
        status_of, posted_any = _canceled(closings, day, owner, eligible, share)
        mine: dict[int, Posted] = {}
        for index, near in enumerate(neighbors):
            if index in posted_any:
                continue
            posted = [e for e in near if e in status_of]
            if not near:
                mine[index] = Posted(0.0, Status.CLOSED, ())
                continue
            tally: Counter[Status] = Counter()
            for e in posted:
                tally[status_of[e].most_common(1)[0][0]] += 1
            chosen = Status.CLOSED
            if tally.get(Status.REMOTE, 0) > tally.get(Status.CLOSED, 0):
                chosen = Status.REMOTE
            named = tuple(e for e in posted if status_of[e].most_common(1)[0][0] == chosen)
            mine[index] = Posted(len(posted) / len(near), chosen, named)
        by_day[day] = mine
    return Neighbors(by_day, read=True)

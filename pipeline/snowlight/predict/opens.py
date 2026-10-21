"""The "school is on" rule (contract C3, rule 7): a unit that said it holds school on a day.

The live ingest publishes ``live/opens.json`` (S8: :class:`~snowlight.schemas.live.OpensFile`)
beside ``live/closings.json``: each school's explicit word that it runs as normal on a local
day, never on a school-day the closings file shows a status for. A pass reads both from the
live host, and a unit counts as having said school is on for day ``D`` when:

* a district: every one of its eligible schools has an open statement for ``D`` (a
  statement the district posted for all its schools reaches every one of them). Only then
  is "Riverside said school is on." true of the district: when some of its schools said so
  and others did not, the district did not, and the usual chance stands;
* a private school: it has an open statement for ``D``;

and none of the unit's schools has a posted status on ``D`` in the closings file of the same
publish. Its chance of no school that day then drops to the floor and its delay chance to 0,
and its "How we got" adds a ``said_open`` line taking the rest away (:mod:`~snowlight.predict.
serve`).

The rule never fires on less than both files of one publish, fresh: with no opens file, a
stale one (older than ``max_age``), a closings file from another publish or none, nothing is
said open and the usual chance stands, which is true of its recorded days. An opens file for
another directory that holds statements cannot be read against this one: the pass goes dark
(as a day timeline of another directory does), rather than publish a chance a school said
does not apply.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import numpy.typing as npt

from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import ClosingsFile, OpensFile


class OpensError(RuntimeError):
    """The opens file is for another directory and holds statements (the pass goes dark)."""


@dataclass(frozen=True, slots=True)
class SaidOpen:
    """The units that said school is on, per local day: district positions and private
    schools' directory positions."""

    districts: Mapping[date, frozenset[int]] = field(default_factory=dict)
    schools: Mapping[date, frozenset[int]] = field(default_factory=dict)

    def district(self, day: date, index: int) -> bool:
        """Whether district ``index`` said school is on for ``day``."""
        return index in self.districts.get(day, frozenset())

    def school(self, day: date, position: int) -> bool:
        """Whether the private school at ``position`` said school is on for ``day``."""
        return position in self.schools.get(day, frozenset())


NOTHING_SAID = SaidOpen()


def _posted(closings: ClosingsFile) -> dict[date, frozenset[int]]:
    return {group.day: frozenset(group.schools()) for group in closings.days}


def said_open(  # noqa: PLR0913 - the two files, the units and the rule's settings
    opens: OpensFile | None,
    closings: ClosingsFile | None,
    *,
    stamp: DirectoryStamp,
    eligible: Sequence[npt.NDArray[np.int64]],
    private: npt.NDArray[np.int64],
    now: datetime,
    max_age: timedelta,
) -> SaidOpen:
    """The units that said school is on (see the module docstring). ``eligible`` holds each
    district's eligible school positions; ``private`` the private schools served.

    Raises:
        OpensError: the opens file is for another directory and holds statements.
    """
    if opens is None:
        return NOTHING_SAID
    if opens.directory != stamp:
        if opens.opens:
            raise OpensError("the opens file indexes another directory")
        return NOTHING_SAID
    if now - opens.generated_at > max_age or opens.generated_at > now:
        return NOTHING_SAID
    if (
        closings is None
        or closings.generated_at != opens.generated_at
        or closings.directory != stamp
    ):
        return NOTHING_SAID
    stated: dict[date, set[int]] = defaultdict(set)
    for item in opens.opens:
        stated[item.day].add(item.school)
    posted = _posted(closings)
    districts: dict[date, frozenset[int]] = {}
    schools: dict[date, frozenset[int]] = {}
    served = frozenset(private.tolist())
    for day, said in stated.items():
        shown = posted.get(day, frozenset())
        found: set[int] = set()
        for index, mine in enumerate(eligible):
            if not mine.size:
                continue
            members = mine.tolist()
            if any(school in shown for school in members):
                continue
            if all(school in said for school in members):
                found.add(index)
        districts[day] = frozenset(found)
        schools[day] = frozenset(school for school in said & served if school not in shown)
    return SaidOpen(districts, schools)

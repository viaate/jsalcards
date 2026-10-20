"""The morning record: what each live pass read and named, kept for the automatic learning.

The prediction model learns from the days the live pipeline read
(:mod:`snowlight.predict.live_labels`). A district-day there is ``open`` only when a list that
carries the district was read whole in its morning window, the pass that read it was shown
on the map, and no list named the district that day without the map lighting it. The change
log (:mod:`snowlight.live.history`) keeps what the map showed; this record keeps the rest,
private, in the state folder: one JSON file per UTC day, ``morning/<day>.json``, rewritten
whole and atomically by every pass (:meth:`MorningLog.record`). Per 30-minute UTC slot:

* ``shown``: the prefixes (``v1``, ``v1-shadow``) a pass of the slot was published under:
  its merge is what the map showed (an upload, or an unchanged pass inside the heartbeat).
  A refused, held, blanked or failed pass, or one with publishing off, is never shown.
* ``reads``: only from shown passes, and only between :data:`READ_BAND` (UTC; every US
  morning read window falls inside it): each source the ledger took a whole read of this
  pass (``ok``, ``not_modified`` or ``empty``; a ``partial`` read never), as
  ``[rows, placed, unread]``: its rows present, the rows the matcher placed on a school, and
  the rows the reader found no status in (``not_status``). A pass's reads appear once per
  distinct triple.
* ``unknown``: the states whose statuses a pass withheld whole (``source_unknown``: a source
  whose say was unknown).
* ``named``: per district (LEAID), the days a present row of any source named it for, lit or
  not (``*``: a row that lights no day of its own: withheld, undated, or a dissent of every
  day), each with the status kinds the naming could mean (:func:`naming`): a lit row's claim
  kinds for its days; a withheld row's status kinds when its words name status kinds only;
  :data:`ANY_KIND` for a dissent, or a withheld row whose words are unsure or unread. A row
  that only says school is open names nothing.

``through`` is the last pass recorded. A file that does not read is never trusted again: the
next pass marks it ``damaged`` (what it lost cannot be told), and no district-day of that UTC
day is labeled. Files older than :data:`KEEP_DAYS` are pruned. The record holds codes, ids,
counts and times only (no names, no list text).
"""

import json
import logging
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Final

from snowlight.live.guards import Withheld
from snowlight.live.resolve import Derived, Resolved
from snowlight.output import JSONValue, dumps_json, write_bytes_atomic
from snowlight.schemas.vocab import STATUS_BY_KIND

LOG: Final = logging.getLogger(__name__)
SLOT_MINUTES: Final = 30
READ_BAND: Final = (time(9, 0), time(21, 0))
"""The UTC hours whose reads are kept: 06:30-09:30 local in every US zone falls inside."""
KEEP_DAYS: Final = 10
SCHEMA_VERSION: Final = 2
EVERY_DAY: Final = "*"
ANY_KIND: Final = "?"
"""A naming whose status cannot be told: a dissent, or a withheld row unsure or unread."""
STATUS_KINDS: Final = frozenset(STATUS_BY_KIND)
KINDS: Final = STATUS_KINDS | {ANY_KIND}
UNPLACED: Final = frozenset({Withheld.UNMATCHED, Withheld.REJECTED_MATCH, Withheld.LOCATED})
"""Rows the matcher did not place on a school."""
OPEN_ONLY: Final = frozenset({"open"})

READ_PARTS: Final = 3
type Read = tuple[int, int, int]
"""One whole read of a source: rows present, rows placed, rows read as no status."""


def slot_of(moment: datetime) -> str:
    """The ``HH:MM`` start of the 30-minute UTC slot ``moment`` falls in."""
    at = moment.astimezone(UTC)
    return f"{at.hour:02d}:{at.minute // SLOT_MINUTES * SLOT_MINUTES:02d}"


def slot_start(day: date, slot: str) -> datetime:
    """The UTC start of ``slot`` on ``day``."""
    hours, minutes = (int(part) for part in slot.split(":"))
    return datetime.combine(day, time(hours, minutes), tzinfo=UTC)


def in_band(moment: datetime) -> bool:
    """Whether ``moment`` is inside :data:`READ_BAND` (UTC)."""
    at = moment.astimezone(UTC).time()
    return READ_BAND[0] <= at < READ_BAND[1]


type Naming = dict[str, set[str]]
"""Day (ISO, or :data:`EVERY_DAY`) to the status kinds named for it (:data:`KINDS`)."""


def naming(derived: Derived) -> Naming:
    """The days a row names its districts for, each with the status kinds it could mean (see
    the module docstring)."""
    if not derived.reach:
        return {}
    found: Naming = defaultdict(set)
    if derived.dissent is not None:
        for day in {day.isoformat() for day in derived.dissent} or {EVERY_DAY}:
            found[day].add(ANY_KIND)
    if derived.withheld is None:
        for claim in derived.claims:
            found[claim.day.isoformat()].add(claim.kind)
        return dict(found)
    words = set(derived.kinds)
    if found:
        return dict(found)
    if words and words <= OPEN_ONLY:
        return {}
    statuses = words & STATUS_KINDS
    if statuses and words <= STATUS_KINDS | OPEN_ONLY:
        return {EVERY_DAY: statuses}
    return {EVERY_DAY: {ANY_KIND}}


def source_read(source: Resolved) -> Read:
    """A source's present rows, placed rows and rows read as no status."""
    rows = placed = unread = 0
    for result in source.rows:
        if not result.present or result.superseded:
            continue
        rows += 1
        withheld = result.derived.withheld
        placed += withheld not in UNPLACED
        unread += withheld is Withheld.NOT_STATUS
    return rows, placed, unread


def named_of(resolved: Iterable[Resolved]) -> dict[str, Naming]:
    """Every district a present row names, with the days and kinds (:func:`naming`)."""
    found: dict[str, Naming] = {}
    for source in resolved:
        for result in source.rows:
            if not result.present or result.superseded:
                continue
            named = naming(result.derived)
            for leaid in result.derived.reach if named else ():
                into = found.setdefault(leaid, {})
                for day, kinds in named.items():
                    into.setdefault(day, set()).update(kinds)
    return found


@dataclass(slots=True)
class Slot:
    """One 30-minute UTC slot of the record."""

    shown: set[str] = field(default_factory=set)
    reads: dict[str, set[Read]] = field(default_factory=dict)
    unknown: set[str] = field(default_factory=set)
    named: dict[str, Naming] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        reads: dict[str, JSONValue] = {}
        for source, found in sorted(self.reads.items()):
            reads[source] = [[rows, placed, unread] for rows, placed, unread in sorted(found)]
        named: dict[str, JSONValue] = {
            leaid: {day: list[JSONValue](sorted(kinds)) for day, kinds in sorted(days.items())}
            for leaid, days in sorted(self.named.items())
        }
        return {
            "shown": list[JSONValue](sorted(self.shown)),
            "reads": reads,
            "unknown": list[JSONValue](sorted(self.unknown)),
            "named": named,
        }

    @classmethod
    def from_json(cls, value: object) -> "Slot":
        """Raises:
        ValueError: ``value`` is not a slot."""
        if not isinstance(value, dict):
            raise ValueError("a slot is an object")
        reads: dict[str, set[Read]] = {}
        for source, found in dict(value["reads"]).items():
            reads[str(source)] = {_read(item) for item in found}
        return cls(
            shown={str(item) for item in value["shown"]},
            reads=reads,
            unknown={str(item) for item in value["unknown"]},
            named={str(k): _naming(days) for k, days in dict(value["named"]).items()},
        )


def _naming(value: object) -> Naming:
    if not isinstance(value, dict):
        raise ValueError("a naming is an object")
    found: Naming = {}
    for day, kinds in value.items():
        named = {str(kind) for kind in kinds}
        if not named or not named <= KINDS:
            raise ValueError("a naming holds status kinds")
        found[str(day)] = named
    return found


def _read(item: object) -> Read:
    if (
        not isinstance(item, list)
        or len(item) != READ_PARTS
        or not all(isinstance(part, int) and part >= 0 for part in item)
    ):
        raise ValueError("a read is three counts")
    rows, placed, unread = item
    return rows, placed, unread


@dataclass(slots=True)
class MorningDay:
    """One UTC day of the record."""

    day: date
    slots: dict[str, Slot] = field(default_factory=dict)
    through: datetime | None = None
    damaged: bool = False

    def to_bytes(self) -> bytes:
        return dumps_json(
            {
                "schema_version": SCHEMA_VERSION,
                "day": self.day.isoformat(),
                "through": None if self.through is None else self.through.isoformat(),
                "damaged": self.damaged,
                "slots": {key: slot.to_json() for key, slot in sorted(self.slots.items())},
            }
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "MorningDay":
        """Raises:
        ValueError: ``data`` is not a day of the record (KeyError and TypeError included)."""
        try:
            body = json.loads(data)
            if body["schema_version"] != SCHEMA_VERSION:
                raise ValueError("another schema")
            through = body["through"]
            return cls(
                day=date.fromisoformat(body["day"]),
                slots={str(k): Slot.from_json(v) for k, v in dict(body["slots"]).items()},
                through=None if through is None else datetime.fromisoformat(through),
                damaged=bool(body["damaged"]),
            )
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(type(error).__name__) from error


@dataclass(frozen=True, slots=True)
class MorningLog:
    """The record's folder (``morning/`` in the live state)."""

    root: Path

    def path(self, day: date) -> Path:
        return self.root / f"{day.isoformat()}.json"

    def day(self, day: date) -> MorningDay | None:
        """The record of UTC ``day``, ``None`` when there is none; a file that does not read
        comes back ``damaged``."""
        path = self.path(day)
        if not path.is_file():
            return None
        try:
            return MorningDay.from_bytes(path.read_bytes())
        except (OSError, ValueError):
            return MorningDay(day, damaged=True)

    def days(self) -> list[date]:
        """The UTC days the record holds, oldest first."""
        found: list[date] = []
        if self.root.is_dir():
            for path in self.root.glob("*.json"):
                try:
                    found.append(date.fromisoformat(path.stem))
                except ValueError:
                    continue
        return sorted(found)

    def through(self) -> datetime | None:
        """The last pass recorded."""
        for day in reversed(self.days()):
            found = self.day(day)
            if found is not None and found.through is not None:
                return found.through
        return None

    def record(
        self,
        at: datetime,
        *,
        shown: str | None,
        reads: Mapping[str, Read],
        unknown: Collection[str],
        named: Mapping[str, Mapping[str, Collection[str]]],
    ) -> None:
        """Fold one pass into its UTC day's file (see the module docstring)."""
        moment = at.astimezone(UTC)
        found = self.day(moment.date()) or MorningDay(moment.date())
        slot = found.slots.setdefault(slot_of(moment), Slot())
        if shown is not None:
            slot.shown.add(shown)
            if in_band(moment):
                for source, read in reads.items():
                    slot.reads.setdefault(source, set()).add(read)
        slot.unknown.update(unknown)
        for leaid, days in named.items():
            into = slot.named.setdefault(leaid, {})
            for day, kinds in days.items():
                into.setdefault(day, set()).update(kinds)
        found.through = moment if found.through is None else max(found.through, moment)
        self.root.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(self.path(moment.date()), found.to_bytes())
        self.prune(moment.date())

    def prune(self, today: date, keep: int = KEEP_DAYS) -> list[date]:
        """Delete the files of days more than ``keep`` days before ``today``."""
        gone = [day for day in self.days() if day < today - timedelta(days=keep)]
        for day in gone:
            self.path(day).unlink(missing_ok=True)
        return gone


def pass_reads(taken: Iterable[str], resolved: Sequence[Resolved]) -> dict[str, Read]:
    """The whole reads of this pass: each source in ``taken`` with its present rows."""
    wanted = set(taken)
    return {
        source.source_id: source_read(source) for source in resolved if source.source_id in wanted
    }

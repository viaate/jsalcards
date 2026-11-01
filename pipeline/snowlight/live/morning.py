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
* ``health`` (advisory-sane L1): the lowest healthy share, in thousandths, of the shown passes
  of the slot inside :data:`READ_BAND` (the share the pass's gate read,
  :meth:`snowlight.live.ingest.Ingest.gate_share`); absent when no such pass recorded one
  (every slot recorded before 2026-10-31).
* ``stale`` (advisory-sane L1): from the same passes, the sources whose whole read was an
  ``empty`` the reader judged from old rows (a list typed by hand last changed more than 36
  hours before, a feed of old posts, page text not yet dated, a list last written before
  the last winter: the read's health gives a reason), not a page that says it holds nothing
  now; and, from 2026-10-31, the sources whose whole read was a populated list whose rows
  name only days before the day before (:func:`old_lists`: a list not updated since an
  earlier storm). Absent when empty. The S7-L labels do not read it; the outcome-blind
  labels never count such a read whole.

Per UTC day, ``by`` (advisory-sane L1): from the shown passes inside :data:`READ_BAND`, each
source read whole with, per slot, the districts its own present rows named for that UTC day
or for every day (:func:`named_by`), so a closed district's other lists can be asked whether
they named it (the co-listing trials of :mod:`snowlight.predict.live_read`). It is stored
once per source as a run of ``[slot, added, removed]`` entries, each slot's set being the
one before it with ``added`` taken in and ``removed`` let go, written only where the set
changes (a slot holding a read of the source and no entry has the set as it last was), so a
list that names the same districts all morning costs its districts once, not once a slot.
Absent when empty.

``through`` is the last pass recorded. A file that does not read is never trusted again: the
next pass marks it ``damaged`` (what it lost cannot be told), and no district-day of that UTC
day is labeled. Every finished day is kept for good in the evidence store
(:mod:`snowlight.live.evidence`). A day leaves the state folder only once a database there is
known to hold its file byte for byte (``kept.json``, :mod:`snowlight.live.kept`): when it is
more than :data:`KEEP_DAYS` (45) days old, or, oldest first and never one of the last
:data:`FLOOR_DAYS`, while the folder holds more than :data:`MAX_BYTES`. A day no database
holds stays, however old, unless the folder passes :data:`HARD_BYTES`: then the oldest go
(never the last 10), each with an ``::error::`` line and the ``evidence`` alert. The record
holds codes, ids, counts and times only (no names, no list text).
"""

import json
import logging
import math
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Final

from snowlight.live.guards import Withheld
from snowlight.live.kept import MORNING as MORNING_KIND
from snowlight.live.kept import note_dropped, read_kept
from snowlight.live.resolve import Derived, Resolved
from snowlight.output import JSONValue, dumps_json, write_bytes_atomic
from snowlight.schemas.vocab import STATUS_BY_KIND

LOG: Final = logging.getLogger(__name__)
SLOT_MINUTES: Final = 30
READ_BAND: Final = (time(9, 0), time(21, 0))
"""The UTC hours whose reads are kept: 06:30-09:30 local in every US zone falls inside."""
KEEP_DAYS: Final = 45
"""Days the state folder keeps (``predict learn`` reads up to ``morning_reads_days``, 44, back);
the evidence store keeps every finished day for good, and an older day stays until it does."""
FLOOR_DAYS: Final = 10
"""Days the record always keeps, whatever its size (the rule before the 45 days)."""
MAX_BYTES: Final = 16 * 1024 * 1024
"""Raw bytes of the folder past which kept days beyond :data:`FLOOR_DAYS` are dropped, oldest
first: at the worst compression seen (4.7 to 1) about 3.4 MB of the state's 16 MB packed
budget."""
HARD_BYTES: Final = 32 * 1024 * 1024
"""Raw bytes past which days beyond :data:`FLOOR_DAYS` go even when no database holds them
(loudly): about 7 MB packed at the worst compression, so the state stays inside its budget
whatever the evidence store does."""
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
PERMILLE: Final = 1000
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
    health: int | None = None
    """The lowest healthy share (thousandths) of the slot's shown passes in the read band."""
    by: dict[str, set[str]] = field(default_factory=dict)
    """Each source read whole by those passes, with the districts its own rows named for the
    UTC day or every day (stored per day, :func:`by_json`)."""
    stale: set[str] = field(default_factory=set)
    """The sources whose whole read by those passes was judged from old rows: an empty the
    reader judged so, or a populated list naming only days before the day before."""

    def to_json(self) -> dict[str, JSONValue]:
        reads: dict[str, JSONValue] = {}
        for source, found in sorted(self.reads.items()):
            reads[source] = [[rows, placed, unread] for rows, placed, unread in sorted(found)]
        named: dict[str, JSONValue] = {
            leaid: {day: list[JSONValue](sorted(kinds)) for day, kinds in sorted(days.items())}
            for leaid, days in sorted(self.named.items())
        }
        value: dict[str, JSONValue] = {
            "shown": list[JSONValue](sorted(self.shown)),
            "reads": reads,
            "unknown": list[JSONValue](sorted(self.unknown)),
            "named": named,
        }
        if self.health is not None:
            value["health"] = self.health
        if self.stale:
            value["stale"] = list[JSONValue](sorted(self.stale))
        return value

    @classmethod
    def from_json(cls, value: object) -> "Slot":
        """Raises:
        ValueError: ``value`` is not a slot."""
        if not isinstance(value, dict):
            raise ValueError("a slot is an object")
        reads: dict[str, set[Read]] = {}
        for source, found in dict(value["reads"]).items():
            reads[str(source)] = {_read(item) for item in found}
        health = value.get("health")
        if health is not None and (
            not isinstance(health, int) or isinstance(health, bool) or not 0 <= health <= PERMILLE
        ):
            raise ValueError("a slot's health is thousandths")
        return cls(
            shown={str(item) for item in value["shown"]},
            reads=reads,
            unknown={str(item) for item in value["unknown"]},
            named={str(k): _naming(days) for k, days in dict(value["named"]).items()},
            health=health,
            stale={str(item) for item in value.get("stale", ())},
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
        value: dict[str, JSONValue] = {
            "schema_version": SCHEMA_VERSION,
            "day": self.day.isoformat(),
            "through": None if self.through is None else self.through.isoformat(),
            "damaged": self.damaged,
            "slots": {key: slot.to_json() for key, slot in sorted(self.slots.items())},
        }
        by = by_json(self.slots)
        if by:
            value["by"] = by
        return dumps_json(value)

    @classmethod
    def from_bytes(cls, data: bytes) -> "MorningDay":
        """Raises:
        ValueError: ``data`` is not a day of the record (KeyError and TypeError included)."""
        try:
            body = json.loads(data)
            if body["schema_version"] != SCHEMA_VERSION:
                raise ValueError("another schema")
            through = body["through"]
            slots = {str(k): Slot.from_json(v) for k, v in dict(body["slots"]).items()}
            by_from_json(body.get("by", {}), slots)
            return cls(
                day=date.fromisoformat(body["day"]),
                slots=slots,
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

    def record(  # noqa: PLR0913 - one pass's parts
        self,
        at: datetime,
        *,
        shown: str | None,
        reads: Mapping[str, Read],
        unknown: Collection[str],
        named: Mapping[str, Mapping[str, Collection[str]]],
        health: float | None = None,
        by: Mapping[str, Collection[str]] | None = None,
        stale: Collection[str] = (),
    ) -> None:
        """Fold one pass into its UTC day's file (see the module docstring): ``health`` is
        the pass's healthy share (0 to 1), ``by`` the districts each source it read whole
        named for the day, and ``stale`` the sources read whole as an empty judged from old
        rows or a list naming only earlier days (:func:`old_lists`), all kept only for a
        shown pass inside the read band."""
        moment = at.astimezone(UTC)
        found = self.day(moment.date()) or MorningDay(moment.date())
        slot = found.slots.setdefault(slot_of(moment), Slot())
        if shown is not None:
            slot.shown.add(shown)
            if in_band(moment):
                for source, read in reads.items():
                    slot.reads.setdefault(source, set()).add(read)
                if health is not None:
                    share = min(PERMILLE, max(0, math.floor(health * PERMILLE)))
                    slot.health = share if slot.health is None else min(slot.health, share)
                for source, leaids in (by or {}).items():
                    if source in reads:
                        slot.by.setdefault(source, set()).update(leaids)
                slot.stale.update(source for source in stale if source in reads)
        slot.unknown.update(unknown)
        for leaid, days in named.items():
            into = slot.named.setdefault(leaid, {})
            for day, kinds in days.items():
                into.setdefault(day, set()).update(kinds)
        found.through = moment if found.through is None else max(found.through, moment)
        self.root.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(self.path(moment.date()), found.to_bytes())
        self.prune(moment.date(), at=moment)

    def prune(
        self,
        today: date,
        keep: int = KEEP_DAYS,
        max_bytes: int = MAX_BYTES,
        hard_bytes: int = HARD_BYTES,
        at: datetime | None = None,
    ) -> list[date]:
        """Delete the files of kept days (:mod:`snowlight.live.kept`) more than ``keep`` days
        before ``today``; then, while the folder holds more than ``max_bytes``, the oldest kept
        day more than :data:`FLOOR_DAYS` before ``today``; then, while it holds more than
        ``hard_bytes``, the oldest such day kept or not (recorded, with an ``::error::``
        line: :func:`snowlight.live.kept.note_dropped`). A day no database holds is never
        pruned for its age."""
        state = self.root.parent
        kept = read_kept(state)
        floor = today - timedelta(days=FLOOR_DAYS)
        days = self.days()

        def held(day: date) -> bool:
            return kept.holds(MORNING_KIND, day, self.path(day))

        gone = [day for day in days if day < today - timedelta(days=keep) and held(day)]
        for day in gone:
            self.path(day).unlink(missing_ok=True)
        left = [day for day in days if day not in gone]
        sizes = {day: self._size(day) for day in left}
        total = sum(sizes.values())
        for day in [day for day in left if day < floor] if total > max_bytes else []:
            if total <= max_bytes:
                break
            if not held(day):
                continue
            self.path(day).unlink(missing_ok=True)
            total -= sizes[day]
            gone.append(day)
            LOG.warning("morning record over %d B: %s (kept) dropped", max_bytes, day)
        lost: list[date] = []
        for day in [day for day in left if day < floor and day not in gone]:
            if total <= hard_bytes:
                break
            self.path(day).unlink(missing_ok=True)
            total -= sizes[day]
            gone.append(day)
            lost.append(day)
        note_dropped(state, lost, at or datetime.combine(today, time(), tzinfo=UTC))
        return sorted(gone)

    def _size(self, day: date) -> int:
        try:
            return self.path(day).stat().st_size
        except OSError:
            return 0


def named_by(taken: Iterable[str], resolved: Sequence[Resolved], day: date) -> dict[str, set[str]]:
    """Each source of ``taken`` (read whole this pass) with the districts its own present rows
    name for ``day`` or for every day (:func:`naming`, any kind; a row that only says school
    is open names none, and a row for another day does not count)."""
    wanted = set(taken)
    days = {day.isoformat(), EVERY_DAY}
    found: dict[str, set[str]] = {}
    for source in resolved:
        if source.source_id not in wanted:
            continue
        into = found.setdefault(source.source_id, set())
        for result in source.rows:
            if result.present and not result.superseded and days & set(naming(result.derived)):
                into.update(result.derived.reach)
    return found


def old_lists(taken: Iterable[str], resolved: Sequence[Resolved], day: date) -> set[str]:
    """The sources of ``taken`` (read whole this pass) whose present rows give dated days
    and none of them on or after the day before ``day``: a populated list still holding an
    earlier storm's rows, judged from the rows' own dates (a row with no date of its own is
    dated by when the list first posted it, so a row left up since an earlier storm counts),
    never from what closed. Rows with no day (withheld or open-ended) say nothing either
    way."""
    wanted = set(taken)
    since = day - timedelta(days=1)
    found: set[str] = set()
    for source in resolved:
        if source.source_id not in wanted:
            continue
        dated = [
            when
            for result in source.rows
            if result.present and not result.superseded
            for when in (
                *(claim.day for claim in result.derived.claims),
                *result.derived.opens,
                *(result.derived.dissent or ()),
            )
        ]
        if dated and max(dated) < since:
            found.add(source.source_id)
    return found


def by_json(slots: Mapping[str, Slot]) -> dict[str, JSONValue]:
    """The slots' ``by`` as one run per source (see the module docstring): ``[slot, added,
    removed]`` against the source's set before, only where the set changes."""
    found: dict[str, list[JSONValue]] = {}
    last: dict[str, set[str]] = {}
    for key, slot in sorted(slots.items()):
        for source, leaids in sorted(slot.by.items()):
            before = last.get(source)
            if before == leaids:
                continue
            before = before or set()
            found.setdefault(source, []).append(
                [
                    key,
                    list[JSONValue](sorted(leaids - before)),
                    list[JSONValue](sorted(before - leaids)),
                ]
            )
            last[source] = set(leaids)
    return dict[str, JSONValue](found)


def by_from_json(value: object, slots: Mapping[str, Slot]) -> None:
    """Put a day's stored ``by`` (:func:`by_json`) back into its ``slots``: from a source's
    first entry on, every slot holding a read of it has its set as of that slot.

    Raises:
        ValueError: it is not one, or an entry names a slot without a read of its source.
    """
    if not isinstance(value, dict):
        raise ValueError("by is an object")
    runs: dict[str, dict[str, tuple[set[str], set[str]]]] = {}
    for source, entries in value.items():
        run = runs.setdefault(str(source), {})
        for entry in entries:
            if not isinstance(entry, list) or len(entry) != READ_PARTS:
                raise ValueError("a by entry is a slot, the districts added and those let go")
            key, added, removed = entry
            if key not in slots or source not in slots[key].reads:
                raise ValueError("a by entry names a slot without a read of its source")
            run[str(key)] = ({str(d) for d in added}, {str(d) for d in removed})
    current: dict[str, set[str]] = {}
    for key, slot in sorted(slots.items()):
        for source, run in runs.items():
            if key in run:
                added, removed = run[key]
                current[source] = (current.get(source, set()) | added) - removed
            if source in current and source in slot.reads:
                slot.by[source] = set(current[source])


def pass_reads(taken: Iterable[str], resolved: Sequence[Resolved]) -> dict[str, Read]:
    """The whole reads of this pass: each source in ``taken`` with its present rows."""
    wanted = set(taken)
    return {
        source.source_id: source_read(source) for source in resolved if source.source_id in wanted
    }

"""Resolve: from a ledger row to the statuses, open signals and dissents it gives each school.

For each row of a source, in this order (the first failure wins and is counted,
spec 7.4):

1. **Excluded.** A district site or banner platform, or a district-level source
   (``leaids``): ``EXCLUDED_PLATFORM``. A station that is not active, or whose
   platform's terms do not permit polling (neither permitted nor overridden by a
   recorded permission or owner decision), lights nothing (``TERMS``): the fetch
   layer skips such stations, and resolve checks again.
2. **Match.** The name matcher with the station's context, and the place guard
   (:func:`matcher_fn`). A listing not accepted is queued for review
   (:attr:`Resolved.unmatched`, private: it holds raw names).
3. **Expand.** The schools the match names (``school``) and the schools of the
   districts it names (``district``), with the guards the replay hardened
   (:mod:`snowlight.replays.build`) and the 2026-10-13 addendum: a district row never
   lights a charter (``DISTRICT_EXCLUDES_CHARTER``) or a fully virtual school
   (``DISTRICT_EXCLUDES_VIRTUAL``), a facility program or a school outside the
   station's states; a district row that names part of its district lights none of
   its schools and stands against their statuses; a public school matched by its
   name alone with nothing to anchor it is withheld (``UNANCHORED``). G8: a row
   reaching 150 schools or more needs an ``alias`` or ``name`` match at 0.95.
4. **Zones.** Every school must have a known zone (``ZONE_UNKNOWN``).
5. **Interval dating** (spec 7.2, D1). A row stamp within 36 hours before the first
   sighting is the one posting time read. Otherwise ``lo`` must be known
   (``UNKNOWN_START``, ``CHURN``) and at most 36 hours before ``hi``
   (``INTERVAL_TOO_LONG``); a row that cannot be dated still darkens when its words
   retract, deny or say open at ``hi`` (a dissent needs no date: it only darkens).
   A dated row is read at ``lo``, ``hi``, every 15 minutes
   between and every local :00 and :30 between (:func:`samples`), in every zone of
   its schools. The reader's day rules change only at whole or half hours, so every
   stretch of the interval where its answer is constant is read at least once.
   Every reading must agree (``ZONE_SPLIT`` across zones at one time,
   ``INTERVAL_DISAGREES`` across times).
6. **Gates** on every reading: a status kind at 0.8 or more (G4; ``WEAK`` counts
   0.7, owner Q5), only the notes ``undated`` and ``unread_words`` (``NOTE``),
   weather (G7, ``NOT_WEATHER``), the wording gates (:func:`~snowlight.live.guards.
   wording_reason`, ``WORDING``) and dates within two days before and six after
   the posting day (``OUT_OF_WINDOW``). A board row's own date must be each day it
   lights (G5, ``BOARD_DATE``). An undated row from a source with no read on the
   previous school day cannot prove it is new (``STALE_UNPROVEN``).
7. **Emit.** One status per school and day from the reader's schedule.

Besides statuses a row can give:

* an **open signal** (owner decision Q8): the reader says the school runs as normal
  (``says_open`` at 0.9 or more at every reading; "Open", "Normal schedule", "Open -
  normal schedule"), for the day the row names, or for an undated row only the posting
  day itself when posted overnight or in the morning, never a later day. It never
  lights a school; it retracts an older status for that school-day
  (:mod:`snowlight.live.merge`) and is kept for S7. An open statement that cannot be
  dated so (posted at midday or in the evening with no day, or naming a day the exact
  reading does not cover) is never an open signal, but it still dissents
  (``OPEN_UNDATED``): for the day a bare status posted then is for, or every day.
* a **dissent**: a reading that takes a status back, denies it, narrows it or
  finds statuses that disagree (the reader's ``revoked``, ``negated``,
  ``superseded``, ``ambiguous``, ``partial_program`` and ``conflict`` notes), says
  the day off is not for weather, or names a learning mode beside another status.
  A retraction dissents for every day, whatever day it names ("Closing rescinded
  Monday evening", "Closings cancelled for Jan 15, 16 and 17"). A dissent never
  lights; it stands against any status for its school and days.

**Successors.** A row that replaced another row of the same listing in its source
(the ledger's ``pred``) is read at its own interval and at its predecessor's. When
the two readings agree, it says the same either way, but it may re-render the old
posting: it is dated from the earliest its predecessor can have been posted to its own
first sighting (:meth:`~snowlight.live.ledger.Ledger.widen`), so merge never takes it
for words newer than a reversal another source posted since (they overlap: dark), and
the wider interval only adds readings. It keeps its own dating when its words name a
kind of status, an open statement or a dissent the predecessor's did not (an upgrade
or a retraction: no re-render changes those).
Otherwise it may be new words posted now or the old posting re-rendered (a station
rewording its whole list overnight, "Closed" to "Closed due to snow", or "Closed"
re-worded on Tuesday to "Closed tomorrow"), and its reading depends on which: it is
left undated (``REWORDED``, :meth:`~snowlight.live.ledger.Ledger.reword`), so it
lights nothing under this or any later version and only darkens. The same holds when
the predecessor has no readable derivation under the current version to compare
with. A row
whose listing is present under a newer key is **superseded**
(:attr:`RowResult.superseded`): the source no longer says it, so merge takes no
status or open signal from it, whatever its successor derives.

The derivation of a row depends only on its key, its ledger entry and the
``derived_version`` (digests of the reader's and the matcher's code and tables, of
the live code and the vocabularies, the guards' version, the directory edition, the
rules, whether a place gazetteer is used and its data, and the station's own record:
see :mod:`snowlight.live.versions` and :func:`station_version`), so it is kept in the
ledger and reused while the version holds (spec S6, T4). A row that vanished keeps its
last derivation, which carries no raw text. Under a newer version a vanished row
cannot be read again: it keeps only the darkening part of its last derivation (its
dissents, and its open statements as dissents), with its schools placed by NCES id in
the current directory edition, so a version bump never re-lights a retracted status,
never moves a dissent onto another school and never keeps a status the new version
could not check. The darkening part is also kept in a plain form of its own (NCES ids
and days, :class:`~snowlight.live.ledger.Darkens`) that reads under any version: a
stored derivation that no longer reads (a damaged payload, or codes a later
vocabulary dropped) keeps darkening from it, and the failure is logged by source id
and error type only. The station's terms and status are checked on every pass, before
any reuse: a station not active, or whose terms stop permitting polling, lights
nothing (``TERMS``) but keeps the darkening part of what each of its rows last said.

Every string kept is a code: the reader's notes, the matcher's reason and level and
the source type are checked against their vocabularies before they are stored, and
anything else is kept as ``unknown``.
"""

import hashlib
import json
import logging
import re
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from typing import Final, Literal, Protocol, get_args
from zoneinfo import ZoneInfo

import polars as pl

from snowlight.classify.model import Note
from snowlight.listed.build import GUARD_REASON
from snowlight.listed.located import Gazetteer, Verdict
from snowlight.listed.matching import Outcome, Query, match_one
from snowlight.listed.scope import EXCLUDED_PLATFORMS, station_context
from snowlight.live.guards import (
    GUARDS_VERSION,
    Rules,
    Withheld,
    names_part,
    open_wording_reason,
    wording_reason,
)
from snowlight.live.ledger import Darkens, Ledger, LedgerRow, SeenRow, Start
from snowlight.live.provenance import (
    BOARD_ROW_DATES,
    BOARD_TYPES,
    PLATFORM_TYPES,
    SourceType,
)
from snowlight.live.versions import live_version, reader_matcher_version
from snowlight.match import Matcher
from snowlight.match.matcher import Reason as MatchReason
from snowlight.match.normalize import Level as MatchLevel
from snowlight.replays.build import (
    LISTING_LEVELS,
    NAME_ONLY,
    PRIVATE_SECTION,
    PUBLIC_SECTION,
    RECORD_LEVELS,
    VIRTUAL_NAME,
    School,
    facility,
)
from snowlight.replays.gates import (
    ALLOWED_NOTES,
    DISSENT_NOTES,
    MONTHS,
    STAMP_PHRASE,
    WEEKDAYS,
    day_words,
)
from snowlight.replays.gates import says_open as open_words
from snowlight.schemas.vocab import REASON_BY_LABEL, STATUS_BY_KIND
from snowlight.sources.stations.registry import Registry, Station, StationStatus

type Level = Literal["school", "district"]

STATUS_KINDS: Final = frozenset(STATUS_BY_KIND)
UNSURE: Final = "unsure"
READ_KINDS: Final = STATUS_KINDS | {"open", "dissent", UNSURE}
"""What :attr:`Derived.kinds` may hold."""
UNSURE_NOTES: Final = frozenset(
    {"hedged", "undated", "unreadable_date", "invalid_date", "date_mismatch", "truncated"}
)
"""Reader notes that mean status words were found but give no day or are hedged."""
RANGE_BEFORE: Final = 2
RANGE_AFTER: Final = 6
OPEN_AHEAD: Final = 6
BARE_STATUS: Final = "Closed"
"""The text whose reading dates an undated open statement: the reader's own rule for a
listing that names no day (overnight and morning: the posting day)."""
FULL_VIRTUAL: Final = "FULLVIRTUAL"
QUEUED: Final = frozenset({Withheld.UNMATCHED, Withheld.REJECTED_MATCH})
"""Rows whose listing goes to the private unmatched queue."""
UNKNOWN_CODE: Final = "unknown"
"""What a string that is not a known code is kept as."""
NOTE_CODES: Final = frozenset(get_args(Note.__value__)) | {UNKNOWN_CODE}
MATCH_REASONS: Final = frozenset(reason.value for reason in MatchReason) | {
    GUARD_REASON,
    UNKNOWN_CODE,
}
MATCH_LEVELS: Final = frozenset(level.value for level in MatchLevel) | {UNKNOWN_CODE}
SOURCE_TYPES: Final = frozenset(kind.value for kind in SourceType)
LOG: Final = logging.getLogger(__name__)
CACHE_LIMIT: Final = 100_000
"""The most readings :class:`CachedReader` keeps (least recently used first out)."""


def code(value: str | None, known: frozenset[str]) -> str | None:
    """``value`` when it is one of ``known`` (or ``None``), else :data:`UNKNOWN_CODE`."""
    return value if value is None or value in known else UNKNOWN_CODE


# --- the status reader, as a protocol ----------------------------------------------------------


class EntryLike(Protocol):
    """One dated status (shaped like ``snowlight.classify.DatedStatus``)."""

    @property
    def kind(self) -> str: ...
    @property
    def dates(self) -> Sequence[date]: ...
    @property
    def delay_minutes(self) -> int | None: ...
    @property
    def opens_at(self) -> time | None: ...
    @property
    def dismissal_time(self) -> time | None: ...
    @property
    def dismissal_early_minutes(self) -> int | None: ...
    @property
    def dates_stated(self) -> bool: ...
    @property
    def until_further_notice(self) -> bool: ...


class ParsedLike(Protocol):
    """What the reader makes of one listing (shaped like ``snowlight.classify.ParsedStatus``)."""

    @property
    def kind(self) -> str: ...
    @property
    def schedule(self) -> Sequence[EntryLike]: ...
    @property
    def names_weather(self) -> bool: ...
    @property
    def reason(self) -> str | None: ...
    @property
    def other_causes(self) -> Sequence[str]: ...
    @property
    def confidence(self) -> float: ...
    @property
    def says_open(self) -> bool: ...
    @property
    def notes(self) -> Sequence[str]: ...


class StatusReader(Protocol):
    """``parse_status(text, *, posted_at, tz)``: the status reader (f5), pinned here."""

    def __call__(self, text: str, *, posted_at: datetime, tz: str) -> ParsedLike: ...


def f5_reader() -> StatusReader:
    """The real status reader, ``snowlight.classify.parse_status``."""
    from snowlight.classify import parse_status  # noqa: PLC0415 - loaded only when used

    reader: StatusReader = parse_status  # checked against the pinned protocol, no cast
    return reader


class CachedReader:
    """A reader whose results are kept by text, posting minute and zone (the reader is pure).

    It keeps at most ``limit`` readings, dropping the least recently used, so a long
    loop process does not grow without bound. The texts it keeps are raw: it lives in
    memory only and is never written or logged.
    """

    def __init__(self, reader: StatusReader, *, limit: int = CACHE_LIMIT) -> None:
        self._reader = reader
        self._kept: OrderedDict[tuple[str, datetime, str], ParsedLike] = OrderedDict()
        self.limit = limit
        self.calls = 0

    def __repr__(self) -> str:
        return f"CachedReader(kept={len(self._kept)}, calls={self.calls})"

    def __len__(self) -> int:
        return len(self._kept)

    def clear(self) -> None:
        self._kept.clear()

    def __call__(self, text: str, *, posted_at: datetime, tz: str) -> ParsedLike:
        minute = posted_at.astimezone(UTC).replace(second=0, microsecond=0)
        key = (text, minute, tz)
        found = self._kept.get(key)
        if found is None:
            self.calls += 1
            found = self._reader(text, posted_at=minute, tz=tz)
            self._kept[key] = found
            if len(self._kept) > self.limit:
                self._kept.popitem(last=False)
        else:
            self._kept.move_to_end(key)
        return found


# --- interval samples --------------------------------------------------------------------------


@cache
def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def samples(
    lo: datetime, hi: datetime, zones: Iterable[str], step: timedelta = timedelta(minutes=15)
) -> list[datetime]:
    """The times a row first seen at ``hi`` and absent at ``lo`` is read at.

    ``lo``, ``hi``, every ``step`` from ``lo``, and every local :00 and :30 strictly
    between them in each of ``zones``.
    """
    found = {lo, hi}
    moment = lo + step
    while moment < hi:
        found.add(moment)
        moment += step
    for name in zones:
        local = lo.astimezone(_zone(name))
        mark = local.replace(minute=0, second=0, microsecond=0)
        while mark.astimezone(UTC) < hi:
            # the half hour in UTC: local arithmetic would take the repeated 01:30 of the night
            # daylight saving time ends (fold 1) for the first one
            for at in (mark.astimezone(UTC), mark.astimezone(UTC) + timedelta(minutes=30)):
                if lo < at < hi:
                    found.add(at)
            mark = (mark.astimezone(UTC) + timedelta(hours=1)).astimezone(_zone(name))
    return sorted(moment.astimezone(UTC) for moment in found)


# --- the directory -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveSchool:
    """One school as the ingest reads it."""

    record: School
    index: int
    """Its published index (position in the deployed ``meta.json``)."""
    charter: bool
    zones: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LiveDirectory:
    """The deployed directory's schools by NCES id, with their zones."""

    schools: Mapping[str, LiveSchool]
    district_sizes: Mapping[str, int]
    edition: str
    """The content hash of the edition these indexes belong to."""

    @classmethod
    def from_frames(
        cls, schools: pl.DataFrame, zones: pl.DataFrame, edition: str
    ) -> "LiveDirectory":
        """Read ``schools.parquet`` and ``school_zones.parquet`` of one edition."""
        zone_of = dict(zip(zones["index"].to_list(), zones["zones"].to_list(), strict=True))
        found: dict[str, LiveSchool] = {}
        sizes: Counter[str] = Counter()
        for row in schools.iter_rows(named=True):
            district = row.get("district_id")
            if district is not None:
                sizes[str(district)] += 1
            enrollment = row.get("enrollment")
            record = School(
                id=str(row["id"]),
                state=str(row["state"]),
                public=row["kind"] == "public",
                status=row.get("status"),
                county_fips=row.get("county_fips"),
                lat=row.get("lat"),
                lon=row.get("lon"),
                virtual=row.get("virtual"),
                name=str(row.get("name") or ""),
                district_id=None if district is None else str(district),
                level=row.get("level"),
                school_type=row.get("school_type"),
                enrollment=None if enrollment is None else int(enrollment),
                grade_low=row.get("grade_low"),
                grade_high=row.get("grade_high"),
            )
            index = int(row["index"])
            found[record.id] = LiveSchool(
                record=record,
                index=index,
                charter=bool(row.get("charter")),
                zones=tuple(zone_of.get(index) or ()),
            )
        return cls(schools=found, district_sizes=dict(sizes), edition=edition)


# --- matching ----------------------------------------------------------------------------------


class MatchFn(Protocol):
    """Match one row of a station's list (the matcher with the station's context)."""

    def __call__(self, station: Station, row: SeenRow) -> Outcome: ...


@dataclass(frozen=True, slots=True)
class CommittedMatch:
    """The committed matcher with the place guard (:mod:`snowlight.listed.located`).

    :attr:`version` names whether a gazetteer is used and digests its data, so a
    derivation made with another gazetteer (or none) is never reused.
    """

    matcher: Matcher = field(repr=False)
    gazetteer: Gazetteer | None = field(default=None, repr=False)
    version: str = "gaz-none"

    def __call__(self, station: Station, row: SeenRow) -> Outcome:
        query = Query(station_context(station), row.name, row.section)
        outcome = match_one(self.matcher, query)
        if self.gazetteer is None or not outcome.accepted or not row.places:
            return outcome
        verdict = self.gazetteer.verdict(row.places, outcome.targets, query.context.states)
        if verdict is Verdict.CONFLICT:
            return replace(outcome, accepted=False, reason=GUARD_REASON, direct=(), via_district=())
        return outcome


def gazetteer_digest(gazetteer: Gazetteer) -> str:
    """A digest of a gazetteer's data (its towns, county outlines and record places).

    The gazetteer is built in a fixed order from the directory and the county list, and
    its outlines pickle as their binary geometry, so the same data digests the same.
    """
    import pickle  # noqa: PLC0415 - only to digest our own object, never to load one

    return hashlib.sha256(pickle.dumps(gazetteer, protocol=5)).hexdigest()[:16]


def matcher_fn(matcher: Matcher, gazetteer: Gazetteer | None = None) -> CommittedMatch:
    """The committed matcher with the place guard, versioned by its gazetteer."""
    if gazetteer is None:
        return CommittedMatch(matcher)
    return CommittedMatch(matcher, gazetteer, f"gaz-{gazetteer_digest(gazetteer)}")


def station_version(station: Station) -> str:
    """The part of a ``derived_version`` a station's own record gives: a digest of every
    field a derivation reads (its platform, status, states, counties, market, district
    ids and matcher context), so a registry correction re-derives its rows."""
    context = station_context(station)
    body = {
        "id": station.id,
        "platform": station.platform,
        "status": str(station.status),
        "states": list(station.states),
        "counties": None if station.counties is None else list(station.counties.fips),
        "market": station.market,
        "dma": station.dma,
        "name": station.name,
        "call_sign": station.call_sign,
        "leaids": list(station.leaids),
        "context": [
            context.market,
            list(context.states),
            None if context.counties is None else list(context.counties),
        ],
    }
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return "st-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# --- what a row gives --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DayClaim:
    """The status a row gives one day."""

    day: date
    kind: str
    reason: str | None
    shift_minutes: int | None
    clock_minute: int | None
    ufn: bool


@dataclass(frozen=True, slots=True)
class Target:
    """A school a row reaches."""

    index: int
    nces_id: str
    level: Level


@dataclass(frozen=True, slots=True)
class Derived:
    """What one row gives, kept in the ledger by key and version (codes, ids, times only)."""

    withheld: Withheld | None
    claims: tuple[DayClaim, ...] = ()
    opens: tuple[date, ...] = ()
    dissent: tuple[date, ...] | None = None
    """``None``: no dissent; empty: every day; else the days dissented."""
    targets: tuple[Target, ...] = ()
    """The schools the row lights (claims and opens)."""
    voters: tuple[Target, ...] = ()
    """Schools the row only stands against (a district row naming part of the district)."""
    announced_at: datetime | None = None
    confidence: float | None = None
    notes: tuple[str, ...] = ()
    match_reason: str | None = None
    match_level: str | None = None
    match_confidence: float | None = None
    source_type: str | None = None
    target_drops: Mapping[str, int] = field(default_factory=dict)
    kinds: tuple[str, ...] = ()
    """What the row's words name at its readings, whatever their confidence or day: status
    kinds, ``open``, ``dissent``, and ``unsure`` for status words with no day or a hedge
    (:data:`READ_KINDS`). Empty when the row was not read."""
    undated: bool = False
    """Its readings name no day: the day comes from when it was posted."""
    stands: tuple[Target, ...] = ()
    """The schools a present row names at school level and lights no claim of its own day for
    (withheld, or dated by its posting time): it stands against their district's
    different status (:mod:`snowlight.live.merge`)."""
    reach: tuple[str, ...] = ()
    """The districts (LEAIDs) of every school the matcher placed the row on and the guards
    kept, lit or not: what the list names, kept when the row is withheld (the automatic
    learning reads a district a list names without lighting as not shown open). Empty when
    the row was not placed."""

    def check_codes(self) -> None:
        """Raise unless every string kept is a code (no raw text can be stored).

        Raises:
            ValueError: a note, match reason or level, source type, claim kind or
                reason is not in its vocabulary (the error names the field, never the value).
        """
        bad = ["notes"] if any(note not in NOTE_CODES for note in self.notes) else []
        if self.match_reason is not None and self.match_reason not in MATCH_REASONS:
            bad.append("match_reason")
        if self.match_level is not None and self.match_level not in MATCH_LEVELS:
            bad.append("match_level")
        if self.source_type is not None and self.source_type not in SOURCE_TYPES:
            bad.append("source_type")
        for claim in self.claims:
            if claim.kind not in STATUS_KINDS:
                bad.append("claim.kind")
            if claim.reason is not None and claim.reason not in REASON_BY_LABEL:
                bad.append("claim.reason")
        if any(reason not in _DROP_CODES for reason in self.target_drops):
            bad.append("target_drops")
        if any(kind not in READ_KINDS for kind in self.kinds):
            bad.append("kinds")
        if any(not (len(leaid) == LEAID_DIGITS and leaid.isdigit()) for leaid in self.reach):
            bad.append("reach")
        if bad:
            raise ValueError(f"a derived result keeps only codes: {sorted(set(bad))}")

    def to_json(self) -> dict[str, object]:
        """The stored form (codes, ids and times only; checked by :meth:`check_codes`)."""
        self.check_codes()
        return {
            "withheld": None if self.withheld is None else self.withheld.value,
            "claims": [
                [c.day.isoformat(), c.kind, c.reason, c.shift_minutes, c.clock_minute, c.ufn]
                for c in self.claims
            ],
            "opens": [day.isoformat() for day in self.opens],
            "dissent": None if self.dissent is None else [d.isoformat() for d in self.dissent],
            "targets": [[t.index, t.nces_id, t.level] for t in self.targets],
            "voters": [[t.index, t.nces_id, t.level] for t in self.voters],
            "announced_at": None if self.announced_at is None else self.announced_at.isoformat(),
            "confidence": self.confidence,
            "notes": list(self.notes),
            "match_reason": self.match_reason,
            "match_level": self.match_level,
            "match_confidence": self.match_confidence,
            "source_type": self.source_type,
            "target_drops": dict(sorted(self.target_drops.items())),
            "kinds": list(self.kinds),
            "undated": self.undated,
            "stands": [[t.index, t.nces_id, t.level] for t in self.stands],
            "reach": list(self.reach),
        }

    @classmethod
    def from_json(cls, data: object) -> "Derived":
        """Read the stored form back, checking every field's type and code.

        Raises:
            ValueError: the payload does not have the stored shape.
        """
        body = _object(data)
        withheld = _opt_str(body["withheld"])
        dissent = body["dissent"]
        announced = _opt_str(body["announced_at"])
        drops = _object(body["target_drops"])
        undated = body["undated"]
        if not isinstance(undated, bool):
            raise ValueError("expected a flag")
        derived = cls(
            withheld=None if withheld is None else Withheld(withheld),
            claims=tuple(_day_claim(item) for item in _list(body["claims"])),
            opens=tuple(date.fromisoformat(_str(day)) for day in _list(body["opens"])),
            dissent=None
            if dissent is None
            else tuple(date.fromisoformat(_str(day)) for day in _list(dissent)),
            targets=tuple(_target(item) for item in _list(body["targets"])),
            voters=tuple(_target(item) for item in _list(body["voters"])),
            announced_at=None if announced is None else _aware(announced),
            confidence=_opt_float(body["confidence"]),
            notes=tuple(_str(note) for note in _list(body["notes"])),
            match_reason=_opt_str(body["match_reason"]),
            match_level=_opt_str(body["match_level"]),
            match_confidence=_opt_float(body["match_confidence"]),
            source_type=_opt_str(body["source_type"]),
            target_drops={_str(key): _int(value) for key, value in drops.items()},
            kinds=tuple(_str(kind) for kind in _list(body["kinds"])),
            undated=undated,
            stands=tuple(_target(item) for item in _list(body["stands"])),
            reach=tuple(_str(leaid) for leaid in _list(body["reach"])),
        )
        derived.check_codes()
        return derived


_DROP_CODES: Final = frozenset(reason.value for reason in Withheld) | {"not_in_directory"}
LEAID_DIGITS: Final = 7
NCES_DIGITS: Final = 12


def reach_of(targets: Iterable[Target]) -> tuple[str, ...]:
    """The districts (LEAIDs, the first 7 digits of a public school's NCES id) of ``targets``."""
    return tuple(
        sorted({t.nces_id[:LEAID_DIGITS] for t in targets if len(t.nces_id) == NCES_DIGITS})
    )


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("expected an object")
    return {str(key): item for key, item in value.items()}


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("expected a list")
    return list(value)


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expected a string")
    return value


def _opt_str(value: object) -> str | None:
    return None if value is None else _str(value)


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected an integer")
    return value


def _opt_int(value: object) -> int | None:
    return None if value is None else _int(value)


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("expected a number")
    return float(value)


def _aware(text: str) -> datetime:
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError("expected a timezone-aware time")
    return moment


def _day_claim(value: object) -> DayClaim:
    day, kind, reason, shift, clock, ufn = _list(value)
    if not isinstance(ufn, bool):
        raise ValueError("expected a flag")
    return DayClaim(
        date.fromisoformat(_str(day)),
        _str(kind),
        _opt_str(reason),
        _opt_int(shift),
        _opt_int(clock),
        ufn,
    )


def _target(value: object) -> Target:
    index, nces_id, level = _list(value)
    if level == "school":
        return Target(_int(index), _str(nces_id), "school")
    if level == "district":
        return Target(_int(index), _str(nces_id), "district")
    raise ValueError("expected a target level")


def darkening_only(derived: Derived, withheld: Withheld = Withheld.NOT_DERIVED) -> Derived:
    """What a row keeps when it cannot be read again: only what darkens.

    Its dissents stand as they were, its open statements become dissents for their
    days, and its statuses are dropped (``withheld``: ``NOT_DERIVED``, or ``TERMS`` for
    a station that may no longer be read).
    """
    voters = derived.voters
    dissent = derived.dissent
    if derived.opens:
        voters = tuple(dict.fromkeys((*voters, *derived.targets)))
        if dissent is None:
            dissent = derived.opens
        elif dissent:
            dissent = tuple(sorted({*dissent, *derived.opens}))
    return Derived(
        withheld=withheld,
        dissent=dissent if voters else None,
        voters=voters if dissent is not None else (),
        source_type=derived.source_type,
    )


def darkens_of(derived: Derived) -> Darkens | None:
    """The plain form of what a derivation darkens (:func:`darkening_only`), or ``None``."""
    dark = darkening_only(derived)
    if dark.dissent is None or not dark.voters:
        return None
    return Darkens(
        schools=tuple(sorted({t.nces_id for t in dark.voters})),
        days=dark.dissent or None,
    )


def _same_reading(one: Derived, other: Derived) -> bool:
    """Whether two derivations of one row say the same of the same days."""
    return (one.withheld, one.claims, one.opens, one.dissent) == (
        other.withheld,
        other.claims,
        other.opens,
        other.dissent,
    )


def _named_changed(now: Sequence[str], before: Sequence[str]) -> bool:
    """Whether a row's words name a kind of status, an open statement or a dissent its
    predecessor's did not (or the reverse). ``unsure`` words on either side cannot show it."""
    if UNSURE in now or UNSURE in before or not (now or before):
        return False
    return set(now) != set(before)


@dataclass(frozen=True, slots=True)
class RowResult:
    """One ledger row and what it gives."""

    row: LedgerRow
    derived: Derived
    present: bool
    reused: bool
    superseded: bool = False
    """Absent, while its listing is present under a newer key: the source no longer says it."""
    version: str = ""
    """The ``derived_version`` the derivation was made under."""


@dataclass(frozen=True, slots=True)
class Resolved:
    """Every row of one source, resolved."""

    source_id: str
    rows: tuple[RowResult, ...]
    unmatched: tuple[Query, ...] = field(repr=False)
    """Listings the matcher did not accept (raw names: the private queue only, never in a repr)."""
    counts: Mapping[str, int]
    version: str = ""
    """The resolver's ``derived_version`` for this pass."""


# --- reading one row ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Reading:
    """What one reading (one time, one zone) of a row says, reduced to compare."""

    verdict: Literal["claim", "open", "dissent", "withheld"]
    claims: tuple[DayClaim, ...] = ()
    days: tuple[date, ...] = ()
    reason: Withheld | None = None
    undated: bool = False
    confidence: float = 0.0
    notes: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    """What its words name (:attr:`Derived.kinds`)."""

    def sig(self) -> tuple[object, ...]:
        """What two readings must share to agree (not their confidence or notes)."""
        return (self.verdict, self.claims, self.days, self.reason, self.undated)


def _minute(value: time | None) -> int | None:
    return None if value is None else value.hour * 60 + value.minute


def _claim(entry: EntryLike, day: date, reason: str | None) -> DayClaim:
    if entry.kind == "delayed":
        shift, clock = entry.delay_minutes, _minute(entry.opens_at)
    elif entry.kind == "early_dismissal":
        shift, clock = entry.dismissal_early_minutes, _minute(entry.dismissal_time)
    else:
        shift, clock = None, None
    return DayClaim(
        day=day,
        kind=entry.kind,
        reason=reason if reason in REASON_BY_LABEL else None,
        shift_minutes=shift,
        clock_minute=clock,
        ufn=entry.until_further_notice,
    )


def _kinds(readings: Iterable[_Reading]) -> tuple[str, ...]:
    return tuple(sorted({kind for reading in readings for kind in reading.kinds}))


def _status_entries(parsed: ParsedLike) -> list[EntryLike]:
    return [entry for entry in parsed.schedule if entry.kind in STATUS_KINDS]


class Resolver:
    """Resolves a source's ledger rows (one per process: the matcher and directory load once)."""

    def __init__(  # noqa: PLR0913 - the inputs a derivation depends on
        self,
        *,
        reader: StatusReader,
        match: MatchFn,
        directory: LiveDirectory,
        ledger: Ledger,
        pollable: Mapping[str, bool],
        version: str | None = None,
        rules: Rules | None = None,
    ) -> None:
        """``version`` is the reader's and the matcher's part of the ``derived_version``;
        ``None`` (the live ingest) computes it from their code and tables
        (:func:`~snowlight.live.versions.reader_matcher_version`). Tests with a stub reader
        or matcher pass their own."""
        if version is None:
            version = reader_matcher_version()
        self.reader = reader if isinstance(reader, CachedReader) else CachedReader(reader)
        self.match = match
        self.directory = directory
        self.ledger = ledger
        self.pollable = dict(pollable)
        """Each platform's terms verdict (:func:`pollable_platforms`); missing is not pollable."""
        self.rules = rules or Rules()
        matching = match.version if isinstance(match, CommittedMatch) else "match-given"
        self.version = (
            f"{version}|{matching}|{GUARDS_VERSION}|{live_version()}|{directory.edition}|"
            f"{self.rules.digest()}"
        )
        """The ``derived_version`` without the station's part (:meth:`version_for`)."""

    def version_for(self, station: Station) -> str:
        """The ``derived_version`` of ``station``'s rows: :attr:`version` and its record's."""
        return f"{self.version}|{station_version(station)}"

    # --- per source ----------------------------------------------------------------------------

    def resolve(self, station: Station, present: Sequence[SeenRow]) -> Resolved:
        """Resolve every ledger row of ``station``; ``present`` are the rows of its last read."""
        by_key = {self.ledger.key(station.id, row): row for row in present}
        listed = {self.ledger.ident(station.id, row) for row in present}
        counts: Counter[str] = Counter()
        unmatched: list[Query] = []
        results: list[RowResult] = []
        refused = self._refused(station)
        version_now = self.version_for(station)
        for found in self.ledger.rows(station.id):
            entry = found
            seen = by_key.get(entry.key)
            if refused is not None:
                # checked before any reuse: a station whose terms stop permitting polling,
                # or that is no longer active, lights nothing from rows derived before, but
                # what it last said still darkens
                kept = self._kept(station, entry.key, counts)
                derived = (
                    refused
                    if kept is None
                    else replace(
                        darkening_only(self.current(kept[1], counts), Withheld.TERMS),
                        source_type=refused.source_type,
                    )
                )
                version, reused = version_now, False
            else:
                settled: Derived | None = None
                if seen is not None and entry.pred is not None:
                    entry, settled = self._date_successor(station, entry, seen, counts, version_now)
                derived, version, reused = self._derivation(
                    station, entry, seen, counts, version=version_now, settled=settled
                )
            if seen is not None and derived.withheld in QUEUED:
                query = Query(station_context(station), seen.name, seen.section)
                if query not in unmatched:
                    unmatched.append(query)
            superseded = seen is None and entry.ident in listed
            counts["reused" if reused else "derived"] += 1
            counts[f"withheld:{derived.withheld}" if derived.withheld else "kept"] += 1
            counts["superseded"] += superseded
            for reason, number in derived.target_drops.items():
                counts[f"target:{reason}"] += number
            results.append(
                RowResult(
                    entry,
                    derived,
                    present=seen is not None,
                    reused=reused,
                    superseded=superseded,
                    version=version,
                )
            )
        return Resolved(
            station.id,
            tuple(results),
            tuple(unmatched),
            dict(sorted((name, number) for name, number in counts.items() if number)),
            version=version_now,
        )

    def _refused(self, station: Station) -> Derived | None:
        """``TERMS`` when the station is not active or its platform's terms do not permit
        polling (never stored: it holds only while the terms do)."""
        kind = PLATFORM_TYPES.get(station.platform)
        if kind is None or kind is SourceType.DISTRICT_SITE:
            return None
        if station.status is StationStatus.ACTIVE and self.pollable.get(station.platform, False):
            return None
        return Derived(withheld=Withheld.TERMS, source_type=kind.value)

    def _kept(
        self, station: Station, key: bytes, counts: Counter[str]
    ) -> tuple[str, Derived] | None:
        """The derivation last stored for a key and its version, or ``None`` when none was.

        A stored derivation that does not read (a damaged payload, or a code a later
        vocabulary dropped) gives what its plain darkening part says, under no version
        (``""``: it is never reused), and the failure is logged by source id and error
        type only (never a payload or a key).
        """
        stored = self.ledger.last_derived(key)
        if stored is None:
            return None
        version, payload = stored
        try:
            return version, Derived.from_json(payload)
        except (KeyError, TypeError, ValueError) as error:
            counts["bad_derived"] += 1
            LOG.warning(
                "unreadable stored derivation in %s (%s): kept as its darkening part",
                station.id,
                type(error).__name__,
            )
        return "", self._darkens(key)

    def _darkens(self, key: bytes) -> Derived:
        """A row's plain darkening part as a derivation (``NOT_DERIVED``, schools by NCES id
        with index -1 until :meth:`current` places them)."""
        dark = self.ledger.darkens(key)
        if dark is None:
            return Derived(withheld=Withheld.NOT_DERIVED)
        return Derived(
            withheld=Withheld.NOT_DERIVED,
            voters=tuple(Target(-1, nces_id, "school") for nces_id in dark.schools),
            dissent=() if dark.days is None else dark.days,
        )

    def _store(self, key: bytes, version: str, derived: Derived) -> None:
        self.ledger.store_derived(key, version, derived.to_json(), darkens_of(derived))

    def _derivation(  # noqa: PLR0913 - one row, its reading and its version
        self,
        station: Station,
        entry: LedgerRow,
        seen: SeenRow | None,
        counts: Counter[str],
        *,
        version: str,
        settled: Derived | None = None,
    ) -> tuple[Derived, str, bool]:
        """A row's derivation, the version it was made under, and whether it was reused."""
        if settled is not None:
            self._store(entry.key, version, settled)
            return settled, version, False
        kept = self._kept(station, entry.key, counts)
        if kept is not None and kept[0] == version:
            return kept[1], version, True
        if seen is not None:
            derived = self.derive(station, entry, seen)
            self._store(entry.key, version, derived)
            return derived, version, False
        if kept is not None:
            counts["older_version"] += 1
            return darkening_only(self.current(kept[1], counts)), kept[0], True
        return Derived(withheld=Withheld.NOT_DERIVED), version, False

    def current(self, derived: Derived, counts: Counter[str] | None = None) -> Derived:
        """``derived`` with every school placed by its NCES id in this directory edition.

        A derivation kept from another edition holds that edition's published indexes;
        a school the edition moved takes its new index, and one it dropped is dropped.
        """

        def place(targets: Iterable[Target]) -> tuple[Target, ...]:
            found: list[Target] = []
            for target in targets:
                school = self.directory.schools.get(target.nces_id)
                if school is None:
                    if counts is not None:
                        counts["older_version:not_in_directory"] += 1
                    continue
                found.append(replace(target, index=school.index))
            return tuple(found)

        return replace(
            derived,
            targets=place(derived.targets),
            voters=place(derived.voters),
            stands=place(derived.stands),
        )

    def _date_successor(
        self,
        station: Station,
        entry: LedgerRow,
        seen: SeenRow,
        counts: Counter[str],
        version: str,
    ) -> tuple[LedgerRow, Derived | None]:
        """Settle how a successor is dated (see the module), and its derivation when known.

        Its own interval when a row stamp dates it; from its predecessor's earliest
        posting to its own first sighting when it reads the same at both intervals (it
        may re-render the old posting, and merge orders rows by when they were posted);
        its own interval when its words
        name something its predecessor's did not (a kind of status, an open statement or
        a dissent: a change no re-render makes). Otherwise it is left undated
        (``REWORDED``): "Closed" re-worded on Tuesday to "Closed tomorrow" reads Wednesday
        if posted Tuesday and Tuesday if it re-renders Monday's posting, and nothing tells
        which, so it lights neither.
        """
        pred_key = entry.pred
        pred = None if pred_key is None else self.ledger.row(pred_key)
        stamp = entry.row_stamp
        own_entry = entry._replace(pred=None)
        if (
            pred_key is None
            or pred is None
            or (stamp is not None and entry.hi - self.rules.stamp_window <= stamp <= entry.hi)
        ):
            self.ledger.settle(entry.key)
            counts["successor:own_date"] += 1
            return own_entry, None
        as_before = entry._replace(
            hi=pred.hi, lo=pred.lo, start=pred.start, row_stamp=pred.row_stamp, pred=None
        )
        own = self.derive(station, own_entry, seen)
        before = self.derive(station, as_before, seen)
        if _same_reading(own, before):
            # The reading holds either way, but when it was posted does not: merge orders
            # rows by their posting intervals, so it is dated from the earliest its
            # predecessor can have been posted to its own first sighting. A word another
            # source posted since then overlaps it (a conflict, dark), and the wider
            # interval is read at more times, so it can only darken.
            widened = self._widened(own_entry, pred)
            self.ledger.widen(entry.key, widened.lo, widened.start)
            counts["successor:same_either_way"] += 1
            return widened, self.derive(station, widened, seen)
        kept = self._kept(station, pred_key, counts)
        earlier = (
            kept[1]
            if kept is not None
            and kept[0] == version
            and kept[1].withheld is not Withheld.NOT_DERIVED
            else None
        )
        if earlier is not None and _named_changed(own.kinds, earlier.kinds):
            self.ledger.settle(entry.key)
            counts["successor:changed"] += 1
            return own_entry, own
        # New words posted now, or the old posting re-rendered, and the reading depends on
        # which: left undated, it lights nothing and only darkens, under every version.
        self.ledger.reword(entry.key)
        counts["successor:reworded"] += 1
        undated = own_entry._replace(lo=None, start=Start.REWORDED, row_stamp=None)
        return undated, None

    def _widened(self, entry: LedgerRow, pred: LedgerRow) -> LedgerRow:
        """``entry`` dated from the earliest its predecessor can have been posted (its row
        stamp when that dated it, else its ``lo``) to its own first sighting; undated when
        either start is unknown."""
        stamp = pred.row_stamp
        if stamp is not None and pred.hi - self.rules.stamp_window <= stamp <= pred.hi:
            earliest: datetime | None = stamp
        else:
            earliest = pred.lo
        if entry.lo is None:
            return entry
        if earliest is None:
            return entry._replace(lo=None, start=pred.start)
        return entry._replace(lo=min(earliest, entry.lo))

    # --- per row -------------------------------------------------------------------------------

    def derive(self, station: Station, entry: LedgerRow, seen: SeenRow) -> Derived:
        """What one row gives (see the module's steps), with the schools it stands for."""
        derived, named = self._derive(station, entry, seen)
        own = tuple(target for target in named if target.level == "school")
        lights = derived.claims or derived.opens
        if own and set(derived.kinds) - {"dissent"} and (not lights or derived.undated):
            return replace(derived, stands=own)
        return derived

    def _derive(  # noqa: PLR0911 - one return per step
        self, station: Station, entry: LedgerRow, seen: SeenRow
    ) -> tuple[Derived, tuple[Target, ...]]:
        """What one row gives, and the schools it names once its zones are known."""
        kind = PLATFORM_TYPES.get(station.platform)
        if kind is None or kind is SourceType.DISTRICT_SITE:
            return Derived(withheld=Withheld.EXCLUDED_PLATFORM), ()
        if station.status is not StationStatus.ACTIVE or not self.pollable.get(
            station.platform, False
        ):
            return Derived(withheld=Withheld.TERMS, source_type=kind.value), ()
        if station.platform in EXCLUDED_PLATFORMS or station.leaids:
            return Derived(withheld=Withheld.EXCLUDED_PLATFORM, source_type=kind.value), ()
        outcome = self.match(station, seen)
        matched = Derived(
            withheld=None,
            match_reason=code(outcome.reason, MATCH_REASONS),
            match_level=code(outcome.level, MATCH_LEVELS),
            match_confidence=outcome.confidence,
            source_type=kind.value,
        )
        if not outcome.accepted:
            if outcome.reason == GUARD_REASON:
                return replace(matched, withheld=Withheld.LOCATED), ()
            reason = Withheld.UNMATCHED if outcome.best_id is None else Withheld.REJECTED_MATCH
            return replace(matched, withheld=reason), ()
        targets, voters, drops, first = self.targets(station, seen, outcome)
        base = replace(
            matched,
            targets=tuple(targets),
            voters=tuple(voters),
            target_drops=dict(drops),
            reach=reach_of([*targets, *voters]),
        )
        if not targets and not voters:
            return replace(base, withheld=first or Withheld.UNMATCHED), ()
        rules = self.rules
        if len(targets) >= rules.big_expansion and not (
            outcome.reason in rules.big_expansion_reasons
            and outcome.confidence >= rules.big_expansion_confidence
        ):
            return replace(base, withheld=Withheld.BIG_EXPANSION, targets=(), voters=()), ()
        zones = self._zones([*targets, *voters])
        if zones is None:
            return replace(base, withheld=Withheld.ZONE_UNKNOWN, targets=(), voters=()), ()
        times, stamped, undatable = self._times(entry, zones)
        if undatable is not None:
            return self._undatable(seen, entry, base, zones, undatable), base.targets
        read = self._read(
            station, entry, seen=seen, base=base, zones=zones, times=times, stamped=stamped
        )
        return read, base.targets

    def targets(
        self, station: Station, seen: SeenRow, outcome: Outcome
    ) -> tuple[list[Target], list[Target], Counter[str], Withheld | None]:
        """The schools a row lights, the schools it only stands against, the drops, the first."""
        reached: list[tuple[str, Level]] = [(sid, "school") for sid in outcome.direct]
        reached += [(sid, "district") for sid in outcome.via_district]
        part = names_part(seen.text)
        kept: list[Target] = []
        voters: list[Target] = []
        drops: Counter[str] = Counter()
        first: Withheld | None = None
        for sid, level in reached:
            school = self.directory.schools.get(sid)
            if school is None:
                drops["not_in_directory"] += 1
                continue
            reason = self._target_drop(station, seen, school, level, outcome, part=part)
            target = Target(school.index, sid, level)
            if reason is None:
                kept.append(target)
                continue
            if reason is Withheld.PART_OF_DISTRICT:
                voters.append(target)
            drops[reason.value] += 1
            first = first or reason
        return kept, voters, drops, first

    def _target_drop(  # noqa: PLR0911, PLR0913 - one return per guard
        self,
        station: Station,
        seen: SeenRow,
        school: LiveSchool,
        level: Level,
        outcome: Outcome,
        *,
        part: bool,
    ) -> Withheld | None:
        record = school.record
        section = seen.section or ""
        if record.state not in station.states:
            return Withheld.OUT_OF_STATE
        if (record.public and PRIVATE_SECTION.search(section)) or (
            not record.public and PUBLIC_SECTION.search(section)
        ):
            return Withheld.SECTION
        if level == "district":
            if school.charter:
                return Withheld.DISTRICT_EXCLUDES_CHARTER
            if record.virtual == FULL_VIRTUAL or VIRTUAL_NAME.search(record.name):
                return Withheld.DISTRICT_EXCLUDES_VIRTUAL
            if facility(record):
                return Withheld.FACILITY
            if part:
                return Withheld.PART_OF_DISTRICT
            return None
        if not self._anchored(record, seen, outcome):
            return Withheld.UNANCHORED
        return None

    def _anchored(self, record: School, seen: SeenRow, outcome: Outcome) -> bool:
        """Whether a school-level match rests on more than a public school's name alone."""
        if not record.public or outcome.reason not in NAME_ONLY:
            return True
        if record.district_id is not None and (
            self.directory.district_sizes.get(record.district_id) == 1
        ):
            return True
        levels = RECORD_LEVELS.get(record.level or "", frozenset())
        return any(word in levels and found.search(seen.name) for word, found in LISTING_LEVELS)

    def _zones(self, targets: Iterable[Target]) -> tuple[str, ...] | None:
        found: set[str] = set()
        for target in targets:
            zones = self.directory.schools[target.nces_id].zones
            if not zones:
                return None
            found.update(zones)
        return tuple(sorted(found))

    def _times(
        self, entry: LedgerRow, zones: Sequence[str]
    ) -> tuple[list[datetime], bool, Withheld | None]:
        """The times a row is read at, whether its row stamp gives them, or why it is withheld."""
        rules = self.rules
        stamp = entry.row_stamp
        if stamp is not None and entry.hi - rules.stamp_window <= stamp <= entry.hi:
            return [stamp], True, None
        if entry.lo is None:
            reason = {Start.CHURN: Withheld.CHURN, Start.REWORDED: Withheld.REWORDED}.get(
                entry.start, Withheld.UNKNOWN_START
            )
            return [], False, reason
        if entry.hi - entry.lo > rules.longest_interval:
            return [], False, Withheld.INTERVAL_TOO_LONG
        return samples(entry.lo, entry.hi, zones, rules.sample_step), False, None

    def _undatable(
        self,
        seen: SeenRow,
        entry: LedgerRow,
        base: Derived,
        zones: Sequence[str],
        reason: Withheld,
    ) -> Derived:
        """A row that cannot be dated lights nothing; when its words retract, deny or say
        open at its first sighting, or it names part of its district, it stands against
        every day of its schools (a dissent needs no date: it only darkens)."""
        readings = [self._reading(seen, entry.hi, zone) for zone in zones]
        base = replace(base, kinds=_kinds(readings), undated=True)
        if base.voters or any(reading.verdict in {"dissent", "open"} for reading in readings):
            return replace(
                base, withheld=reason, targets=(), voters=base.targets + base.voters, dissent=()
            )
        return replace(base, withheld=reason, targets=(), voters=())

    # --- reading -------------------------------------------------------------------------------

    def _read(  # noqa: PLR0913 - one row and its readings
        self,
        station: Station,
        entry: LedgerRow,
        *,
        seen: SeenRow,
        base: Derived,
        zones: Sequence[str],
        times: Sequence[datetime],
        stamped: bool,
    ) -> Derived:
        readings: list[_Reading] = []
        split = False
        for moment in times:
            here = [self._reading(seen, moment, zone) for zone in zones]
            if any(reading.sig() != here[0].sig() for reading in here[1:]):
                split = True
            readings.extend(here)
        base = replace(
            base,
            kinds=_kinds(readings),
            undated=any(reading.undated for reading in readings) and not stamped,
        )
        dissents = [reading for reading in readings if reading.verdict == "dissent"]
        if dissents:
            every = any(not reading.days for reading in dissents)
            darkening = [reading for reading in readings if reading.verdict in {"dissent", "open"}]
            days = sorted({day for reading in darkening for day in reading.days})
            return replace(
                base,
                withheld=dissents[0].reason,
                targets=(),
                voters=base.targets + base.voters,
                dissent=() if every else tuple(days),
            )
        voters_dissent = self._voter_days(readings) if base.voters else None
        first = readings[0]
        withheld: Withheld | None = None
        if split:
            withheld = Withheld.ZONE_SPLIT
        elif any(reading.sig() != first.sig() for reading in readings[1:]):
            withheld = Withheld.INTERVAL_DISAGREES
        elif first.verdict == "withheld":
            withheld = first.reason
        else:
            withheld = self._board_reason(station, seen, entry, first, stamped=stamped)
        if withheld is None and (
            first.undated and not stamped and not self._read_previous_school_day(entry, zones)
        ):
            withheld = Withheld.STALE_UNPROVEN
        if withheld is not None:
            if any(reading.verdict == "open" for reading in readings):
                # an open statement that cannot be kept still stands against every day
                voters = base.targets + base.voters
                return replace(base, withheld=withheld, targets=(), voters=voters, dissent=())
            return replace(base, withheld=withheld, targets=(), dissent=voters_dissent)
        lit = replace(
            base,
            announced_at=self._announced(entry, stamped=stamped, times=times),
            confidence=min(reading.confidence for reading in readings),
            notes=first.notes,
            dissent=voters_dissent,
        )
        if first.verdict == "open":
            return replace(lit, opens=first.days)
        return replace(lit, claims=first.claims)

    def _voter_days(self, readings: Sequence[_Reading]) -> tuple[date, ...]:
        """The days a part-of-district row stands against: its claimed days, else every day."""
        days = {claim.day for reading in readings for claim in reading.claims}
        days |= {day for reading in readings for day in reading.days}
        return tuple(sorted(days))

    def _reading(self, seen: SeenRow, moment: datetime, zone: str) -> _Reading:  # noqa: PLR0911
        rules = self.rules
        parsed = self.reader(seen.text, posted_at=moment, tz=zone)
        local = moment.astimezone(_zone(zone)).date()
        notes = tuple(
            sorted({note if note in NOTE_CODES else UNKNOWN_CODE for note in parsed.notes})
        )
        entries = _status_entries(parsed)
        entry_days = tuple(sorted({day for item in entries for day in item.dates}))
        named = tuple(sorted({item.kind for item in entries}))
        if not named and set(notes) & UNSURE_NOTES:
            named = (UNSURE,)
        dissent = ("dissent",)
        if set(notes) & DISSENT_NOTES:
            return _Reading("dissent", reason=Withheld.NOTE, notes=notes, kinds=dissent)
        if entries and (parsed.other_causes and not (parsed.names_weather or parsed.reason)):
            return _Reading(
                "dissent", days=entry_days, reason=Withheld.NOT_WEATHER, notes=notes, kinds=dissent
            )
        remote = bool(entries) and all(e.kind == "remote" for e in entries)
        says_open = parsed.says_open and parsed.confidence >= rules.open_confidence
        wording = (
            open_wording_reason(seen.text, seen.name)
            if says_open and not entries
            else wording_reason(seen.text, seen.name, remote=remote)
        )
        if wording is not None:
            # A planned day, a learning mode, the SAT or unclear day numbers: the row says
            # the school is not closed for weather on its days (every day when it names
            # none), so it stands against older statuses, whether the reader found a
            # status or not.
            reason = Withheld.NOT_WEATHER if wording == "planned" else Withheld.WORDING
            return _Reading("dissent", days=entry_days, reason=reason, notes=notes, kinds=dissent)
        if not entries:
            if says_open:
                return self._open_reading(seen, moment, zone, parsed, notes)
            return _Reading(
                "withheld", reason=self._weak(parsed.confidence), notes=notes, kinds=named
            )
        if parsed.confidence < rules.min_confidence:
            return _Reading(
                "withheld", reason=self._weak(parsed.confidence), notes=notes, kinds=named
            )
        if not set(notes) <= ALLOWED_NOTES:
            return _Reading("withheld", reason=Withheld.NOTE, notes=notes, kinds=named)
        if parsed.says_open or open_words(seen.text):
            # status words beside open words: the row does not say which holds
            return _Reading(
                "dissent", days=entry_days, reason=Withheld.WORDING, notes=notes, kinds=dissent
            )
        low, high = local - timedelta(days=RANGE_BEFORE), local + timedelta(days=RANGE_AFTER)
        if any(not low <= day <= high for day in entry_days):
            return _Reading("withheld", reason=Withheld.OUT_OF_WINDOW, notes=notes, kinds=named)
        claims = tuple(
            sorted(
                (_claim(item, day, parsed.reason) for item in entries for day in item.dates),
                key=lambda claim: (claim.day, claim.kind),
            )
        )
        if len({claim.day for claim in claims}) != len(claims):
            return _Reading("withheld", reason=Withheld.NOTE, notes=notes, kinds=named)
        return _Reading(
            "claim",
            claims=claims,
            undated=not any(item.dates_stated for item in entries),
            confidence=parsed.confidence,
            notes=notes,
            kinds=named,
        )

    def _weak(self, confidence: float) -> Withheld:
        rules = self.rules
        if rules.weak_confidence <= confidence < rules.min_confidence:
            return Withheld.WEAK
        return Withheld.NOT_STATUS

    def _open_reading(
        self, seen: SeenRow, moment: datetime, zone: str, parsed: ParsedLike, notes: tuple[str, ...]
    ) -> _Reading:
        """An open statement's days: the days it names, or for an undated one the posting day,
        when the reader would give a bare status that day (overnight or morning).

        One that cannot be dated so is a dissent (``OPEN_UNDATED``), never an open signal:
        for the days a bare status posted then is for, or every day when that names none
        or the statement names a day the exact reading does not cover.
        """
        local = moment.astimezone(_zone(zone)).date()
        kinds = ("open",)
        named, _may = day_words(seen.text, local, local)
        if named:
            days = open_days(seen.text, local)
            if not days:
                return _Reading("dissent", reason=Withheld.OPEN_UNDATED, notes=notes, kinds=kinds)
            return _Reading(
                "open", days=days, confidence=parsed.confidence, notes=notes, kinds=kinds
            )
        bare = self.reader(BARE_STATUS, posted_at=moment, tz=zone)
        bare_days = sorted({day for item in _status_entries(bare) for day in item.dates})
        if bare_days != [local]:
            return _Reading(
                "dissent",
                days=tuple(bare_days),
                reason=Withheld.OPEN_UNDATED,
                notes=notes,
                kinds=kinds,
            )
        return _Reading(
            "open",
            days=(local,),
            undated=True,
            confidence=parsed.confidence,
            notes=notes,
            kinds=("open",),
        )

    def _board_reason(
        self, station: Station, seen: SeenRow, entry: LedgerRow, first: _Reading, *, stamped: bool
    ) -> Withheld | None:
        """G5: a board row lights only the day its own date names, or with a fresh row stamp."""
        kind = PLATFORM_TYPES.get(station.platform)
        if kind not in BOARD_TYPES:
            return None
        days = {claim.day for claim in first.claims} | set(first.days)
        if station.platform in BOARD_ROW_DATES:
            own = board_date(seen.row_date)
            return None if own is not None and days == {own} else Withheld.BOARD_DATE
        stamp = entry.row_stamp
        fresh = (
            stamped
            and stamp is not None
            and entry.hi - self.rules.board_stamp_window <= stamp <= entry.hi
        )
        return None if fresh else Withheld.BOARD_DATE

    def _read_previous_school_day(self, entry: LedgerRow, zones: Sequence[str]) -> bool:
        """Addendum 3: the source was read on the school day before the row's first sighting,
        in every zone, so an undated row can be new."""
        reads = self.ledger.good_reads(entry.source_id)
        for zone in zones:
            tz = _zone(zone)
            today = entry.hi.astimezone(tz).date()
            before = previous_school_day(today)
            if not any(read.astimezone(tz).date() == before for read in reads):
                return False
        return True

    def _announced(
        self, entry: LedgerRow, *, stamped: bool, times: Sequence[datetime]
    ) -> datetime | None:
        """Spec 7.6: from the row stamp, or (owner Q6) ``hi`` when the row was watched
        appearing within 15 minutes; never from a page stamp or a cold row."""
        if stamped:
            return times[0]
        watched = self.rules.watched_announce
        if watched is not None and entry.lo is not None and entry.hi - entry.lo <= watched:
            return entry.hi
        return None


_OPEN_WORDS: Final = re.compile(
    "|".join(
        [
            r"(?P<today>\btoday\b|\bthis\s+morning\b)",
            r"(?P<tomorrow>\btomorrow\b)",
            *(rf"(?P<w{number}>\b{word}\b\.?)" for number, word in enumerate(WEEKDAYS)),
            *(
                rf"(?P<m{number}>\b{word}\.?\s*(?P<d{number}>\d{{1,2}})(?:st|nd|rd|th)?\b)"
                for number, word in enumerate(MONTHS)
            ),
            r"(?P<numeric>(?<![\d/])(?P<nm>\d{1,2})/(?P<nd>\d{1,2})(?![\d/]))",
        ]
    ),
    re.IGNORECASE,
)


def open_days(text: str, posted: date) -> tuple[date, ...]:
    """The days an open statement names, read exactly against its posting day ``posted``.

    "today" is the posting day, "tomorrow" the next, a weekday its next date from the
    posting day on, a month and day or ``M/D`` that date within the next
    :data:`OPEN_AHEAD` days. Anything else that names a day ("tonight", "yesterday", a
    span, a date out of reach) gives no day: such an open statement is not kept.
    """
    words = STAMP_PHRASE.sub(" ", text)
    days: set[date] = set()
    for found in _OPEN_WORDS.finditer(words):
        day = _open_day(found, posted)
        if day is None:
            return ()
        days.add(day)
    rest = _OPEN_WORDS.sub(" ", words)
    if day_words(rest, posted, posted)[0]:
        return ()  # another day word the exact reading does not cover
    return tuple(sorted(days))


def _open_day(found: re.Match[str], posted: date) -> date | None:
    group = found.lastgroup or ""
    if group == "today":
        return posted
    if group == "tomorrow":
        return posted + timedelta(days=1)
    if group.startswith("w"):
        return posted + timedelta(days=(int(group[1:]) - posted.weekday()) % 7)
    if group.startswith("m") or group == "numeric":
        if group == "numeric":
            month, number = int(found.group("nm")), int(found.group("nd"))
        else:
            month, number = int(group[1:]) + 1, int(found.group(f"d{group[1:]}"))
        for year in (posted.year, posted.year + 1):
            try:
                day = date(year, month, number)
            except ValueError:
                return None
            if 0 <= (day - posted).days <= OPEN_AHEAD:
                return day
    return None


def previous_school_day(day: date) -> date:
    """The weekday before ``day``."""
    before = day - timedelta(days=1)
    while before.weekday() >= 5:  # noqa: PLR2004 - Saturday and Sunday
        before -= timedelta(days=1)
    return before


_BOARD_FORMATS: Final = ("%Y-%m-%d", "%A, %B %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%A %B %d, %Y")
_ORDINAL: Final = re.compile(r"(?<=\d)(?:st|nd|rd|th)\b", re.IGNORECASE)


def board_date(text: str) -> date | None:
    """A board's row date, in the forms boards write it; ``None`` when it is not one."""
    clean = _ORDINAL.sub("", " ".join(text.split())).strip()
    for form in _BOARD_FORMATS:
        try:
            return datetime.strptime(clean, form).date()
        except ValueError:
            continue
    return None


def pollable_platforms(registry: Registry) -> dict[str, bool]:
    """Each registry platform's terms verdict (``Terms.pollable``), for :class:`Resolver`."""
    return {platform.id: platform.terms.pollable for platform in registry.platforms.values()}


ResolveFn = Callable[[Station, Sequence[SeenRow]], Resolved]

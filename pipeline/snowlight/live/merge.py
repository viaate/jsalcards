"""Merge: one status per school and day from every source's rows (pure, spec 7.5).

The input is every resolved row (:class:`~snowlight.live.resolve.Resolved`) and
which sources are held (G13: a source's rows stand only while its last good read
is recent). For each school and local day:

1. **The latest posted row wins**, so a delay upgraded to a closure becomes
   closed. A row wins only when it was surely posted after every row that says
   something else: a row first seen after the newest row's interval began (after
   its ``lo``, or its row stamp) may have been posted after it, so the two are
   read as posted at the same time. Among those, two different statuses are both
   withheld (``CONFLICT``); a school's own status beats its district's only when
   they were first seen at the very same time (a real tie, as when one list holds
   both), never when their intervals merely overlap.
   Identical ones merge and keep the earliest trustworthy ``announced_at`` since
   the status last changed. (The spec compares first sightings only; two lists
   read a few minutes apart would then be ordered by when they were read.)
2. **Open and dissent.** When the latest word is an open statement (owner
   decision Q8) or a dissent (a retraction, a denial, a narrowing, a cause that is
   not weather), nothing is published (``RETRACTED``); an open statement is kept as
   an :class:`OpenSignal` for S7, which never lights the map. Beside a status at
   the same time, either is a ``CONFLICT``, whatever the levels: a district's later
   word darkens a school's status it may have been posted after.
   A source that is not held contributes no status (``STALE_SOURCE``), but its
   dissents and open statements still stand against older statuses: they only darken.
   A school's own row that is present in a held source and lights no status of its
   own for the day (withheld, or dated by its posting time to another day) stands
   against its district's status when its words name another kind (``CONFLICT``):
   a school is never shown with its district's status while its own row says
   something else.
3. **A vanished row is kept through its day** while its source is held, unless
   the ``vanish_retracts`` flag is on, it is superseded (its listing is present
   under a newer row: the source no longer says it, so it gives no status or open
   signal, only its dissents), or it vanished before its day began in the school's
   zone (``VANISHED_BEFORE_DAY``: "Closed Thursday" taken down on Wednesday, or
   "Closed" for Tuesday posted Monday at 20:00 and taken down at 21:30;
   ``vanished_before_day`` sets a margin, none by default). A row gone from every
   source that carried it within an hour of first sight is logged
   (:attr:`Merged.fast_vanishes`), and so is every status lit only by vanished rows
   (:attr:`Merged.held_vanishes`), so the soak can count both for the owner's
   ``vanish_retracts`` decision.
4. **Until further notice** (F14): a status the reader marks open-ended also covers
   the school days after its first, up to the school's local today and three
   school days in all, while its row is present and its source held.
5. **Expiry** (G10): a day before the school's local today in any of its zones is
   dropped (``PAST_DAY``), and so is a day outside ``live.local_days``
   (``OUT_OF_WINDOW``).
6. **Breaker** (G9): a source contributing more statuses than its limit has all of
   them dropped (``BREAKER``), and is named in :attr:`Merged.breakers`.
7. **The admin outranks every list** (accounts spec C, :func:`with_overrides`): a
   status the site's admin set by hand (:class:`AdminStatus`, from
   :mod:`snowlight.live.overrides`) replaces whatever the lists gave that school on that
   day, and an admin "open" takes the lists' status away. It runs after the merge, so
   no list row, open statement or dissent can outvote it.

The output is the published :class:`~snowlight.schemas.live.Closing` rows, the
open signals, one private provenance line per published status and the counts.
Every choice is made in a fixed order (by source id and row key), so the output
does not depend on the order of its input.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

from snowlight.live.guards import Rules, Withheld, breaker_limit
from snowlight.live.provenance import SourceType, provenance_line
from snowlight.live.resolve import DayClaim, LiveDirectory, Resolved, RowResult
from snowlight.output import JSONValue
from snowlight.schemas.live import Closing, local_days
from snowlight.schemas.scalars import MAX_MINUTES_AGO, MAX_SHIFT_MINUTES, MINUTES_PER_DAY
from snowlight.schemas.vocab import REASON_BY_LABEL, SHIFTED, STATUS_BY_KIND, Status

type Verdict = Literal["claim", "open", "dissent", "stand"]
SATURDAY: Final = 5


@dataclass(frozen=True, slots=True)
class Item:
    """What one row says of one school: a status or an open statement for a day, or a dissent."""

    verdict: Verdict
    school: int
    nces_id: str
    day: date | None
    """``None`` only for a dissent that stands against every day."""
    claim: DayClaim | None
    level: str
    source_id: str
    result: RowResult

    @property
    def posted_hi(self) -> datetime:
        return self.result.row.hi

    @property
    def posted_lo(self) -> datetime:
        """The earliest the row can have been posted: its row stamp when that dated it, else
        the read before it that lacked it (its first sighting when neither is known)."""
        row = self.result.row
        stamp = row.row_stamp
        if stamp is not None and self.result.derived.announced_at == stamp:
            return stamp
        return row.lo or row.hi

    def key(self) -> tuple[object, ...]:
        """What two items must share to say the same thing."""
        if self.claim is None:
            return (self.verdict,)
        return (self.verdict, self.claim.kind, self.claim.shift_minutes, self.claim.clock_minute)


@dataclass(frozen=True, slots=True)
class OpenSignal:
    """A school's explicit word that it runs as normal on a day (owner Q8, for S7).

    It never lights the map.
    """

    school: int
    nces_id: str
    day: date
    at: datetime
    """When the statement was first seen."""
    source_id: str
    source_type: str | None
    confidence: float | None

    def to_public_json(self) -> dict[str, JSONValue]:
        """The shape published for S7: the school, day, time and confidence only.

        Source names and source types are never published (spec D11, section 12).
        """
        return {
            "school": self.school,
            "day": self.day.isoformat(),
            "kind": "open",
            "at": self.at.astimezone(UTC).isoformat(),
            "confidence": self.confidence,
        }

    def to_private_json(self) -> dict[str, JSONValue]:
        """The private provenance shape: the public one plus where it came from."""
        return {
            **self.to_public_json(),
            "nces_id": self.nces_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
        }


@dataclass(frozen=True, slots=True)
class FastVanish:
    """A status every source took down within the fast-vanish time of first showing it."""

    school: int
    day: date
    sources: tuple[str, ...]
    first_seen: datetime
    gone_at: datetime


@dataclass(frozen=True, slots=True)
class HeldVanish:
    """A status lit only by rows their sources took down (kept through its day)."""

    school: int
    day: date
    sources: tuple[str, ...]
    gone_at: datetime
    """When the last of them vanished."""


@dataclass(frozen=True, slots=True)
class Merged:
    """One merge's result."""

    closings: tuple[Closing, ...]
    opens: tuple[OpenSignal, ...]
    provenance: tuple[dict[str, JSONValue], ...]
    withheld: Mapping[str, int]
    breakers: tuple[str, ...]
    fast_vanishes: tuple[FastVanish, ...]
    held_vanishes: tuple[HeldVanish, ...] = ()
    counts: Mapping[str, int] = field(default_factory=dict)


def school_today(zones: Sequence[str], moment: datetime) -> date:
    """The latest local date of ``moment`` over a school's zones (a day passed anywhere is past)."""
    return max(moment.astimezone(ZoneInfo(zone)).date() for zone in zones)


def _items(result: RowResult) -> list[Item]:
    derived = result.derived
    source = result.row.source_id
    found: list[Item] = []
    for target in derived.targets:
        for claim in derived.claims:
            found.append(
                Item(
                    "claim",
                    target.index,
                    target.nces_id,
                    claim.day,
                    claim,
                    target.level,
                    source,
                    result,
                )
            )
        for day in derived.opens:
            found.append(
                Item("open", target.index, target.nces_id, day, None, target.level, source, result)
            )
    if derived.dissent is not None:
        against: Iterable[date | None] = derived.dissent or (None,)
        for target in derived.voters:
            for when in against:
                found.append(
                    Item(
                        "dissent",
                        target.index,
                        target.nces_id,
                        when,
                        None,
                        target.level,
                        source,
                        result,
                    )
                )
    return found


def _ufn_days(first: date, today: date, most: int) -> list[date]:
    """The school days after ``first`` up to ``today`` that an open-ended status covers."""
    days: list[date] = []
    day = first + timedelta(days=1)
    while day <= today and len(days) < most - 1:
        if day.weekday() < SATURDAY:
            days.append(day)
        day += timedelta(days=1)
    return days


def day_start(day: date, zones: Sequence[str]) -> datetime:
    """When ``day`` begins for a school: its latest local midnight over the school's zones."""
    return max(datetime.combine(day, time(0), ZoneInfo(zone)) for zone in zones).astimezone(UTC)


def merge(  # noqa: PLR0912, PLR0915 - the steps of the module, in order
    resolved: Iterable[Resolved],
    *,
    held: Mapping[str, bool],
    directory: LiveDirectory,
    generated_at: datetime,
    rules: Rules | None = None,
) -> Merged:
    """Merge every source's rows into one status per school and day (see the module)."""
    rules = rules or Rules()
    withheld: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    items: list[Item] = []
    standing: dict[int, list[Item]] = defaultdict(list)
    for source in resolved:
        for result in source.rows:
            if result.present and not result.superseded and held.get(source.source_id, False):
                for target in result.derived.stands:
                    standing[target.index].append(
                        Item(
                            "stand",
                            target.index,
                            target.nces_id,
                            None,
                            None,
                            target.level,
                            source.source_id,
                            result,
                        )
                    )
            for item in _items(result):
                if item.verdict == "dissent":
                    items.append(item)  # a dissent only darkens: it stands, held or not
                elif result.superseded:
                    withheld[Withheld.SUPERSEDED.value] += 1
                    if item.verdict == "open":
                        items.append(replace(item, verdict="dissent"))
                elif not held.get(source.source_id, False):
                    withheld[Withheld.STALE_SOURCE.value] += 1
                    if item.verdict == "open":
                        items.append(replace(item, verdict="dissent"))
                elif not result.present and rules.vanish_retracts:
                    withheld["vanished"] += 1
                else:
                    items.append(item)

    # ufn: extend open-ended statuses over the school days since, while present and held
    first_day, last_day = local_days(generated_at)
    extended: list[Item] = []
    for item in items:
        claim = item.claim
        if claim is None or not claim.ufn or not item.result.present or item.day is None:
            continue
        zones = directory.schools[item.nces_id].zones
        today = school_today(zones, generated_at)
        for day in _ufn_days(item.day, today, rules.ufn_school_days):
            extended.append(
                Item(
                    "claim",
                    item.school,
                    item.nces_id,
                    day,
                    claim,
                    item.level,
                    item.source_id,
                    item.result,
                )
            )
    items.extend(extended)
    counts["ufn_days"] = len(extended)

    # drop the days that are past or outside the window (G10)
    kept: list[Item] = []
    for item in items:
        if item.day is None or item.verdict == "dissent":
            kept.append(item)
            continue
        zones = directory.schools[item.nces_id].zones
        absent = item.result.row.absent_since
        if item.day < school_today(zones, generated_at):
            withheld[Withheld.PAST_DAY.value] += 1
        elif not first_day <= item.day <= last_day:
            withheld[Withheld.OUT_OF_WINDOW.value] += 1
        elif (
            not item.result.present
            and absent is not None
            and absent <= day_start(item.day, zones) - rules.vanished_before_day
        ):
            withheld[Withheld.VANISHED_BEFORE_DAY.value] += 1
        else:
            kept.append(item)

    # the breaker (G9)
    per_source = Counter(item.source_id for item in kept if item.verdict == "claim")
    breakers = sorted(
        source for source, number in per_source.items() if number > breaker_limit(source, rules)
    )
    if breakers:
        tripped = set(breakers)
        withheld[Withheld.BREAKER.value] += sum(per_source[source] for source in breakers)
        kept = [item for item in kept if item.source_id not in tripped or item.verdict == "dissent"]

    # group per school and day; a dissent for every day joins each of its school's days
    groups: dict[tuple[int, date], list[Item]] = defaultdict(list)
    every_day: dict[int, list[Item]] = defaultdict(list)
    for item in kept:
        if item.day is None:
            every_day[item.school].append(item)
        else:
            groups[(item.school, item.day)].append(item)
    for (school, _day), group in groups.items():
        group.extend(every_day.get(school, ()))

    closings: list[Closing] = []
    opens: list[OpenSignal] = []
    provenance: list[dict[str, JSONValue]] = []
    vanishes: list[FastVanish] = []
    kept_vanished: list[HeldVanish] = []
    for (school, day), group in sorted(groups.items()):
        claims = [item for item in group if item.verdict == "claim"]
        vanish = _fast_vanish(school, day, claims, rules)
        if vanish is not None:
            vanishes.append(vanish)
        latest = max(item.posted_hi for item in group)
        newest = [item for item in group if item.posted_hi == latest]
        since = min(item.posted_lo for item in newest)
        top = [item for item in group if item.posted_hi == latest or item.posted_hi > since]
        verdicts = {item.verdict for item in top}
        if "claim" in verdicts and len(verdicts) > 1:
            withheld[Withheld.CONFLICT.value] += 1
            continue
        if "dissent" in verdicts:
            if claims:
                withheld[Withheld.RETRACTED.value] += 1
            continue
        if verdicts == {"open"}:
            first = min(top, key=_order)
            confidences = [c for item in top if (c := item.result.derived.confidence) is not None]
            opens.append(
                OpenSignal(
                    school=school,
                    nces_id=first.nces_id,
                    day=day,
                    at=latest,
                    source_id=first.source_id,
                    source_type=first.result.derived.source_type,
                    confidence=min(confidences, default=None),
                )
            )
            if claims:
                withheld[Withheld.RETRACTED.value] += 1
            continue
        school_level = [item for item in top if item.level == "school"]
        if (
            len({item.key() for item in top}) > 1
            and school_level
            and len({item.posted_hi for item in top}) == 1
        ):
            top = school_level  # a real tie: one list holds both, and the school's own row wins
        if len({item.key() for item in top}) > 1:
            withheld[Withheld.CONFLICT.value] += 1
            continue
        if _school_row_stands(top, group, standing.get(school, ())):
            withheld[Withheld.CONFLICT.value] += 1
            counts["school_row_stands"] += 1
            continue
        winner = min(top, key=_order)
        closing, announced_by = _closing(
            school, day, winner=winner, top=top, group=group, generated_at=generated_at
        )
        closings.append(closing)
        provenance.append(_provenance(closing, winner, top, announced_by, generated_at))
        if not any(item.result.present for item in top):
            gone = [at for item in top if (at := item.result.row.absent_since) is not None]
            kept_vanished.append(
                HeldVanish(
                    school=school,
                    day=day,
                    sources=tuple(sorted({item.source_id for item in top})),
                    gone_at=max(gone, default=latest),
                )
            )
    counts["closings"] = len(closings)
    counts["opens"] = len(opens)
    counts["held_vanishes"] = len(kept_vanished)
    return Merged(
        closings=tuple(closings),
        opens=tuple(opens),
        provenance=tuple(provenance),
        withheld=dict(sorted(withheld.items())),
        breakers=tuple(breakers),
        fast_vanishes=tuple(vanishes),
        held_vanishes=tuple(kept_vanished),
        counts=dict(sorted(counts.items())),
    )


def _school_row_stands(top: Sequence[Item], group: Sequence[Item], stands: Sequence[Item]) -> bool:
    """Whether a school's own present row stands against the district status ``top`` holds:
    it gives no status of its own for the day and its words name another kind."""
    if not stands or any(item.level != "district" for item in top):
        return False
    kinds = {item.claim.kind for item in top if item.claim is not None}
    here = {(item.source_id, item.result.row.key) for item in group}
    for stand in stands:
        if (stand.source_id, stand.result.row.key) in here:
            continue  # the row speaks for this day itself
        if set(stand.result.derived.kinds) - {"dissent"} - kinds:
            return True
    return False


def _order(item: Item) -> tuple[str, bytes]:
    """The fixed order every choice among equals follows."""
    return (item.source_id, item.result.row.key)


def _fast_vanish(school: int, day: date, claims: Sequence[Item], rules: Rules) -> FastVanish | None:
    if not claims or any(item.result.present for item in claims):
        return None
    gone = [item.result.row.absent_since for item in claims]
    if any(at is None for at in gone):
        return None
    first = min(item.posted_hi for item in claims)
    last_gone = max(at for at in gone if at is not None)
    quick = all(
        at is not None and at - item.posted_hi <= rules.fast_vanish
        for item, at in zip(claims, gone, strict=True)
    )
    if not quick:
        return None
    sources = tuple(sorted({item.source_id for item in claims}))
    return FastVanish(school=school, day=day, sources=sources, first_seen=first, gone_at=last_gone)


def _closing(  # noqa: PLR0913 - the school-day, its winners and its group
    school: int,
    day: date,
    *,
    winner: Item,
    top: Sequence[Item],
    group: Sequence[Item],
    generated_at: datetime,
) -> tuple[Closing, Item | None]:
    """The published status, and the row whose announcement it shows (if any)."""
    claim = winner.claim
    if claim is None:
        raise ValueError("a published status comes from a claim")
    status = STATUS_BY_KIND[claim.kind]
    reasons = {item.claim.reason for item in top if item.claim is not None}
    label = reasons.pop() if len(reasons) == 1 else None
    shift = (
        claim.shift_minutes
        if claim.shift_minutes and claim.shift_minutes <= MAX_SHIFT_MINUTES
        else None
    )
    clock = (
        claim.clock_minute
        if claim.clock_minute is not None and 0 <= claim.clock_minute < MINUTES_PER_DAY
        else None
    )
    # The earliest trustworthy announcement since the status last changed.
    same = winner.key()
    changed = [item.posted_hi for item in group if item.key() != same]
    since = max(changed, default=None)
    announced = [
        (at, _order(item), item)
        for item in group
        if item.key() == same
        and (since is None or item.posted_hi > since)
        and (at := item.result.derived.announced_at) is not None
        and at <= generated_at
        and generated_at - at <= timedelta(minutes=MAX_MINUTES_AGO)
    ]
    earliest = min(announced, key=lambda found: found[:2]) if announced else None
    closing = Closing(
        school=school,
        day=day,
        status=status,
        announced_at=None if earliest is None else earliest[0].astimezone(UTC),
        reason=None if label is None else REASON_BY_LABEL[label],
        shift_minutes=shift,
        clock_minute=clock,
    )
    return closing, None if earliest is None else earliest[2]


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat()


def _provenance(
    closing: Closing,
    winner: Item,
    top: Sequence[Item],
    announced_by: Item | None,
    generated_at: datetime,
) -> dict[str, JSONValue]:
    row = winner.result.row
    derived = winner.result.derived
    contributing: list[JSONValue] = [
        [item.source_id, item.result.derived.source_type, item.result.row.key.hex()]
        for item in sorted(top, key=_order)
    ]
    return provenance_line(
        {
            "nces_id": winner.nces_id,
            "school": closing.school,
            "day": closing.day.isoformat(),
            "status": int(closing.status),
            "reason": None if closing.reason is None else int(closing.reason),
            "source_type": derived.source_type,
            "source_id": winner.source_id,
            "row_key": row.key.hex(),
            "lo": _iso(row.lo),
            "hi": _iso(row.hi),
            "row_stamp": _iso(row.row_stamp),
            "f5_confidence": derived.confidence,
            "f5_notes": list(derived.notes),
            "match_reason": derived.match_reason,
            "match_level": derived.match_level,
            "target_level": winner.level,
            "match_confidence": derived.match_confidence,
            "derived_version": winner.result.version,
            "generated_at": _iso(generated_at),
            "present": winner.result.present,
            "contributing": contributing,
            "announced_by": None if announced_by is None else announced_by.result.row.key.hex(),
            "sources": len({item.source_id for item in top}),
        }
    )


ADMIN_SOURCE: Final = "snowlight-admin"
"""The source id of every status the admin set (provenance only; never published)."""
ADMIN_TYPE: Final = SourceType.ADMIN.value
ADMIN_VERSION: Final = "admin-1"


@dataclass(frozen=True, slots=True)
class AdminStatus:
    """A status the site's admin set by hand for one school on one local day.

    ``status`` ``None`` is "open": the school runs as normal that day, whatever a list says.
    """

    school: int
    nces_id: str
    day: date
    status: Status | None
    shift_minutes: int | None
    clock_minute: int | None
    set_at: datetime
    """When the admin set it: the "Posted" time."""
    level: Literal["school", "district"]
    """Whether it was set for the school itself or for its whole district."""
    key: str
    """The override's own id (a digest of its scope, target and time; no words)."""

    def __post_init__(self) -> None:
        if self.status not in SHIFTED and (
            self.shift_minutes is not None or self.clock_minute is not None
        ):
            raise ValueError("only a delay or an early dismissal has times")


def with_overrides(merged: Merged, admin: Sequence[AdminStatus], generated_at: datetime) -> Merged:
    """``merged`` with the admin's statuses on top (rule 7): each replaces the lists'
    status and open statement for its school and day; an admin "open" leaves no status and
    stands as an open statement. Two admin statuses for one school and day: the school's
    own beats its district's, then the later one wins.

    Raises:
        ValueError: an admin status was set after ``generated_at``.
    """
    chosen: dict[tuple[int, date], AdminStatus] = {}
    for status in sorted(
        admin, key=lambda found: (found.level == "school", found.set_at, found.key)
    ):
        if status.set_at > generated_at:
            raise ValueError("an admin status was set after the file's generated_at")
        chosen[(status.school, status.day)] = status
    if not chosen:
        return merged
    kept = [
        (closing, line)
        for closing, line in zip(merged.closings, merged.provenance, strict=True)
        if (closing.school, closing.day) not in chosen
    ]
    replaced = len(merged.closings) - len(kept)
    opens = [signal for signal in merged.opens if (signal.school, signal.day) not in chosen]
    for (school, day), status in sorted(chosen.items()):
        if status.status is None:
            opens.append(
                OpenSignal(
                    school=school,
                    nces_id=status.nces_id,
                    day=day,
                    at=status.set_at,
                    source_id=ADMIN_SOURCE,
                    source_type=ADMIN_TYPE,
                    confidence=1.0,
                )
            )
            continue
        closing = Closing(
            school=school,
            day=day,
            status=status.status,
            announced_at=status.set_at,
            reason=None,
            shift_minutes=status.shift_minutes,
            clock_minute=status.clock_minute,
            manual=True,
        )
        kept.append((closing, _admin_provenance(closing, status, generated_at)))
    kept.sort(key=lambda pair: (pair[0].school, pair[0].day))
    opens.sort(key=lambda signal: (signal.school, signal.day))
    counts = Counter(merged.counts)
    counts["admin"] = sum(1 for status in chosen.values() if status.status is not None)
    counts["admin_open"] = len(chosen) - counts["admin"]
    counts["overridden"] = replaced
    counts["closings"] = len(kept)
    counts["opens"] = len(opens)
    return replace(
        merged,
        closings=tuple(closing for closing, _ in kept),
        opens=tuple(opens),
        provenance=tuple(line for _, line in kept),
        counts=dict(counts),
    )


def _admin_provenance(
    closing: Closing, status: AdminStatus, generated_at: datetime
) -> dict[str, JSONValue]:
    return provenance_line(
        {
            "nces_id": status.nces_id,
            "school": closing.school,
            "day": closing.day.isoformat(),
            "status": int(closing.status),
            "reason": None,
            "source_type": ADMIN_TYPE,
            "source_id": ADMIN_SOURCE,
            "row_key": status.key,
            "lo": None,
            "hi": _iso(status.set_at),
            "row_stamp": None,
            "f5_confidence": None,
            "f5_notes": [],
            "match_reason": ADMIN_TYPE,
            "match_level": status.level,
            "target_level": status.level,
            "match_confidence": 1.0,
            "derived_version": ADMIN_VERSION,
            "generated_at": _iso(generated_at),
            "present": True,
            "contributing": [[ADMIN_SOURCE, ADMIN_TYPE, status.key]],
            "announced_by": status.key,
            "sources": 1,
        }
    )

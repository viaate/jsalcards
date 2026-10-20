"""Publish and gate (spec 7.7): one pass's merged statuses become the live files, or nothing.

Each pass, :meth:`LivePublisher.publish` turns the merge's result into
``live/closings.json`` (stamped with the deployed directory's stamp,
:mod:`snowlight.live.edition`) and ``live/opens.json`` (the open statements kept
for the prediction model, owner decision Q8), and runs the publish gate (G12,
:func:`snowlight.live.guards.gate_refusals`):

* **a** the directory handshake passed;
* **b** at least 60% of the sources due read healthy, and at least half the
  previous pass's share;
* **c** ``generated_at`` is newer than the last file published, which is read back
  from the host before every upload and remembered after (spec S5), and is not
  ahead of the clock;
* **d** the file validates and round-trips through its schema, and is at most
  400 KB gzipped;
* **e** the spike hold: a rise of more than 2,000 lit school-days, with fewer than
  half of the newly lit schools under an alert, holds one pass and publishes on
  the next only if those rows are still there.

Only when every check passes are the files uploaded: when what they show changed,
or as a heartbeat on every pass that starts at least :data:`HEARTBEAT` less
:data:`PASS_SLACK` after the pass that last uploaded (measured on the passes' starts,
the 5-minute grid, so a pass whose reads end sooner than the last one's still
uploads). A refused pass
uploads nothing, so the file ages and the page says "Updated" after 20 minutes; two
refused passes in a row raise an alert (:attr:`PassReport.alert`). A refusal exits
3, a host or encoding error 1, a publish or a healthy hold 0 (:class:`Exit`).

When the directory handshake finds the deployed content changed under a stamp a
public file carries, every public file with that stamp is blanked at once
(:meth:`LivePublisher.blank`): an empty closings and opens file, every day timeline
the day index lists emptied, and an empty index, so nothing public indexes into the
old directory under a stamp that now names other content (a settled new deployment
that cannot be read blanks every public file, each under its own stamp). The pass is
refused and the alert raised.

**The hold** (``live/hold.json``, :class:`LiveHold`): ``snowlight live blank``
(:func:`emergency_blank`) sets it first, in a write of its own, in every prefix,
whatever ``LIVE_PUBLISH`` says, then blanks the files; ``snowlight live release``
(:func:`release`) clears it. Each hold is recorded once by a running publisher: the
statuses the change log shows go dark (``"by": "hold"``) when the hold began, or after
the last change logged when a publish raced it, and those school-days are redacted
(:attr:`Memory.redacted`). While it is set every pass is refused (``held``) and a file
that still shows statuses is blanked again. A hold file that does not read counts as
set. Every upload is guarded by the hold (:func:`~snowlight.live.publishers.guarded_write`:
on GitHub it is read in the commit the upload builds on) and the hold is read again
after it, so a pass that ran while ``live blank`` landed never leaves the map lit.
After the release, a redacted school-day lights only while a source still lists the
row that lights it (never by a row merge keeps through its day after it was taken
down), until its day is over; and the day timelines leave out every status the hold
darkened (:func:`~snowlight.live.history.timeline`).

Every publish also adds what it changed on the map to the private change log and
publishes the day timelines (:mod:`snowlight.live.history`): each day in progress
with a status, and each day over once as final under each directory stamp and
content (a day published under another is published again from the change log). The
index lists only days whose file carries the current stamp, and goes up with every
upload. A day the change log has no file for, whose public timeline carries the
current stamp and this directory's content (each day file records it), is first taken
into the log from that file (a successor that lost its state goes on with the day). The
files go up in this order: closings, opens, day timelines, index; a host that writes
them one by one and fails part way reports what it wrote, and the change log keeps what
the map showed.
The public files hold school indexes, days, codes and times only.

``LIVE_PUBLISH`` (:class:`Mode`): ``on`` writes under ``v1/``, ``shadow`` under
``v1-shadow/``, ``off`` runs the gate and writes nothing.

Logs carry counts, codes and source ids only (never a name or a status's words).
"""

import gzip
import hashlib
import json
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, ValidationError

from snowlight.live.edition import EditionVerdict
from snowlight.live.guards import GateInput, Refusal, SpikeState, gate_refusals, spike_hold
from snowlight.live.history import (
    BY,
    BY_HOLD,
    INDEX_DAYS,
    Change,
    ChangeLog,
    Event,
    Key,
    Shown,
    content_of,
    day_index,
    is_final,
    school_past,
    seed_changes,
    timeline,
)
from snowlight.live.merge import Merged, OpenSignal
from snowlight.live.publishers import (
    GuardRefusedError,
    Publisher,
    PublishError,
    WriteGuard,
    guarded_write,
)
from snowlight.live.resolve import LiveDirectory
from snowlight.output import JSONValue, dumps_json, write_bytes_atomic, write_json
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import (
    Closing,
    ClosingsFile,
    DayIndex,
    DayTimeline,
    OpensFile,
    local_days,
)

LOG: Final = logging.getLogger(__name__)
HEARTBEAT: Final = timedelta(minutes=5)
PASS_SLACK: Final = timedelta(seconds=60)
"""How much sooner than :data:`HEARTBEAT` a pass may start after the last uploading one
and still be the heartbeat (a pass starts a little after its grid mark)."""
CLOSINGS: Final = "live/closings.json"
OPENS: Final = "live/opens.json"
DAYS: Final = "live/days/index.json"
HOLD: Final = "live/hold.json"
PREFIXES: Final = ("v1", "v1-shadow")
REFUSALS_TO_ALERT: Final = 2
CLOCK_SLACK: Final = timedelta(seconds=60)
REDACTED: Final = "redacted"
"""Withheld: a status the hold darkened, lit again after the release only by rows that
are gone (kept through their day): nothing the source says now lights it."""


class Mode(StrEnum):
    """``LIVE_PUBLISH``: where the files go."""

    ON = "on"
    SHADOW = "shadow"
    OFF = "off"

    @property
    def prefix(self) -> str | None:
        return {Mode.ON: "v1", Mode.SHADOW: "v1-shadow", Mode.OFF: None}[self]


class Exit(IntEnum):
    """The ingest's exit codes (spec 7.7)."""

    OK = 0
    """Published, or held healthily (nothing changed, publishing off)."""
    ERROR = 1
    """A host or encoding error: nothing is known to be published."""
    REFUSED = 3
    """The gate refused: nothing was uploaded."""


def day_path(day: date) -> str:
    return f"live/days/{day.isoformat()}.json"


class LiveHold(BaseModel):
    """``live/hold.json``: whether ``snowlight live blank`` holds the map dark (the web never
    reads it; it holds a flag and times only)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: int
    held: bool
    at: datetime
    """When the hold was last set or cleared."""
    held_at: datetime | None
    """When the last hold began (kept when it is cleared, so a pass that never saw the hold
    still records the statuses going dark then)."""

    def to_json_bytes(self) -> bytes:
        def when(moment: datetime | None) -> str | None:
            return None if moment is None else moment.astimezone(UTC).isoformat()

        return dumps_json(
            {
                "schema_version": self.schema_version,
                "held": self.held,
                "at": when(self.at),
                "held_at": when(self.held_at),
            }
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "LiveHold":
        """Raises ``ValueError`` (or ``KeyError``/``TypeError``) on another shape."""
        value = json.loads(data)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("not a hold file")
        held, began = value["held"], value["held_at"]
        if not isinstance(held, bool):
            raise TypeError("held is true or false")
        return cls(
            schema_version=1,
            held=held,
            at=datetime.fromisoformat(str(value["at"])),
            held_at=None if began is None else datetime.fromisoformat(str(began)),
        )


def read_hold(host: Publisher, prefix: str, now: datetime) -> LiveHold | None:
    """The hold file under ``prefix`` (set or cleared), or ``None`` when there is none. One
    that does not read counts as set (at ``now``).

    Raises:
        PublishError: the host could not be read.
    """
    data = host.read(f"{prefix}/{HOLD}")
    if data is None:
        return None
    try:
        return LiveHold.from_bytes(data)
    except (KeyError, TypeError, ValueError):
        LOG.warning("%s/%s does not read: it counts as a hold", prefix, HOLD)
        moment = _whole(now)
        return LiveHold(schema_version=1, held=True, at=moment, held_at=moment)


def _read_closings(host: Publisher, prefix: str) -> ClosingsFile | None:
    data = host.read(f"{prefix}/{CLOSINGS}")
    if data is None:
        return None
    try:
        return ClosingsFile.from_json_bytes(data)
    except (ValidationError, ValueError):
        LOG.warning("%s/%s does not read; it is replaced", prefix, CLOSINGS)
        return None


def _listed_days(host: Publisher, prefix: str) -> set[date]:
    data = host.read(f"{prefix}/{DAYS}")
    if data is None:
        return set()
    try:
        return {entry.day for entry in DayIndex.from_json_bytes(data).days}
    except (ValidationError, ValueError):
        LOG.warning("%s/%s does not read; it is replaced", prefix, DAYS)
        return set()


def blank_files(
    stamp: DirectoryStamp, generated_at: datetime, days: Iterable[date]
) -> dict[str, bytes]:
    """A blank publish under ``stamp``: empty closings and opens, each of ``days`` as an empty
    timeline, and an empty day index (unprefixed paths, closings first)."""
    files = {
        CLOSINGS: ClosingsFile.encode(
            (), generated_at=generated_at, directory=stamp
        ).to_json_bytes(),
        OPENS: opens_file((), (), generated_at=generated_at, stamp=stamp).to_json_bytes(),
    }
    for day in sorted(days):
        files[day_path(day)] = DayTimeline.model_validate(
            {
                "schema_version": 1,
                "day": day,
                "generated_at": generated_at,
                "directory": stamp,
                "content_sha256": None,
                "final": is_final(day, generated_at),
                "gaps": (),
                "counts": (),
                "minutes": (),
                "statuses": (),
                "reasons": (),
                "shifts": (),
                "clocks": (),
            }
        ).to_json_bytes()
    files[DAYS] = day_index({}, generated_at).to_json_bytes()
    return files


def _blank_time(now: datetime, last: datetime | None) -> datetime:
    """A blank's ``generated_at``: now, or a second after the newest file when that is not
    older (an emergency is never refused for a clash within a second)."""
    moment = _whole(now)
    return moment if last is None or moment > last else last + timedelta(seconds=1)


def _ahead(generated_at: datetime, host: Publisher, now: datetime) -> bool:
    moment = getattr(host, "server_time", None)
    reference = moment if isinstance(moment, datetime) else now
    return generated_at > reference + CLOCK_SLACK


def emergency_blank(host: Publisher, now: datetime) -> "PassReport":
    """``snowlight live blank``: set the hold in every prefix (first, in a write of its own,
    so it stands whatever happens next), then blank every public closings file under its
    own stamp, with the day timelines its index lists emptied.

    It ignores ``LIVE_PUBLISH`` and touches no private state (a running ingest records
    the statuses going dark when it reads the hold, and blanks a file it finds lit while
    the hold is set). Exit 0 when every prefix is held and every file blanked; 3 when a
    blank would be stamped ahead of the host's clock (the hold is set, and the running
    ingest blanks that file once the clock allows); 1 on a host error.
    """
    stamped = _whole(now)
    holds = {
        f"{prefix}/{HOLD}": LiveHold(
            schema_version=1, held=True, at=stamped, held_at=stamped
        ).to_json_bytes()
        for prefix in PREFIXES
    }
    try:
        host.write(holds)
    except PublishError as error:
        LOG.error("hold: %s", error)
        return PassReport(Exit.ERROR, stamped, blank=True, note=f"hold: {error}")
    files: dict[str, bytes] = {}
    blanked: list[str] = []
    ahead: list[str] = []
    try:
        for prefix in PREFIXES:
            remote = _read_closings(host, prefix)
            if remote is None:
                continue
            generated_at = _blank_time(now, remote.generated_at)
            if _ahead(generated_at, host, now):
                LOG.warning("blank %s refused: it would be ahead of the host's clock", prefix)
                ahead.append(prefix)
                continue
            made = blank_files(remote.directory, generated_at, _listed_days(host, prefix))
            files.update({f"{prefix}/{path}": body for path, body in made.items()})
            blanked.append(prefix)
        if files:
            host.write(files)
    except PublishError as error:
        LOG.error("blank: %s", error)
        note = f"held in {len(PREFIXES)} prefixes; the blank failed: {error}"
        return PassReport(Exit.ERROR, stamped, uploaded=tuple(holds), blank=True, note=note)
    done = ", ".join(blanked) or "none (nothing published)"
    note = f"held in {len(PREFIXES)} prefixes; blanked {done}"
    uploaded = (*holds, *files)
    if ahead:
        note += f"; not blanked (ahead of the host's clock): {', '.join(ahead)}"
        return PassReport(
            Exit.REFUSED,
            stamped,
            uploaded=uploaded,
            refusals=(Refusal.CLOCK_AHEAD.value,),
            blank=True,
            note=note,
        )
    return PassReport(Exit.OK, stamped, uploaded=uploaded, blank=True, note=note)


def holds(data: bytes | None) -> bool:
    """Whether a hold file's bytes hold the map dark (one that does not read does)."""
    if data is None:
        return False
    try:
        return LiveHold.from_bytes(data).held
    except (KeyError, TypeError, ValueError):
        return True


def release(host: Publisher, now: datetime) -> "PassReport":
    """``snowlight live release``: clear the hold in every prefix (the next pass publishes)."""
    stamped = _whole(now)
    try:
        files = {}
        for prefix in PREFIXES:
            before = read_hold(host, prefix, now)
            files[f"{prefix}/{HOLD}"] = LiveHold(
                schema_version=1,
                held=False,
                at=stamped,
                held_at=None if before is None else before.held_at,
            ).to_json_bytes()
        host.write(files)
    except PublishError as error:
        LOG.error("release: %s", error)
        return PassReport(Exit.ERROR, stamped, note=f"release: {error}")
    return PassReport(Exit.OK, stamped, uploaded=tuple(files), note="hold cleared")


@dataclass(frozen=True, slots=True)
class DayRecord:
    """A day timeline published under one prefix: the stamp and content it indexes into, how
    many schools it holds, and whether it was the final one."""

    token: str
    schools: int
    final: bool


@dataclass(slots=True)
class Memory:
    """What the publisher keeps between passes (``publish.json`` in the private state)."""

    last_published: datetime | None = None
    last_stamp: DirectoryStamp | None = None
    last_content: str | None = None
    """The digest of the last upload's content, with its prefix."""
    last_upload: datetime | None = None
    last_upload_pass: datetime | None = None
    """When the pass that last uploaded started (the heartbeat is measured on it)."""
    previous_healthy_share: float | None = None
    spike: frozenset[tuple[int, str]] | None = None
    lit: frozenset[tuple[int, str]] = frozenset()
    refused_streak: int = 0
    days: dict[str, DayRecord] = field(default_factory=dict)
    """``<prefix>/<day>``: the day timeline last published there (so a final day is not
    published again, nor its change log read, while the stamp and content stay)."""
    hold_seen: datetime | None = None
    """The start of the last hold this process recorded (each hold is recorded once)."""
    redacted: frozenset[tuple[str, str]] = frozenset()
    """The school-days (NCES id, day) a hold darkened, until their day is over."""

    def to_json(self) -> dict[str, JSONValue]:
        def when(moment: datetime | None) -> str | None:
            return None if moment is None else moment.astimezone(UTC).isoformat()

        def pairs(rows: frozenset[tuple[int, str]]) -> list[JSONValue]:
            return [[school, day] for school, day in sorted(rows)]

        stamp = self.last_stamp
        return {
            "last_published": when(self.last_published),
            "last_stamp": None if stamp is None else stamp.to_json_value(),
            "last_content": self.last_content,
            "last_upload": when(self.last_upload),
            "last_upload_pass": when(self.last_upload_pass),
            "previous_healthy_share": self.previous_healthy_share,
            "spike": None if self.spike is None else pairs(self.spike),
            "lit": pairs(self.lit),
            "refused_streak": self.refused_streak,
            "days": {
                key: [record.token, record.schools, record.final]
                for key, record in sorted(self.days.items())
            },
            "hold_seen": when(self.hold_seen),
            "redacted": [[nces_id, day] for nces_id, day in sorted(self.redacted)],
        }

    @classmethod
    def load(cls, path: Path) -> "Memory":
        """The memory kept at ``path``; a fresh one when there is none.

        Raises:
            ValueError: the file is not a publisher's memory.
        """
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))

            def when(value: object) -> datetime | None:
                return None if value is None else datetime.fromisoformat(str(value))

            def pairs(value: object) -> frozenset[tuple[int, str]]:
                if not isinstance(value, list):
                    raise TypeError("rows are a list")
                return frozenset((int(school), str(day)) for school, day in value)

            stamp = data["last_stamp"]
            share = data["previous_healthy_share"]
            return cls(
                last_published=when(data["last_published"]),
                last_stamp=None
                if stamp is None
                else DirectoryStamp.from_json_bytes(json.dumps(stamp).encode()),
                last_content=data["last_content"],
                last_upload=when(data["last_upload"]),
                last_upload_pass=when(data.get("last_upload_pass")),
                previous_healthy_share=None if share is None else float(share),
                spike=None if data["spike"] is None else pairs(data["spike"]),
                lit=pairs(data["lit"]),
                refused_streak=int(data["refused_streak"]),
                days={
                    str(key): DayRecord(str(token), int(schools), final is True)
                    for key, (token, schools, final) in data.get("days", {}).items()
                },
                hold_seen=when(data.get("hold_seen")),
                redacted=frozenset(
                    (str(nces_id), str(day)) for nces_id, day in data.get("redacted", [])
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{path.name} is not the publisher's memory") from error

    def save(self, path: Path) -> None:
        write_json(path, self.to_json())

    def forget_days(self, prefix: str) -> None:
        """Every day file under ``prefix`` is to be published again (after a blank)."""
        self.days = {
            key: record for key, record in self.days.items() if not key.startswith(f"{prefix}/")
        }


@dataclass(frozen=True, slots=True)
class PassReport:
    """What one publish pass did (counts and codes only)."""

    exit: Exit
    generated_at: datetime
    uploaded: tuple[str, ...] = ()
    refusals: tuple[str, ...] = ()
    blank: bool = False
    alert: bool = False
    note: str = ""
    counts: Mapping[str, int] = field(default_factory=dict)
    edition: str = ""
    """The directory handshake's verdict this pass (set by the ingest)."""

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "exit": int(self.exit),
            "generated_at": self.generated_at.astimezone(UTC).isoformat(),
            "uploaded": list(self.uploaded),
            "refusals": list(self.refusals),
            "blank": self.blank,
            "alert": self.alert,
            "note": self.note,
            "counts": dict(self.counts),
            "edition": self.edition,
        }


def _never(_school: int) -> bool:
    return False


def _whole(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(microsecond=0)


def content_digest(
    stamp: DirectoryStamp, closings: Sequence[Closing], opens: Sequence[object]
) -> str:
    """What a publish shows, apart from its ``generated_at``: two passes with equal digests
    publish the same statuses."""
    rows = sorted(
        (
            closing.day.isoformat(),
            closing.school,
            int(closing.status),
            None if closing.reason is None else int(closing.reason),
            closing.shift_minutes,
            closing.clock_minute,
            None if closing.announced_at is None else closing.announced_at.isoformat(),
        )
        for closing in closings
    )
    body = json.dumps([stamp.to_json_value(), rows, [repr(item) for item in opens]], default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def opens_file(
    opens: Sequence[OpenSignal],
    closings: Sequence[Closing],
    *,
    generated_at: datetime,
    stamp: DirectoryStamp,
) -> OpensFile:
    """live/opens.json: the open statements in force, never on a school-day with a status.

    Raises:
        ValueError: a statement is dated after ``generated_at`` (a clock fault is refused,
            never hidden).
    """
    shown = {(closing.school, closing.day) for closing in closings}
    first, last = local_days(generated_at)
    rows = sorted(
        (signal for signal in opens if (signal.school, signal.day) not in shown),
        key=lambda signal: (signal.day, signal.school),
    )
    if any(_whole(signal.at) > generated_at for signal in rows):
        raise ValueError("an open statement is dated after the file")
    return OpensFile.model_validate(
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "directory": stamp,
            "opens": tuple(
                {
                    "school": signal.school,
                    "day": signal.day,
                    "kind": "open",
                    "at": _whole(signal.at),
                    "confidence": None
                    if signal.confidence is None
                    else round(min(max(signal.confidence, 0.0), 1.0), 2),
                }
                for signal in rows
                if first <= signal.day <= last
            ),
        }
    )


@dataclass(slots=True)
class LivePublisher:
    """Publishes one pass's statuses through the gate (see the module)."""

    host: Publisher
    directory: LiveDirectory
    state_dir: Path
    """The private state folder: ``publish.json`` and ``changes/``."""
    internal_dir: Path
    """The private output folder: ``provenance.jsonl`` (the last publish's)."""
    mode: Mode = Mode.SHADOW
    heartbeat: timedelta = HEARTBEAT
    memory: Memory = field(init=False)
    changes: ChangeLog = field(init=False)
    _days: dict[str, DayRecord] = field(init=False, default_factory=dict)
    _seeded: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.memory = Memory.load(self.memory_path)
        self.changes = ChangeLog(self.state_dir / "changes")

    @property
    def memory_path(self) -> Path:
        return self.state_dir / "publish.json"

    def key(self, path: str) -> str | None:
        prefix = self.mode.prefix
        return None if prefix is None else f"{prefix}/{path}"

    def read_back(self) -> ClosingsFile | None:
        """The closings file the host holds now under this mode's prefix, or ``None``.

        Raises:
            PublishError: the host could not be read.
        """
        prefix = self.mode.prefix
        return None if prefix is None else _read_closings(self.host, prefix)

    def public_stamps(self) -> tuple[tuple[DirectoryStamp, ...], bool]:
        """The stamps the public closings files carry (read back from the host under every
        prefix) and the one remembered, newest knowledge first, and whether every prefix
        was read back (a host that cannot be read leaves the remembered one)."""
        found: list[DirectoryStamp] = []
        complete = True
        for prefix in PREFIXES:
            try:
                remote = _read_closings(self.host, prefix)
            except PublishError as error:
                LOG.warning("read back %s: %s", prefix, error)
                complete = False
                continue
            if remote is not None and remote.directory not in found:
                found.append(remote.directory)
        last = self.memory.last_stamp
        if last is not None and last not in found:
            found.append(last)
        return tuple(found), complete

    def _reference(self, now: datetime) -> datetime:
        """The clock ``generated_at`` is checked against (G12c): the host's own, from the
        ``Date`` of its last answer, when it gave one; else the box's."""
        moment = getattr(self.host, "server_time", None)
        return moment if isinstance(moment, datetime) else now

    def _last_published(self) -> datetime | None:
        remote = self.read_back()
        known = [
            moment
            for moment in (
                self.memory.last_published,
                None if remote is None else remote.generated_at,
            )
            if moment is not None
        ]
        return max(known, default=None)

    def _token(self, stamp: DirectoryStamp) -> str:
        body = json.dumps([stamp.to_json_value(), self.directory.edition], default=str)
        return hashlib.sha256(body.encode()).hexdigest()[:32]

    def publish(  # noqa: PLR0911, PLR0913 - one pass: refusals, holds, skips and uploads
        self,
        merged: Merged,
        *,
        now: datetime,
        healthy_share: float,
        edition: EditionVerdict,
        alerted: Callable[[int], bool] = _never,
        started: datetime | None = None,
    ) -> PassReport:
        """Run the gate on one pass's merge and publish when it passes. ``started`` is when
        the pass began (before its reads; ``now`` when not given): the heartbeat is measured
        on it."""
        generated_at = _whole(now)
        if edition.wants_blank:
            return self.edition_blank(edition, now=now)
        try:
            held = self._hold(now)
            last = self._last_published()
            if edition.ok and edition.stamp is not None:
                self._seed(edition.stamp, now)
        except PublishError as error:
            LOG.error("read back: %s", error)
            return PassReport(Exit.ERROR, generated_at, note=f"read back: {error}")
        if held is not None:
            self._take_hold(held)
        if held is not None and held.held:
            return self._keep_held(now)
        merged, redacted = self._redact(merged, now)
        stamp = edition.stamp if edition.ok else None
        files: dict[str, bytes] = {}
        valid, gzip_bytes, digest = stamp is not None, 0, ""
        lit_now: frozenset[tuple[int, str]] = frozenset()
        if stamp is not None:
            try:
                closings = ClosingsFile.encode(
                    merged.closings, generated_at=generated_at, directory=stamp
                )
                opens = opens_file(
                    merged.opens, merged.closings, generated_at=generated_at, stamp=stamp
                )
                files = {CLOSINGS: closings.to_json_bytes(), OPENS: opens.to_json_bytes()}
            except (ValidationError, ValueError) as error:
                LOG.error("the closings file does not validate: %s", type(error).__name__)
                valid = False
            else:
                gzip_bytes = len(gzip.compress(files[CLOSINGS], mtime=0))
                digest = f"{self.mode.prefix}:{content_digest(stamp, merged.closings, opens.opens)}"
                lit_now = frozenset(
                    (closing.school, closing.day.isoformat()) for closing in merged.closings
                )
        memory = self.memory
        new_rows = lit_now - memory.lit
        alert_share = (
            sum(alerted(school) for school, _ in new_rows) / len(new_rows) if new_rows else 1.0
        )
        hold, pending = spike_hold(
            lit_before=len(memory.lit),
            lit_now=len(lit_now),
            new_rows=new_rows,
            alert_share=alert_share,
            pending=None if memory.spike is None else SpikeState(memory.spike),
        )
        refusals = gate_refusals(
            GateInput(
                edition_ok=edition.ok,
                healthy_share=healthy_share,
                previous_healthy_share=memory.previous_healthy_share,
                generated_at=generated_at,
                last_published=last,
                now=self._reference(now),
                gzip_bytes=gzip_bytes,
                spike=hold,
                valid=valid or not edition.ok,
            )
        )
        memory.previous_healthy_share = healthy_share
        memory.spike = None if pending is None else pending.rows
        counts = {
            "closings": len(merged.closings),
            "opens": len(merged.opens),
            "gzip": gzip_bytes,
            REDACTED: redacted,
        }
        if refusals or stamp is None:
            codes = tuple(refusal.value for refusal in refusals)
            return self._refuse(codes, generated_at, counts, alert=edition.alert)
        memory.refused_streak = 0
        if self.mode is Mode.OFF:
            memory.save(self.memory_path)
            return PassReport(Exit.OK, generated_at, note="publishing is off", counts=counts)
        began = now if started is None else started
        if (
            digest == memory.last_content
            and memory.last_upload_pass is not None
            and timedelta(0) <= began - memory.last_upload_pass < self.heartbeat - PASS_SLACK
        ):
            memory.save(self.memory_path)
            return PassReport(Exit.OK, generated_at, note="unchanged", counts=counts)
        shown = {
            (str(line["nces_id"]), closing.day): (Shown.of(closing), _change_fields(line))
            for closing, line in zip(merged.closings, merged.provenance, strict=True)
        }
        return self._upload(
            files,
            shown,
            began=began,
            generated_at=generated_at,
            stamp=stamp,
            digest=digest,
            lit=lit_now,
            provenance=merged.provenance,
            counts=counts,
        )

    def edition_blank(self, edition: EditionVerdict, *, now: datetime) -> PassReport:
        """The blank a handshake verdict names (:attr:`EditionVerdict.wants_blank`),
        published at once: refused (3) with the alert when it is done, an error (1) when the
        host failed; ``blank`` is true only when nothing public is lit under that stamp."""
        report = self.blank(now=now, stamp=None if edition.blank_every else edition.blank)
        done = report.exit is Exit.OK
        return PassReport(
            Exit.ERROR if report.exit is Exit.ERROR else Exit.REFUSED,
            _whole(now),
            uploaded=report.uploaded,
            refusals=(Refusal.EDITION.value, *report.refusals),
            blank=done,
            alert=True,
            note=(
                "a new deployment cannot be read: "
                if edition.blank_every
                else "the deployed directory changed under a public stamp: "
            )
            + (
                ("published blank" if report.uploaded else "the public files were blank")
                if done
                else f"the blank failed ({report.note or 'refused'})"
            ),
            edition=edition.state.value,
        )

    def _unknown_hold(self, now: datetime, counts: Mapping[str, int]) -> PassReport:
        """The hold could not be read after an upload: ``live blank`` may have landed
        during it, so this prefix's files are blanked again at once (a plain blank: the hold
        is recorded once it reads), with the alert, and the pass is an error."""
        mine = self.mode.prefix
        report = self.blank(now=now, stamp=None, prefixes=() if mine is None else (mine,))
        note = "the hold could not be read after the upload: " + (
            "published blank" if report.exit is Exit.OK else f"the blank failed ({report.note})"
        )
        return PassReport(
            Exit.ERROR,
            report.generated_at,
            uploaded=report.uploaded,
            refusals=report.refusals,
            blank=report.exit is Exit.OK,
            alert=True,
            note=note,
            counts=counts,
        )

    def _refuse(
        self,
        codes: tuple[str, ...],
        generated_at: datetime,
        counts: Mapping[str, int],
        *,
        alert: bool = False,
    ) -> PassReport:
        memory = self.memory
        memory.refused_streak += 1
        memory.save(self.memory_path)
        LOG.warning("gate refused: %s", ", ".join(codes))
        return PassReport(
            Exit.REFUSED,
            generated_at,
            refusals=codes,
            alert=alert or memory.refused_streak >= REFUSALS_TO_ALERT,
            counts=counts,
        )

    def _hold(self, now: datetime) -> LiveHold | None:
        prefix = self.mode.prefix
        return None if prefix is None else read_hold(self.host, prefix, now)

    def _keep_held(self, now: datetime) -> PassReport:
        """A pass under the hold (the statuses went dark in the change log at the hold's
        time): blank a file that still shows statuses, and refuse."""
        generated_at = _whole(now)
        note = "held by live blank"
        uploaded: tuple[str, ...] = ()
        try:
            remote = self.read_back()
        except PublishError as error:
            remote = None
            note += f"; read back: {error}"
        if remote is not None and remote.days:
            report = self.blank(now=now, stamp=None, by_hold=True)
            uploaded = report.uploaded
            note += (
                "; blanked again"
                if report.exit is Exit.OK
                else f"; the blank failed ({report.note or 'refused'})"
            )
        refused = self._refuse((Refusal.HELD.value,), generated_at, {})
        return replace(refused, uploaded=uploaded, note=note)

    def _take_hold(self, held: LiveHold) -> None:
        """Record a hold once: what the map showed goes dark, by the hold, when it began (or
        after the last change logged, when a publish raced it). A hold already over before
        this process last published or logged a change is not recorded (that process's
        successor, say, after its release)."""
        began, memory = held.held_at, self.memory
        if began is None or began == memory.hold_seen:
            return
        last = self.changes.last_at
        seen = max((m for m in (memory.last_published, last) if m is not None), default=None)
        if held.held or seen is None or began > seen:
            self._darken(began if last is None else max(began, last), by_hold=True)
        memory.hold_seen = began
        memory.save(self.memory_path)

    def _held_late(self, now: datetime, note: str) -> PassReport:
        """The hold was set while this pass ran: record it, blank what is lit, refuse."""
        try:
            held = self._hold(now)
        except PublishError as error:
            LOG.error("read hold: %s", error)
            held = None
        if held is None or not held.held:
            moment = _whole(now)
            held = LiveHold(schema_version=1, held=True, at=moment, held_at=moment)
        self._take_hold(held)
        report = self._keep_held(now)
        return replace(report, note=f"{note}; {report.note}")

    def _redact(self, merged: Merged, now: datetime) -> tuple[Merged, int]:
        """``merged`` without a school-day the hold darkened that only gone rows (kept
        through their day) light: the release brings back only what a source says now.
        Returns it and how many statuses went."""
        memory = self.memory
        kept = frozenset(
            key for key in memory.redacted if not is_final(date.fromisoformat(key[1]), now)
        )
        memory.redacted = kept
        if not kept:
            return merged, 0
        vanished = {(item.school, item.day) for item in merged.held_vanishes}
        pairs = [
            (closing, line)
            for closing, line in zip(merged.closings, merged.provenance, strict=True)
            if (str(line.get("nces_id")), closing.day.isoformat()) not in kept
            or (closing.school, closing.day) not in vanished
        ]
        gone = len(merged.closings) - len(pairs)
        if not gone:
            return merged, 0
        withheld = dict(merged.withheld)
        withheld[REDACTED] = withheld.get(REDACTED, 0) + gone
        found = replace(
            merged,
            closings=tuple(closing for closing, _ in pairs),
            provenance=tuple(line for _, line in pairs),
            withheld=withheld,
        )
        return found, gone

    def _seed(self, stamp: DirectoryStamp, now: datetime) -> None:
        """Once per process: a day the change log has no file for, whose public timeline
        carries ``stamp`` and was built from this directory's content, is taken into the log
        from that file (a successor that lost its state continues the day rather than
        starting it again at its own first publish). A file built from other content under
        the same stamp is skipped, with a logged reason: its indexes name other schools.

        Raises:
            PublishError: the host could not be read.
        """
        prefix = self.mode.prefix
        if self._seeded or prefix is None:
            return
        local = set(self.changes.days())
        own = content_of(self.directory)
        oldest = local_days(now)[0] - timedelta(days=INDEX_DAYS)
        seeded: list[Change] = []
        for day in sorted(_listed_days(self.host, prefix)):
            if day in local or day < oldest:
                continue
            data = self.host.read(f"{prefix}/{day_path(day)}")
            if data is None:
                continue
            try:
                made = DayTimeline.from_json_bytes(data)
            except (ValidationError, ValueError):
                LOG.warning("%s/%s does not read; it is not continued", prefix, day_path(day))
                continue
            if made.directory != stamp or made.day != day:
                continue
            if made.content_sha256 != own:
                if made.gaps:
                    LOG.warning(
                        "%s/%s was built from other directory content under this stamp; "
                        "it is not continued",
                        prefix,
                        day_path(day),
                    )
                continue
            seeded.extend(seed_changes(made, self.directory))
        if seeded:
            self.changes.commit(seeded)
            LOG.info("change log: %d changes taken from the public day files", len(seeded))
        self._seeded = True

    def _darken(self, at: datetime, *, by_hold: bool = False) -> int:
        """Log every status the change log shows as going dark at ``at`` (``by_hold``: the
        lines say so, and the school-days are redacted); forget what was lit and which day
        files are published (they are published again on release)."""
        changes = self.changes.diff(at, {}, past=school_past(self.directory, at))
        memory = self.memory
        if by_hold:
            changes = [
                replace(change, fields={BY: BY_HOLD}) if change.event is Event.DARK else change
                for change in changes
            ]
            memory.redacted = memory.redacted | {
                (change.nces_id, change.day.isoformat())
                for change in changes
                if change.event is Event.DARK
            }
        self.changes.commit(changes)
        memory.lit = frozenset()
        memory.spike = None
        memory.last_content = None
        prefix = self.mode.prefix
        if prefix is not None:
            memory.forget_days(prefix)
        memory.save(self.memory_path)
        return len(changes)

    def blank(
        self,
        *,
        now: datetime,
        stamp: DirectoryStamp | None,
        by_hold: bool = False,
        prefixes: Sequence[str] = PREFIXES,
    ) -> PassReport:
        """Blank every public closings file that carries ``stamp`` (``None``: every one, under
        its own stamp), in every prefix (or only ``prefixes``): empty closings and opens, the
        day timelines its index lists or this process published emptied, and an empty index.

        It skips the health check and the spike hold; its ``generated_at`` is newer than the
        file it replaces (a second after it when the clock gives no newer one), and never
        ahead of the host's clock. What this process showed goes dark in the change log.
        """
        generated_at = _whole(now)
        files: dict[str, bytes] = {}
        mine = self.mode.prefix
        try:
            for prefix in prefixes:
                remote = _read_closings(self.host, prefix)
                if remote is None or (stamp is not None and remote.directory != stamp):
                    continue
                days = _listed_days(self.host, prefix) | {
                    date.fromisoformat(key.split("/", 1)[1])
                    for key in self.memory.days
                    if key.startswith(f"{prefix}/")
                }
                if not remote.days and not days:
                    continue  # already blank: nothing public names a school
                last = remote.generated_at
                if prefix == mine and self.memory.last_published is not None:
                    last = max(last, self.memory.last_published)
                when = _blank_time(now, last)
                if _ahead(when, self.host, now):
                    LOG.warning("blank refused: it would be ahead of the host's clock")
                    return PassReport(
                        Exit.REFUSED,
                        generated_at,
                        refusals=(Refusal.CLOCK_AHEAD.value,),
                        blank=True,
                    )
                made = blank_files(remote.directory, when, days)
                files.update({f"{prefix}/{path}": body for path, body in made.items()})
                generated_at = max(generated_at, when)
            if not files:
                return PassReport(
                    Exit.OK, generated_at, blank=True, note="nothing to blank (already blank)"
                )
            self.host.write(files)
        except PublishError as error:
            LOG.error("blank: %s", error)
            return PassReport(Exit.ERROR, generated_at, blank=True, note=f"blank: {error}")
        if mine is not None and f"{mine}/{CLOSINGS}" in files:
            self._darken(generated_at, by_hold=by_hold)
            self.memory.last_published = generated_at
            self.memory.last_upload = generated_at
            self.memory.last_stamp = ClosingsFile.from_json_bytes(
                files[f"{mine}/{CLOSINGS}"]
            ).directory
            self.memory.save(self.memory_path)
        LOG.info("published blank: %d files", len(files))
        return PassReport(Exit.OK, generated_at, uploaded=tuple(files), blank=True)

    def _upload(  # noqa: PLR0913 - one publish's files and what they show
        self,
        files: dict[str, bytes],
        shown: Mapping[Key, tuple[Shown, Mapping[str, JSONValue]]],
        *,
        began: datetime,
        generated_at: datetime,
        stamp: DirectoryStamp,
        digest: str,
        lit: frozenset[tuple[int, str]],
        provenance: Sequence[Mapping[str, JSONValue]],
        counts: Mapping[str, int],
    ) -> PassReport:
        changes = self.changes.diff(
            generated_at, shown, past=school_past(self.directory, generated_at)
        )
        days = self._timelines(changes, generated_at=generated_at, stamp=stamp)
        ordered = {**files, **{path: days[path] for path in sorted(days) if path != DAYS}}
        if DAYS in days:
            ordered[DAYS] = days[DAYS]
        keyed: dict[str, bytes] = {}
        for path, body in ordered.items():
            key = self.key(path)
            if key is not None:
                keyed[key] = body
        memory = self.memory
        prefix = self.mode.prefix or PREFIXES[0]
        try:
            guarded_write(self.host, keyed, WriteGuard(f"{prefix}/{HOLD}", holds))
        except GuardRefusedError:
            LOG.warning("upload refused: the hold was set while the pass ran")
            return self._held_late(generated_at, "the hold was set while the pass ran")
        except PublishError as error:
            LOG.error("upload: %s", error)
            if self.key(CLOSINGS) in error.written:
                # The map changed: the change log and the memory keep what it shows. The
                # content is not remembered, so the next pass uploads every file again.
                self.changes.commit(changes)
                memory.last_published = memory.last_upload = generated_at
                memory.last_stamp, memory.lit, memory.spike = stamp, lit, None
                memory.last_content = None
                memory.save(self.memory_path)
            return PassReport(Exit.ERROR, generated_at, note=f"upload: {error}", counts=counts)
        self.changes.commit(changes)
        memory.last_published = generated_at
        memory.last_stamp = stamp
        memory.last_content = digest
        memory.last_upload = generated_at
        memory.last_upload_pass = began
        memory.lit = lit
        memory.spike = None
        memory.days = {**memory.days, **self._days}
        memory.save(self.memory_path)
        self.changes.prune(local_days(generated_at)[0])
        write_bytes_atomic(
            self.internal_dir / "provenance.jsonl",
            b"".join(dumps_json(dict(line)) + b"\n" for line in provenance),
        )
        try:
            after = self._hold(generated_at)
        except PublishError as error:
            LOG.error("read hold after the upload: %s; blanking", error)
            return self._unknown_hold(generated_at, counts)
        if after is not None and after.held:
            LOG.warning("the hold was set during the upload: blanking")
            return self._held_late(generated_at, "the hold was set during the upload")
        LOG.info(
            "published %d statuses, %d changes, %d files",
            counts.get("closings", 0),
            len(changes),
            len(keyed),
        )
        return PassReport(
            Exit.OK,
            generated_at,
            uploaded=tuple(keyed),
            counts={**counts, "changes": len(changes)},
        )

    def _timelines(
        self, changes: Sequence[Change], *, generated_at: datetime, stamp: DirectoryStamp
    ) -> dict[str, bytes]:
        """The day files to publish with this pass, plus the index: each day in progress
        with a status, and each day over whose final timeline is not yet published under
        this prefix, stamp and content (from the change log, which is keyed by NCES id).
        The index lists only days whose file carries this stamp."""
        prefix = self.mode.prefix or ""
        token = self._token(stamp)
        pending: dict[date, list[Change]] = {}
        for change in changes:
            pending.setdefault(change.day, []).append(change)
        files: dict[str, bytes] = {}
        entries: dict[date, tuple[int, bool]] = {}
        self._days = {}
        candidates = sorted({*self.changes.days(), *pending}, reverse=True)[:INDEX_DAYS]
        for day in sorted(candidates):
            final = is_final(day, generated_at)
            key = f"{prefix}/{day.isoformat()}"
            done = self.memory.days.get(key)
            if (
                final
                and done is not None
                and done.final
                and done.token == token
                and day not in pending
            ):
                entries[day] = (done.schools, True)  # its log is not read again
                continue
            made = timeline(
                day,
                [*self.changes.changes(day), *pending.get(day, [])],
                directory=self.directory,
                stamp=stamp,
                generated_at=generated_at,
                final=final,
            )
            if made is None:
                continue
            entries[day] = (len(made.gaps), final)
            files[day_path(day)] = made.to_json_bytes()
            self._days[key] = DayRecord(token, len(made.gaps), final)
        files[DAYS] = day_index(entries, generated_at).to_json_bytes()
        return files


def _change_fields(line: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """The provenance a change line keeps: codes, ids and times (never raw text)."""
    return {
        name: line.get(name)
        for name in ("school", "source_id", "source_type", "row_key", "hi", "derived_version")
    }

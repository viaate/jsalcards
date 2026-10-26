"""The outlook's private record (S7-F, spec-f s. 5 and 10; piece F3): what S7-L learns the
night-before outlook from and scores it on.

Per school day ``D`` and deployed district (positions in the directory, ``content`` naming it):

* **samples**: at each sample hour (08:00 D-1 to 04:00 D local, 21 of them), the class issued,
  the heads-up and the forecast bucket as they stood at that hour exactly, packed as ``c0 * 84
  + heads-up * 14 + bucket``; taken by the first pass within 15 minutes after the hour, as of
  the hour (the product log replays the alerts, the forecast is the newest run that counted
  then). A sample no pass took in time is not taken (never imputed); a zone whose forecast did
  not read is not taken either (a run that was stale reads as bucket 13, as in the history).
* **chance**: the published chance of no school (v2, the file the site shows) and the
  outlook's (S7-F, as ``PREDICT_OUTLOOK`` on would show it), in whole percent, from the first
  pass in the 15 minutes after 20:00 D-1.
* **record**: the class at 05:00 D exactly (rule D3, the label class and ``T``'s target), from
  the first pass between 05:00 and 09:00 D, with the product log rebuilt as of 05:00 (later
  withdrawals not applied). No pass then: the day's record is unknown.

Each part keeps, per zone, when it was taken (and the forecast run read). The serving pass
keeps the newest days in its private state (the Actions cache); ``predict learn`` merges them
into ``predictions/outlook/record.json`` beside ``learn.json`` on the live host and keeps
:data:`HOST_DAYS` school days there. Chances and NOAA states only: never a list's text.
"""

import base64
import zlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt

from snowlight.predict.outlook import BUCKETS
from snowlight.predict.outlook_states import SAMPLES
from snowlight.predict.situations import HeadsUp, morning_record

VERSION: Final = 1
NOT_TAKEN16: Final = 0xFFFF
NOT_TAKEN8: Final = 0xFF
GRACE: Final = timedelta(minutes=15)
"""A sample (or the 20:00 chance) is taken by a pass within this long after its hour."""
MORNING_UNTIL: Final = time(9)
"""The 05:00 record is taken by the first pass from 05:00 until this hour on the day."""
CHANCE_AT: Final = time(20)
"""The chance recorded: the evening before, at this hour (the first pass after it)."""
STATE_DAYS: Final = 3
"""Days the serving pass keeps in its state (``predict learn`` moves them to the host)."""
HOST_DAYS: Final = 10
"""School days the host's record keeps."""
HEADS: Final = len(HeadsUp)
STATE_CODE: Final = HEADS * BUCKETS
"""``c0 * STATE_CODE + heads-up * BUCKETS + bucket``."""
RECORD_PATH: Final = "predictions/outlook/record.json"


def pack(c0: int, heads: int, bucket: int) -> int:
    """A sample's state as one number."""
    return c0 * STATE_CODE + heads * BUCKETS + bucket


def unpack(code: npt.NDArray[np.integer]) -> tuple[npt.NDArray[np.int64], ...]:
    """(c0, heads-up, bucket) of packed states."""
    value = np.asarray(code, dtype=np.int64)
    return value // STATE_CODE, (value // BUCKETS) % HEADS, value % BUCKETS


def encode(values: npt.NDArray[np.integer], dtype: type[np.unsignedinteger]) -> str:
    """An array as compressed base64 text (little-endian)."""
    raw = np.asarray(values, dtype=np.dtype(dtype).newbyteorder("<")).tobytes()
    return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def decode(text: str, dtype: type[np.unsignedinteger], size: int) -> npt.NDArray[np.int64]:
    """The array :func:`encode` wrote.

    Raises:
        ValueError: the text is not one of ``size`` values.
    """
    try:
        raw = zlib.decompress(base64.b64decode(text.encode("ascii"), validate=True))
    except (zlib.error, ValueError, UnicodeEncodeError) as error:
        raise ValueError("a record part does not decode") from error
    found = np.frombuffer(raw, dtype=np.dtype(dtype).newbyteorder("<")).astype(np.int64)
    if found.size != size:
        raise ValueError(f"a record part holds {found.size} values, not {size}")
    return found


# --- when a pass takes each part -----------------------------------------------------------------


def due_samples(day: date, zone: str, now: datetime) -> int | None:
    """The sample of night ``day`` a pass at ``now`` takes in ``zone``: the one whose hour was
    at most 15 minutes ago, or ``None``."""
    local = now.astimezone(ZoneInfo(zone))
    for k, moment in enumerate(SAMPLES):
        at = moment.at(day, zone)
        if at <= local < at + GRACE:
            return k
    return None


def sample_moment(day: date, zone: str, k: int) -> datetime:
    """Sample ``k`` of night ``day`` in ``zone``, in UTC."""
    return SAMPLES[k].at(day, zone).astimezone(UTC)


def due_chance(day: date, zone: str, now: datetime) -> bool:
    """Whether a pass at ``now`` takes the 20:00 chance of ``day`` in ``zone``."""
    at = datetime.combine(day - timedelta(days=1), CHANCE_AT, tzinfo=ZoneInfo(zone))
    return at <= now < at + GRACE


def due_morning(day: date, zone: str, now: datetime) -> bool:
    """Whether a pass at ``now`` takes the 05:00 record of ``day`` in ``zone``."""
    start = morning_record(day, zone)
    return start <= now < datetime.combine(day, MORNING_UNTIL, tzinfo=ZoneInfo(zone))


# --- the record ----------------------------------------------------------------------------------


@dataclass(slots=True)
class Part:
    """One part of one day: a value per district and, per zone, when it was taken (and the
    forecast run it read, for samples)."""

    values: npt.NDArray[np.int64]
    taken: dict[str, str] = field(default_factory=dict)
    runs: dict[str, str | None] = field(default_factory=dict)

    def put(self, zone: str, members: Sequence[int], values: npt.NDArray[np.integer],
            at: datetime, run: datetime | None = None) -> None:  # fmt: skip
        """Take ``zone``'s districts (``members``, positions) at ``at``."""
        if len(members):
            self.values[np.asarray(members, dtype=np.int64)] = np.asarray(values, dtype=np.int64)
        self.taken[zone] = at.astimezone(UTC).isoformat()
        self.runs[zone] = None if run is None else run.astimezone(UTC).isoformat()


@dataclass(slots=True)
class Day:
    """One school day's record."""

    samples: dict[int, Part] = field(default_factory=dict)
    chance_v2: Part | None = None
    chance_f: Part | None = None
    morning: Part | None = None


@dataclass(slots=True)
class Record:
    """The record of one directory content (see the module docstring)."""

    content: str
    districts: int
    days: dict[date, Day] = field(default_factory=dict)
    leaids: tuple[str, ...] | None = None
    """The districts' LEAIDs by position (the host's record keeps them, so a new directory
    content carries its days over by LEAID: :func:`carried`)."""

    def day(self, day: date) -> Day:
        """The day's record (made empty when there is none)."""
        return self.days.setdefault(day, Day())

    def sample(self, day: date, k: int) -> Part:
        """Sample ``k`` of ``day`` (made empty when there is none)."""
        found = self.day(day).samples.get(k)
        if found is None:
            found = Part(np.full(self.districts, NOT_TAKEN16, dtype=np.int64))
            self.day(day).samples[k] = found
        return found

    def chance(self, day: date) -> tuple[Part, Part]:
        """The 20:00 chances of ``day`` (v2 and S7-F)."""
        entry = self.day(day)
        if entry.chance_v2 is None or entry.chance_f is None:
            entry.chance_v2 = Part(np.full(self.districts, NOT_TAKEN8, dtype=np.int64))
            entry.chance_f = Part(np.full(self.districts, NOT_TAKEN8, dtype=np.int64))
        return entry.chance_v2, entry.chance_f

    def morning(self, day: date) -> Part:
        """The 05:00 record of ``day``."""
        entry = self.day(day)
        if entry.morning is None:
            entry.morning = Part(np.full(self.districts, NOT_TAKEN8, dtype=np.int64))
        return entry.morning

    def kept(self, oldest: date) -> "Record":
        """The record without days before ``oldest``."""
        return Record(
            self.content,
            self.districts,
            {d: v for d, v in self.days.items() if d >= oldest},
            self.leaids,
        )

    def as_json(self) -> dict[str, object]:
        """The record as JSON values."""

        def part(found: Part, dtype: type[np.unsignedinteger]) -> dict[str, object]:
            out: dict[str, object] = {
                "values": encode(found.values, dtype),
                "taken": dict(sorted(found.taken.items())),
            }
            if any(run is not None for run in found.runs.values()):
                out["runs"] = dict(sorted(found.runs.items()))
            return out

        days: dict[str, object] = {}
        for day, entry in sorted(self.days.items()):
            value: dict[str, object] = {}
            if entry.samples:
                value["samples"] = {
                    str(k): part(found, np.uint16) for k, found in sorted(entry.samples.items())
                }
            if entry.chance_v2 is not None and entry.chance_f is not None:
                value["chance_v2"] = part(entry.chance_v2, np.uint8)
                value["chance_f"] = part(entry.chance_f, np.uint8)
            if entry.morning is not None:
                value["morning"] = part(entry.morning, np.uint8)
            days[day.isoformat()] = value
        found: dict[str, object] = {
            "version": VERSION,
            "content": self.content,
            "districts": self.districts,
            "days": days,
        }
        if self.leaids is not None:
            text = "\n".join(self.leaids).encode()
            found["leaids"] = base64.b64encode(zlib.compress(text, 9)).decode("ascii")
        return found

    @classmethod
    def from_json(cls, value: object, content: str, districts: int) -> "Record":
        """The record kept for ``content`` with ``districts`` districts; an empty one when the
        kept record is of another directory content or does not read (a part that does not
        read is left out: its zones read as not taken)."""
        found = cls.read_any(value)
        if found is None or found.content != content or found.districts != districts:
            return cls(content, districts)
        return found

    @classmethod
    def read_any(cls, value: object) -> "Record | None":
        """The record as kept, of whatever directory content it names; ``None`` when it does
        not read."""
        if not isinstance(value, Mapping) or value.get("version") != VERSION:
            return None
        content, districts = value.get("content"), value.get("districts")
        if not isinstance(content, str) or not isinstance(districts, int) or districts < 0:
            return None
        days = value.get("days")
        if not isinstance(days, Mapping):
            return None
        empty = cls(content, districts, leaids=_leaids(value.get("leaids"), districts))

        def part(item: object, dtype: type[np.unsignedinteger]) -> Part | None:
            if not isinstance(item, Mapping):
                return None
            taken, runs = item.get("taken"), item.get("runs", {})
            if not isinstance(taken, Mapping) or not isinstance(runs, Mapping):
                return None
            try:
                values = decode(str(item.get("values", "")), dtype, districts)
            except ValueError:
                return None
            return Part(
                values,
                {str(k): str(v) for k, v in taken.items()},
                {str(k): None if v is None else str(v) for k, v in runs.items()},
            )

        for key, entry in days.items():
            try:
                day = date.fromisoformat(str(key))
            except ValueError:
                continue
            if not isinstance(entry, Mapping):
                continue
            found = Day()
            samples = entry.get("samples", {})
            if isinstance(samples, Mapping):
                for k, item in samples.items():
                    read = part(item, np.uint16)
                    if read is not None and str(k).isdigit() and int(k) < len(SAMPLES):
                        found.samples[int(k)] = read
            v2, f = part(entry.get("chance_v2"), np.uint8), part(entry.get("chance_f"), np.uint8)
            if v2 is not None and f is not None:
                found.chance_v2, found.chance_f = v2, f
            found.morning = part(entry.get("morning"), np.uint8)
            empty.days[day] = found
        return empty


def _leaids(value: object, districts: int) -> tuple[str, ...] | None:
    """The LEAIDs a record keeps, or ``None`` when it keeps none (or they do not read)."""
    if not isinstance(value, str):
        return None
    try:
        text = zlib.decompress(base64.b64decode(value.encode("ascii"), validate=True)).decode()
    except (zlib.error, ValueError, UnicodeError):
        return None
    found = tuple(text.split("\n")) if text else ()
    return found if len(found) == districts else None


def remapped(record: Record, names: Sequence[str], content: str, leaids: Sequence[str]) -> Record:
    """``record`` (its districts named ``names``, by position) on another directory content
    whose districts are ``leaids``: each district's values follow its LEAID; a district the
    record did not hold reads as not taken, and one the new content does not hold is left
    out. Each zone's taken time is kept (a district that moved zones keeps the values it was
    taken with)."""
    index = {leaid: i for i, leaid in enumerate(names)}
    take = np.array([index.get(leaid, -1) for leaid in leaids], dtype=np.int64)
    has = take >= 0

    def part(found: Part | None, fill: int) -> Part | None:
        if found is None:
            return None
        values = np.full(len(leaids), fill, dtype=np.int64)
        values[has] = found.values[take[has]]
        return Part(values, dict(found.taken), dict(found.runs))

    days: dict[date, Day] = {}
    for day, entry in record.days.items():
        samples = {k: p for k, item in entry.samples.items() if (p := part(item, NOT_TAKEN16))}
        days[day] = Day(
            samples=samples,
            chance_v2=part(entry.chance_v2, NOT_TAKEN8),
            chance_f=part(entry.chance_f, NOT_TAKEN8),
            morning=part(entry.morning, NOT_TAKEN8),
        )
    return Record(content, len(leaids), days, tuple(leaids))


def carried(
    value: object, content: str, leaids: Sequence[str], via: Record | None = None
) -> tuple[Record, str | None]:
    """The kept record ``value`` on directory ``content`` (districts ``leaids``): as kept when
    it is of that content; of another content, remapped by LEAID (:func:`remapped`) with the
    LEAIDs it keeps, or else ``via``'s when ``via`` is of its content; else empty. A line says
    when its days were carried over or lost."""
    found = Record.read_any(value)
    empty = Record(content, len(leaids), leaids=tuple(leaids))
    if found is None:
        return empty, None
    if found.content == content and found.districts == len(leaids):
        found.leaids = tuple(leaids)
        return found, None
    names = found.leaids
    if names is None and via is not None and via.content == found.content:
        names = via.leaids if via.districts == found.districts else None
    if names is None:
        return empty, (
            f"outlook: a record of another directory ({len(found.days)} days) names no "
            "districts: it starts again"
        )
    moved = remapped(found, names, content, leaids)
    return moved, f"outlook: carried {len(found.days)} days of the record to the new directory"


def _merge_part(mine: Part | None, theirs: Part | None, zones: Sequence[str]) -> Part | None:
    """``theirs`` taken into ``mine`` zone by zone (a zone ``theirs`` took replaces mine)."""
    if theirs is None:
        return mine
    if mine is None:
        return Part(theirs.values.copy(), dict(theirs.taken), dict(theirs.runs))
    found = Part(mine.values.copy(), dict(mine.taken), dict(mine.runs))
    members: dict[str, list[int]] = {}
    for index, zone in enumerate(zones):
        members.setdefault(zone, []).append(index)
    for zone, at in theirs.taken.items():
        rows = members.get(zone, [])
        if rows:
            found.values[rows] = theirs.values[rows]
        found.taken[zone] = at
        found.runs[zone] = theirs.runs.get(zone)
    return found


def merged(host: Record, state: Record, zones: Sequence[str], keep: int = HOST_DAYS) -> Record:
    """The host's record with the state's days taken in, zone by zone (``zones``: each
    district's zone), keeping the newest ``keep`` days. A state of another directory content
    restarts the record."""
    if host.content != state.content or host.districts != state.districts:
        base = Record(state.content, state.districts, leaids=state.leaids)
    else:
        base = Record(host.content, host.districts, dict(host.days), host.leaids)
    for day, entry in state.days.items():
        mine = base.days.get(day, Day())
        samples = dict(mine.samples)
        for k, part in entry.samples.items():
            joined = _merge_part(samples.get(k), part, zones)
            if joined is not None:
                samples[k] = joined
        base.days[day] = Day(
            samples=samples,
            chance_v2=_merge_part(mine.chance_v2, entry.chance_v2, zones),
            chance_f=_merge_part(mine.chance_f, entry.chance_f, zones),
            morning=_merge_part(mine.morning, entry.morning, zones),
        )
    newest = sorted(base.days)[-keep:]
    return Record(
        base.content, base.districts, {day: base.days[day] for day in newest}, base.leaids
    )


def zone_members(zones: Iterable[str]) -> dict[str, list[int]]:
    """Each zone's districts (positions)."""
    found: dict[str, list[int]] = {}
    for index, zone in enumerate(zones):
        found.setdefault(zone, []).append(index)
    return found

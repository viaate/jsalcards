"""The frozen record (predict-next P1): every chance served, with its inputs, frozen four times a
night and kept for good. Nothing served reads it.

**When.** For each school day D, each time zone the deployed districts are in, at four times on
that zone's clock: 20:07 the evening before (``d1_2007``, horizon 1), 21:30 the evening before
(``d1_2130``, when families look), 05:07 on the day (``d0_0507``, horizon 0) and 06:30 on the
day (``d0_0630``). A freeze is taken by the first pass that publishes (or finds its file
unchanged) at or after its time, once per (D, zone, freeze); no later pass rewrites it. It says
how late it was taken (``late_by_s``). A freeze more than :data:`LATE_MAX` late is written
``missed``, counts only, never filled from a later chance.

**What.** Codes and numbers only: LEAIDs, days, times, codes and chances; no names, no list
text, no URLs. A day is one file, ``<D>.jsonl``: each freeze of a zone is a header line
(``"k": "freeze"``: the freeze, zone, its time, when it was taken, how late, the pass's file
time, run id, code sha and the ``live_score`` sha256) followed by one line per district of the
zone (:data:`ROW_KEYS`), or one ``"k": "missed"`` line. A district with no chance in the file
still has a line (``"s": 0`` and why), so coverage is measurable.

**Where.** The pass state's folder (:data:`FOLDER`, its own Actions cache key) keeps each day
until both evidence databases hold the finished day byte for byte (kind ``frozen``, key D,
:mod:`snowlight.live.evidence`); a day is finished, and offered, once the last zone's (Hawaii's)
06:30 freeze has passed plus :data:`SETTLE`. Its ``index.json`` keeps which freezes each day
took or missed, the bytes written, and which databases hold each finished day.

The pass calls :func:`record` after it publishes; any error there is the caller's to log once
(the pass publishes as before). :func:`rows` reads days back from the folder and the store, every
copy merged (:func:`merge`).
"""

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Final, Protocol
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt

from snowlight.output import write_bytes_atomic
from snowlight.predict.alerts_live import LiveEvent
from snowlight.predict.calendar import is_school_day
from snowlight.predict.config import PIPELINE_ROOT
from snowlight.predict.exposure import CLASS_OF_WEATHER, CLASSES
from snowlight.predict.forecast_values import Forecasts
from snowlight.predict.serve import (
    ADJUST_KINDS,
    SITUATION_POSITION,
    AdjustDetail,
    Noted,
    ServeModel,
    adjust_detail,
    exposure_offsets,
)
from snowlight.predict.situations import Situation, WeatherClass, Window, counts
from snowlight.predict.why import ALERT_KIND
from snowlight.schemas.predictions import ClassBase, Forecast, PredictionsFile

FOLDER: Final = PIPELINE_ROOT / "out" / "internal" / "predict" / "frozen"
INDEX: Final = "index.json"
SCHEMA: Final = 1
FREEZES: Final = (
    ("d1_2007", -1, time(20, 7)),
    ("d1_2130", -1, time(21, 30)),
    ("d0_0507", 0, time(5, 7)),
    ("d0_0630", 0, time(6, 30)),
)
"""Each freeze: its name, its day against the school day, and its time on the zone's clock."""
NAMES: Final = tuple(name for name, _, _ in FREEZES)
LATE_MAX: Final = timedelta(minutes=90)
"""A freeze later than this is written missed, never taken from a later pass's chance."""
LATE_NEVER: Final = 1 << 62
"""How late a missed freeze counts as taken when versions of a day are merged (never)."""
SETTLE: Final = timedelta(hours=1)
LAST_ZONE: Final = "Pacific/Honolulu"
WAIT: Final = timedelta(days=2)
"""A finished day not in both databases this long after it finished fails the check."""
DONE_DAYS: Final = 14
"""Days a day released from the folder is remembered (so no pass takes it up again)."""
RESTORE_DAYS: Final = 7
"""Days back a restore asks the store for, after the folder was lost."""
ROUND: Final = 6
"""Decimals of the unrounded chances and the class level (a millionth)."""
TERM_ROUND: Final = 4
"""Decimals of the terms, their bounds and the exposure offset (log odds)."""
SNOW_ROUND: Final = 2
"""Decimals of the forecast snow read (hundredths of an inch: finer than the forecast's own
tenths)."""
ICE_ROUND: Final = 3
"""Decimals of the forecast ice read (thousandths of an inch: finer than its hundredths)."""
CLAMPED: Final = 1e-12
"""A term the bounds moved by more than this was clamped."""
ROW_KEYS: Final[Mapping[str, str]] = {
    "l": "LEAID",
    "s": "1 when the chance was served in the public file, else 0",
    "why": "with s 0: no_chance (none in the file for the day), not_public (no public file), "
    "not_shown (the public file was not this pass's: held dark, or not yet uploaded) or "
    "unconfirmed (the public file did not read back)",
    "p": "the chance of no school as published (hundredths)",
    "q": "the chance of a delay as published (hundredths)",
    "pr": "the chance of no school before publishing rounds it, where known",
    "qr": "the chance of a delay before publishing rounds it, where known",
    "sit": "the situation (weather class, _after for the day after a closing)",
    "c": "the serving class: none, advisory, warning or cold",
    "ak": "the alert kind of a one-code class",
    "b": "the base's kind",
    "lv": "the district's class level before rounding (a class day)",
    "pts": "the class level as published, in points (a class day)",
    "o": "the exposure offset of the district in its class (log odds)",
    "rs": "the reasons shown: [kind, points] each",
    "sa": "1 when the district said school is on",
    "fr": "the forecast adjustment's read: before (the class snapshot), none, read or kept; "
    "absent where the file did not apply the adjustment",
    "f": "the forecast read: sn window snow, cm commute snow, bb snow before the bus hour "
    "(07:00 local; inches, hundredths), pp periods "
    "[start, end, snow] (minutes from the day's 00:00 UTC), ice (inches, thousandths), fl 7 AM "
    "feel, code, rt run time",
    "t": "the adjustment's terms (snow, timing, ice, cold; log odds, 4 decimals): raw, lo/hi "
    "bounds, and only where a term was clamped b bounded and cl clamped flags (else b is raw)",
    "ab": "the class's alert begins",
    "ae": "the class's alert ends (absent: until further notice)",
    "h": "1 when the class's alert names heights",
    "wa": "the strongest watch in the active feed reaching the district that day",
    "v": "shadow variants scored on the same row (later pieces)",
}


def freeze_at(day: date, zone: str, name: str) -> datetime:
    """When freeze ``name`` of school day ``day`` is on ``zone``'s clock (UTC)."""
    for found, offset, at in FREEZES:
        if found == name:
            local = datetime.combine(day + timedelta(days=offset), at, tzinfo=ZoneInfo(zone))
            return local.astimezone(UTC)
    raise ValueError(f"no freeze {name}")


def finished_at(day: date, zones: Iterable[str] = ()) -> datetime:
    """When school day ``day`` is finished: the last zone's 06:30 freeze plus :data:`SETTLE`."""
    return max(freeze_at(day, zone, "d0_0630") for zone in {LAST_ZONE, *zones}) + SETTLE


# --- the index --------------------------------------------------------------------------------


@dataclass(slots=True)
class DayEntry:
    """One day of the folder."""

    zones: list[str] = field(default_factory=list)
    groups: dict[str, str] = field(default_factory=dict)
    """``zone|freeze`` to ``taken`` or ``missed``."""
    bytes: int = 0
    closed: str | None = None
    """When it finished (ISO), once a pass saw it finished; it is then offered."""
    held: dict[str, str] = field(default_factory=dict)
    """Database to the sha256 it holds of the day."""

    def as_json(self) -> dict[str, object]:
        return {
            "zones": self.zones,
            "groups": self.groups,
            "bytes": self.bytes,
            "closed": self.closed,
            "held": self.held,
        }

    @classmethod
    def of(cls, value: object) -> "DayEntry":
        if not isinstance(value, dict):
            return cls()
        return cls(
            zones=[str(z) for z in value.get("zones") or []],
            groups={str(k): str(v) for k, v in (value.get("groups") or {}).items()},
            bytes=int(value.get("bytes") or 0),
            closed=None if value.get("closed") is None else str(value["closed"]),
            held={str(k): str(v) for k, v in (value.get("held") or {}).items()},
        )


@dataclass(slots=True)
class Index:
    """``index.json``: the days kept, the days released, and whether the folder began afresh
    (no index was there: a first run or a lost cache) and was not yet restored."""

    days: dict[str, DayEntry] = field(default_factory=dict)
    done: dict[str, str] = field(default_factory=dict)
    fresh: bool = False

    def as_json(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "days": {key: entry.as_json() for key, entry in sorted(self.days.items())},
            "done": dict(sorted(self.done.items())),
            "fresh": self.fresh,
        }


def load_index(folder: Path) -> Index:
    """The folder's index; where there is none, or it does not read or is of another
    :data:`SCHEMA`, one made again from the day files there (:func:`_rebuilt`), fresh."""
    try:
        found = json.loads((folder / INDEX).read_bytes())
    except (OSError, ValueError):
        return _rebuilt(folder)
    if not isinstance(found, dict) or found.get("schema") != SCHEMA:
        return _rebuilt(folder)
    return Index(
        days={str(k): DayEntry.of(v) for k, v in (found.get("days") or {}).items()},
        done={str(k): str(v) for k, v in (found.get("done") or {}).items()},
        fresh=bool(found.get("fresh")),
    )


def save_index(folder: Path, index: Index) -> None:
    write_bytes_atomic(folder / INDEX, json.dumps(index.as_json(), sort_keys=True).encode())


def day_path(folder: Path, day: str) -> Path:
    return folder / f"{day}.jsonl"


@dataclass(frozen=True, slots=True)
class _Block:
    """One whole freeze of a day file: its (zone, freeze), taken or missed, how late it was
    taken, where it ends in the file and its lines."""

    group: tuple[str, str]
    how: str
    late: int
    end: int
    data: bytes


def _blocks(data: bytes) -> Iterator[_Block]:
    """The whole freezes of a day file in order (a header and every row it counts, or a missed
    line, each line whole and read), up to the first that is not (a torn write or a cut
    file)."""
    pos = 0
    start = 0
    head: dict[str, Any] | None = None
    left = 0
    while (end := data.find(b"\n", pos)) >= 0:
        line, pos = data[pos:end], end + 1
        try:
            value = json.loads(line)
        except ValueError:
            return
        if not isinstance(value, dict):
            return
        kind = value.get("k")
        if kind in {"freeze", "missed"}:
            if head is not None:
                return  # a freeze cut short
            start = pos - len(line) - 1
            group = (str(value.get("zone")), str(value.get("freeze")))
            if kind == "missed":
                yield _Block(group, "missed", LATE_NEVER, pos, data[start:pos])
                continue
            head, left = value, int(value.get("rows") or 0)
        elif head is None:
            return
        else:
            left -= 1
        if left <= 0:
            group = (str(head.get("zone")), str(head.get("freeze")))
            late = int(head.get("late_by_s") or 0)
            yield _Block(group, "taken", late, pos, data[start:pos])
            head = None


def _scan(data: bytes) -> tuple[int, dict[str, str]]:
    """The bytes of a day file up to its last whole freeze, and the freezes held there
    (``zone|freeze`` to ``taken`` or ``missed``; the first copy of each)."""
    good = 0
    groups: dict[str, str] = {}
    for block in _blocks(data):
        groups.setdefault("|".join(block.group), block.how)
        good = block.end
    return good, groups


def _rebuilt(folder: Path) -> Index:
    """An index made again from the day files of the folder (its own was lost, does not read
    or is of another schema): each day open, with the freezes its file holds whole and its
    bytes up to them (a pass cuts the rest and closes the day when it has finished); fresh, so
    the evidence step restores the finished days the folder lacks."""
    index = Index(fresh=True)
    try:
        paths = sorted(folder.glob("*.jsonl"))
    except OSError:
        return index
    for path in paths:
        try:
            date.fromisoformat(path.stem)
            data = path.read_bytes()
        except (OSError, ValueError):
            continue
        good, groups = _scan(data)
        if groups:
            zones = sorted({group.split("|", 1)[0] for group in groups})
            index.days[path.stem] = DayEntry(zones=zones, groups=groups, bytes=good)
    return index


def _repair(folder: Path, key: str, entry: DayEntry) -> bool:
    """Make a day file hold exactly what its index counts: a longer file (a pass stopped
    between the append and the index) is cut back to the count, so a freeze is never in the
    file twice; a shorter one (a cut cache) is cut back to its last whole freeze and the index
    then counts only the freezes held there (a lost one is taken again while due, else written
    missed). Whether the index lost a freeze."""
    path = day_path(folder, key)
    try:
        size = path.stat().st_size
    except OSError:
        lost = bool(entry.bytes or entry.groups)
        entry.bytes = 0
        entry.groups = {}
        return lost
    if size > entry.bytes:
        with path.open("r+b") as handle:
            handle.truncate(entry.bytes)
    elif size < entry.bytes:
        good, groups = _scan(path.read_bytes())
        with path.open("r+b") as handle:
            handle.truncate(good)
        entry.bytes = good
        entry.groups = groups
        return True
    return False


# --- one pass's rows --------------------------------------------------------------------------


class Reach(Protocol):
    def __call__(self, event: LiveEvent) -> npt.NDArray[np.int64]: ...


@dataclass(frozen=True, slots=True)
class PassInputs:
    """What a pass served and made it from (the pass's own objects, read only)."""

    made: PredictionsFile
    model: ServeModel
    classes: npt.NDArray[np.int64]
    after: Mapping[date, frozenset[int]]
    forecasts: Forecasts
    events: Sequence[LiveEvent]
    """The alerts counted (the pass's alert memory)."""
    watches: Sequence[LiveEvent]
    """The active feed's heads-ups (watches among them)."""
    reach: Reach
    """The schools an event reaches (heights applied)."""
    reach_all: Reach
    """The schools an event's zones hold (for watches)."""
    window: Window
    shown: Callable[[], str | None]
    """Why the file's chances are not the public ones at the pass (``not_public``,
    ``not_shown`` or ``unconfirmed``: see :data:`ROW_KEYS`), or ``None`` where they are; asked
    once, and only by a pass that takes a freeze."""
    run_id: str | None
    code_sha: str | None
    live_score_sha256: str
    adjusted: bool
    """Whether the file applied the forecast adjustment (a regular file, adjusting, at a fit
    with reasons, and the reasons' terms off): only then does a row say what it read."""
    maker: str = "model"
    """What made the file's chances: ``model`` (the regular pass) or ``outlook``. An outlook
    file's rows hold what it published, not the regular model's level, offset or terms."""
    noted: Mapping[tuple[int, date], Noted] | None = None
    """The class order cap and terms of each adjusted district-day as the file applied them
    (``None``, or a day it lacks: worked out again)."""


@dataclass(frozen=True, slots=True)
class Taken:
    """One freeze a pass wrote: its day, name, how many zones and rows, the most late, missed
    zones."""

    day: str
    freeze: str
    zones: int
    rows: int
    late_s: int
    missed: int
    served: int


def _r(value: float | None, digits: int = ROUND) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def _iso(at: datetime | None) -> str | None:
    return None if at is None else at.astimezone(UTC).isoformat()


@dataclass(slots=True)
class _Alerts:
    begin: datetime
    end: datetime | None
    heights: bool


def _school_district(model: ServeModel) -> npt.NDArray[np.int64]:
    found = np.full(len(model.directory.points), -1, dtype=np.int64)
    for index, schools in enumerate(model.eligible):
        found[schools] = index
    return found


def _alert_spans(
    inputs: PassInputs,
    d: int,
    day: date,
    wanted: npt.NDArray[np.bool_],
    owner: npt.NDArray[np.int64],
) -> dict[int, _Alerts]:
    """Per district (of ``wanted``), the span of the alerts of its class that count for it on
    ``day`` and whether one names heights."""
    model = inputs.model
    now = inputs.made.generated_at
    spans: dict[int, _Alerts] = {}
    checked: dict[tuple[int, str], bool] = {}
    for e, item in enumerate(inputs.events):
        weather = item.event.weather
        if weather is None:
            continue
        reached = owner[inputs.reach(item)]
        for i in np.unique(reached[reached >= 0]).tolist():
            if not wanted[i] or int(inputs.classes[i, d]) != int(weather):
                continue
            zone = model.time_zone[i]
            key = (e, zone)
            if key not in checked:
                checked[key] = counts(item.event, day, zone, inputs.window, now)
            if not checked[key]:
                continue
            found = spans.get(i)
            end = item.event.end
            if found is None:
                spans[i] = _Alerts(item.event.start, end, item.elevation is not None)
                continue
            found.begin = min(found.begin, item.event.start)
            found.end = None if found.end is None or end is None else max(found.end, end)
            found.heights = found.heights or item.elevation is not None
    return spans


def _watches(
    inputs: PassInputs, day: date, wanted: npt.NDArray[np.bool_], owner: npt.NDArray[np.int64]
) -> dict[int, str]:
    """Per district (of ``wanted``), the strongest watch of the active feed reaching it whose
    span meets its window on ``day``."""
    model = inputs.model
    now = inputs.made.generated_at
    watches: dict[int, tuple[int, str]] = {}
    for item in inputs.watches:
        heads = item.event.heads_up
        if not heads or not heads.label.endswith("_watch") or item.event.issued > now:
            continue
        reached = owner[inputs.reach_all(item)]
        for i in np.unique(reached[reached >= 0]).tolist():
            if not wanted[i]:
                continue
            start, end = inputs.window.span(day, model.time_zone[i])
            event = item.event
            if not (event.start < end and (event.end is None or event.end > start)):
                continue
            if i not in watches or int(heads) < watches[i][0]:
                watches[i] = (int(heads), heads.label)
    return {i: label for i, (_, label) in watches.items()}


def _unrounded(  # noqa: PLR0913, PLR0917 - the model, the cell, what was served and how
    model: ServeModel,
    i: int,
    k: int,
    item: Forecast,
    detail: AdjustDetail | None,
    kinds: set[str],
) -> tuple[float | None, float | None]:
    """The chance of no school and of a delay before publishing rounded them, where the pass's
    model says (``None``: the file's lines come from elsewhere, so it is not known here)."""
    q_rate = float(model.q_rate[i, k]) if model.q_rate.size else math.nan
    settings = model.artifact.settings
    if "said_open" in kinds:
        return item.p_no_school, 0.0
    if not kinds:
        raw = float(model.p_rate[i, k]) if model.p_rate.size else math.nan
        shown = min(max(round(raw, 2), settings.floor), settings.ceiling)
        if not math.isfinite(raw) or round(shown * 100) != round(item.p_no_school * 100):
            return None, None
        return raw, (1.0 - item.p_no_school) * q_rate
    if detail is not None and detail.raw is not None and kinds <= ADJUST_KINDS:
        shown = min(max(round(detail.raw, 2), settings.floor), settings.ceiling)
        if round(shown * 100) == round(item.p_no_school * 100):
            return detail.raw, (1.0 - item.p_no_school) * q_rate
    return None, None


def _minutes(at: datetime, day: date) -> int:
    """Minutes from ``day``'s 00:00 UTC to ``at`` (a period's bound in a row)."""
    return round((at - datetime.combine(day, time(0), tzinfo=UTC)).total_seconds() / 60)


def _forecast_json(detail: AdjustDetail, day: date) -> dict[str, object] | None:
    found = detail.forecast
    if found is None:
        return None
    value: dict[str, object] = {
        "sn": _r(found.snow, SNOW_ROUND),
        "cm": _r(found.snow_commute, SNOW_ROUND),
        "bb": _r(found.snow_bus, SNOW_ROUND),
        "pp": [
            [_minutes(p.start, day), _minutes(p.end, day), _r(p.snow, SNOW_ROUND)]
            for p in found.snow_parts
        ],
        "ice": _r(found.ice, ICE_ROUND),
        "fl": found.feels,
        "code": found.code,
        "rt": _iso(found.run_time),
    }
    return {key: v for key, v in value.items() if v is not None}


def _terms_json(detail: AdjustDetail) -> dict[str, object] | None:
    parts = detail.parts
    if parts is None:
        return None
    found: dict[str, object] = {
        "raw": [_r(v, TERM_ROUND) for v in parts.raw],
        "lo": _r(parts.low, TERM_ROUND),
        "hi": _r(parts.high, TERM_ROUND),
    }
    clamped = [int(abs(a - b) > CLAMPED) for a, b in zip(parts.raw, parts.bounded, strict=True)]
    if any(clamped):
        found["b"] = [_r(v, TERM_ROUND) for v in parts.bounded]
        found["cl"] = clamped
    return found


def _terms_read(value: object) -> Mapping[str, Any] | None:
    """A row's terms as the reader gives them: ``raw``, ``b``, ``cl``, ``lo`` and ``hi`` each
    (a row keeps ``b`` and ``cl`` only where a term was clamped)."""
    if not isinstance(value, dict):
        return None
    raw = list(value.get("raw") or ())
    return {
        "raw": raw,
        "b": list(value.get("b") or raw),
        "cl": list(value.get("cl") or [0] * len(raw)),
        "lo": value.get("lo"),
        "hi": value.get("hi"),
    }


def _row(  # noqa: PLR0913, PLR0917 - one district's fields, each where it applies
    inputs: PassInputs,
    i: int,
    d: int,
    day: date,
    offsets: npt.NDArray[np.float64],
    spans: Mapping[int, _Alerts],
    watches: Mapping[int, str],
    hidden: str | None,
) -> dict[str, object]:
    model, made = inputs.model, inputs.made
    row: dict[str, object] = {"l": model.directory.district_ids[i]}
    item = made.districts[i].days[d] if i < len(made.districts) else None
    if not isinstance(item, Forecast):
        row.update(s=0, why="no_chance", v={})
        return row
    row["s"] = 1 if hidden is None else 0
    if hidden is not None:
        row["why"] = hidden
    weather = WeatherClass(int(inputs.classes[i, d]))
    situation = Situation.of(weather, i in inputs.after.get(day, frozenset()))
    k = SITUATION_POSITION[situation.key]
    kinds: set[str] = {str(reason.kind) for reason in item.why.reasons}
    regular = inputs.maker == "model"
    detail = (
        adjust_detail(model, i, k, day, inputs.forecasts, made.generated_at, inputs.noted)
        if regular and inputs.adjusted and "said_open" not in kinds
        else None
    )
    p_raw, q_raw = _unrounded(model, i, k, item, detail, kinds) if regular else (None, None)
    klass = CLASS_OF_WEATHER.get(int(weather), "none")
    row.update(p=item.p_no_school, q=item.p_delay, pr=_r(p_raw), qr=_r(q_raw))
    row.update(sit=situation.key, c=klass, ak=ALERT_KIND.get(weather), b=item.why.base.kind)
    if isinstance(item.why.base, ClassBase):
        row["pts"] = item.why.base.points
        if regular and model.p_rate.size:
            row["lv"] = _r(float(model.p_rate[i, k]))
    if regular and klass in CLASSES:
        row["o"] = _r(float(offsets[i, CLASSES.index(klass)]), TERM_ROUND)
    if item.why.reasons:
        row["rs"] = [[reason.kind, reason.points] for reason in item.why.reasons]
    if "said_open" in kinds:
        row["sa"] = 1
    if detail is not None:
        row.update(_read_fields(detail, day, made.generated_at, kinds))
    span = spans.get(i)
    if span is not None:
        row.update(ab=_iso(span.begin), ae=_iso(span.end), h=int(span.heights))
    if i in watches:
        row["wa"] = watches[i]
    row["v"] = {}
    return {key: value for key, value in row.items() if value is not None}


_MADE_FOR: list[tuple[ServeModel, npt.NDArray[np.float64], npt.NDArray[np.int64]]] = []
"""The last model's exposure offsets and school owners, worked out once per model (a pass
keeps its model until the directory or the artifact changes)."""


def _of_model(model: ServeModel) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.int64]]:
    for known, offsets, owner in _MADE_FOR:
        if known is model:
            return offsets, owner
    offsets, owner = exposure_offsets(model), _school_district(model)
    _MADE_FOR[:] = [(model, offsets, owner)]
    return offsets, owner


def _read_fields(
    detail: AdjustDetail, day: date, generated: datetime, kinds: set[str]
) -> dict[str, object]:
    """What a row says the forecast adjustment read (``fr``, ``f``, ``t``)."""
    if generated < detail.snapshot:
        return {"fr": "before"}
    if detail.forecast is not None:
        return {"fr": "read", "f": _forecast_json(detail, day), "t": _terms_json(detail)}
    return {"fr": "kept" if kinds and kinds <= ADJUST_KINDS else "none"}


def _lines(
    inputs: PassInputs, day: date, zone_rows: Mapping[str, list[int]], hidden: str | None
) -> dict[str, list[dict[str, object]]]:
    made = inputs.made
    d = made.days.index(day)
    wanted = np.zeros(len(inputs.model.directory.district_ids), dtype=np.bool_)
    for indexes in zone_rows.values():
        wanted[indexes] = True
    offsets, owner = _of_model(inputs.model)
    spans = _alert_spans(inputs, d, day, wanted, owner)
    watches = _watches(inputs, day, wanted, owner)
    return {
        zone: [_row(inputs, i, d, day, offsets, spans, watches, hidden) for i in indexes]
        for zone, indexes in zone_rows.items()
    }


def _dumps(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode() + b"\n"


def record(inputs: PassInputs, folder: Path = FOLDER) -> list[Taken]:  # noqa: PLR0912, PLR0915
    """Take every freeze due at the pass (see the module), close the days that finished, and
    write them; what was written, per day and freeze.

    Raises:
        OSError, ValueError: the folder does not write (the caller logs it; nothing served
            changes).
    """
    made, model = inputs.made, inputs.model
    now = made.generated_at
    folder.mkdir(parents=True, exist_ok=True)
    index = load_index(folder)
    by_zone: dict[str, list[int]] = {}
    for i, zone in enumerate(model.time_zone):
        by_zone.setdefault(zone, []).append(i)
    for day in made.days:
        key = day.isoformat()
        if not is_school_day(day) or key in index.done:
            continue
        if key not in index.days and now >= finished_at(day, by_zone):
            continue  # first seen once finished (a lost folder): nothing left to take
        entry = index.days.setdefault(key, DayEntry())
        entry.zones = sorted(set(entry.zones) | set(by_zone))
    written: dict[tuple[str, str], list[int]] = {}
    shown: list[str | None] = []

    def hidden() -> str | None:
        if not shown:
            shown.append(inputs.shown())
        return shown[0]

    for key, entry in sorted(index.days.items()):
        if _repair(folder, key, entry) and entry.closed is not None:
            entry.closed = None  # a finished day that lost a freeze: closed again below
            entry.held = {}
        if entry.closed is not None:
            continue
        day = date.fromisoformat(key)
        take: dict[str, list[tuple[str, datetime]]] = {}
        out: list[bytes] = []
        for zone in entry.zones:
            for name in NAMES:
                group = f"{zone}|{name}"
                if group in entry.groups:
                    continue
                at = freeze_at(day, zone, name)
                if now < at:
                    continue
                if now - at > LATE_MAX or day not in made.days or zone not in by_zone:
                    out.append(_missed(day, zone, name, at, len(by_zone.get(zone, ())), now))
                    entry.groups[group] = "missed"
                    count = written.setdefault((key, name), [0, 0, 0, 0, 0])
                    count[3] += 1
                    continue
                take.setdefault(name, []).append((zone, at))
        for name, zones in take.items():
            why = hidden()
            lines = _lines(inputs, day, {zone: by_zone[zone] for zone, _ in zones}, why)
            count = written.setdefault((key, name), [0, 0, 0, 0, 0])
            for zone, at in zones:
                rows = lines[zone]
                late = round((now - at).total_seconds())
                head = _header(inputs, day, zone, name, at, late, len(rows), why)
                out.append(_dumps(head))
                out.extend(_dumps(row) for row in rows)
                entry.groups[f"{zone}|{name}"] = "taken"
                count[0] += 1
                count[1] += len(rows)
                count[2] = max(count[2], late)
                count[4] += sum(1 for row in rows if row.get("s") == 1)
        if now >= finished_at(day, entry.zones):
            for zone in entry.zones:
                for name in NAMES:
                    group = f"{zone}|{name}"
                    if group not in entry.groups:
                        at = freeze_at(day, zone, name)
                        out.append(_missed(day, zone, name, at, len(by_zone.get(zone, ())), now))
                        entry.groups[group] = "missed"
                        written.setdefault((key, name), [0, 0, 0, 0, 0])[3] += 1
            entry.closed = finished_at(day, entry.zones).isoformat()
        if out:
            data = b"".join(out)
            with day_path(folder, key).open("ab") as handle:
                handle.write(data)
            entry.bytes += len(data)
    save_index(folder, index)
    return [
        Taken(day, name, c[0], c[1], c[2], c[3], c[4]) for (day, name), c in sorted(written.items())
    ]


def _header(  # noqa: PLR0913, PLR0917 - the pass, the freeze and its counts
    inputs: PassInputs,
    day: date,
    zone: str,
    name: str,
    at: datetime,
    late: int,
    rows: int,
    hidden: str | None,
) -> dict[str, object]:
    found: dict[str, object] = {
        "k": "freeze",
        "day": day.isoformat(),
        "freeze": name,
        "zone": zone,
        "at": _iso(at),
        "late_by_s": late,
        "generated_at": _iso(inputs.made.generated_at),
        "run_id": inputs.run_id,
        "code_sha": inputs.code_sha,
        "live_score_sha256": inputs.live_score_sha256,
        "public": hidden is None,
        "why": hidden,
        "maker": None if inputs.maker == "model" else inputs.maker,
        "rows": rows,
    }
    return {key: value for key, value in found.items() if value is not None}


def _missed(  # noqa: PLR0913, PLR0917 - the freeze and the districts it would have held
    day: date, zone: str, name: str, at: datetime, districts: int, now: datetime
) -> bytes:
    return _dumps(
        {
            "k": "missed",
            "day": day.isoformat(),
            "freeze": name,
            "zone": zone,
            "at": _iso(at),
            "districts": districts,
            "noted_at": _iso(now),
        }
    )


def said(taken: Sequence[Taken]) -> list[str]:
    """One log line per day and freeze written."""
    found: list[str] = []
    for item in taken:
        missed = f", {item.missed} zones missed" if item.missed else ""
        rows = (
            f"{item.zones} zones, {item.rows:,} rows ({item.served:,} served), "
            f"up to {item.late_s} s late"
            if item.zones
            else "no zone taken"
        )
        found.append(f"predict frozen: {item.day} {item.freeze}: {rows}{missed}")
    return found


# --- the evidence -----------------------------------------------------------------------------


def offers(folder: Path = FOLDER) -> list[tuple[str, bytes]]:
    """The finished days of the folder (key, bytes) not yet in both databases."""
    index = load_index(folder)
    found: list[tuple[str, bytes]] = []
    for key, entry in sorted(index.days.items()):
        if entry.closed is None:
            continue
        try:
            found.append((key, day_path(folder, key).read_bytes()[: entry.bytes]))
        except OSError:
            continue
    return found


def note_held(
    folder: Path,
    held: Mapping[str, Mapping[tuple[str, str], frozenset[str]]],
    now: datetime,
) -> list[str]:
    """Note which databases hold each finished day byte for byte (``held``: per database that
    answered, ``(kind, key)`` to the sha256s it holds, :meth:`snowlight.live.evidence.
    EvidenceStore.held`); a day both of ``databases`` hold leaves the folder (it is remembered
    :data:`DONE_DAYS` days). The days released."""
    from snowlight.live.evidence import DATABASES, FROZEN  # noqa: PLC0415

    index = load_index(folder)
    released: list[str] = []
    for key, entry in sorted(index.days.items()):
        if entry.closed is None:
            continue
        try:
            data = day_path(folder, key).read_bytes()[: entry.bytes]
        except OSError:
            continue
        digest = hashlib.sha256(data).hexdigest()
        for database, versions in held.items():
            if digest in versions.get((FROZEN, key), frozenset()):
                entry.held[database] = digest
        if all(entry.held.get(name) == digest for name in DATABASES):
            index.done[key] = digest
            released.append(key)
    for key in released:
        del index.days[key]
        day_path(folder, key).unlink(missing_ok=True)
    oldest = (now.astimezone(UTC).date() - timedelta(days=DONE_DAYS)).isoformat()
    index.done = {key: v for key, v in index.done.items() if key >= oldest}
    save_index(folder, index)
    return released


def check(folder: Path, now: datetime) -> tuple[str, int]:
    """``predict evidence --check``'s line for the frozen record, and how many finished days
    have waited over :data:`WAIT` for both databases."""
    from snowlight.live.evidence import DATABASES  # noqa: PLC0415

    index = load_index(folder)
    closed = {key: entry for key, entry in index.days.items() if entry.closed is not None}
    late = sum(
        1
        for entry in closed.values()
        if entry.closed is not None
        and now - datetime.fromisoformat(entry.closed) > WAIT
        and not all(name in entry.held for name in DATABASES)
    )
    line = (
        f"predict evidence check: {len(closed)} finished frozen days wait for both databases,"
        f" {len(index.done)} released"
    )
    if late:
        line += f"; {late} waited over 2 days"
    return line, late


class Store(Protocol):
    def pull_all(self, kind: str, since: date | None = None) -> dict[tuple[str, str], bytes]: ...


def merge(versions: Iterable[bytes]) -> bytes:
    """One day from every copy of it (the folder's, each version a database keeps): each
    (zone, freeze) once, a taken copy over a missed one and of two taken the one taken
    first, in the order first seen. A day kept in one version comes back byte for byte (a
    torn tail left out).

    A version can say ``missed`` for a freeze another holds taken: a run whose folder was not
    saved after its push leaves the next run an older folder, which closes the day without
    the freezes taken since."""
    chosen: dict[tuple[str, str], _Block] = {}
    for data in versions:
        for block in _blocks(data):
            have = chosen.get(block.group)
            if have is None or block.late < have.late:
                chosen[block.group] = block
    return b"".join(block.data for block in chosen.values())


def _store_days(store: Store, since: date) -> dict[str, list[bytes]]:
    from snowlight.live.evidence import FROZEN  # noqa: PLC0415

    found: dict[str, list[bytes]] = {}
    for (key, _sha), data in sorted(store.pull_all(FROZEN, since).items()):
        found.setdefault(key, []).append(data)
    return found


def restore(folder: Path, store: Store, now: datetime) -> list[str]:
    """After the folder was lost (its index began afresh): the finished days of the last
    :data:`RESTORE_DAYS` days the store holds and the folder lacks, back into the folder as
    finished days (every version kept merged, :func:`merge`; so they are kept until both
    databases hold them, and none is taken up again). The days restored; none when the index
    is not fresh."""
    index = load_index(folder)
    if not index.fresh:
        return []
    since = now.astimezone(UTC).date() - timedelta(days=RESTORE_DAYS)
    restored: list[str] = []
    for key, versions in sorted(_store_days(store, since).items()):
        if key in index.days or key in index.done:
            continue
        data = merge(versions)
        day = parse_day(data)
        write_bytes_atomic(day_path(folder, key), data)
        index.days[key] = DayEntry(
            zones=sorted({z for z, _ in day.groups}),
            groups={f"{zone}|{name}": how for (zone, name), how in day.groups.items()},
            bytes=len(data),
            closed=finished_at(date.fromisoformat(key), {z for z, _ in day.groups}).isoformat(),
        )
        restored.append(key)
    index.fresh = False
    folder.mkdir(parents=True, exist_ok=True)
    save_index(folder, index)
    return restored


# --- the read path (L4) -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrozenRow:
    """One district's frozen chance at one freeze, with its freeze's fields (typed)."""

    day: date
    freeze: str
    zone: str
    at: datetime
    late_by_s: int
    generated_at: datetime
    run_id: str | None
    code_sha: str | None
    live_score_sha256: str
    leaid: str
    served: bool
    why: str | None
    p: float | None
    q: float | None
    p_raw: float | None
    q_raw: float | None
    situation: str | None
    klass: str | None
    alert: str | None
    base: str | None
    level: float | None
    points: int | None
    offset: float | None
    reasons: tuple[tuple[str, int], ...]
    said_open: bool
    forecast_read: str | None
    forecast: Mapping[str, Any] | None
    terms: Mapping[str, Any] | None
    alert_begin: datetime | None
    alert_end: datetime | None
    heights: bool
    watch: str | None
    variants: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Missed:
    """A freeze written missed: counts only."""

    day: date
    freeze: str
    zone: str
    at: datetime
    districts: int


@dataclass(frozen=True, slots=True)
class FrozenDay:
    """A day's rows and missed freezes, each (freeze, zone) once, and what each group was."""

    day: date
    rows: tuple[FrozenRow, ...]
    missed: tuple[Missed, ...]
    groups: Mapping[tuple[str, str], str]
    """``(zone, freeze)`` to ``taken`` or ``missed``."""


def _time(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def _float(value: object) -> float | None:
    return None if value is None else float(str(value))


def _make_row(header: Mapping[str, Any], row: Mapping[str, Any]) -> FrozenRow:
    points = row.get("pts")
    return FrozenRow(
        day=date.fromisoformat(str(header["day"])),
        freeze=str(header["freeze"]),
        zone=str(header["zone"]),
        at=datetime.fromisoformat(str(header["at"])),
        late_by_s=int(header["late_by_s"]),
        generated_at=datetime.fromisoformat(str(header["generated_at"])),
        run_id=header.get("run_id"),
        code_sha=header.get("code_sha"),
        live_score_sha256=str(header["live_score_sha256"]),
        leaid=str(row["l"]),
        served=row.get("s") == 1,
        why=row.get("why"),
        p=_float(row.get("p")),
        q=_float(row.get("q")),
        p_raw=_float(row.get("pr")),
        q_raw=_float(row.get("qr")),
        situation=row.get("sit"),
        klass=row.get("c"),
        alert=row.get("ak"),
        base=row.get("b"),
        level=_float(row.get("lv")),
        points=None if points is None else int(points),
        offset=_float(row.get("o")),
        reasons=tuple((str(kind), int(n)) for kind, n in row.get("rs") or ()),
        said_open=row.get("sa") == 1,
        forecast_read=row.get("fr"),
        forecast=row.get("f"),
        terms=_terms_read(row.get("t")),
        alert_begin=_time(row.get("ab")),
        alert_end=_time(row.get("ae")),
        heights=row.get("h") == 1,
        watch=row.get("wa"),
        variants=dict(row.get("v") or {}),
    )


def parse_day(data: bytes) -> FrozenDay:
    """A day file's rows and missed freezes; a (zone, freeze) given twice counts once, the
    first (a later copy is never read).

    Raises:
        ValueError: a line does not read, or a row has no freeze before it.
    """
    rows: list[FrozenRow] = []
    missed: list[Missed] = []
    groups: dict[tuple[str, str], str] = {}
    header: Mapping[str, Any] | None = None
    skip = False
    day: date | None = None
    for line in data.splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        kind = value.get("k")
        if kind in {"freeze", "missed"}:
            group = (str(value["zone"]), str(value["freeze"]))
            day = date.fromisoformat(str(value["day"]))
            skip = group in groups
            header = value if kind == "freeze" else None
            if skip:
                continue
            groups[group] = "taken" if kind == "freeze" else "missed"
            if kind == "missed":
                missed.append(
                    Missed(
                        day=day,
                        freeze=group[1],
                        zone=group[0],
                        at=datetime.fromisoformat(str(value["at"])),
                        districts=int(value["districts"]),
                    )
                )
            continue
        if skip:
            continue
        if header is None:
            raise ValueError("a frozen row with no freeze before it")
        rows.append(_make_row(header, value))
    if day is None:
        raise ValueError("an empty frozen day")
    return FrozenDay(day, tuple(rows), tuple(missed), groups)


def rows(
    first: date,
    last: date,
    folder: Path = FOLDER,
    store: Store | None = None,
) -> dict[date, FrozenDay]:
    """The frozen days from ``first`` to ``last``: each from the folder and, where a store is
    given, every version it keeps, merged (:func:`merge`: a freeze taken in any copy is read
    taken). A day neither holds is left out.

    Raises:
        ValueError: a day does not read.
        snowlight.live.evidence.EvidenceError: the store does not read.
    """
    index = load_index(folder)
    wanted = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    copies: dict[str, list[bytes]] = {}
    for day in wanted:
        entry = index.days.get(day.isoformat())
        if entry is None or not entry.bytes:
            continue
        try:
            data = day_path(folder, day.isoformat()).read_bytes()[: entry.bytes]
        except OSError:
            continue
        copies[day.isoformat()] = [data]
    if store is not None:
        for key, versions in _store_days(store, first).items():
            if key <= last.isoformat():
                copies.setdefault(key, []).extend(versions)
    found = {date.fromisoformat(key): parse_day(merge(data)) for key, data in copies.items()}
    return dict(sorted(found.items()))

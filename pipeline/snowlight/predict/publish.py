"""Putting ``predictions/latest.json`` on the live host, or keeping it dark (spec d).

A pass publishes through a :class:`Host`, the publisher interface of the live ingest
(S8-D's ``snowlight.live.publishers``: ``read(key)`` and ``write(files)``, keys under
``v1/`` or ``v1-shadow/`` only). ``PREDICT_PUBLISH`` picks the folder: ``on``
(``v1/``), ``shadow`` (``v1-shadow/``) or ``off`` (the default: nothing is written).

Fails dark (nothing uploads, the pass exits 3, the old file ages out and the page hides
the chance within 90 minutes; never a stale or invented chance) when:

1. the alerts feed cannot be read, or its ``updated`` is older than
   ``alerts_max_age_minutes``;
2. the deployed edition cannot be read, or its ``meta.json`` and ``points.bin`` are not
   the ones it names;
3. fewer than ``min_district_share`` of the deployed districts are in the model;
4. the winter alerts drop by more than ``collapse_drop`` from a pass that had more than
   ``collapse_from``: publish only once the next pass confirms it;
5. the file does not validate, or breaks the size budget (raw and gzip);
6. the file read back after the upload is not the one sent;
7. yesterday's day timeline on the host cannot be read (only a file that is not there means
   no district had a day off);
8. the 30-hour alert memory does not reach back to 18:00 the evening before the first day
   published (a lost or stale state) and cannot be rebuilt from the NWS alert history;
9. ``predict blank`` set the hold (``predictions/hold.json``): every upload is refused until
   ``predict release`` clears it.

A file whose content (all but ``generated_at``) equals the last one uploaded is not
uploaded again, except as the heartbeat: every pass on the grid (:07 and :37) uploads it
unless an upload went out less than ``heartbeat_skip_minutes`` before, and any pass does
once ``heartbeat_minutes`` have passed. The page hides a file older than 90 minutes, so
the heartbeat keeps a true file fresh. ``blank`` sets the hold and uploads a valid file
with no districts at once (an immediate dark that stays dark).
"""

import gzip
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol

from pydantic import ValidationError

from snowlight.live.publish import LiveHold, holds
from snowlight.live.publishers import GuardRefusedError, WriteGuard, guarded_write
from snowlight.predict.config import ServeSettings
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.predictions import PredictionsFile

PATH: Final = "predictions/latest.json"
HOLD_NAME: Final = "hold.json"


class Host(Protocol):
    """Where the live files go (S8-D's ``Publisher``)."""

    def read(self, key: str) -> bytes | None:
        """The bytes the host holds at ``key``, or ``None``."""
        ...

    def write(self, files: Mapping[str, bytes]) -> None:
        """Write every file of one publish."""
        ...


class Mode(StrEnum):
    """``PREDICT_PUBLISH``: where a pass writes."""

    ON = "on"
    SHADOW = "shadow"
    OFF = "off"

    @property
    def key(self) -> str | None:
        """The file's key on the host, or ``None`` when nothing is written."""
        if self is Mode.ON:
            return f"v1/{PATH}"
        if self is Mode.SHADOW:
            return f"v1-shadow/{PATH}"
        return None


def mode_of(value: str | None) -> Mode:
    """The mode ``PREDICT_PUBLISH`` names; unset is ``off``.

    Raises:
        ValueError: it names another.
    """
    return Mode(value or Mode.OFF.value)


class Dark(StrEnum):
    """Why a pass published nothing."""

    ALERTS = "alerts_unreadable"
    ALERTS_STALE = "alerts_stale"
    EDITION = "edition_unreadable"
    COVERAGE = "coverage"
    COLLAPSE = "alert_collapse"
    INVALID = "invalid"
    SIZE = "size"
    READ_BACK = "read_back"
    DAY_FILE = "day_file_unreadable"
    MEMORY = "alert_memory"
    HELD = "held"


class DarkError(RuntimeError):
    """The pass refused to publish (exit 3)."""

    def __init__(self, reason: Dark, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason


def content_digest(data: bytes) -> str:
    """SHA-256 of a file's content with ``generated_at`` left out (and ``previous`` times kept):
    equal digests mean nothing a reader sees changed."""
    document = json.loads(data)
    document.pop("generated_at", None)
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()


def check_budget(data: bytes, settings: ServeSettings) -> int:
    """The file's gzip size, when within the budget.

    Raises:
        DarkError: raw or gzip size over budget.
    """
    packed = len(gzip.compress(data, mtime=0))
    if len(data) > settings.budget_raw_bytes or packed > settings.budget_gzip_bytes:
        raise DarkError(Dark.SIZE, f"{len(data):,} bytes raw, {packed:,} gzip")
    return packed


def checked(data: bytes) -> PredictionsFile:
    """The file, parsed back strictly.

    Raises:
        DarkError: it does not validate.
    """
    try:
        return PredictionsFile.from_json_bytes(data)
    except ValidationError as error:
        raise DarkError(Dark.INVALID, f"{error.error_count()} errors") from error


def check_alert_age(updated: datetime | None, now: datetime, settings: ServeSettings) -> None:
    """Refuse a feed with no ``updated`` or one older than the limit.

    Raises:
        DarkError: the feed is stale.
    """
    if updated is None or now - updated > timedelta(minutes=settings.alerts_max_age_minutes):
        raise DarkError(Dark.ALERTS_STALE, f"updated {updated}")


def check_coverage(share: float, settings: ServeSettings) -> None:
    """Refuse a pass that knows too few deployed districts.

    Raises:
        DarkError: under ``min_district_share``.
    """
    if share < settings.min_district_share:
        raise DarkError(Dark.COVERAGE, f"{share:.4f} of deployed districts in the model")


@dataclass(slots=True)
class State:
    """What the pass remembers between runs (the private state)."""

    digest: str | None = None
    """:func:`content_digest` of the last file uploaded."""
    uploaded_at: datetime | None = None
    winter_alerts: int | None = None
    """Winter alert count of the last pass that was not held for a collapse."""
    held_count: int | None = None
    """The collapsed count a pass held, waiting for the next pass to confirm it."""
    alerts_digest: str | None = None
    """The alerts the last pass that published (or found nothing to change) was made from; a
    pass that went dark leaves it, so the loop tries again."""
    memory: list[dict[str, object]] = field(default_factory=list)
    memory_since: datetime | None = None
    """Since when the memory holds every alert of the feed (it was read at least every
    ``memory_gap_minutes`` since then, or rebuilt from the NWS alert history)."""
    observed_at: datetime | None = None
    """The last time the memory took in the feed."""
    snapshots: dict[str, object] = field(default_factory=dict)
    """Each district's weather class per school day as the passes up to its training snapshot
    saw it (:func:`snowlight.predict.live_labels.record_snapshots`): what the live days'
    labels are counted under."""

    def as_json(self) -> dict[str, object]:
        """For the state store."""

        def when(moment: datetime | None) -> str | None:
            return None if moment is None else moment.isoformat()

        return {
            "digest": self.digest,
            "uploaded_at": when(self.uploaded_at),
            "winter_alerts": self.winter_alerts,
            "held_count": self.held_count,
            "alerts_digest": self.alerts_digest,
            "memory": self.memory,
            "memory_since": when(self.memory_since),
            "observed_at": when(self.observed_at),
            "snapshots": self.snapshots,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> "State":
        """The state as kept (missing fields are empty)."""
        uploaded = value.get("uploaded_at")
        memory = value.get("memory")
        winter = value.get("winter_alerts")
        held = value.get("held_count")
        digest = value.get("digest")
        alerts = value.get("alerts_digest")
        since = value.get("memory_since")
        observed = value.get("observed_at")
        snapshots = value.get("snapshots")
        return cls(
            digest=digest if isinstance(digest, str) else None,
            uploaded_at=datetime.fromisoformat(uploaded) if isinstance(uploaded, str) else None,
            winter_alerts=winter if isinstance(winter, int) else None,
            held_count=held if isinstance(held, int) else None,
            alerts_digest=alerts if isinstance(alerts, str) else None,
            memory=list(memory) if isinstance(memory, list) else [],
            memory_since=datetime.fromisoformat(since) if isinstance(since, str) else None,
            observed_at=datetime.fromisoformat(observed) if isinstance(observed, str) else None,
            snapshots=dict(snapshots) if isinstance(snapshots, dict) else {},
        )


def check_collapse(count: int, state: State, settings: ServeSettings) -> None:
    """Hold a pass whose winter alerts collapsed, until the next pass confirms the count.

    A count within ``collapse_drop`` of the last one, or one a held pass already saw
    (within the same drop), is accepted and becomes the last count.

    Raises:
        DarkError: the first pass after the collapse.
    """
    last = state.winter_alerts
    collapsed = (
        last is not None
        and last > settings.collapse_from
        and count < (1.0 - settings.collapse_drop) * last
    )
    if collapsed and (
        state.held_count is None or count < (1.0 - settings.collapse_drop) * state.held_count
    ):
        state.held_count = count
        raise DarkError(Dark.COLLAPSE, f"{count} winter alerts after {last}")
    state.winter_alerts = count
    state.held_count = None


def due(state: State, digest: str, now: datetime, settings: ServeSettings, *, grid: bool) -> bool:
    """Whether to upload: the content changed; or the heartbeat: a pass on the grid, unless an
    upload went out less than ``heartbeat_skip_minutes`` before, or any pass once
    ``heartbeat_minutes`` have passed."""
    if state.digest != digest or state.uploaded_at is None:
        return True
    age = now - state.uploaded_at
    if age >= timedelta(minutes=settings.heartbeat_minutes):
        return True
    return grid and age >= timedelta(minutes=settings.heartbeat_skip_minutes)


def hold_key(key: str) -> str:
    """The hold beside a file's key (``v1/predictions/hold.json``)."""
    return f"{key.rsplit('/', 1)[0]}/{HOLD_NAME}"


def held(data: bytes | None) -> bool:
    """Whether a hold file holds the chances dark (one that does not read does)."""
    return holds(data)


def upload(host: Host, key: str, data: bytes) -> None:
    """Write the file, guarded by the hold (read in the very commit on GitHub), and read it
    back.

    Raises:
        DarkError: the hold is set, or the read-back differs.
        PublishError: the host failed.
    """
    try:
        guarded_write(host, {key: data}, WriteGuard(hold_key(key), held))
    except GuardRefusedError as error:
        raise DarkError(Dark.HELD, hold_key(key)) from error
    if host.read(key) != data:
        raise DarkError(Dark.READ_BACK, key)


def hold_file(now: datetime, *, set_hold: bool, began: datetime | None) -> bytes:
    """The hold's bytes: set (``predict blank``) or cleared (``predict release``)."""
    moment = now.astimezone(UTC).replace(microsecond=0)
    return LiveHold(
        schema_version=1, held=set_hold, at=moment, held_at=moment if set_hold else began
    ).to_json_bytes()


def blank_file(stamp: DirectoryStamp, days: tuple[date, ...], now: datetime) -> bytes:
    """A valid file with no districts: every chance goes dark at once."""
    return PredictionsFile(
        schema_version=1,
        generated_at=now.replace(microsecond=0),
        directory=stamp,
        days=days,
        districts=(),
    ).to_json_bytes()


@dataclass(frozen=True, slots=True)
class Outcome:
    """What a publish step did."""

    uploaded: bool
    bytes: int
    gzip_bytes: int
    digest: str

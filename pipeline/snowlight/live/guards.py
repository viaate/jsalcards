"""The live guards: why a row or a status is withheld, the thresholds, and the pure checks.

Every row or status left out is counted by a :class:`Withheld` reason. The checks
here are pure functions of their arguments:

* the wording gates the status reader leaves to the ingest (:func:`wording_reason`):
  a planned or test day, a learning mode beside a status that is not remote, an
  all-caps "SAT", a weekday followed by bare day numbers;
* a district row that names part of its district (:func:`names_part`);
* the source hold (G13, :func:`held`) and the breaker limit (G9, :func:`breaker_limit`);
* the publish gate's checks (G12, :func:`gate_refusals`) and its spike hold
  (G12e, :func:`spike_hold`), which the publisher (S8-D) runs before every upload.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from snowlight.replays.build import PART_WORDS
from snowlight.replays.gates import LEARNING_WORDS, NON_WEATHER_WORDS, learning_mode

GUARDS_VERSION: Final = "s8c-4"
"""Part of every ``derived_version``: bump it when a guard changes what a row derives."""


class Withheld(StrEnum):
    """Why a row, a school or a status is not published."""

    EXCLUDED_PLATFORM = "excluded_platform"
    UNMATCHED = "unmatched"
    REJECTED_MATCH = "rejected_match"
    LOCATED = "located"
    OUT_OF_STATE = "out_of_state"
    SECTION = "section"
    UNANCHORED = "unanchored"
    DISTRICT_EXCLUDES_CHARTER = "district_excludes_charter"
    DISTRICT_EXCLUDES_VIRTUAL = "district_excludes_virtual"
    FACILITY = "facility"
    PART_OF_DISTRICT = "part_of_district"
    BIG_EXPANSION = "big_expansion"
    TERMS = "terms"
    NOT_STATUS = "not_status"
    WEAK = "weak"
    NOTE = "note"
    NOT_WEATHER = "not_weather"
    WORDING = "wording"
    UNKNOWN_START = "unknown_start"
    CHURN = "churn"
    REWORDED = "reworded"
    """A listing re-worded so that its reading depends on when it was posted, with nothing
    to show whether the new words were posted now or re-render the old posting."""
    OPEN_UNDATED = "open_undated"
    """An explicit open statement that cannot be dated to its posting day: it stands against
    older statuses but is never kept as an open signal."""
    INTERVAL_TOO_LONG = "interval_too_long"
    INTERVAL_DISAGREES = "interval_disagrees"
    ZONE_SPLIT = "zone_split"
    ZONE_UNKNOWN = "zone_unknown"
    BOARD_DATE = "board_date"
    STALE_UNPROVEN = "stale_unproven"
    NOT_DERIVED = "not_derived"
    SUPERSEDED = "superseded"
    VANISHED_BEFORE_DAY = "vanished_before_day"
    PAST_DAY = "past_day"
    OUT_OF_WINDOW = "out_of_window"
    STALE_SOURCE = "stale_source"
    CONFLICT = "conflict"
    RETRACTED = "retracted"
    BREAKER = "breaker"
    SPIKE_HOLD = "spike_hold"


@dataclass(frozen=True, slots=True)
class Rules:
    """The live thresholds and flags (``pipeline/config/live.yaml`` once S8-D loads it)."""

    min_confidence: float = 0.8
    """G4 (owner Q5): a status lights only at this reader confidence or more, at every sample."""
    weak_confidence: float = 0.7
    """Readings from here up to :attr:`min_confidence` are counted as ``WEAK`` (Q5 report)."""
    open_confidence: float = 0.9
    """An explicit open statement counts as an OPEN signal from this confidence (owner Q8)."""
    longest_interval: timedelta = timedelta(hours=36)
    """D1: a row first seen more than this after the source's last read lacking it is withheld."""
    sample_step: timedelta = timedelta(minutes=15)
    stamp_window: timedelta = timedelta(hours=36)
    """A row stamp dates its row when it lies this long before the first sighting, or less."""
    board_stamp_window: timedelta = timedelta(hours=18)
    """G5: a board with no row date needs a row stamp at most this old at the first sighting."""
    watched_announce: timedelta | None = timedelta(minutes=15)
    """Owner Q6: a row watched appearing within this (``hi - lo``) is announced at ``hi``;
    ``None`` announces only from a row stamp."""
    big_expansion: int = 150
    """G8: a row reaching this many schools or more needs a strong match."""
    big_expansion_reasons: frozenset[str] = frozenset({"alias", "name"})
    big_expansion_confidence: float = 0.95
    hold_boosted: timedelta = timedelta(minutes=45)
    """G13: a source's statuses stand while its last good read is this recent in a window or
    an alert."""
    hold_quiet: timedelta = timedelta(minutes=90)
    """G13, outside windows and alerts."""
    ufn_school_days: int = 3
    """F14: a status "until further notice" covers at most this many school days."""
    vanish_retracts: bool = False
    """A vanished row retracts its status at once (off: it is kept through its day)."""
    vanished_before_day: timedelta = timedelta(0)
    """A vanished row is not kept for a day that began this long or more after it vanished
    (none by default: a row taken down before its day began is not kept for that day)."""
    fast_vanish: timedelta = timedelta(minutes=60)
    """A row gone from every source that carried it this soon after it appeared is logged."""
    breaker_floor: int = 50
    breaker_factor: int = 3
    breaker_limits: Mapping[str, int] = field(default_factory=dict)
    """Each source's largest archived storm-day count (``live-limits.json``, from S8-G)."""

    def digest(self) -> str:
        """A digest of every threshold and flag, the same in every process.

        Sets and mappings are written in sorted order, never by ``repr``: the order of
        a set of strings changes with each process's hash seed.
        """
        body = {item.name: _plain(getattr(self, item.name)) for item in fields(self)}
        text = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


type _Plain = bool | int | float | str | list["_Plain"] | None


def _plain(value: object) -> _Plain:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, frozenset | set):
        items: list[_Plain] = [str(item) for item in sorted(value, key=str)]
        return items
    if isinstance(value, Mapping):
        return [
            [str(key), _plain(item)]
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        ]
    raise TypeError(f"a rule of type {type(value).__name__} has no canonical form")


# --- wording gates ----------------------------------------------------------------------------

EXTRA_LEARNING: Final = re.compile(
    r"\b(?:flex\w*|digital|learning\s+days?|snow\s+packets?|e[\s-]?learning\s+days?)\b",
    re.IGNORECASE,
)
"""Learning words the replay's list leaves out ("Flexible Learning Day", "Digital Day", "Flex
learning"), read on top of :data:`snowlight.replays.gates.LEARNING_WORDS`."""
CAPS_SAT: Final = re.compile(r"(?<![A-Za-z])SAT(?![A-Za-z])")
"""All-caps "SAT": the test, not Saturday."""
WEEKDAY_NUMBERS: Final = re.compile(
    r"\b(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+(?:the\s+)?\d{1,2}"
    r"(?:st|nd|rd|th)?\s*(?:&|and|,|-|thru|through|to)\s*\d{1,2}(?:st|nd|rd|th)?\b(?!\s*[/:])",
    re.IGNORECASE,
)
"""A weekday followed by bare day numbers ("Monday, 15th & 16th"): which days are meant is not
clear."""
EXTRA_PART: Final = re.compile(
    r"\b(?:intermediate|bus\s+routes?|routes?\s*#?\s*\d+|(?:north|south|east|west)\s+(?:side|end)|"
    r"only)\b",
    re.IGNORECASE,
)
"""Words that narrow a district row on top of :data:`snowlight.replays.build.PART_WORDS`:
intermediate schools, bus routes, a side of the district, "only"."""


def wording_reason(text: str, name: str, *, remote: bool) -> str | None:
    """Why a row's words keep its status from lighting, or ``None``.

    ``text`` is the reader's text (status and comments), ``name`` the row's name and
    ``remote`` whether the reading is remote learning. Every check is read over the
    whole text, whatever days its clauses name: the replay skips a learning word in a
    clause about other days, which lets "Snow packet day, buses resume Wednesday"
    through; live does not.
    """
    if NON_WEATHER_WORDS.search(name) or NON_WEATHER_WORDS.search(text):
        return "planned"
    if not remote and (
        learning_mode(text) or EXTRA_LEARNING.search(text) or LEARNING_WORDS.search(name)
    ):
        return "learning"
    if CAPS_SAT.search(text):
        return "sat"
    if WEEKDAY_NUMBERS.search(text):
        return "weekday_numbers"
    return None


OPEN_SCHEDULE: Final = re.compile(
    r"\b(?:on\s+(?:a\s+|the\s+)?)?(?:normal|regular|usual)\s+(?:school\s+)?"
    r"(?:schedule|hours|day|time)\b",
    re.IGNORECASE,
)
"""The words of an explicit open statement that name the school's own schedule ("Normal
schedule", "Open - normal schedule", "On a regular schedule"): the planned-day words read
them as a schedule of the school's own, which for a row that says only this is the open
statement itself (owner Q8)."""


def open_wording_reason(text: str, name: str) -> str | None:
    """:func:`wording_reason` for a row the reader reads as an explicit open statement and
    nothing else: the same gates, with its own normal-schedule words left out."""
    return wording_reason(OPEN_SCHEDULE.sub(" ", text), name, remote=False)


def names_part(text: str) -> bool:
    """Whether a district row's words name only part of the district."""
    return bool(PART_WORDS.search(text) or EXTRA_PART.search(text))


# --- holds and the breaker --------------------------------------------------------------------


def held(last_good_at: datetime | None, now: datetime, *, boosted: bool, rules: Rules) -> bool:
    """G13: whether a source's statuses still stand at ``now``.

    ``boosted`` is whether the source is in a reading window or an alert.
    """
    if last_good_at is None:
        return False
    limit = rules.hold_boosted if boosted else rules.hold_quiet
    return timedelta(0) <= now - last_good_at <= limit


def breaker_limit(source_id: str, rules: Rules) -> int:
    """G9: the most statuses one source may contribute in a pass."""
    archived = rules.breaker_limits.get(source_id, 0)
    return max(rules.breaker_floor, rules.breaker_factor * archived)


# --- the publish gate (G12), for the publisher ------------------------------------------------

MIN_HEALTHY_SHARE: Final = 0.6
MIN_HEALTHY_RATIO: Final = 0.5
CLOCK_LEEWAY: Final = timedelta(seconds=60)
MAX_GZIP_BYTES: Final = 400 * 1024
SPIKE_RISE: Final = 2000
SPIKE_ALERT_SHARE: Final = 0.5


class Refusal(StrEnum):
    """Why the publish gate refuses an upload (each has its own test, T10a-f)."""

    EDITION = "edition"
    HEALTH = "health"
    NOT_NEWER = "not_newer"
    CLOCK_AHEAD = "clock_ahead"
    OVERSIZE = "oversize"
    SPIKE_HOLD = "spike_hold"
    INVALID = "invalid"
    """The file does not validate against its schema, or does not round-trip (G12d)."""
    UNDECIDED = "undecided"
    """A row the ledger holds as present was never derived and cannot be read again until
    its source is (a pass cut off between reading and resolving): what it says, a
    retraction perhaps, is unknown."""
    HELD = "held"
    """``snowlight live blank`` set the hold: every pass stays dark until ``live release``."""
    OVERRIDES = "overrides"
    """The admin's statuses could not be read (an API error): nothing is published, so a
    status the admin set is never dropped on a blip."""


@dataclass(frozen=True, slots=True)
class GateInput:
    """What the gate reads for one pass."""

    edition_ok: bool
    healthy_share: float
    """Share of the sources due in the last 15 minutes that read ok, not modified or empty."""
    previous_healthy_share: float | None
    generated_at: datetime
    last_published: datetime | None
    """The newest ``generated_at`` published: read back from the public file, then remembered."""
    now: datetime
    gzip_bytes: int
    spike: bool = False
    """The spike hold holds this pass (:func:`spike_hold`)."""
    valid: bool = True
    """The file validated and round-tripped through its schema (G12d)."""
    undecided: int = 0
    """Present rows never derived, of sources not yet read again (:attr:`Refusal.UNDECIDED`)."""


def gate_refusals(check: GateInput) -> list[Refusal]:
    """G12: every reason the gate refuses this pass, in order; empty means publish."""
    refusals: list[Refusal] = []
    if not check.edition_ok:
        refusals.append(Refusal.EDITION)
    previous = check.previous_healthy_share
    if check.healthy_share < MIN_HEALTHY_SHARE or (
        previous is not None and check.healthy_share < MIN_HEALTHY_RATIO * previous
    ):
        refusals.append(Refusal.HEALTH)
    if check.last_published is not None and check.generated_at <= check.last_published:
        refusals.append(Refusal.NOT_NEWER)
    if check.generated_at > check.now + CLOCK_LEEWAY:
        refusals.append(Refusal.CLOCK_AHEAD)
    if check.gzip_bytes > MAX_GZIP_BYTES:
        refusals.append(Refusal.OVERSIZE)
    if check.spike:
        refusals.append(Refusal.SPIKE_HOLD)
    if not check.valid:
        refusals.append(Refusal.INVALID)
    if check.undecided:
        refusals.append(Refusal.UNDECIDED)
    return refusals


@dataclass(frozen=True, slots=True)
class SpikeState:
    """A spike held once, waiting for the same rows on the next good read."""

    rows: frozenset[tuple[int, str]]
    """The newly lit (school, ISO day) pairs that were held."""


def spike_hold(
    *,
    lit_before: int,
    lit_now: int,
    new_rows: frozenset[tuple[int, str]],
    alert_share: float,
    pending: SpikeState | None,
) -> tuple[bool, SpikeState | None]:
    """G12e: whether to hold this pass, and the state to keep for the next.

    Today's lit count rising by more than :data:`SPIKE_RISE` while fewer than
    :data:`SPIKE_ALERT_SHARE` of the newly lit schools' counties have an active alert
    holds the pass once. The next pass publishes when it holds the same new rows (or
    more); otherwise it holds again with its own rows.
    """
    if lit_now - lit_before <= SPIKE_RISE or alert_share >= SPIKE_ALERT_SHARE:
        return False, None
    if pending is not None and pending.rows <= new_rows:
        return False, None
    return True, SpikeState(rows=new_rows)

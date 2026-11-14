"""Each district's own record: one row per district and live school morning (each-school
P2a1; docs/predict.md, "Each district's own record").

The owner's ruling: each district's own record (whether it tends to close early or hold out)
is the spine of the prediction. This module starts writing that record from every live
morning. **It changes no number**: nothing that learns or serves reads it (no pass, no refit,
no published file), and it writes only ``out/internal/predict/record.parquet`` (internal,
never published) and the evidence store's ``record`` kind.

**Inputs of a day D** (all read only):

* the outcome-blind live labels' day, ``reads/rows/<D>.json``
  (:class:`~snowlight.predict.live_read.ReadDay`, the predict chain's ``predict-reads-``
  cache): every alerted district's class at the snapshot, its label and how it was read, and
  every district the map lit no school (the next school day's ``after``);
* the day's timeline, ``live/days/<D>.json`` on the live host, final: each school's status
  as the map showed it at the read window's end (``labels.read_until``, 09:30 local) and the
  reason it named. The morning's call is read there, not at the day's last change: lists
  clear their rows in the afternoon (on Nov 4 2026 every one of the 27 statuses of the day
  was taken back after 13:00 local), and a status taken back before 09:30 counts as none.
  Reasons are read raw: a stated cause that is not the weather is kept as its code here
  (the prediction's loaders read it as dark, and this record never feeds them). The host
  holding no timeline of a day means the map lit nothing that day only once its day index,
  written after the day was over everywhere, does not list it (labels' own rule,
  ``live_labels.day_ready``); else the day waits;
* the previous school day's timeline, at 09:30 and at its last change (each row's ``after``);
* the deployed directory: each district's eligible schools (public, not charter, not fully
  virtual, else all of them: the serving pass's rule), on the same content the read day and
  the timeline name; another directory's day is skipped, never guessed.

**The rows.** A district gets a row on D when either:

* its read row is labeled ``no_school`` or ``delayed``, or ``unnamed`` while the map lit none
  of its eligible schools with a morning call at 09:30 or later that day: a **live read** row,
  ``source_complete`` true and ``closings_only`` false (a whole, healthy, fresh read of a list
  that carries it decided the label before any outcome was looked at). ``unnamed`` stays
  ``unnamed`` (the owner's O5 counts it open, but a list misses closings at its sensitivity,
  so it is never written ``open``);
* or else the map lit at least one of its eligible schools closed, remote or delayed at
  09:30, for any reason or none: a **live map** row, ``source_complete`` false and
  ``closings_only`` true (the map shows what lists named; a district it did not light is not
  known open). This is every no-alert closing, every closing of a district no list read
  whole, every closing for a stated cause that is not the weather, and a district a read
  called ``unnamed`` while the map lit it (a status labels read as dark, such as a code
  above 7, or one taken back later): its read label is kept in ``read``. A district the map
  lit only after 09:30 gets a live map row too, its call from the day's last change,
  ``agrees`` false and never a weather day (posted late, the morning view does not show it).

**The call of a read row** is the 09:30 map's call by the label rule (as for a map row,
below) when that call is of the label's kind (no school, or delayed) and whole: ``agrees``
true. Otherwise (the district was posted after 09:30, or its call changed later) the row
keeps the label's kind of call, ``agrees`` is false, ``lit``, ``cause`` and ``reasons`` come
from the schools lit with that call at the day's last change (the view the label was read
from), and it is never a weather day: the morning view does not show the weather making the
call. ``remote`` when every school lit no school was lit remote, else ``closed``. Every row
carries ``map_call``, the call the 09:30 map makes for any reason and of any scope (``None``:
it lit nothing), so a row that does not agree shows both.

Every row carries its class that morning (``advisory``, ``warning``, ``cold``, ``none``, or
``unknown`` when the read day holds unclassed districts and this one has no row there), two
day-after flags (``None``: not known), its cause, ``closings_only``, ``scope`` and
``source_complete``:

* ``after``: on the previous school day the map lit no school (closed or remote, for any
  reason or none) at at least ``no_school_share`` of its eligible schools at 09:30 or at that
  day's last change (a closing posted after 09:30 included), or its read row that day was
  labeled ``no_school`` (that day's record row is a no-school call), or ``after_weather`` is
  true: a closing for the weather is a closing. This is the day-after flag a page filters on
  (spec rule 10); :class:`RecordRow` refuses ``after_weather`` true with ``after`` not true;
* ``after_weather``: labels.py's day-after flag, the one the prediction's situations use: the
  map lit it no school *for the weather* on the previous school day (its read row's
  ``after``, else the previous read day's ``no_school``). ``situation`` is made from it, and
  is ``None`` when it is not known and the class has an after situation.

**Cause and weather days** (owner ruling, Nov 13: every real closing is shown with its
reason, but the snow-day prediction never learns from non-weather closings).
A school's reasons are read at every change of the day with a morning call, not only at
09:30: a status that names no reason at 07:00 and a power outage at 10:00 was a closing for a
power outage. ``cause`` is ``named``, and ``weather_day`` false, when any of the district's
eligible schools names a cause that is not the weather (heat, a power outage, or any code
above 7) with a morning call at any change of the day.
Otherwise ``weather_day`` is true only when the schools lit for the weather by labels.py's
rule (:func:`~snowlight.predict.labels.weather_positive`: a named weather reason, or no
reason named on an alerted morning) reach the call at 09:30 by the label rule's shares on
their own; ``cause`` is then ``weather`` (a weather reason named) or ``any`` (none named).
Else ``cause`` is ``weather`` when only weather reasons are named (a tropical reason on a day
that is not tropical), else ``any``, and ``weather_day`` is false. ``reasons`` keeps every
code the district's eligible schools named with a morning call at any change of the day, so
a page can say why.
:class:`RecordRow` refuses a weather day with a ``named`` cause, with nothing lit, with no
morning call, or that does not agree.

**Scope.** ``whole`` when the label rule's shares give the call (at least
``no_school_share`` of the eligible schools lit no school, or ``delayed_share`` delayed);
``share`` when fewer were lit (``lit`` of ``eligible``). A live read row is always ``whole``.

**Fit use.** ``weather_day`` is not a fit filter. ``fit_usable`` is the one flag a later fit
may filter on, and only as far as these rows can say (the spec's rules 6, 6b, 10 and 13; a
held-out check and the hand audit come on top): ``source_complete``, scope ``whole``,
``agrees``, no ``named`` cause, not ``tropical``, ``after`` false and ``after_weather`` not
true, nothing ``taken_back``, and a weather day or ``unnamed``. :class:`RecordRow` refuses a
row whose ``fit_usable`` is not exactly that. Take-back days and rows
(``learn.excluded_days``, ``learn.excluded_rows``) are kept in the evidence store, which is
append-only, and left out of ``record.parquet`` (:func:`kept_rows`).

Codes, ids, counts and times only: no name, no URL and no list text. A read row's market is
kept as a code (:func:`market_code`), never its name. Each day's bytes are checked before
they are offered (:func:`day_bytes`), and the evidence writer checks again.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Literal, Protocol, Self

import numpy as np
import numpy.typing as npt
import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

from snowlight.directory.points import Points
from snowlight.output import write_bytes_atomic
from snowlight.predict.calendar import previous_school_day
from snowlight.predict.config import PIPELINE_ROOT, LabelSettings, LearnSettings
from snowlight.predict.exposure import CLASS_OF_WEATHER
from snowlight.predict.labels import (
    NO_SCHOOL,
    TROPICAL_REASONS,
    WEATHER_REASONS,
    LitStatus,
    Outcome,
    Shares,
    outcome_of,
    shares,
    weather_positive,
)
from snowlight.predict.live_read import UNCLASSED, Label, ReadDay, ReadRow
from snowlight.predict.serve import CHARTER, PRIVATE, VIRTUAL
from snowlight.predict.situations import AFTER_CLASSES, Situation, WeatherClass
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import DayIndex, DayTimeline
from snowlight.schemas.vocab import Reason, Status

RECORD_VERSION: Final = 1
"""The row format's version (the parser version of the spec's record row)."""
RECORD_PATH: Final = PIPELINE_ROOT / "out" / "internal" / "predict" / "record.parquet"
"""Every record day the evidence store holds, as one table (internal, never published)."""
DAYS_PER_RUN: Final = 10
"""The most new days one run writes (the newest first); the rest wait for the next run."""
NO_DISTRICT: Final = 0xFFFFFFFF
"""``points.bin``'s district index of a school with no district (a private school)."""
CALLED: Final = frozenset({Status.CLOSED, Status.REMOTE, Status.DELAYED})
"""The statuses a morning call is made of (an early dismissal is not a morning call)."""
SAFE: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.:")
"""The only characters a string of a record row may hold (codes, ids, dates, times)."""
MAX_TEXT: Final = 64
"""The longest string a record row may hold."""


class Call(StrEnum):
    """What a district did on the morning, as its source says it (spec section 3)."""

    CLOSED = "closed"
    REMOTE = "remote"
    DELAYED = "delayed"
    OPEN = "open"
    """A list carrying it was read whole and did not name it, by labels.py's archive rule
    (archived lists; never written from a live read)."""
    UNNAMED = "unnamed"
    """An outcome-blind live read did not name it (or a list carrying it was read, not
    whole)."""
    CLOSED_OR_DELAYED = "closed_or_delayed"
    SAID_OPEN = "said_open"


NO_SCHOOL_CALLS: Final = frozenset({Call.CLOSED, Call.REMOTE})
MORNING_CALLS: Final = frozenset({Call.CLOSED, Call.REMOTE, Call.DELAYED})


class Cause(StrEnum):
    """What the source says the call was for."""

    WEATHER = "weather"
    """A weather reason is named (labels.py's weather reasons)."""
    ANY = "any"
    """No reason is named."""
    NAMED = "named"
    """A cause that is not the weather is named (heat, a power outage, any code above 7)."""


class Scope(StrEnum):
    """How much of the district the call covers."""

    WHOLE = "whole"
    """The label rule's shares give the call for the district."""
    SHARE = "share"
    """Fewer of its eligible schools than that (``lit`` of ``eligible``)."""
    UNKNOWN = "unknown"


class SourceKind(StrEnum):
    """Where a row's call comes from."""

    LIVE_READ = "live_read"
    """The outcome-blind live labels (advisory-sane L1)."""
    LIVE_MAP = "live_map"
    """What the live map lit, with no read deciding it (closings only)."""
    PAST_RECORDS = "past_records"
    """A public state record of past school days (each-school P2d,
    :mod:`snowlight.predict.state_records`): the coarse kind a page may say (LR8: seen live by
    us, or from past records), never the agency's name. Rows of this kind are
    :class:`PastDay` and :class:`YearCount`, never :class:`RecordRow`."""


type ClassKey = Literal["advisory", "warning", "cold", "none", "unknown"]


class RecordError(ValueError):
    """A record day that must not be written."""


class RecordRow(BaseModel):
    """One district's row of one live school morning (codes, ids, counts and times only)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    version: int = Field(ge=1)
    day: date
    unit: str = Field(pattern=r"^\d{7}$")
    """The district's LEAID."""
    weather: int | None = Field(ge=0, le=7)
    """Its weather class at the read day's snapshot (:class:`WeatherClass`); ``None``: the
    read day does not know it (it holds unclassed districts and this one is not alerted)."""
    klass: ClassKey
    """``advisory``, ``warning`` (warning-or-above and tropical: the serving classes,
    ``exposure.CLASS_OF_WEATHER``), ``cold``, ``none``, or ``unknown``."""
    after: bool | None
    """The day-after flag, true to the map: on its previous school day the map lit no school
    (closed or remote, any reason or none) at at least the no-school share of its eligible
    schools at 09:30 (``None``: what the map showed that day is not known)."""
    after_weather: bool | None
    """labels.py's day-after flag (the situations' input): the map lit it no school *for the
    weather* on its previous school day (``None``: not known)."""
    situation: str | None
    """Its situation (``advisory_after``) from ``after_weather``; ``None`` when its class is
    not known, or ``after_weather`` is not known and the class has an after situation."""
    call: Call
    source_kind: SourceKind
    source_complete: bool
    """A source that would have shown an open district as open (a whole outcome-blind read)."""
    closings_only: bool
    """The source lists only closings, so its silence is not an open day."""
    scope: Scope
    cause: Cause
    weather_day: bool
    """It counts as a weather closing or delay (see the module); never for a stated cause that
    is not the weather. Not a fit filter: see ``fit_usable``."""
    agrees: bool
    """The 09:30 map makes the row's call (always, but for a read row whose label the morning
    view does not give, and a map row posted only after 09:30: see the module)."""
    map_call: Call | None
    """The call the 09:30 map makes by the label rule, for any reason and of any scope
    (``None``: it lit none of the district's eligible schools with a morning call at 09:30),
    so a row that does not agree shows both."""
    taken_back: bool
    """A school lit with a morning call at any change of the day (at 09:30 or not) shows no
    status at the day's last change."""
    fit_usable: bool
    """The one flag a later fit may filter on (see the module): complete, whole, agreeing, no
    named cause, not tropical, not a day after, nothing taken back, a weather day or
    unnamed."""
    reasons: tuple[int, ...]
    """Every reason code its eligible schools named with a morning call at any change of the
    day, sorted."""
    eligible: int = Field(ge=0)
    """Its eligible schools (``n_i``)."""
    lit: int = Field(ge=0)
    """Of them, those lit with the row's call (a no-school call counts closed and remote)."""
    tropical: bool
    """A tropical class or a tropical reason: kept, never in a winter fit."""
    read: str | None
    """Its read row's label when that row does not decide the call (``unknown``,
    ``not_read``, or ``unnamed`` while the map lit it), else ``None``."""
    why: str | None
    """Why that read row did not decide it (its ``why``)."""
    tier: str | None
    market: str | None
    """Its read row's market as a code (:func:`market_code`), never the market's name."""
    sources: tuple[str, ...]
    """The lists that read it (ids)."""
    slot: str | None
    """The first qualifying 30-minute slot's UTC start, ``HH:MM``."""

    @model_validator(mode="after")
    def _honest(self) -> Self:
        """A weather day names no other cause, lights a school with a morning call and agrees
        with the map; ``fit_usable`` is exactly the module's rule."""
        if self.source_kind not in LIVE_KINDS:
            raise ValueError(f"{self.day} {self.unit}: a live row of the past records' kind")
        if self.weather_day and (
            self.cause is Cause.NAMED
            or self.lit == 0
            or self.call not in MORNING_CALLS
            or not self.agrees
        ):
            raise ValueError(f"{self.day} {self.unit}: a weather day it cannot be")
        if self.after_weather is True and self.after is not True:
            raise ValueError(f"{self.day} {self.unit}: a day after a weather closing it cannot be")
        if self.agrees and self.map_call != (self.call if self.call in MORNING_CALLS else None):
            raise ValueError(f"{self.day} {self.unit}: a call the 09:30 map does not make")
        if self.fit_usable != fit_rule({name: getattr(self, name) for name in FIT_FIELDS}):
            raise ValueError(f"{self.day} {self.unit}: fit_usable is not the module's rule")
        return self


FIT_FIELDS: Final = (
    "source_complete", "scope", "agrees", "cause", "tropical", "after", "after_weather",
    "taken_back", "call", "weather_day",
)  # fmt: skip
"""The fields ``fit_usable`` is made of."""


def fit_rule(fields: Mapping[str, Any]) -> bool:
    """Whether a row with these :data:`FIT_FIELDS` may reach a fit as far as the record's rows
    can say (see the module)."""
    return bool(
        fields["source_complete"]
        and Scope(fields["scope"]) is Scope.WHOLE
        and fields["agrees"]
        and Cause(fields["cause"]) is not Cause.NAMED
        and not fields["tropical"]
        and fields["after"] is False
        and fields["after_weather"] is not True
        and not fields["taken_back"]
        and (fields["weather_day"] or Call(fields["call"]) is Call.UNNAMED)
    )


LIVE_KINDS: Final = frozenset({SourceKind.LIVE_READ, SourceKind.LIVE_MAP})
"""The kinds a :class:`RecordRow` (a live morning) may carry: seen live by us."""


class PastDay(BaseModel):
    """One district's dated day from a public state record of past school days (each-school
    P2d; :mod:`snowlight.predict.state_records`). Codes, ids and dates only.

    The internal field names ``source_kind``, ``source_complete`` and ``sources`` follow
    :class:`RecordRow`'s. They stay in the evidence store and the internal ``record.parquet``
    (neither is published); the published shard (P2e) maps them to its coarse two-value
    ``seen`` field (seen live by us, or from past records) and never carries these names (LR8).

    Unlike a live row it has no 09:30 map, no read and no schools counted, so it carries none
    of those fields (``record.parquet`` holds them empty for it). ``code`` is the state's own
    calendar code (Kentucky's ``W``, a weather day), mapped to ``call`` and ``cause`` by the
    written map in ``config/state-records.yaml``; a day of a weather code that the config's
    written ``not_weather`` list names (a closing the state listed under its weather code for
    another cause, such as a water main break) keeps the state's code but has cause ``named``
    and is never a weather day (LR12); one its written ``unconfirmed`` list names (a day the
    review could not tie to the weather) keeps the code with cause ``any`` and is never a
    weather day either. Its class that morning is ``unknown`` until a
    backfill or P2a2 fills it (LR14): such a row is counted and shown as unknown, and never
    fit-usable."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    version: int = Field(ge=1)
    day: date
    unit: str = Field(pattern=r"^\d{7}$")
    """The district's LEAID (the state's id joined by the written id rule, never guessed)."""
    weather: int | None = Field(ge=0, le=7)
    klass: ClassKey
    after: bool | None
    """On its previous scheduled school day (its own calendar in the same file) the source
    lists a day it did not hold school (``True``); ``None`` when that day is not known to be
    one (an at-home NTI day is not dated, so a day the source does not list is not known to
    be a school day held)."""
    after_weather: bool | None
    """That previous day was listed for the weather (``True``) or for another named cause
    (``False``); ``None``: not known."""
    situation: str | None
    call: Call
    source_kind: SourceKind
    source_complete: bool
    closings_only: bool
    scope: Scope
    cause: Cause
    weather_day: bool
    """The state's code names the weather (see ``code``); never for another named cause."""
    fit_usable: bool
    """Always the rule of :func:`past_fit_rule` (false for every closings-only source and
    every row whose class is not known)."""
    reasons: tuple[int, ...]
    tropical: bool | None
    """``None`` while the class is not known."""
    sources: tuple[str, ...]
    """The state file it was read from (its id in ``config/state-records.yaml``, never a URL
    or an agency's name)."""
    code: str = Field(min_length=1, max_length=16)
    """The state's calendar code for the day (``W``)."""

    @model_validator(mode="after")
    def _honest(self) -> Self:
        """A past record row is of the past-records kind; a closings-only source is never
        complete and never says open; an unknown class knows no situation; a weather day
        names no other cause; ``fit_usable`` is exactly :func:`past_fit_rule`."""
        where = f"{self.day} {self.unit}"
        if self.source_kind is not SourceKind.PAST_RECORDS:
            raise ValueError(f"{where}: a past record row of a live kind")
        if self.closings_only and (
            self.source_complete or self.call in {Call.OPEN, Call.UNNAMED, Call.SAID_OPEN}
        ):
            raise ValueError(f"{where}: a closings-only source cannot be complete or say open")
        if self.klass == "unknown" and (
            self.weather is not None or self.situation is not None or self.tropical is not None
        ):
            raise ValueError(f"{where}: an unknown class with a weather class, situation or flag")
        if self.weather_day and (self.cause is Cause.NAMED or self.call not in MORNING_CALLS):
            raise ValueError(f"{where}: a weather day it cannot be")
        if self.after_weather is not None and self.after is not True:
            raise ValueError(f"{where}: a day-after cause with no day after")
        if self.fit_usable != past_fit_rule(self):
            raise ValueError(f"{where}: fit_usable is not the past rows' rule")
        return self


def past_fit_rule(row: "PastDay") -> bool:
    """Whether a past record row may reach a fit as far as the row can say (spec rules 6, 6b,
    8, 10 and 13; a held-out check and the hand audit come on top): a complete source, whole
    scope, no named cause, a weather day, a known class that is not tropical, and not a day
    after a closing. Closings-only sources (Kentucky's dated weather days) never are (rule 6;
    rule 9's statewide slope is a serving piece's own filter, never this flag)."""
    return bool(
        row.source_complete
        and not row.closings_only
        and row.scope is Scope.WHOLE
        and row.cause is not Cause.NAMED
        and row.weather_day
        and row.klass != "unknown"
        and row.tropical is False
        and row.after is False
        and row.after_weather is not True
    )


class YearCount(BaseModel):
    """One district's count of one kind of day in one school year, from a public state
    record (each-school P2d). Kept as a count: never spread into dates (spec rule 9).

    ``days`` is the state's own number. For Kentucky's ``W`` it counts the weather days the
    district **made up**: a weather day not made up is removed from the amended calendar, so
    it is not a count of weather closings, and the state's weather code can carry a
    non-weather emergency. ``not_weather`` is how many of ``days`` the config's written
    ``not_weather`` list names as another cause, and ``unconfirmed`` how many its written
    ``unconfirmed`` list names (a day the review could not tie to the weather), so the weather
    days known are ``days - not_weather - unconfirmed``. An undated count (the trend's years)
    cannot be checked: both are ``None`` there, never ``0``. Internal field names as
    :class:`PastDay`'s (P2e maps them, LR8)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    version: int = Field(ge=1)
    unit: str = Field(pattern=r"^\d{7}$")
    year: str = Field(pattern=r"^\d{4}-\d{2}$")
    """The school year, ``2024-25``."""
    code: str = Field(min_length=1, max_length=16)
    """The state's calendar code counted (Kentucky: ``W`` weather days, ``N`` at-home NTI
    days, ``I`` days closed for illness, ``D`` district-wide emergency days)."""
    days: int = Field(ge=0)
    """The state's own count."""
    not_weather: int | None = Field(ge=0)
    """Of ``days``, those the written ``not_weather`` list names as another cause (``0`` for a
    code that is not the weather's); ``None`` where the days are not dated and cannot be
    checked."""
    unconfirmed: int | None = Field(ge=0)
    """Of ``days``, those the written ``unconfirmed`` list names: kept, never weather days;
    ``None`` where the days are not dated and cannot be checked."""
    source_kind: SourceKind
    sources: tuple[str, ...]
    """The state file it was read from (its id)."""
    covid: bool
    """A COVID year (2019-20, 2020-21): kept, never in a count fit (spec rule 9)."""
    disaster: bool | None
    """The district had a district-wide emergency day that year (kept and flagged, never in a
    winter fit: spec rule 8); ``None`` where the file does not say."""

    @model_validator(mode="after")
    def _kind(self) -> Self:
        if self.source_kind is not SourceKind.PAST_RECORDS:
            raise ValueError(f"{self.year} {self.unit}: a year count of a live kind")
        if (self.not_weather is None) != (self.unconfirmed is None):
            raise ValueError(f"{self.year} {self.unit}: checked for one cause and not the other")
        if (self.not_weather or 0) + (self.unconfirmed or 0) > self.days:
            raise ValueError(f"{self.year} {self.unit}: more days not the weather than counted")
        return self


PAST_PREFIX: Final = "past/"
"""The record kind's keys of past records: ``past/<file id>/v<edition>/days``
(:class:`PastDay` lines) and ``past/<file id>/v<edition>/counts`` (:class:`YearCount` lines).
A live day's key is its ISO date. The record is append-only and a key is written once, so a
reviewed change to a file's rows (a parser, map or exception fix) bumps the file's
``edition`` in ``config/state-records.yaml`` and writes new keys; :func:`kept_rows` and
:func:`kept_counts` read only each file's newest edition."""
PAST_DAYS: Final = "days"
PAST_COUNTS: Final = "counts"
PAST_KEY: Final = re.compile(r"past/([a-z]{2}-[a-z0-9-]{1,40})/v([1-9]\d{0,3})/(days|counts)")


def past_key(file_id: str, edition: int, kind: str) -> str:
    """A past record key (:data:`PAST_PREFIX`)."""
    return f"{PAST_PREFIX}{file_id}/v{edition}/{kind}"


COUNTS_NAME: Final = "record-counts.parquet"
"""The past records' yearly counts, beside ``record.parquet`` (internal, never published)."""


def market_code(market: str | None) -> str | None:
    """A market as the record keeps it: ``m`` and the first 12 hex digits of the sha256 of the
    registry's market text (config maps it back), never the text itself."""
    if market is None:
        return None
    return "m" + hashlib.sha256(market.encode()).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class Units:
    """The deployed directory as the record needs it: each district's eligible schools."""

    districts: tuple[str, ...]
    eligible: tuple[npt.NDArray[np.int64], ...]
    content: str
    """What names the directory's indexes (``learn.content_key``)."""
    stamp: DirectoryStamp
    digest: str | None

    def indexes(self, timeline: DayTimeline) -> bool:
        """Whether ``timeline``'s school indexes are this directory's: the same content digest
        when both name one (the content is what names the indexes, ``learn.content_key``;
        two builds of one content may carry two stamps), else the same stamp."""
        theirs = timeline.content_sha256
        if self.digest is not None and theirs is not None:
            return theirs == self.digest
        return timeline.directory == self.stamp


def eligible_schools(points: Points, districts: int) -> tuple[npt.NDArray[np.int64], ...]:
    """Each district's eligible schools: those not private, charter or fully virtual, else
    all of them (the serving pass's rule, ``serve.build_model``)."""
    district = points.district.astype(np.int64)
    open_flags = (points.kind & (PRIVATE | CHARTER | VIRTUAL)) == 0
    order = np.argsort(district, kind="stable")
    ordered = district[order]
    found: list[npt.NDArray[np.int64]] = []
    for index in range(districts):
        low = int(np.searchsorted(ordered, index, side="left"))
        high = int(np.searchsorted(ordered, index, side="right"))
        mine = np.sort(order[low:high]).astype(np.int64)
        chosen = mine[open_flags[mine]] if mine.size else mine
        found.append(chosen if chosen.size else mine)
    return tuple(found)


def units_of(directory: Any) -> Units:
    """The record's view of a deployed directory
    (:class:`~snowlight.predict.serve.DeployedDirectory`)."""
    from snowlight.predict.learn import content_key  # noqa: PLC0415 - the serving stack

    return Units(
        districts=tuple(directory.district_ids),
        eligible=eligible_schools(directory.points, len(directory.district_ids)),
        content=content_key(directory),
        stamp=directory.stamp,
        digest=directory.content_sha256,
    )


@dataclass(frozen=True, slots=True)
class Shown:
    """A school's last shown status of a view and the reason code it named, raw (a code above
    7 is kept), with every code it named with a morning call at any change of the day."""

    status: Status
    reason: int | None
    codes: frozenset[int] = frozenset()
    """Every reason code the school named with a morning call (closed, remote or delayed) at
    any change of the day, before the view's minute or after it: a cause stated later is the
    cause of the morning's call too."""

    def lit(self) -> LitStatus:
        """As labels.py reads it: a code that is not a named reason reads as none."""
        named = self.reason if self.reason is not None and self.reason in _REASON_CODES else None
        return LitStatus(self.status, None if named is None else Reason(named))

    def named(self) -> frozenset[int]:
        """The view's code and the day's codes."""
        return self.codes if self.reason is None else self.codes | {self.reason}

    def stated(self) -> bool:
        """It names a cause that is not the weather (heat, a power outage, a code above 7) in
        the view or at any change of the day with a morning call."""
        return bool(self.named() - _WEATHER_CODES)


_REASON_CODES: Final = frozenset(int(r) for r in Reason)
_WEATHER_CODES: Final = frozenset(int(r) for r in WEATHER_REASONS)
_TROPICAL_CODES: Final = frozenset(int(r) for r in TROPICAL_REASONS)


def _weather_lit(found: Shown, weather: WeatherClass) -> bool:
    """Whether a school counts as lit for the weather (labels.py's rule) in the view and at
    every change of the day with a morning call: a stated cause that is not the weather (a
    code that is not a named reason included) at any of them is never weather."""
    if found.stated() or not weather_positive(found.lit(), weather):
        return False
    return all(weather_positive(LitStatus(found.status, Reason(c)), weather) for c in found.codes)


def shown_of(timeline: DayTimeline | None, until: int | None = None) -> dict[int, Shown]:
    """Each school's status on the timeline's day with its raw reason code: the last change
    before minute ``until`` of the day (local; ``None``: the day's last change), with every
    code it named with a morning call at any change of the day (:attr:`Shown.codes`). A school
    showing none then (not yet lit, or taken back) is left out."""
    if timeline is None:
        return {}
    found: dict[int, Shown] = {}
    start = 0
    for school, count in zip(timeline.schools(), timeline.counts, strict=True):
        last = None
        codes: set[int] = set()
        for position in range(start, start + count):
            if until is None or timeline.minutes[position] < until:
                last = position
            status, code = timeline.statuses[position], timeline.reasons[position]
            if status is not None and Status(status) in CALLED and code is not None:
                codes.add(code)
        if last is not None and (status := timeline.statuses[last]) is not None:
            found[school] = Shown(Status(status), timeline.reasons[last], frozenset(codes))
        start += count
    return found


def morning_end(rule: LabelSettings) -> int:
    """The minute of the day the morning's call is read at: the read window's end."""
    return rule.read_until.hour * 60 + rule.read_until.minute


def class_key(weather: WeatherClass | None) -> ClassKey:
    """A class as the record names it."""
    if weather is None:
        return "unknown"
    if weather is WeatherClass.NONE:
        return "none"
    key = CLASS_OF_WEATHER[int(weather)]
    if key == "advisory":
        return "advisory"
    if key == "cold":
        return "cold"
    return "warning"


def _cause(codes: Iterable[int | None]) -> Cause:
    """A cause from the reason codes of the schools that make a call."""
    named = {code for code in codes if code is not None}
    if named - _WEATHER_CODES:
        return Cause.NAMED
    return Cause.WEATHER if named else Cause.ANY


def _no_school_call(schools: Sequence[Shown]) -> Call:
    """``remote`` when every school lit no school was lit remote, else ``closed``."""
    lit = [s for s in schools if s.status in NO_SCHOOL]
    return Call.REMOTE if lit and all(s.status is Status.REMOTE for s in lit) else Call.CLOSED


@dataclass(frozen=True, slots=True)
class _Read:
    """A morning's call by the label rule, from what the map showed."""

    call: Call | None
    scope: Scope
    cause: Cause
    weather_day: bool
    lit: int


def _of(
    eligible: Sequence[str],
    shown: Mapping[str, Shown],
    weather: WeatherClass,
    rule: LabelSettings,
    *,
    stated: bool = False,
) -> _Read:
    """The call the map makes for a district (see the module): first the schools lit for the
    weather alone, then every school lit with a morning call. ``stated``: a school of the
    district lit with a morning call names a cause that is not the weather that day (then
    the cause is ``named`` and it is no weather day)."""
    stated = stated or any(f.stated() for f in shown.values())
    statuses = {s: found.lit() for s, found in shown.items() if _weather_lit(found, weather)}
    by_weather = shares(eligible, statuses, weather)
    told = outcome_of(by_weather, read=False, settings=rule)
    if not stated and told in (Outcome.NO_SCHOOL, Outcome.DELAYED):
        mine = [
            found
            for s, found in shown.items()
            if s in statuses and (found.status in NO_SCHOOL) == (told is Outcome.NO_SCHOOL)
        ]
        call = _no_school_call(mine) if told is Outcome.NO_SCHOOL else Call.DELAYED
        return _Read(call, Scope.WHOLE, _cause(_codes(mine)), True, len(mine))
    total = len(eligible)
    closed = [found for found in shown.values() if found.status in NO_SCHOOL]
    delayed = [found for found in shown.values() if found.status is Status.DELAYED]
    if not closed and not delayed:
        return _Read(None, Scope.UNKNOWN, Cause.ANY, False, 0)
    every = Shares(len(closed) / total, len(delayed) / total, len(shown) / total)
    found = outcome_of(every, read=False, settings=rule)
    if found is Outcome.NO_SCHOOL or (found is not Outcome.DELAYED and closed):
        mine = closed
        call = _no_school_call(mine)
    else:
        mine = delayed
        call = Call.DELAYED
    scope = Scope.WHOLE if found in (Outcome.NO_SCHOOL, Outcome.DELAYED) else Scope.SHARE
    cause = Cause.NAMED if stated else _cause(_codes(mine))
    return _Read(call, scope, cause, False, len(mine))


def _codes(view: Iterable[Shown] | Mapping[str, Shown]) -> tuple[int, ...]:
    """Every code the view's schools named, in the view or with a morning call at any change
    of the day, sorted."""
    found: set[int] = set()
    for f in view.values() if isinstance(view, Mapping) else view:
        found |= f.named()
    return tuple(sorted(found))


def called_today(timeline: DayTimeline | None) -> dict[int, frozenset[int]]:
    """Each school the timeline lit with a morning call at any change of its day, and every
    reason code it named with one."""
    if timeline is None:
        return {}
    found: dict[int, frozenset[int]] = {}
    start = 0
    for school, count in zip(timeline.schools(), timeline.counts, strict=True):
        codes: set[int] = set()
        lit = False
        for position in range(start, start + count):
            status = timeline.statuses[position]
            if status is not None and Status(status) in CALLED:
                lit = True
                if (code := timeline.reasons[position]) is not None:
                    codes.add(code)
        if lit:
            found[school] = frozenset(codes)
        start += count
    return found


def _tropical(weather: WeatherClass | None, codes: Iterable[int]) -> bool:
    return weather is WeatherClass.TROPICAL or any(code in _TROPICAL_CODES for code in codes)


@dataclass(frozen=True, slots=True)
class Previous:
    """What the map showed on the previous school day (each row's ``after``)."""

    day: date
    timeline: DayTimeline | None
    """``None``: the map lit nothing that day (the host's index says so)."""


@dataclass(frozen=True, slots=True)
class RecordDay:
    """One day's inputs."""

    day: date
    read: ReadDay
    timeline: DayTimeline | None
    """``None``: the map lit nothing that day (the host's index says so)."""
    before: ReadDay | None = None
    """The read day of the previous school day, when the record holds it (each district's
    ``after_weather`` when it has no read row)."""
    previous: Previous | None = None
    """The previous school day's map; ``None``: not known (each row's ``after`` is ``None``)."""


def no_school_units(
    timeline: DayTimeline | None, units: Units, rule: LabelSettings
) -> frozenset[int]:
    """The district positions the map lit no school (closed or remote, any reason or none, at
    at least ``no_school_share`` of their eligible schools) at 09:30 or at the day's last
    change (a closing posted after 09:30 is a closing too)."""
    owner = _owners(units)
    found: set[int] = set()
    for until in (morning_end(rule), None):
        lit: dict[int, int] = {}
        for school, shown in shown_of(timeline, until).items():
            if shown.status in NO_SCHOOL and school in owner:
                lit[owner[school]] = lit.get(owner[school], 0) + 1
        found |= {
            index
            for index, count in lit.items()
            if count / len(units.eligible[index]) >= rule.no_school_share
        }
    return frozenset(found)


def record_rows(found: RecordDay, units: Units, rule: LabelSettings) -> list[RecordRow]:
    """One day's record rows, sorted by district (see the module).

    Raises:
        RecordError: the read day or the timeline is not this directory's, or names another
            day.
    """
    day, read = found.day, found.read
    if read.day != day:
        raise RecordError(f"{day}: the read day names {read.day}")
    if read.content != units.content:
        raise RecordError(f"{day}: the read day is of another directory")
    timeline = found.timeline
    if timeline is not None and (timeline.day != day or not units.indexes(timeline)):
        raise RecordError(f"{day}: the timeline is not this directory's day")
    before = found.before
    if before is not None and before.day != previous_school_day(day):
        before = None
    after_map: frozenset[int] | None = None
    previous = found.previous
    if previous is not None and previous.day == previous_school_day(day):
        prior = previous.timeline
        if prior is None or (prior.day == previous.day and units.indexes(prior)):
            after_map = no_school_units(prior, units, rule)
    closed_before = frozenset(
        () if before is None else (r.district for r in before.rows if r.label is Label.NO_SCHOOL)
    )
    unclassed = any(c.weather == UNCLASSED and c.alerted for c in read.audit.classes)
    position = {leaid: index for index, leaid in enumerate(units.districts)}
    rows_of = {row.district: row for row in read.rows}
    shown = shown_of(timeline, morning_end(rule))
    last = shown_of(timeline)
    today = called_today(timeline)
    lit_districts: set[int] = set()
    owner = _owners(units)
    for view in (shown, last):
        for school, found_status in view.items():
            if found_status.status in CALLED and school in owner:
                lit_districts.add(owner[school])
    wanted = {position[d] for d in rows_of if d in position} | lit_districts
    out: list[RecordRow] = []
    for index in sorted(wanted):
        leaid = units.districts[index]
        eligible = [str(s) for s in units.eligible[index].tolist()]
        after = None if after_map is None else index in after_map
        made = _row(
            day, leaid, row=rows_of.get(leaid), eligible=eligible,
            mine=_called(eligible, shown), final=_called(eligible, last),
            today={s: today[int(s)] for s in eligible if int(s) in today},
            still=frozenset(s for s in eligible if int(s) in last),
            unclassed=unclassed, before=before,
            after=True if leaid in closed_before else after, rule=rule,
        )  # fmt: skip
        if made is not None:
            out.append(made)
    return out


def _called(eligible: Sequence[str], shown: Mapping[int, Shown]) -> dict[str, Shown]:
    """The eligible schools ``shown`` lit with a morning call."""
    return {
        s: shown[int(s)] for s in eligible if int(s) in shown and shown[int(s)].status in CALLED
    }


def _owners(units: Units) -> dict[int, int]:
    """Each eligible school's district position."""
    found: dict[int, int] = {}
    for index, schools in enumerate(units.eligible):
        for school in schools.tolist():
            found[int(school)] = index
    return found


def _row(  # noqa: PLR0913 - one district's day and its inputs
    day: date,
    leaid: str,
    *,
    row: ReadRow | None,
    eligible: Sequence[str],
    mine: Mapping[str, Shown],
    final: Mapping[str, Shown],
    today: Mapping[str, frozenset[int]],
    still: AbstractSet[str],
    unclassed: bool,
    before: ReadDay | None,
    after: bool | None,
    rule: LabelSettings,
) -> RecordRow | None:
    """One district's row, or ``None`` when nothing is known of its morning. ``mine``: its
    eligible schools lit with a morning call at 09:30; ``final``: at the day's last change;
    ``today``: those lit with a morning call at any change of the day, and the codes they
    named with one; ``still``: those showing any status at the day's last change."""
    if row is not None:
        weather: WeatherClass | None = WeatherClass(row.weather)
        after_weather = row.after
    else:
        weather = None if unclassed else WeatherClass.NONE
        after_weather = None if before is None else leaid in before.no_school
    if weather is None or (after_weather is None and weather in AFTER_CLASSES):
        situation = None
    else:
        situation = Situation.of(weather, after_weather is True).key
    base: dict[str, Any] = {
        "version": RECORD_VERSION,
        "day": day,
        "unit": leaid,
        "weather": None if weather is None else int(weather),
        "klass": class_key(weather),
        "after": True if after_weather is True else after,
        "after_weather": after_weather,
        "situation": situation,
        "eligible": len(eligible),
        "taken_back": any(s not in still for s in today),
        "tier": None if row is None or row.tier is None else row.tier.value,
        "market": None if row is None else market_code(row.market),
        "sources": () if row is None else tuple(sorted(row.sources)),
        "slot": None if row is None else row.slot,
    }
    klass = weather or WeatherClass.NONE
    codes = frozenset[int]().union(*today.values())
    stated = bool(codes - _WEATHER_CODES)
    reasons = tuple(sorted(codes))
    decided: dict[str, Any]
    if row is not None and row.label in (Label.NO_SCHOOL, Label.DELAYED):
        decided = _read_row(
            row, eligible, mine=mine, final=final, weather=klass, rule=rule, stated=stated
        )
    elif not mine and not final:
        if row is None or row.label is not Label.UNNAMED:
            return None
        decided = {
            **_READ, "call": Call.UNNAMED, "cause": Cause.NAMED if stated else Cause.ANY,
            "weather_day": False, "lit": 0, "agrees": True, "map_call": None,
        }  # fmt: skip
    else:
        # lit at 09:30, or posted only after it (then the call is the day's last change's,
        # it does not agree with the morning view, and it is no weather day)
        told = _of(eligible, mine or final, klass, rule, stated=stated)
        if told.call is None:  # pragma: no cover - a school lit with a morning call is a call
            return None
        decided = {
            "call": told.call,
            "source_kind": SourceKind.LIVE_MAP,
            "source_complete": False,
            "closings_only": True,
            "scope": told.scope,
            "cause": told.cause,
            "weather_day": told.weather_day and bool(mine),
            "lit": told.lit,
            "agrees": bool(mine),
            "map_call": told.call if mine else None,
            "read": None if row is None else row.label.value,
            "why": None if row is None else row.why,
        }
    fields = {**base, **decided, "reasons": reasons, "tropical": _tropical(weather, reasons)}
    return RecordRow(**fields, fit_usable=fit_rule(fields))


_READ: Final[Mapping[str, Any]] = {
    "source_kind": SourceKind.LIVE_READ,
    "source_complete": True,
    "closings_only": False,
    "scope": Scope.WHOLE,
    "read": None,
    "why": None,
}
"""The fields every live read row holds."""


def _read_row(  # noqa: PLR0913 - one read row and both views of its schools
    row: ReadRow,
    eligible: Sequence[str],
    *,
    mine: Mapping[str, Shown],
    final: Mapping[str, Shown],
    weather: WeatherClass,
    rule: LabelSettings,
    stated: bool,
) -> dict[str, Any]:
    """The fields a ``no_school`` or ``delayed`` read row decides (see the module): the 09:30
    map's call when it is the label's kind and whole, else the label's kind of call, never a
    weather day."""
    no_school = row.label is Label.NO_SCHOOL
    told = _of(eligible, mine, weather, rule, stated=stated)
    if (
        told.call is not None
        and told.scope is Scope.WHOLE
        and (told.call in NO_SCHOOL_CALLS) == no_school
    ):
        return {
            **_READ, "call": told.call, "cause": told.cause, "weather_day": told.weather_day,
            "lit": told.lit, "agrees": True, "map_call": told.call,
        }  # fmt: skip
    called = [found for found in final.values() if (found.status in NO_SCHOOL) == no_school]
    return {
        **_READ,
        "call": _no_school_call(called) if no_school else Call.DELAYED,
        "cause": Cause.NAMED if stated else _cause(_codes(called)),
        "weather_day": False,
        "lit": len(called),
        "agrees": False,
        "map_call": told.call,
    }


# --- the bytes ----------------------------------------------------------------------------------


def _checked(value: object, where: str) -> None:
    """Every string a row holds is a code, id, date or time (see :data:`SAFE`)."""
    if isinstance(value, str):
        if len(value) > MAX_TEXT or not set(value) <= SAFE:
            raise RecordError(f"{where}: holds a string that is not a code")
        return
    if isinstance(value, list | tuple):
        for item in value:
            _checked(item, where)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _checked(key, where)
            _checked(item, where)


def day_bytes(rows: Sequence[RecordRow]) -> bytes:
    """A record day's bytes: one JSON object a line, by district, keys sorted.

    Raises:
        RecordError: a row holds a string that is not a code, id, date or time, or the rows
            are not of one day.
    """
    lines: list[str] = []
    days = {row.day for row in rows}
    if len(days) > 1:
        raise RecordError("rows of more than one day")
    for row in sorted(rows, key=lambda r: r.unit):
        body = row.model_dump(mode="json")
        _checked(body, f"{row.day} {row.unit}")
        lines.append(json.dumps(body, sort_keys=True, separators=(",", ":")))
    return ("\n".join(lines) + "\n").encode() if lines else b""


def rows_of(data: bytes) -> list[RecordRow]:
    """A record day's rows from its bytes.

    Raises:
        pydantic.ValidationError: a line is not a row.
    """
    return [
        RecordRow.model_validate_json(line, strict=False)
        for line in data.decode().splitlines()
        if line.strip()
    ]


PAST_COLUMNS: Final = tuple(
    name for name in PastDay.model_fields if name not in RecordRow.model_fields
)
"""The columns only a past record row has (``code``)."""
COLUMNS: Final = (*RecordRow.model_fields, *PAST_COLUMNS)
"""``record.parquet``'s columns: a live row's, then a past row's own. A live row holds its
past-only columns empty, a past row the live-only ones (it has no 09:30 map, read or schools
counted)."""


def table(rows: Iterable[RecordRow | PastDay]) -> pl.DataFrame:
    """The record as a table (``record.parquet``), by day then district (a district's live and
    past rows of one day both kept, the live one first)."""
    found: list[dict[str, Any]] = [
        dict.fromkeys(COLUMNS) | row.model_dump(mode="json") for row in rows
    ]
    schema: dict[str, Any] = {
        "version": pl.Int64,
        "day": pl.Date,
        "unit": pl.String,
        "weather": pl.Int64,
        "klass": pl.String,
        "after": pl.Boolean,
        "after_weather": pl.Boolean,
        "situation": pl.String,
        "call": pl.String,
        "source_kind": pl.String,
        "source_complete": pl.Boolean,
        "closings_only": pl.Boolean,
        "scope": pl.String,
        "cause": pl.String,
        "weather_day": pl.Boolean,
        "agrees": pl.Boolean,
        "map_call": pl.String,
        "taken_back": pl.Boolean,
        "fit_usable": pl.Boolean,
        "reasons": pl.List(pl.Int64),
        "eligible": pl.Int64,
        "lit": pl.Int64,
        "tropical": pl.Boolean,
        "read": pl.String,
        "why": pl.String,
        "tier": pl.String,
        "market": pl.String,
        "sources": pl.List(pl.String),
        "slot": pl.String,
        "code": pl.String,
    }
    for item in found:
        item["day"] = date.fromisoformat(item["day"])
    frame = pl.DataFrame(found, schema=schema) if found else pl.DataFrame(schema=schema)
    return frame.sort("day", "unit", "source_kind", maintain_order=True)


COUNT_COLUMNS: Final = tuple(YearCount.model_fields)


def counts_table(counts: Iterable[YearCount]) -> pl.DataFrame:
    """The past records' yearly counts as a table (``record-counts.parquet``), by district,
    year and code."""
    schema: dict[str, Any] = {
        "version": pl.Int64,
        "unit": pl.String,
        "year": pl.String,
        "code": pl.String,
        "days": pl.Int64,
        "not_weather": pl.Int64,
        "unconfirmed": pl.Int64,
        "source_kind": pl.String,
        "sources": pl.List(pl.String),
        "covid": pl.Boolean,
        "disaster": pl.Boolean,
    }
    found = [count.model_dump(mode="json") for count in counts]
    frame = pl.DataFrame(found, schema=schema) if found else pl.DataFrame(schema=schema)
    return frame.sort("unit", "year", "code")


def write_table(
    rows: Iterable[RecordRow | PastDay],
    path: Path = RECORD_PATH,
    counts: Iterable[YearCount] | None = None,
) -> int:
    """Write ``record.parquet`` whole (atomically), and with ``counts`` its yearly counts beside
    it (:data:`COUNTS_NAME`); returns the record's rows."""
    if counts is not None:
        _write_frame(counts_table(counts), path.with_name(COUNTS_NAME))
    return _write_frame(table(rows), path)


def _write_frame(frame: pl.DataFrame, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(".parquet.part")
    frame.write_parquet(scratch)
    write_bytes_atomic(path, scratch.read_bytes())
    scratch.unlink()
    return frame.height


def kept_rows(
    kept: Mapping[str, bytes],
    learn: LearnSettings,
    warn: Callable[[str], None] | None = None,
) -> list[RecordRow | PastDay]:
    """Every row of the days the evidence store keeps, oldest first, but the take-back days and
    rows (``learn.excluded_days``, ``learn.excluded_rows``: spec rule 5, live corrections of
    the live map), then every past record row of each file's newest edition
    (:func:`newest_past`). Yearly counts are :func:`kept_counts`'."""
    live: list[RecordRow | PastDay] = [
        row
        for key, data in sorted(kept.items())
        if not key.startswith(PAST_PREFIX)
        for row in rows_of(data)
        if not learn.excludes_row(row.day, row.unit)
    ]
    return [
        *live,
        *(row for _, rows in newest_past(kept, PAST_DAYS, past_days_of, warn) for row in rows),
    ]


def kept_counts(
    kept: Mapping[str, bytes], warn: Callable[[str], None] | None = None
) -> list[YearCount]:
    """Every yearly count of each file's newest edition the evidence store keeps
    (:func:`newest_past`)."""
    return [
        count for _, counts in newest_past(kept, PAST_COUNTS, counts_of, warn) for count in counts
    ]


def newest_past[T](
    kept: Mapping[str, bytes],
    kind: str,
    read: Callable[[bytes], list[T]],
    warn: Callable[[str], None] | None = None,
) -> list[tuple[str, list[T]]]:
    """Each file's newest edition of its past ``kind`` key, read, by key. A past key whose name
    or rows do not read is warned of (the key and the error's kind) and left out, never the
    whole record: an older key a later model cannot read must not stop the daily step."""
    say = warn if warn is not None else _say
    newest: dict[str, tuple[int, str]] = {}
    for key in sorted(kept):
        if not key.startswith(PAST_PREFIX):
            continue
        match = PAST_KEY.fullmatch(key)
        if match is None:
            say(f"::warning::predict each-school record: {key}: not a past record key, left out")
            continue
        file_id, edition, found = match.group(1), int(match.group(2)), match.group(3)
        if found == kind and edition > newest.get(file_id, (0, ""))[0]:
            newest[file_id] = (edition, key)
    read_back: list[tuple[str, list[T]]] = []
    for _, key in sorted(newest.values(), key=lambda item: item[1]):
        try:
            read_back.append((key, read(kept[key])))
        except ValueError as error:
            say(
                f"::warning::predict each-school record: {key}: {type(error).__name__}, its rows"
                f" do not read; left out"
            )
    return read_back


def past_days_of(data: bytes) -> list[PastDay]:
    """A past record file's day rows from their bytes.

    Raises:
        pydantic.ValidationError: a line is not a past record row.
    """
    return [
        PastDay.model_validate_json(line, strict=False)
        for line in data.decode().splitlines()
        if line.strip()
    ]


def counts_of(data: bytes) -> list[YearCount]:
    """A past record file's yearly counts from their bytes.

    Raises:
        pydantic.ValidationError: a line is not a yearly count.
    """
    return [
        YearCount.model_validate_json(line, strict=False)
        for line in data.decode().splitlines()
        if line.strip()
    ]


def lines_bytes(rows: Sequence[PastDay] | Sequence[YearCount], where: str) -> bytes:
    """A past record key's bytes: one JSON object a line, keys sorted, every string a code
    (:data:`SAFE`), in the order given.

    Raises:
        RecordError: a row holds a string that is not a code, id, date or time.
    """
    lines: list[str] = []
    for row in rows:
        body = row.model_dump(mode="json")
        _checked(body, where)
        lines.append(json.dumps(body, sort_keys=True, separators=(",", ":")))
    return ("\n".join(lines) + "\n").encode() if lines else b""


def counts_line(day: date, rows: Sequence[RecordRow]) -> str:
    """One log line of a day's rows (counts only)."""
    calls = {call: sum(row.call is call for row in rows) for call in Call}
    said = ", ".join(f"{call.value} {n}" for call, n in calls.items() if n)
    read = sum(row.source_kind is SourceKind.LIVE_READ for row in rows)
    weather = sum(row.weather_day for row in rows)
    named = sum(row.cause is Cause.NAMED for row in rows)
    after = sum(row.after is True for row in rows)
    differ = sum(not row.agrees for row in rows)
    usable = sum(row.fit_usable for row in rows)
    return (
        f"predict each-school record: {day}: {len(rows)} rows ({said or 'none'}); {read} from"
        f" the read labels, {len(rows) - read} from the map alone; {weather} weather days,"
        f" {named} for a stated cause that is not the weather; {after} the day after a"
        f" closing; {differ} read calls the 09:30 map does not give; {usable} fit-usable"
    )


# --- the step -----------------------------------------------------------------------------------


class Host(Protocol):
    """The live host's day files (read only)."""

    def timeline(self, day: date) -> DayTimeline | None:
        """``live/days/<day>.json``; ``None`` when the host answers that it holds none.

        Raises:
            RecordError: it did not read (the day waits for the next run).
        """

    def index(self) -> DayIndex | None:
        """``live/days/index.json``; ``None`` when the host answers that it holds none.

        Raises:
            RecordError: it did not read.
        """


STUCK_DAYS: Final = 7
"""A labeled day this many days older than the newest one and still not written is warned
of on every run that leaves it."""


def seen(host: Host, day: date, index: DayIndex | None) -> DayTimeline | None:
    """What the map showed on ``day`` for good: its final timeline, or ``None`` when the host
    holds none and its index, written after the day was over everywhere, does not list the
    day (labels' rule, ``live_labels.day_ready``).

    Raises:
        RecordError: it is not known yet (the day waits).
    """
    from snowlight.predict.live_labels import day_ready  # noqa: PLC0415 - read only

    timeline = host.timeline(day)
    why = day_ready(day, timeline, index)
    if why is not None:
        raise RecordError(f"{day}: {why}")
    return timeline


def previous_of(host: Host, day: date, index: DayIndex | None) -> Previous | None:
    """The previous school day's map, ``None`` when it is not known for good (the host holds
    no timeline of a day older than every day its index lists).

    Raises:
        RecordError: it is not known yet (the day waits).
    """
    from snowlight.predict.live_labels import day_ready  # noqa: PLC0415 - read only

    prior = previous_school_day(day)
    timeline = host.timeline(prior)
    if timeline is None and (
        index is None or not index.days or prior < min(entry.day for entry in index.days)
    ):
        return None
    why = day_ready(prior, timeline, index)
    if why is not None:
        raise RecordError(f"{prior} (the previous school day): {why}")
    return Previous(prior, timeline)


@dataclass(slots=True)
class RecordRun:
    """One run's new record days (the job's step, :func:`run_record`)."""

    reads: Path
    units: Units
    rule: LabelSettings
    host: Host
    held: frozenset[str]
    """The days the evidence store holds already (never written again)."""
    say: Callable[[str], None]
    days: int = DAYS_PER_RUN

    def new_days(self) -> list[tuple[date, bytes]]:
        """Each new day's bytes, oldest first: the newest :attr:`days` labeled days the store
        does not hold, whose map is known for good (a day whose timeline is not final yet, or
        did not read, or does not read as a record day, waits and is said)."""
        from snowlight.predict import live_read  # noqa: PLC0415

        labeled = [d for d in live_read.labeled_days(self.reads) if d.isoformat() not in self.held]
        try:
            index = self.host.index()
        except RecordError as error:
            self.say(f"predict each-school record: the day index: {error}")
            index = None
        found: list[tuple[date, bytes]] = []
        window = labeled[-self.days :]
        for day in window:
            try:
                read = live_read.read_day(self.reads, day)
                if read is None:
                    raise RecordError(f"{day}: its read day does not read")
                timeline = seen(self.host, day, index)
                before = self._before(day)
                previous = previous_of(self.host, day, index)
                rows = record_rows(
                    RecordDay(day, read, timeline, before, previous), self.units, self.rule
                )
                data = day_bytes(rows)
            except (ValueError, OSError) as error:
                # RecordError, a read day that does not validate, a file that does not read
                # (only the error's kind: a private file's bytes never reach the log)
                said = error if isinstance(error, RecordError) else type(error).__name__
                self.say(f"predict each-school record: {day}: {said}: left for a later run")
                if labeled and (labeled[-1] - day).days >= STUCK_DAYS:
                    self.say(
                        f"::warning::predict each-school record: {day} is still not written"
                        f" {(labeled[-1] - day).days} days on"
                    )
                continue
            self.say(counts_line(day, rows))
            found.append((day, data))
        if len(labeled) > len(window):
            self.say(
                f"predict each-school record: {len(labeled) - len(window)} older labeled days"
                f" not held wait for a later run (the newest {self.days} are read a run)"
            )
        return found

    def _before(self, day: date) -> ReadDay | None:
        """The previous school day's read day (``after_weather``), ``None`` when the record
        holds none that reads (said)."""
        from snowlight.predict import live_read  # noqa: PLC0415

        prior = previous_school_day(day)
        try:
            return live_read.read_day(self.reads, prior)
        except (ValueError, OSError) as error:
            self.say(
                f"predict each-school record: {day}: the previous read day {prior} does not"
                f" read ({type(error).__name__}): its weather day-after flags are not known"
            )
            return None


def held_days(store: Any) -> frozenset[str]:
    """The record days some evidence database holds (an empty day included: a morning with
    no row is kept too, so it is never written again).

    Raises:
        EvidenceError: no database answered.
    """
    from snowlight.live import evidence  # noqa: PLC0415

    return frozenset(
        key
        for versions in store.held((evidence.RECORD,)).values()
        for kind, key in versions
        if kind == evidence.RECORD
    )


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``each-school record``."""
    from snowlight.predict import live_read  # noqa: PLC0415
    from snowlight.predict.cli import DEFAULT_REPOSITORY, DEFAULT_SITE, LIVE_ROOT  # noqa: PLC0415

    each = actions.add_parser("each-school", help="each district's own record (docs/predict.md)")
    steps = each.add_subparsers(dest="each_school", required=True)
    record = steps.add_parser("record", help="write the new live mornings' record rows (daily)")
    record.add_argument("--config", type=Path, default=PIPELINE_ROOT / "config" / "predict.yaml")
    record.add_argument("--reads", type=Path, default=live_read.READS_DIR)
    record.add_argument("--out", type=Path, default=RECORD_PATH)
    record.add_argument("--site", default=DEFAULT_SITE, help="the site whose directory to read")
    record.add_argument(
        "--repository", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY)
    )
    record.add_argument(
        "--site-data", type=Path, default=None, help="read meta.json and points.bin here instead"
    )
    record.add_argument("--live-root", default=LIVE_ROOT, help="the live host's public root")
    record.add_argument(
        "--live-dir", type=Path, default=None, help="read live/days/<day>.json here instead"
    )
    record.add_argument(
        "--dry-run",
        type=Path,
        default=None,
        help="write each new day's rows to this folder; the evidence store is not asked",
    )
    record.set_defaults(handler=run_record)
    from snowlight.predict import state_records  # noqa: PLC0415

    state_records.register(steps)


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


class _LiveHost:  # pragma: no cover - the live host
    """The live host's public day files (or a folder of them, ``--live-dir``)."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.root = str(args.live_root).rstrip("/")
        self.folder: Path | None = None if args.live_dir is None else Path(args.live_dir)

    def _get(self, name: str) -> bytes | None:
        import httpx  # noqa: PLC0415

        from snowlight.predict.inputs import client  # noqa: PLC0415

        if self.folder is not None:
            local = self.folder / name
            return local.read_bytes() if local.is_file() else None
        try:
            with client() as http:
                answer = http.get(f"{self.root}/v1/live/days/{name}")
        except httpx.HTTPError as error:
            raise RecordError(f"live/days/{name}: {type(error).__name__}") from error
        if answer.status_code == 404:  # noqa: PLR2004 - HTTP
            return None
        if answer.status_code != 200:  # noqa: PLR2004 - HTTP
            raise RecordError(f"live/days/{name} answered HTTP {answer.status_code}")
        return answer.content

    def timeline(self, day: date) -> DayTimeline | None:
        from snowlight.predict import host_files  # noqa: PLC0415

        name = f"{day.isoformat()}.json"
        data = self._get(name)
        try:
            return None if data is None else host_files.timeline(data, where=name)
        except ValueError as error:
            raise RecordError(f"{day}: the timeline does not read") from error

    def index(self) -> DayIndex | None:
        from snowlight.predict import host_files  # noqa: PLC0415

        data = self._get("index.json")
        try:
            return None if data is None else host_files.index(data, where="index.json")
        except ValueError as error:
            raise RecordError("the day index does not read") from error


def run_record(args: argparse.Namespace) -> int:  # pragma: no cover - the real world
    """Run ``predict each-school record`` (each-school-record.yml)."""
    from snowlight.live import evidence  # noqa: PLC0415
    from snowlight.live.cli import make_client  # noqa: PLC0415
    from snowlight.live.d1 import D1Error  # noqa: PLC0415
    from snowlight.predict.config import PredictConfig  # noqa: PLC0415
    from snowlight.predict.inputs import read_deployed, read_local  # noqa: PLC0415

    env = dict(os.environ)
    if not (args.reads / "rows").is_dir():
        _say("predict each-school record: no read record reached this run: nothing is written")
        return 0
    try:
        config = PredictConfig.load(args.config)
        directory = (
            read_local(args.site_data)
            if args.site_data is not None
            else read_deployed(args.site, args.repository, env.get("GITHUB_TOKEN"))
        )
        units = units_of(directory)
    except (OSError, ValueError) as error:
        _say(f"predict each-school record: error: {type(error).__name__}: nothing is written")
        return 1
    host = _LiveHost(args)
    if args.dry_run is not None:
        run = RecordRun(args.reads, units, config.labels, host, frozenset(), _say)
        for day, data in run.new_days():
            write_bytes_atomic(args.dry_run / f"{day.isoformat()}.jsonl", data)
        return 0
    try:
        with make_client() as client:
            store = evidence.make_store(env, client)
            run = RecordRun(args.reads, units, config.labels, host, held_days(store), _say)
            offers = [
                evidence.Offer(evidence.RECORD, day.isoformat(), data)
                for day, data in run.new_days()
            ]
            if offers:
                for report in store.push(offers, (evidence.RECORD,)):
                    _say(
                        f"predict each-school record {report.database}: {len(offers)} days"
                        f" offered, {report.kept} kept and read back, {report.copied} copied"
                        f" from the other database"
                    )
            kept = store.pull(evidence.RECORD)
    except (D1Error, evidence.EvidenceError) as error:
        _say(f"::error::predict each-school record: {error}")
        return 1
    rows = kept_rows(kept, config.learn)
    counts = kept_counts(kept)
    count = write_table(rows, args.out, counts)
    past = sum(key.startswith(PAST_PREFIX) for key in kept)
    _say(
        f"predict each-school record: {len(kept) - past} days and {past} past record keys,"
        f" {count} rows in {args.out.name} (take-back days and rows left out),"
        f" {len(counts)} yearly counts in {COUNTS_NAME}"
    )
    return 0

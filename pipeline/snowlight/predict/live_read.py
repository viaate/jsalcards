"""Outcome-blind live labels (advisory-sane L1, as the owner's Addendum A amends it: O5 yes).

The S7-L labels (:mod:`snowlight.predict.live_labels`) read a district only through a list
that already lit it on two live days, so a district that is read every morning and never
closes gives no row: its labels come mostly from closings. This module labels a school
morning from **which lists were read**, decided before any outcome is looked at, and only
then joins what the map showed. S7-L, ``learn.json`` and their tests are untouched: this is
a second, separate record.

**The read rule** (pre-registered in ``predict.yaml`` ``live_score.read`` and S7 addendum h).
District d is read on school day D when some source ``src``:

1. is **tier A** for d (it carries d in the archive audiences, ``audiences.json.gz``, or in
   the live audience: it lit a school of d on ``audience_days`` live days **before** D, from
   the change log's days before D only, so what the lists lit on D never decides whether d
   was read on D) or **tier B** (it is proven for d's county, ``read-sources.json.gz``, and
   has ``min_captures`` **closing-size** captures, archive and live record before D
   together: lead ruling B1.4). One test decides a closing-size capture on both sides
   (:func:`closing_size`, lead rulings C1 and C2): the list's **own** rows named at least
   :data:`CLOSING_LIT` districts under a warning-or-above class (archive: on the capture's
   local day or the next, one value a day, :func:`closing_rows`; live: at that day's
   snapshot, and lit closed, remote or delayed on our map that morning). A live day
   **counts** for a list (:func:`counted_days`) only when that day's own read passed every
   check (shown, healthy, not stale, gated, not thin, not short against its reference as it
   stood) and was closing-size; only counted days are its live captures, live reference
   values, tier B captures and recent days (condition 4). That our map lit districts the
   list carries is never enough. The record keeps 45 days, so the live part counts at most
   those. A district-level source (a
   district's own site: its registry entry names LEAIDs) is neither: its rows never light
   the map, so its silence says nothing;
2. has a **whole** read (``ok``, ``not_modified`` or ``empty``; never ``partial``) recorded
   in a 30-minute slot wholly inside d's local window [``read_from``, ``read_until``), the
   slot shown on the map under the prefix read here with no pass of it withholding d's state
   whole, in a record that reaches the window's last slot, that passes the archive's and
   S7-L's station gates (:func:`snowlight.predict.labels.station_reads`, one rule for all
   three): a populated read the replay step would drop (over a quarter of its rows unread,
   or under half its source's median share placed: ``dropped_read``); any read, populated
   or empty, of a source with under ``station_min_captures`` captures of any day
   (``thin_station``: too few lists to tell a whole one from a partial one); on a storm day
   (d's class above ``none``) a populated read under ``capture_min_share`` of its source's
   closing-size reference (``small_capture``: a partial list; :func:`reference_of`: the
   median of its closing-size archive days' largest captures and of its counted live days'
   largest reads, never an advisory or quiet day's, never under the archive's own median), or, for a
   source with under ``station_min_captures`` closing-size captures (a thin reference, lead
   ruling B1.2), under ``capture_min_share`` of the longest read in the window of a market
   peer that vouches by :class:`PeerVouch` (the one rule the counted days apply too: never a
   thin, short, stale, unhealthy or district-site peer), or with no such peer, and any empty
   read of it; on a warning-or-above morning a populated read naming
   no district for D while another list of its market named some (``stale_populated``,
   lead ruling B1.3); an empty read while a market peer held
   ``market_rows_void`` rows in the window (``voided_empty``); an empty read the reader
   judged from old rows, a list not kept for 36 hours or a feed of old posts
   (``stale_empty``: the record's ``stale``; only a page that says it holds nothing now is
   whole); and on a storm day an empty read no other list of its market read with in the
   window (``empty_uncorroborated``; a peer counts only when its read passed every gate in
   a healthy slot);
3. in a slot whose reader **healthy share** (the morning record's ``health``) is at least
   ``healthy_share``: a slot with no share recorded never counts (``health_unrecorded``);
4. and either has a **counted** day (above) in the ``recent_days`` UTC days of the record
   before D, or a second tier A or B source of d's in the same market also meets 1 to 3.

The read set is computed from the morning record's reads, shown prefixes, withheld states,
stale empties and healthy shares, the coverage files, the change log before D and the
district's class at the snapshot only (:func:`read_set`); what any list named and what the
map lit on D enter after it (:func:`label_read_day`), so clearing them, or D's change log,
leaves the read set as it was. The row's tier is A when any qualifying source is tier A,
else B.

**The label of a read district-day:**

* ``no_school``: the map lit at least ``no_school_share`` of its eligible schools closed or
  remote for the weather; ``delayed``: at least ``delayed_share`` delayed;
* ``unknown``: a list named it for D (or every day) anywhere in D's record, or in the
  record of the day before, and the map did not show that (``listed_unread``, the S7-L rule
  :func:`~snowlight.predict.live_labels.listed_unread`, over the whole day, not only up to
  the window's end), lit in part
  (``partly_lit``), a status taken back (``retracted``), a likely break (``break``), or,
  on a storm day, dark while at least ``storm_absence_share`` of the other read districts of
  its market closed (``absent_in_storm``);
* ``unnamed``: read, no list named it, the map lit none of its schools with any status (one
  lit school with no naming is ``partly_lit``). Under the owner's O5 an unnamed district
  **counts as open** (:data:`OPEN_LABEL`).

A district with no class at the snapshot is never labeled (counted ``unclassed``). Rows are
kept for every alerted district (class above ``none``), read or not, with why not
(:class:`NotRead`); the other classes are counted only.

**Co-listing trials (list sensitivity).** On a school day of any class where the map lit d
``no_school`` (closed districts only, as registered; a delayed district gives no trial),
every qualifying source of d that did not itself light it
gives one trial: did its own rows name d for D (or every day) in a slot it qualified in
(the morning record's ``by``; the registered estimand), and anywhere in D's record of its
whole reads (``named_in_day``, the event ``unnamed`` turns on, reported beside it)? A
source "lit it" when the change log holds a lighting or a
change of one of d's schools for D from it logged before d's window ended (any log day, so
a closing announced days ahead counts its lighter out); a source that lit d only after the
window is a trial like any other. ``s_A ~ Beta(9 + hits, 1 + misses)``, ``s_B ~ Beta(4 +
hits, 2 + misses)``. Trials condition on closure, so the capture bias does not touch them;
they do condition on the trial source not being the one whose row lit the map by the
window's end (its hit would be certain), and on the source being read whole in the window
(as every labeled row is). Trials of one list on one morning are not independent, so the
private report gives their distinct dates and lists and a day-aggregated interval beside
the registered Beta one (:class:`Sensitivity`).

Everything here is codes, ids and counts: no names, no list text.
"""

import gzip
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal, Protocol, cast

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from snowlight.live.history import Change, ChangeLog, Event, is_final
from snowlight.live.morning import SLOT_MINUTES, MorningLog, Slot, slot_start
from snowlight.output import JSONValue, dumps_json, write_bytes_atomic
from snowlight.predict.calendar import is_school_day, likely_break, previous_school_day
from snowlight.predict.config import PIPELINE_ROOT, LabelSettings, PredictConfig
from snowlight.predict.geography import REGION_OF
from snowlight.predict.labels import (
    Outcome,
    StationRead,
    Unread,
    audiences,
    outcome_of,
    shares,
    station_reads,
)
from snowlight.predict.learn import ANOTHER_DIRECTORY, EXCLUDED, NEVER
from snowlight.predict.live_labels import (
    KIND_OF,
    Directory,
    Lit,
    LiveSource,
    Morning,
    StateSource,
    day_ready,
    district_state,
    leaid_of,
    listed_unread,
    lit_of,
    named_on,
    snapshot_classes,
    station_window,
    window_of,
)
from snowlight.predict.situations import WeatherClass, Window
from snowlight.replays.gates import UNREADABLE_SHARE, low_match, station_median
from snowlight.schemas.live import DayIndex, DayTimeline
from snowlight.schemas.stats import ReadAudit, ReadAuditDay, ReadClass

READ_SOURCES_PATH: Final = PIPELINE_ROOT / "data" / "predict" / "read-sources.json.gz"
"""County FIPS to the sources proven for it (codes only; ``snowlight predict read-sources``)."""
AUDIENCES_PATH: Final = PIPELINE_ROOT / "data" / "predict" / "audiences.json.gz"
"""The archive audiences: each source's districts (LEAIDs only, no dates)."""
FILES_VERSION: Final = 3
"""The coverage files' ``schema_version`` (3: closing-size archive rows one a day, audiences of the
current and previous season without dates); a file of another version is refused, never
read as this one."""
READS_DIR: Final = PIPELINE_ROOT / "out" / "internal" / "predict" / "reads"
"""The private record: ``rows/<day>.json`` and ``trials/<day>.jsonl`` (the predict state)."""
AUDIT_PATH: Final = "predictions/read-audit.json"
PERMILLE: Final = 1000
UNCLASSED: Final = "unclassed"
SCHEMA_VERSION: Final = 1
CAPTURE_DAYS: Final = 366
"""A source's live captures count over every day of the record before (it keeps 45)."""
OFFER_DAYS: Final = 21
"""The newest labeled days offered to the evidence store each run (each is offered on about
90 runs before it leaves this window; a day both databases hold is never written again)."""
AUDIT_SAMPLE: Final = 50
"""Unnamed rows drawn for the weekly hand audit (G1), by a fixed hash of day and district."""
WARNING_CLASSES: Final = frozenset(
    {
        WeatherClass.TROPICAL,
        WeatherClass.LAKE_SNOW,
        WeatherClass.SNOW_WARNING,
        WeatherClass.ICE,
        WeatherClass.BLIZZARD,
    }
)
"""The warning-or-above classes (the spec's ``warning`` class level: snow, lake snow, ice,
blizzard and tropical warnings; cold and advisories are not)."""
CLOSING_LIT: Final = 3
"""Lead rulings B1.1, C1 and C2 (:func:`closing_size`): a capture is closing-size only when the
list's own rows named at least this many districts under a warning-or-above class (archive:
on its local day or the next; live: at the day's snapshot, and lit closed, remote or delayed
on our map that morning)."""


class Tier(StrEnum):
    """How a source is known to cover a district."""

    A = "A"
    """It carries the district (archive or live audience)."""
    B = "B"
    """It is proven for the district's county."""


class Label(StrEnum):
    """What a read district-day did (``not_read``: alerted, not read)."""

    NO_SCHOOL = "no_school"
    DELAYED = "delayed"
    UNNAMED = "unnamed"
    UNKNOWN = "unknown"
    NOT_READ = "not_read"


OPEN_LABEL: Final = Label.UNNAMED
"""Owner O5: a covered district a whole, healthy, fresh read did not name counts as open."""


class NotRead(StrEnum):
    """Why a district was not read, from the furthest any of its sources got."""

    NOT_COVERED = "not_covered"
    """No tier A or tier B source."""
    WITHHELD_STATE = "withheld_state"
    """No source of it had a whole read in a qualifying slot of its window, and a slot of the
    window was left out because a pass withheld its state (counted apart, to measure how
    often withholding, which happens more on closing mornings, keeps a district unread)."""
    NO_WHOLE_READ = "no_whole_read"
    """No source of it had a whole read in a qualifying slot of its window."""
    DROPPED_READ = "dropped_read"
    VOIDED_EMPTY = "voided_empty"
    STALE_EMPTY = "stale_empty"
    """Its only whole reads are empties the reader judged from old rows."""
    STALE_POPULATED = "stale_populated"
    """Lead ruling B1.3: on a warning-or-above morning, its sources' populated reads named no
    district for the day (every row dated earlier) while another list of their market named
    districts for it: a list still holding an earlier day's rows."""
    THIN_STATION = "thin_station"
    """Its sources' reads, populated or empty, come from lists with under
    ``station_min_captures``."""
    SMALL_CAPTURE = "small_capture"
    """On a storm day, its sources' populated reads are under half their closing-size lists'
    median rows, or, for a source with under ``station_min_captures`` closing-size lists (a
    thin reference), under half of the longest read in the window of a market peer that
    vouches (:class:`PeerVouch`), or with no such peer, or empty (lead ruling B1.2)."""
    EMPTY_UNCORROBORATED = "empty_uncorroborated"
    """On a storm day, its sources' only whole reads are empties no market peer read with."""
    HEALTH_UNRECORDED = "health_unrecorded"
    """Its whole reads are in slots recorded with no healthy share (before 2026-10-31)."""
    UNHEALTHY = "unhealthy"
    """Its whole reads are in slots under the healthy share."""
    NOT_RECENT = "not_recent"
    """No populated read in the recent days, and no second source of its market read."""


STAGES: Final = (
    NotRead.NO_WHOLE_READ,
    NotRead.DROPPED_READ,
    NotRead.VOIDED_EMPTY,
    NotRead.STALE_EMPTY,
    NotRead.STALE_POPULATED,
    NotRead.THIN_STATION,
    NotRead.SMALL_CAPTURE,
    NotRead.EMPTY_UNCORROBORATED,
    NotRead.HEALTH_UNRECORDED,
    NotRead.UNHEALTHY,
    NotRead.NOT_RECENT,
)
"""The checks in order: a district's reason is the furthest stage any source reached."""


class Why(StrEnum):
    """Why a read district-day is unknown."""

    LISTED_UNREAD = "listed_unread"
    PARTLY_LIT = "partly_lit"
    RETRACTED = "retracted"
    BREAK = "break"
    ABSENT_IN_STORM = "absent_in_storm"


# --- the rule's settings ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReadRule:
    """The pre-registered read rule (``live_score.read`` and ``live_score.sensitivity``) and
    the label settings it shares with S7-L."""

    labels: LabelSettings
    healthy_share: float
    recent_days: int
    min_captures: int
    open_if_unnamed: bool
    prior_a: tuple[float, float]
    prior_b: tuple[float, float]
    tier_b_min: float = 0.7
    tier_b_min_trials: int = 20

    @classmethod
    def of(cls, config: PredictConfig) -> "ReadRule":
        """The rule as ``predict.yaml`` registers it.

        Raises:
            ValueError: the ``live_score`` block lacks a setting or holds the wrong kind.
        """
        read = config.live_score.get("read", {})
        sense = config.live_score.get("sensitivity", {})
        try:
            prior_a = sense["tier_a_prior"]
            prior_b = sense["tier_b_prior"]
            if not isinstance(prior_a, list) or not isinstance(prior_b, list):
                raise TypeError("a prior is two numbers")
            window = [config.labels.read_from.strftime("%H:%M"),
                      config.labels.read_until.strftime("%H:%M")]  # fmt: skip
            if read["window"] != window:
                raise ValueError(
                    f"live_score.read: the registered window {read['window']} is not the labels' "
                    f"{window}"
                )
            return cls(
                labels=config.labels,
                healthy_share=float(_number(read["healthy_share"])),
                recent_days=int(_number(read["recent_days"])),
                min_captures=int(_number(read["min_captures"])),
                open_if_unnamed=bool(read["open_if_unnamed"]),
                prior_a=(float(_number(prior_a[0])), float(_number(prior_a[1]))),
                prior_b=(float(_number(prior_b[0])), float(_number(prior_b[1]))),
                tier_b_min=float(_number(sense["tier_b_min"])),
                tier_b_min_trials=int(_number(sense["tier_b_min_trials"])),
            )
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError(f"live_score.read: {type(error).__name__}") from error

    def healthy(self, slot: Slot) -> bool | None:
        """Whether the slot's healthy share reaches the rule's (``None``: none recorded)."""
        if slot.health is None:
            return None
        return slot.health >= round(self.healthy_share * PERMILLE)

    def sensitivity(self, tier: Tier, trials: int, hits: int) -> float:
        """The posterior mean of the tier's list sensitivity."""
        a, b = self.posterior(tier, trials, hits)
        return a / (a + b)

    def posterior(self, tier: Tier, trials: int, hits: int) -> tuple[float, float]:
        """The tier's Beta posterior after ``hits`` of ``trials`` named."""
        a, b = self.prior_a if tier is Tier.A else self.prior_b
        return a + hits, b + trials - hits


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("a number")
    return float(value)


# --- the coverage files -------------------------------------------------------------------------


type Audience = Mapping[str, Mapping[str, date]]
"""Source to each district it carries and the first day it listed it (the live audience)."""
type Carried = Mapping[str, Collection[str]]
"""Source to the districts it carries in the archive (codes only, no dates)."""


@dataclass(frozen=True, slots=True)
class Coverage:
    """Which sources may read a district: the archive audiences (tier A, with the live
    audience of the day), the proven sources per county (tier B, each once it has
    ``min_captures`` closing-size captures in the archive and the live record before the
    day), each district's county, and the district-level sources that never count."""

    county_sources: Mapping[str, tuple[str, ...]]
    archive: Carried
    county_of: Mapping[str, str]
    district_sites: frozenset[str] = frozenset()
    captures: Mapping[str, int] = field(default_factory=dict)
    """Each source's populated captures in the archive, of any day (``thin_station``)."""
    min_captures: int = 0
    rows: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    """Each source's **closing-size** archive captures' rows (:func:`closing_captures`: the
    size gate's reference and tier B's captures); a capture of a quiet day is not among
    them."""
    audience_season: int | None = None
    """The season (the year of its Aug 1) ``audiences.json.gz`` was built in
    (:func:`load_audience_season`; ``None``: not checked). Its pairs are those listed in that
    season or the one before (lead ruling C4), so from the next Aug 1 it is out of date and
    the step reads none of them (:func:`audiences_current`, review R6-S4)."""
    _carried: dict[str, set[str]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        for source, districts in self.archive.items():
            for leaid in districts:
                self._carried.setdefault(leaid, set()).add(source)

    def candidates(
        self, leaid: str, day: date, live: Audience, captures: Mapping[str, int]
    ) -> dict[str, Tier]:
        """Each source that may read ``leaid`` on ``day``, with its tier (A wins): ``live`` the
        live audience before ``day``, ``captures`` each source's captures, archive and live
        record before ``day`` together (:class:`ListStats`)."""
        found: dict[str, Tier] = {}
        county = self.county_of.get(leaid)
        for source in self.county_sources.get(county, ()) if county else ():
            if captures.get(source, 0) >= self.min_captures:
                found[source] = Tier.B
        for source in self._carried.get(leaid, ()):
            found[source] = Tier.A
        for source, districts in live.items():
            first = districts.get(leaid)
            if first is not None and first <= day:
                found[source] = Tier.A
        return {s: tier for s, tier in sorted(found.items()) if s not in self.district_sites}


def read_gzip_json(path: Path) -> object | None:
    """A gzip JSON file, ``None`` when it is absent.

    Raises:
        ValueError: it does not read.
    """
    if not path.is_file():
        return None
    try:
        found: object = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, EOFError) as error:
        raise ValueError(f"{path.name}: {type(error).__name__}") from error
    return found


@dataclass(frozen=True, slots=True)
class ReadSources:
    """``read-sources.json.gz``: county FIPS to its proven sources, each source's populated
    archive captures of any day, and the rows of its **closing-size** archive captures."""

    counties: Mapping[str, tuple[str, ...]]
    captures: Mapping[str, int]
    rows: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    """Each source's closing-size archive captures' rows (:func:`closing_captures`)."""

    @property
    def present(self) -> bool:
        """Whether the file held a county table (an absent or empty file holds none)."""
        return bool(self.counties)


def _version(found: dict[str, object], name: str) -> None:
    if found.get("schema_version") != FILES_VERSION:
        raise ValueError(
            f"{name}: schema_version {found.get('schema_version')!r}, not {FILES_VERSION}"
        )


def load_read_sources(path: Path = READ_SOURCES_PATH) -> ReadSources:
    """``read-sources.json.gz`` (empty when absent).

    Raises:
        ValueError: the file is not one, or of another version.
    """
    found = read_gzip_json(path)
    if found is None:
        return ReadSources({}, {})
    if not isinstance(found, dict) or not isinstance(found.get("counties"), dict):
        raise ValueError(f"{path.name}: no county table")
    _version(found, path.name)
    captures = found.get("captures", {})
    rows = found.get("closing_rows", {})
    if not isinstance(captures, dict) or not isinstance(rows, dict):
        raise ValueError(f"{path.name}: no capture counts")
    return ReadSources(
        counties={
            str(county): tuple(sorted(str(s) for s in sources))
            for county, sources in sorted(found["counties"].items())
            if isinstance(sources, list)
        },
        captures={str(s): int(n) for s, n in sorted(captures.items())},
        rows={str(s): tuple(sorted(int(n) for n in found_)) for s, found_ in sorted(rows.items())},
    )


def load_audiences(path: Path = AUDIENCES_PATH) -> dict[str, frozenset[str]]:
    """``audiences.json.gz``: each source's districts (empty when absent).

    Raises:
        ValueError: the file is not one, or of another version.
    """
    found = read_gzip_json(path)
    if found is None:
        return {}
    if not isinstance(found, dict) or not isinstance(found.get("audiences"), dict):
        raise ValueError(f"{path.name}: no audience table")
    _version(found, path.name)
    return {
        str(source): frozenset(str(d) for d in found_)
        for source, found_ in sorted(found["audiences"].items())
        if isinstance(found_, list)
    }


def load_audience_season(path: Path = AUDIENCES_PATH) -> int | None:
    """The season ``audiences.json.gz`` was built in (the year its Aug 1 falls in, a season
    code; ``None`` when the file is absent).

    Raises:
        ValueError: the file names no build season.
    """
    found = read_gzip_json(path)
    if found is None:
        return None
    season = found.get("season") if isinstance(found, dict) else None
    if not isinstance(season, int) or isinstance(season, bool):
        raise ValueError(f"{path.name}: no build season")
    return season


def audiences_current(season: int, today: date) -> bool:
    """Whether audiences built in ``season`` still hold only pairs of ``today``'s season and
    the one before (lead ruling C4): until the next Aug 1. The file is rebuilt each Aug 1
    (``predict read-sources --as-of``)."""
    return season_of(today).year <= season


def gzip_json(value: Mapping[str, object]) -> bytes:
    """Key-sorted JSON, gzip with no name and no time (the same value, the same bytes).

    Raises:
        TypeError: ``value`` holds something that is not a JSON value.
    """
    return gzip.compress(dumps_json(cast("JSONValue", dict(value))), mtime=0)


def county_sources_of(proven: Mapping[str, object]) -> dict[str, list[str]]:
    """``coverage.json``'s ``proven.counties`` reduced to the sources each county is proven
    for (codes only; district-level and statewide sources are not among them)."""
    found: dict[str, list[str]] = {}
    for county, entry in sorted(proven.items()):
        if not isinstance(entry, dict):
            continue
        sources = sorted(str(s) for s in entry.get("proven", ()))
        if sources:
            found[str(county)] = sources
    return found


type Capture = tuple[str, str]
"""An archive capture: its source and ``fetched_at`` (as ``reads.jsonl`` writes it)."""


def populated_rows(lines: Iterable[str]) -> dict[str, list[int]]:
    """Each source's populated captures' rows in an archive ``reads.jsonl`` (state
    ``populated``; a capture with no row count counts as 0 rows)."""
    found: dict[str, list[int]] = defaultdict(list)
    for line in lines:
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("state") != "populated":
            continue
        rows = item.get("rows", 0)
        found[str(item["source_id"])].append(rows if isinstance(rows, int) else 0)
    return {source: sorted(rows) for source, rows in sorted(found.items())}


def populated_captures(lines: Iterable[str]) -> dict[str, int]:
    """Each source's populated captures in an archive ``reads.jsonl`` (state ``populated``)."""
    return {source: len(rows) for source, rows in populated_rows(lines).items()}


def closing_size(
    named: Iterable[tuple[str, date]],
    closing: Callable[[str, date], bool],
    least: int = CLOSING_LIT,
) -> bool:
    """**The** closing-size test of one list, archive and live alike (lead rulings B1.1, C1
    and C2; :func:`closing_captures` and :func:`counted_days` both call it, so the two sides
    cannot drift): the list's **own** rows named at least ``least`` distinct districts that
    ``closing`` holds for the day they were named for. Archive: under a warning-or-above
    class (:data:`WARNING_CLASSES`) on the capture's local day or the next. Live: under a
    warning-or-above class at the day's snapshot and lit closed, remote or delayed on our map
    that morning. That other lists named them, or that our map lit districts the list
    carries, is never enough."""
    found: set[str] = set()
    for leaid, day in named:
        if leaid not in found and closing(leaid, day):
            found.add(leaid)
            if len(found) >= least:
                return True
    return len(found) >= least


def closing_captures(
    named: Mapping[Capture, Iterable[tuple[str, date]]],
    weather: Mapping[tuple[str, date], WeatherClass],
    least: int = CLOSING_LIT,
) -> dict[Capture, date]:
    """The archive's **closing-size captures** (lead ruling C1, rule (a)), each with its day
    (the latest local day of the districts it named): the captures whose own rows named, in
    the archive's match, at least ``least`` districts that were in a warning-or-above class
    (:data:`WARNING_CLASSES`) on the capture's local day or the next (a list captured in the
    evening names the next morning's closings), by :func:`closing_size`. ``named``: each
    capture's districts with its local day there.

    An archive capture is a snapshot of any hour of any day (an August page, an evening
    church list, a one-row list); only these say how long the list runs when schools close,
    so only these set the size gate's reference and count toward tier B's captures, one value
    a day (:func:`closing_rows`)."""

    def warned(leaid: str, day: date) -> bool:
        return (
            weather.get((leaid, day)) in WARNING_CLASSES
            or weather.get((leaid, day + timedelta(days=1))) in WARNING_CLASSES
        )

    found: dict[Capture, date] = {}
    for capture, districts in named.items():
        pairs = tuple(districts)
        if pairs and closing_size(pairs, warned, least):
            found[capture] = max(day for _leaid, day in pairs)
    return found


def closing_rows(lines: Iterable[str], closing: Mapping[Capture, date]) -> dict[str, list[int]]:
    """Each source's closing-size archive rows, **one value a day** (review R5-S3, as the live
    side keeps one a day): the largest populated capture of each of its closing-size days
    (``closing``: :func:`closing_captures`). A list snapshotted early on a storm morning, while
    it was still growing, and again later gives the later, longer list only; five snapshots of
    one storm are one capture, not five."""
    largest: dict[tuple[str, date], int] = {}
    for line in lines:
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("state") != "populated":
            continue
        capture = (str(item["source_id"]), str(item["fetched_at"]))
        day = closing.get(capture)
        if day is None:
            continue
        rows = item.get("rows", 0)
        key = (capture[0], day)
        largest[key] = max(largest.get(key, 0), rows if isinstance(rows, int) else 0)
    found: dict[str, list[int]] = defaultdict(list)
    for (source, _day), rows in largest.items():
        found[source].append(rows)
    return {source: sorted(rows) for source, rows in sorted(found.items())}


# --- what was read, outcome-blind ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Read:
    """A read district: its tier, the sources that qualified, the market, and the first slot
    (UTC start) one of them qualified in, with that slot's healthy share."""

    tier: Tier
    sources: tuple[str, ...]
    market: str
    slot: datetime
    health: int
    unplaced: bool = False
    """A qualifying read held rows the matcher placed nowhere (the hand audit's stratum)."""


@dataclass(frozen=True, slots=True)
class Qualified:
    """One source's qualifying slots for one district window (conditions 2 and 3)."""

    slots: tuple[datetime, ...]
    stage: NotRead | None
    """``None`` when it qualifies; else the first check it failed."""
    unplaced: bool = False
    """A read of it in a qualifying slot held rows the matcher placed nowhere (a district's
    own row may be among them)."""


@dataclass(frozen=True, slots=True)
class LiveCaptures:
    """Each source's **counted** days in the live record before a day (lead ruling C2,
    :func:`counted_days`): the UTC days on which its own read passed every check and was
    closing-size by :func:`closing_size`, one value a day (that day's largest such read).
    These alone are its live captures for the station gate (``thin_station``), its live
    closing-size captures for tier B (lead ruling B1.4), its live values of the size gate's
    reference, and its 'recent populated' days (condition 4). A quiet or advisory day, a
    stale list, a read in an unhealthy or unshown slot, a short read or a list naming fewer
    than :data:`CLOSING_LIT` warned, lit districts itself never counts."""

    days: Mapping[str, int] = field(default_factory=dict)
    storm_rows: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    """Each source's counted days' largest reads (one per day)."""


type ClosingDistricts = Callable[[date], AbstractSet[str]]
"""Each day of the record: the districts under a warning-or-above class
(:data:`WARNING_CLASSES`) at that day's snapshot that our map lit closed, remote or delayed
that morning (none when either is not known). Advisory and quiet days hold none."""


@dataclass(frozen=True, slots=True)
class Closing:
    """What decides whether a live day counts for a list (:func:`counted_days`)."""

    rule: ReadRule
    coverage: Coverage
    districts: ClosingDistricts
    zones: Mapping[str, str] = field(default_factory=dict)
    """Each district's IANA zone (the directory's): a district the list named counts toward
    its closing-size test only in a slot wholly inside the district's read window
    (``read_from`` to ``read_until`` local, review R6-S5); one with no zone here never
    does."""


@dataclass(frozen=True, slots=True)
class PeerVouch:
    """**The** peer-vouch rule (lead ruling B1.2, review R6-B1): the one test the read
    (:class:`_Windows`) and the counted days (:func:`counted_days`) both make before a market
    peer's read vouches for the length of a list with a thin reference. A peer's read
    vouches only when:

    * its slot is shown under ``prefix`` alone and healthy (its share recorded and at least
      the rule's), and the read is not stale (the record's ``stale``, or, on a morning its
      market named districts for the day, a populated read naming none: lead ruling B1.3);
    * the peer is not a district site;
    * its captures (archive and counted live days before the day) reach
      ``station_min_captures``;
    * its own reference as it stood that day is not thin (:func:`reference_of`: a thin peer
      cannot tell its own whole read from a partial one, so two thin lists never vouch for
      each other);
    * the read holds at least ``capture_min_share`` of that reference (a peer partial by its
      own gate vouches for nothing).

    An empty read never vouches: a vouching read holds at least ``capture_min_share`` of a
    reference of populated reads, so a thin list's empty read is never whole on a storm
    day."""

    rule: ReadRule
    prefix: str
    district_sites: AbstractSet[str]
    market_of: Mapping[str, str]

    def vouches(
        self,
        source: str,
        rows: int,
        slot: Slot,
        stats: "ListStats",
        named_markets: AbstractSet[str] = frozenset(),
    ) -> bool:
        """Whether ``source``'s read of ``rows`` rows in ``slot`` vouches for a market peer's
        length, ``stats`` as they stood that day, ``named_markets`` the markets some list of
        which named a district for the day (empty but on a warning-or-above morning)."""
        settings = self.rule.labels
        if (
            rows <= 0
            or slot.shown != {self.prefix}
            or self.rule.healthy(slot) is not True
            or source in slot.stale
            or source in self.district_sites
        ):
            return False
        if not slot.by.get(source) and self.market_of.get(source, source) in named_markets:
            return False
        if stats.captures.get(source, 0) < settings.station_min_captures:
            return False
        reference = stats.median_rows.get(source, math.inf)
        return not math.isinf(reference) and rows >= settings.capture_min_share * reference


def reference_of(archive: Sequence[int], live: Sequence[int], least: int) -> float:
    """The size gate's reference of a list: the median of its closing-size archive rows
    (one a day) and its counted live days' largest reads, never under the archive's own
    median when the archive alone holds ``least``; unbounded (``inf``: a **thin reference**,
    lead ruling B1.2) with fewer than ``least`` values in all."""
    every = [*archive, *live]
    if not every or len(every) < least:
        return math.inf
    found = float(statistics.median(every))
    if archive and len(archive) >= least:
        found = max(found, float(statistics.median(archive)))
    return found


def counted_days(
    log: MorningLog, closing: Closing, *, market_of: Mapping[str, str], prefix: str
) -> dict[date, dict[str, int]]:
    """Each UTC day of the record (a damaged day holds none): the sources whose own read that
    day **counts** (lead ruling C2), each with its largest such read's rows. A read counts
    only when it passed every check the rule makes of a list's read, as the list stood that
    day:

    * in a slot shown under ``prefix`` alone whose healthy share is recorded and reaches the
      rule's (``unhealthy``, ``health_unrecorded``);
    * not judged stale (the record's ``stale``: an empty or a list of old rows, the
      reader's ``old_lists``);
    * populated and passing the read gate (never one the replay step would drop:
      ``dropped_read``; the placed share's median from the record's days up to and
      including the day, review R6-S5);
    * its own rows (the slot's ``by``) named at least :data:`CLOSING_LIT` districts under a
      warning-or-above class and lit on our map that morning (:func:`closing_size`, the
      archive's test; ``closing.districts``), in a slot wholly inside each such district's
      read window (``closing.zones``);
    * not a district site, and of a list with ``station_min_captures`` captures by then,
      archive and counted days (``thin_station``);
    * at least ``capture_min_share`` of the list's reference as of that day (archive
      closing-size rows and the days counted before it, :func:`reference_of`:
      ``small_capture``), or, for a thin reference, of the longest read that day of a market
      peer that vouches by :class:`PeerVouch`, the rule the read applies (review R6-B1: a
      thin, short, partial, stale, unhealthy or district-site peer vouches for nothing);
      with no such peer it does not count.

    Days are taken in order, so a day's count rests on the days before it only. Each day is
    parsed once."""
    records = [
        (when, record)
        for when in log.days()
        if (record := log.day(when)) is not None and not record.damaged
    ]
    coverage = closing.coverage
    settings = closing.rule.labels
    least = settings.station_min_captures
    share = settings.capture_min_share
    vouch = PeerVouch(closing.rule, prefix, coverage.district_sites, market_of)
    counted: dict[str, list[int]] = defaultdict(list)
    shares: dict[str, list[float]] = defaultdict(list)
    found: dict[date, dict[str, int]] = {}
    for when, record in records:
        for slot in record.slots.values():
            for source, reads in slot.reads.items():
                shares[source].extend(kept / n for n, kept, _unread in reads if n)
        lit = closing.districts(when)
        if not lit:
            found[when] = {}
            continue
        stats = ListStats.of(
            coverage,
            LiveCaptures(
                days={s: len(rows) for s, rows in counted.items()},
                storm_rows={s: tuple(rows) for s, rows in counted.items()},
            ),
            least,
        )
        placed = _Placed(shares)
        best, longest = _own_reads(when, record.slots, closing, lit, placed, vouch, stats)
        day: dict[str, int] = {}
        for source, rows in sorted(best.items()):
            if source in coverage.district_sites or stats.captures.get(source, 0) < least:
                continue
            reference = stats.median_rows.get(source, math.inf)
            if math.isinf(reference):
                market = market_of.get(source, source)
                peers = [
                    n for s, n in longest.items() if s != source and market_of.get(s, s) == market
                ]
                if not peers or rows < share * max(peers):
                    continue
            elif rows < share * reference:
                continue
            day[source] = rows
        for source, rows in day.items():
            counted[source].append(rows)
        found[when] = day
    return found


@dataclass(slots=True)
class _Placed:
    """Each source's median placed share over the record's days so far (memoized)."""

    shares: Mapping[str, Sequence[float]]
    _found: dict[str, float | None] = field(default_factory=dict)

    def __call__(self, source: str) -> float | None:
        if source not in self._found:
            self._found[source] = station_median(self.shares.get(source, ()))
        return self._found[source]


def _own_reads(  # noqa: PLR0913, PLR0917 - one day of the record and how to read it
    when: date,
    slots: Mapping[str, Slot],
    closing: Closing,
    lit: AbstractSet[str],
    placed: Callable[[str], float | None],
    vouch: PeerVouch,
    stats: "ListStats",
) -> tuple[dict[str, int], dict[str, int]]:
    """One day's lists whose own read passed the list-level checks of :func:`counted_days`
    and was closing-size, each with its largest such read; and each list's longest read
    that vouches for a market peer by :class:`PeerVouch` (``stats`` as they stood that day),
    both from slots wholly inside the read window of a district ``lit`` that day."""
    settings = closing.rule.labels
    windows: dict[str, tuple[datetime, datetime]] = {}

    def inside(leaid: str, at: datetime) -> bool:
        zone = closing.zones.get(leaid)
        if zone is None:
            return False
        if zone not in windows:
            windows[zone] = window_of(when, zone, settings)
        start, end = windows[zone]
        return start <= at and at + timedelta(minutes=SLOT_MINUTES) <= end

    named_markets = frozenset(
        vouch.market_of.get(source, source)
        for slot in slots.values()
        for source, named in slot.by.items()
        if named
    )
    best: dict[str, int] = {}
    longest: dict[str, int] = {}
    for key, slot in sorted(slots.items()):
        at = slot_start(when, key)
        timely = frozenset(leaid for leaid in lit if inside(leaid, at))
        if not timely or slot.shown != {vouch.prefix} or not closing.rule.healthy(slot):
            continue

        def warned_lit(leaid: str, _day: date, timely: AbstractSet[str] = timely) -> bool:
            return leaid in timely

        for source, reads in slot.reads.items():
            if source in slot.stale:
                continue
            rows = max(
                (
                    n
                    for n, kept, unread in reads
                    if n > 0
                    and unread / n <= UNREADABLE_SHARE
                    and not low_match(kept / n, placed(source))
                ),
                default=0,
            )
            if not rows:
                continue
            if vouch.vouches(source, rows, slot, stats, named_markets):
                longest[source] = max(longest.get(source, 0), rows)
            if closing_size(((leaid, when) for leaid in slot.by.get(source, ())), warned_lit):
                best[source] = max(best.get(source, 0), rows)
    return best, longest


def captures_of(counted: Mapping[date, Mapping[str, int]], day: date, days: int) -> LiveCaptures:
    """The sources' counted days (:func:`counted_days`) in the ``days`` UTC days of the
    record before ``day``, with their values."""
    count: Counter[str] = Counter()
    rows: dict[str, list[int]] = defaultdict(list)
    for when, largest in sorted(counted.items()):
        if not day - timedelta(days=days) <= when < day:
            continue
        for source, most in largest.items():
            count[source] += 1
            rows[source].append(most)
    return LiveCaptures(
        days=dict(sorted(count.items())),
        storm_rows={source: tuple(sorted(found)) for source, found in sorted(rows.items())},
    )


def live_captures(  # noqa: PLR0913 - the record, the day and the rule's inputs
    log: MorningLog,
    day: date,
    days: int,
    closing: Closing,
    *,
    market_of: Mapping[str, str],
    prefix: str,
) -> LiveCaptures:
    """The sources' counted days in the record's ``days`` UTC days before ``day``."""
    return captures_of(counted_days(log, closing, market_of=market_of, prefix=prefix), day, days)


@dataclass(frozen=True, slots=True)
class ListStats:
    """Each source's captures and the **reference** rows of its closing-size lists, for the
    station gates (``thin_station``, ``small_capture``) and tier B.

    ``captures``: the archive's captures and the live record's counted days before the day
    (``thin_station``: a list caught under ``station_min_captures`` times is never read).
    ``closing``: the archive's closing-size days and the live record's counted days (lead
    ruling B1.4: a tier B list needs ``min_captures`` of these; quiet and advisory days, and
    days its own read did not count, never do).

    The reference is :func:`reference_of`: the median over the source's closing-size
    captures (each closing-size archive day's largest capture, :func:`closing_rows`, and one
    value per counted live day), never under the archive's median when the archive alone
    holds ``least``. A source with under ``least`` of them has a **thin reference**
    (``thin``, lead ruling B1.2): on a storm day a populated read of it counts only when the
    longest read in the window of a market peer that vouches (:class:`PeerVouch`)
    corroborates its length, and an empty read of it never (:class:`_Windows`)."""

    captures: Mapping[str, int]
    median_rows: Mapping[str, float]
    closing: Mapping[str, int] = field(default_factory=dict)
    thin: frozenset[str] = frozenset()

    @classmethod
    def of(cls, coverage: Coverage, live: LiveCaptures, least: int = 0) -> "ListStats":
        sources = sorted(set(coverage.captures) | set(live.days) | set(live.storm_rows))
        median = {
            source: reference_of(
                coverage.rows.get(source, ()), live.storm_rows.get(source, ()), least
            )
            for source in sources
        }
        return cls(
            captures={s: coverage.captures.get(s, 0) + live.days.get(s, 0) for s in sources},
            median_rows=median,
            closing={
                s: len(coverage.rows.get(s, ())) + len(live.storm_rows.get(s, ())) for s in sources
            },
            thin=frozenset(s for s, found in median.items() if math.isinf(found)),
        )


@dataclass(slots=True)
class _Windows:
    """One day's slots per (zone, state, storm, warning), each source's whole reads in them."""

    morning: Morning
    rule: ReadRule
    stats: ListStats
    district_sites: AbstractSet[str] = frozenset()
    found: dict[tuple[str, str, bool, bool], dict[str, Qualified]] = field(default_factory=dict)
    withheld: dict[tuple[str, str, bool, bool], bool] = field(default_factory=dict)
    """Whether a slot of the window was left out because a pass withheld the state."""
    _named_markets: frozenset[str] | None = None

    def named_markets(self) -> frozenset[str]:
        """The markets some list of which named a district for the day in the day's record
        (its ``by``): the market had closings or delays that morning (lead ruling B1.3)."""
        if self._named_markets is None:
            self._named_markets = frozenset(
                self.morning.market_of.get(source, source)
                for slot in self.morning.slots.values()
                for source, named in slot.by.items()
                if named
            )
        return self._named_markets

    def of(  # noqa: PLR0912, PLR0915 - one window's checks, in the rule's order
        self, zone: str, state: str, storm: bool, warning: bool = False
    ) -> dict[str, Qualified]:
        key = (zone, state, storm, warning)
        if key in self.found:
            return self.found[key]
        settings = self.rule.labels
        start, end = window_of(self.morning.day, zone, settings)
        every = [
            (at, slot)
            for at, slot in sorted(self.morning.slots.items())
            if start <= at and at + timedelta(minutes=SLOT_MINUTES) <= end
        ]
        last = end - timedelta(minutes=SLOT_MINUTES)
        ran_through = any(last <= at < end for at in self.morning.slots)
        shown = [
            (at, slot) for at, slot in every if ran_through and slot.shown == {self.morning.prefix}
        ]
        qualified = [
            (at, slot)
            for at, slot in shown
            if (state not in slot.unknown if state else not slot.unknown)
        ]
        self.withheld[key] = len(qualified) < len(shown)
        everything = [slot for _at, slot in every]
        windows: list[tuple[datetime, Slot, bool | None, dict[str, _Current]]] = []
        for at, slot in qualified:
            reads = station_window([slot], everything, self.morning, settings)
            current = {s: _current(item, stale=s in slot.stale) for s, item in reads.items()}
            windows.append((at, slot, self.rule.healthy(slot), current))
        named_markets = self.named_markets() if warning else frozenset()

        def stale(source: str, slot: Slot, kind: str | None) -> bool:
            # A populated list the reader judged from old rows (its rows name only days
            # before the day before: the record's ``stale``), on any morning; or, on a
            # warning-or-above morning, one naming nothing for the day while its market
            # named closings (lead ruling B1.3).
            if kind != "populated":
                return False
            if source in slot.stale:
                return True
            market = self.morning.market_of.get(source, source)
            return not slot.by.get(source) and market in named_markets

        # The market peers a list may need on a storm day: lists whose read passed every gate
        # by its own reference (never by a peer's) in a healthy slot of the window, and is not
        # a stale populated list; and the longest read of each that vouches for a peer's
        # length by the one rule the counted days apply too (:class:`PeerVouch`).
        vouch = PeerVouch(
            self.rule, self.morning.prefix, self.district_sites, self.morning.market_of
        )
        readers: dict[str, set[str]] = defaultdict(set)
        longest: dict[str, int] = {}
        for _at, slot, healthy, current in windows:
            for source, item in current.items():
                stage, kind = self._gate(source, item, storm=storm)
                if healthy and stage is None and not stale(source, slot, kind):
                    readers[self.morning.market_of.get(source, source)].add(source)
                    rows = max(item.populated, default=0)
                    if vouch.vouches(source, rows, slot, self.stats, named_markets):
                        longest[source] = max(longest.get(source, 0), rows)
        stages: dict[str, int] = {}
        good: dict[str, list[datetime]] = defaultdict(list)
        unplaced: set[str] = set()
        for at, slot, healthy, current in windows:
            for source, item in current.items():
                market = self.morning.market_of.get(source, source)
                peers = readers[market] - {source}
                stage, kind = self._gate(source, item, storm=storm)
                if (
                    stage == STAGES.index(NotRead.SMALL_CAPTURE)
                    and source in self.stats.thin
                    and self._corroborated(item, [longest[p] for p in peers if p in longest])
                ):
                    stage, kind = None, "populated"
                if stage is None and storm and kind == "empty" and not peers:
                    stage = STAGES.index(NotRead.EMPTY_UNCORROBORATED)
                if stage is None and storm and kind == "empty" and source in self.stats.thin:
                    # Lead ruling B1.2 for an empty list: a thin reference's length is
                    # vouched for only by a peer's read that vouches (:class:`PeerVouch`),
                    # which is never empty, and 0 rows is never ``capture_min_share`` of it.
                    stage = STAGES.index(NotRead.SMALL_CAPTURE)
                if stage is None and stale(source, slot, kind):
                    stage = STAGES.index(NotRead.STALE_POPULATED)
                if stage is None and healthy is None:
                    stage = STAGES.index(NotRead.HEALTH_UNRECORDED)
                elif stage is None and not healthy:
                    stage = STAGES.index(NotRead.UNHEALTHY)
                elif stage is None:
                    good[source].append(at)
                    if any(rows > placed for rows, placed, _ in slot.reads.get(source, ())):
                        unplaced.add(source)
                    stage = len(STAGES)
                stages[source] = max(stages.get(source, 0), stage)
        found = {
            source: Qualified(
                tuple(good.get(source, ())),
                None if stage == len(STAGES) else STAGES[stage],
                unplaced=source in unplaced,
            )
            for source, stage in sorted(stages.items())
        }
        self.found[key] = found
        return found

    def _corroborated(self, item: "_Current", peers: Sequence[int]) -> bool:
        """Lead ruling B1.2: a populated read of a list with a thin reference is whole on a
        storm day only when it holds at least ``capture_min_share`` of the **longest** gated
        market peer's whole read in the window (review R5-S1: as for an empty read, every
        peer must vouch, so a short peer never vouches for a list while a longer one read a
        storm-size list)."""
        longest = max(peers, default=0)
        if not item.populated or longest <= 0:
            return False
        return max(item.populated) >= self.rule.labels.capture_min_share * longest

    def _gate(self, source: str, item: "_Current", *, storm: bool) -> tuple[int | None, str | None]:
        """What the station gates made of the slot's reads of ``source`` (``populated``,
        ``empty`` or ``None``), with ``None`` when they are whole after the station gates
        (:func:`~snowlight.predict.labels.station_reads`, the archive's and S7-L's rule, with
        an empty read of a list under ``station_min_captures`` refused too: a list too thin
        to tell a whole read from a partial one is never read, populated or empty); else the
        stage it stopped at. (The market peer an empty list needs on a storm day is the
        caller's.)"""
        kind, reason = station_reads(
            source,
            item.read,
            storm,
            captures=self.stats.captures,
            median_rows=self.stats.median_rows,
            settings=self.rule.labels,
        )
        thin = self.stats.captures.get(source, 0) < self.rule.labels.station_min_captures
        if kind == "empty" and thin:
            return STAGES.index(NotRead.THIN_STATION), kind
        if kind is not None:
            return None, kind
        if reason is Unread.THIN_STATION:
            return STAGES.index(NotRead.THIN_STATION), kind
        if reason is Unread.SMALL_CAPTURE:
            return STAGES.index(NotRead.SMALL_CAPTURE), kind
        if item.stale:
            return STAGES.index(NotRead.STALE_EMPTY), kind
        return _refused_stage(item.read), kind


@dataclass(frozen=True, slots=True)
class _Current:
    """One slot's reads of a source with an empty judged from old rows taken out."""

    read: StationRead
    stale: bool

    @property
    def populated(self) -> tuple[int, ...]:
        return self.read.populated

    @property
    def empty(self) -> bool:
        return self.read.empty


def _current(item: StationRead, *, stale: bool) -> _Current:
    if stale and item.empty:
        return _Current(StationRead(item.populated, False, item.refused), stale=True)
    return _Current(item, stale=False)


def _refused_stage(item: StationRead) -> int:
    if Unread.VOIDED_EMPTY in item.refused:
        return STAGES.index(NotRead.VOIDED_EMPTY)
    if Unread.DROPPED_READ in item.refused:
        return STAGES.index(NotRead.DROPPED_READ)
    return 0


def _storm(klass: WeatherClass | None) -> bool:
    return klass is not None and klass is not WeatherClass.NONE


def _warning(klass: WeatherClass | None) -> bool:
    return klass in WARNING_CLASSES


def read_set(  # noqa: PLR0913 - the day's record and the rule
    morning: Morning,
    *,
    directory: Directory,
    coverage: Coverage,
    recent: Mapping[str, int],
    rule: ReadRule,
    stats: ListStats | None = None,
    weather: Sequence[WeatherClass | None] | None = None,
    districts: Iterable[int] | None = None,
    windows: "_Windows | None" = None,
) -> dict[str, Read | NotRead]:
    """Which deployed districts were read on the morning's day, and why the others were not
    (every district of ``districts``, positions in the directory; all by default). It reads
    the record's reads, shown prefixes, withheld states, stale empties and healthy shares,
    the coverage, the live audience before the day (``morning.audience``), each source's
    captures before the day (``stats``) and each district's class at the snapshot
    (``weather``: a storm day's gates) only: never what a list named nor what the map lit,
    but for one list-level check of a warning-or-above morning (lead ruling B1.3,
    ``stale_populated``: a populated list naming nothing for the day while another list of
    its market named districts for it)."""
    stats = (
        stats
        if stats is not None
        else ListStats.of(coverage, LiveCaptures(), rule.labels.station_min_captures)
    )
    windows = (
        windows if windows is not None else _Windows(morning, rule, stats, coverage.district_sites)
    )
    found: dict[str, Read | NotRead] = {}
    positions = range(len(directory.districts)) if districts is None else districts
    for index in positions:
        leaid = directory.districts[index]
        candidates = coverage.candidates(leaid, morning.day, morning.audience, stats.closing)
        if not candidates:
            found[leaid] = NotRead.NOT_COVERED
            continue
        storm = _storm(weather[index]) if weather is not None else False
        warning = _warning(weather[index]) if weather is not None else False
        window = windows.of(directory.zones[index], district_state(leaid), storm, warning)
        whole = {s: window[s] for s in candidates if s in window and window[s].stage is None}
        markets = Counter(morning.market_of.get(s, s) for s in whole)
        fresh = sorted(
            s
            for s in whole
            if recent.get(s, 0) >= 1 or markets[morning.market_of.get(s, s)] >= 2  # noqa: PLR2004
        )
        if fresh:
            tier = Tier.A if any(candidates[s] is Tier.A for s in fresh) else Tier.B
            first = min(at for s in fresh for at in whole[s].slots)
            slot = morning.slots[first]
            lead = sorted(fresh, key=lambda s: (candidates[s] is not Tier.A, s))[0]
            found[leaid] = Read(
                tier=tier,
                sources=tuple(fresh),
                market=morning.market_of.get(lead, lead),
                slot=first,
                health=slot.health if slot.health is not None else 0,
                unplaced=any(whole[s].unplaced for s in fresh),
            )
            continue
        if whole:
            found[leaid] = NotRead.NOT_RECENT
            continue
        reached = [window[s].stage for s in candidates if s in window]
        stage = max((STAGES.index(r) for r in reached if r is not None), default=0)
        withheld = windows.withheld.get(
            (directory.zones[index], district_state(leaid), storm, warning)
        )
        if stage == 0 and withheld:
            found[leaid] = NotRead.WITHHELD_STATE
            continue
        found[leaid] = STAGES[stage]
    return found


# --- one day's labels ---------------------------------------------------------------------------


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ReadRow(_Row):
    """One alerted district-day (private): its class, label and how it was read."""

    district: str = Field(pattern=r"^\d{7}$")
    weather: int = Field(ge=1, le=7)
    after: bool | None
    """The map lit the district no school on its previous school day (read or not; ``None``:
    what the map showed that day is not known)."""
    label: Label
    why: str | None
    tier: Tier | None
    market: str | None
    sources: tuple[str, ...]
    slot: str | None
    """The first qualifying slot's UTC start, ``HH:MM``."""
    health: int | None = Field(ge=0, le=PERMILLE)
    unplaced: bool = False
    """A qualifying read held rows the matcher placed nowhere: the district's own row may be
    among them, so the weekly hand audit checks the read lists' unmatched rows for an
    ``unnamed`` row with it."""


class Trial(_Row):
    """One co-listing trial (private): a source that read a lit district, and whether its own
    rows named it: in a slot it qualified in (``named``, the registered estimand of s_A and
    s_B), and anywhere in the day's record of its whole reads (``named_in_day``; ``None`` in
    a record written before it was kept). The label rule keeps a district from ``unnamed``
    when any list named it anywhere in the day, so ``named_in_day`` is the event an unnamed
    row's correction turns on; ``named`` is never above it, so s from ``named`` is biased low
    (toward more closings hidden among unnamed rows)."""

    district: str = Field(pattern=r"^\d{7}$")
    source: str
    tier: Tier
    named: bool
    weather: int = Field(ge=0, le=7)
    named_in_day: bool | None = None


class ReadDay(_Row):
    """``reads/rows/<day>.json``: one labeled school day of the outcome-blind record."""

    schema_version: Literal[1]
    day: date
    content: str
    """The directory content the district positions were read against."""
    rows: tuple[ReadRow, ...]
    no_school: tuple[str, ...]
    """Every district (any class, read or not) the map lit no school: the next school day's
    ``after``."""
    audit: ReadAuditDay

    def to_bytes(self) -> bytes:
        return dumps_json(self.model_dump(mode="json"))

    @classmethod
    def from_bytes(cls, data: bytes) -> "ReadDay":
        """Raises:
        pydantic.ValidationError: it is not one."""
        return cls.model_validate_json(data, strict=False)


@dataclass(frozen=True, slots=True)
class Labeled:
    """One day's outcome-blind labels: the alerted rows, the trials, the audit counts, and
    every district the map lit no school (any class, read or not: the next day's ``after``)."""

    rows: list[ReadRow]
    trials: list[Trial]
    audit: ReadAuditDay
    no_school: frozenset[str]


@dataclass(slots=True)
class _Tally:
    alerted: int = 0
    covered: int = 0
    read: Counter[str] = field(default_factory=Counter)
    labels: Counter[str] = field(default_factory=Counter)
    unknown: Counter[str] = field(default_factory=Counter)
    not_read: Counter[str] = field(default_factory=Counter)
    named: int = 0
    unplaced: int = 0
    health: list[int] = field(default_factory=list)
    trials: Counter[str] = field(default_factory=Counter)
    hits: Counter[str] = field(default_factory=Counter)

    def counts(self, weather: str) -> ReadClass:
        return ReadClass(
            weather=weather,  # type: ignore[arg-type]
            alerted=self.alerted,
            covered=self.covered,
            read_a=self.read[Tier.A],
            read_b=self.read[Tier.B],
            named=self.named,
            lit_no_school=self.labels[Label.NO_SCHOOL],
            lit_delayed=self.labels[Label.DELAYED],
            unnamed=self.labels[Label.UNNAMED],
            unnamed_unplaced=self.unplaced,
            unknown_listed=self.unknown[Why.LISTED_UNREAD],
            unknown_partly_lit=self.unknown[Why.PARTLY_LIT],
            unknown_retracted=self.unknown[Why.RETRACTED],
            unknown_break=self.unknown[Why.BREAK],
            unknown_absent=self.unknown[Why.ABSENT_IN_STORM],
            not_covered=self.not_read[NotRead.NOT_COVERED],
            withheld_state=self.not_read[NotRead.WITHHELD_STATE],
            no_whole_read=self.not_read[NotRead.NO_WHOLE_READ],
            dropped_read=self.not_read[NotRead.DROPPED_READ],
            voided_empty=self.not_read[NotRead.VOIDED_EMPTY],
            stale_empty=self.not_read[NotRead.STALE_EMPTY],
            stale_populated=self.not_read[NotRead.STALE_POPULATED],
            thin_list=self.not_read[NotRead.THIN_STATION],
            small_capture=self.not_read[NotRead.SMALL_CAPTURE],
            empty_uncorroborated=self.not_read[NotRead.EMPTY_UNCORROBORATED],
            health_unrecorded=self.not_read[NotRead.HEALTH_UNRECORDED],
            unhealthy=self.not_read[NotRead.UNHEALTHY],
            not_recent=self.not_read[NotRead.NOT_RECENT],
            median_health=round(statistics.median(self.health)) if self.health else None,
            trials_a=self.trials[Tier.A],
            hits_a=self.hits[Tier.A],
            trials_b=self.trials[Tier.B],
            hits_b=self.hits[Tier.B],
        )


@dataclass(frozen=True, slots=True)
class _Told:
    """One read district's label before the storm-absence rule."""

    leaid: str
    weather: WeatherClass
    label: Label
    why: Why | None
    lit_share: float
    read: Read


def _label(  # noqa: PLR0913 - the district, its day and the rules
    leaid: str,
    schools: Sequence[int],
    weather: WeatherClass,
    *,
    lit: Lit,
    morning: Morning,
    zone: str,
    settings: LabelSettings,
) -> tuple[Label, Why | None, float, frozenset[str]]:
    """A read district's label (before the storm-absence rule), its lit share, and the
    status kinds a list named it with."""
    found = shares(
        [str(s) for s in schools],
        {str(s): lit.statuses[s] for s in schools if s in lit.statuses},
        weather,
    )
    del zone  # a naming anywhere in the day's record counts, not only up to the window's end
    named = named_on(morning, leaid, _day_end(morning.day))
    shown = frozenset(KIND_OF[lit.statuses[s].status] for s in schools if s in lit.statuses)
    outcome = outcome_of(found, read=True, settings=settings)
    if likely_break(morning.day):
        return Label.UNKNOWN, Why.BREAK, found.any_status, named
    if any(s in lit.retracted for s in schools):
        return Label.UNKNOWN, Why.RETRACTED, found.any_status, named
    if listed_unread(outcome, named, shown):
        return Label.UNKNOWN, Why.LISTED_UNREAD, found.any_status, named
    label = {
        Outcome.NO_SCHOOL: Label.NO_SCHOOL,
        Outcome.DELAYED: Label.DELAYED,
        Outcome.OPEN: Label.UNNAMED,
    }.get(outcome)
    if label is None or (label is Label.UNNAMED and found.any_status > 0):
        # Unnamed is dark: a school lit with no list naming the district (an override, or a
        # closing lit on an earlier log day) is never counted open.
        return Label.UNKNOWN, Why.PARTLY_LIT, found.any_status, named
    return label, None, found.any_status, named


def _day_end(day: date) -> datetime:
    """Past every slot of the UTC day's record."""
    return datetime.combine(day + timedelta(days=1), time(), tzinfo=UTC)


def lit_no_school(
    lit: Lit,
    directory: Directory,
    weather: Sequence[WeatherClass | None],
    settings: LabelSettings,
) -> frozenset[str]:
    """Every district the map lit no school (at least ``no_school_share`` of its eligible
    schools closed or remote for the weather), read or not: the next school day's ``after``."""
    found: set[str] = set()
    for index, leaid in enumerate(directory.districts):
        schools = [str(s) for s in directory.eligible[index].tolist()]
        klass = weather[index] or WeatherClass.NONE
        statuses = {s: lit.statuses[int(s)] for s in schools if int(s) in lit.statuses}
        if (
            statuses
            and outcome_of(shares(schools, statuses, klass), read=True, settings=settings)
            is Outcome.NO_SCHOOL
        ):
            found.add(leaid)
    return frozenset(found)


def _absent_in_storm(told: Sequence[_Told], share: float) -> set[str]:
    """The storm-day unnamed districts dark while at least ``share`` of the other known read
    districts of their market had no school (the archive's ``absent_in_storm`` rule)."""
    known: Counter[str] = Counter()
    closed: Counter[str] = Counter()
    for item in told:
        if item.label is not Label.UNKNOWN:
            known[item.read.market] += 1
            closed[item.read.market] += item.label is Label.NO_SCHOOL
    found: set[str] = set()
    for item in told:
        others = known[item.read.market] - 1
        if (
            item.label is Label.UNNAMED
            and item.weather is not WeatherClass.NONE
            and item.lit_share == 0.0
            and others > 0
            and closed[item.read.market] / others >= share
        ):
            found.add(item.leaid)
    return found


def label_read_day(  # noqa: PLR0913, PLR0912, PLR0915 - the day, its inputs and the rules
    day: date,
    *,
    morning: Morning,
    coverage: Coverage,
    weather: Sequence[WeatherClass | None],
    lit: Lit,
    directory: Directory,
    rule: ReadRule,
    recent: Mapping[str, int],
    live: LiveCaptures | None = None,
    lit_by: Mapping[str, Mapping[str, datetime]] | None = None,
    after: frozenset[str] | None = frozenset(),
) -> Labeled:
    """One school day's outcome-blind labels (see the module docstring): the read set first
    (:func:`read_set`), then what the lists named and the map lit. ``weather`` is each
    deployed district's class at its snapshot; ``lit_by`` the sources whose rows lit or
    changed each district's schools for the day, each with when it first did (from the
    change log; ``None``: unknown, so no trials); ``after`` the districts the map lit no
    school on the previous school day (``None``: not known); ``recent`` each source's days
    with a populated read in the rule's recent days before, ``live`` its captures in the
    whole record before (none when not given)."""
    settings = rule.labels
    tallies: dict[str, _Tally] = defaultdict(_Tally)
    no_school = lit_no_school(lit, directory, weather, settings)
    if morning.held or not is_school_day(day):
        return Labeled([], [], ReadAuditDay(day=day, held=morning.held, classes=()), no_school)
    stats = ListStats.of(
        coverage,
        live if live is not None else LiveCaptures(),
        settings.station_min_captures,
    )
    windows = _Windows(morning, rule, stats, coverage.district_sites)
    reads = read_set(
        morning,
        directory=directory,
        coverage=coverage,
        recent=recent,
        rule=rule,
        stats=stats,
        weather=weather,
        windows=windows,
    )
    told: list[_Told] = []
    named_of: dict[str, frozenset[str]] = {}
    for index, leaid in enumerate(directory.districts):
        klass = weather[index]
        key = klass.label if klass is not None else UNCLASSED
        tally = tallies[key]
        tally.alerted += 1
        found = reads[leaid]
        schools = [int(s) for s in directory.eligible[index].tolist()]
        if not schools:
            found = NotRead.NOT_COVERED
        if found is not NotRead.NOT_COVERED:
            tally.covered += 1
        if isinstance(found, NotRead):
            tally.not_read[found] += 1
            continue
        if klass is None:
            tally.read[found.tier] += 1
            continue
        label, why, lit_share, named = _label(
            leaid, schools, klass, lit=lit, morning=morning, zone=directory.zones[index],
            settings=settings,
        )  # fmt: skip
        named_of[leaid] = named
        told.append(_Told(leaid, klass, label, why, lit_share, found))
    absent = _absent_in_storm(told, settings.storm_absence_share)
    rows: list[ReadRow] = []
    trials: list[Trial] = []
    position = {leaid: i for i, leaid in enumerate(directory.districts)}

    def after_of(leaid: str) -> bool | None:
        return None if after is None else leaid in after

    for item in told:
        label, why = item.label, item.why
        if item.leaid in absent:
            label, why = Label.UNKNOWN, Why.ABSENT_IN_STORM
        tally = tallies[item.weather.label]
        tally.read[item.read.tier] += 1
        tally.named += bool(named_of[item.leaid])
        tally.health.append(item.read.health)
        if label is Label.UNKNOWN and why is not None:
            tally.unknown[why] += 1
        else:
            tally.labels[label] += 1
            tally.unplaced += label is Label.UNNAMED and item.read.unplaced
        if label is Label.NO_SCHOOL and lit_by is not None:
            for trial in _trials(
                item,
                windows=windows,
                coverage=coverage,
                lit_by=lit_by,
                directory=directory,
                position=position,
            ):
                trials.append(trial)
                tally.trials[trial.tier] += 1
                tally.hits[trial.tier] += trial.named
        if item.weather is not WeatherClass.NONE:
            rows.append(
                ReadRow(
                    district=item.leaid,
                    weather=int(item.weather),
                    after=after_of(item.leaid),
                    label=label,
                    why=None if why is None else why.value,
                    tier=item.read.tier,
                    market=item.read.market,
                    sources=item.read.sources,
                    slot=item.read.slot.astimezone(UTC).strftime("%H:%M"),
                    health=item.read.health,
                    unplaced=item.read.unplaced,
                )
            )
    for index, leaid in enumerate(directory.districts):
        klass = weather[index]
        found = reads[leaid]
        if not directory.eligible[index].size:
            found = NotRead.NOT_COVERED
        if klass is None or klass is WeatherClass.NONE or not isinstance(found, NotRead):
            continue
        rows.append(
            ReadRow(
                district=leaid, weather=int(klass), after=after_of(leaid), label=Label.NOT_READ,
                why=found.value, tier=None, market=None, sources=(), slot=None, health=None,
            )
        )  # fmt: skip
    classes = tuple(tallies[key].counts(key) for key in sorted(tallies, key=_class_order))
    rows.sort(key=lambda row: row.district)
    trials.sort(key=lambda t: (t.district, t.source))
    return Labeled(rows, trials, ReadAuditDay(day=day, held=False, classes=classes), no_school)


def _class_order(key: str) -> int:
    if key == UNCLASSED:
        return len(WeatherClass)
    return int(WeatherClass[key.upper()])


def _trials(  # noqa: PLR0913 - one lit district and the day
    item: _Told,
    *,
    windows: _Windows,
    coverage: Coverage,
    lit_by: Mapping[str, Mapping[str, datetime]],
    directory: Directory,
    position: Mapping[str, int],
) -> list[Trial]:
    """The co-listing trials of one lit district: each of its qualifying sources that had
    not lit it by its window's end, named or not by its own rows in a slot it qualified in
    (``named``, the registered estimand), and named or not by its own whole reads anywhere in
    the day's record (``named_in_day``: the event the label rule's ``unnamed`` turns on)."""
    morning = windows.morning
    captures = windows.stats.closing
    candidates = coverage.candidates(item.leaid, morning.day, morning.audience, captures)
    index = position[item.leaid]
    zone = directory.zones[index]
    window = windows.of(
        zone, district_state(item.leaid), _storm(item.weather), _warning(item.weather)
    )
    end = window_of(morning.day, zone, windows.rule.labels)[1]
    lighting = {s for s, at in lit_by.get(item.leaid, {}).items() if at < end}
    every = list(morning.slots.values())
    found: list[Trial] = []
    for source in item.read.sources:
        if source in lighting:
            continue
        qualified = window.get(source)
        if qualified is None or qualified.stage is not None:
            continue
        named = any(item.leaid in morning.slots[at].by.get(source, ()) for at in qualified.slots)
        in_day = named or any(item.leaid in slot.by.get(source, ()) for slot in every)
        found.append(
            Trial(
                district=item.leaid,
                source=source,
                tier=candidates[source],
                named=named,
                weather=int(item.weather),
                named_in_day=in_day,
            )
        )
    return found


# --- the inputs, as the step sees them -----------------------------------------------------------


class ReadSource(LiveSource, Protocol):
    """The live days (:class:`~snowlight.predict.live_labels.LiveSource`) and, for the read
    rule, each source's counted days and the sources that lit each district."""

    def captures(self, day: date, days: int, closing: Closing | None = None) -> LiveCaptures:
        """Each source's counted days (:func:`counted_days`, lead ruling C2) in the ``days``
        UTC days of the record before ``day``, with their values (none without
        ``closing``)."""
        ...

    def lit_by(self, day: date) -> Mapping[str, Mapping[str, datetime]] | None:
        """The sources whose rows lit each district's schools for ``day``, with when each
        first did (``None``: unknown)."""
        ...


class ChangeDays(Protocol):
    """The change log's days and each day's changes (:class:`~snowlight.live.history.
    ChangeLog`, or :class:`LoadedChanges`)."""

    def days(self) -> list[date]: ...

    def changes(self, day: date) -> list[Change]: ...


@dataclass(frozen=True, slots=True)
class LoadedChanges:
    """A change log read once (one run reads it for every day it labels)."""

    by_day: Mapping[date, Sequence[Change]]

    @classmethod
    def of(cls, log: ChangeLog) -> "LoadedChanges":
        return cls({day: tuple(log.changes(day)) for day in log.days()})

    def days(self) -> list[date]:
        return sorted(self.by_day)

    def changes(self, day: date) -> list[Change]:
        return list(self.by_day.get(day, ()))


def lit_sources(changes: ChangeDays, day: date) -> dict[str, dict[str, datetime]]:
    """The sources a lit or changed status of each district's schools for ``day`` came from,
    each with the first time it did: every log day up to ``day`` (a closing announced days
    ahead is lit on an earlier day's log)."""
    found: dict[str, dict[str, datetime]] = defaultdict(dict)
    for logged in changes.days():
        if logged > day:
            break
        for change in changes.changes(logged):
            source = change.fields.get("source_id")
            district = leaid_of(change.nces_id)
            if (
                change.day == day
                and change.event in (Event.LIT, Event.CHANGED)
                and isinstance(source, str)
                and district
            ):
                first = found[district].get(source)
                if first is None or change.at < first:
                    found[district][source] = change.at
    return {district: dict(sorted(found[district].items())) for district in sorted(found)}


def audience_before(changes: ChangeDays, day: date, min_days: int) -> dict[str, dict[str, date]]:
    """Each source's live audience before ``day`` (the S7-L rule,
    :func:`~snowlight.predict.live_labels.audience_of`, on the change log's days before
    ``day`` and lightings of days before ``day`` only): what the lists lit on ``day``, or
    for a later day on ``day``'s log, never decides who reads ``day``."""
    listings: list[tuple[str, str, date]] = []
    for logged in changes.days():
        if logged >= day:
            break
        for change in changes.changes(logged):
            source = change.fields.get("source_id")
            district = leaid_of(change.nces_id)
            if (
                change.day < day
                and change.event in (Event.LIT, Event.CHANGED)
                and source
                and district
            ):
                listings.append((str(source), district, change.day))
    return audiences(listings, min_days)


# --- the record ---------------------------------------------------------------------------------


def rows_path(folder: Path, day: date) -> Path:
    return folder / "rows" / f"{day.isoformat()}.json"


def trials_path(folder: Path, day: date) -> Path:
    return folder / "trials" / f"{day.isoformat()}.jsonl"


def audit_path(folder: Path, day: date) -> Path:
    return folder / "audit" / f"{day.isoformat()}.json"


SUMMARY: Final = "summary.json"
"""The private report of the record (:func:`report_of`), rewritten every run."""


def labeled_days(folder: Path) -> list[date]:
    """The days the record holds, oldest first."""
    found: list[date] = []
    root = folder / "rows"
    if root.is_dir():
        for path in root.glob("*.json"):
            try:
                found.append(date.fromisoformat(path.stem))
            except ValueError:
                continue
    return sorted(found)


def read_day(folder: Path, day: date) -> ReadDay | None:
    """The record's day, ``None`` when it holds none.

    Raises:
        ValueError: the file does not read.
    """
    path = rows_path(folder, day)
    if not path.is_file():
        return None
    return ReadDay.from_bytes(path.read_bytes())


def audit_bytes(found: ReadAuditDay) -> bytes:
    """One day's audit counts as the evidence store keeps them."""
    return dumps_json(found.model_dump(mode="json"))


def write_day(folder: Path, found: ReadDay, trials: Sequence[Trial]) -> None:
    """Write one labeled day (its trials and audit first: a day is labeled once its rows file
    is there)."""
    lines = b"".join(dumps_json(t.model_dump(mode="json")) + b"\n" for t in trials)
    write_bytes_atomic(trials_path(folder, found.day), lines)
    write_bytes_atomic(audit_path(folder, found.day), audit_bytes(found.audit))
    write_bytes_atomic(rows_path(folder, found.day), found.to_bytes())


def audit_of(folder: Path, now: datetime, held: ReadAudit | None = None) -> ReadAudit:
    """The public audit: every labeled day's counts (codes and counts only). A day the
    published audit (``held``) already holds keeps its published counts, and one it holds
    that the record lacks (the Actions cache lost it; the evidence store keeps it) stays:
    the audit never rewrites or drops its own history."""
    days = {item.day: item for item in held.days} if held is not None else {}
    for day in labeled_days(folder):
        if day in days:
            continue
        found = read_day(folder, day)
        if found is not None:
            days[day] = found.audit
    return ReadAudit(
        schema_version=1,
        generated_at=now.astimezone(UTC).replace(microsecond=0),
        days=tuple(days[day] for day in sorted(days)),
    )


def trial_totals(audit: ReadAudit) -> dict[Tier, tuple[int, int]]:
    """Trials and hits per tier over every day and class."""
    trials: Counter[Tier] = Counter()
    hits: Counter[Tier] = Counter()
    for item in audit.days:
        for counts in item.classes:
            trials[Tier.A] += counts.trials_a
            hits[Tier.A] += counts.hits_a
            trials[Tier.B] += counts.trials_b
            hits[Tier.B] += counts.hits_b
    return {tier: (trials[tier], hits[tier]) for tier in Tier}


# --- the private report (G1's numbers) ----------------------------------------------------------

BETA_GRID: Final = 20_001


def beta_interval(a: float, b: float, mass: float = 0.9) -> tuple[float, float]:
    """The central ``mass`` interval of Beta(a, b) (a, b above 0), by its distribution
    function on a fine grid (to about 1e-4); a parameter under 1 (the Jeffreys prior's 0.5)
    makes the density unbounded at that end, so that end's first cell takes its exact mass
    there."""
    grid = np.linspace(0.0, 1.0, BETA_GRID)
    step = float(grid[1])
    with np.errstate(divide="ignore", invalid="ignore"):
        log_pdf = (a - 1) * np.log(grid) + (b - 1) * np.log1p(-grid)
    finite = np.isfinite(log_pdf)
    top = float(log_pdf[finite].max())
    pdf = np.where(finite, np.exp(np.where(finite, log_pdf, top) - top), 0.0)
    cells = (pdf[1:] + pdf[:-1]) / 2 * step
    if a < 1:
        cells[0] = math.exp(-top) * step**a / a
    if b < 1:
        cells[-1] = math.exp(-top) * step**b / b
    cdf = np.concatenate(([0.0], np.cumsum(cells)))
    cdf /= cdf[-1]
    tail = (1 - mass) / 2
    low = float(np.interp(tail, cdf, grid))
    high = float(np.interp(1 - tail, cdf, grid))
    return low, high


class Sensitivity(_Row):
    """One tier's list sensitivity over the season's trials (private report; review
    E-R6-5).

    ``mean``, ``low`` and ``high``: the registered estimator, the tier's Beta posterior with
    every trial independent, and its central 90% interval. Trials are not independent: one
    list on one storm morning gives a trial for every district it read, all decided by
    whether that list carried the morning's closings. So ``dates`` and ``lists`` count the
    distinct school days and lists the record's trials come from, and ``day_low`` to
    ``day_high`` is the day-aggregated 90% interval: the same prior, each date one
    observation weighing its share of hits (one storm morning of 20 trials moves it as one
    trial does)."""

    tier: Tier
    trials: int = Field(ge=0)
    hits: int = Field(ge=0)
    mean: float = Field(ge=0, le=1)
    low: float = Field(ge=0, le=1)
    """The 90% interval's lower end."""
    high: float = Field(ge=0, le=1)
    dates: int = Field(ge=0)
    lists: int = Field(ge=0)
    day_mean: float = Field(ge=0, le=1)
    day_low: float = Field(ge=0, le=1)
    day_high: float = Field(ge=0, le=1)
    in_day_trials: int = Field(ge=0)
    """The record's trials that kept ``named_in_day``."""
    in_day_hits: int = Field(ge=0)
    in_day_mean: float = Field(ge=0, le=1)
    """The same prior's posterior mean of ``named_in_day`` (the event ``unnamed`` turns on:
    the sensitivity an unnamed row's correction uses); ``in_day_low`` to ``in_day_high`` its
    90% interval. The registered s (``mean``) is never above it."""
    in_day_low: float = Field(ge=0, le=1)
    in_day_high: float = Field(ge=0, le=1)


class HandAudit(_Row):
    """G1's hand audit (private report): each ISO week's draw of up to :data:`AUDIT_SAMPLE`
    unnamed rows, frozen once labeling has passed the week (``hand-audit/<week>.json``), and
    the results entered by hand (``hand-audit/results.jsonl``: day, district, and whether the
    district was in fact open). ``false_opens`` of ``audited`` drawn rows were not open;
    ``low`` to ``high`` is the Jeffreys 90% interval of that rate; ``g1``: at least
    ``min_rows`` audited with at most ``max_share`` false opens. ``to_audit``: drawn rows with
    no result yet."""

    unnamed: int = Field(ge=0)
    """Unnamed rows in the record."""
    weeks: int = Field(ge=0)
    drawn: int = Field(ge=0)
    audited: int = Field(ge=0)
    false_opens: int = Field(ge=0)
    rate: float | None = Field(ge=0, le=1)
    low: float | None = Field(ge=0, le=1)
    high: float | None = Field(ge=0, le=1)
    min_rows: int
    max_share: float
    g1: bool
    to_audit: tuple[tuple[date, str], ...]


class ReadReport(_Row):
    """``reads/summary.json`` (private): the record's G1 numbers, rewritten every run.

    It covers one school season (``since``, Aug 1, on, :data:`SEASON_START`, the one season
    start of this piece: each run reads that season's days only, so its time does not grow
    season over season). ``sensitivity`` per tier
    (:class:`Sensitivity`); ``tier_b_g1``: whether s_B is at least ``tier_b_min`` over at
    least ``tier_b_min_trials`` closed trials from at least ``tier_b_min_dates`` distinct
    dates (lead ruling B1.5), the registered check, always read beside the dates and lists
    the trials come from (the other way into G1, tier agreement, is the nightly scorer's,
    L4), and never met while the record is ``incomplete``: the season's days the public
    audit holds and the record lost (their trial totals are in ``sensitivity``, their dates,
    lists and hand-audit rows are not, so no check is claimed on them); ``rows``: alerted
    district-days by NOAA region (or state code outside the regions), class and label;
    ``states``: read alerted rows per state; ``hand_audit``: G1's hand audit
    (:class:`HandAudit`).

    Lead ruling C5, the by-date diagnostic: ``tier_b_not_by_date`` holds when the registered
    check is met by trials while tier B's **by-date mean** (``Sensitivity.day_mean``: each
    date one observation) is under ``tier_b_min`` (one storm morning of hits and a few
    one-trial dates can do that): "met by trials, not by date", said in the log beside the
    check with the by-date mean. It is a diagnostic, not a gate, until
    :data:`BY_DATE_LISTS` tier B lists exist: the larger of the lists that are tier B as of
    the run (``tier_b_lists_now``: proven and with ``min_captures`` closing-size values,
    archive and counted live days) and the lists the season's tier B trials come from
    (``tier_b_lists``, never more; review R6-S3); from then on (``tier_b_by_date_gates``)
    ``tier_b_g1`` also needs the by-date mean to reach ``tier_b_min``."""

    schema_version: Literal[6]
    since: date
    days: int = Field(ge=0)
    incomplete: int = Field(ge=0)
    sensitivity: tuple[Sensitivity, ...]
    tier_b_g1: bool
    tier_b_not_by_date: bool
    tier_b_lists: int = Field(ge=0)
    """The distinct lists the season's tier B trials come from."""
    tier_b_lists_now: int = Field(ge=0)
    """The lists that are tier B as of the run (:func:`tier_b_lists`)."""
    tier_b_by_date_gates: bool
    """The larger of ``tier_b_lists`` and ``tier_b_lists_now`` reached
    :data:`BY_DATE_LISTS`: the by-date mean is part of G1."""
    tier_b_min: float
    tier_b_min_trials: int
    tier_b_min_dates: int
    rows: dict[str, dict[str, dict[str, int]]]
    states: dict[str, int]
    """Read (labeled) alerted district-days per state code."""
    hand_audit: HandAudit


G1_MIN_DATES: Final = 5
"""Lead ruling B1.5: G1's tier B check also needs trials from at least this many dates."""
BY_DATE_LISTS: Final = 20
"""Lead ruling C5: tier B's by-date mean is a diagnostic until this many tier B lists exist
(the larger of the lists tier B as of the run and the lists the season's tier B trials come
from); from then on G1 asks it too."""


def tier_b_lists(coverage: Coverage, closing: Mapping[str, int]) -> int:
    """The lists that are tier B: proven for a county, not a district site, with
    ``min_captures`` closing-size values (``closing``: archive and counted live days,
    :attr:`ListStats.closing`)."""
    proven = {s for found in coverage.county_sources.values() for s in found}
    return sum(
        closing.get(source, 0) >= coverage.min_captures
        for source in proven - coverage.district_sites
    )


SEASON_START: Final = (8, 1)
"""A school season runs from Aug 1 (lead ruling C4): the report reads the current season's
days only, and the archive audiences keep the pairs listed in the current or previous
season. The one season start of this piece."""


def season_of(day: date) -> date:
    """The Aug 1 that starts ``day``'s school season."""
    start = date(day.year, *SEASON_START)
    return start if day >= start else date(day.year - 1, *SEASON_START)


AUDIT_MIN_ROWS: Final = 50
AUDIT_MAX_SHARE: Final = 0.05
"""G1's hand audit: at least 50 unnamed rows audited, at most 5% false opens."""
HAND_AUDIT: Final = "hand-audit"
RESULTS: Final = "results.jsonl"


def _region(leaid: str) -> str:
    state = district_state(leaid)
    return REGION_OF.get(state, state or "unknown")


def _week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _audit_key(day: date, district: str) -> str:
    return hashlib.sha256(f"{day.isoformat()}:{district}".encode()).hexdigest()


def draw_weeks(
    folder: Path, unnamed: Sequence[tuple[date, str]], since: date | None = None
) -> dict[str, list[tuple[date, str]]]:
    """Each ISO week's hand-audit draw: a week's draw is made once labeling has passed it (a
    labeled day after its Sunday: days are labeled in order, so none of its days is labeled
    later) and then kept in ``hand-audit/<week>.json``, never drawn again; up to
    :data:`AUDIT_SAMPLE` of the week's unnamed rows by a fixed hash of day and district.
    ``since``: the weeks of the season's labeled days only.

    Raises:
        ValueError: a kept draw does not read.
    """
    root = folder / HAND_AUDIT
    labeled = labeled_days(folder)
    last = labeled[-1] if labeled else None
    if since is not None:
        labeled = [day for day in labeled if day >= since]
    by_week: dict[str, list[tuple[date, str]]] = defaultdict(list)
    for day, district in unnamed:
        by_week[_week(day)].append((day, district))
    weeks = {_week(day) for day in labeled}
    drawn: dict[str, list[tuple[date, str]]] = {}
    for week in sorted(weeks):
        path = root / f"{week}.json"
        if path.is_file():
            try:
                found = json.loads(path.read_bytes())
                drawn[week] = [(date.fromisoformat(d), str(n)) for d, n in found["rows"]]
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"{path.name}: {type(error).__name__}") from error
            continue
        year, number = (int(part) for part in week.split("-W"))
        sunday = date.fromisocalendar(year, number, 7)
        if last is None or last <= sunday:
            continue
        rows = sorted(by_week.get(week, ()), key=lambda item: _audit_key(*item))
        sample = sorted(rows[:AUDIT_SAMPLE])
        value = {
            "week": week,
            "unnamed": len(rows),
            "rows": [[day.isoformat(), district] for day, district in sample],
        }
        write_bytes_atomic(path, dumps_json(cast("JSONValue", value)))
        drawn[week] = sample
    return drawn


def audit_results(folder: Path) -> dict[tuple[date, str], bool]:
    """The hand audit's results (``hand-audit/results.jsonl``): whether each audited
    district-day was open; a later line for the same row wins.

    Raises:
        ValueError: a line does not read.
    """
    path = folder / HAND_AUDIT / RESULTS
    found: dict[tuple[date, str], bool] = {}
    if not path.is_file():
        return found
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            opened = item["open"]
            if not isinstance(opened, bool):
                raise TypeError("open is true or false")
            found[(date.fromisoformat(item["day"]), str(item["district"]))] = opened
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{RESULTS} line {number}: {type(error).__name__}") from error
    return found


def _sensitivity(
    tier: Tier, totals: tuple[int, int], trials: Sequence[tuple[date, Trial]], rule: ReadRule
) -> Sensitivity:
    count, hits = totals
    a, b = rule.posterior(tier, count, hits)
    low, high = beta_interval(a, b)
    by_day: dict[date, list[bool]] = defaultdict(list)
    for day, trial in trials:
        by_day[day].append(trial.named)
    shares = [sum(found) / len(found) for found in by_day.values()]
    prior = rule.prior_a if tier is Tier.A else rule.prior_b
    day_a, day_b = prior[0] + sum(shares), prior[1] + len(shares) - sum(shares)
    day_low, day_high = beta_interval(day_a, day_b)
    in_day = [trial.named_in_day for _day, trial in trials if trial.named_in_day is not None]
    in_a, in_b = rule.posterior(tier, len(in_day), sum(in_day))
    in_low, in_high = beta_interval(in_a, in_b)
    return Sensitivity(
        tier=tier, trials=count, hits=hits, mean=round(a / (a + b), 4),
        low=round(low, 4), high=round(high, 4), dates=len(by_day),
        lists=len({trial.source for _day, trial in trials}),
        day_mean=round(day_a / (day_a + day_b), 4), day_low=round(day_low, 4),
        day_high=round(day_high, 4), in_day_trials=len(in_day), in_day_hits=sum(in_day),
        in_day_mean=round(in_a / (in_a + in_b), 4), in_day_low=round(in_low, 4),
        in_day_high=round(in_high, 4),
    )  # fmt: skip


def read_trials(folder: Path, day: date) -> list[Trial]:
    """The record's trials of ``day`` (none when it holds none).

    Raises:
        ValueError: the file does not read.
    """
    path = trials_path(folder, day)
    if not path.is_file():
        return []
    return [
        Trial.model_validate_json(line, strict=False)
        for line in path.read_bytes().splitlines()
        if line.strip()
    ]


def report_of(
    folder: Path,
    audit: ReadAudit,
    rule: ReadRule,
    since: date | None = None,
    lists_now: int = 0,
) -> ReadReport:
    """The private report of the record's season from ``since`` (see :class:`ReadReport`;
    by default the season of the audit's last day), ``lists_now`` the lists tier B as of the
    run (:func:`tier_b_lists`); it also freezes the hand audit's draw of every week of the
    season labeling has passed (:func:`draw_weeks`).

    Raises:
        ValueError: a day of the record, a kept draw or the audit results do not read.
    """
    if since is None:
        last = max((item.day for item in audit.days), default=None)
        since = season_of(last) if last is not None else date.min
    season = replace_days(audit, [item for item in audit.days if item.day >= since])
    totals = trial_totals(season)
    rows: dict[str, dict[str, dict[str, int]]] = {}
    states: Counter[str] = Counter()
    unnamed: list[tuple[date, str]] = []
    trials: dict[Tier, list[tuple[date, Trial]]] = defaultdict(list)
    held: set[date] = set()
    for day in labeled_days(folder):
        if day < since:
            continue
        found = read_day(folder, day)
        if found is None:
            continue
        held.add(day)
        for trial in read_trials(folder, day):
            trials[trial.tier].append((day, trial))
        for row in found.rows:
            klass = WeatherClass(row.weather).label
            by_class = rows.setdefault(_region(row.district), {}).setdefault(klass, {})
            by_class[row.label.value] = by_class.get(row.label.value, 0) + 1
            if row.label is not Label.NOT_READ:
                states[district_state(row.district) or "unknown"] += 1
            if row.label is Label.UNNAMED:
                unnamed.append((day, row.district))
    incomplete = sum(item.day not in held for item in season.days)
    sensitivity = tuple(_sensitivity(tier, totals[tier], trials[tier], rule) for tier in Tier)
    tier_b = sensitivity[1]
    registered = (
        not incomplete
        and tier_b.trials >= rule.tier_b_min_trials
        and tier_b.dates >= G1_MIN_DATES
        and tier_b.mean >= rule.tier_b_min
    )
    by_date = tier_b.day_mean >= rule.tier_b_min
    gates = max(tier_b.lists, lists_now) >= BY_DATE_LISTS
    return ReadReport(
        schema_version=6,
        since=since,
        days=len(season.days),
        incomplete=incomplete,
        sensitivity=sensitivity,
        tier_b_g1=registered and (by_date or not gates),
        tier_b_not_by_date=registered and not by_date,
        tier_b_lists=tier_b.lists,
        tier_b_lists_now=lists_now,
        tier_b_by_date_gates=gates,
        tier_b_min=rule.tier_b_min,
        tier_b_min_trials=rule.tier_b_min_trials,
        tier_b_min_dates=G1_MIN_DATES,
        rows={region: dict(sorted(found.items())) for region, found in sorted(rows.items())},
        states=dict(sorted(states.items())),
        hand_audit=hand_audit_of(folder, unnamed, since),
    )


def replace_days(audit: ReadAudit, days: Sequence[ReadAuditDay]) -> ReadAudit:
    """``audit`` holding ``days`` only."""
    return audit.model_copy(update={"days": tuple(days)})


def hand_audit_of(
    folder: Path, unnamed: Sequence[tuple[date, str]], since: date | None = None
) -> HandAudit:
    """G1's hand audit from the frozen weekly draws (of the season from ``since``) and the
    results entered by hand.

    Raises:
        ValueError: a kept draw or the results do not read.
    """
    drawn = draw_weeks(folder, unnamed, since)
    results = audit_results(folder)
    sample = sorted(row for rows in drawn.values() for row in rows)
    audited = [results[row] for row in sample if row in results]
    false_opens = sum(not opened for opened in audited)
    rate = low = high = None
    if audited:
        rate = round(false_opens / len(audited), 4)
        found = beta_interval(0.5 + false_opens, 0.5 + len(audited) - false_opens)
        low, high = round(found[0], 4), round(found[1], 4)
    return HandAudit(
        unnamed=len(unnamed),
        weeks=len(drawn),
        drawn=len(sample),
        audited=len(audited),
        false_opens=false_opens,
        rate=rate,
        low=low,
        high=high,
        min_rows=AUDIT_MIN_ROWS,
        max_share=AUDIT_MAX_SHARE,
        g1=len(audited) >= AUDIT_MIN_ROWS and false_opens <= AUDIT_MAX_SHARE * len(audited),
        to_audit=tuple(row for row in sample if row not in results),
    )


# --- the step -----------------------------------------------------------------------------------


@dataclass(slots=True)
class StateReadSource:
    """The live ingest's state folder as the read rule needs it: the S7-L source
    (:class:`~snowlight.predict.live_labels.StateSource`) with its live audience taken from
    the change log before the day (:func:`audience_before`), the record's counted days, and
    the change log's lighting sources. The morning record's days and the change log are each
    read once a run (the folder does not change while it runs), however many days it
    labels."""

    state: StateSource
    _counted: tuple[Closing, dict[date, dict[str, int]]] | None = field(default=None, init=False)
    _changes: LoadedChanges | None = field(default=None, init=False)

    def index(self) -> DayIndex | None:
        return self.state.index()

    def timeline(self, day: date) -> DayTimeline | None:
        return self.state.timeline(day)

    def _log(self) -> LoadedChanges:
        if self._changes is None:
            self._changes = LoadedChanges.of(ChangeLog(self.state.folder / "changes"))
        return self._changes

    def _days(self, closing: Closing) -> dict[date, dict[str, int]]:
        if self._counted is None or self._counted[0] is not closing:
            found = counted_days(
                MorningLog(self.state.folder / "morning"), closing,
                market_of=self.state.market_of, prefix=self.state.prefix,
            )  # fmt: skip
            self._counted = (closing, found)
        return self._counted[1]

    def morning(self, day: date) -> Morning | str:
        found = self.state.morning(day)
        if isinstance(found, str):
            return found
        return replace(
            found, audience=audience_before(self._log(), day, self.state.settings.audience_days)
        )

    def captures(self, day: date, days: int, closing: Closing | None = None) -> LiveCaptures:
        if closing is None:
            return LiveCaptures()
        return captures_of(self._days(closing), day, days)

    def lit_by(self, day: date) -> Mapping[str, Mapping[str, datetime]] | None:
        changes = self._log()
        if day not in changes.days():
            return None
        return lit_sources(changes, day)


@dataclass(slots=True)
class ReadRun:
    """What a run labeled, and why other days were not."""

    added: list[date] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)
    waiting: set[date] = field(default_factory=set)
    counted: LiveCaptures | None = None
    """The record's counted days (lead ruling C2) before the day after the newest day added
    (none when no day was added): which lists gain live closing-size captures, week by week
    (review E-R5-3)."""
    closing: Mapping[str, int] = field(default_factory=dict)
    """Each list's closing-size values then, archive and counted days together (5 or more:
    its reference is not thin, and a proven list is tier B)."""
    recent: LiveCaptures | None = None
    """The counted days in the ``recent_days`` days before then: the lists that read with no
    second list of their market (condition 4), the read's live peer-free reach (review
    E-R6-1)."""
    closing_rule: Closing | None = None
    """What decided the run's counted days (one object a run, so a source's counted days are
    worked out once), for a later reader of the same days' captures."""

    def skip(self, day: date, why: str) -> None:
        self.skipped[why] += 1
        if why not in NEVER and why != PUBLISHED:
            self.waiting.add(day)


DAYS_PER_RUN: Final = 5
"""The most days one run labels. The morning record starts on Oct 25, 2026 and keeps 45
days, so a first run after landing has the school days since then: about 8 to 10 at an
early-November landing (two runs), never over 33."""
LEFT: Final = f"left for the next run ({DAYS_PER_RUN} days a run)"
PUBLISHED: Final = "the public audit holds it, and the record does not: never labeled again"
"""A day done for good (the next day's ``after`` comes from the map, not from its rows)."""


@dataclass(slots=True)
class _Storms:
    """Each day's closing districts (:data:`ClosingDistricts`, lead ruling C2): the districts
    in a warning-or-above class at that day's snapshot that our map lit closed, remote or
    delayed that morning (``lit``: the day's map; ``None``, or no snapshot, gives none).
    Each day is found once a run."""

    snapshots: Mapping[str, object]
    directory: Directory
    window: Window
    slack: timedelta
    lit: Callable[[date], Lit | None] = lambda _when: None
    settings: LabelSettings | None = None
    timeline: Callable[[date], DayTimeline | None] | None = None
    """Each day's timeline, the map's statuses (in place of ``lit``): a day whose timeline
    this directory does not index (another directory's school indexes) gives no closing
    districts, as :func:`_after` and the candidate day refuse it (review R6-S2)."""
    _closing: dict[date, frozenset[str]] = field(default_factory=dict)

    def _lit(self, when: date) -> Lit | None:
        if self.timeline is None:
            return self.lit(when)
        timeline = self.timeline(when)
        if timeline is not None and not self.directory.indexes(timeline):
            return None
        return lit_of(timeline)

    def __call__(self, when: date) -> frozenset[str]:
        if when not in self._closing:
            classes = snapshot_classes(
                self.snapshots, when, content=self.directory.content,
                zones=self.directory.zones, window=self.window, slack=self.slack,
            )  # fmt: skip
            warned = [i for i, klass in enumerate(classes) if _warning(klass)]
            lit = self._lit(when) if warned and self.settings is not None else None
            found: set[str] = set()
            if lit is not None and self.settings is not None:
                found.update(
                    self.directory.districts[index]
                    for index in warned
                    if _lit_any(lit, self.directory, index, classes[index], self.settings)
                )
            self._closing[when] = frozenset(found)
        return self._closing[when]


def _lit_any(
    lit: Lit,
    directory: Directory,
    index: int,
    klass: WeatherClass | None,
    settings: LabelSettings,
) -> bool:
    """Whether the map lit the district closed, remote or delayed (the label rule's shares)."""
    schools = [str(s) for s in directory.eligible[index].tolist()]
    statuses = {s: lit.statuses[int(s)] for s in schools if int(s) in lit.statuses}
    if not statuses:
        return False
    outcome = outcome_of(
        shares(schools, statuses, klass or WeatherClass.NONE), read=True, settings=settings
    )
    return outcome in (Outcome.NO_SCHOOL, Outcome.DELAYED)


def _after(  # noqa: PLR0913 - the day before and how to read it
    source: ReadSource,
    before: date,
    *,
    index: DayIndex | None,
    directory: Directory,
    snapshots: Mapping[str, object],
    window: Window,
    slack: timedelta,
    settings: LabelSettings,
) -> frozenset[str] | None:
    """The districts the map lit no school on ``before`` (``None``: not known for good)."""
    timeline = source.timeline(before)
    if day_ready(before, timeline, index) is not None:
        return None
    if timeline is not None and not directory.indexes(timeline):
        return None
    classes = snapshot_classes(
        snapshots, before, content=directory.content, zones=directory.zones,
        window=window, slack=slack,
    )  # fmt: skip
    return lit_no_school(lit_of(timeline), directory, classes, settings)


def read_new_days(  # noqa: PLR0912, PLR0913, PLR0915 - the record, the inputs and when
    folder: Path,
    source: ReadSource,
    *,
    directory: Directory,
    coverage: Coverage,
    snapshots: Mapping[str, object],
    config: PredictConfig,
    now: datetime,
    published: Iterable[date] = (),
    limit: int | None = None,
    on_added: Callable[[date], None] | None = None,
) -> ReadRun:
    """Label every school day of the last ``morning_reads_days`` that is ready and not in the
    record yet, by the readiness rules of the S7-L step (:func:`snowlight.predict.learn.
    label_new_days`): over everywhere, its record whole, its timeline final, its previous
    school day not waiting, not excluded. A labeled day is frozen: its file is never written
    again, and a day the public audit already holds (``published``) is never labeled again
    either, even when the record lost it. On its first run this takes in every day the
    morning record still holds, :data:`DAYS_PER_RUN` (``limit``) a run, oldest first (the
    step has 2 minutes; the rest wait for the next run). ``on_added`` is called as each day
    is about to be written (before its files, so a run cut off between the two still saves
    it), and before the next is begun, so a run cut off keeps what it wrote."""
    rule = ReadRule.of(config)
    limit = DAYS_PER_RUN if limit is None else limit
    done = ReadRun()
    weather = config.weather
    window = Window(weather.window_from, weather.window_until, weather.snapshot_hour)
    slack = timedelta(minutes=config.learn.snapshot_slack_minutes)
    today = now.astimezone(UTC).date()
    labeled = set(labeled_days(folder))
    frozen = set(published) - labeled
    index: DayIndex | None = None
    index_read = False
    closing = Closing(
        rule,
        coverage,
        _Storms(
            snapshots, directory, window, slack, settings=rule.labels, timeline=source.timeline,
        ),
        zones=dict(zip(directory.districts, directory.zones, strict=True)),
    )  # fmt: skip
    done.closing_rule = closing
    day = today - timedelta(days=config.learn.morning_reads_days)
    while day < today:
        candidate, day = day, day + timedelta(days=1)
        if not is_school_day(candidate) or candidate in labeled:
            continue
        if len(done.added) >= limit:
            done.skip(candidate, LEFT)
            continue
        if candidate in frozen:
            done.skip(candidate, PUBLISHED)
            continue
        if candidate in config.learn.excluded_days:
            done.skip(candidate, EXCLUDED)
            continue
        if not is_final(candidate, now):
            done.skip(candidate, "not over everywhere yet")
            continue
        before = previous_school_day(candidate)
        if before in done.waiting:
            done.skip(candidate, "its previous school day is not labeled yet")
            continue
        morning = source.morning(candidate)
        if isinstance(morning, str):
            done.skip(candidate, morning)
            continue
        timeline = source.timeline(candidate)
        if not index_read:
            index, index_read = source.index(), True
        waiting = day_ready(candidate, timeline, index)
        if waiting is not None:
            done.skip(candidate, waiting)
            continue
        if timeline is not None and timeline.gaps and not directory.indexes(timeline):
            done.skip(candidate, ANOTHER_DIRECTORY)
            continue
        classes = snapshot_classes(
            snapshots, candidate, content=directory.content, zones=directory.zones,
            window=window, slack=slack,
        )  # fmt: skip
        found = label_read_day(
            candidate,
            morning=morning,
            coverage=coverage,
            weather=classes,
            lit=lit_of(timeline),
            directory=directory,
            rule=rule,
            recent=source.captures(candidate, rule.recent_days, closing).days,
            live=source.captures(candidate, CAPTURE_DAYS, closing),
            lit_by=source.lit_by(candidate),
            after=_after(
                source, before, index=index, directory=directory, snapshots=snapshots,
                window=window, slack=slack, settings=rule.labels,
            ),
        )  # fmt: skip
        if on_added is not None:
            # Marked before the write: a step cut off between the two still saves the cache
            # (an extra save of an unchanged folder is harmless; a written day left unsaved
            # would be labeled again by the next run).
            on_added(candidate)
        write_day(
            folder,
            ReadDay(
                schema_version=1,
                day=candidate,
                content=directory.content,
                rows=tuple(found.rows),
                no_school=tuple(sorted(found.no_school)),
                audit=found.audit,
            ),
            found.trials,
        )
        labeled.add(candidate)
        done.added.append(candidate)
    if done.added:
        # The record's days are parsed already (memoized for the run): this costs a count.
        after = done.added[-1] + timedelta(days=1)
        done.counted = source.captures(after, CAPTURE_DAYS, closing)
        done.recent = source.captures(after, rule.recent_days, closing)
        done.closing = dict(
            ListStats.of(coverage, done.counted, rule.labels.station_min_captures).closing
        )
    return done


__all__ = [
    "AUDIT_PATH",
    "OPEN_LABEL",
    "Coverage",
    "HandAudit",
    "Label",
    "Labeled",
    "ListStats",
    "LiveCaptures",
    "LoadedChanges",
    "NotRead",
    "Read",
    "ReadDay",
    "ReadReport",
    "ReadRow",
    "ReadRule",
    "ReadSource",
    "Tier",
    "Trial",
    "Why",
    "audience_before",
    "label_read_day",
    "read_new_days",
    "read_set",
    "report_of",
]

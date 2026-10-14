"""Earlier reads of a page closings are typed into: telling a leftover note from a new one.

A list typed by hand into a page that states no time for itself (Scripps' Brightspot
pages: KSTU's ``/weather/closings``) cannot say how old its rows are. Its own words
date a row only when they pin down a day (a heading "WEDNESDAY, FEB. 22",
:func:`snowlight.sources.stations.typed.row_names_day_near`). Otherwise the page's
earlier reads date it: a row the page has held, unchanged, for longer than
:data:`TYPED_CURRENT` is an old note (KSTU's "Provo City School District will operate
on a Two Hour Late Start schedule on Tuesday", archived on the page on 2025-05-20,
2025-09-16, 2025-12-17 and 2026-05-09, and read live every time since, is not about
this Tuesday), and a row an earlier read of the last :data:`TYPED_CURRENT` did not
hold was typed since.

Observations
============

Every read of a station's page that parsed (populated or empty) is an observation
(:class:`Seen`): when (a live read's time, an archived capture's timestamp), how
(``live`` or ``archive``), the page's address and SHA-256, and the keys of its rows
(:func:`row_key`: everything the row holds, its name, status, time and the context its
adapter kept, such as the whole line, the heading in force and nested details, with
whitespace collapsed and case folded, hashed). Two reads hold the same row when they
hold the same key. Only reads of the address being judged count
(:func:`same_page`), and only those made before the read.

Earlier observations come from two places:

* the archived captures the archive parse read (``archive/reads.jsonl`` and the
  ``rows.jsonl`` beside it, :meth:`TypedHistory.from_archive`): an empty capture
  (KSTU's of 2025-02-11) is an observation that holds no row;
* the earlier live reads, which ``stations fetch`` keeps in ``typed-history.json``
  (internal, never published; :meth:`TypedHistory.write`), adding each read it
  judges.

The verdict on each row of a read made at ``T`` (:func:`judge`)
===================================================================

* ``dated``: its heading, note or line names a day near ``T``. Kept.
* ``past``: the days its heading, note or line name are all gone by ``T`` (KSTU's
  page on Sunday 26 February 2023 still held its rows under "WEDNESDAY, FEB. 22" and
  "THURSDAY, FEB. 23"). Not kept: an old note by its own words.
* ``old``: every observation since the last one without it held it, and the first of
  them was made more than :data:`TYPED_CURRENT` before ``T`` (the row has stood
  unchanged for longer than that). Not kept.
* ``new``: an observation made within :data:`TYPED_CURRENT` before ``T`` did not hold
  it: it was typed since. Kept.
* ``unknown``: neither (no observation holds or lacks it, or it was first seen within
  :data:`TYPED_CURRENT` of ``T`` while the last observation without it is older than
  that). Not kept: it cannot be told from an old note.

``stations fetch`` keeps the dated and new rows. When it keeps none, the read is
``empty`` when every row is old or past (the station's list holds nothing current; the
station counts as working) and ``stale`` when any is unknown (see
:mod:`snowlight.sources.stations.fetch`, step 5).

``typed-history.json``::

    {"generated_at", "typed_current_hours",
     "sources": {id: [{"at", "mode", "url", "sha256", "keys": [key, ...]}, ...]}}

Of each run of consecutive observations holding the same keys only the first and the
last are kept (:meth:`TypedHistory.compact`); the verdicts do not change, since they
depend only on where such runs begin and end.
"""

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError

from snowlight.output import JSONValue, write_json
from snowlight.sources.stations import typed
from snowlight.sources.stations.http import iso_utc
from snowlight.sources.stations.model import (
    JsonScalar,
    ListingRead,
    ListingState,
    ParsedRow,
    RawRow,
    ReadMode,
)

TYPED_CURRENT = timedelta(hours=36)
"""How long a typed row is taken as current: after its page last changed, or since it
was first seen on a page that states no time (see the module docstring)."""
HISTORY_FILE = "typed-history.json"
MAX_SEEN = 400
"""At most this many observations are kept per source (the newest), after compaction."""
KEY_LENGTH = 16
"""Hex digits of a row key (64 bits of its SHA-256)."""
_SPACE = re.compile(r"\s+")
_READ = TypeAdapter(ListingRead)
_ROW = TypeAdapter(RawRow)


class TypedHistoryError(ValueError):
    """A history, reads or rows file does not have the shape its writer gives it."""


def _norm(text: str) -> str:
    return _SPACE.sub(" ", text).strip().casefold()


def row_key(
    name: str, status: str, updated_text: str | None, extra: Mapping[str, JsonScalar]
) -> str:
    """Return the key of one row: everything it holds, normalized and hashed."""
    parts: list[str] = [_norm(name), _norm(status), _norm(updated_text or "")]
    for field_name in sorted(extra):
        value = extra[field_name]
        parts.append(f"{field_name}={_norm(value) if isinstance(value, str) else value!r}")
    digest = hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()[:KEY_LENGTH]


def parsed_key(row: ParsedRow) -> str:
    """Return the key of an adapter's row."""
    return row_key(row.name, row.status, row.updated_text, row.extra)


def raw_key(row: RawRow) -> str:
    """Return the key of a stamped row (the same as its :class:`ParsedRow`'s)."""
    return row_key(row.raw_name, row.raw_status, row.raw_updated_text, row.raw_extra)


def page_key(url: str) -> tuple[str, str]:
    """Return one page's identity: host without ``www.``, path without a trailing slash."""
    parts = urlsplit(url)
    return (parts.hostname or "").lower().removeprefix("www."), parts.path.rstrip("/")


def same_page(one: str, other: str) -> bool:
    """Whether two URLs name the same page (scheme, ``www.``, query and a trailing slash aside)."""
    return page_key(one) == page_key(other)


@dataclass(frozen=True, slots=True)
class Seen:
    """One read of a typed page: when, how, which body, and the keys of its rows."""

    at: datetime
    mode: ReadMode
    url: str
    sha256: str
    keys: frozenset[str]

    def describe(self) -> str:
        """Say which read this is, for a health reason."""
        how = "archived capture" if self.mode is ReadMode.ARCHIVE else "live read"
        return f"the {how} of {iso_utc(self.at)}"

    def as_json(self) -> dict[str, JSONValue]:
        """The observation as ``typed-history.json`` holds it."""
        keys: list[JSONValue] = [*sorted(self.keys)]
        return {
            "at": iso_utc(self.at),
            "mode": self.mode.value,
            "url": self.url,
            "sha256": self.sha256,
            "keys": keys,
        }


class Verdict(StrEnum):
    """What the earlier reads (or the row's own words) say of one typed row."""

    DATED = "dated"
    PAST = "past"
    NEW = "new"
    OLD = "old"
    UNKNOWN = "unknown"


KEPT = frozenset({Verdict.DATED, Verdict.NEW})
GONE = frozenset({Verdict.PAST, Verdict.OLD})
"""Verdicts of rows that are old notes: by their own words, or by the earlier reads."""


@dataclass(frozen=True, slots=True)
class RowVerdict:
    """One row's verdict and the observations it rests on."""

    row: ParsedRow
    key: str
    verdict: Verdict
    since: Seen | None
    """The first of the observations that have held it since the last one without it."""
    lacking: Seen | None
    """The last observation without it, if any."""


@dataclass(frozen=True, slots=True)
class Judgement:
    """The verdicts on one read's rows, and how many earlier observations they rest on."""

    rows: tuple[RowVerdict, ...]
    earlier: int

    @property
    def kept(self) -> tuple[ParsedRow, ...]:
        """The rows kept: those dated by their own words or typed since a recent read."""
        return tuple(item.row for item in self.rows if item.verdict in KEPT)

    def count(self, verdict: Verdict) -> int:
        """How many rows earned ``verdict``."""
        return sum(item.verdict is verdict for item in self.rows)

    @property
    def all_old(self) -> bool:
        """Whether every row is an old note (none kept, none unknown)."""
        return bool(self.rows) and all(item.verdict in GONE for item in self.rows)

    def oldest(self) -> RowVerdict | None:
        """The old row first seen earliest (the one a reason cites), if any."""
        old = [item for item in self.rows if item.verdict is Verdict.OLD and item.since]
        if not old:
            return None
        return min(old, key=_since_at)

    def summary(self) -> str:
        """Say what the verdicts were, e.g. ``1 old`` or ``2 new, 1 old``."""
        parts = [
            f"{self.count(verdict)} {verdict.value}" for verdict in Verdict if self.count(verdict)
        ]
        return ", ".join(parts)


def _since_at(item: RowVerdict) -> datetime:
    return item.since.at if item.since is not None else datetime.max.replace(tzinfo=UTC)


def _verdict(
    key: str, earlier: Sequence[Seen], read_at: datetime, window: timedelta
) -> tuple[Verdict, Seen | None, Seen | None]:
    """One undated row's verdict from the observations before the read, oldest first."""
    lacking: Seen | None = None
    since: Seen | None = None
    for seen in earlier:
        if key in seen.keys:
            if since is None:
                since = seen
        else:
            lacking, since = seen, None
    cutoff = read_at - window
    if since is not None and since.at < cutoff:
        return Verdict.OLD, since, lacking
    if lacking is not None and lacking.at >= cutoff:
        return Verdict.NEW, since, lacking
    return Verdict.UNKNOWN, since, lacking


def judge(
    rows: Sequence[ParsedRow],
    read_at: datetime,
    earlier: Iterable[Seen],
    window: timedelta = TYPED_CURRENT,
) -> Judgement:
    """Judge each row of a typed read made at ``read_at`` (see the module docstring).

    ``earlier`` are the observations of the same page; those not made before
    ``read_at`` are passed over.
    """
    before = sorted((seen for seen in earlier if seen.at < read_at), key=lambda s: s.at)
    verdicts: list[RowVerdict] = []
    for row in rows:
        key = parsed_key(row)
        if typed.row_names_day_near(row, read_at):
            verdicts.append(RowVerdict(row, key, Verdict.DATED, None, None))
            continue
        if typed.row_names_only_past_days(row, read_at):
            verdicts.append(RowVerdict(row, key, Verdict.PAST, None, None))
            continue
        verdict, since, lacking = _verdict(key, before, read_at, window)
        verdicts.append(RowVerdict(row, key, verdict, since, lacking))
    return Judgement(tuple(verdicts), len(before))


def _parse_seen(record: object) -> Seen:
    if not isinstance(record, dict):
        raise TypedHistoryError("an observation is not an object")
    try:
        keys = record["keys"]
        if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
            raise TypedHistoryError("an observation's keys are not a list of strings")
        return Seen(
            at=datetime.fromisoformat(str(record["at"]).replace("Z", "+00:00")),
            mode=ReadMode(record["mode"]),
            url=str(record["url"]),
            sha256=str(record["sha256"]),
            keys=frozenset(keys),
        )
    except (KeyError, ValueError) as error:
        raise TypedHistoryError(f"an observation is malformed: {error}") from error


class TypedHistory:
    """The observations of every typed page read so far, per source."""

    def __init__(self, by_source: Mapping[str, Iterable[Seen]] | None = None) -> None:
        self.by_source: dict[str, list[Seen]] = defaultdict(list)
        for source_id, observations in (by_source or {}).items():
            self.by_source[source_id].extend(observations)
        self.compact()

    def earlier(self, source_id: str, url: str, before: datetime) -> list[Seen]:
        """The observations of ``url``'s page for ``source_id`` made before ``before``."""
        return [
            seen
            for seen in self.by_source.get(source_id, ())
            if seen.at < before and same_page(seen.url, url)
        ]

    def add(self, source_id: str, seen: Seen) -> None:
        """Record one observation (it is placed by time; compaction follows)."""
        self.by_source[source_id].append(seen)
        self._compact_one(source_id)

    def merge(self, other: "TypedHistory") -> None:
        """Take in every observation of ``other``."""
        for source_id, observations in other.by_source.items():
            self.by_source[source_id].extend(observations)
            self._compact_one(source_id)

    def compact(self) -> None:
        """Keep the first and last of each run of observations holding the same keys."""
        for source_id in list(self.by_source):
            self._compact_one(source_id)

    def _compact_one(self, source_id: str) -> None:
        unique = {(seen.at, seen.url, seen.sha256): seen for seen in self.by_source[source_id]}
        ordered = sorted(unique.values(), key=lambda seen: (seen.at, seen.url, seen.sha256))
        kept: list[Seen] = []
        by_page: dict[tuple[str, str], list[Seen]] = defaultdict(list)
        for seen in ordered:
            by_page[page_key(seen.url)].append(seen)
        for observations in by_page.values():
            for number, seen in enumerate(observations):
                previous = observations[number - 1] if number else None
                following = observations[number + 1] if number + 1 < len(observations) else None
                inside = (
                    previous is not None
                    and following is not None
                    and previous.keys == seen.keys == following.keys
                )
                if not inside:
                    kept.append(seen)
        kept.sort(key=lambda seen: (seen.at, seen.url, seen.sha256))
        self.by_source[source_id] = kept[-MAX_SEEN:]

    def as_json(self, generated_at: datetime) -> dict[str, JSONValue]:
        """The history as ``typed-history.json`` holds it."""
        sources: dict[str, JSONValue] = {
            source_id: [seen.as_json() for seen in observations]
            for source_id, observations in sorted(self.by_source.items())
            if observations
        }
        return {
            "generated_at": iso_utc(generated_at),
            "typed_current_hours": TYPED_CURRENT.total_seconds() / 3600,
            "sources": sources,
        }

    def write(self, path: Path, generated_at: datetime) -> None:
        """Write the history to ``path``."""
        write_json(path, self.as_json(generated_at))

    @classmethod
    def load(cls, path: Path) -> "TypedHistory":
        """Read ``typed-history.json``; a missing file is an empty history."""
        if not path.exists():
            return cls()
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise TypedHistoryError(f"{path}: {error}") from error
        sources = document.get("sources") if isinstance(document, dict) else None
        if not isinstance(sources, dict):
            raise TypedHistoryError(f"{path}: no sources object")
        by_source: dict[str, list[Seen]] = {}
        for source_id, records in sources.items():
            if not isinstance(records, list):
                raise TypedHistoryError(f"{path}: {source_id}'s observations are not a list")
            by_source[str(source_id)] = [_parse_seen(record) for record in records]
        return cls(by_source)

    @classmethod
    def from_archive(
        cls, reads_path: Path, rows_path: Path, source_ids: Collection[str]
    ) -> "TypedHistory":
        """Observations from the archived captures of ``source_ids`` the archive parse read.

        A capture read as empty holds no row; one read as populated holds the rows the
        archive parse wrote for it (matched by source and capture time). A populated
        read whose rows cannot be told apart from another read's (two addresses
        captured in the same second) or are missing is passed over, and so is every
        read that did not parse (an error, a count-only page). Missing files give an
        empty history.
        """
        wanted = set(source_ids)
        if not wanted or not reads_path.exists():
            return cls()
        reads = [
            read
            for read in _lines(reads_path, _READ, wanted)
            if read.mode is ReadMode.ARCHIVE
            and read.state in (ListingState.POPULATED, ListingState.EMPTY)
        ]
        rows: dict[tuple[str, datetime], list[RawRow]] = defaultdict(list)
        if rows_path.exists():
            for row in _lines(rows_path, _ROW, wanted):
                rows[(row.source_id, row.fetched_at)].append(row)
        sharing: dict[tuple[str, datetime], int] = defaultdict(int)
        for read in reads:
            sharing[(read.source_id, read.fetched_at)] += 1
        by_source: dict[str, list[Seen]] = defaultdict(list)
        for read in reads:
            where = (read.source_id, read.fetched_at)
            if read.state is ListingState.EMPTY:
                keys: frozenset[str] = frozenset()
            elif sharing[where] == 1 and len(rows.get(where, ())) == read.rows and read.rows:
                keys = frozenset(raw_key(row) for row in rows[where])
            else:
                continue
            by_source[read.source_id].append(
                Seen(read.fetched_at, ReadMode.ARCHIVE, read.url, read.sha256, keys)
            )
        return cls(by_source)


def _lines[T](path: Path, adapter: TypeAdapter[T], wanted: set[str]) -> Iterable[T]:
    """Parse the JSON lines of ``path`` whose ``source_id`` is one of ``wanted``."""
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            marker = line.find('"source_id":"')
            if marker >= 0:
                start = marker + len('"source_id":"')
                if line[start : line.find('"', start)] not in wanted:
                    continue
            try:
                record = adapter.validate_json(line)
            except ValidationError as error:
                raise TypedHistoryError(f"{path}:{number}: {error}") from error
            if getattr(record, "source_id", None) in wanted:
                yield record


def observation(read_at: datetime, url: str, sha256: str, rows: Sequence[ParsedRow]) -> Seen:
    """The observation one live read of a typed page makes."""
    return Seen(read_at, ReadMode.LIVE, url, sha256, frozenset(parsed_key(row) for row in rows))

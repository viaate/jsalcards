"""The row ledger: when each row was first seen, and the read before it that lacked it (G1-G3).

A row's posting time is bounded by an interval ``[lo, hi]`` (spec D1): ``hi`` is
the first read that held the row and never moves while the row lives; ``lo`` is
the source's previous good read, which lacked it. The status reader is then run
across the whole interval (:mod:`snowlight.live.resolve`), so a result never
depends on when inside it the row went up. The fetch time is never the posted time.

A row is known by a key: an HMAC-SHA256, under the ledger's own secret, of its
source, its normalized name, section, stated places, status words and row date
(:func:`row_key`).
The secret lives only in the ledger file (the private state store), so a key cannot
be reversed by hashing guessed names and statuses. The row date is the row-scoped
stamp's text (``updated_scope == "row"``) or a board's row-date field; a page-scoped
stamp, HTTP Last-Modified and the fetch time are never part of a key or a date (D2),
so a page whose stamp changes on every read keeps its keys. A row's identity
(:func:`row_ident`) is the same without the status words and row date: the listing
the row is about. Two rows of one read with the same key are kept once and counted
(``duplicate_keys``).

Rules (spec 7.2):

* a good read (``ok``, ``not_modified``, ``empty``) refreshes the rows it holds and
  dates the new ones: ``lo`` is the previous good read when it is at most
  ``longest`` before, else unknown (a cold start, D3);
* a new key whose listing (identity) is already known in the source, under a key
  now absent, is that key's **successor** (the listing's words changed: an upgrade,
  a retraction, or a re-render); it keeps the predecessor's key (``pred``), so the
  resolver can tell a change of meaning from a re-render (and may then leave the
  successor undated, :meth:`Ledger.reword`). When
  two absent keys of the listing tie as the latest, the predecessor is not known and
  the successor's ``lo`` is unknown;
* a churn read leaves the new keys' ``lo`` unknown. Churn is counted on listings (at
  least half the listings new and at least half the previous listings gone, from at
  least 5: every new key) and on keys (the same shares of keys, F3: every new key
  that is not a successor). A successor in a key-churn read keeps its interval, and
  the resolver leaves it undated unless its words changed what the listing says or
  its reading does not depend on when it was posted (:mod:`snowlight.live.resolve`):
  a storm morning's batch of upgrades lights, a list re-worded overnight does not;
* a key absent for less than 3 hours keeps its first sighting (a flap). Absent for 3
  hours or more, a later sighting is a new appearance (T1f): with the source's last
  read as ``lo`` when a read lacking it showed something new (the list was live
  while the key was away), else with ``lo`` unknown when its first sighting was on
  an earlier local day than its return in any US zone. A key back the same day
  after a spell of empty or old reads keeps its first sighting, so a list restored
  after a glitch is never dated as new (F1);
* a read that lost half its rows or more, or every row, is partial: it refreshes
  and deletes nothing, and does not hold the source, unless the next read holds
  the same rows (the list really shrank or emptied);
* a ``not_modified`` read without its rows confirms the last good read: it refreshes
  the rows present and the hold, and changes no presence;
* keys unseen for 14 days are pruned.

The ledger is one SQLite file. It holds keys, times, source ids and derived codes,
never raw text (D10).
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Final, NamedTuple
from zoneinfo import ZoneInfo

from snowlight.listed.evidence import section_of
from snowlight.listed.located import Places, stated_places
from snowlight.live.provenance import BOARD_ROW_DATES
from snowlight.replays.rows import detail_of, posted_stamp, reader_text
from snowlight.sources.stations.model import RawRow

FLAP: Final = timedelta(hours=3)
PRUNE: Final = timedelta(days=14)
LONGEST: Final = timedelta(hours=36)
CHURN_SHARE: Final = 0.5
CHURN_MIN_ROWS: Final = 5
PARTIAL_SHARE: Final = 0.5
SCHEMA_VERSION: Final = 4
US_ZONES: Final = (
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Phoenix",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
)
"""The zones a return is checked in: a first sighting on an earlier date in any of them
is an earlier local day (the ledger does not know a source's schools' zones)."""


class Outcome(StrEnum):
    """How one read of a source went."""

    OK = "ok"
    NOT_MODIFIED = "not_modified"
    EMPTY = "empty"
    ERROR = "error"
    BLOCKED = "blocked"
    DEFERRED = "deferred"
    LATE = "late"
    PARTIAL = "partial"


GOOD: Final = frozenset({Outcome.OK, Outcome.NOT_MODIFIED, Outcome.EMPTY})


class Start(StrEnum):
    """How a key's ``lo`` is known."""

    WARM = "warm"
    """``lo`` is the source's previous good read."""
    COLD = "cold"
    """No previous good read within ``longest``: ``lo`` is unknown."""
    CHURN = "churn"
    """The read re-keyed the list: ``lo`` is unknown."""
    REWORDED = "reworded"
    """A successor whose reading depends on whether it was posted at its own first sighting
    or re-renders its predecessor's posting, with nothing to tell which: ``lo`` is unknown."""


def norm(text: str) -> str:
    """NFKC, casefolded, whitespace collapsed, punctuation stripped at the edges."""
    folded = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    start, end = 0, len(folded)
    while start < end and _edge(folded[start]):
        start += 1
    while end > start and _edge(folded[end - 1]):
        end -= 1
    return folded[start:end]


def _edge(char: str) -> bool:
    return char == " " or unicodedata.category(char).startswith("P")


def places_text(places: Places) -> str:
    """A row's stated places in one normalized, ordered form (for its key and identity)."""
    found = {
        "|".join(norm(part or "") for part in (place.state, place.city, place.county))
        for place in places
    }
    return "\x1e".join(sorted(found))


def row_key(  # noqa: PLR0913 - the parts of a key
    secret: bytes,
    source_id: str,
    name: str,
    section: str | None,
    text: str,
    *,
    row_date: str,
    places: Places = (),
) -> bytes:
    """The key of a row: its source, name, section, places, status words and row date,
    under ``secret``.

    The status words are the reader's whole text (status and comments): a comment
    that changes changes what the row says, so it is a new row. The stated places are
    part of it: two rows of one name in different places are different rows.
    """
    parts = (
        "row",
        source_id,
        norm(name),
        norm(section or ""),
        places_text(places),
        norm(text),
        norm(row_date),
    )
    return hmac.digest(secret, "\x1f".join(parts).encode("utf-8"), "sha256")


def row_ident(
    secret: bytes, source_id: str, name: str, section: str | None, places: Places = ()
) -> bytes:
    """The identity of a row: its source, name, section and places, under ``secret``."""
    parts = ("ident", source_id, norm(name), norm(section or ""), places_text(places))
    return hmac.digest(secret, "\x1f".join(parts).encode("utf-8"), "sha256")


@dataclass(frozen=True, slots=True)
class SeenRow:
    """One row of a read, as the ledger and the resolver take it (in memory only)."""

    name: str = field(repr=False)
    text: str = field(repr=False)
    """The reader's text: the status, then the row's other status words."""
    section: str | None = field(default=None, repr=False)
    places: Places = field(default=(), repr=False)
    row_stamp: datetime | None = None
    """The row-scoped stamp (``updated_scope == "row"``), parsed; never a page's."""
    row_date: str = field(default="", repr=False)
    """The row's own date text: its row-scoped stamp's text, or a board's row-date field."""


def seen_row(raw: RawRow, *, variant: str, platform: str, zone: str) -> SeenRow:
    """Build a :class:`SeenRow` from an adapter's row.

    ``zone`` is the station's zone, in which a row stamp without its own zone is read.
    A page-scoped or unmarked stamp is dropped (D2), and so is a stamp that names a
    date and no time.
    """
    extra = raw.raw_extra
    detail = detail_of(raw.raw_name, raw.raw_status, extra)
    stamp: datetime | None = None
    row_date = ""
    if extra.get("updated_scope") == "row" and raw.raw_updated_text:
        row_date = raw.raw_updated_text
        named = extra.get("updated_zone")
        posted = posted_stamp(
            raw.raw_updated_text, raw.fetched_at, zone, named if isinstance(named, str) else None
        )
        if posted is not None and not posted.date_only:
            stamp = posted.at
    elif platform in BOARD_ROW_DATES:
        value = extra.get(BOARD_ROW_DATES[platform])
        row_date = value if isinstance(value, str) else ""
    return SeenRow(
        name=raw.raw_name,
        text=reader_text(raw.raw_status, detail),
        section=section_of(variant, extra),
        places=stated_places(variant, extra),
        row_stamp=stamp,
        row_date=row_date,
    )


@dataclass(frozen=True, slots=True)
class Darkens:
    """What a row stands against, in the plain form kept beside its derivation: schools by
    NCES id, and the days (``None``: every day)."""

    schools: tuple[str, ...]
    days: tuple[date, ...] | None


class LedgerRow(NamedTuple):
    """One key's sightings."""

    key: bytes
    source_id: str
    hi: datetime
    """The first sighting; it never moves while the key lives."""
    lo: datetime | None
    """The source's last good read lacking the key; ``None`` when unknown."""
    start: Start
    row_stamp: datetime | None
    last_seen: datetime
    absent_since: datetime | None
    gone: bool
    """Absent for 3 hours or more, with a live read since: a later sighting is a new
    appearance."""
    ident: bytes
    """The listing the row is about (:func:`row_ident`)."""
    pred: bytes | None
    """The key this one replaced in its listing, until the resolver settles how it is dated."""
    lapsed: bool
    """A read lacking the key showed something new (the list was live while it was away)."""


class SourceState(NamedTuple):
    """What the ledger keeps about one source between passes."""

    source_id: str
    last_good_at: datetime | None
    last_outcome: Outcome
    blocked_until: datetime | None
    next_due: datetime | None
    rows_last: int
    etag: str | None
    last_modified: str | None
    sha256: str | None
    derived_version: str | None


@dataclass(frozen=True, slots=True)
class Observed:
    """What one read changed."""

    outcome: Outcome
    """The read's outcome as the ledger took it (``partial`` when it lost too many rows)."""
    new: tuple[bytes, ...] = ()
    returned: tuple[bytes, ...] = ()
    vanished: tuple[bytes, ...] = ()
    gone: tuple[bytes, ...] = ()
    successors: tuple[bytes, ...] = ()
    churn: bool = False
    """Churn on listings: every new key's ``lo`` is unknown."""
    key_churn: bool = False
    """Churn on keys (F3): every new key that is not a successor has ``lo`` unknown."""
    reappeared: tuple[bytes, ...] = ()
    """Keys back after 3 hours or more that count as new appearances (T1f)."""
    counts: Mapping[str, int] = field(default_factory=dict)


_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS rows (
    key BLOB PRIMARY KEY, source_id TEXT NOT NULL, hi TEXT NOT NULL, lo TEXT,
    start TEXT NOT NULL, row_stamp TEXT, last_seen TEXT NOT NULL, absent_since TEXT,
    gone INTEGER NOT NULL DEFAULT 0, ident BLOB NOT NULL, pred BLOB,
    lapsed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS rows_source ON rows (source_id);
CREATE INDEX IF NOT EXISTS rows_ident ON rows (ident);
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY, last_good_at TEXT, last_outcome TEXT NOT NULL,
    blocked_until TEXT, next_due TEXT, rows_last INTEGER NOT NULL DEFAULT 0,
    etag TEXT, last_modified TEXT, sha256 TEXT, derived_version TEXT, pending TEXT
);
CREATE TABLE IF NOT EXISTS good_reads (source_id TEXT NOT NULL, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS good_reads_source ON good_reads (source_id, at);
CREATE TABLE IF NOT EXISTS derived (
    key BLOB PRIMARY KEY, version TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS darkens (key BLOB NOT NULL, part TEXT NOT NULL, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS darkens_key ON darkens (key);
"""


_SELECT_ROWS: Final = (
    "SELECT key, source_id, hi, lo, start, row_stamp, last_seen, absent_since, gone, ident,"
    " pred, lapsed FROM rows"
)
_INSERT_ROW: Final = (
    "INSERT OR REPLACE INTO rows (key, source_id, hi, lo, start, row_stamp, last_seen,"
    " absent_since, gone, ident, pred, lapsed) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?, 0)"
)


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        raise ValueError("ledger times are timezone-aware")
    return moment.astimezone(UTC).isoformat()


def _when(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


def _keys_digest(keys: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    for key in sorted(keys):
        digest.update(key)
    return digest.hexdigest()


def _churn(before: set[bytes], now: set[bytes]) -> bool:
    """At least half of ``now`` new and at least half of ``before`` gone, from at least 5."""
    return (
        len(before) >= CHURN_MIN_ROWS
        and len(now - before) >= CHURN_SHARE * len(now)
        and len(before - now) >= CHURN_SHARE * len(before)
    )


def _earlier_day(first: datetime, now: datetime) -> bool:
    """Whether ``first`` falls on an earlier local date than ``now`` in any US zone."""
    return any(
        first.astimezone(ZoneInfo(zone)).date() < now.astimezone(ZoneInfo(zone)).date()
        for zone in US_ZONES
    )


def _predecessor(replaced: Sequence[LedgerRow]) -> tuple[bytes | None, bool]:
    """The absent key a successor replaced: the one last seen (then first seen) latest.

    When two or more tie, which one it replaced is not known (the keys' order is the
    ledger secret's), so there is none and the second value is ``True``.
    """
    if not replaced:
        return None, False
    latest = max((entry.last_seen, entry.hi) for entry in replaced)
    tied = [entry for entry in replaced if (entry.last_seen, entry.hi) == latest]
    if len(tied) > 1:
        return None, True
    return tied[0].key, False


class Ledger:
    """The row ledger, in one SQLite file (or in memory with ``":memory:"``)."""

    def __init__(self, path: Path | str, *, longest: timedelta = LONGEST) -> None:
        self._db = sqlite3.connect(str(path))
        fresh = self._db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if not fresh and version != SCHEMA_VERSION:
            self._db.close()
            raise ValueError(f"ledger schema {version}, expected {SCHEMA_VERSION}: start a new one")
        with self._db:
            self._db.executescript(_SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._db.execute(
                "INSERT OR IGNORE INTO meta (name, value) VALUES ('secret', ?)",
                (secrets.token_bytes(32),),
            )
        stored = self._db.execute("SELECT value FROM meta WHERE name = 'secret'").fetchone()[0]
        if not isinstance(stored, bytes):
            raise TypeError("the ledger's secret is bytes")
        self._secret = stored
        self.longest = longest

    def key(self, source_id: str, row: SeenRow) -> bytes:
        """A row's key in this ledger."""
        return row_key(
            self._secret,
            source_id,
            row.name,
            row.section,
            row.text,
            row_date=row.row_date,
            places=row.places,
        )

    def ident(self, source_id: str, row: SeenRow) -> bytes:
        """A row's listing identity in this ledger."""
        return row_ident(self._secret, source_id, row.name, row.section, row.places)

    def close(self) -> None:
        self._db.close()

    # --- reads -------------------------------------------------------------------------------

    def source(self, source_id: str) -> SourceState | None:
        """The state kept for a source, or ``None`` before its first read."""
        found = self._db.execute(
            "SELECT source_id, last_good_at, last_outcome, blocked_until, next_due, rows_last,"
            " etag, last_modified, sha256, derived_version FROM sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if found is None:
            return None
        return SourceState(
            source_id=found[0],
            last_good_at=_when(found[1]),
            last_outcome=Outcome(found[2]),
            blocked_until=_when(found[3]),
            next_due=_when(found[4]),
            rows_last=int(found[5]),
            etag=found[6],
            last_modified=found[7],
            sha256=found[8],
            derived_version=found[9],
        )

    def sources(self) -> list[SourceState]:
        """Every source the ledger has seen, by id."""
        ids = [row[0] for row in self._db.execute("SELECT source_id FROM sources ORDER BY 1")]
        return [state for source_id in ids if (state := self.source(source_id)) is not None]

    def rows(self, source_id: str, *, include_gone: bool = True) -> list[LedgerRow]:
        """A source's keys, oldest first."""
        query = _SELECT_ROWS + " WHERE source_id = ?"
        if not include_gone:
            query += " AND gone = 0"
        found = self._db.execute(query + " ORDER BY hi, key", (source_id,)).fetchall()
        return [_ledger_row(row) for row in found]

    def row(self, key: bytes) -> LedgerRow | None:
        found = self._db.execute(_SELECT_ROWS + " WHERE key = ?", (key,)).fetchone()
        return None if found is None else _ledger_row(found)

    def good_reads(self, source_id: str) -> list[datetime]:
        """The times of a source's good reads in the last 14 days, oldest first."""
        found = self._db.execute(
            "SELECT at FROM good_reads WHERE source_id = ? ORDER BY at", (source_id,)
        )
        return [datetime.fromisoformat(row[0]) for row in found]

    # --- writes ------------------------------------------------------------------------------

    def observe(
        self,
        source_id: str,
        outcome: Outcome,
        fetched_at: datetime,
        rows: Sequence[SeenRow] = (),
    ) -> Observed:
        """Fold one read of a source into the ledger (see the module's rules).

        A ``not_modified`` read may come without its rows: it then confirms the last
        good read as it was (see :meth:`_confirm`). Pass the rows when the fetch layer
        has them, so the read is checked like any other.
        """
        previous = self.source(source_id)
        with self._db:
            if outcome not in GOOD:
                self._set_outcome(source_id, outcome, previous)
                return Observed(outcome=outcome)
            last = previous.last_good_at if previous is not None else None
            if last is not None and fetched_at <= last:
                self._set_outcome(source_id, Outcome.LATE, previous)
                return Observed(outcome=Outcome.LATE)
            if outcome is Outcome.NOT_MODIFIED and not rows:
                return self._confirm(source_id, fetched_at, previous)
            keys = {self.key(source_id, row): row for row in rows}
            duplicates = len(rows) - len(keys)
            if self._partial(source_id, previous, keys):
                return Observed(outcome=Outcome.PARTIAL, counts={"duplicate_keys": duplicates})
            observed = self._good(source_id, outcome, fetched_at, keys, last)
            return replace(observed, counts={**observed.counts, "duplicate_keys": duplicates})

    def _confirm(
        self, source_id: str, fetched_at: datetime, previous: SourceState | None
    ) -> Observed:
        """A ``not_modified`` read without rows: the body is the last good read's.

        It refreshes the rows present and the source's hold, and changes no presence.
        After a partial read the validators may be the partial body's, so it changes
        nothing then (``partial``). Before any good read it cannot be placed.

        Raises:
            ValueError: the source has no good read for the 304 to confirm.
        """
        if previous is None or previous.last_good_at is None:
            raise ValueError("a not_modified read without rows needs an earlier good read")
        if previous.last_outcome is Outcome.PARTIAL:
            return Observed(outcome=Outcome.PARTIAL)
        now = _iso(fetched_at)
        self._db.execute(
            "UPDATE rows SET last_seen = ? WHERE source_id = ? AND absent_since IS NULL",
            (now, source_id),
        )
        gone = self._age(source_id, fetched_at)
        self._db.execute(
            "UPDATE sources SET last_good_at = ?, last_outcome = ?, pending = NULL"
            " WHERE source_id = ?",
            (now, Outcome.NOT_MODIFIED.value, source_id),
        )
        self._db.execute("INSERT INTO good_reads VALUES (?, ?)", (source_id, now))
        return Observed(
            outcome=Outcome.NOT_MODIFIED,
            gone=tuple(gone),
            counts={"rows": previous.rows_last, "gone": len(gone)},
        )

    def _age(self, source_id: str, fetched_at: datetime) -> list[bytes]:
        """Mark gone every key absent 3 hours or more since a live read lacked it."""
        gone: list[bytes] = []
        for entry in self.rows(source_id, include_gone=False):
            absent = entry.absent_since
            if absent is not None and entry.lapsed and fetched_at - absent >= FLAP:
                gone.append(entry.key)
                self._db.execute("UPDATE rows SET gone = 1 WHERE key = ?", (entry.key,))
        return sorted(gone)

    def _partial(
        self, source_id: str, previous: SourceState | None, keys: Mapping[bytes, SeenRow]
    ) -> bool:
        if (
            previous is None
            or previous.rows_last == 0
            or len(keys) > PARTIAL_SHARE * previous.rows_last
        ):
            return False
        digest = _keys_digest(keys)
        pending = self._db.execute(
            "SELECT pending FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone()
        if pending is not None and pending[0] == digest:
            return False  # the same smaller list twice in a row: the list really shrank
        self._db.execute(
            "UPDATE sources SET last_outcome = ?, pending = ? WHERE source_id = ?",
            (Outcome.PARTIAL.value, digest, source_id),
        )
        return True

    def _good(  # noqa: PLR0912, PLR0915 - the module's rules, in order
        self,
        source_id: str,
        outcome: Outcome,
        fetched_at: datetime,
        keys: Mapping[bytes, SeenRow],
        last: datetime | None,
    ) -> Observed:
        known = {row.key: row for row in self.rows(source_id, include_gone=False)}
        before = {key for key, row in known.items() if row.absent_since is None}
        idents = {key: self.ident(source_id, row) for key, row in keys.items()}
        listed_before = {known[key].ident for key in before}
        listed_now = set(idents.values())
        churn = _churn(listed_before, listed_now)
        new = [key for key in keys if key not in known]
        key_churn = _churn(before, set(keys))
        absent_by_ident: dict[bytes, list[LedgerRow]] = {}
        for key, entry in known.items():
            if key not in keys:
                absent_by_ident.setdefault(entry.ident, []).append(entry)
        warm = last is not None and fetched_at - last <= self.longest
        now = _iso(fetched_at)
        returned: list[bytes] = []
        reappeared: list[bytes] = []
        for key in keys.keys() & known.keys():
            entry = known[key]
            absent = entry.absent_since
            if absent is not None and fetched_at - absent >= FLAP:
                if entry.lapsed:
                    reappeared.append(key)  # T1f: a new appearance, dated as any new key
                    continue
                if _earlier_day(entry.hi, fetched_at):
                    reappeared.append(key)  # back on a later day: when it went up is unknown
                    continue
            if absent is not None:
                returned.append(key)
            self._db.execute(
                "UPDATE rows SET last_seen = ?, absent_since = NULL, lapsed = 0 WHERE key = ?",
                (now, key),
            )
        successors: list[bytes] = []
        ambiguous = 0
        for key in [*new, *reappeared]:
            pred: bytes | None = None
            tied = False
            if key in new:
                pred, tied = _predecessor(absent_by_ident.get(idents[key], []))
            ambiguous += tied
            if pred is not None:
                successors.append(key)
            if key in reappeared and not known[key].lapsed:
                lo = None
            elif warm and not tied and (pred is not None or not (churn or key_churn)):
                lo = last
            else:
                lo = None
            if lo is not None:
                start = Start.WARM
            elif warm and (churn or key_churn) and not tied and key not in reappeared:
                start = Start.CHURN
            else:
                start = Start.COLD
            self._db.execute(
                _INSERT_ROW,
                (
                    key,
                    source_id,
                    now,
                    _iso(lo),
                    start.value,
                    _iso(keys[key].row_stamp),
                    now,
                    idents[key],
                    pred,
                ),
            )
            self._db.execute("DELETE FROM derived WHERE key = ?", (key,))
            self._db.execute("DELETE FROM darkens WHERE key = ?", (key,))
        vanished: list[bytes] = []
        for key in known.keys() - keys.keys():
            if known[key].absent_since is None:
                vanished.append(key)
                self._db.execute("UPDATE rows SET absent_since = ? WHERE key = ?", (now, key))
            if new:
                self._db.execute("UPDATE rows SET lapsed = 1 WHERE key = ?", (key,))
        gone = self._age(source_id, fetched_at)
        cutoff = _iso(fetched_at - PRUNE)
        pruned = [
            row[0]
            for row in self._db.execute(
                "SELECT key FROM rows WHERE source_id = ? AND last_seen < ?", (source_id, cutoff)
            )
        ]
        for key in pruned:
            self._db.execute("DELETE FROM rows WHERE key = ?", (key,))
            self._db.execute("DELETE FROM derived WHERE key = ?", (key,))
            self._db.execute("DELETE FROM darkens WHERE key = ?", (key,))
        self._db.execute(
            "INSERT INTO sources (source_id, last_good_at, last_outcome, rows_last, pending)"
            " VALUES (?, ?, ?, ?, NULL) ON CONFLICT (source_id) DO UPDATE SET"
            " last_good_at = excluded.last_good_at, last_outcome = excluded.last_outcome,"
            " rows_last = excluded.rows_last, pending = NULL",
            (source_id, now, outcome.value, len(keys)),
        )
        self._db.execute("INSERT INTO good_reads VALUES (?, ?)", (source_id, now))
        self._db.execute(
            "DELETE FROM good_reads WHERE source_id = ? AND at < ?", (source_id, cutoff)
        )
        return Observed(
            outcome=outcome,
            new=tuple(sorted(new)),
            returned=tuple(sorted(returned)),
            vanished=tuple(sorted(vanished)),
            gone=tuple(gone),
            successors=tuple(sorted(successors)),
            churn=churn,
            key_churn=key_churn,
            reappeared=tuple(sorted(reappeared)),
            counts={
                "rows": len(keys),
                "new": len(new),
                "successors": len(successors),
                "ambiguous_successors": ambiguous,
                "returned": len(returned),
                "reappeared": len(reappeared),
                "vanished": len(vanished),
                "gone": len(gone),
                "pruned": len(pruned),
            },
        )

    def _set_outcome(self, source_id: str, outcome: Outcome, previous: SourceState | None) -> None:
        if previous is None:
            self._db.execute(
                "INSERT INTO sources (source_id, last_outcome) VALUES (?, ?)",
                (source_id, outcome.value),
            )
        else:
            self._db.execute(
                "UPDATE sources SET last_outcome = ? WHERE source_id = ?",
                (outcome.value, source_id),
            )

    def set_fetch_state(  # noqa: PLR0913 - the fields the fetch layer keeps
        self,
        source_id: str,
        *,
        blocked_until: datetime | None = None,
        next_due: datetime | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        sha256: str | None = None,
    ) -> None:
        """Keep a source's fetch state: its block, its next due time and its validators."""
        with self._db:
            if self.source(source_id) is None:
                self._set_outcome(source_id, Outcome.DEFERRED, None)
            self._db.execute(
                "UPDATE sources SET blocked_until = ?, next_due = ?, etag = ?,"
                " last_modified = ?, sha256 = ? WHERE source_id = ?",
                (_iso(blocked_until), _iso(next_due), etag, last_modified, sha256, source_id),
            )

    def reword(self, key: bytes) -> None:
        """Leave a successor undated (:attr:`Start.REWORDED`): whether its words were posted
        at its first sighting or re-render its predecessor's posting cannot be told, and its
        reading depends on which. It then darkens only, under every later version."""
        with self._db:
            self._db.execute(
                "UPDATE rows SET lo = NULL, start = ?, row_stamp = NULL, pred = NULL WHERE key = ?",
                (Start.REWORDED.value, key),
            )

    def widen(self, key: bytes, lo: datetime | None, start: Start) -> None:
        """Date a successor that reads the same at its own interval and its predecessor's
        from the earliest either can have been posted (``lo``; ``None`` when unknown): it
        may re-render the old posting, so merge must not take it for newer words."""
        with self._db:
            self._db.execute(
                "UPDATE rows SET lo = ?, start = ?, pred = NULL WHERE key = ?",
                (_iso(lo), start.value, key),
            )

    def settle(self, key: bytes) -> None:
        """Keep a successor's own dating: it says something its predecessor did not."""
        with self._db:
            self._db.execute("UPDATE rows SET pred = NULL WHERE key = ?", (key,))

    # --- derived results ---------------------------------------------------------------------

    def derived(self, key: bytes, version: str) -> object | None:
        """The derived result stored for a key under ``version``, or ``None``."""
        found = self._db.execute(
            "SELECT version, payload FROM derived WHERE key = ?", (key,)
        ).fetchone()
        if found is None or found[0] != version:
            return None
        return _payload(found[1])

    def last_derived(self, key: bytes) -> tuple[str, object] | None:
        """The derived result last stored for a key, under whatever version, or ``None``."""
        found = self._db.execute(
            "SELECT version, payload FROM derived WHERE key = ?", (key,)
        ).fetchone()
        if found is None:
            return None
        return str(found[0]), _payload(found[1])

    def store_derived(
        self, key: bytes, version: str, payload: object, darkens: Darkens | None = None
    ) -> None:
        """Keep a key's derived result (codes, times and ids only) under ``version``, and
        the part of it that darkens (``darkens``: ``None`` when it darkens nothing) in its
        own plain form, which reads back under any version (:meth:`darkens`)."""
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        parts: list[tuple[bytes, str, str]] = []
        if darkens is not None:
            parts += [(key, "school", nces_id) for nces_id in sorted(set(darkens.schools))]
            if darkens.days is None:
                parts.append((key, "every", ""))
            else:
                parts += [(key, "day", day.isoformat()) for day in sorted(set(darkens.days))]
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO derived (key, version, payload) VALUES (?, ?, ?)",
                (key, version, text),
            )
            self._db.execute("DELETE FROM darkens WHERE key = ?", (key,))
            self._db.executemany("INSERT INTO darkens (key, part, value) VALUES (?, ?, ?)", parts)
            self._db.execute(
                "UPDATE sources SET derived_version = ? WHERE source_id ="
                " (SELECT source_id FROM rows WHERE key = ?)",
                (version, key),
            )

    def darkens(self, key: bytes) -> Darkens | None:
        """The darkening part last stored for a key, or ``None`` when it darkens nothing.

        It always reads: a day that is not a date, or a part of another kind, reads as
        every day (the stored form can only darken more, never less).
        """
        schools: list[str] = []
        days: set[date] = set()
        every = False
        for part, value in self._db.execute(
            "SELECT part, value FROM darkens WHERE key = ?", (key,)
        ):
            if part == "school" and isinstance(value, str) and value:
                schools.append(value)
                continue
            if part == "day" and isinstance(value, str):
                try:
                    days.add(date.fromisoformat(value))
                    continue
                except ValueError:
                    pass
            every = True
        if not schools:
            return None
        return Darkens(
            schools=tuple(sorted(set(schools))),
            days=None if every or not days else tuple(sorted(days)),
        )


def _payload(text: object) -> object:
    """A stored payload read back; one that is not JSON text reads as ``None`` (never fatal)."""
    if not isinstance(text, str):
        return None
    try:
        loaded: object = json.loads(text)
    except json.JSONDecodeError:
        return None
    return loaded


def _ledger_row(found: tuple[object, ...]) -> LedgerRow:
    key, source_id, hi, lo, start, stamp, last_seen, absent, gone, ident, pred, lapsed = found
    if (
        not isinstance(key, bytes)
        or not isinstance(source_id, str)
        or not isinstance(ident, bytes)
        or not (pred is None or isinstance(pred, bytes))
    ):
        raise TypeError("a ledger row has the wrong shape")
    return LedgerRow(
        key=key,
        source_id=source_id,
        hi=datetime.fromisoformat(str(hi)),
        lo=_when(None if lo is None else str(lo)),
        start=Start(str(start)),
        row_stamp=_when(None if stamp is None else str(stamp)),
        last_seen=datetime.fromisoformat(str(last_seen)),
        absent_since=_when(None if absent is None else str(absent)),
        gone=bool(gone),
        ident=ident,
        pred=pred,
        lapsed=bool(lapsed),
    )

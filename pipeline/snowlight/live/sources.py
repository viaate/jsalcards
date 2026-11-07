"""Where each lit closing came from, for the admin page only (ADMIN-SOURCES).

In the idle time after the morning record's shipment (every :00 and :30 UTC), the live reader
reads the last publish's private ``provenance.jsonl`` and ships, for each local day the
publish covers (:func:`~snowlight.schemas.live.local_days`), a small summary of every lit
status's sources to the accounts database (``snowlight-accounts``, which the API Worker
already reads; found by its exact name and never created): the winning source's id and type,
its public link from the registry (its page, else a list file it GETs), the row's times
(``lo``, ``hi``, ``row_stamp``), whether it is still on its list (``present``), the source
whose time shows as "Posted", and every contributing source's id and type. Codes, ids,
links and times only: never a list's text, no row key. Nothing here reaches a public file;
the API serves it to the admin alone (``GET /v1/admin/sources``).

**Tables** (``api/migrations/0005_lit_sources.sql``): ``lit_sources(day, n, data)``, the
day's summary as gzip, cut into :data:`~snowlight.live.d1.CHUNK_BYTES` pieces, each base64
(at most :data:`MAX_PARTS`); ``lit_sources_head(day, sha256, parts, closings, published_at,
written_at, mode, latest_at)``; ``lit_sources_budget(day, rows)``: the rows these writes took
each UTC day.

**Mode and later publishes.** Each head carries the publisher's mode (``on``, or ``shadow``:
those statuses are not on the public map, and the page says so), and ``latest_at``: the
publisher's last publish or the start of the last hold it recorded (its memory), when that is
later than the publish the summary is from (the newest ``generated_at`` its lines carry, the
time each head shows). A blank publish (a hold, the breaker), a hold set by ``live blank`` in
another process (the reader records its start on its first held pass) and an upload that
failed after the closings file was written do not rewrite ``provenance.jsonl``, so the summary
is then the earlier publish's and the page says the map was published again at
``latest_at``. A file with no line is judged by the file's time, so a later publish is still named.
A day too big to ship keeps its last shipped summary and gets the later publish's time as its
``latest_at``. With no ``provenance.jsonl`` yet in this run (its first publish was blank), the
heads already stored get ``latest_at``. With publishing off, nothing is shipped.
A day's parts go first (8 a request), then its head and the trim of its old parts; until
the head names them the admin page sees parts that fail the sha256 and says the day is
being written, so a half-written day never shows. A day whose
summary did not change only has its head's times updated (one row); a day whose shipment
failed partway is written whole again at the next one, whatever its content. Days before the first
local day of the publish are kept as they were last shipped (yesterday's last word), and
days before that are deleted (today and yesterday only).

**Bounds.** At most :data:`SOURCES_ROWS` rows a UTC day (5% of the account's free 100,000;
a normal day writes a few hundred); a shipment that would pass it ships nothing and
says so. Every request ends by the deadline the loop gives; the rows a shipment wrote
(those of a request whose answer was lost included) are billed even when it ran out of time,
in one last request given :data:`BILL_GRACE` past the deadline (a bill that fails is kept and
sent with the next shipment). A failure is one line in the log (counts and codes only) and
never touches the pass or the state push.
"""

import base64
import gzip
import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from snowlight.live.d1 import CHUNK_BYTES, WORKFLOW, WRITE_BATCH, Answer, D1Api, D1Error, Statement
from snowlight.schemas.live import local_days

ACCOUNTS: Final = "snowlight-accounts"
MAX_PARTS: Final = 16
"""Parts a day may take (16 x 64 KiB of gzip: about 30,000 lit statuses)."""
SOURCES_ROWS: Final = 5_000
"""Rows these writes may take a UTC day."""
KEEP_DAYS: Final = 1
"""Days kept before the publish's first local day: yesterday."""
BILL_GRACE: Final = 5.0
"""Seconds the bill may take past the deadline (inside the loop's 30-s push margin)."""
MODES: Final = frozenset({"on", "shadow"})
"""The publisher's modes whose publishes are shipped (``off`` publishes nothing)."""

_HEADS: Final = "SELECT day, sha256 FROM lit_sources_head"
_BUDGET: Final = "SELECT rows FROM lit_sources_budget WHERE day = ?"
_PART: Final = (
    "INSERT INTO lit_sources (day, n, data) VALUES (?, ?, ?)"
    " ON CONFLICT (day, n) DO UPDATE SET data = excluded.data"
)
_HEAD: Final = (
    "INSERT INTO lit_sources_head"
    " (day, sha256, parts, closings, published_at, written_at, mode, latest_at)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (day) DO UPDATE SET sha256 = excluded.sha256,"
    " parts = excluded.parts, closings = excluded.closings,"
    " published_at = excluded.published_at, written_at = excluded.written_at,"
    " mode = excluded.mode, latest_at = excluded.latest_at"
)
_TRIM: Final = "DELETE FROM lit_sources WHERE day = ? AND n >= ?"
_TOUCH: Final = (
    "UPDATE lit_sources_head SET published_at = ?, written_at = ?, mode = ?, latest_at = ?"
    " WHERE day = ?"
)
_LATER: Final = (
    "UPDATE lit_sources_head SET latest_at = ?, written_at = ?"
    " WHERE day >= ? AND published_at < ? AND (latest_at IS NULL OR latest_at < ?)"
)
_BEHIND: Final = (
    "UPDATE lit_sources_head SET latest_at = ?, written_at = ?"
    " WHERE day = ? AND published_at < ? AND (latest_at IS NULL OR latest_at < ?)"
)
_DROP_HEADS: Final = "DELETE FROM lit_sources_head WHERE day < ?"
_DROP_PARTS: Final = "DELETE FROM lit_sources WHERE day < ?"
_SPEND: Final = (
    "INSERT INTO lit_sources_budget (day, rows) VALUES (?, ?)"
    " ON CONFLICT (day) DO UPDATE SET rows = rows + excluded.rows"
)
_DROP_BUDGET: Final = "DELETE FROM lit_sources_budget WHERE day < ?"
STATEMENTS: Final = frozenset(
    {_HEADS, _BUDGET, _PART, _HEAD, _TRIM, _TOUCH, _DROP_HEADS, _DROP_PARTS, _SPEND}
    | {_DROP_BUDGET, _LATER, _BEHIND}
)
"""Every statement the shipper sends; nothing else is ever sent (its own three tables only)."""


class SourcesError(D1Error):
    """The shipment could not run (codes only)."""


@dataclass(frozen=True, slots=True)
class SourcesShipped:
    """What one shipment did (counts and times only)."""

    outcome: str
    """``shipped``; ``same`` (nothing new since the last shipment); ``capped`` (the day's
    rows would pass :data:`SOURCES_ROWS`); ``none`` (no publish yet)."""
    days: int = 0
    changed: int = 0
    closings: int = 0
    parts: int = 0
    rows: int = 0
    too_big: int = 0
    seconds: float = 0.0

    def line(self) -> str:
        """The log line: counts only."""
        return (
            f"sources shipped: {self.outcome}, {self.days} days, {self.changed} changed, "
            f"{self.closings} statuses, {self.parts} parts, {self.rows} rows, "
            f"{self.too_big} too big, {self.seconds * 1000:.0f} ms"
        )


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def summary(line: Mapping[str, Any]) -> dict[str, Any]:
    """One provenance line as the admin sees it: codes, ids and times only (no row key)."""
    contributing = line.get("contributing")
    rows = contributing if isinstance(contributing, list) else []
    kinds: dict[str, str] = {}
    posted = None
    for row in rows:
        if isinstance(row, list) and len(row) >= 2 and isinstance(row[0], str):  # noqa: PLR2004
            kinds.setdefault(row[0], str(row[1]))
            if len(row) >= 3 and row[2] == line.get("announced_by"):  # noqa: PLR2004
                posted = row[0]
    status = line.get("status")
    reason = line.get("reason")
    return {
        "nces": str(line.get("nces_id", "")),
        "status": status if isinstance(status, int) else None,
        "reason": reason if isinstance(reason, int) else None,
        "level": _str(line.get("target_level")),
        "source": _str(line.get("source_id")),
        "type": _str(line.get("source_type")),
        "lo": _str(line.get("lo")),
        "hi": _str(line.get("hi")),
        "row_stamp": _str(line.get("row_stamp")),
        "present": line.get("present") is True,
        "posted_by": posted,
        "contributing": [[source, kind] for source, kind in kinds.items()],
    }


def day_bytes(lines: Sequence[Mapping[str, Any]], links: Mapping[str, str]) -> bytes:
    """A day's summary, canonical (equal content gives equal bytes)."""
    closings = sorted((summary(line) for line in lines), key=lambda c: (c["nces"], c["source"]))
    used = {source for c in closings for source, _ in c["contributing"]}
    used |= {c["source"] for c in closings if c["source"] is not None}
    body = {
        "v": 1,
        "closings": closings,
        "links": {source: links[source] for source in sorted(used) if source in links},
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def pack(data: bytes) -> list[str]:
    """gzip (mtime 0), cut into :data:`CHUNK_BYTES` pieces, each base64."""
    packed = gzip.compress(data, compresslevel=6, mtime=0)
    pieces = [packed[at : at + CHUNK_BYTES] for at in range(0, len(packed), CHUNK_BYTES)]
    return [base64.b64encode(piece).decode("ascii") for piece in pieces]


def read_days(path: Path) -> tuple[datetime, dict[date, list[dict[str, Any]]]] | None:
    """The file's time and its lines by local day; ``None``: no file yet."""
    try:
        stat = path.stat()
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    at = datetime.fromtimestamp(stat.st_mtime, UTC).replace(microsecond=0)
    days: dict[date, list[dict[str, Any]]] = {}
    for raw in text.splitlines():
        if not raw.strip():
            continue
        line = json.loads(raw)
        if isinstance(line, dict) and isinstance(line.get("day"), str):
            days.setdefault(date.fromisoformat(line["day"]), []).append(line)
    return at, days


@dataclass(slots=True)
class _Plan:
    work: list[tuple[str, list[Statement]]] = field(default_factory=list)
    """Each changed day and its batch: its parts, its head, the trim of its old parts."""
    touch: list[Statement] = field(default_factory=list)
    """The unchanged days' head times."""
    closings: int = 0
    parts: int = 0
    too_big: int = 0


def _second(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(microsecond=0)


@dataclass(slots=True)
class SourcesShipper:
    """Ships the lit statuses' sources to the accounts database (see the module)."""

    api: D1Api
    env: Mapping[str, str]
    links: Mapping[str, str]
    """Each registry station's public link, by source id (:func:`station_links`)."""
    publish: Callable[[], tuple[str, datetime | None]]
    """The publisher's mode (``on``, ``shadow``, ``off``) and its last publish time from its
    memory (a blank one included; ``None``: none yet)."""
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    monotonic: Callable[[], float] = time.monotonic
    _database: str | None = None
    _last: tuple[float | None, datetime | None, str] | None = None
    """The provenance file's mtime, the last publish and the mode at the last good shipment
    (unchanged: nothing is asked)."""
    _unbilled: int = 0
    """Rows written and not yet billed (a bill that failed is sent with the next shipment)."""
    _broken: set[str] = field(default_factory=set)
    """Days whose shipment failed partway (some parts may be overwritten under the old head):
    written whole at the next shipment even when their content is the head's again."""

    def database(self) -> str:
        """The accounts database's id, by its exact name (never created).

        Raises:
            SourcesError: the account lists none, or more than one.
        """
        if self._database is None:
            found = [uuid for name, uuid in self.api.databases(ACCOUNTS) if name == ACCOUNTS]
            if len(found) != 1:
                raise SourcesError(f"the account lists {len(found)} accounts databases")
            self._database = found[0]
        return self._database

    def ship(self, path: Path, *, deadline: datetime) -> SourcesShipped:
        """Ship the summaries of ``path`` (``provenance.jsonl``), all of it by ``deadline``
        (the bill alone may take :data:`BILL_GRACE` more).

        Raises:
            SourcesError: not a live-read run, or no accounts database.
            D1Error: the database cannot be read or written, or the time ran out.
        """
        if self.env.get("GITHUB_WORKFLOW") != WORKFLOW:
            raise SourcesError(f"only a {WORKFLOW} run ships the sources")
        began = self.monotonic()
        api: Any = self.api
        previous = getattr(api, "deadline", None)
        if hasattr(api, "deadline") and hasattr(api, "monotonic"):
            left = max(0.0, (deadline - self.clock()).total_seconds())
            budget = api.monotonic() + left
            api.deadline = budget if previous is None else min(previous, budget)
        try:
            found = self._ship(path, deadline)
        finally:
            if hasattr(api, "deadline"):
                api.deadline = previous
        return replace(found, seconds=self.monotonic() - began)

    def _run(self, statements: Sequence[Statement], deadline: datetime) -> list[Answer]:
        for sql, _ in statements:
            if sql not in STATEMENTS:  # pragma: no cover - a programming error
                raise SourcesError("refused a statement the shipper does not own")
        if self.clock() >= deadline:
            raise SourcesError("the shipment ran out of time")
        database = self.database()
        lost = getattr(self.api, "lost_rows", 0)
        try:
            answers = self.api.run(database, statements)
        finally:
            # writes that may have run with their answer lost are billed too
            self._unbilled += max(0, getattr(self.api, "lost_rows", 0) - lost)
        if len(answers) != len(statements):
            raise SourcesError("the answer holds another number of results")
        self._unbilled += sum(answer.rows_written for answer in answers)
        return answers

    def _bill(self, bill: str) -> None:
        """Bill the unbilled rows (and the bill's own), past the deadline by at most
        :data:`BILL_GRACE`: the cap never goes blind on a slow day."""
        if not self._unbilled:
            return
        api: Any = self.api
        if hasattr(api, "deadline") and hasattr(api, "monotonic"):
            api.deadline = api.monotonic() + BILL_GRACE  # ship() puts the caller's back
        self.api.run(self.database(), [(_SPEND, (bill, self._unbilled + 2))])
        self._unbilled = 0

    def _plan(  # noqa: PLR0913 - one shipment's days, heads and labels
        self,
        window: Sequence[date],
        by_day: Mapping[date, Sequence[Mapping[str, Any]]],
        heads: Mapping[str, str],
        at: str,
        *,
        stamp: str,
        label: tuple[str, str | None],
    ) -> _Plan:
        """Each day's statements; ``label``: the head's mode and ``latest_at``."""
        plan = _Plan()
        for day in window:
            key = day.isoformat()
            lines = by_day.get(day, [])
            data = day_bytes(lines, self.links)
            sha = hashlib.sha256(data).hexdigest()
            if heads.get(key) == sha and key not in self._broken:
                plan.touch.append((_TOUCH, (at, stamp, *label, key)))
                plan.closings += len(lines)
                continue
            texts = pack(data)
            if len(texts) > MAX_PARTS:
                # the head keeps the last shipped version, with its time, and says when the
                # map was published again
                plan.too_big += 1
                behind = label[1] or at
                plan.touch.append((_BEHIND, (behind, stamp, key, behind, behind)))
                continue
            statements: list[Statement] = [(_PART, (key, n, text)) for n, text in enumerate(texts)]
            statements.append((_HEAD, (key, sha, len(texts), len(lines), at, stamp, *label)))
            statements.append((_TRIM, (key, len(texts))))
            plan.work.append((key, statements))
            plan.closings += len(lines)
            plan.parts += len(texts)
        return plan

    def _write(self, plan: _Plan, keep: str | None, bill: str, deadline: datetime) -> int:
        """Send the plan (and the prune of days before ``keep``), then the bill; the rows
        this wrote."""
        before = self._unbilled
        try:
            for key, statements in plan.work:
                # parts first, the head last: until the head names them, the API's reader
                # sees parts that fail the head's sha256 and shows the day as being written
                self._broken.add(key)
                for start in range(0, len(statements), WRITE_BATCH):
                    self._run(statements[start : start + WRITE_BATCH], deadline)
                self._broken.discard(key)
            if plan.touch:
                self._run(plan.touch, deadline)
            if keep is not None:
                drops: list[Statement] = [
                    (_DROP_HEADS, (keep,)),
                    (_DROP_PARTS, (keep,)),
                    (_DROP_BUDGET, (keep,)),
                ]
                self._run(drops, deadline)
        finally:
            written = self._unbilled - before
            self._bill(bill)  # even when the time ran out: the cap never goes blind
        return written

    def _ship(self, path: Path, deadline: datetime) -> SourcesShipped:
        mode, latest = self.publish()
        if mode not in MODES:
            return SourcesShipped("none")
        try:
            mtime: float | None = path.stat().st_mtime
        except FileNotFoundError:
            mtime = None
        latest = None if latest is None else _second(latest)
        seen = (mtime, latest, mode)
        if seen == self._last:
            return SourcesShipped("same")
        read = read_days(path)
        by_day: Mapping[date, Sequence[Mapping[str, Any]]] = {}
        newest: datetime | None = None
        if read is not None:
            published, newest, by_day = _stamped(*read)
        elif latest is not None:
            published = latest
        else:
            return SourcesShipped("none")
        now = self.clock().astimezone(UTC)
        bill = now.date().isoformat()
        stamp = now.replace(microsecond=0).isoformat()
        first, last = local_days(published)
        window = (
            [] if read is None else [first + timedelta(n) for n in range((last - first).days + 1)]
        )
        if read is not None:
            self._broken &= {day.isoformat() for day in window}
        # the summary is from an earlier publish when the publisher's last one (a blank, a
        # hold, an upload that failed after the closings file) did not rewrite the file: the
        # page then says when the map was published again
        stale = read is None or (newest is not None and latest is not None and latest > newest)
        later = latest.isoformat() if stale and latest is not None else None
        found = self._run([(_HEADS, ()), (_BUDGET, (bill,))], deadline)
        heads = {str(row.get("day")): str(row.get("sha256")) for row in found[0].rows}
        spent = int(found[1].rows[0].get("rows", 0)) if found[1].rows else 0
        keep = (first - timedelta(days=KEEP_DAYS)).isoformat()
        label = (mode, later)
        plan = self._plan(window, by_day, heads, published.isoformat(), stamp=stamp, label=label)
        if read is None and later is not None:
            # no file in this run yet (its first publish was blank): the stored heads say so
            plan.touch.append((_LATER, (later, stamp, first.isoformat(), later, later)))
        changed, closings, parts, too_big = len(plan.work), plan.closings, plan.parts, plan.too_big
        prune = read is not None and any(day < keep for day in heads)
        cost = 2 * parts + 3 * changed + len(plan.touch) + len(heads) + (4 if prune else 0) + 2
        if spent + self._unbilled + cost > SOURCES_ROWS:
            return SourcesShipped("capped", len(window), changed, closings, parts, 0, too_big)
        written = self._write(plan, keep if prune else None, bill, deadline)
        if too_big == 0:
            self._last = seen
        outcome = "none" if read is None else "shipped" if changed else "later" if later else "same"
        return SourcesShipped(outcome, len(window), changed, closings, parts, written, too_big)


def _stamped(
    at: datetime, by_day: dict[date, list[dict[str, Any]]]
) -> tuple[datetime, datetime | None, dict[date, list[dict[str, Any]]]]:
    """The publish's own stamp (the newest ``generated_at`` its lines carry: the file is
    written after the publish, seconds later; the file's time when no line carries one),
    that stamp again for the staleness test (the file's time when there is no line, so a
    later publish, such as a first lit one whose upload failed after the closings file, is
    still named) and the lines."""
    if not any(by_day.values()):
        return at, at, by_day
    newest = _newest(by_day) or at
    return newest, newest, by_day


def _newest(by_day: Mapping[date, Sequence[Mapping[str, Any]]]) -> datetime | None:
    """The newest ``generated_at`` the lines carry (``None``: none does)."""
    found = None
    for lines in by_day.values():
        for line in lines:
            text = line.get("generated_at")
            if isinstance(text, str):
                try:
                    moment = _second(datetime.fromisoformat(text))
                except ValueError:
                    continue
                found = moment if found is None or moment > found else found
    return found


def station_links(stations: Mapping[str, Any]) -> dict[str, str]:
    """Each registry station's public link, by id, whatever its source type: its page, else
    the list file the reader reads when that answers a plain GET (a station with only a
    ``data_url``). Stations with neither, and POST-only endpoints, are left out."""
    links: dict[str, str] = {}
    for source, station in stations.items():
        url = getattr(station, "page_url", None)
        if url is None and getattr(station, "data_post", None) is None:
            url = getattr(station, "data_url", None)
        if url is not None:
            links[source] = str(url)
    return links

"""The live reader's private state in a D1 database, over the Cloudflare API (S8-E section 2).

The state folder (:func:`snowlight.live.state.pack`) is kept in the database
``snowlight-live-state`` of the owner's Cloudflare account, reached with the repository's
``CLOUDFLARE_API_TOKEN`` and ``CLOUDFLARE_ACCOUNT_ID``. No Worker is bound to it, so nothing
on the internet reaches it. The store runs only its own fixed statements, values always as
bound parameters, finds the database by its exact name (and uses no other id), and never
logs or prints an answer's body: an error names the HTTP status or a code only.

**Tables.** ``chunks(slot, n, data)``: the packed state, 64 KiB per chunk as base64;
``head`` (one row, ``id = 1``): the epoch, the slot ``head`` names with its part count and
sha256, the previous slot, the size, when and by which run it was pushed; ``budget(day,
rows)``: the rows written each UTC day; ``holds(source_id, until, why)``: blocks and
``Retry-After`` waits (codes and times only).

**Pull** (:meth:`D1StateStore.pull`): read ``head``. With exactly one row, read its slot
(16 chunks a request) and check its sha256 and that every SQLite file in it passes ``PRAGMA
quick_check``; on a mismatch or a damaged ledger read the previous slot. Then take
the epoch: ``UPDATE head SET epoch = epoch + 1 ... WHERE epoch = <read>`` must change one row
(the newest puller wins), and the new epoch goes in ``d1.json`` (never packed). No ``head``
row (an HTTP 200 with zero rows, nothing else) means a first run: a plain ``INSERT`` of
epoch 1, which fails when a row appeared meanwhile. The database is created only when the
account's list answers HTTP 200 and names no database exactly ``snowlight-live-state``.
Any other answer is a failed pull (:class:`D1Error`). Both slots failing their sha256 is a
failed pull too (:class:`UnreadableStateError`), until ``head`` was last pushed over 2 hours
ago: then the epoch is taken and the run starts empty (cold), so a readable state is never
overwritten by an empty one.

**Push** (:meth:`D1StateStore.push`): read ``head``; another epoch there means this run lost
the state (:class:`LostStateError`: stop pushing). Else write this epoch's own slot
(``e<epoch>a`` or ``e<epoch>b``, whichever ``head`` does not name) with upserts (no
``DELETE``), then swap ``head`` to it ``WHERE epoch = <mine> AND sha256 IS <the one just
read>``: one changed row or the state is lost. After this epoch's second good push the
chunks of slots ``head`` names neither as current nor previous are deleted (one handoff's
worth). An older writer (a cancelled run's end step) sees another epoch and writes nothing;
if it read ``head`` just before the successor took the epoch it writes only its own slot,
which ``head`` does not name, and its swap fails. ``head`` always names bytes that match its
sha256.

**Write cap.** Every answer's ``meta.rows_written`` is counted, and each push adds the count
to ``budget`` for the UTC day. Past :data:`HOURLY_FROM` rows the loop pushes hourly
(:attr:`PushResult.hourly`); a push that would take the day past :data:`WRITE_CAP` is
refused (:class:`WriteCapError`); a first push of a run that writes more than
:data:`FIRST_PUSH_SLACK` times its plan (parts + 2) switches the run to hourly and raises
the ``state`` alert. That leaves 70% of the account's 100,000 daily writes to the accounts
database.

The store takes an epoch or pushes only when ``GITHUB_WORKFLOW`` is ``live-read``
(:data:`WORKFLOW`); no machine outside Actions holds the token.
"""

import base64
import hashlib
import json
import logging
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Protocol

import httpx

from snowlight.live.state import BUDGET_BYTES, StateError, check_packed, pack, unpack
from snowlight.output import write_bytes_atomic

LOG: Final = logging.getLogger(__name__)

DATABASE: Final = "snowlight-live-state"
WORKFLOW: Final = "live-read"
"""The only workflow whose runs may take an epoch or push (``GITHUB_WORKFLOW``)."""
API: Final = "https://api.cloudflare.com/client/v4"
CHUNK_BYTES: Final = 64 * 1024
"""Raw bytes per chunk (87,384 base64 characters, under D1's 100 KB statement)."""
WRITE_BATCH: Final = 8
READ_BATCH: Final = 16
WRITE_CAP: Final = 30_000
"""Rows a UTC day's pushes may write (of the account's 100,000)."""
UPSERT_ROWS: Final = 2
"""What the cap counts a written chunk row as (D1 does not publish how an upsert is billed;
a delete is counted the same)."""
HOLD_ALLOWANCE: Final = 200
"""Rows a day the holds may write past :data:`WRITE_CAP` (the account's own limit is
100,000): a block or a ``Retry-After`` wait is kept at once even on a day the cap stops the
pushes, so a successor on a new runner never asks a blocked source again."""
HOURLY_FROM: Final = 20_000
FIRST_PUSH_SLACK: Final = 1.2
STALE_HEAD: Final = timedelta(hours=2)
"""How old ``head``'s push must be before an unreadable state is replaced by an empty one."""
EPOCH_FILE: Final = "d1.json"
TIMEOUT: Final = httpx.Timeout(30.0, connect=10.0)
RETRY_PAUSE: Final = 5.0

DDL: Final = (
    "CREATE TABLE IF NOT EXISTS chunks (slot TEXT NOT NULL, n INTEGER NOT NULL,"
    " data TEXT NOT NULL, PRIMARY KEY (slot, n)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS head (id INTEGER PRIMARY KEY CHECK (id = 1),"
    " epoch INTEGER NOT NULL, slot TEXT, parts INTEGER, sha256 TEXT, prev_slot TEXT,"
    " prev_parts INTEGER, prev_sha256 TEXT, bytes INTEGER, pushed_at TEXT, run_id TEXT)",
    "CREATE TABLE IF NOT EXISTS budget (day TEXT PRIMARY KEY, rows INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS holds (source_id TEXT PRIMARY KEY, until TEXT NOT NULL,"
    " why TEXT NOT NULL)",
)
_HEAD: Final = (
    "SELECT epoch, slot, parts, sha256, prev_slot, prev_parts, prev_sha256, bytes,"
    " pushed_at, run_id FROM head WHERE id = 1"
)
_CHUNKS: Final = "SELECT n, data FROM chunks WHERE slot = ? AND n >= ? AND n < ? ORDER BY n"
_TAKE: Final = "UPDATE head SET epoch = epoch + 1, run_id = ? WHERE id = 1 AND epoch = ?"
_FIRST: Final = "INSERT INTO head (id, epoch, run_id) VALUES (1, 1, ?)"
_UPSERT: Final = (
    "INSERT INTO chunks (slot, n, data) VALUES (?, ?, ?)"
    " ON CONFLICT (slot, n) DO UPDATE SET data = excluded.data"
)
_SWAP: Final = (
    "UPDATE head SET prev_slot = slot, prev_parts = parts, prev_sha256 = sha256, slot = ?,"
    " parts = ?, sha256 = ?, bytes = ?, pushed_at = ?, run_id = ?"
    " WHERE id = 1 AND epoch = ? AND sha256 IS ?"
)
_BUDGET: Final = "SELECT rows FROM budget WHERE day = ?"
_SPEND: Final = (
    "INSERT INTO budget (day, rows) VALUES (?, ?)"
    " ON CONFLICT (day) DO UPDATE SET rows = rows + excluded.rows"
)
_CLEAN: Final = "DELETE FROM chunks WHERE slot IS NOT ? AND slot IS NOT ?"
_STALE: Final = "SELECT COUNT(*) AS n FROM chunks WHERE slot IS NOT ? AND slot IS NOT ?"
_HOLDS: Final = "SELECT source_id, until, why FROM holds WHERE until > ?"
_HOLD: Final = (
    "INSERT INTO holds (source_id, until, why) VALUES (?, ?, ?)"
    " ON CONFLICT (source_id) DO UPDATE SET until = excluded.until, why = excluded.why"
)
_EXPIRE: Final = "DELETE FROM holds WHERE until <= ?"
STATEMENTS: Final = frozenset(
    {*DDL, _HEAD, _CHUNKS, _TAKE, _FIRST, _UPSERT, _SWAP, _BUDGET, _SPEND, _CLEAN, _HOLDS}
    | {_HOLD, _EXPIRE, _STALE}
)
"""Every statement the store sends; nothing else is ever sent."""

type Value = str | int | float | None
type Statement = tuple[str, tuple[Value, ...]]


class D1Error(StateError):
    """The database could not be reached or answered badly (codes and HTTP status only)."""


class UnreadableStateError(D1Error):
    """``head`` names slots whose bytes fail their sha256 (and it was pushed recently)."""


class LostStateError(D1Error):
    """Another run took the epoch: this run must stop pushing."""


class WriteCapError(D1Error):
    """The push would take the day's rows written past :data:`WRITE_CAP`."""


class WorkflowError(D1Error):
    """Not a live-read run: no epoch is taken and nothing is pushed."""


@dataclass(frozen=True, slots=True)
class Answer:
    """One statement's answer: its rows, and the rows it wrote and changed."""

    rows: tuple[Mapping[str, Any], ...] = ()
    rows_written: int = 0
    changes: int = 0


class D1Api(Protocol):
    """The Cloudflare API's D1 calls (tests use an in-memory SQLite stand-in)."""

    def databases(self, name: str) -> list[tuple[str, str]]:
        """``(name, uuid)`` of the account's databases the list names for ``name``.

        Raises:
            D1Error: the list did not answer HTTP 200 with a list.
        """
        ...

    def create(self, name: str) -> str:
        """Create the database ``name``; its uuid."""
        ...

    def run(self, database: str, statements: Sequence[Statement]) -> list[Answer]:
        """Run ``statements`` in order; one answer each.

        Raises:
            D1Error: any statement failed.
        """
        ...


@dataclass(frozen=True, slots=True)
class Secrets:
    token: str = field(repr=False)
    account: str
    api: str = API

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Secrets":
        """The Cloudflare secrets.

        Raises:
            D1Error: either is missing.
        """
        token = env.get("CLOUDFLARE_API_TOKEN", "")
        account = env.get("CLOUDFLARE_ACCOUNT_ID", "")
        if not token or not account:
            raise D1Error("needs CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID")
        return cls(token=token, account=account, api=env.get("CLOUDFLARE_API_URL") or API)


@dataclass(slots=True)
class CloudflareD1:
    """:class:`D1Api` over the Cloudflare REST API. Statements go 8 to a ``batch`` request;
    when the API refuses the batch form (HTTP 400 on a batch) they go one per request from
    then on."""

    client: httpx.Client
    secrets: Secrets
    pause: float = RETRY_PAUSE
    batch: bool = True
    deadline: float | None = None
    """When (``monotonic``) every request must be over: none starts after it, each one's
    timeout is cut to what is left, and no retry pause runs past it (a hanging API cannot
    stretch a pull or a push beyond its budget)."""
    monotonic: Callable[[], float] = time.monotonic
    lost_rows: int = 0
    """Rows a write may have written with no answer to say so: each try of a writing
    statement that got no answer or a 5xx (it may have run on the server) is counted at its
    floor, so a write sent again is billed for both runs."""

    def _url(self, tail: str) -> str:
        return f"{self.secrets.api}/accounts/{self.secrets.account}/d1/database{tail}"

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.secrets.token}"}

    def databases(self, name: str) -> list[tuple[str, str]]:
        body = self._answer(
            lambda: self.client.get(
                self._url(""), params={"name": name}, headers=self._auth(), timeout=self._timeout()
            ),
            "list databases",
        )
        found = body.get("result")
        if not isinstance(found, list):
            raise D1Error("list databases: no list")
        return [
            (str(item.get("name")), str(item.get("uuid")))
            for item in found
            if isinstance(item, dict) and isinstance(item.get("uuid"), str)
        ]

    def create(self, name: str) -> str:
        body = self._answer(
            lambda: self.client.post(
                self._url(""), json={"name": name}, headers=self._auth(), timeout=self._timeout()
            ),
            "create database",
        )
        result = body.get("result")
        uuid = result.get("uuid") if isinstance(result, dict) else None
        if not isinstance(uuid, str):
            raise D1Error("create database: no id")
        return uuid

    def run(self, database: str, statements: Sequence[Statement]) -> list[Answer]:
        if self.batch and len(statements) > 1:
            try:
                return self._post(
                    database,
                    {"batch": [{"sql": sql, "params": list(params)} for sql, params in statements]},
                    statements,
                )
            except _BatchRefusedError:
                LOG.warning("d1: the batch form was refused; one statement per request")
                self.batch = False
        answers: list[Answer] = []
        for sql, params in statements:
            answers.extend(
                self._post(database, {"sql": sql, "params": list(params)}, [(sql, params)])
            )
        return answers

    def _timeout(self) -> httpx.Timeout:
        """:data:`TIMEOUT`, cut to what is left before :attr:`deadline`."""
        if self.deadline is None:
            return TIMEOUT
        left = max(0.1, self.deadline - self.monotonic())
        return httpx.Timeout(min(30.0, left), connect=min(10.0, left))

    def _post(
        self, database: str, payload: Mapping[str, object], statements: Sequence[Statement]
    ) -> list[Answer]:
        floor = sum(_floor(sql, 1) for sql, _ in statements)
        lost = [0]
        try:
            body = self._answer(
                lambda: self.client.post(
                    self._url(f"/{database}/query"),
                    json=payload,
                    headers=self._auth(),
                    timeout=self._timeout(),
                ),
                "query",
                batch="batch" in payload,
                lost=lost,
            )
        finally:
            self.lost_rows += lost[0] * floor
        results = body.get("result")
        if not isinstance(results, list) or len(results) != len(statements):
            raise D1Error("query: the answer holds another number of results")
        answers = []
        for result, (sql, _) in zip(results, statements, strict=True):
            if not isinstance(result, dict) or result.get("success") is False:
                raise D1Error("query: a statement failed")
            found = result.get("meta")
            meta: Mapping[str, object] = found if isinstance(found, dict) else {}
            rows = result.get("results") or []
            if not isinstance(rows, list):
                raise D1Error("query: no rows")
            changes = _count(meta.get("changes"))
            written = meta.get("rows_written")
            answers.append(
                Answer(
                    rows=tuple(row for row in rows if isinstance(row, dict)),
                    # an answer without the count is billed one row a writing statement at
                    # least, so the write cap never goes blind
                    rows_written=_count(written)
                    if isinstance(written, int)
                    else _floor(sql, changes),
                    changes=changes,
                )
            )
        return answers

    def _answer(
        self,
        request: Callable[[], httpx.Response],
        what: str,
        *,
        batch: bool = False,
        lost: list[int] | None = None,
    ) -> dict[str, Any]:
        """The JSON of a successful answer; no answer or a 5xx is asked again once (each such
        try is counted in ``lost``: it may have run)."""
        response: httpx.Response | None = None
        for attempt in range(2):
            if self.deadline is not None and self.monotonic() >= self.deadline:
                raise D1Error(f"{what}: out of time")
            try:
                response = request()
            except httpx.HTTPError:
                response = None
            if response is not None and response.status_code < 500:  # noqa: PLR2004 - 5xx
                break
            if lost is not None:
                lost[0] += 1
            if attempt == 0:
                if self.deadline is not None and self.monotonic() + self.pause >= self.deadline:
                    break
                time.sleep(self.pause)
        if response is None:
            raise D1Error(f"{what}: the Cloudflare API did not answer")
        if batch and response.status_code == httpx.codes.BAD_REQUEST:
            raise _BatchRefusedError(what)
        try:
            body = response.json()
        except ValueError:
            body = None
        if (
            response.status_code != httpx.codes.OK
            or not isinstance(body, dict)
            or body.get("success") is not True
        ):
            raise D1Error(f"{what}: HTTP {response.status_code}")
        return body


class _BatchRefusedError(D1Error):
    pass


def _count(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _floor(sql: str, changes: int) -> int:
    """The rows a statement is billed when D1's answer gives no ``rows_written``: none for a
    read, else its changes and at least one."""
    return 0 if sql.lstrip().upper().startswith("SELECT") else max(1, changes)


@dataclass(frozen=True, slots=True)
class Head:
    """``head``'s row."""

    epoch: int
    slot: str | None
    parts: int | None
    sha256: str | None
    prev_slot: str | None
    prev_parts: int | None
    prev_sha256: str | None
    bytes: int | None
    pushed_at: datetime | None
    run_id: str | None

    @classmethod
    def of(cls, row: Mapping[str, Any]) -> "Head":
        def text(name: str) -> str | None:
            value = row.get(name)
            return None if value is None else str(value)

        def number(name: str) -> int | None:
            value = row.get(name)
            return None if value is None else int(value)

        pushed = text("pushed_at")
        epoch = number("epoch")
        if epoch is None:
            raise D1Error("head: no epoch")
        return cls(
            epoch=epoch,
            slot=text("slot"),
            parts=number("parts"),
            sha256=text("sha256"),
            prev_slot=text("prev_slot"),
            prev_parts=number("prev_parts"),
            prev_sha256=text("prev_sha256"),
            bytes=number("bytes"),
            pushed_at=None if pushed is None else datetime.fromisoformat(pushed),
            run_id=text("run_id"),
        )


@dataclass(frozen=True, slots=True)
class Pulled:
    """What a pull did: the names restored, the epoch taken, and whether it started empty."""

    names: tuple[str, ...]
    epoch: int
    cold: bool
    """The run starts empty: no ``head`` yet, or an unreadable state over 2 hours old."""
    replaced_unreadable: bool = False
    holds: tuple[tuple[str, datetime, str], ...] = ()
    """The holds kept in the database, still in force: ``(source id, until, why)``."""


@dataclass(frozen=True, slots=True)
class PushResult:
    """What a push did (sizes and counts only)."""

    bytes: int
    parts: int
    rows_written: int
    day_rows: int
    """The UTC day's rows written after this push."""
    hourly: bool
    """Push hourly from now on (the day's writes past :data:`HOURLY_FROM`, or a first push
    that wrote more than planned)."""
    over_plan: bool = False


@dataclass(slots=True)
class D1StateStore:
    """The state folder in D1 (see the module). One per process."""

    api: D1Api
    env: Mapping[str, str]
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    _database: str | None = None
    _unbilled: int = 0
    """Rows written by this process's statements not yet added to ``budget``."""

    # The database -----------------------------------------------------------------------

    def database(self) -> str:
        """The database's id, found by its exact name; created only when the list answered
        and names none."""
        if self._database is not None:
            return self._database
        found = [uuid for name, uuid in self.api.databases(DATABASE) if name == DATABASE]
        if len(found) > 1:
            raise D1Error("the account lists the state database more than once")
        uuid = found[0] if found else self.api.create(DATABASE)
        self._database = uuid
        self._run([(sql, ()) for sql in DDL])
        return uuid

    def _run(self, statements: Sequence[Statement]) -> list[Answer]:
        for sql, _ in statements:
            if sql not in STATEMENTS:  # pragma: no cover - a programming error
                raise D1Error("refused a statement the store does not own")
        database = self._database
        if database is None:  # pragma: no cover - database() sets it first
            raise D1Error("no database")
        lost = getattr(self.api, "lost_rows", 0)
        try:
            answers = self.api.run(database, statements)
        finally:
            # writes that may have run with their answer lost are billed too (the cap never
            # under-counts a statement sent again)
            self._unbilled += max(0, getattr(self.api, "lost_rows", 0) - lost)
        if len(answers) != len(statements):
            raise D1Error("the answer holds another number of results")
        self._unbilled += sum(answer.rows_written for answer in answers)
        return answers

    def _guard(self) -> None:
        if self.env.get("GITHUB_WORKFLOW") != WORKFLOW:
            raise WorkflowError(f"only a {WORKFLOW} run takes the state's epoch or pushes it")

    def head(self) -> Head | None:
        """``head``'s row, or ``None`` when the table holds none (an answer with zero rows).

        Raises:
            D1Error: the database cannot be read.
        """
        self.database()
        rows = self._run([(_HEAD, ())])[0].rows
        if len(rows) > 1:
            raise D1Error("head holds more than one row")
        return Head.of(rows[0]) if rows else None

    def reachable(self) -> bool:
        """Whether ``head`` can be read now (no write)."""
        try:
            self.head()
        except D1Error:
            return False
        return True

    def pullable(self) -> bool:
        """Whether a pull would succeed now, read only (no epoch is taken): ``head`` reads,
        and there is none yet, or its slot or the previous one matches its sha256, or it was
        pushed over :data:`STALE_HEAD` ago (the pull then starts empty). An overrides-only run
        ends only then, so a readable database whose slots fail their sha256 does not start a
        successor that fails the same way every few minutes."""
        try:
            head = self.head()
            if head is None or head.slot is None:
                return True
            if self._slot(head.slot, head.parts, head.sha256) is not None:
                return True
            if self._slot(head.prev_slot, head.prev_parts, head.prev_sha256) is not None:
                return True
        except (D1Error, ValueError):
            return False
        return head.pushed_at is not None and self.clock() - head.pushed_at > STALE_HEAD

    def limit(self, seconds: float) -> None:
        """Every request of this store from now on ends within ``seconds`` (an API that
        hangs cannot stretch a pull or a probe past it)."""
        if hasattr(self.api, "deadline") and hasattr(self.api, "monotonic"):
            self.api.deadline = self.api.monotonic() + seconds

    # Pull -------------------------------------------------------------------------------

    def _slot(self, slot: str | None, parts: int | None, sha: str | None) -> bytes | None:
        """The bytes of ``slot`` when they match ``sha`` and their ledger passes ``PRAGMA
        quick_check`` (:func:`~snowlight.live.state.check_packed`), else ``None``."""
        if slot is None or parts is None or sha is None or parts <= 0:
            return None
        texts: list[str] = []
        for start in range(0, parts, READ_BATCH):
            rows = self._run([(_CHUNKS, (slot, start, min(start + READ_BATCH, parts)))])[0].rows
            if [int(row.get("n", -1)) for row in rows] != list(
                range(start, min(start + READ_BATCH, parts))
            ):
                return None
            texts.extend(str(row.get("data", "")) for row in rows)
        try:
            data = b"".join(base64.b64decode(text, validate=True) for text in texts)
        except ValueError:
            return None
        if hashlib.sha256(data).hexdigest() != sha:
            return None
        try:
            check_packed(data)  # a sound sha256 over a damaged ledger is a failed slot too
        except StateError:
            LOG.warning("d1: slot %s holds a state that fails its integrity check", slot)
            return None
        return data

    def pull(self, folder: Path) -> list[str]:
        """:class:`~snowlight.live.state.StateStore`'s pull: see :meth:`take`."""
        return list(self.take(folder).names)

    def take(self, folder: Path) -> Pulled:
        """Restore the state into ``folder`` and take the epoch (see the module).

        Raises:
            WorkflowError: not a live-read run.
            UnreadableStateError: both slots fail their sha256, and ``head`` is recent.
            D1Error: the database cannot be read, or another run took the epoch first.
        """
        self._guard()
        run_id = self.env.get("GITHUB_RUN_ID") or None
        head = self.head()
        now = self.clock()
        if head is None:
            try:
                made = self._run([(_FIRST, (run_id,))])[0].changes == 1
            except D1Error:
                made = False  # an answer lost after the insert ran: head says whose it is
            if not made and not self._took(1, run_id):
                raise D1Error("head appeared while it was being made")
            self._write_epoch(folder, 1, None)
            holds = self._holds(now)
            self._bill(now)
            return Pulled((), 1, cold=True, holds=holds)
        data = self._slot(head.slot, head.parts, head.sha256)
        if data is None and head.slot is not None:
            LOG.warning("d1: the current slot fails its checks; reading the previous one")
            data = self._slot(head.prev_slot, head.prev_parts, head.prev_sha256)
        unreadable = data is None and head.slot is not None
        if unreadable and (head.pushed_at is None or now - head.pushed_at <= STALE_HEAD):
            raise UnreadableStateError("both slots fail their sha256")
        answer = self._run([(_TAKE, (run_id, head.epoch))])[0]
        # no row changed: the answer of an update that ran may have been lost and the update
        # sent again; head then holds the next epoch under this run's id
        if answer.changes != 1 and not self._took(head.epoch + 1, run_id):
            raise D1Error("another run took the epoch first")
        epoch = head.epoch + 1
        names = () if data is None else tuple(unpack(data, folder))
        self._write_epoch(folder, epoch, head.sha256)
        holds = self._holds(now)
        self._bill(now)
        return Pulled(names, epoch, cold=data is None, replaced_unreadable=unreadable, holds=holds)

    def _took(self, epoch: int, run_id: str | None) -> bool:
        """Whether ``head`` holds ``epoch`` under this run (``run_id``)."""
        if run_id is None:
            return False
        head = self.head()
        return head is not None and head.epoch == epoch and head.run_id == run_id

    def _bill(self, now: datetime) -> None:
        """Add this process's unbilled writes to the day's ``budget`` now (the pull is a
        process of its own; nothing it wrote is left out of the cap)."""
        if self._unbilled <= 0:
            return
        day = now.astimezone(UTC).date().isoformat()
        try:
            self._run([(_SPEND, (day, self._unbilled + 1))])
        except D1Error as error:
            LOG.warning("d1: the pull's writes were not billed: %s", error)
            return
        self._unbilled = 0

    def _holds(self, now: datetime) -> tuple[tuple[str, datetime, str], ...]:
        moment = now.astimezone(UTC).isoformat()
        rows = self._run([(_EXPIRE, (moment,)), (_HOLDS, (moment,))])[1].rows
        found = []
        for row in rows:
            try:
                found.append(
                    (
                        str(row["source_id"]),
                        datetime.fromisoformat(str(row["until"])),
                        str(row["why"]),
                    )
                )
            except (KeyError, ValueError):
                continue
        return tuple(found)

    @staticmethod
    def _write_epoch(folder: Path, epoch: int, sha: str | None) -> None:
        document = {"epoch": epoch, "pulled_sha256": sha, "pushes": 0}
        write_bytes_atomic(folder / EPOCH_FILE, (json.dumps(document) + "\n").encode())

    @staticmethod
    def epoch_of(folder: Path) -> dict[str, Any]:
        """``d1.json`` of ``folder``.

        Raises:
            D1Error: there is none (no good pull in this run) or it does not read.
        """
        try:
            document = json.loads((folder / EPOCH_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise D1Error("no epoch: the state was not pulled in this run") from error
        if not isinstance(document, dict) or not isinstance(document.get("epoch"), int):
            raise D1Error("d1.json does not read")
        return document

    # Push -------------------------------------------------------------------------------

    def push(self, folder: Path) -> int:
        """:class:`~snowlight.live.state.StateStore`'s push: see :meth:`keep`."""
        return self.keep(folder).bytes

    def keep(self, folder: Path, *, deadline: datetime | None = None) -> PushResult:
        """Keep ``folder``'s state under this run's epoch (see the module). The whole push,
        each request included, ends by ``deadline``: past it the push stops, ``head`` still
        names the last good push, and the next slot tries again.

        Raises:
            WorkflowError: not a live-read run.
            LostStateError: another run took the epoch, or ``head`` moved under this push.
            WriteCapError: the day's writes would pass the cap.
            D1Error: the database cannot be read or written, or the state is over budget.
        """
        api: Any = self.api
        previous = getattr(api, "deadline", None)
        if deadline is not None and hasattr(api, "deadline") and hasattr(api, "monotonic"):
            left = max(0.0, (deadline - self.clock()).total_seconds())
            budget = api.monotonic() + left
            api.deadline = budget if previous is None else min(previous, budget)
        try:
            return self._keep(folder, deadline)
        finally:
            if hasattr(api, "deadline"):
                api.deadline = previous

    def _keep(self, folder: Path, deadline: datetime | None) -> PushResult:
        self._guard()
        mine = self.epoch_of(folder)
        epoch = int(mine["epoch"])
        data = pack(folder)
        if len(data) > BUDGET_BYTES:
            raise D1Error(f"the packed state is {len(data)} bytes, over the budget")
        raw = [data[start : start + CHUNK_BYTES] for start in range(0, len(data), CHUNK_BYTES)]
        parts = max(1, len(raw))
        plan = parts + 2
        now = self.clock()
        day = now.astimezone(UTC).date().isoformat()
        self.database()
        rows = self._run([(_BUDGET, (day,))])[0].rows
        spent = int(rows[0].get("rows", 0)) if rows else 0
        # an upsert may be billed two rows (D1 does not say): the cap counts it so
        if spent + self._unbilled + UPSERT_ROWS * parts + 2 > WRITE_CAP:
            raise WriteCapError(f"the day's writes would pass {WRITE_CAP} rows")
        head = self.head()
        if head is None or head.epoch != epoch:
            raise LostStateError("another run holds the state's epoch")
        slot = f"e{epoch}a" if head.slot != f"e{epoch}a" else f"e{epoch}b"
        before = self._unbilled
        texts = [base64.b64encode(chunk).decode("ascii") for chunk in raw] or [""]
        for start in range(0, len(texts), WRITE_BATCH):
            if deadline is not None and self.clock() >= deadline:
                raise D1Error("the push ran out of time before its slot was written")
            self._run(
                [
                    (_UPSERT, (slot, start + index, text))
                    for index, text in enumerate(texts[start : start + WRITE_BATCH])
                ]
            )
        sha = hashlib.sha256(data).hexdigest()
        moment = self.clock().astimezone(UTC).isoformat()
        run_id = self.env.get("GITHUB_RUN_ID") or None
        swap = self._run(
            [(_SWAP, (slot, parts, sha, len(data), moment, run_id, epoch, head.sha256))]
        )[0]
        if swap.changes != 1 and not self._swapped(epoch, slot, sha):
            raise LostStateError("head moved under the push")
        pushes = int(mine.get("pushes", 0)) + 1
        if pushes >= 2 and not mine.get("cleaned"):  # noqa: PLR2004 - this epoch's second push
            mine["cleaned"] = self._clean(slot, head.slot, spent)
        written = self._unbilled - before
        over = pushes == 1 and written > FIRST_PUSH_SLACK * plan
        billed = self._unbilled + 1  # the budget's own upsert
        self._run([(_SPEND, (day, billed))])
        self._unbilled = 0
        total = spent + billed
        mine.update(
            pushes=pushes,
            pushed_sha256=sha,
            hourly=bool(mine.get("hourly")) or over,
            bytes=len(data),
            day_rows=total,
        )
        write_bytes_atomic(folder / EPOCH_FILE, (json.dumps(mine) + "\n").encode())
        return PushResult(
            bytes=len(data),
            parts=parts,
            rows_written=written,
            day_rows=total,
            hourly=bool(mine["hourly"]) or total > HOURLY_FROM,
            over_plan=over,
        )

    def _clean(self, slot: str, named: str | None, spent: int) -> bool:
        """Delete the chunks of slots ``head`` names no more (older epochs'), counted first,
        and only when their delete (billed at most :data:`UPSERT_ROWS` a row) stays under the
        cap; otherwise they wait for a later push (nothing reads them). ``True`` once none
        is left."""
        found = self._run([(_STALE, (slot, named))])[0].rows
        stale = int(found[0].get("n", 0)) if found else 0
        if stale <= 0:
            return True
        if spent + self._unbilled + UPSERT_ROWS * stale + 1 > WRITE_CAP:
            LOG.warning("d1: %d old chunks wait for a later push (the day's write cap)", stale)
            return False
        self._run([(_CLEAN, (slot, named))])
        return True

    def _swapped(self, epoch: int, slot: str, sha: str) -> bool:
        """Whether ``head`` already names this push (a swap that ran, whose answer was lost
        and which was sent again, changes no row)."""
        head = self.head()
        return head is not None and head.epoch == epoch and head.slot == slot and head.sha256 == sha

    def put_holds(self, holds: Sequence[tuple[str, datetime, str]]) -> None:
        """Keep blocks and waits at once (codes and times only), so a new runner never asks
        a blocked source again after a crash; billed to the day's ``budget`` at once. The
        holds have their own :data:`HOLD_ALLOWANCE` past the write cap, so a day the cap
        stops the pushes still keeps a new block.

        Raises:
            WorkflowError: not a live-read run.
            WriteCapError: the day's writes would pass the cap and the allowance.
            D1Error: the database cannot be written.
        """
        if not holds:
            return
        self._guard()
        self.database()
        day = self.clock().astimezone(UTC).date().isoformat()
        rows = self._run([(_BUDGET, (day,))])[0].rows
        spent = int(rows[0].get("rows", 0)) if rows else 0
        if spent + self._unbilled + len(holds) + 1 > WRITE_CAP + HOLD_ALLOWANCE:
            raise WriteCapError(f"the day's writes would pass {WRITE_CAP + HOLD_ALLOWANCE} rows")
        before = self._unbilled
        self._run(
            [
                (_HOLD, (source, until.astimezone(UTC).isoformat(), why))
                for source, until, why in holds
            ]
        )
        self._run([(_SPEND, (day, self._unbilled - before + 1))])
        self._unbilled = before


def make_store(env: Mapping[str, str], client: httpx.Client) -> D1StateStore:
    """The store over the Cloudflare API with the environment's secrets.

    Raises:
        D1Error: the secrets are missing.
    """
    return D1StateStore(CloudflareD1(client, Secrets.from_env(env)), env)


def plan_parts(size: int) -> int:
    """How many chunks a packed state of ``size`` bytes takes."""
    return max(1, math.ceil(size / CHUNK_BYTES))

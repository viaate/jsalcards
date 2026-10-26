"""The posts' private state in the D1 database ``snowlight-live-state``.

Reached over the Cloudflare API with the repository secrets ``CLOUDFLARE_API_TOKEN`` and
``CLOUDFLARE_ACCOUNT_ID``. The database is found by its exact name and never created here
(the live reader owns it); this module adds only its own two tables, ``social_token`` and
``social_posts``, runs only its own fixed statements with every value bound as a parameter,
and never logs an answer's body: an error names the HTTP status only.

**The token chain** (``social_token``, one row, ``id = 1``): ``version`` counts the stored
refresh tokens, ``sealed`` holds the newest (:mod:`snowlight.social.seal`), ``seed`` the
fingerprint of the ``X_REFRESH_TOKEN`` secret the chain started from, and ``lease`` /
``lease_until`` the run that may spend it. A run first takes the lease with
``UPDATE ... WHERE version = <read> AND (lease IS NULL OR lease_until < <now>)``; only the
run holding it refreshes, and it stores the rotated token with
``UPDATE ... SET version = version + 1 ... WHERE version = <read> AND lease = <run>``, so two
runs can never both spend one refresh token or overwrite each other's. The first run inserts
the row at version 0 with its lease (an insert fails when a row appeared meanwhile).

**The posts** (``social_posts``): one row a slot (``queue:<id>`` or ``haiku:<UTC day>``),
claimed before anything is sent with one ``INSERT ... SELECT ... WHERE`` that also enforces
the day's cap, so a slot is posted at most once and a day never holds more than
:data:`MAX_POSTS_PER_DAY` posts. ``state`` is ``claimed``, then ``posted`` (with the post id)
or ``uncertain`` (X may have posted it: never sent again). A post X refused is deleted, so a
later run may try it again.
"""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import httpx

API: Final = "https://api.cloudflare.com/client/v4"
DATABASE: Final = "snowlight-live-state"
TIMEOUT: Final = httpx.Timeout(30.0, connect=10.0)
RETRY_PAUSE: Final = 3.0
LEASE: Final = timedelta(minutes=10)
"""How long a run may hold the token chain (the job's timeout is 15 minutes)."""
MAX_POSTS_PER_DAY: Final = 2
"""Posts of every kind in one UTC day, claimed or posted."""
STORE_TRIES: Final = 3

TABLES: Final = (
    "CREATE TABLE IF NOT EXISTS social_token (id INTEGER PRIMARY KEY CHECK (id = 1),"
    " version INTEGER NOT NULL, sealed TEXT NOT NULL, seed TEXT NOT NULL, lease TEXT,"
    " lease_until TEXT, updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS social_posts (slot TEXT PRIMARY KEY, kind TEXT NOT NULL,"
    " style TEXT NOT NULL, day TEXT NOT NULL, state TEXT NOT NULL, image TEXT NOT NULL,"
    " post_id TEXT, claimed_at TEXT NOT NULL, posted_at TEXT, run TEXT NOT NULL)",
)

type Value = str | int | None
type Row = dict[str, Any]


class StoreError(RuntimeError):
    """The database could not be read or written (the message names only the HTTP status)."""


class MissingDatabaseError(StoreError):
    """The Cloudflare account has no database ``snowlight-live-state``."""


class ChainBusyError(StoreError):
    """Another run holds the token chain, or changed it since it was read."""


@dataclass(frozen=True, slots=True)
class CloudflareSecrets:
    token: str = field(repr=False)
    account: str = field(repr=False)
    api: str = API

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "CloudflareSecrets | None":
        token = env.get("CLOUDFLARE_API_TOKEN", "")
        account = env.get("CLOUDFLARE_ACCOUNT_ID", "")
        if not token or not account:
            return None
        return cls(token=token, account=account, api=env.get("CLOUDFLARE_API_URL") or API)


@dataclass(frozen=True, slots=True)
class Answer:
    rows: tuple[Row, ...]
    changes: int


class D1:
    """One database, by id; one statement a request."""

    def __init__(
        self,
        client: httpx.Client,
        secrets: CloudflareSecrets,
        database: str,
        *,
        pause: float = RETRY_PAUSE,
    ) -> None:
        self._client = client
        self._secrets = secrets
        self._database = database
        self._pause = pause

    @classmethod
    def find(
        cls, client: httpx.Client, secrets: CloudflareSecrets, *, pause: float = RETRY_PAUSE
    ) -> "D1":
        """The database ``snowlight-live-state``, by its exact name.

        Raises:
            MissingDatabaseError: the account lists no such database.
            StoreError: the list could not be read.
        """
        url = f"{secrets.api}/accounts/{secrets.account}/d1/database"
        body = _answer(
            lambda: client.get(
                url, params={"name": DATABASE}, headers=_auth(secrets), timeout=TIMEOUT
            ),
            pause,
            retry=True,
        )
        found = [
            item
            for item in body.get("result") or []
            if isinstance(item, dict)
            and item.get("name") == DATABASE
            and isinstance(item.get("uuid"), str)
        ]
        if not found:
            raise MissingDatabaseError(f"the Cloudflare account has no database {DATABASE}")
        return cls(client, secrets, str(found[0]["uuid"]), pause=pause)

    def run(self, sql: str, params: Sequence[Value] = (), *, retry: bool = True) -> Answer:
        """One statement's rows and changed-row count.

        ``retry`` asks again once after no answer or a 5xx: only for reads and for writes
        whose second sending changes nothing the first did not.
        """
        url = (
            f"{self._secrets.api}/accounts/{self._secrets.account}"
            f"/d1/database/{self._database}/query"
        )
        body = _answer(
            lambda: self._client.post(
                url,
                json={"sql": sql, "params": list(params)},
                headers=_auth(self._secrets),
                timeout=TIMEOUT,
            ),
            self._pause,
            retry=retry,
        )
        results = body.get("result")
        if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
            raise StoreError("the D1 answer holds no result")
        result = results[0]
        if result.get("success") is False:
            raise StoreError("a D1 statement failed")
        rows = result.get("results") or []
        meta = result.get("meta")
        changes = meta.get("changes") if isinstance(meta, dict) else None
        if not isinstance(rows, list):
            raise StoreError("the D1 answer holds no rows")
        return Answer(
            rows=tuple(row for row in rows if isinstance(row, dict)),
            changes=changes if isinstance(changes, int) else 0,
        )


def _auth(secrets: CloudflareSecrets) -> dict[str, str]:
    return {"Authorization": f"Bearer {secrets.token}"}


def _answer(request: Callable[[], httpx.Response], pause: float, *, retry: bool) -> dict[str, Any]:
    """The JSON of a successful answer (the error names the HTTP status only)."""
    response: httpx.Response | None = None
    for attempt in range(2 if retry else 1):
        try:
            response = request()
        except httpx.HTTPError:
            response = None
        if response is not None and response.status_code < 500:  # noqa: PLR2004 - HTTP 5xx
            break
        if retry and attempt == 0:
            time.sleep(pause)
    if response is None:
        raise StoreError("the Cloudflare API did not answer")
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise StoreError(f"the Cloudflare API answered HTTP {response.status_code} without JSON")
    if response.status_code != httpx.codes.OK or body.get("success") is not True:
        raise StoreError(f"the Cloudflare API answered HTTP {response.status_code}")
    return body


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class Chain:
    """The token row as read (``version`` 0 and ``sealed`` empty before the first store)."""

    version: int
    sealed: str = field(repr=False)
    seed: str = field(repr=False)


class Store:
    """The social tables of one database."""

    def __init__(self, db: D1) -> None:
        self.db = db

    def prepare(self) -> None:
        """Make the two tables when they are not there yet."""
        for sql in TABLES:
            self.db.run(sql)

    # -- the token chain ---------------------------------------------------------------

    def take_chain(self, run: str, now: datetime) -> Chain:
        """Lease the token chain to this run.

        Raises:
            ChainBusyError: another run holds it, or took it first.
            StoreError: the database could not be read or written.
        """
        until = _iso(now + LEASE)
        rows = self.db.run(
            "SELECT version, sealed, seed, lease, lease_until FROM social_token WHERE id = 1"
        ).rows
        if not rows:
            made = self.db.run(
                "INSERT INTO social_token (id, version, sealed, seed, lease, lease_until,"
                " updated_at) VALUES (1, 0, '', '', ?, ?, ?)",
                (run, until, _iso(now)),
                retry=False,
            )
            if made.changes != 1:
                raise ChainBusyError("another run started the token chain first")
            return Chain(version=0, sealed="", seed="")
        row = rows[0]
        version = row.get("version")
        if not isinstance(version, int):
            raise StoreError("the token row has no version")
        taken = self.db.run(
            "UPDATE social_token SET lease = ?, lease_until = ? WHERE id = 1 AND version = ?"
            " AND (lease IS NULL OR lease = ? OR lease_until < ?)",
            (run, until, version, run, _iso(now)),
        )
        if taken.changes != 1:
            raise ChainBusyError("another run holds the token chain")
        return Chain(
            version=version, sealed=str(row.get("sealed") or ""), seed=str(row.get("seed") or "")
        )

    def store_chain(self, chain: Chain, run: str, sealed: str, seed: str, now: datetime) -> int:
        """Store the rotated token as version ``chain.version + 1``; the new version.

        Asked up to :data:`STORE_TRIES` times: after an error the row is read back, and a row
        already holding this run's seal at the new version counts as stored.

        Raises:
            ChainBusyError: the row changed under this run (it no longer holds the lease).
            StoreError: the token could not be stored.
        """
        new = chain.version + 1
        for attempt in range(STORE_TRIES):
            try:
                swapped = self.db.run(
                    "UPDATE social_token SET version = ?, sealed = ?, seed = ?, lease = NULL,"
                    " lease_until = NULL, updated_at = ? WHERE id = 1 AND version = ?"
                    " AND lease = ?",
                    (new, sealed, seed, _iso(now), chain.version, run),
                    retry=False,
                )
                if swapped.changes == 1:
                    return new
            except StoreError:
                if attempt == STORE_TRIES - 1:
                    raise
            rows = self._token_row()
            if rows is not None and rows.get("version") == new and rows.get("sealed") == sealed:
                return new
            if rows is not None and (
                rows.get("version") != chain.version or rows.get("lease") != run
            ):
                raise ChainBusyError("the token row changed under this run")
        raise StoreError("the rotated token could not be stored")

    def release_chain(self, run: str) -> None:
        """Give the lease back without storing (nothing was spent, or X refused the token)."""
        self.db.run(
            "UPDATE social_token SET lease = NULL, lease_until = NULL WHERE id = 1 AND lease = ?",
            (run,),
        )

    def _token_row(self) -> Row | None:
        try:
            rows = self.db.run("SELECT version, sealed, lease FROM social_token WHERE id = 1").rows
        except StoreError:
            return None
        return rows[0] if rows else None

    # -- the posts ---------------------------------------------------------------------

    def taken_slots(self) -> set[str]:
        """Every slot claimed, posted or uncertain."""
        return {str(row["slot"]) for row in self.db.run("SELECT slot FROM social_posts").rows}

    def posts_on(self, day: str) -> int:
        rows = self.db.run("SELECT COUNT(*) AS n FROM social_posts WHERE day = ?", (day,)).rows
        n = rows[0].get("n") if rows else 0
        return n if isinstance(n, int) else 0

    def last_post(self) -> Row | None:
        """The newest claimed row (any state), or ``None``."""
        rows = self.db.run(
            "SELECT slot, kind, style, claimed_at, posted_at FROM social_posts"
            " ORDER BY claimed_at DESC LIMIT 1"
        ).rows
        return rows[0] if rows else None

    def claim(  # noqa: PLR0913 - one row's columns
        self, slot: str, *, kind: str, style: str, image: str, run: str, now: datetime
    ) -> bool:
        """Claim a slot before sending it: false when it is taken or the day is full."""
        day = now.date().isoformat()
        made = self.db.run(
            "INSERT INTO social_posts (slot, kind, style, day, state, image, claimed_at, run)"
            " SELECT ?, ?, ?, ?, 'claimed', ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM"
            " social_posts WHERE slot = ?) AND (SELECT COUNT(*) FROM social_posts WHERE"
            " day = ?) < ?",
            (slot, kind, style, day, image, _iso(now), run, slot, day, MAX_POSTS_PER_DAY),
            retry=False,
        )
        return made.changes == 1

    def posted(self, slot: str, run: str, post_id: str, now: datetime) -> None:
        self.db.run(
            "UPDATE social_posts SET state = 'posted', post_id = ?, posted_at = ?"
            " WHERE slot = ? AND run = ?",
            (post_id, _iso(now), slot, run),
        )

    def uncertain(self, slot: str, run: str) -> None:
        self.db.run(
            "UPDATE social_posts SET state = 'uncertain' WHERE slot = ? AND run = ?",
            (slot, run),
        )

    def release(self, slot: str, run: str) -> None:
        """Drop this run's claim on a slot nothing was posted for."""
        self.db.run(
            "DELETE FROM social_posts WHERE slot = ? AND run = ? AND state = 'claimed'",
            (slot, run),
        )

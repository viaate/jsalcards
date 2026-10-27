"""The posts' private state in the D1 database ``snowlight-live-state``.

Reached over the Cloudflare API with the repository secrets ``CLOUDFLARE_API_TOKEN`` and
``CLOUDFLARE_ACCOUNT_ID``. The database is found by its exact name and never created here
(the live reader owns it); this module adds only its own tables (``social_token``,
``social_posts``, ``social_haiku_days``, ``social_refusals`` and ``social_marks``), runs only
its own fixed statements with every value bound as a parameter, and never logs an answer's
body: an error names the HTTP status only.

**The token chain** (``social_token``, one row, ``id = 1``): ``version`` counts the stored
refresh tokens, ``sealed`` holds the newest (:mod:`snowlight.social.seal`), ``seed`` the
fingerprint of the ``X_REFRESH_TOKEN`` secret the chain started from, and ``lease`` /
``lease_until`` the run that may spend it. A run first takes the lease with
``UPDATE ... WHERE version = <read> AND (lease IS NULL OR lease_until < <now>)``; only the
run holding it refreshes, and it stores the rotated token with
``UPDATE ... SET version = version + 1 ... WHERE version = <read> AND lease = <run>``, so two
runs can never both spend one refresh token or overwrite each other's. The first run inserts
the row at version 0 with its lease (an insert fails when a row appeared meanwhile).
``refused`` holds the fingerprint of the secret whose chain stopped (X refused it, the stored
token did not open or could not be stored, or a scope is missing) until a refresh works again:
while it is the current secret's fingerprint, every run stops before it picks a post, so no
run calls Haiku, claims a slot or sends that token to X again. A run whose secret's
fingerprint differs (the owner pasted a new one) refreshes from the new secret, so the new
token is checked and the owner's issue closes; a refused one is never tried again by itself.
``held`` holds the fingerprint of the secret in use when X refused a post or an image upload
for good (HTTP 401, 402 or 403: no credits, no write permission, a duplicate), with the owner's
issue (``held_issue``) and X's answer (``held_why``): every run stops before it picks a post
until the owner closes that issue or pastes a new secret. A hold whose issue could not be
opened stays, and each run tries to open it, so it is never lifted as "closed" by an issue
that never was. ``unknown`` holds when a refresh got no answer (X may have spent the token
then), so a later refusal of that token says so; a stored rotation clears it.

**The Haiku tries** (``social_haiku_days``): one row a try Haiku was asked to write, named
``<UTC day>#<n>``, made before the first call with an ``INSERT ... WHERE NOT EXISTS``, so a
try is at most four calls whatever happens to it (both drafts failed a check, X refused the
post, the run stopped), and a day holds at most
:data:`snowlight.social.post.MAX_HAIKU_PER_DAY` tries (:meth:`Store.haiku_tries`).

**The posts** (``social_posts``): one row a slot (``queue:<id>`` or
``haiku:<UTC day>#<n>``),
claimed before anything is sent with one ``INSERT ... SELECT ... WHERE`` that also enforces
the day's cap, so a slot is posted at most once and a day never holds more than
:data:`MAX_POSTS_PER_DAY` posts. ``state`` is ``claimed``, then ``posted`` (with the post id)
or ``uncertain`` (X may have posted it: never sent again). A post X refused is deleted, so a
later run may try it again, except that :data:`REFUSALS_TO_SKIP` refusals in a row with the
same 4xx (not 429, not one that holds posting; counted in ``social_refusals``) keep it as
``skipped``: never sent again and counted toward no cap, with the owner's issue. A
``claimed`` row older than :data:`STALE_CLAIM` belongs to a run that stopped mid-send: it may
or may not be posted, so it is never sent again by itself, and every run warns about it until
the owner deletes the row (docs/social.md).

**The marks** (``social_marks``): one row a slot, written just before its claim, with a short
mark of the post's words (:func:`snowlight.social.post.draft_mark`), queued or Haiku: a
posted queue file is removed, so this is what lets a Haiku draft be held against every recent
post (X refuses a duplicate with a 403, which holds all posting). A mark counts only while its
slot is in ``social_posts`` (a claim dropped before X got the post is gone, and its mark with
it).

Nothing else records what was posted: the ``social_posts`` table must never be dropped, and
a posted queue file is removed from ``social/queue`` (docs/social.md).
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
"""How long a run may hold the token chain: taken in the Post step just before the refresh
(timed from that moment) and given back when the rotated token is stored, well under a minute
later (one refresh call of at most 30 seconds). A run never starts a refresh past
:data:`snowlight.social.post.REFRESH_BY` into the Post step, whose own timeout is 10 minutes,
and the job's concurrency group runs one post job at a time."""
STALE_CLAIM: Final = timedelta(minutes=30)
"""A claim older than this belongs to a run that stopped mid-send (the Post step's timeout is
10 minutes)."""
MAX_POSTS_PER_DAY: Final = 3
"""Posts of every kind in one UTC day, claimed or posted."""
STORE_TRIES: Final = 3

TABLES: Final = (
    "CREATE TABLE IF NOT EXISTS social_token (id INTEGER PRIMARY KEY CHECK (id = 1),"
    " version INTEGER NOT NULL, sealed TEXT NOT NULL, seed TEXT NOT NULL, lease TEXT,"
    " lease_until TEXT, refused TEXT, held TEXT, held_issue INTEGER, held_why TEXT,"
    " unknown TEXT, updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS social_posts (slot TEXT PRIMARY KEY, kind TEXT NOT NULL,"
    " style TEXT NOT NULL, day TEXT NOT NULL, state TEXT NOT NULL, image TEXT NOT NULL,"
    " post_id TEXT, claimed_at TEXT NOT NULL, posted_at TEXT, run TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS social_haiku_days (day TEXT PRIMARY KEY, state TEXT NOT NULL,"
    " run TEXT NOT NULL, at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS social_refusals (slot TEXT PRIMARY KEY, count INTEGER NOT NULL,"
    " status INTEGER NOT NULL, at TEXT NOT NULL, run TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS social_marks (slot TEXT PRIMARY KEY, mark TEXT NOT NULL,"
    " at TEXT NOT NULL)",
)
REFUSALS_TO_SKIP: Final = 2
"""How many times X may refuse one slot with the same kind of answer (a 4xx other than 429
and :data:`snowlight.social.xapi.FOR_GOOD`) before the slot is skipped for good."""

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
    """The Cloudflare API token and account. The token only ever goes to :data:`API`: no
    setting, in the environment or anywhere else, sends it to another host."""

    token: str = field(repr=False)
    account: str = field(repr=False)

    @property
    def api(self) -> str:
        return API

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "CloudflareSecrets | None":
        token = env.get("CLOUDFLARE_API_TOKEN", "")
        account = env.get("CLOUDFLARE_ACCOUNT_ID", "")
        if not token or not account:
            return None
        return cls(token=token, account=account)


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

    @property
    def pause(self) -> float:
        """The pause before a second asking."""
        return self._pause

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
    unknown: str | None = None
    """When a refresh from this token got no answer (X may have spent it), or ``None``."""


@dataclass(frozen=True, slots=True)
class Held:
    """Posting held since X refused a post for good: the secret's fingerprint then, the
    owner's issue (``None`` when it could not be opened) and X's answer (status and code)."""

    seed: str
    issue: int | None
    why: str


class Store:
    """The social tables of one database."""

    def __init__(self, db: D1) -> None:
        self.db = db

    def prepare(self) -> None:
        """Make the social tables when they are not there yet."""
        for sql in TABLES:
            self.db.run(sql)

    # -- the token chain ---------------------------------------------------------------

    def take_chain(self, run: str, now: datetime, seed: str) -> Chain:
        """Lease the token chain to this run. A new row starts from ``seed``, the fingerprint
        of the secret this run refreshes from (so a stop on that secret can be told apart
        from a newer one, :meth:`chain_seed`).

        Raises:
            ChainBusyError: another run holds it, or took it first.
            StoreError: the database could not be read or written.
        """
        until = _iso(now + LEASE)
        rows = self.db.run(
            "SELECT version, sealed, seed, lease, lease_until, unknown FROM social_token"
            " WHERE id = 1"
        ).rows
        if not rows:
            made = self.db.run(
                "INSERT INTO social_token (id, version, sealed, seed, lease, lease_until,"
                " updated_at) VALUES (1, 0, '', ?, ?, ?, ?)",
                (seed, run, until, _iso(now)),
                retry=False,
            )
            if made.changes != 1:
                raise ChainBusyError("another run started the token chain first")
            return Chain(version=0, sealed="", seed=seed)
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
        unknown = row.get("unknown")
        return Chain(
            version=version,
            sealed=str(row.get("sealed") or ""),
            seed=str(row.get("seed") or ""),
            unknown=unknown if isinstance(unknown, str) and unknown else None,
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
                    " lease_until = NULL, refused = NULL, unknown = NULL, updated_at = ?"
                    " WHERE id = 1"
                    " AND version = ?"
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

    def stopped(self, seed: str) -> None:
        """Record that the chain started from ``seed`` (a fingerprint) stopped."""
        self.db.run("UPDATE social_token SET refused = ? WHERE id = 1", (seed,))

    def refresh_unknown(self, run: str, now: datetime) -> None:
        """Record that this run's refresh got no answer: X may have spent the stored token
        (a later refusal of it then most likely has that cause). Also gives the lease back."""
        self.db.run(
            "UPDATE social_token SET unknown = ?, lease = NULL, lease_until = NULL WHERE id = 1"
            " AND lease = ?",
            (_iso(now), run),
        )

    def chain_seed(self) -> tuple[int, str] | None:
        """The stored chain's version and the fingerprint of the secret it started from, or
        ``None`` before the first run."""
        rows = self.db.run("SELECT version, seed FROM social_token WHERE id = 1").rows
        if not rows or not isinstance(rows[0].get("version"), int):
            return None
        return int(rows[0]["version"]), str(rows[0].get("seed") or "")

    def working(self) -> None:
        """Record that the chain works again (a refresh worked with every scope)."""
        self.db.run("UPDATE social_token SET refused = NULL WHERE id = 1")

    def hold(self, seed: str, issue: int | None, why: str) -> None:
        """Record that X refused a post for good while ``seed`` (a fingerprint) was in use,
        with the owner's issue (``None``: it could not be opened) and X's answer."""
        self.db.run(
            "UPDATE social_token SET held = ?, held_issue = ?, held_why = ? WHERE id = 1",
            (seed, issue, why),
        )

    def held_issue(self, issue: int) -> None:
        """Record the owner's issue of a hold whose issue could not be opened before."""
        self.db.run("UPDATE social_token SET held_issue = ? WHERE id = 1", (issue,))

    def unhold(self) -> None:
        """Record that posting may be tried again (the owner closed the issue, or a new
        secret is in place)."""
        self.db.run(
            "UPDATE social_token SET held = NULL, held_issue = NULL, held_why = NULL WHERE id = 1"
        )

    def held(self) -> Held | None:
        """The hold on posting since X refused a post for good, or ``None``."""
        rows = self.db.run("SELECT held, held_issue, held_why FROM social_token WHERE id = 1").rows
        if not rows:
            return None
        seed, issue, why = rows[0].get("held"), rows[0].get("held_issue"), rows[0].get("held_why")
        if not isinstance(seed, str) or not seed:
            return None
        return Held(
            seed=seed,
            issue=issue if isinstance(issue, int) and issue > 0 else None,
            why=str(why or "X refused a post"),
        )

    def refused_seed(self) -> str | None:
        """The fingerprint of the secret whose chain stopped, or ``None`` when it works."""
        rows = self.db.run("SELECT refused FROM social_token WHERE id = 1").rows
        value = rows[0].get("refused") if rows else None
        return value if isinstance(value, str) and value else None

    def _token_row(self) -> Row | None:
        try:
            rows = self.db.run("SELECT version, sealed, lease FROM social_token WHERE id = 1").rows
        except StoreError:
            return None
        return rows[0] if rows else None

    # -- the posts ---------------------------------------------------------------------

    def taken_slots(self) -> set[str]:
        """Every slot claimed, posted, uncertain or skipped (X refused it twice)."""
        return {str(row["slot"]) for row in self.db.run("SELECT slot FROM social_posts").rows}

    def posts_on(self, day: str) -> int:
        rows = self.db.run(
            "SELECT COUNT(*) AS n FROM social_posts WHERE day = ? AND state != 'skipped'", (day,)
        ).rows
        n = rows[0].get("n") if rows else 0
        return n if isinstance(n, int) else 0

    def last_post(self) -> Row | None:
        """The newest claimed row (claimed, posted or uncertain), or ``None``."""
        rows = self.db.run(
            "SELECT slot, kind, style, claimed_at, posted_at FROM social_posts"
            " WHERE state != 'skipped' ORDER BY claimed_at DESC LIMIT 1"
        ).rows
        return rows[0] if rows else None

    def refused(self, slot: str, status: int, now: datetime, run: str) -> int:
        """Count one more refusal of ``slot`` by X (a 4xx that is not for good); how many
        there were with this status in a row (another status starts the count again). A run
        counts once: when the statement is sent again after its answer was lost, the row
        already names this run and the count stays."""
        self.db.run(
            "INSERT INTO social_refusals (slot, count, status, at, run) VALUES (?, 1, ?, ?, ?)"
            " ON CONFLICT (slot) DO UPDATE SET count = CASE"
            " WHEN social_refusals.run = excluded.run THEN social_refusals.count"
            " WHEN social_refusals.status = excluded.status THEN social_refusals.count + 1"
            " ELSE 1 END, status = excluded.status, at = excluded.at, run = excluded.run",
            (slot, status, _iso(now), run),
        )
        rows = self.db.run("SELECT count FROM social_refusals WHERE slot = ?", (slot,)).rows
        count = rows[0].get("count") if rows else None
        return count if isinstance(count, int) else 1

    def skip(self, slot: str, run: str) -> None:
        """Keep this run's claim on ``slot`` as ``skipped``: X refused it
        :data:`REFUSALS_TO_SKIP` times, so no run sends it again (it counts toward no cap)."""
        self.db.run(
            "UPDATE social_posts SET state = 'skipped' WHERE slot = ? AND run = ?"
            " AND state = 'claimed'",
            (slot, run),
        )

    def claim(  # noqa: PLR0913 - one row's columns
        self, slot: str, *, kind: str, style: str, image: str, run: str, now: datetime
    ) -> bool:
        """Claim a slot before sending it: false when it is taken or the day is full.

        When the claim's answer is lost, the row is read back: a row this run holds counts
        as claimed, so a claim that was made is never left stranded.

        Raises:
            StoreError: the claim failed and its row could not be read back.
        """
        day = now.date().isoformat()
        try:
            made = self.db.run(
                "INSERT INTO social_posts (slot, kind, style, day, state, image, claimed_at,"
                " run) SELECT ?, ?, ?, ?, 'claimed', ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM"
                " social_posts WHERE slot = ?) AND (SELECT COUNT(*) FROM social_posts WHERE"
                " day = ? AND state != 'skipped') < ?",
                (slot, kind, style, day, image, _iso(now), run, slot, day, MAX_POSTS_PER_DAY),
                retry=False,
            )
        except StoreError:
            rows = self.db.run("SELECT run, state FROM social_posts WHERE slot = ?", (slot,)).rows
            if rows and rows[0].get("run") == run and rows[0].get("state") == "claimed":
                return True
            raise
        return made.changes == 1

    def stale_claims(self, now: datetime) -> list[Row]:
        """Claims older than :data:`STALE_CLAIM` (runs that stopped mid-send)."""
        return list(
            self.db.run(
                "SELECT slot, run, claimed_at FROM social_posts WHERE state = 'claimed'"
                " AND claimed_at < ? ORDER BY claimed_at",
                (_iso(now - STALE_CLAIM),),
            ).rows
        )

    def posted(self, slot: str, run: str, post_id: str, now: datetime) -> None:
        """Mark a slot posted, asked up to :data:`STORE_TRIES` times (the same update twice
        changes nothing more).

        Raises:
            StoreError: it could not be recorded.
        """
        for attempt in range(STORE_TRIES):
            try:
                self.db.run(
                    "UPDATE social_posts SET state = 'posted', post_id = ?, posted_at = ?"
                    " WHERE slot = ? AND run = ?",
                    (post_id, _iso(now), slot, run),
                )
            except StoreError:
                if attempt == STORE_TRIES - 1:
                    raise
                time.sleep(self.db.pause)
                continue
            return

    def uncertain(self, slot: str, run: str) -> None:
        self.db.run(
            "UPDATE social_posts SET state = 'uncertain' WHERE slot = ? AND run = ?",
            (slot, run),
        )

    # -- the Haiku days ------------------------------------------------------------------

    def begin_haiku_day(self, day: str, run: str, now: datetime) -> bool:
        """Mark ``day`` (a UTC date) as the day Haiku writes in this run: false when a run
        already asked Haiku that day. A lost answer is read back.

        Raises:
            StoreError: the row could not be made or read back.
        """
        try:
            made = self.db.run(
                "INSERT INTO social_haiku_days (day, state, run, at) SELECT ?, 'writing', ?, ?"
                " WHERE NOT EXISTS (SELECT 1 FROM social_haiku_days WHERE day = ?)",
                (day, run, _iso(now), day),
                retry=False,
            )
        except StoreError:
            rows = self.db.run("SELECT run FROM social_haiku_days WHERE day = ?", (day,)).rows
            if rows and rows[0].get("run") == run:
                return True
            raise
        return made.changes == 1

    def haiku_tries(self, day: str) -> int:
        """How many times Haiku was asked to write on ``day`` (a UTC date): its rows
        ``<day>#<n>``, and a row named by the day alone (one try a day, before Oct 27, 2026)."""
        rows = self.db.run(
            "SELECT COUNT(*) AS n FROM social_haiku_days WHERE day = ? OR day LIKE ?",
            (day, f"{day}#%"),
        ).rows
        value = rows[0].get("n") if rows else 0
        return int(value) if isinstance(value, int | str) else 0

    def haiku_marks(self, since: datetime, but: str) -> set[str]:
        """The marks of the Haiku drafts made since ``since`` that X may have been sent
        (their rows' ``drafted <mark>`` state, :func:`snowlight.social.post.draft_mark`, with
        the try's slot still in ``social_posts``: posted, uncertain, claimed or skipped; a
        claim dropped before X got the post is gone), but the try ``but``."""
        rows = self.db.run(
            "SELECT h.state AS state FROM social_haiku_days AS h JOIN social_posts AS p"
            " ON p.slot = 'haiku:' || h.day WHERE h.at >= ? AND h.day != ?"
            " AND h.state LIKE 'drafted %'",
            (_iso(since), but),
        ).rows
        return {str(row.get("state")).removeprefix("drafted ") for row in rows}

    def mark(self, slot: str, mark: str, now: datetime) -> None:
        """Keep the mark of the post about to be claimed for ``slot`` (the same slot's mark is
        replaced: a queued post edited after a refusal is held by its new words)."""
        self.db.run(
            "INSERT INTO social_marks (slot, mark, at) VALUES (?, ?, ?) ON CONFLICT (slot)"
            " DO UPDATE SET mark = excluded.mark, at = excluded.at",
            (slot, mark, _iso(now)),
        )

    def recent_marks(self, since: datetime, but: str) -> set[str]:
        """The marks of the posts of every kind claimed since ``since`` that X may have been
        sent (the slot still in ``social_posts``: posted, uncertain, claimed or skipped), but
        the slot ``but``."""
        rows = self.db.run(
            "SELECT m.mark AS mark FROM social_marks AS m JOIN social_posts AS p"
            " ON p.slot = m.slot WHERE p.claimed_at >= ? AND m.slot != ?",
            (_iso(since), but),
        ).rows
        return {str(row.get("mark")) for row in rows}

    def haiku_day(self, day: str) -> str | None:
        """How ``day``'s Haiku try went (``writing``, ``failed``, ``drafted <mark>``), or
        ``None``."""
        rows = self.db.run("SELECT state FROM social_haiku_days WHERE day = ?", (day,)).rows
        value = rows[0].get("state") if rows else None
        return str(value) if value is not None else None

    def end_haiku_day(self, day: str, run: str, state: str) -> None:
        self.db.run(
            "UPDATE social_haiku_days SET state = ? WHERE day = ? AND run = ?", (state, day, run)
        )

    def release(self, slot: str, run: str) -> None:
        """Drop this run's claim on a slot nothing was posted for."""
        self.db.run(
            "DELETE FROM social_posts WHERE slot = ? AND run = ? AND state = 'claimed'",
            (slot, run),
        )

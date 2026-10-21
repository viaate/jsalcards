"""What the sender reads from and writes to the accounts database (migration 0004).

Reads: the VAPID key pair, the accounts that have a browser to send to (not disabled, the
browser's sign-in still lasting, with their saved schools and settings), and the log.
Writes: the log (only for accounts that still exist), the push services' refusals in a row,
and the deletion of subscriptions a push service says are gone or kept refusing. Every value
is a bound parameter.
"""

import json
from collections.abc import Iterable, Sequence
from datetime import date, time
from typing import Final

from snowlight.notify.d1 import D1, MAX_PARAMS, Row, Value
from snowlight.notify.rules import (
    THRESHOLDS,
    Account,
    Kind,
    Record,
    School,
    SentKey,
    Settings,
    Subscription,
)
from snowlight.notify.webpush import Vapid, VapidError

MAX_SCHOOLS: Final = 5
KINDS: Final[frozenset[str]] = frozenset({"status", "chance", "chance_rise", "night"})
KEEP_DAYS: Final = 4
"""The log keeps this many days before today (UTC)."""

STRIKES: Final = 10
"""Refusals in a row (:attr:`~snowlight.notify.webpush.Delivery.REFUSED`) after which a
browser is deleted, once they span :data:`STRIKE_SPAN_MS` too."""
STRIKE_SPAN_MS: Final = 24 * 3600 * 1000

LIVE: Final = """FROM push_subscriptions p
  JOIN users u ON u.id = p.user_id
  JOIN sessions se ON se.token_hash = p.session_hash AND se.expires_at > ?1"""
"""The browsers that get notifications: the account is not disabled and the sign-in each was
turned on in still lasts (logging out, a password change, an admin reset or disable and
expiry all end it; docs/notify.md)."""

COUNT_SQL: Final = f"SELECT COUNT(*) AS n {LIVE} WHERE u.disabled = 0"

ACCOUNTS_SQL: Final = f"""SELECT u.id AS user_id, u.schools AS schools,
  s.status AS status, s.chance AS chance, s.threshold AS threshold,
  s.night_before AS night_before, s.night_time AS night_time,
  s.quiet_from AS quiet_from, s.quiet_to AS quiet_to,
  p.endpoint AS endpoint, p.p256dh AS p256dh, p.auth AS auth, p.failures AS failures
  {LIVE}
  LEFT JOIN notify_settings s ON s.user_id = u.id
  WHERE u.disabled = 0
  ORDER BY u.id, p.created_at, p.endpoint"""


def subscription_count(db: D1, now_ms: int) -> int:
    """How many browsers get notifications (:data:`LIVE`)."""
    rows = db.query(COUNT_SQL, (now_ms,))
    return int(rows[0].get("n") or 0) if rows else 0


def read_vapid(db: D1) -> Vapid | None:
    """The key pair api.yml made (``None`` until it made one, or when it is not a pair)."""
    rows = db.query(
        "SELECT name, value FROM settings WHERE name IN ('vapid_public', 'vapid_private')"
    )
    values = {str(row.get("name")): str(row.get("value")) for row in rows}
    if "vapid_public" not in values or "vapid_private" not in values:
        return None
    try:
        return Vapid.from_stored(values["vapid_private"], values["vapid_public"])
    except VapidError:
        return None


def _time(value: object, default: time) -> time:
    try:
        return time.fromisoformat(str(value)) if value is not None else default
    except ValueError:
        return default


def settings_of(row: Row) -> Settings:
    """An account's settings from its row (no row: the defaults)."""
    if row.get("status") is None:
        return Settings()
    defaults = Settings()
    threshold = row.get("threshold")
    return Settings(
        status=bool(row.get("status")),
        chance=bool(row.get("chance")),
        threshold=threshold
        if isinstance(threshold, int) and threshold in THRESHOLDS
        else defaults.threshold,
        night_before=bool(row.get("night_before")),
        night_time=_time(row.get("night_time"), defaults.night_time),
        quiet_from=_time(row.get("quiet_from"), defaults.quiet_from),
        quiet_to=_time(row.get("quiet_to"), defaults.quiet_to),
    )


def schools_of(text: object) -> tuple[School, ...]:
    """The saved schools (``users.schools``, a JSON list of ``{id, name}``); anything else
    reads as none."""
    try:
        parsed = json.loads(str(text))
    except ValueError:
        return ()
    if not isinstance(parsed, list):
        return ()
    found: list[School] = []
    for item in parsed[:MAX_SCHOOLS]:
        if not isinstance(item, dict):
            continue
        school_id, name = item.get("id"), item.get("name")
        if isinstance(school_id, str) and isinstance(name, str) and name.strip():
            found.append(School(id=school_id, name=name.strip()[:120]))
    return tuple(found)


def read_accounts(db: D1, now_ms: int) -> list[Account]:
    """Every account with a browser that gets notifications (:data:`LIVE`), with its schools
    and settings."""
    accounts: dict[str, Account] = {}
    for row in db.query(ACCOUNTS_SQL, (now_ms,)):
        user_id = str(row.get("user_id"))
        failures = row.get("failures")
        subscription = Subscription(
            endpoint=str(row.get("endpoint")),
            p256dh=str(row.get("p256dh")),
            auth=str(row.get("auth")),
            failures=failures if isinstance(failures, int) else 0,
        )
        known = accounts.get(user_id)
        if known is None:
            accounts[user_id] = Account(
                user_id=user_id,
                schools=schools_of(row.get("schools")),
                settings=settings_of(row),
                subscriptions=(subscription,),
            )
        else:
            accounts[user_id] = Account(
                user_id=user_id,
                schools=known.schools,
                settings=known.settings,
                subscriptions=(*known.subscriptions, subscription),
            )
    return list(accounts.values())


def read_sent(db: D1, since: date) -> dict[SentKey, str]:
    """The log from ``since`` on."""
    rows = db.query(
        "SELECT user_id, school_id, kind, day, value FROM notify_sent WHERE day >= ?1",
        (since.isoformat(),),
    )
    sent: dict[SentKey, str] = {}
    for row in rows:
        kind = str(row.get("kind"))
        if kind not in KINDS:
            continue
        try:
            day = date.fromisoformat(str(row.get("day")))
        except ValueError:
            continue
        sent[SentKey(str(row.get("user_id")), str(row.get("school_id")), _kind(kind), day)] = str(
            row.get("value")
        )
    return sent


def _kind(value: str) -> Kind:
    if value == "status":
        return "status"
    if value == "chance":
        return "chance"
    if value == "chance_rise":
        return "chance_rise"
    return "night"


ROW_PARAMS: Final = 6
PER_INSERT: Final = MAX_PARAMS // ROW_PARAMS
"""Log rows in one statement."""
INSERT_HEAD: Final = (
    "INSERT INTO notify_sent (user_id, school_id, kind, day, value, sent_at)"
    " SELECT v.column1, v.column2, v.column3, v.column4, v.column5, v.column6 FROM (VALUES "
)
INSERT_TAIL: Final = (
    ") AS v WHERE EXISTS (SELECT 1 FROM users u WHERE u.id = v.column1)"
    " ON CONFLICT (user_id, school_id, kind, day)"
    " DO UPDATE SET value = excluded.value, sent_at = excluded.sent_at"
)
"""Only rows of accounts that still exist: an account deleted while a pass runs drops its
rows instead of failing the statement on the foreign key, with the other accounts' rows."""


def write_sent(db: D1, records: Iterable[Record], at_ms: int) -> int:
    """Writes log rows (a newer value replaces an older one), leaving out accounts that are
    gone; returns how many it was given."""
    rows = list(records)
    for start in range(0, len(rows), PER_INSERT):
        chunk = rows[start : start + PER_INSERT]
        places = ", ".join(
            "(" + ", ".join(f"?{i * ROW_PARAMS + j + 1}" for j in range(ROW_PARAMS)) + ")"
            for i in range(len(chunk))
        )
        params: list[Value] = []
        for record in chunk:
            key = record.key
            params += [key.user_id, key.school_id, key.kind, key.day.isoformat(), record.value]
            params.append(at_ms)
        db.query(INSERT_HEAD + places + INSERT_TAIL, params)
    return len(rows)


def delete_subscriptions(db: D1, endpoints: Sequence[str]) -> None:
    """Deletes the subscriptions a push service said are gone."""
    for start in range(0, len(endpoints), MAX_PARAMS):
        chunk = endpoints[start : start + MAX_PARAMS]
        places = ", ".join(f"?{i + 1}" for i in range(len(chunk)))
        db.query(f"DELETE FROM push_subscriptions WHERE endpoint IN ({places})", chunk)  # noqa: S608 - placeholders only


def _in(endpoints: Sequence[str], first: int) -> str:
    return ", ".join(f"?{first + i}" for i in range(len(endpoints)))


def note_refusals(db: D1, endpoints: Sequence[str], at_ms: int) -> None:
    """Counts one more refusal in a row for each browser, and deletes those refused
    :data:`STRIKES` times in a row over more than :data:`STRIKE_SPAN_MS`."""
    per = MAX_PARAMS - 2
    for start in range(0, len(endpoints), per):
        chunk = list(endpoints[start : start + per])
        db.query(
            "UPDATE push_subscriptions SET failures = failures + 1,"  # noqa: S608 - placeholders only
            f" failing_since = COALESCE(failing_since, ?1) WHERE endpoint IN ({_in(chunk, 2)})",
            [at_ms, *chunk],
        )
        db.query(
            "DELETE FROM push_subscriptions WHERE failures >= ?1 AND failing_since <= ?2"  # noqa: S608 - placeholders only
            f" AND endpoint IN ({_in(chunk, 3)})",
            [STRIKES, at_ms - STRIKE_SPAN_MS, *chunk],
        )


def clear_refusals(db: D1, endpoints: Sequence[str]) -> None:
    """A browser that took a push starts its count of refusals again."""
    for start in range(0, len(endpoints), MAX_PARAMS):
        chunk = list(endpoints[start : start + MAX_PARAMS])
        db.query(
            "UPDATE push_subscriptions SET failures = 0, failing_since = NULL"  # noqa: S608 - placeholders only
            f" WHERE endpoint IN ({_in(chunk, 1)})",
            chunk,
        )


def prune_sent(db: D1, before: date) -> None:
    """Drops the log's rows for days before ``before``."""
    db.query("DELETE FROM notify_sent WHERE day < ?1", (before.isoformat(),))

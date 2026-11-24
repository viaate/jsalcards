"""``snowlight notify flights`` (flights-live.yml, after each live pass): the Flights trip alerts
(flights spec D12), by web push through the existing push path and, where the account connected
Google, by email from its own Gmail to itself.

The Actions job does the work; the Worker only stores and sends (10 ms rule). The job reads the
saved trips, choices, browsers and log from the accounts database over the Cloudflare API (as the
Schools sender does), the published Flights files from the live repository through GitHub's API
(never the CDN), and works each trip's alerts (:mod:`snowlight.notify.flights_rules`). A push goes
to each of the account's browsers whose sign-in lasts; an email goes through the Worker's
``POST /v1/internal/flights/mail``, which words and sends it. The job proves itself to that route
with a fresh key whose SHA-256 it writes in the database's settings table for 15 minutes (it has
no secret of its own) and deletes after the pass. An alert is logged once a browser or the email
took it, so each change is said once.

It fails dark and stays quiet as the Schools sender does: no secrets, no tables, no trips, an old
live file: one line, nothing sent, exit 0. Nothing it logs names a person, a trip or an address.
"""

import argparse
import hashlib
import json
import os
import secrets as tokens
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Final

import httpx
from pydantic import ValidationError

from snowlight.notify import store
from snowlight.notify.d1 import D1, RETRY_PAUSE, D1Error, NoTablesError, Row, Secrets
from snowlight.notify.flights_rules import (
    Airport,
    Alert,
    Choices,
    Told,
    Trip,
    World,
    alerts_for,
)
from snowlight.notify.rules import Subscription
from snowlight.notify.webpush import Delivery, Message, Vapid, send
from snowlight.schemas.flights import FlightsLatest, FlightsLive, FlightsRoutes

type Env = Mapping[str, str]

LIVE_REPOSITORY: Final = "viaate/snowlight-live"
LIVE_ROOT: Final = "v1"
AIRPORTS_FILE: Final = (
    Path(__file__).resolve().parents[3] / "web" / "public" / "flights" / "airports.json"
)
MAIL_KEY: Final = "flights_mail_key"
MAIL_KEY_MINUTES: Final = 15
TICKETS: Final[frozenset[str]] = frozenset({"basic", "regular", "premium", "unsure"})
SEND_SCOPE: Final = "https://www.googleapis.com/auth/gmail.send"

TRIPS_SQL: Final = """SELECT t.id, t.user_id, t.carrier, t.number, t.from_airport, t.to_airport,
  t.day, t.leaves, t.lands, t.ticket, t.need_by
  FROM trips t JOIN users u ON u.id = t.user_id
  WHERE u.disabled = 0 AND t.day >= ?1 AND t.day <= ?2
  ORDER BY t.user_id, t.day, t.leaves"""
CHOICES_SQL: Final = """SELECT u.id AS user_id, f.alerts, f.threshold, f.night_before, f.night_time,
  f.email, s.quiet_from, s.quiet_to
  FROM users u LEFT JOIN flights_notify f ON f.user_id = u.id
  LEFT JOIN notify_settings s ON s.user_id = u.id
  WHERE u.id IN (SELECT DISTINCT user_id FROM trips WHERE day >= ?1 AND day <= ?2)"""
BROWSERS_SQL: Final = f"""SELECT p.user_id, p.endpoint, p.p256dh, p.auth, p.failures
  {store.LIVE}
  WHERE u.disabled = 0
    AND p.user_id IN (SELECT DISTINCT user_id FROM trips WHERE day >= ?2 AND day <= ?3)
  ORDER BY p.user_id, p.created_at, p.endpoint"""  # noqa: S608 - a constant join, no value
MAILED_SQL: Final = "SELECT user_id, scopes FROM google_links"
SENT_SQL: Final = """SELECT trip_id, kind, value, sent_at FROM flights_sent
  WHERE trip_id IN (SELECT id FROM trips WHERE day >= ?1 AND day <= ?2)"""
LOG_SQL: Final = """INSERT OR IGNORE INTO flights_sent (user_id, trip_id, kind, value, sent_at)
  SELECT ?1, ?2, ?3, ?4, ?5 WHERE EXISTS (SELECT 1 FROM trips WHERE id = ?2 AND user_id = ?1)"""


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


# --- reading ------------------------------------------------------------------------------------


def _clock(value: object, default: time) -> time:
    if isinstance(value, str) and len(value) == 5:  # noqa: PLR2004 - "HH:MM"
        try:
            return time.fromisoformat(value)
        except ValueError:
            return default
    return default


def choices_of(row: Row) -> Choices:
    base = Choices()
    threshold = row.get("threshold")
    return Choices(
        alerts=row.get("alerts") != 0,
        threshold=threshold
        if isinstance(threshold, int) and threshold in {30, 50, 70}
        else base.threshold,
        night_before=row.get("night_before") != 0,
        night_time=_clock(row.get("night_time"), base.night_time),
        email=row.get("email") != 0,
        quiet_from=_clock(row.get("quiet_from"), base.quiet_from),
        quiet_to=_clock(row.get("quiet_to"), base.quiet_to),
    )


def trip_of(row: Row) -> Trip | None:
    try:
        ticket = str(row.get("ticket"))
        need = row.get("need_by")
        return Trip(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            carrier=str(row["carrier"]),
            number=int(row["number"]),
            from_=str(row["from_airport"]),
            to=str(row["to_airport"]),
            day=date.fromisoformat(str(row["day"])),
            leaves=int(row["leaves"]),
            lands=int(row["lands"]),
            ticket=ticket if ticket in TICKETS else "unsure",  # type: ignore[arg-type]
            need_by=need if isinstance(need, str) else None,
        )
    except (KeyError, ValueError, TypeError):
        return None


@dataclass(frozen=True, slots=True)
class Accounts:
    trips: list[Trip]
    choices: dict[str, Choices]
    browsers: dict[str, list[Subscription]]
    mailed: set[str]
    sent: dict[tuple[str, str], frozenset[str]]
    told: dict[str, Told] = field(default_factory=dict)
    """Per trip, its last chance, rise, fall or safer alert."""


RISK_KINDS: Final = frozenset({"chance", "rise", "fall", "safer"})
OWN_TOPIC: Final = frozenset({"faa", "waiver"})
"""The alert kinds with their own push topic; the trip's risk (chance, rise, fall, safer and the
evening check) shares one, as it shares one tray slot (push.ts flightTag)."""


def push_topic(kind: str, trip_id: str) -> str:
    """The alert's push topic: a newer alert on it replaces one the push service still holds for
    a phone that was offline, so two risk alerts from two passes never reach it out of order and
    an older one never stands as current (TRAV-R6-B1). Web Push topics are at most 32 URL-safe
    characters."""
    group = kind if kind in OWN_TOPIC else "risk"
    return f"fl-{group}-{trip_id[:20]}"


STATE_KINDS: Final = frozenset({"chance", "rise", "fall"})
"""Of the rows one alert logs at once (a chance and the plans it named), the one with the state."""


def read_accounts(db: D1, now: datetime) -> Accounts:
    """The trips from yesterday to 3 days ahead (every airport's today and the next 2 days are
    within them), their accounts' choices, browsers, Google links and log."""
    first = (now - timedelta(days=1)).date().isoformat()
    last = (now + timedelta(days=3)).date().isoformat()
    trips = [
        t for t in (trip_of(row) for row in db.query(TRIPS_SQL, (first, last))) if t is not None
    ]
    choices = {
        str(row.get("user_id")): choices_of(row) for row in db.query(CHOICES_SQL, (first, last))
    }
    browsers: dict[str, list[Subscription]] = {}
    for row in db.query(BROWSERS_SQL, (int(now.timestamp() * 1000), first, last)):
        failures = row.get("failures")
        browsers.setdefault(str(row.get("user_id")), []).append(
            Subscription(
                endpoint=str(row.get("endpoint")),
                p256dh=str(row.get("p256dh")),
                auth=str(row.get("auth")),
                failures=failures if isinstance(failures, int) else 0,
            )
        )
    mailed = {
        str(row.get("user_id"))
        for row in db.query(MAILED_SQL)
        if SEND_SCOPE in str(row.get("scopes", "")).split(" ")
    }
    sent: dict[tuple[str, str], set[str]] = {}
    told: dict[str, Told] = {}
    for row in db.query(SENT_SQL, (first, last)):
        trip_id, kind = str(row.get("trip_id")), str(row.get("kind"))
        value = str(row.get("value"))
        sent.setdefault((trip_id, kind), set()).add(value)
        at = row.get("sent_at")
        if kind in RISK_KINDS and isinstance(at, int | float) and not isinstance(at, bool):
            when = datetime.fromtimestamp(at / 1000, UTC)
            last_told = told.get(trip_id)
            if (
                last_told is None
                or when > last_told.at
                or (when == last_told.at and kind in STATE_KINDS)
            ):
                told[trip_id] = Told(when, kind, value)
    return Accounts(
        trips, choices, browsers, mailed, {k: frozenset(v) for k, v in sent.items()}, told
    )


def read_airports(path: Path = AIRPORTS_FILE) -> dict[str, Airport]:
    """The site's committed airports table (web/public/flights/airports.json)."""
    data = json.loads(path.read_text())
    out: dict[str, Airport] = {}
    for row in data.get("airports", []):
        try:
            out[str(row["code"])] = Airport(
                str(row["code"]),
                str(row["tz"]),
                float(row["lat"]),
                float(row["lon"]),
                float(row["per_day"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


# --- sending ------------------------------------------------------------------------------------


@dataclass(slots=True)
class Report:
    due: int = 0
    pushed: int = 0
    mailed: int = 0
    held: int = 0
    """Alerts no browser and no email took (said again next pass if still due)."""

    def line(self) -> str:
        return f"{self.due} due, {self.pushed} pushed, {self.mailed} emailed, {self.held} not taken"


type Pusher = Callable[[Subscription, Message, int], Delivery]
type Mailer = Callable[[str, Mapping[str, object]], bool]


def mail_key(db: D1, now: datetime) -> str:
    """A fresh key for the Worker's mail route: its SHA-256 goes in the settings table for 15
    minutes (the key itself never leaves this job)."""
    key = tokens.token_urlsafe(32)[:43]
    digest = hashlib.sha256(key.encode()).hexdigest()
    ends = int((now + timedelta(minutes=MAIL_KEY_MINUTES)).timestamp() * 1000)
    db.query(
        "INSERT INTO settings (name, value) VALUES (?1, ?2)"
        " ON CONFLICT (name) DO UPDATE SET value = ?2",
        (MAIL_KEY, f"{digest}:{ends}"),
    )
    return key


def drop_mail_key(db: D1) -> None:
    db.query("DELETE FROM settings WHERE name = ?1", (MAIL_KEY,))


def worker_mailer(client: httpx.Client, api_root: str, key: str) -> Mailer:
    """Sends one alert email through the Worker (it words it and sends it from the person's own
    Gmail). A refusal or a failure is False: the alert is tried again next pass."""

    def mail(user_id: str, facts: Mapping[str, object]) -> bool:
        try:
            response = client.post(
                f"{api_root.rstrip('/')}/v1/internal/flights/mail",
                json={"user_id": user_id, "alert": facts},
                headers={"Authorization": f"Bearer {key}"},
                timeout=30.0,
            )
        except httpx.HTTPError:
            return False
        return response.status_code == httpx.codes.OK

    return mail


def deliver(  # noqa: PLR0913, PLR0917 - the alerts, who gets them and how
    db: D1,
    alerts: Sequence[Alert],
    accounts: Accounts,
    pusher: Pusher | None,
    mailer: Mailer | None,
    now: datetime,
) -> Report:
    """Sends each alert to the account's browsers and its email, and logs what was taken."""
    report = Report(due=len(alerts))
    unix = int(now.timestamp())
    gone: set[str] = set()
    for alert in alerts:
        user = alert.trip.user_id
        took = False
        payload = json.dumps(alert.facts, separators=(",", ":")).encode()
        message = Message(
            payload=payload,
            ttl=alert.ttl,
            urgency="high" if alert.kind == "faa" else "normal",
            topic=push_topic(alert.kind, alert.trip.id),
        )
        if pusher is not None:
            for subscription in accounts.browsers.get(user, []):
                if subscription.endpoint in gone:
                    continue
                result = pusher(subscription, message, unix)
                if result is Delivery.GONE:
                    gone.add(subscription.endpoint)
                took = took or result is Delivery.SENT
            if took:
                report.pushed += 1
        choices = accounts.choices.get(user, Choices())
        if (
            mailer is not None
            and choices.email
            and user in accounts.mailed
            and mailer(user, alert.facts)
        ):
            took = True
            report.mailed += 1
        if not took:
            report.held += 1
            continue
        for kind, value in ((alert.kind, alert.value), *alert.also):
            db.query(LOG_SQL, (user, alert.trip.id, kind, value, unix * 1000))
    if gone:
        store.delete_subscriptions(db, sorted(gone))
    return report


def due_alerts(world: World, accounts: Accounts) -> list[Alert]:
    out: list[Alert] = []
    for trip in accounts.trips:
        choices = accounts.choices.get(trip.user_id, Choices())
        out.extend(alerts_for(world, trip, choices, accounts.sent, accounts.told.get(trip.id)))
    return out


def api_root_of(client: httpx.Client, secrets: Secrets, env: Env) -> str:
    """The accounts API's root: SNOWLIGHT_API_ROOT, else the Worker on the account's workers.dev
    subdomain, as api.yml finds it; empty when neither reads (no email is sent then)."""
    given = env.get("SNOWLIGHT_API_ROOT", "").strip()
    if given:
        return given
    try:
        response = client.get(
            f"{secrets.api}/accounts/{secrets.account}/workers/subdomain",
            headers={"Authorization": f"Bearer {secrets.token}"},
        )
        sub = response.json().get("result", {}).get("subdomain", "")
    except (httpx.HTTPError, ValueError, AttributeError):
        return ""
    return f"https://snowlight-api.{sub}.workers.dev" if isinstance(sub, str) and sub else ""


# --- the command --------------------------------------------------------------------------------


def public_file(client: httpx.Client, path: str, env: Env) -> bytes | None:  # pragma: no cover
    """A file of the live repository through GitHub's API (never the CDN)."""
    api = env.get("GITHUB_API_URL") or "https://api.github.com"
    headers = {"Accept": "application/vnd.github.raw+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token := env.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    response = client.get(f"{api}/repos/{LIVE_REPOSITORY}/contents/{path}", headers=headers)
    if response.status_code == httpx.codes.NOT_FOUND:
        return None
    response.raise_for_status()
    return response.content


type Reader = Callable[[str], bytes | None]


def read_world(read: Reader, now: datetime, airports: Mapping[str, Airport]) -> World:
    """The published Flights files: the current live file (its stamp the latest's), the waivers
    and, as asked, each airport's usual flights. A file that is missing or does not read is
    none; a live file that is old or another stamp is none."""
    live: FlightsLive | None = None
    latest_bytes = read(f"{LIVE_ROOT}/flights/latest.json")
    try:
        latest = None if latest_bytes is None else FlightsLatest.model_validate_json(latest_bytes)
        slot_bytes = (
            None if latest is None else read(f"{LIVE_ROOT}/flights/live/{latest.slot}.json")
        )
        candidate = None if slot_bytes is None else FlightsLive.model_validate_json(slot_bytes)
        if candidate is not None and latest is not None and candidate.stamp == latest.stamp:
            live = candidate
    except ValidationError:
        live = None
    waivers: Mapping[str, object] | None = None
    raw = read(f"{LIVE_ROOT}/flights/waivers.json")
    if raw is not None:
        try:
            value = json.loads(raw)
            waivers = value if isinstance(value, dict) else None
        except ValueError:
            waivers = None
    kept: dict[str, FlightsRoutes | None] = {}

    def routes(code: str) -> FlightsRoutes | None:
        if code not in kept:
            data = read(f"{LIVE_ROOT}/flights/routes/{code.lower()}.json")
            try:
                kept[code] = None if data is None else FlightsRoutes.model_validate_json(data)
            except ValidationError:
                kept[code] = None
        return kept[code]

    return World.of(now, airports, live, routes, waivers)


@dataclass(slots=True)
class Outside:
    """The parts that touch the world; tests replace them."""

    env: Callable[[], Env] = field(default=lambda: dict(os.environ))
    client: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=30.0)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    reader: Callable[[httpx.Client, Env], Reader] = lambda client, env: (
        lambda path: public_file(client, path, env)
    )
    airports: Callable[[], Mapping[str, Airport]] = read_airports
    pusher: Callable[[httpx.Client, Vapid], Pusher] = lambda client, vapid: (
        lambda s, m, now: send(client, vapid, s.endpoint, s.p256dh, s.auth, m, now)
    )
    pause: float = RETRY_PAUSE


def run_flights(_args: argparse.Namespace, outside: Outside | None = None) -> int:
    """One pass of the Flights alerts. Always exit 0: a problem is one warning line."""
    outside = outside or Outside()
    env = outside.env()
    secrets = Secrets.from_env(env)
    if secrets is None:
        _say("notify flights: no Cloudflare secrets: nothing to send")
        return 0
    try:
        return _run(outside, env, secrets)
    except D1Error as error:
        _say(f"::warning::notify flights: the accounts database failed ({error})")
    except Exception as error:
        _say(f"::warning::notify flights: {type(error).__name__}")
    return 0


def _run(outside: Outside, env: Env, secrets: Secrets) -> int:
    now = outside.clock()
    with outside.client() as client:
        try:
            db = D1.find(client, secrets, pause=outside.pause)
            accounts = read_accounts(db, now)
        except NoTablesError:
            _say(
                "notify flights: the trips tables are not there yet"
                " (api.yml applies 0006_flights.sql): nothing to send"
            )
            return 0
        if not accounts.trips:
            _say("notify flights: no trips in the next days: nothing to send")
            return 0
        world = read_world(outside.reader(client, env), now, outside.airports())
        if world.live is None:
            _say("notify flights: no current live file: only FAA and waiver alerts can be due")
        alerts = due_alerts(world, accounts)
        if not alerts:
            _say(f"notify flights: {len(accounts.trips)} trips, nothing due")
            return 0
        vapid = store.read_vapid(db)
        pusher = None if vapid is None else outside.pusher(client, vapid)
        api_root = api_root_of(client, secrets, env) if accounts.mailed else ""
        mailer: Mailer | None = None
        key: str | None = None
        if api_root.startswith("https://") and accounts.mailed:
            key = mail_key(db, now)
            mailer = worker_mailer(client, api_root, key)
        try:
            report = deliver(db, alerts, accounts, pusher, mailer, now)
        finally:
            if key is not None:
                drop_mail_key(db)
        _say(f"notify flights: {report.line()}")
    return 0


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """``notify flights``, on the ``notify`` command's actions."""
    flights = actions.add_parser("flights", help="Flights trip alerts (flights-live.yml)")
    flights.set_defaults(handler=run_flights)


__all__ = [
    "Accounts",
    "Report",
    "deliver",
    "due_alerts",
    "read_accounts",
    "read_world",
    "run_flights",
]

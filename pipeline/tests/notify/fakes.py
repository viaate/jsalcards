"""Stand-ins for the notification sender's world: the Cloudflare D1 API over a real SQLite
database built from the API's own migrations, browsers' push keys, and a stub push service.

Every account, school, key and address here is SYNTHETIC.
"""

import base64
import json
import re
import sqlite3
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from snowlight.notify.d1 import D1, Secrets
from snowlight.notify.webpush import Vapid, b64encode

MIGRATIONS = Path(__file__).resolve().parents[3] / "api" / "migrations"
API = "https://cf.test/client/v4"
ACCOUNT = "acct"
DATABASE_ID = "11111111-2222-3333-4444-555555555555"
SECRETS = Secrets(token="tok", account=ACCOUNT, api=API)  # noqa: S106 - a test token


def migrate(db: sqlite3.Connection, *, skip: Callable[[str], bool] = lambda _f: False) -> None:
    """Applies the API's migrations as the Miniflare harness does (comments dropped, split on
    semicolons)."""
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if skip(path.name):
            continue
        text = re.sub(r"--[^\n]*", "", path.read_text())
        for statement in (part.strip() for part in text.split(";")):
            if statement:
                db.execute(statement)
    db.commit()


def _connect() -> sqlite3.Connection:
    """An in-memory database that enforces foreign keys, as D1 does."""
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")
    return db


SIGNED_IN_UNTIL = 10**15
"""A session's expiry far in the future (milliseconds)."""


def session_of(endpoint: str) -> str:
    """The token_hash of the session a test browser was turned on in."""
    return f"session:{endpoint}"


@dataclass
class FakeD1:
    """The D1 part of the Cloudflare API, over one SQLite database."""

    db: sqlite3.Connection = field(default_factory=_connect)
    fail: list[int] = field(default_factory=list)
    """HTTP statuses to answer with before answering properly (one each)."""
    statements: list[str] = field(default_factory=list)
    params: list[list[Any]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            return httpx.Response(self.fail.pop(0), json={"success": False, "errors": []})
        assert request.headers["Authorization"] == f"Bearer {SECRETS.token}"
        path = request.url.path
        if request.method == "GET" and path.endswith(f"/accounts/{ACCOUNT}/d1/database"):
            assert request.url.params.get("name") == "snowlight-accounts"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": [{"uuid": DATABASE_ID, "name": "snowlight-accounts"}],
                },
            )
        assert path.endswith(f"/accounts/{ACCOUNT}/d1/database/{DATABASE_ID}/query")
        body = json.loads(request.content)
        self.statements.append(body["sql"])
        self.params.append(body["params"])
        try:
            # D1 binds ?1, ?2, ...: Python's sqlite3 takes those as names.
            params = {str(i + 1): value for i, value in enumerate(body["params"])}
            cursor = self.db.execute(body["sql"], params)
        except sqlite3.Error as error:
            return httpx.Response(
                400,
                json={"success": False, "errors": [{"code": 7500, "message": f"{error}"}]},
            )
        names = [column[0] for column in cursor.description or ()]
        rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        self.db.commit()
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": [
                    {"results": rows, "success": True, "meta": {"changes": cursor.rowcount}}
                ],
            },
        )

    def rows(self, sql: str, *params: Any) -> list[tuple[Any, ...]]:
        return list(self.db.execute(sql, params).fetchall())


def routed(
    fake: FakeD1, push: Callable[[httpx.Request], httpx.Response] | None = None
) -> httpx.Client:
    """A client whose Cloudflare calls reach ``fake``; anything else reaches ``push`` (or the
    real network, for the stub push service on a loopback port)."""
    real = httpx.HTTPTransport()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cf.test":
            return fake.handle(request)
        if push is not None:
            return push(request)
        response = real.handle_request(request)
        response.read()
        return response

    return httpx.Client(transport=httpx.MockTransport(handler))


def d1(fake: FakeD1) -> D1:
    return D1.find(routed(fake), SECRETS, pause=0)


@dataclass(frozen=True)
class Browser:
    """A browser's push subscription keys (it decrypts what it gets)."""

    private: ec.EllipticCurvePrivateKey
    auth: bytes
    endpoint: str

    @classmethod
    def make(cls, endpoint: str, seed: int = 1) -> "Browser":
        return cls(
            private=ec.generate_private_key(ec.SECP256R1()),
            auth=bytes([seed]) * 16,
            endpoint=endpoint,
        )

    @property
    def p256dh(self) -> str:
        return b64encode(
            self.private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        )

    @property
    def auth_b64(self) -> str:
        return b64encode(self.auth)


def vapid_rows() -> tuple[str, str, Vapid]:
    """A fresh VAPID pair as api.yml stores it: (private, public, the parsed pair)."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = b64encode(key.private_numbers().private_value.to_bytes(32, "big"))
    public = b64encode(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
    return private, public, Vapid.from_stored(private, public)


def add_vapid(fake: FakeD1) -> Vapid:
    private, public, vapid = vapid_rows()
    fake.db.execute(
        "INSERT INTO settings (name, value) VALUES ('vapid_public', ?), ('vapid_private', ?)",
        (public, private),
    )
    fake.db.commit()
    return vapid


def add_user(  # noqa: PLR0913 - one synthetic account
    fake: FakeD1,
    user_id: str,
    schools: list[tuple[str, str]],
    browsers: list[Browser] = (),  # type: ignore[assignment]
    *,
    disabled: bool = False,
    settings: dict[str, Any] | None = None,
    signed_in_until: int = SIGNED_IN_UNTIL,
) -> None:
    fake.db.execute(
        "INSERT INTO users (id, login, email, name, role, schools, disabled, created_at)"
        " VALUES (?, ?, ?, 'Pat Lee', 'user', ?, ?, 1)",
        (
            user_id,
            f"{user_id}@example.com",
            f"{user_id}@example.com",
            json.dumps([{"id": i, "name": n} for i, n in schools]),
            1 if disabled else 0,
        ),
    )
    for n, browser in enumerate(browsers):
        fake.db.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, refreshed_at)"
            " VALUES (?, ?, 1, ?, 1)",
            (session_of(browser.endpoint), user_id, signed_in_until),
        )
        fake.db.execute(
            "INSERT INTO push_subscriptions"
            " (endpoint, user_id, session_hash, p256dh, auth, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                browser.endpoint,
                user_id,
                session_of(browser.endpoint),
                browser.p256dh,
                browser.auth_b64,
                n,
            ),
        )
    if settings is not None:
        columns = ["user_id", *settings, "updated_at"]
        fake.db.execute(
            f"INSERT INTO notify_settings ({', '.join(columns)}) VALUES "  # noqa: S608 - test only
            f"({', '.join('?' for _ in columns)})",
            (user_id, *settings.values(), 1),
        )
    fake.db.commit()


@dataclass
class PushService:
    """A stub push service on a loopback port: it keeps what it was sent, and answers each
    path with the status set for it (201 by default)."""

    answers: dict[str, int] = field(default_factory=dict)
    received: list[tuple[str, dict[str, str], bytes]] = field(default_factory=list)
    url: str = ""

    def endpoint(self, name: str) -> str:
        return f"{self.url}/push/{name}"


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def serve_push() -> Iterator[PushService]:
    service = PushService()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            service.received.append((self.path, dict(self.headers.items()), body))
            status = service.answers.get(self.path, 201)
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    service.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield service
    finally:
        server.shutdown()
        server.server_close()

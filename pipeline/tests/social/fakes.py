"""Stand-ins for the social poster's world, all over mocked HTTP: the Cloudflare D1 API over a
real SQLite database, X (whose refresh tokens rotate and work once), GitHub's issues, and the
Anthropic Messages API.

Every token, key, fact and post here is SYNTHETIC.
"""

import base64
import json
import secrets
import sqlite3
import string
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import anthropic
import httpx
import httpx2

CF_API = "https://cf.test/client/v4"
ACCOUNT = "acct-test"
DATABASE_ID = "99999999-8888-7777-6666-555555555555"
X_API = "https://api.x.com"
GITHUB_API = "https://api.github.com"

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def token(prefix: str) -> str:
    """A secret-shaped SYNTHETIC token (mixed case and digits, 48 characters)."""
    alphabet = string.ascii_letters + string.digits
    return prefix + "Q7" + "".join(secrets.choice(alphabet) for _ in range(44))


SEED = token("Rt")
CLIENT_ID = token("Ci")
CLIENT_SECRET = token("Cs")
CF_TOKEN = token("Cf")
ANTHROPIC_KEY = "sk-ant-" + token("Ak")
GITHUB_TOKEN = "ghs_" + token("Gh")


def env(**extra: str) -> dict[str, str]:
    base = {
        "X_CLIENT_ID": CLIENT_ID,
        "X_CLIENT_SECRET": CLIENT_SECRET,
        "X_REFRESH_TOKEN": SEED,
        "CLOUDFLARE_API_TOKEN": CF_TOKEN,
        "CLOUDFLARE_ACCOUNT_ID": ACCOUNT,
        "CLOUDFLARE_API_URL": CF_API,
        "GITHUB_TOKEN": GITHUB_TOKEN,
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_RUN_ID": "1001",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    base.update(extra)
    return base


@dataclass
class FakeD1:
    db: sqlite3.Connection = field(default_factory=lambda: sqlite3.connect(":memory:"))
    has_database: bool = True
    fail_next: list[str] = field(default_factory=list)
    """Statement prefixes whose next request answers HTTP 500 (after running, when the
    entry starts with ``ran:``, as a lost answer)."""
    statements: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {CF_TOKEN}"
        path = request.url.path
        if request.method == "GET" and path.endswith("/d1/database"):
            result = (
                [{"name": "snowlight-live-state", "uuid": DATABASE_ID}] if self.has_database else []
            )
            return httpx.Response(200, json={"success": True, "result": result})
        assert path.endswith(f"/d1/database/{DATABASE_ID}/query"), path
        body = json.loads(request.content)
        sql, params = body["sql"], body["params"]
        self.statements.append(sql)
        for entry in list(self.fail_next):
            ran = entry.startswith("ran:")
            if sql.startswith(entry.removeprefix("ran:")):
                self.fail_next.remove(entry)
                if ran:
                    self._execute(sql, params)
                return httpx.Response(500, json={"success": False, "errors": []})
        try:
            rows, changes = self._execute(sql, params)
        except sqlite3.IntegrityError:
            return httpx.Response(
                400, json={"success": False, "errors": [{"message": "constraint"}]}
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": [{"success": True, "results": rows, "meta": {"changes": changes}}],
            },
        )

    def _execute(self, sql: str, params: list[Any]) -> tuple[list[dict[str, Any]], int]:
        cursor = self.db.execute(sql, params)
        names = [column[0] for column in cursor.description or []]
        rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        self.db.commit()
        return rows, cursor.rowcount if cursor.rowcount > 0 else 0

    def row(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        cursor = self.db.execute(sql, params)
        names = [column[0] for column in cursor.description or []]
        found = cursor.fetchone()
        return dict(zip(names, found, strict=True)) if found else None


@dataclass
class FakeX:
    valid: set[str] = field(default_factory=lambda: {SEED})
    scope: str = "tweet.read tweet.write users.read offline.access media.write"
    refresh_status: int = 200
    refresh_error: str = "invalid_request"
    upload_status: int = 200
    processing: list[str] = field(default_factory=list)
    post_status: int = 201
    post_raises: type[Exception] | None = None
    rotate: bool = True
    refreshes: int = 0
    uploads: int = 0
    posts: list[dict[str, Any]] = field(default_factory=list)
    issued: list[str] = field(default_factory=list)
    next_id: int = 1850000000000000001

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/2/oauth2/token":
            return self._refresh(request)
        auth = request.headers.get("Authorization", "")
        assert auth.startswith("Bearer ")
        assert auth[7:] in self.issued, "a stale access token"
        if path == "/2/media/upload" and request.method == "POST":
            self.uploads += 1
            assert b'name="media_category"' in request.content
            assert b"tweet_image" in request.content
            assert b'name="media"' in request.content
            if self.upload_status != 200:
                return httpx.Response(self.upload_status, json={"title": "Forbidden"})
            info = {"state": self.processing.pop(0)} if self.processing else None
            data: dict[str, Any] = {
                "id": "1880028106020515840",
                "media_key": "3_1880028106020515840",
            }
            if info:
                data["processing_info"] = {**info, "check_after_secs": 1}
            return httpx.Response(200, json={"data": data})
        if path == "/2/media/upload" and request.method == "GET":
            assert request.url.params["command"] == "STATUS"
            state = self.processing.pop(0) if self.processing else "succeeded"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": request.url.params["media_id"],
                        "processing_info": {"state": state},
                    }
                },
            )
        if path == "/2/tweets":
            if self.post_raises is not None:
                raise self.post_raises("synthetic", request=request)  # type: ignore[call-arg]
            body = json.loads(request.content)
            if self.post_status != 201:
                return httpx.Response(
                    self.post_status,
                    json={"title": "Forbidden", "detail": "synthetic", "type": "about:blank"},
                )
            self.posts.append(body)
            self.next_id += 1
            return httpx.Response(
                201, json={"data": {"id": str(self.next_id), "text": body["text"]}}
            )
        raise AssertionError(f"unexpected X call {request.method} {path}")

    def _refresh(self, request: httpx.Request) -> httpx.Response:
        self.refreshes += 1
        basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        assert request.headers["Authorization"] == f"Basic {basic}"
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        assert form["grant_type"] == "refresh_token"
        if self.refresh_status != 200:
            return httpx.Response(self.refresh_status, json={"error": "server_error"})
        if form["refresh_token"] not in self.valid:
            return httpx.Response(
                400,
                json={
                    "error": self.refresh_error,
                    "error_description": "Value passed for the token was invalid.",
                },
            )
        access = token("At")
        self.issued.append(access)
        body = {
            "token_type": "bearer",
            "expires_in": 7200,
            "access_token": access,
            "scope": self.scope,
        }
        if self.rotate:
            self.valid.discard(form["refresh_token"])
            rotated = token("Rr")
            self.valid.add(rotated)
            body["refresh_token"] = rotated
        return httpx.Response(200, json=body)


@dataclass
class FakeGitHub:
    issues: list[dict[str, Any]] = field(default_factory=list)
    comments: list[tuple[int, str]] = field(default_factory=list)
    calls: int = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        assert request.headers["Authorization"] == f"Bearer {GITHUB_TOKEN}"
        path = request.url.path
        if request.method == "GET" and path == "/repos/owner/repo/issues":
            return httpx.Response(
                200, json=[issue for issue in self.issues if issue["state"] == "open"]
            )
        if request.method == "POST" and path == "/repos/owner/repo/issues":
            body = json.loads(request.content)
            issue = {"number": len(self.issues) + 1, "state": "open", **body}
            self.issues.append(issue)
            return httpx.Response(201, json=issue)
        number = int(path.split("/")[5])
        issue = next(issue for issue in self.issues if issue["number"] == number)
        if request.method == "PATCH":
            issue.update(json.loads(request.content))
            return httpx.Response(200, json=issue)
        if request.method == "POST" and path.endswith("/comments"):
            self.comments.append((number, json.loads(request.content)["body"]))
            return httpx.Response(201, json={"id": 1})
        raise AssertionError(f"unexpected GitHub call {request.method} {path}")


@dataclass
class World:
    d1: FakeD1 = field(default_factory=FakeD1)
    x: FakeX = field(default_factory=FakeX)
    github: FakeGitHub = field(default_factory=FakeGitHub)

    def handle(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "cf.test":
            return self.d1.handle(request)
        if host == "api.x.com":
            return self.x.handle(request)
        if host == "api.github.com":
            return self.github.handle(request)
        raise AssertionError(f"unexpected host {host}")

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))


@dataclass
class FakeAnthropic:
    """The Messages API: answers in order, each a JSON object (or a full message dict)."""

    answers: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        assert request.headers["x-api-key"] == ANTHROPIC_KEY
        assert request.url.path == "/v1/messages"
        body = json.loads(request.content)
        self.requests.append(body)
        answer = self.answers.pop(0)
        if "status" in answer:
            return httpx2.Response(
                answer["status"],
                json={"type": "error", "error": {"type": "api_error", "message": "synthetic"}},
            )
        stop = answer.pop("_stop", "end_turn")
        text = answer.pop("_text", None)
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [
                    {"type": "text", "text": text if text is not None else json.dumps(answer)}
                ],
                "stop_reason": stop,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            },
        )

    def client(self) -> anthropic.Anthropic:
        return anthropic.Anthropic(
            api_key=ANTHROPIC_KEY,
            max_retries=0,
            http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(self.handle)),
        )


FACTS = """# Facts (SYNTHETIC test copy)

- [LIVE] waitlist: The waitlist is open; the link is in my bio.
- [LIVE] reader: The closings reader runs 24/7 in practice mode and checks lists every 5\
 minutes in the morning and evening.
- [LIVE] schools: The map holds 118,211 schools in 18,227 districts.
- [TESTING] map: The map itself is in private testing. | terms: the map, map
- [COMING] closings: Live closings on the map at launch. | terms: closings on the map, glow
- [COMING] alerts: Phone alerts for your school. | terms: alerts, notifications
"""


def make_root(
    tmp: Path,
    *,
    queue: list[dict[str, Any]] | None = None,
    images: int = 2,
    facts: str = FACTS,
) -> Path:
    social = tmp / "social"
    (social / "images").mkdir(parents=True)
    (social / "queue").mkdir()
    (social / "facts.md").write_text(facts)
    for n in range(1, images + 1):
        (social / "images" / f"img-{n}.png").write_bytes(PNG)
        (social / "images" / f"img-{n}.json").write_text(
            json.dumps(
                {
                    "id": f"img-{n}",
                    "file": f"img-{n}.png",
                    "day": "2026-10-20",
                    "shows": f"SYNTHETIC test image {n}: the national map at night, no glow",
                }
            )
        )
    for item in queue or []:
        (social / "queue" / f"{item['id']}.json").write_text(json.dumps(item))
        (social / "queue" / item["image"]).write_bytes(PNG)
    return tmp


def queued(
    number: str,
    text: str = "Dev log: the closings reader runs 24/7 in practice mode. Waitlist link in my bio.",
) -> dict[str, Any]:
    return {
        "id": number,
        "style": "dev_log",
        "text": text,
        "image": f"{number}.png",
        "day": "2026-10-26",
        "shows": "SYNTHETIC test image: the national map at night",
    }


class Clock:
    def __init__(self, start: datetime) -> None:
        self.at = start

    def __call__(self) -> datetime:
        return self.at


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


Say = Callable[[str], None]

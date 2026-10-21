"""End to end, against a stub push service on a loopback port and the D1 API over the API's
own migrations: ``snowlight notify status`` sends each new status once to every browser,
decryptable and signed, logs it, deletes a browser its push service says is gone or keeps
refusing, says a status was lifted only on an open statement (never because it left the
file), keeps the log through an account deleted mid-pass, never fails the run, and stays
quiet and dark whenever it should; the
chance notifier does the same for chances (tests/predict/test_notify_hook.py: the
predictions loop runs it only on the live root, never failing a pass for it).

Every account, school, key and file here is SYNTHETIC (the schemas' example files).
"""

import argparse
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import http_ece
import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from notify.fakes import (
    API,
    SIGNED_IN_UNTIL,
    Browser,
    FakeD1,
    PushService,
    add_user,
    add_vapid,
    b64d,
    migrate,
    routed,
    serve_push,
)
from snowlight import cli as main_cli
from snowlight.directory.points import NO_DISTRICT, decode, encode
from snowlight.live.cli import DEFAULT_CONFIG
from snowlight.live.overrides import DeployedSchools
from snowlight.notify import cli
from snowlight.notify.d1 import Secrets
from snowlight.notify.deliver import Clock
from snowlight.predict.serve import DeployedDirectory
from snowlight.schemas.live import ClosingsFile
from snowlight.schemas.predictions import PredictionsFile

EXAMPLES = Path(__file__).resolve().parents[1] / "schemas" / "examples"
IDS = ("000000000001", "000000000002", "000000000003", "000000000004", "A0000005", "A0000006")
DISTRICTS = ("1700001", "1700002")
DISTRICT_OF = (0, 0, 1, 1, None, None)
CHICAGO = "America/Chicago"
ENV = {"CLOUDFLARE_API_TOKEN": "tok", "CLOUDFLARE_ACCOUNT_ID": "acct", "CLOUDFLARE_API_URL": API}
CLOSINGS = (EXAMPLES / "synthetic-closings.json").read_bytes()
OPENS = (EXAMPLES / "synthetic-opens.json").read_bytes()
MADE = datetime(2027, 1, 12, 13, 5, tzinfo=UTC)  # 07:05 in Chicago


@pytest.fixture
def push() -> Iterator[PushService]:
    yield from serve_push()


def schools() -> DeployedSchools:
    stamp = ClosingsFile.from_json_bytes(CLOSINGS).directory
    return DeployedSchools(
        stamp=stamp,
        content_sha256="0" * 64,
        school_ids=IDS,
        district_ids=DISTRICTS,
        district_of=DISTRICT_OF,
        zones=(CHICAGO, CHICAGO),
        lon_e6=(-94_580_000, -94_570_000, -94_500_000, -94_490_000, -94_590_000, -94_600_000),
        lat_e6=(39_100_000, 39_110_000, 39_120_000, 39_130_000, 39_090_000, 39_080_000),
    )


def world(
    fake: FakeD1,
    *,
    now: datetime = MADE + timedelta(minutes=5),
    closings: bytes | None = CLOSINGS,
    opens: bytes | None = OPENS,
    env: dict[str, str] | None = None,
) -> cli.World:
    return cli.World(
        env=lambda: ENV if env is None else env,
        client=lambda: routed(fake),
        files=lambda _config, _env, _client: (closings, opens),
        schools=lambda _config, _env: schools(),
        clock=lambda: now,
        pause=0,
        loopback=True,
    )


ARGS = argparse.Namespace(config=DEFAULT_CONFIG)


def database() -> FakeD1:
    fake = FakeD1()
    migrate(fake.db)
    return fake


def opened(browser: Browser, body: bytes) -> dict[str, Any]:
    clear = http_ece.decrypt(
        body, private_key=browser.private, auth_secret=browser.auth, version="aes128gcm"
    )
    payload: dict[str, Any] = json.loads(clear)
    return payload


def signed_by(headers: dict[str, str], public: str) -> None:
    token = headers["Authorization"].removeprefix("vapid t=").split(", k=")[0]
    head, claims, signature = token.split(".")
    raw = b64d(signature)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64d(public))
    key.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def moved(text: bytes, at: datetime, drop_first_row_of_jan12: bool = False) -> bytes:
    """The example closings file written again at ``at`` (optionally without school 0's
    closing on Jan 12)."""
    value = json.loads(text)
    value["generated_at"] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    if drop_first_row_of_jan12:
        day = value["days"][0]
        day["gaps"] = [1, 0, 0, 1]
        for column in ("statuses", "announced", "reasons"):
            day[column] = day[column][1:]
    return json.dumps(value).encode()


def opens_for(at: datetime, school: int = 0, day: str = "2027-01-12") -> bytes:
    """An opens file written at ``at`` with one open statement."""
    value = json.loads(OPENS)
    value["generated_at"] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    value["opens"] = [
        {"at": stamp, "confidence": None, "day": day, "kind": "open", "school": school}
    ]
    return json.dumps(value).encode()


def blank(text: bytes, at: datetime) -> bytes:
    """The closings file blanked under the same stamp (``live blank``, a settled deployment
    that cannot be read): no status at all."""
    value = json.loads(text)
    value["generated_at"] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    value["days"] = []
    return json.dumps(value).encode()


def test_end_to_end_dry_run_against_a_stub_push_service(
    push: PushService, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = database()
    vapid = add_vapid(fake)
    phone = Browser.make(push.endpoint("phone"), 1)
    old = Browser.make(push.endpoint("old"), 2)
    push.answers["/push/old"] = 410
    add_user(fake, "u1", [(IDS[0], "Lincoln High"), (IDS[5], "Saint Ann")], [phone, old])
    add_user(
        fake, "u2", [(IDS[0], "Lincoln High")], [Browser.make(push.endpoint("off"))], disabled=True
    )
    add_user(
        fake,
        "u3",
        [(IDS[1], "Pine")],
        [Browser.make(push.endpoint("quiet"))],
        settings={"status": 0},
    )

    assert cli.run_status(ARGS, world(fake)) == 0
    line = capsys.readouterr().out
    assert "notify status: 3 due, 3 sent to 3 browsers, 0 failed, 1 subscriptions gone" in line

    paths = [path for path, _headers, _body in push.received]
    assert paths.count("/push/phone") == 3
    assert paths.count("/push/old") == 1, "a gone browser is not tried again"
    assert "/push/off" not in paths
    assert "/push/quiet" not in paths
    payloads = []
    for path, headers, body in push.received:
        if path != "/push/phone":
            continue
        signed_by(headers, vapid.public_key)
        assert headers["Urgency"] == "high"
        payloads.append(opened(phone, body))
    assert sorted((p["school"], p["day"], p["status"]) for p in payloads) == [
        (IDS[0], "2027-01-12", "closed"),
        (IDS[0], "2027-01-13", "closed"),
        (IDS[5], "2027-01-12", "early_dismissal"),
    ]
    early = next(p for p in payloads if p["status"] == "early_dismissal")
    assert early == {
        "v": 1,
        "school": IDS[5],
        "name": "Saint Ann",
        "day": "2027-01-12",
        "zone": CHICAGO,
        "kind": "status",
        "status": "early_dismissal",
        "shift": 180,
        "clock": 750,
    }
    assert fake.rows("SELECT endpoint FROM push_subscriptions WHERE user_id = 'u1'") == [
        (phone.endpoint,)
    ]
    assert len(fake.rows("SELECT * FROM notify_sent WHERE user_id = 'u1'")) == 3

    # The next pass, same file: nothing is sent twice.
    push.received.clear()
    later = MADE + timedelta(minutes=10)
    assert cli.run_status(ARGS, world(fake, now=later, closings=moved(CLOSINGS, later))) == 0
    assert push.received == []

    # School 0's closing on Jan 12 leaves the file: its source is held back, or the row
    # dropped, for 30 minutes of passes. Gone from the file is not lifted: nothing is sent,
    # and nothing again when the row comes back.
    for minutes in range(15, 50, 5):
        at = MADE + timedelta(minutes=minutes)
        file = moved(CLOSINGS, at, drop_first_row_of_jan12=True)
        assert cli.run_status(ARGS, world(fake, now=at, closings=file, opens=None)) == 0
    back = MADE + timedelta(minutes=50)
    assert cli.run_status(ARGS, world(fake, now=back, closings=moved(CLOSINGS, back))) == 0
    # A blanked file under the same stamp: nothing either, and nothing when it comes back.
    for minutes in (55, 60, 65, 70):
        at = MADE + timedelta(minutes=minutes)
        assert cli.run_status(ARGS, world(fake, now=at, closings=blank(CLOSINGS, at))) == 0
    again = MADE + timedelta(minutes=75)
    assert cli.run_status(ARGS, world(fake, now=again, closings=moved(CLOSINGS, again))) == 0
    assert push.received == []

    # An open statement for that school-day is what lifts it.
    at = MADE + timedelta(minutes=80)
    file = moved(CLOSINGS, at, drop_first_row_of_jan12=True)
    assert cli.run_status(ARGS, world(fake, now=at, closings=file, opens=opens_for(at))) == 0
    [(path, _headers, body)] = push.received
    lifted = opened(phone, body)
    assert (lifted["kind"], lifted["was"], lifted["open"], lifted["day"]) == (
        "lifted",
        "closed",
        True,
        "2027-01-12",
    )


def test_quiet_and_dark(push: PushService, capsys: pytest.CaptureFixture[str]) -> None:
    fake = database()
    assert cli.run_status(ARGS, world(fake, env={})) == 0
    assert capsys.readouterr().out == "notify: no Cloudflare secrets: nothing to send\n"

    bare = FakeD1()
    migrate(bare.db, skip=lambda name: name.startswith("0004"))
    assert cli.run_status(ARGS, world(bare)) == 0
    assert "tables are not there yet" in capsys.readouterr().out

    assert cli.run_status(ARGS, world(fake)) == 0
    assert capsys.readouterr().out == "notify: no browser gets notifications: nothing to send\n"
    queries = len(fake.statements)
    assert queries == 1, "zero subscriptions cost one query"

    add_user(fake, "u1", [(IDS[0], "Lincoln High")], [Browser.make(push.endpoint("a"))])
    assert cli.run_status(ARGS, world(fake)) == 0
    assert "no VAPID key pair yet" in capsys.readouterr().out
    add_vapid(fake)

    stale = MADE + timedelta(minutes=21)
    assert cli.run_status(ARGS, world(fake, now=stale)) == 0
    assert capsys.readouterr().out == "notify: the closings file is 21 min old: no status is sent\n"
    assert cli.run_status(ARGS, world(fake, closings=None)) == 0
    assert "no closings file" in capsys.readouterr().out
    assert cli.run_status(ARGS, world(fake, closings=b"{}")) == 0
    assert "does not validate" in capsys.readouterr().out
    other = json.loads(CLOSINGS)
    other["directory"]["generated_on"] = "2026-09-25"
    assert cli.run_status(ARGS, world(fake, closings=json.dumps(other).encode())) == 0
    assert "another directory" in capsys.readouterr().out
    assert push.received == []


def test_a_database_that_cannot_be_read_warns_and_never_fails_the_run(
    push: PushService, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = database()
    fake.fail = [500, 500]
    assert cli.run_status(ARGS, world(fake)) == 0
    out = capsys.readouterr().out
    assert out.startswith("::warning::notify: the pass stopped:")
    assert "HTTP 500" in out

    # A write that fails after sending: the run stays green, and the warning names no value.
    add_vapid(fake)
    phone = Browser.make(push.endpoint("phone"))
    add_user(fake, "u1", [(IDS[0], "Lincoln High")], [phone])
    real = fake.handle

    def no_writes(request: httpx.Request) -> httpx.Response:
        if b"INSERT INTO notify_sent" in request.content:
            return httpx.Response(400, json={"success": False, "errors": [{"code": 7500}]})
        return real(request)

    fake.handle = no_writes  # type: ignore[method-assign]
    assert cli.run_status(ARGS, world(fake)) == 0
    out = capsys.readouterr().out
    assert out.startswith("::warning::notify: the pass stopped:")
    assert phone.endpoint not in out
    assert "Lincoln" not in out
    assert len(push.received) == 2


def test_an_account_deleted_mid_pass_keeps_the_others_log(push: PushService) -> None:
    fake = database()
    add_vapid(fake)
    for n in range(20):
        add_user(
            fake, f"u{n:02}", [(IDS[0], "Lincoln High")], [Browser.make(push.endpoint(f"{n}"))]
        )
    real = fake.handle
    deleted = False

    def delete_on_first_write(request: httpx.Request) -> httpx.Response:
        nonlocal deleted
        if not deleted and b"INSERT INTO notify_sent" in request.content:
            deleted = True
            for table in ("push_subscriptions", "notify_settings", "notify_sent", "sessions"):
                fake.db.execute(f"DELETE FROM {table} WHERE user_id = 'u03'")  # noqa: S608 - test
            fake.db.execute("DELETE FROM users WHERE id = 'u03'")
            fake.db.commit()
        return real(request)

    fake.handle = delete_on_first_write  # type: ignore[method-assign]
    assert cli.run_status(ARGS, world(fake)) == 0
    assert deleted
    users = {row[0] for row in fake.rows("SELECT DISTINCT user_id FROM notify_sent")}
    assert users == {f"u{n:02}" for n in range(20)} - {"u03"}
    # The next pass sends nothing again.
    push.received.clear()
    assert cli.run_status(ARGS, world(fake)) == 0
    assert push.received == []


def test_only_browsers_whose_sign_in_lasts_get_pushes(push: PushService) -> None:
    fake = database()
    add_vapid(fake)
    now = MADE + timedelta(minutes=5)
    ended = int(now.timestamp() * 1000) - 1
    add_user(
        fake,
        "u1",
        [(IDS[0], "Lincoln High")],
        [Browser.make(push.endpoint("over"))],
        signed_in_until=ended,
    )
    add_user(
        fake,
        "u2",
        [(IDS[0], "Lincoln High")],
        [Browser.make(push.endpoint("on"))],
        signed_in_until=SIGNED_IN_UNTIL,
    )
    assert cli.run_status(ARGS, world(fake, now=now)) == 0
    assert {path for path, _h, _b in push.received} == {"/push/on"}


def test_a_push_service_that_keeps_refusing_loses_the_browser(push: PushService) -> None:
    fake = database()
    add_vapid(fake)
    stale = Browser.make(push.endpoint("stale"), 1)
    fine = Browser.make(push.endpoint("fine"), 2)
    push.answers["/push/stale"] = 403
    add_user(fake, "u1", [(IDS[0], "Lincoln High")], [stale, fine])

    def failures() -> list[tuple[str, int]]:
        return [
            (str(row[0]).rsplit("/", 1)[-1], int(row[1]))
            for row in fake.rows(
                "SELECT endpoint, failures FROM push_subscriptions ORDER BY endpoint"
            )
        ]

    # Each pass with a push due counts one refusal; the log is cleared to make one due.
    def a_pass(at: datetime) -> None:
        fake.db.execute("DELETE FROM notify_sent")
        fake.db.commit()
        assert cli.run_status(ARGS, world(fake, now=at, closings=moved(CLOSINGS, at))) == 0

    start = MADE + timedelta(minutes=5)
    for n in range(12):
        a_pass(start + timedelta(minutes=5 * n))
    assert failures() == [("fine", 0), ("stale", 12)], "kept until the refusals span a day"
    # The first refusal a day back: the next refusal deletes the browser.
    fake.db.execute("UPDATE push_subscriptions SET failing_since = failing_since - 86400000")
    fake.db.commit()
    a_pass(start + timedelta(minutes=60))
    assert failures() == [("fine", 0)]
    # A browser that takes a push again starts over.
    push.answers["/push/fine"] = 400
    a_pass(start + timedelta(minutes=65))
    assert failures() == [("fine", 1)]
    push.answers["/push/fine"] = 201
    a_pass(start + timedelta(minutes=70))
    assert failures() == [("fine", 0)]


def test_the_command_is_registered() -> None:
    args = main_cli.build_parser().parse_args(["notify", "status"])
    assert args.handler is cli.run_status


def directory() -> DeployedDirectory:
    stamp = PredictionsFile.from_json_bytes(
        (EXAMPLES / "synthetic-predictions.json").read_bytes()
    ).directory
    points = decode(
        encode(
            [-94_580_000 + i for i in range(6)],
            [39_100_000 + i for i in range(6)],
            [NO_DISTRICT if d is None else d for d in DISTRICT_OF],
            [0, 0, 0, 0, 1, 1],
            len(DISTRICTS),
        )
    )
    return DeployedDirectory(stamp, DISTRICTS, points, school_ids=IDS)


def test_chance_notifier_end_to_end(push: PushService) -> None:
    fake = database()
    add_vapid(fake)
    phone = Browser.make(push.endpoint("phone"))
    add_user(
        fake,
        "u1",
        [(IDS[0], "Lincoln High"), (IDS[4], "Saint Ann"), (IDS[2], "Oak")],
        [phone],
        settings={"night_before": 1, "night_time": "17:00"},
    )
    file = PredictionsFile.from_json_bytes((EXAMPLES / "synthetic-predictions.json").read_bytes())
    notifier = cli.ChanceNotifier(
        secrets=Secrets(token="tok", account="acct", api=API),  # noqa: S106 - a test token
        client=routed(fake),
        closings=lambda: None,
        pause=0,
        loopback=True,
    )
    # 17:07 in Chicago on Jan 11: tomorrow is Jan 12 (school 0's district 62%, Saint Ann 1%,
    # Oak's district no school day).
    evening = datetime(2027, 1, 11, 23, 7, tzinfo=UTC)
    line = notifier(file, directory(), evening)
    assert line.startswith("notify chance: 1 due, 1 sent")
    [(_path, headers, body)] = push.received
    assert headers["Urgency"] == "normal"
    payload = opened(phone, body)
    assert (payload["kind"], payload["school"], payload["percent"], payload["day"]) == (
        "night",
        IDS[0],
        62,
        "2027-01-12",
    )
    kinds = fake.rows("SELECT kind, value FROM notify_sent ORDER BY kind")
    assert kinds == [("chance", "62"), ("night", "62")]
    push.received.clear()
    assert notifier(file, directory(), evening + timedelta(minutes=30)).startswith(
        "notify chance: 0 due"
    )
    assert push.received == []
    # A closing already shown for that day stops any chance push.
    fake.db.execute("DELETE FROM notify_sent")
    fake.db.commit()
    closed = json.loads(CLOSINGS)
    closed["generated_at"] = "2027-01-11T23:00:00Z"
    closed["days"] = [{**closed["days"][0], "day": "2027-01-12"}]
    shown = replace(notifier, closings=lambda: json.dumps(closed).encode())
    assert shown(file, directory(), evening).startswith("notify chance: 0 due")


def test_the_deadline_leaves_pushes_for_the_next_pass(push: PushService) -> None:
    fake = database()
    add_vapid(fake)
    add_user(fake, "u1", [(IDS[0], "Lincoln High")], [Browser.make(push.endpoint("p"))])
    over = world(fake)
    ticks = iter([0.0, 0.0, 1e9, 1e9])
    over.deadline = lambda: Clock(seconds=10, monotonic=lambda: next(ticks))
    assert cli.run_status(ARGS, over) == 0
    assert len(push.received) == 1
    assert len(fake.rows("SELECT * FROM notify_sent")) == 1

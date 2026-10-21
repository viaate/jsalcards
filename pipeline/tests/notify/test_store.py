"""The database side: D1 over the Cloudflare API (found by name, values bound, retried once,
errors that name only a status), and the sender's reads and writes against the API's own
migrations. Every account here is SYNTHETIC."""

import sqlite3
from datetime import date, time

import httpx
import pytest

from notify.fakes import (
    SECRETS,
    Browser,
    FakeD1,
    add_user,
    add_vapid,
    d1,
    migrate,
    routed,
)
from snowlight.notify import store
from snowlight.notify.d1 import D1, D1Error, NoTablesError, Secrets
from snowlight.notify.rules import Record, School, SentKey, Settings


def fake(*, with_0004: bool = True) -> FakeD1:
    found = FakeD1()
    migrate(found.db, skip=lambda name: not with_0004 and name.startswith("0004"))
    return found


def test_secrets_from_the_environment() -> None:
    assert Secrets.from_env({}) is None
    assert Secrets.from_env({"CLOUDFLARE_API_TOKEN": "t"}) is None
    found = Secrets.from_env({"CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "a"})
    assert found == Secrets(token="t", account="a")  # noqa: S106 - a test token


def test_finds_the_database_by_name_and_binds_every_value() -> None:
    world = fake()
    db = d1(world)
    assert db.query("SELECT ?1 + ?2 AS n", (2, 3)) == [{"n": 5}]
    assert world.params[-1] == [2, 3]
    with pytest.raises(ValueError, match="100"):
        db.query("SELECT 1", list(range(101)))


def test_no_such_database() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "result": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(D1Error, match="no database"):
        D1.find(client, SECRETS, pause=0)


def test_asks_again_once_after_a_5xx_then_names_only_the_status() -> None:
    world = fake()
    db = d1(world)
    world.fail = [503]
    assert db.query("SELECT 1 AS one") == [{"one": 1}]
    world.fail = [502, 502]
    with pytest.raises(D1Error) as caught:
        db.query("SELECT 'secret-value' AS x")
    assert str(caught.value) == "the Cloudflare API answered HTTP 502"
    world.fail = [403]
    with pytest.raises(D1Error, match="HTTP 403"):
        db.query("SELECT 1")


NOW_MS = 1_800_000_000_000


def test_tables_not_there_yet() -> None:
    db = d1(fake(with_0004=False))
    with pytest.raises(NoTablesError):
        store.subscription_count(db, NOW_MS)


def test_reads_accounts_with_browsers_settings_and_schools() -> None:
    world = fake()
    a, b = (
        Browser.make("https://fcm.googleapis.com/a", 1),
        Browser.make("https://fcm.googleapis.com/b", 2),
    )
    add_user(world, "u1", [("360000000001", "Lincoln High")], [a, b])
    add_user(
        world,
        "u2",
        [("060000000002", "Pine Elementary"), ("A0000005", "  Saint Ann  ")],
        [Browser.make("https://fcm.googleapis.com/c", 3)],
        settings={"threshold": 70, "night_before": 1, "night_time": "19:30", "chance": 0},
    )
    add_user(
        world,
        "u3",
        [("360000000001", "Lincoln High")],
        [Browser.make("https://fcm.googleapis.com/d")],
        disabled=True,
    )
    add_user(world, "u4", [("360000000001", "Lincoln High")])
    add_user(
        world,
        "u5",
        [("360000000001", "Lincoln High")],
        [Browser.make("https://fcm.googleapis.com/e")],
        signed_in_until=NOW_MS,
    )
    db = d1(world)
    assert store.subscription_count(db, NOW_MS) == 3
    accounts = {account.user_id: account for account in store.read_accounts(db, NOW_MS)}
    assert set(accounts) == {"u1", "u2"}, "not disabled, not signed out"
    assert [s.endpoint for s in accounts["u1"].subscriptions] == [a.endpoint, b.endpoint]
    assert accounts["u1"].settings == Settings()
    assert accounts["u2"].settings == Settings(
        chance=False, threshold=70, night_before=True, night_time=time(19, 30)
    )
    assert accounts["u2"].schools == (
        School("060000000002", "Pine Elementary"),
        School("A0000005", "Saint Ann"),
    )


def test_schools_that_do_not_read_are_none() -> None:
    assert store.schools_of("not json") == ()
    assert store.schools_of('{"id": "x"}') == ()
    assert store.schools_of('[{"id": 1, "name": "x"}, {"id": "y", "name": ""}]') == ()
    many = "[" + ",".join(f'{{"id": "{i}", "name": "S{i}"}}' for i in range(9)) + "]"
    assert len(store.schools_of(many)) == store.MAX_SCHOOLS


def test_the_vapid_pair_once_both_rows_are_there() -> None:
    world = fake()
    db = d1(world)
    assert store.read_vapid(db) is None
    made = add_vapid(world)
    found = store.read_vapid(db)
    assert found is not None
    assert found.public_key == made.public_key
    world.db.execute("UPDATE settings SET value = 'AAAA' WHERE name = 'vapid_private'")
    world.db.commit()
    assert store.read_vapid(db) is None


def test_the_log_is_written_in_bound_batches_and_newer_values_replace_older() -> None:
    world = fake()
    add_user(world, "u1", [])
    db = d1(world)
    records = [
        Record(SentKey("u1", f"{i:012d}", "status", date(2027, 1, 12)), "closed") for i in range(40)
    ]
    assert store.write_sent(db, records, 1000) == 40
    assert all(len(params) <= 100 for params in world.params)
    store.write_sent(db, [Record(records[0].key, "none")], 2000)
    sent = store.read_sent(db, date(2027, 1, 11))
    assert len(sent) == 40
    assert sent[records[0].key] == "none"
    assert store.read_sent(db, date(2027, 1, 13)) == {}
    store.prune_sent(db, date(2027, 1, 13))
    assert world.rows("SELECT COUNT(*) FROM notify_sent") == [(0,)]


def test_the_log_leaves_out_an_account_that_is_gone_and_keeps_the_rest() -> None:
    world = fake()
    add_user(world, "u1", [])
    add_user(world, "u2", [])
    db = d1(world)
    day = date(2027, 1, 12)
    rows = [
        Record(SentKey(u, "000000000001", "status", day), "closed#1") for u in ("u1", "u9", "u2")
    ]
    assert store.write_sent(db, rows, 1000) == 3
    assert world.rows("SELECT user_id FROM notify_sent ORDER BY user_id") == [("u1",), ("u2",)]


def test_gone_subscriptions_are_deleted_and_the_log_row_kind_is_checked() -> None:
    world = fake()
    browsers = [Browser.make(f"https://fcm.googleapis.com/{i}") for i in range(3)]
    add_user(world, "u1", [], browsers)
    db = d1(world)
    store.delete_subscriptions(db, [browsers[0].endpoint, browsers[2].endpoint])
    assert world.rows("SELECT endpoint FROM push_subscriptions") == [(browsers[1].endpoint,)]
    with pytest.raises(sqlite3.IntegrityError):
        world.db.execute(
            "INSERT INTO notify_sent VALUES ('u1', 's', 'other', '2027-01-12', 'x', 1)"
        )


def test_routed_client_reaches_the_fake_only_for_cloudflare() -> None:
    world = fake()
    seen: list[str] = []

    def push(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(201)

    client = routed(world, push)
    assert client.post("https://fcm.googleapis.com/x").status_code == 201
    assert seen == ["https://fcm.googleapis.com/x"]

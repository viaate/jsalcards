"""The outlook's product log rebuild (S7-F F3): it reads the heads-ups' products as well as the
classes', in a read of its own apart from the alert memory's, within the outlook's time for
reads; a rebuild that fails in the record step backs off instead of holding pass after pass;
and with the outlook on the pass starts that time once. SYNTHETIC products only."""

import json
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest

from predict import night, world
from predict.test_publish import MemoryHost, make_pass
from snowlight.predict import cli
from snowlight.predict.inputs import (
    HEADS_UP_EVENTS,
    HISTORY_EVENTS,
    PRODUCT_EVENTS,
    AlertsHistory,
)
from snowlight.predict.outlook import OutlookMode
from snowlight.predict.outlook_live import Budget
from snowlight.predict.publish import Dark, DarkError, Mode
from snowlight.predict.situations import CLASS_BY_CODE, HEADS_UP_BY_CODE, HeadsUp
from snowlight.sources.nws.alerts import NwsAlert, parse_active
from snowlight.weather.hazards import ALERT_TYPES

NOW = world.utc("2026-01-07T02:10")
"""8:10 PM in Kansas City: the 8 PM sample hour is due, within its 15 minutes of grace."""
SAMPLE = world.utc("2026-01-07T02:00")
WATCH_SPAN = "260107T1200Z-260108T0000Z"


def watch(action: str, sent: str) -> dict[str, Any]:
    """SYNTHETIC: one winter storm watch product for the Kansas City zone."""
    return world.feature(
        f"/O.{action}.KEAX.WS.A.0007.{WATCH_SPAN}/",
        ("MOZ028",),
        sent=sent,
        onset="2026-01-07T12:00:00+00:00",
        ends="2026-01-08T00:00:00+00:00",
        event="Winter Storm Watch",
    )


def alerts(features: list[dict[str, Any]]) -> list[NwsAlert]:
    return list(parse_active(world.feed_bytes(features, NOW.isoformat())).alerts)


FIRST = watch("NEW", "2026-01-06T21:00:00+00:00")
"""The watch as issued at 3 PM: it stood at the 8 PM sample hour."""
LATER = watch("CON", "2026-01-07T02:05:00+00:00")
"""Its next product, sent at 8:05 PM: the only one the active feed still holds at 8:10 PM."""


def heads_up_at(log: Any, at: datetime) -> set[HeadsUp]:
    return {item.event.heads_up for item in log.events_at(at)} - {HeadsUp.NONE}


def test_the_product_log_s_read_names_every_heads_up_and_the_memory_s_stays_as_it_was() -> None:
    codes = {
        f"{p}.{s}" for kind in ALERT_TYPES if kind.event in HEADS_UP_EVENTS for p, s in kind.codes
    }
    assert set(HEADS_UP_BY_CODE) <= codes  # every heads-up code, retired ones too
    assert not codes & set(CLASS_BY_CODE)
    assert PRODUCT_EVENTS == HISTORY_EVENTS + HEADS_UP_EVENTS
    assert "Winter Storm Watch" not in HISTORY_EVENTS
    asked: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, content=world.feed_bytes([FIRST], NOW.isoformat()))

    reader = AlertsHistory(httpx.Client(transport=httpx.MockTransport(handler)))
    found = reader.read(NOW - timedelta(hours=30), NOW, events=PRODUCT_EVENTS)
    assert [alert.event for alert in found] == ["Winter Storm Watch"]
    assert asked[0].url.params["event"].split(",") == list(PRODUCT_EVENTS)
    reader.read(NOW - timedelta(hours=30), NOW)
    assert asked[1].url.params["event"].split(",") == list(HISTORY_EVENTS)


def test_the_product_log_s_read_stops_before_a_page_once_its_time_is_up() -> None:
    asked: list[str] = []
    following = "https://api.weather.gov/alerts?cursor=2"

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        body = json.loads(
            world.feed_bytes([FIRST] if len(asked) == 1 else [LATER], NOW.isoformat())
        )
        body["pagination"] = {"next": following + str(len(asked))}
        return httpx.Response(200, content=json.dumps(body).encode())

    reader = AlertsHistory(httpx.Client(transport=httpx.MockTransport(handler)))
    left = iter([True, False])
    with pytest.raises(DarkError) as raised:
        reader.read(NOW - timedelta(hours=30), NOW, before=lambda: next(left))
    assert raised.value.reason is Dark.MEMORY
    assert len(asked) == 1  # the first page, then no request once the time was up
    with pytest.raises(DarkError):
        reader.read(NOW - timedelta(hours=30), NOW, before=lambda: False)
    assert len(asked) == 1


def shadow_pass(product_history: Any) -> cli.Pass:
    """A shadow pass at 8:10 PM over a feed holding only the watch's 8:05 PM product, with no
    product log yet (the first shadow pass after landing); the alert memory's history holds
    the classes' products alone, as its event filter reads them."""
    host = MemoryHost()
    run = make_pass(host, mode=Mode.ON, directory=world.directory(), now=NOW)
    run.alerts = lambda: (parse_active(world.feed_bytes([LATER], NOW.isoformat())), True)
    run.history = lambda _start, _end: []
    run.product_history = product_history
    night.with_outlook(OutlookMode.SHADOW)(run)
    return run


def test_a_rebuilt_product_log_holds_a_watch_that_only_the_history_still_has() -> None:
    spans: list[tuple[datetime, datetime]] = []

    def product_history(start: datetime, end: datetime) -> list[NwsAlert]:
        spans.append((start, end))
        return alerts([FIRST])

    run = shadow_pass(product_history)
    log = cli.remember_products(run, run.alerts()[0], NOW, NOW - timedelta(hours=6))
    assert len(spans) == 1
    assert heads_up_at(log, SAMPLE) == {HeadsUp.WINTER_STORM_WATCH}
    # Without the heads-ups' products the rebuilt log says no heads-up stood at 8 PM.
    bare = shadow_pass(None)
    log = cli.remember_products(bare, bare.alerts()[0], NOW, NOW - timedelta(hours=6))
    assert heads_up_at(log, SAMPLE) == set()
    assert heads_up_at(log, NOW) == {HeadsUp.WINTER_STORM_WATCH}


def test_the_record_step_records_the_watch_through_a_rebuild(capsys: Any) -> None:
    run = shadow_pass(lambda _start, _end: alerts([FIRST]))
    assert cli.one_pass(run) == 0
    assert "nothing recorded" not in capsys.readouterr().err
    assert run.state.products_observed == NOW
    assert run.state.outlook is not None


def test_a_record_step_whose_rebuild_fails_backs_off_and_never_touches_the_pass(
    capsys: Any,
) -> None:
    asked: list[datetime] = []

    def down(_start: datetime, end: datetime) -> list[NwsAlert]:
        asked.append(end)
        raise DarkError(Dark.MEMORY, "alert history: HTTP 503")

    run = shadow_pass(down)
    clock = [NOW]
    run.now = lambda: clock[0]
    run.alerts = lambda: (
        parse_active(world.feed_bytes([LATER], (clock[0] - timedelta(minutes=1)).isoformat())),
        True,
    )
    for minutes in (0, 10, 20, 29, 30, 40):
        clock[0] = NOW + timedelta(minutes=minutes)
        assert cli.one_pass(run) == 0  # never dark
    # A try at 8:10, none for 30 minutes, again at 8:40 (8:50 backs off from it).
    assert asked == [NOW, NOW + timedelta(minutes=30)]
    err = capsys.readouterr().err
    assert err.count("nothing recorded") == 6
    assert "no new try before 02:40Z" in err
    assert run.state.products_observed is None
    # A rebuild that works clears the back-off.
    run.product_history = lambda _start, _end: alerts([FIRST])
    clock[0] = NOW + timedelta(minutes=70)
    assert cli.one_pass(run) == 0
    assert run.state.products_observed == clock[0]


class CountingBudget(Budget):
    starts: int = 0

    def start(self) -> None:
        self.starts += 1
        super().start()


@pytest.mark.parametrize("mode", [OutlookMode.SHADOW, OutlookMode.ON])
def test_a_pass_starts_the_outlook_s_time_once(mode: OutlookMode) -> None:
    host = MemoryHost()
    run = make_pass(host, mode=Mode.ON, directory=world.directory(), now=NOW)
    run.alerts = lambda: (parse_active(world.feed_bytes([LATER], NOW.isoformat())), True)
    run.product_history = lambda _start, _end: alerts([FIRST])
    night.with_outlook(mode)(run)
    budget = CountingBudget()
    run.outlook_budget = budget
    assert cli.one_pass(run) == 0
    assert budget.starts == 1
    run.now = lambda: NOW + timedelta(minutes=5)
    assert cli.one_pass(run) == 0
    assert budget.starts == 2

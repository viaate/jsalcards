"""GF9 on the serving path (S7-F F3): the pass's product log, polled through the night, rebuilds
the class issued and the heads-up at 20:00, 22:15 and 05:00 exactly as the history rows count
them under rule D2, heads-ups included; the 05:00 record a pass takes late is that exact
replay. SYNTHETIC rows and features only, in a Kansas City zone (America/Chicago)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from predict import world
from predict.test_outlook_rule import DAY, KC, WINDOW, local, season_csv, stamp, vtec_time
from snowlight.predict.alerts_history import read_season
from snowlight.predict.alerts_live import (
    OUTLOOK_CODES,
    Memory,
    ProductLog,
    UgcIndex,
    live_events,
    withdrawn,
)
from snowlight.predict.outlook_record import Record
from snowlight.predict.outlook_serve import district_states
from snowlight.predict.outlook_states import INDEX_OF, MOMENTS
from snowlight.predict.serve import build_model, unit_classes
from snowlight.predict.situations import (
    HEADS_UP_BY_CODE,
    HeadsUp,
    WeatherClass,
    school_state,
)
from snowlight.sources.nws.alerts import parse_active

LABELS = ("20:00", "22:15", "05:00")
EVENTS = {"WS.W": "Winter Storm Warning", "WS.A": "Winter Storm Watch",
          "WW.Y": "Winter Weather Advisory", "EC.A": "Extreme Cold Watch",
          "CW.Y": "Cold Weather Advisory"}  # fmt: skip


@dataclass(frozen=True)
class Product:
    """One SYNTHETIC product: its code, event number, action, when it was sent, its span."""

    code: str
    etn: int
    action: str
    sent: datetime
    start: datetime
    end: datetime

    def feature(self) -> dict[str, Any]:
        span = f"{vtec_time(self.start)}-{vtec_time(self.end)}"
        vtec = f"/O.{self.action}.KEAX.{self.code}.{self.etn:04d}.{span}/"
        return world.feature(
            vtec, ("MOZ028",), sent=self.sent.isoformat(), onset=self.start.isoformat(),
            ends=self.end.isoformat(), event=EVENTS[self.code],
            message_type="Cancel" if self.action == "CAN" else "Alert",
        )  # fmt: skip


def history_rows(rows: list[dict[str, str]]) -> list[Any]:
    """The season file's rows of both code tables."""
    text = season_csv(rows)
    return read_season(text, 2024) + read_season(text, 2024, codes=HEADS_UP_BY_CODE.keys())


def row_of(  # noqa: PLR0913, PLR0917 - one history row's fields
    code: str, etn: int, status: str, issued: datetime, start: datetime, end: datetime,
    final: datetime,
) -> dict[str, str]:  # fmt: skip
    phenomena, significance = code.split(".")
    return {
        "phenomena": phenomena, "significance": significance, "status": status,
        "eventid": str(etn), "utc_issue": stamp(start), "utc_expire": stamp(final),
        "utc_prodissue": stamp(issued), "utc_init_expire": end.strftime("%Y%m%d%H%M"),
    }  # fmt: skip


def polled(products: list[Product], until: datetime) -> ProductLog:
    """The product log of passes polling the feed every 5 minutes from noon D-1 to ``until``:
    each poll's feed holds every product sent by then."""
    log = ProductLog(30)
    moment = local("12:00")
    while moment <= until:
        alerts = parse_active(
            world.feed_bytes(
                [p.feature() for p in products if p.sent <= moment], moment.isoformat()
            )
        ).alerts
        log.take(alerts, moment)
        moment += timedelta(minutes=5)
    return log


def both(history: list[Any], log: ProductLog, label: str) -> tuple[Any, Any]:
    at = MOMENTS[INDEX_OF[label]].at(DAY, KC)
    from_history = school_state([item.event_issued(at) for item in history], DAY, KC, WINDOW, at)
    from_live = school_state([event.event for event in log.events_at(at)], DAY, KC, WINDOW, at)
    return from_history, from_live


START, END = local("23:00"), local("12:00", before=False)
MORNING = local("06:00", before=False)


@pytest.mark.parametrize(
    ("cancel", "action"),
    [("19:30", "CAN"), ("23:30", "CAN"), ("19:30", "UPG"), ("23:30", "UPG")],
)
def test_a_warning_cancelled_or_upgraded_replays_as_the_history_counts_it(
    cancel: str, action: str
) -> None:
    issued, taken = local("15:00"), local(cancel)
    history = history_rows([row_of("WS.W", 1, action, issued, START, END, taken)])
    products = [
        Product("WS.W", 1, "NEW", issued, START, END),
        Product("WS.W", 1, action, taken, START, END),
    ]
    log = polled(products, MORNING)
    for label in LABELS:
        from_history, from_live = both(history, log, label)
        assert from_history == from_live, (cancel, action, label)


def test_a_watch_cancelled_after_its_start_replays_alike() -> None:
    issued, start = local("10:00"), local("21:00")
    taken = local("01:00", before=False)
    history = history_rows([row_of("WS.A", 3, "CAN", issued, start, END, taken)])
    products = [
        Product("WS.A", 3, "NEW", issued, start, END),
        Product("WS.A", 3, "CAN", taken, start, END),
    ]
    log = polled(products, MORNING)
    found = {label: both(history, log, label) for label in LABELS}
    assert found["20:00"][0] == found["20:00"][1] == (WeatherClass.NONE, HeadsUp.WINTER_STORM_WATCH)
    assert found["22:15"][0] == found["22:15"][1]
    assert found["05:00"][0] == found["05:00"][1] == (WeatherClass.NONE, HeadsUp.NONE)


def test_a_watch_cancelled_at_seven_thirty_for_three_am_replays_alike() -> None:
    issued, start = local("09:00"), local("03:00", before=False)
    taken = local("19:30")
    history = history_rows([row_of("WS.A", 4, "CAN", issued, start, END, taken)])
    products = [
        Product("WS.A", 4, "NEW", issued, start, END),
        Product("WS.A", 4, "CAN", taken, start, END),
    ]
    log = polled(products, MORNING)
    for label in LABELS:
        from_history, from_live = both(history, log, label)
        assert from_history == from_live == (WeatherClass.NONE, HeadsUp.NONE), label
    seven = local("19:00")
    assert school_state([e.event for e in log.events_at(seven)], DAY, KC, WINDOW, seven) == (
        WeatherClass.NONE,
        HeadsUp.WINTER_STORM_WATCH,
    )


def test_an_extreme_cold_watch_that_becomes_a_cold_weather_advisory_replays_alike() -> None:
    issued, switched = local("11:00"), local("22:00")
    start, end = local("02:00", before=False), local("10:00", before=False)
    history = history_rows(
        [
            row_of("EC.A", 5, "UPG", issued, start, end, switched),
            row_of("CW.Y", 6, "EXP", switched, start, end, end),
        ]
    )
    products = [
        Product("EC.A", 5, "NEW", issued, start, end),
        Product("EC.A", 5, "UPG", switched, start, end),
        Product("CW.Y", 6, "NEW", switched, start, end),
    ]
    log = polled(products, MORNING)
    expected = {
        "20:00": (WeatherClass.NONE, HeadsUp.EXTREME_COLD_WATCH),
        "22:15": (WeatherClass.NONE, HeadsUp.COLD_WEATHER_ADVISORY),
        "05:00": (WeatherClass.NONE, HeadsUp.COLD_WEATHER_ADVISORY),
    }
    for label, want in expected.items():
        assert both(history, log, label) == (want, want), label


def test_a_warning_downgraded_to_an_advisory_replays_alike() -> None:
    issued, downgraded = local("15:00"), local("22:00")
    history = history_rows(
        [
            row_of("WS.W", 1, "CAN", issued, START, END, downgraded),
            row_of("WW.Y", 2, "EXP", downgraded, START, END, END),
        ]
    )
    products = [
        Product("WS.W", 1, "NEW", issued, START, END),
        Product("WS.W", 1, "CAN", downgraded, START, END),
        Product("WW.Y", 2, "NEW", downgraded, START, END),
    ]
    log = polled(products, MORNING)
    expected = {
        "20:00": WeatherClass.SNOW_WARNING,
        "22:15": WeatherClass.ADVISORY,
        "05:00": WeatherClass.ADVISORY,
    }
    for label, want in expected.items():
        from_history, from_live = both(history, log, label)
        assert from_history[0] is from_live[0] is want, label


def test_a_late_five_am_record_is_the_exact_replay_of_five_am() -> None:
    # An advisory issued at 15:00, cancelled at 05:20: the 05:00 record a pass takes at 05:40
    # still holds it (later withdrawals are not applied), as the history replays it.
    issued, taken = local("15:00"), local("05:20", before=False)
    history = history_rows([row_of("WW.Y", 9, "CAN", issued, START, END, taken)])
    products = [
        Product("WW.Y", 9, "NEW", issued, START, END),
        Product("WW.Y", 9, "CAN", taken, START, END),
    ]
    late = local("05:40", before=False)
    log = polled(products, late)
    from_history, from_live = both(history, log, "05:00")
    assert from_history == from_live == (WeatherClass.ADVISORY, HeadsUp.NONE)
    now = school_state([e.event for e in log.events_at(late)], DAY, KC, WINDOW, late)
    assert now == (WeatherClass.NONE, HeadsUp.NONE)
    # The pass at 05:40 takes the record as of 05:00 exactly (outlook_live.take_record).
    from predict.night import fake_forecast, outlook_model  # noqa: PLC0415
    from snowlight.predict.outlook_live import take_record  # noqa: PLC0415
    from snowlight.predict.outlook_serve import OutlookServe  # noqa: PLC0415

    rates, table = outlook_model()
    model = build_model(world.directory(), rates, world.CONFIG, lambda _x, _y: None)
    serve = OutlookServe.of(model, table)
    lon, lat = world.lon_lat()
    record = Record("content", len(world.DISTRICTS))
    take_record(
        record,
        serve=serve,
        log=log,
        ugcs=UgcIndex.build(lon, lat, world.ugc_areas()),
        days=[DAY],
        now=late,
        window=WINDOW,
        share=0.5,
        read=fake_forecast(),
        published=None,
        chances=None,
    )
    morning = record.days[DAY].morning
    assert morning is not None
    missouri = [i for i, leaid in enumerate(world.DISTRICTS) if leaid.startswith("29")]
    assert all(int(morning.values[i]) == WeatherClass.ADVISORY for i in missouri)


def test_the_log_at_now_agrees_with_the_live_memory_on_every_pass_of_a_night() -> None:
    """Rule D2 at the moment now is the shipped live rule: over the SYNTHETIC night, the
    class each district gets from the product log equals the pass's own, every pass."""
    from predict import night  # noqa: PLC0415

    model = build_model(world.directory(), world.model(), world.CONFIG, lambda _x, _y: None)
    lon, lat = world.lon_lat()
    ugcs = UgcIndex.build(lon, lat, world.ugc_areas())
    memory = Memory(30)
    log = ProductLog(30)
    days = [DAY.replace(year=2026, month=1, day=7)]
    for now in night.times():
        feed = night.feed_at(now)
        counted = memory.update(live_events(feed), now, withdrawn(feed.alerts))
        log.take(feed.alerts, now)
        classes, _private = unit_classes(model, counted, ugcs, days, now, WINDOW, 0.5)
        c0, _heads = district_states(model, log.events_at(now), ugcs, days, now, WINDOW, 0.5)
        assert np.array_equal(classes, c0), now


def test_the_log_keeps_withdrawals_and_heads_ups_and_round_trips() -> None:
    issued, taken = local("15:00"), local("19:30")
    products = [
        Product("WS.A", 1, "NEW", issued, START, END),
        Product("WS.A", 1, "CAN", taken, START, END),
    ]
    log = polled(products, local("20:00"))
    assert {p.code for p in log.products.values()} == {"WS.A"}
    assert any(p.withdraws for p in log.products.values())
    back = ProductLog.from_json(30, log.as_json())
    assert back.products == log.products
    assert back.events_at(local("19:00")) == log.events_at(local("19:00"))
    # Products last seen over 30 hours before are forgotten.
    log.take([], local("20:00") + timedelta(hours=31))
    assert not log.products
    assert set(OUTLOOK_CODES) >= {"WS.A", "CW.Y", "WS.W"}
    # An entry that does not read is left out, never guessed.
    assert not ProductLog.from_json(30, [{"key": "x"}]).products
    assert datetime.now(UTC) > issued

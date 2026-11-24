"""The Flights trip alerts (snowlight.notify.flights, flights spec D12) on SYNTHETIC files and a
SYNTHETIC accounts database: every chance, FAA program, waiver, trip, account and browser here is
made up. A simulated day checks that each change is said once."""

import argparse
import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, get_args
from zoneinfo import ZoneInfo

import httpx
import pytest

from notify.fakes import SECRETS, Browser, FakeD1, add_user, add_vapid, d1, migrate, routed
from snowlight.notify import flights as fl
from snowlight.notify.flights_rules import (
    ALERT_BACKUPS,
    ALERT_CARRIED,
    BACKUP_LEAD,
    SAFER_POINTS,
    Airport,
    Choices,
    Kind,
    Leg,
    Plan,
    PlanKind,
    Sent,
    Told,
    Trip,
    World,
    alerts_for,
    backup_plans,
    departs,
    level_of,
    plan_chance,
    rank_key,
    shown,
    trip_leg,
)
from snowlight.notify.rules import Subscription
from snowlight.notify.webpush import Delivery, Message
from snowlight.schemas.flights import FlightsLive, FlightsRoutes

AIRPORTS = {
    "MCI": Airport("MCI", "America/Chicago", 39.2976, -94.7139, 160),
    "LAX": Airport("LAX", "America/Los_Angeles", 33.9425, -118.4081, 600),
    "BUR": Airport("BUR", "America/Los_Angeles", 34.2007, -118.3585, 120),
    "DEN": Airport("DEN", "America/Denver", 39.86, -104.6738, 870),
}
DAY = date(2026, 1, 6)
"""Tuesday. The pass's clock starts Monday, Jan 5, 2026, 6:00 am in Kansas City."""
START = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
TRIP_ID = "0" * 31 + "1"
USER = "u" * 32


def row(n: int) -> list[int]:
    return [n] * 5


def entry(
    code: str, today: str, dep: list[list[int]] | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "code": code,
        "today": today,
        "dep_canc": dep or [row(10), row(10), row(10)],
        "dep_late": [row(60), row(60), row(60)],
        "arr_canc": [row(10), row(10), row(10)],
        "arr_late": [row(60), row(60), row(60)],
        "rough": [10, 10, 10],
        "runs": [None, None, None],
        "usual": [[0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]],
        "rough_usual": 0,
        "why": [[0], [0], []],
        "programs": [],
        "alerts": [],
        "now": None,
        **extra,
    }


def live(at: datetime, mci: dict[str, Any], *, programs_at: datetime | None = None) -> FlightsLive:
    stamp = at.strftime("%Y%m%dT%H%MZ")
    iso = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    pat = (programs_at or at).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = "2026-01-05" if at < datetime(2026, 1, 6, 6, tzinfo=UTC) else "2026-01-06"
    return FlightsLive.model_validate_json(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": iso,
                "slot": "slot-1",
                "stamp": stamp,
                "run": iso,
                "programs_at": pat,
                "alerts_at": iso,
                "weather_at": iso,
                "observed_at": iso,
                "airports": [mci, *(entry(c, today) for c in ("LAX", "BUR", "DEN"))],
            }
        )
    )


def usual(carrier: str, number: int, to: str, leaves: int, lands: int) -> dict[str, Any]:
    return {
        "carrier": carrier,
        "number": number,
        "to_airport": to,
        "leaves": leaves,
        "lands": lands,
        "weekdays": 127,
        "days": 30,
        "cancelled": 0,
        "late": 2,
    }


ROUTES = {
    "MCI": [
        usual("WN", 1234, "LAX", 600, 720),
        usual("WN", 1500, "LAX", 900, 1020),
        usual("AA", 88, "LAX", 1080, 1200),
        usual("WN", 77, "BUR", 1110, 1230),
        usual("WN", 300, "DEN", 780, 840),
    ],
    "DEN": [usual("WN", 400, "LAX", 960, 1060), usual("WN", 401, "LAX", 860, 960)],
}


LATER = {**ROUTES, "MCI": [*ROUTES["MCI"], usual("WN", 1600, "LAX", 915, 1035)]}
"""The routes with one more usual WN flight to LAX at 3:15 pm (TRAV-R5-B1: two same-airline
backups that both leave soon after the 2 hour lead)."""


def routes(code: str, table: Mapping[str, list[dict[str, Any]]] = ROUTES) -> FlightsRoutes | None:
    flights = table.get(code)
    if flights is None:
        return None
    return FlightsRoutes.model_validate_json(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-01-05T00:00:00Z",
                "code": code,
                "months": [{"month": "2025-09", "flights": flights}],
            }
        )
    )


TRIP = Trip(TRIP_ID, USER, "WN", 1234, "MCI", "LAX", DAY, 600, 720, "basic")


def mci(tomorrow_morning: int, today: str = "2026-01-05", **extra: Any) -> dict[str, Any]:
    """MCI with tomorrow's (Jan 6) early and morning blocks at ``tomorrow_morning`` per mille."""
    day = [tomorrow_morning, tomorrow_morning, 20, 10, 10]
    rows = [row(10), day, row(10)] if today == "2026-01-05" else [day, row(10), row(10)]
    return entry("MCI", today, rows, **extra)


def world(  # noqa: PLR0913 - the test world's knobs
    at: datetime,
    mci_entry: dict[str, Any],
    waivers: Mapping[str, object] | None = None,
    programs_at: datetime | None = None,
    *,
    stale: bool = False,
    table: Mapping[str, list[dict[str, Any]]] = ROUTES,
) -> World:
    current = None if stale else live(at, mci_entry, programs_at=programs_at)
    return World.of(at, AIRPORTS, current, lambda code: routes(code, table), waivers)


def test_shown_percent_and_level_follow_the_page() -> None:
    # JavaScript's Math.round: 45 per mille shows 5%, so Some risk; 44 shows 4%, Low risk.
    assert shown(45) == 5
    assert shown(44) == 4
    assert level_of(shown(45), 0) == "delay"
    assert level_of(shown(44), 0) == "low"
    assert level_of(15, 0) == "cancel"
    assert level_of(4, 25) == "delay"


def test_a_chance_comes_from_forecast_values_only_and_never_from_an_old_file() -> None:
    fresh = world(START, mci(300))
    leg = trip_leg(fresh, TRIP)
    assert leg is not None
    assert (leg.cancel, leg.late, leg.level) == (31, 6, "cancel")
    usual_mask = mci(300, usual=[[0, 0b11, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]])
    assert trip_leg(world(START, usual_mask), TRIP) is None
    old = World.of(START + timedelta(hours=2), AIRPORTS, live(START, mci(300)), routes)
    assert trip_leg(old, TRIP) is None
    assert alerts_for(old, TRIP, Choices(), {}) == []


def test_backup_plans_keep_legal_layovers_and_the_deadline() -> None:
    plans = backup_plans(world(START, mci(300)), TRIP)
    keys = [plan.key() for plan in plans]
    assert "WN1500-MCI-2026-01-06" in keys
    assert "AA88-MCI-2026-01-06" in keys
    assert "WN77-MCI-2026-01-06" in keys
    assert "WN300-MCI-2026-01-06+WN400-DEN-2026-01-06" in keys
    assert not any("WN401" in key for key in keys)
    assert "WN1234-MCI-2026-01-06" not in keys
    assert plans[0].chance == plan_chance(plans[0].legs)
    # D11, the case backup.ts's tests share: among the plans 10 points safer than the trip, the
    # same airline and route comes first, WN 1500 at 91% before AA 88 at 92%, then by chance.
    trip_chance = plan_chance((trip_leg(world(START, mci(300)), TRIP) or plans[0].legs[0],))
    safer = [p for p in plans if p.chance >= trip_chance + SAFER_POINTS]
    order = {"same": 0, "other": 1, "nearby": 2, "hub": 3}
    assert [order[p.kind] for p in safer] == sorted(order[p.kind] for p in safer)
    for kind in order:
        same_kind = [p.chance for p in safer if p.kind == kind]
        assert same_kind == sorted(same_kind, reverse=True)
    wn = next(p for p in plans if p.key() == "WN1500-MCI-2026-01-06")
    aa = next(p for p in plans if p.key() == "AA88-MCI-2026-01-06")
    assert (wn.chance, aa.chance) == (91, 92)
    assert plans.index(wn) < plans.index(aa)
    bur = next(p for p in plans if p.key() == "WN77-MCI-2026-01-06")
    assert (bur.kind, bur.miles) == ("nearby", 18)
    due = Trip(TRIP_ID, USER, "WN", 1234, "MCI", "LAX", DAY, 600, 720, need_by="2026-01-06T17:30")
    late = backup_plans(world(START, mci(300)), due)
    assert all(plan.legs[-1].arrives <= datetime(2026, 1, 7, 1, 30, tzinfo=UTC) for plan in late)
    assert "AA88-MCI-2026-01-06" not in [plan.key() for plan in late]


def test_a_same_airline_plan_1_point_lower_comes_first_the_case_backup_ts_shares() -> None:
    def plan(kind: PlanKind, carrier: str, number: int, chance: int) -> Plan:
        arrives = datetime(2026, 1, 7, 2, 0, tzinfo=UTC)
        to = "BUR" if kind == "nearby" else "LAX"
        leg = Leg(carrier, number, "MCI", to, DAY, 600, 700, arrives, 1, 1)
        return Plan((leg,), chance, kind)

    plans = [
        plan("other", "AA", 88, 92),
        plan("hub", "WN", 300, 93),
        plan("same", "WN", 1500, 91),
        plan("other", "DL", 5, 72),
        plan("nearby", "WN", 77, 92),
        plan("same", "WN", 1, 70),
    ]
    ranked = sorted(plans, key=rank_key(65))
    assert [f"{p.legs[0].carrier}{p.legs[0].number}" for p in ranked] == [
        "WN1500",
        "AA88",
        "WN77",
        "WN300",
        "DL5",
        "WN1",
    ]


def test_the_chance_alert_names_the_safer_plans_and_counts_them_said() -> None:
    [alert] = alerts_for(world(START, mci(300)), TRIP, Choices(), {})
    assert (alert.kind, alert.value) == ("chance", "30:0:cancel:31")
    facts = alert.facts
    assert facts["cancel"] == 31
    assert facts["checked"] == {"day": "2026-01-05", "minute": 360}
    assert facts["at"] == int(START.timestamp())
    assert facts["level"] == "cancel"
    assert facts["ticket"] == "basic"
    backups = facts["backups"]
    assert isinstance(backups, list)
    assert 2 < len(backups) <= ALERT_CARRIED
    assert [kind for kind, _ in alert.also] == ["safer", "safer"]
    assert all(value.rsplit(":", 1)[-1].isdigit() for _, value in alert.also)
    # Under the threshold: nothing.
    assert alerts_for(world(START, mci(200)), TRIP, Choices(threshold=30), {}) == []


def sent_of(*rows: tuple[str, str]) -> dict[tuple[str, str], frozenset[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    for kind, value in rows:
        out.setdefault((TRIP_ID, kind), set()).add(value)
    return {key: frozenset(values) for key, values in out.items()}


def test_a_rise_is_said_once_a_full_step_above_what_was_said() -> None:
    said = sent_of(("chance", "30:0:delay:30"), ("night", "2026-01-06:0:delay:30"))
    [rise] = alerts_for(world(START, mci(300)), TRIP, Choices(), said)
    assert (rise.kind, rise.value) == ("rise", "0:cancel:31")
    again = alerts_for(
        world(START, mci(300)),
        TRIP,
        Choices(),
        sent_of(("chance", "30:0:delay:30"), ("rise", "0:cancel:31")),
    )
    assert "rise" not in [alert.kind for alert in again]


def test_an_evening_check_alone_never_starts_a_rise_under_the_threshold() -> None:
    # TRAV-R2-S1: with the evening check off the same weather sends nothing, so with it on too.
    for after in ("2026-01-06:0:low:3", "2026-01-06:0:delay:6"):
        said = sent_of(("night", after))
        assert alerts_for(world(START, mci(190)), TRIP, Choices(), said) == []
        assert alerts_for(world(START, mci(300)), TRIP, Choices(threshold=70), said) == []


def test_a_rise_of_20_points_at_the_threshold_is_said_once_more() -> None:
    said = sent_of(("chance", "30:0:cancel:31"), ("safer", "WN1500-MCI-2026-01-06:92"))
    assert [a.kind for a in alerts_for(world(START, mci(450)), TRIP, Choices(), said)] == []
    [rise] = alerts_for(world(START, mci(600)), TRIP, Choices(), said)
    assert (rise.kind, rise.value, rise.facts["cancel"]) == ("rise", "0:cancel:60", 60)
    said = sent_of(
        ("chance", "30:0:cancel:31"),
        ("rise", "0:cancel:60"),
        ("safer", "WN1500-MCI-2026-01-06:92"),
    )
    assert alerts_for(world(START, mci(700)), TRIP, Choices(), said) == []
    [higher] = alerts_for(world(START, mci(850)), TRIP, Choices(), said)
    assert higher.value == "0:cancel:85"
    # Under a 70% threshold a 20-point rise in High risk stays quiet.
    said70 = sent_of(("night", "2026-01-06:0:cancel:31"))
    assert alerts_for(world(START, mci(600)), TRIP, Choices(threshold=70), said70) == []


def test_faa_holds_today_only_live_and_not_past_their_end() -> None:
    trip = Trip(TRIP_ID, USER, "WN", 1234, "MCI", "LAX", date(2026, 1, 5), 600, 720)
    stop = [{"program": 0, "minutes": None, "until": None, "why": 1}]
    [alert] = alerts_for(world(START, mci(10, programs=stop)), trip, Choices(), {})
    assert (alert.kind, alert.value) == ("faa", "MCI:0:open")
    assert alert.facts["faa"] == {"airport": "MCI", "program": 0, "until": None}
    # D7: the push service never holds it past the FAA read's 30 minutes.
    assert alert.ttl == 30 * 60
    # SAFE-R2-S2: counted from the read, not this pass: a read 25 minutes old has 5 left, and the
    # alert's time is the read's, so a late push says when the FAA was checked.
    read = START - timedelta(minutes=25)
    [aged] = alerts_for(world(START, mci(10, programs=stop), programs_at=read), trip, Choices(), {})
    assert aged.ttl <= 5 * 60
    assert aged.facts["at"] == int(read.timestamp())
    assert aged.facts["checked"] == {"day": "2026-01-05", "minute": 335}
    assert (
        alerts_for(
            world(START, mci(10, programs=stop)), trip, Choices(), sent_of(("faa", "MCI:0:open"))
        )
        == []
    )
    # A stop with an end: held no longer than the end, which the facts carry in local time.
    soon = [{"program": 0, "minutes": None, "until": "2026-01-05T12:10:00Z", "why": 1}]
    [ends] = alerts_for(world(START, mci(10, programs=soon)), trip, Choices(), {})
    assert (ends.value, ends.ttl) == ("MCI:0:20260105T1210Z", 600)
    assert ends.facts["faa"] == {"airport": "MCI", "program": 0, "until": 370}
    # A second stop later the same day (another end) is a new change, said once.
    later = [{"program": 0, "minutes": None, "until": "2026-01-05T16:00:00Z", "why": 1}]
    said = sent_of(("faa", "MCI:0:20260105T1210Z"))
    [again] = alerts_for(world(START, mci(10, programs=later)), trip, Choices(), said)
    assert again.value == "MCI:0:20260105T1600Z"
    old = world(START, mci(10, programs=stop), programs_at=START - timedelta(minutes=31))
    assert alerts_for(old, trip, Choices(), {}) == []
    ended = [{"program": 0, "minutes": None, "until": "2026-01-05T11:00:00Z", "why": 1}]
    assert alerts_for(world(START, mci(10, programs=ended)), trip, Choices(), {}) == []
    delays = [{"program": 2, "minutes": 30, "until": None, "why": 1}]
    assert alerts_for(world(START, mci(10, programs=delays)), trip, Choices(), {}) == []
    # A trip tomorrow never hears today's FAA as its own.
    assert alerts_for(world(START, mci(10, programs=stop)), TRIP, Choices(), {}) == []


def waivers(
    at: datetime, *, state: str = "checked", airports: list[str] | None = None
) -> dict[str, object]:
    iso = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": 1,
        "generated_at": iso,
        "airlines": [
            {"code": "WN", "name": "Southwest", "path": "/", "state": state, "read_at": iso}
        ],
        "waivers": [
            {
                "airline": "WN",
                "airports": airports if airports is not None else ["MCI"],
                "all_airports": False,
                "travel_from": "2026-01-05",
                "travel_to": "2026-01-07",
                "on_page": True,
                "active": True,
                "last_seen": iso,
            }
        ],
    }


def test_a_waiver_read_on_the_airlines_page_is_said_once_never_a_guess() -> None:
    [alert] = alerts_for(world(START, mci(10), waivers(START)), TRIP, Choices(), {})
    assert (alert.kind, alert.value) == ("waiver", "waiver:2026-01-05:2026-01-07")
    # W8: basic economy only when the waiver says so plainly.
    assert alert.facts["waiver"] == {"state": "waiver", "basic": False, "airport": "MCI"}
    assert alert.ttl == 120 * 60
    with_basic = waivers(START)
    rows = with_basic["waivers"]
    assert isinstance(rows, list)
    rows[0]["basic_economy"] = True
    [basic] = alerts_for(world(START, mci(10), with_basic), TRIP, Choices(), {})
    assert basic.facts["waiver"] == {"state": "waiver", "basic": True, "airport": "MCI"}
    assert (
        alerts_for(
            world(START, mci(10), waivers(START)),
            TRIP,
            Choices(),
            sent_of(("waiver", "waiver:2026-01-05:2026-01-07")),
        )
        == []
    )
    assert (
        alerts_for(world(START, mci(10), waivers(START, state="not_checked")), TRIP, Choices(), {})
        == []
    )
    assert (
        alerts_for(world(START, mci(10), waivers(START - timedelta(hours=3))), TRIP, Choices(), {})
        == []
    )
    assert alerts_for(world(START, mci(10), None), TRIP, Choices(), {}) == []
    [unclear] = alerts_for(
        world(
            START,
            mci(10),
            waivers(START, airports=None)
            | {
                "waivers": [
                    {
                        "airline": "WN",
                        "airports": None,
                        "travel_from": "2026-01-05",
                        "travel_to": "2026-01-07",
                    }
                ]
            },
        ),
        TRIP,
        Choices(),
        {},
    )
    assert unclear.value.startswith("unclear:")


def test_quiet_hours_hold_a_waiver_until_they_end() -> None:
    night = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)  # 2 am in Kansas City
    assert alerts_for(world(night, mci(10), waivers(night)), TRIP, Choices(), {}) == []
    morning = datetime(2026, 1, 5, 11, 0, tzinfo=UTC)  # 5 am, quiet hours over
    [alert] = alerts_for(world(morning, mci(10), waivers(morning)), TRIP, Choices(), {})
    assert alert.kind == "waiver"


def test_the_reason_comes_from_the_end_that_drives_the_chance() -> None:
    lax = entry(
        "LAX",
        "2026-01-05",
        arr_canc=[row(10), row(400), row(10)],
        why=[[0], [3], []],
    )
    mci_entry = mci(10, why=[[0], [0], []])
    made = live(START, mci_entry).model_dump(mode="json")
    made["airports"] = [lax if a["code"] == "LAX" else a for a in made["airports"]]
    swapped = FlightsLive.model_validate_json(json.dumps(made))
    w = World.of(START, AIRPORTS, swapped, routes)
    [alert] = alerts_for(w, TRIP, Choices(), {})
    assert (alert.facts["why"], alert.facts["why_at"]) == (3, "LAX")
    [mci_driven] = alerts_for(world(START, mci(300)), TRIP, Choices(), {})
    assert (mci_driven.facts["why"], mci_driven.facts["why_at"]) == (0, "MCI")


def test_quiet_hours_hold_the_chance_but_not_the_faa() -> None:
    late_night = datetime(2026, 1, 6, 4, 30, tzinfo=UTC)  # 10:30 pm in Kansas City
    trip = Trip(TRIP_ID, USER, "WN", 1234, "MCI", "LAX", date(2026, 1, 5), 1380, 1430)
    stop = [{"program": 0, "minutes": None, "until": None, "why": 1}]
    mci_late = entry("MCI", "2026-01-05", [[300] * 5, row(10), row(10)], programs=stop)
    found = alerts_for(world(late_night, mci_late), trip, Choices(), {})
    assert [a.kind for a in found] == ["faa"]
    assert (
        alerts_for(
            world(late_night, mci_late), trip, Choices(quiet_from=time(0), quiet_to=time(0)), {}
        )[1].kind
        == "chance"
    )
    assert alerts_for(world(START, mci(300)), TRIP, Choices(alerts=False), {}) == []


# --- simulated days on the rules alone ---------------------------------------------------------

REGULAR = Trip(TRIP_ID, USER, "WN", 1234, "MCI", "LAX", DAY, 600, 720, "regular")


def run_day(  # noqa: PLR0913 - the simulated day's knobs
    morning_of: Callable[[datetime], int],
    hours: int = 22,
    choices: Choices | None = None,
    *,
    stale_of: Callable[[datetime], bool] = lambda _at: False,
    extra_of: Callable[[datetime], dict[str, Any]] = lambda _at: {},
    facts: list[Mapping[str, object]] | None = None,
) -> list[tuple[str, str, str, object, list[tuple[object, ...]]]]:
    """Every 20 minutes from 6 am Monday in Kansas City: what is sent, logged as sent (each
    alert's facts also go to ``facts``)."""
    sent: dict[tuple[str, str], frozenset[str]] = {}
    told: Told | None = None
    out: list[tuple[str, str, str, object, list[tuple[object, ...]]]] = []
    at = START
    while at < START + timedelta(hours=hours):
        today = "2026-01-05" if at < datetime(2026, 1, 6, 6, tzinfo=UTC) else "2026-01-06"
        w = world(at, mci(morning_of(at), today=today, **extra_of(at)), stale=stale_of(at))
        for a in alerts_for(w, REGULAR, choices or Choices(), sent, told):
            if a.kind in fl.RISK_KINDS:
                told = Told(at, a.kind, a.value)
            clock = at.astimezone(ZoneInfo("America/Chicago")).strftime("%a %H:%M")
            backups = a.facts["backups"]
            assert isinstance(backups, list)
            names: list[tuple[object, ...]] = [
                (b["carrier"], b["number"], b["day"], b["chance"]) for b in backups
            ]
            out.append((clock, str(a.kind), a.value, a.facts["cancel"], names))
            if facts is not None:
                facts.append(a.facts)
            for kind, value in ((a.kind, a.value), *a.also):
                sent[(REGULAR.id, kind)] = sent.get((REGULAR.id, kind), frozenset()) | {value}
        at += timedelta(minutes=20)
    return out


def test_a_constant_risk_day_says_it_once_and_then_the_evening_check() -> None:
    # 33% all day: a day-before backup leaving, or dropping out of the top two, sends nothing.
    day = run_day(lambda _at: 320, hours=27)
    assert [(when, kind) for when, kind, *_ in day] == [
        ("Mon 06:00", "chance"),
        ("Mon 20:00", "night"),
    ]


def test_a_chance_said_on_the_evening_pass_stands_for_the_evening_check() -> None:
    crosses = datetime(2026, 1, 6, 1, 50, tzinfo=UTC)  # 7:50 pm in Kansas City
    day = run_day(lambda at: 10 if at < crosses else 320)
    assert [(when, kind) for when, kind, *_ in day] == [("Mon 20:00", "chance")]


def test_a_chance_just_before_the_evening_check_stands_for_it() -> None:
    # TRAV-R2-B2 case J: the risk crosses at 7:30 pm; the 7:40 pm chance alert is the evening
    # check too (same chance, reason and backups), so 8 pm sends nothing.
    crosses = datetime(2026, 1, 6, 1, 30, tzinfo=UTC)
    day = run_day(lambda at: 10 if at < crosses else 330, hours=16)
    assert [(when, kind) for when, kind, *_ in day] == [("Mon 19:40", "chance")]


def chicago(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, minute, tzinfo=ZoneInfo("America/Chicago")).astimezone(UTC)


def test_a_fall_just_before_the_evening_check_stands_for_it_only_while_it_holds() -> None:
    # TRAV-R3-B1 case J8: a fall at 7:40 pm, then High risk from 7:50 pm. The fall said another
    # state, so the 8 pm evening check says the new chance (the last word that night is current).
    def j8(at: datetime) -> int:
        return (
            10
            if at < chicago(5, 13)
            else 340
            if at < chicago(5, 19, 30)
            else 20
            if at < chicago(5, 19, 50)
            else 200
        )

    day = run_day(j8, hours=27)
    assert [(when, kind, cancel) for when, kind, _v, cancel, _b in day] == [
        ("Mon 13:00", "chance", 35),
        ("Mon 19:40", "fall", 3),
        ("Mon 20:00", "night", 21),
    ]
    # The same fall, with the chance still low at 8 pm: the fall is the evening check.
    steady = run_day(lambda at: 10 if at < chicago(5, 13) or at >= chicago(5, 19, 30) else 340)
    assert [(when, kind) for when, kind, *_ in steady] == [
        ("Mon 13:00", "chance"),
        ("Mon 19:40", "fall"),
    ]


def test_a_chance_just_before_the_evening_check_that_no_longer_holds_gets_one() -> None:
    # TRAV-R3-B1 case J9: 35% at 7:20 pm, 17% from 7:50 pm (no fall: not 20 points down). The
    # evening check says 17%, never leaves the 35% as the last word.
    day = run_day(
        lambda at: 10 if at < chicago(5, 19, 10) else 340 if at < chicago(5, 19, 50) else 160
    )
    assert [(when, kind, cancel) for when, kind, _v, cancel, _b in day] == [
        ("Mon 19:20", "chance", 35),
        ("Mon 20:00", "night", 17),
    ]


def test_a_safer_alert_never_stands_for_the_evening_check() -> None:
    assert Told(START, "safer", "WN1500-MCI-2026-01-06:91").state() is None
    assert Told(START, "chance", "30:0:cancel:34").state() == "0:cancel:34"
    assert Told(START, "rise", "1:cancel:60").state() == "1:cancel:60"
    # A fall ends its round: the evening check after it says the next round's state.
    assert Told(START, "fall", "0:low:3").state() == "1:low:3"
    assert Told(START, "chance", "30:x:cancel:34").state() is None


def test_backups_leave_with_time_to_change_the_ticket_and_get_there() -> None:
    # TRAV-R3-B3 case V: the risk crosses at 9:30 am Monday. The 10:00 am day-early flight is 20
    # minutes away and is never named; every named one leaves 2 hours on (3 from a nearby airport).
    facts: list[Mapping[str, object]] = []
    day = run_day(lambda at: 10 if at < chicago(5, 9, 30) else 330, hours=6, facts=facts)
    assert [(when, kind) for when, kind, *_ in day] == [("Mon 09:40", "chance")]
    [(_w, _k, _v, _c, names)] = day
    assert ("WN", 1234, "2026-01-05", 92) not in names
    for made in facts:
        at = int(made["at"])  # type: ignore[call-overload]
        backups = made["backups"]
        assert isinstance(backups, list)
        for backup in backups:
            near = backup["from"] != "MCI"
            assert backup["departs"] - at >= (3 if near else 2) * 3600


def test_plans_drop_flights_that_leave_too_soon() -> None:
    at = chicago(5, 9, 40)
    plans = backup_plans(world(at, mci(330)), REGULAR)
    assert plans
    assert all(departs(world(at, mci(330)), plan) >= at + BACKUP_LEAD for plan in plans)
    assert not any(p.key() == "WN1234-MCI-2026-01-05" for p in plans)
    assert any(
        p.key() == "WN1234-MCI-2026-01-05"
        for p in backup_plans(world(chicago(5, 7), mci(330)), REGULAR)
    )


def test_with_no_forecast_for_the_trip_the_evening_check_says_so_on_time() -> None:
    # TRAV-R3-S1 case P: the file is current but the trip's block shows the usual rate. Settings
    # says the evening check tells you either way: it says there is no forecast yet.
    def usual_block(at: datetime) -> dict[str, Any]:
        return {
            "usual": [
                [0, 3, 0] if at < chicago(6, 0) else [3, 0, 0],
                [0, 0, 0],
                [0, 0, 0],
                [0, 0, 0],
            ]
        }

    facts: list[Mapping[str, object]] = []
    day = run_day(lambda _at: 330, hours=27, extra_of=usual_block, facts=facts)
    assert [(when, kind, value, cancel) for when, kind, value, cancel, _b in day] == [
        ("Mon 20:00", "night", "2026-01-06:0:usual:0", None),
    ]
    assert facts[0]["no_forecast"] is True


def test_the_evening_check_comes_before_quiet_hours_that_cover_its_time() -> None:
    # TRAV-R2-S2 cases K and K2: never lost to quiet hours.
    at_nine = run_day(
        lambda _at: 330, hours=27, choices=Choices(night_time=time(21), quiet_from=time(21))
    )
    assert [(when, kind) for when, kind, *_ in at_nine] == [
        ("Mon 06:00", "chance"),
        ("Mon 20:00", "night"),
    ]
    late = run_day(lambda _at: 330, hours=27, choices=Choices(night_time=time(22, 30)))
    assert [(when, kind) for when, kind, *_ in late] == [
        ("Mon 06:00", "chance"),
        ("Mon 21:00", "night"),
    ]


def test_with_no_current_live_file_the_evening_check_says_it_could_not_check() -> None:
    def stale(at: datetime) -> bool:
        return datetime(2026, 1, 6, 2, tzinfo=UTC) <= at < datetime(2026, 1, 6, 5, tzinfo=UTC)

    day = run_day(lambda _at: 330, hours=27, stale_of=stale)
    assert [(when, kind, value, cancel) for when, kind, value, cancel, _b in day] == [
        ("Mon 06:00", "chance", "30:0:cancel:34", 34),
        # The window ends at quiet hours (10 pm): its last 40 minutes, no number.
        ("Mon 21:20", "night", "2026-01-06:0:none:0", None),
    ]


def test_a_fall_is_said_once_and_a_new_crossing_after_it_is_said_again() -> None:
    def morning(at: datetime) -> int:
        hours = (at - START).total_seconds() / 3600
        return 320 if 2 <= hours < 5 else 330 if hours >= 9 else 10

    day = run_day(morning)
    kinds = [(when, kind, cancel) for when, kind, _v, cancel, _b in day]
    assert kinds == [
        ("Mon 08:00", "chance", 33),
        ("Mon 11:00", "fall", 2),
        ("Mon 15:00", "chance", 34),
        ("Mon 20:00", "night", 34),
    ]
    fall = next(item for item in day if item[1] == "fall")
    assert fall[4] == []


def test_the_alerts_name_the_same_airline_first() -> None:
    [(_when, _kind, _value, _cancel, names)] = run_day(lambda _at: 320, hours=1)
    # The two it names (the carried plans past them are the next best, for a late push).
    assert all(carrier == "WN" for carrier, *_ in names[:ALERT_BACKUPS])
    late = run_day(lambda at: 10 if at < START + timedelta(hours=10) else 320, hours=11)
    [(_w, kind, _v, _c, named)] = late
    # 4 pm: Monday's flights have left; WN 1500 (91%) comes before AA 88 (92%).
    assert (kind, named[0][:2], named[1][:2]) == ("chance", ("WN", 1500), ("AA", 88))


# --- the facts the web words (web/src/modes/flights/tests/alert-facts.json) --------------------

FACTS_FILE = Path(__file__).resolve().parents[3] / "web" / "src" / "modes" / "flights" / "tests"
FACTS_FILE = FACTS_FILE / "alert-facts.json"


def sender_facts() -> dict[str, Mapping[str, object]]:
    """One alert of each kind, as the sender makes it on the SYNTHETIC files: the web's copy and
    push tests word exactly these (so a page, a push and an email never say what the sender
    would not)."""
    stop = [{"program": 0, "minutes": None, "until": "2026-01-05T13:30:00Z", "why": 1}]
    today = Trip(TRIP_ID, USER, "WN", 1234, "MCI", "LAX", date(2026, 1, 5), 600, 720, "regular")
    four_pm = START + timedelta(hours=10)
    evening = datetime(2026, 1, 6, 2, 0, tzinfo=UTC)
    late_evening = datetime(2026, 1, 6, 3, 30, tzinfo=UTC)
    cases: dict[str, tuple[World, Trip, Sent]] = {
        "chance_day_early": (world(START, mci(300)), REGULAR, {}),
        "chance": (world(four_pm, mci(300)), REGULAR, {}),
        "rise": (
            world(four_pm, mci(600)),
            REGULAR,
            sent_of(("chance", "30:0:cancel:31"), ("safer", "WN1500-MCI-2026-01-06:91")),
        ),
        "fall": (world(four_pm, mci(10)), REGULAR, sent_of(("chance", "30:0:cancel:31"))),
        "safer": (
            world(four_pm, mci(300)),
            REGULAR,
            sent_of(("chance", "30:0:cancel:31"), ("safer", "WN1500-MCI-2026-01-06:75")),
        ),
        "night": (world(evening, mci(100, today="2026-01-05")), REGULAR, {}),
        "night_none": (world(late_evening, mci(100), stale=True), REGULAR, {}),
        "night_usual": (
            world(evening, mci(100, usual=[[0, 3, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]])),
            REGULAR,
            {},
        ),
        # TRAV-R5-B1: the top two leave 2 h 05 min and 2 h 20 min on; a late push names a later one.
        "chance_late": (world(chicago(5, 12, 55), mci(330), table=LATER), REGULAR, {}),
        "faa": (world(START, mci(10, programs=stop)), today, {}),
        "waiver_basic": (world(START, mci(10), waivers(START)), TRIP, {}),
    }
    out: dict[str, Mapping[str, object]] = {}
    for name, (w, trip, said) in cases.items():
        [alert] = [a for a in alerts_for(w, trip, Choices(), said) if a.kind == name.split("_")[0]]
        out[name] = alert.facts
    return out


def test_the_web_words_the_facts_the_sender_makes() -> None:
    made = json.loads(json.dumps(sender_facts()))
    if os.environ.get("SNOWLIGHT_WRITE_FIXTURES") == "1":
        FACTS_FILE.write_text(json.dumps(made, indent=2) + "\n", encoding="utf-8")
    assert json.loads(FACTS_FILE.read_text(encoding="utf-8")) == made


def test_an_alert_carries_more_safer_plans_than_it_names_best_first() -> None:
    # TRAV-R5-B1: the two it names (same airline) leave 2 h 05 min and 2 h 20 min on. It carries
    # the next ones, best first, so one shown late still names a safer flight that can be caught,
    # and says when it found more than it carries.
    at = chicago(5, 12, 55)
    w = world(at, mci(330), table=LATER)
    [alert] = alerts_for(w, REGULAR, Choices(), {})
    leg = trip_leg(w, REGULAR)
    assert leg is not None
    safer = [p for p in backup_plans(w, REGULAR) if p.chance >= plan_chance((leg,)) + SAFER_POINTS]
    assert len(safer) > ALERT_CARRIED
    carried = alert.facts["backups"]
    assert isinstance(carried, list)
    assert [(b["carrier"], b["number"], b["day"]) for b in carried] == [
        (p.legs[0].carrier, p.legs[0].number, p.legs[0].day.isoformat())
        for p in safer[:ALERT_CARRIED]
    ]
    assert [(b["number"], b["departs"] - int(at.timestamp())) for b in carried[:2]] == [
        (1500, 125 * 60),
        (1600, 140 * 60),
    ]
    assert alert.facts["more"] is True
    # Only the top ones it names are logged as said.
    assert len(alert.also) == ALERT_BACKUPS
    # Few plans: none past them.
    [few] = alerts_for(world(START + timedelta(hours=10), mci(300)), REGULAR, Choices(), {})
    assert few.facts["more"] is False


def test_a_full_alert_fits_one_push() -> None:
    # The Web Push record holds 4096 bytes; the sender's facts stay well under it with every
    # carried plan the longest it can be (a one-stop plan with 4-digit flights).
    [alert] = alerts_for(world(START, mci(300)), TRIP, Choices(), {})
    longest = {
        "carrier": "WN",
        "number": 9999,
        "from": "MCI",
        "to": "LAX",
        "day": "2026-01-06",
        "leaves": 1439,
        "departs": 1767700000,
        "chance": 100,
        "kind": "nearby",
        "miles": 119,
        "via": {"carrier": "WN", "number": 9999, "hub": "DEN"},
    }
    facts = {**alert.facts, "backups": [longest] * ALERT_CARRIED, "more": True}
    assert len(json.dumps(facts, separators=(",", ":")).encode()) < 3000


# --- a simulated day through the database and the sender ---------------------------------------


@pytest.fixture
def fake() -> FakeD1:
    fake = FakeD1()
    migrate(fake.db)
    add_vapid(fake)
    add_user(fake, USER, [], [Browser.make("https://fcm.googleapis.com/fcm/send/one")])
    fake.db.execute(
        "INSERT INTO trips (id, user_id, carrier, number, from_airport, to_airport, day, leaves,"
        " lands, ticket, ticket_asked, created_at, updated_at)"
        " VALUES (?, ?, 'WN', 1234, 'MCI', 'LAX', '2026-01-06', 600, 720, 'regular', 1, 1, 1)",
        (TRIP_ID, USER),
    )
    fake.db.execute(
        "INSERT INTO google_links (user_id, google_email, scopes, refresh_token, connected_at)"
        " VALUES (?, 'pat@example.com', ?, 'v1.x.y', 1)",
        (USER, "openid email https://www.googleapis.com/auth/gmail.send"),
    )
    fake.db.commit()
    return fake


def test_every_risk_alert_of_a_trip_shares_one_push_topic() -> None:
    # TRAV-R6-B1: the push service keeps only the newest message per topic for an offline phone,
    # so the trip's risk alerts (one tray slot, push.ts flightTag) share one topic and an older
    # one never reaches the phone after a newer one. FAA and waiver alerts keep their own.
    kinds = get_args(Kind.__value__)
    risk = {fl.push_topic(kind, TRIP_ID) for kind in kinds if kind not in {"faa", "waiver"}}
    assert risk == {f"fl-risk-{TRIP_ID[:20]}"}
    assert set(kinds) - {"faa", "waiver"} == {"chance", "rise", "fall", "safer", "night"}
    for kind in kinds:
        topic = fl.push_topic(kind, "f" * 32)
        assert len(topic) <= 32
        assert re.fullmatch(r"[A-Za-z0-9_-]+", topic)
    assert fl.push_topic("faa", TRIP_ID) == f"fl-faa-{TRIP_ID[:20]}"
    assert fl.push_topic("waiver", TRIP_ID) == f"fl-waiver-{TRIP_ID[:20]}"
    assert fl.push_topic("chance", TRIP_ID) != fl.push_topic("chance", "1" * 32)


def test_a_simulated_day_says_each_change_once(fake: FakeD1) -> None:
    db = d1(fake)
    pushed: list[dict[str, Any]] = []
    topics: set[tuple[str, str]] = set()
    mailed: list[tuple[str, Mapping[str, object]]] = []

    def pusher(_s: Subscription, message: Message, _now: int) -> Delivery:
        pushed.append(json.loads(message.payload))
        topics.add((pushed[-1]["alert"], message.topic))
        return Delivery.SENT

    def mailer(user: str, facts: Mapping[str, object]) -> bool:
        mailed.append((user, facts))
        return True

    def morning(at: datetime) -> int:
        """Tomorrow morning's cancel chance at MCI as the day goes: calm, then 31%, then 61%."""
        hours = (at - START).total_seconds() / 3600
        return 10 if hours < 3 else 300 if hours < 8 else 600

    stop_from = START + timedelta(hours=20)  # 12 am Jan 6 in Kansas City... a stop before the trip
    at = START
    while at < START + timedelta(hours=23):
        today = "2026-01-05" if at < datetime(2026, 1, 6, 6, tzinfo=UTC) else "2026-01-06"
        programs = (
            [{"program": 1, "minutes": 45, "until": None, "why": 1}] if at >= stop_from else []
        )
        if today == "2026-01-05":
            mci_entry = mci(morning(at), programs=programs)
        else:
            mci_entry = mci(morning(at), today=today, programs=programs)
        w = world(at, mci_entry, waivers(at) if at >= START + timedelta(hours=10) else None)
        accounts = fl.read_accounts(db, at)
        alerts = fl.due_alerts(w, accounts)
        fl.deliver(db, alerts, accounts, pusher, mailer, at)
        at += timedelta(minutes=20)
    said = [(p["alert"], p["cancel"]) for p in pushed]
    kinds = [p["alert"] for p in pushed]
    # Calm at first: nothing. Then 31%: one chance alert. Then 60%: 29 points more, one rise.
    assert kinds.count("chance") == 1
    assert said[kinds.index("chance")] == ("chance", 31)
    assert kinds.count("rise") == 1
    assert said[kinds.index("rise")] == ("rise", 60)
    assert kinds.count("safer") == 0
    # The waiver once, the evening check once (8 pm Kansas City), the ground delay once (today).
    assert kinds.count("waiver") == 1
    assert kinds.count("night") == 1
    assert kinds.count("faa") == 1
    assert len(mailed) == len(pushed)
    rows = fake.rows("SELECT kind, value FROM flights_sent ORDER BY kind, value")
    assert ("chance", "30:0:cancel:31") in rows
    assert ("faa", "MCI:1:open") in rows
    assert sum(1 for kind, _ in rows if kind == "night") == 1
    # The day's chance, rise and evening check went out on one topic, the FAA and waiver on theirs.
    risk = f"fl-risk-{TRIP_ID[:20]}"
    assert topics == {
        ("chance", risk),
        ("rise", risk),
        ("night", risk),
        ("waiver", f"fl-waiver-{TRIP_ID[:20]}"),
        ("faa", f"fl-faa-{TRIP_ID[:20]}"),
    }


def test_the_log_times_carry_a_chance_just_before_the_evening_check(fake: FakeD1) -> None:
    # TRAV-R2-B2 case J through the database: the 7:40 pm chance alert's log time stands for the
    # 8 pm evening check, so one push and one email go out for the one change.
    db = d1(fake)
    pushed: list[dict[str, Any]] = []
    crosses = datetime(2026, 1, 6, 1, 30, tzinfo=UTC)

    def pusher(_s: Subscription, message: Message, _now: int) -> Delivery:
        pushed.append(json.loads(message.payload))
        return Delivery.SENT

    at = datetime(2026, 1, 6, 1, 0, tzinfo=UTC)
    while at < datetime(2026, 1, 6, 4, 0, tzinfo=UTC):
        accounts = fl.read_accounts(db, at)
        alerts = fl.due_alerts(world(at, mci(10 if at < crosses else 330)), accounts)
        fl.deliver(db, alerts, accounts, pusher, lambda *_: True, at)
        at += timedelta(minutes=20)
    assert [p["alert"] for p in pushed] == ["chance"]
    told = fl.read_accounts(db, at).told
    assert told == {
        TRIP_ID: Told(datetime(2026, 1, 6, 1, 40, tzinfo=UTC), "chance", "30:0:cancel:34")
    }


def test_an_alert_no_browser_and_no_email_took_is_tried_again(fake: FakeD1) -> None:
    db = d1(fake)
    accounts = fl.read_accounts(db, START)
    alerts = fl.due_alerts(world(START, mci(300)), accounts)
    report = fl.deliver(db, alerts, accounts, lambda *_: Delivery.FAILED, lambda *_: False, START)
    assert report.held == 1
    assert fake.rows("SELECT * FROM flights_sent") == []
    gone = fl.deliver(db, alerts, accounts, lambda *_: Delivery.GONE, None, START)
    assert gone.held == 1
    assert fake.rows("SELECT * FROM push_subscriptions") == []


def test_the_mail_key_is_written_hashed_and_dropped(fake: FakeD1) -> None:
    db = d1(fake)
    key = fl.mail_key(db, START)
    [(value,)] = fake.rows("SELECT value FROM settings WHERE name = 'flights_mail_key'")
    digest, ends = str(value).split(":")
    assert digest == hashlib.sha256(key.encode()).hexdigest()
    assert int(ends) == int((START + timedelta(minutes=15)).timestamp() * 1000)
    assert key not in str(fake.rows("SELECT * FROM settings"))
    fl.drop_mail_key(db)
    assert fake.rows("SELECT * FROM settings WHERE name = 'flights_mail_key'") == []


def test_the_worker_mailer_posts_the_facts_with_the_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"sent": True})

    mail = fl.worker_mailer(
        httpx.Client(transport=httpx.MockTransport(handler)), "https://api.test/", "k" * 43
    )
    assert mail(USER, {"v": 1}) is True
    assert seen[0].url == "https://api.test/v1/internal/flights/mail"
    assert seen[0].headers["Authorization"] == "Bearer " + "k" * 43
    assert json.loads(seen[0].content) == {"user_id": USER, "alert": {"v": 1}}


def test_the_command_stays_dark_without_secrets_or_trips(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert fl.run_flights(argparse.Namespace(), fl.Outside(env=dict)) == 0
    assert "no Cloudflare secrets" in capsys.readouterr().out
    empty = FakeD1()
    migrate(empty.db)

    outside = fl.Outside(
        env=lambda: {
            "CLOUDFLARE_API_TOKEN": SECRETS.token,
            "CLOUDFLARE_ACCOUNT_ID": SECRETS.account,
            "CLOUDFLARE_API_URL": SECRETS.api,
        },
        client=lambda: routed(empty),
        pause=0,
    )
    assert fl.run_flights(argparse.Namespace(), outside) == 0
    assert "no trips" in capsys.readouterr().out


def test_read_world_takes_the_live_file_only_with_the_latest_stamp() -> None:
    made = live(START, mci(300))
    files: dict[str, bytes] = {
        "v1/flights/latest.json": json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-01-05T12:00:00Z",
                "slot": "slot-1",
                "stamp": made.stamp,
            }
        ).encode(),
        "v1/flights/live/slot-1.json": made.model_dump_json().encode(),
    }
    read: Callable[[str], bytes | None] = files.get
    assert fl.read_world(read, START, AIRPORTS).live is not None
    files["v1/flights/latest.json"] = files["v1/flights/latest.json"].replace(
        made.stamp.encode(), b"20260105T1100Z"
    )
    assert fl.read_world(read, START, AIRPORTS).live is None
    assert fl.read_airports()["MCI"].tz == "America/Chicago"


def test_the_api_root_is_the_variable_else_the_workers_dev_worker() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/accounts/acct/workers/subdomain")
        return httpx.Response(200, json={"result": {"subdomain": "made-up"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fl.api_root_of(client, SECRETS, {"SNOWLIGHT_API_ROOT": "https://api.x.test"}) == (
        "https://api.x.test"
    )
    assert fl.api_root_of(client, SECRETS, {}) == "https://snowlight-api.made-up.workers.dev"
    broken = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(500, text="no")))
    assert fl.api_root_of(broken, SECRETS, {}) == ""

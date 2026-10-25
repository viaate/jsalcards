"""The admin's manual statuses (accounts spec C): ``snowlight live overrides`` against a stub
API on a loopback port and a folder host, the strict reading of the API's answer, the
directory check, the day rule, and the admin's precedence in the merge.

Every id, school and district here is SYNTHETIC (the predict tests' small world).
"""

import argparse
import json
import os
import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from snowlight import cli
from snowlight.directory.deployed import DeployedEditionError
from snowlight.directory.points import NO_DISTRICT, decode, encode
from snowlight.live import cli as live_cli
from snowlight.live.edition import EditionState, EditionVerdict
from snowlight.live.merge import ADMIN_SOURCE, AdminStatus, Merged, OpenSignal, with_overrides
from snowlight.live.overrides import (
    EMPTY,
    DeployedSchools,
    Override,
    OverridesError,
    api_url,
    fetch,
    nothing_to_publish,
    parse,
    resolve,
    zone_table,
)
from snowlight.live.publish import CLOSINGS, HOLD, LiveHold, LivePublisher, Mode
from snowlight.live.publishers import DEFAULT_MESSAGE, DirPublisher, GitHubPublisher, Publisher
from snowlight.predict.serve import DeployedDirectory
from snowlight.schemas.directory import DirectoryStamp, SchoolDirectoryMeta
from snowlight.schemas.live import Closing, ClosingsFile, OpensFile
from snowlight.schemas.vocab import Status

CONTENT = "c" * 64
DISTRICTS = ("2000004", "2900001", "2900002", "2900003", "4900005")
# Each SYNTHETIC school: its district position (None: a private school without one).
SCHOOL_DISTRICTS: tuple[int | None, ...] = (1, 1, 2, 2, 3, 0, 4, None)
STAMP = DirectoryStamp(
    generated_on=date(2026, 10, 14), schools=len(SCHOOL_DISTRICTS), districts=len(DISTRICTS)
)
ZONES = {
    "2900001": "America/Chicago",
    "2900002": "America/Chicago",
    "2900003": "America/Chicago",
    "2000004": "America/Chicago",
    "4900005": "America/Denver",
}
# 13:05 UTC: 08:05 in Kansas City (Central), 07:05 in Salt Lake City (Mountain).
MORNING = datetime(2026, 11, 17, 13, 5, tzinfo=UTC)
TODAY = date(2026, 11, 17)
END_OF_TODAY_CENTRAL = "2026-11-18T06:00:00Z"
END_OF_TOMORROW_CENTRAL = "2026-11-19T06:00:00Z"
TOMORROW = TODAY + timedelta(days=1)
TOMORROW_ONLY: Mapping[str, Any] = {"days": ["2026-11-18"], "expires_at": END_OF_TOMORROW_CENTRAL}
BOTH_DAYS: Mapping[str, Any] = {
    "days": ["2026-11-17", "2026-11-18"],
    "expires_at": END_OF_TOMORROW_CENTRAL,
}
SCHOOL_IDS = tuple(f"{i:012d}" for i in range(1, len(SCHOOL_DISTRICTS) + 1))


def deployed(content: str | None = CONTENT) -> DeployedDirectory:
    count = len(SCHOOL_DISTRICTS)
    points = encode(
        [-94_580_000] * count,
        [39_100_000] * count,
        [NO_DISTRICT if d is None else d for d in SCHOOL_DISTRICTS],
        [0] * count,
        len(DISTRICTS),
    )
    return DeployedDirectory(STAMP, DISTRICTS, decode(points), content_sha256=content)


def meta() -> SchoolDirectoryMeta:
    return SchoolDirectoryMeta.from_json_bytes(
        json.dumps(
            {
                "schema_version": 1,
                "generated_on": "2026-10-14",
                "count": len(SCHOOL_IDS),
                "ids": list(SCHOOL_IDS),
                "names": [f"SYNTHETIC School {i}" for i in range(len(SCHOOL_IDS))],
                "districts": {
                    "ids": list(DISTRICTS),
                    "names": [f"SYNTHETIC District {i}" for i in range(len(DISTRICTS))],
                },
                "school_years": {"private": "2023-2024", "public": "2024-2025"},
            }
        ).encode()
    )


def schools() -> DeployedSchools:
    """A SYNTHETIC directory: districts 2900001 (schools 0, 1), 2900002
    (2, 3), 2900003 (4), 2000004 (5) in Central time, 4900005 (6) in Mountain time, and a
    private school without a district (7)."""
    return DeployedSchools.from_deployed(deployed(), meta(), ZONES)


def wire(**fields: Any) -> dict[str, Any]:
    """One override as the API serves it (closed for district 2900001 today, by default)."""
    value: dict[str, Any] = {
        "scope": "district",
        "id": "2900001",
        "status": "closed",
        "minutes": None,
        "at_local_time": None,
        "days": ["2026-11-17"],
        "time_zone": "America/Chicago",
        "set_at": "2026-11-17T12:40:00Z",
        "expires_at": END_OF_TODAY_CENTRAL,
    }
    value.update(fields)
    return value


def body(*overrides: Mapping[str, Any]) -> bytes:
    return json.dumps({"overrides": list(overrides)}).encode()


# --- reading the API -------------------------------------------------------------------------


def test_a_well_formed_answer_reads() -> None:
    found = parse(
        body(
            wire(**BOTH_DAYS, time_zone=None),
            wire(scope="school", id="000000000007", status="delayed", minutes=120, note="x"),
            wire(status="early_dismissal", at_local_time="12:30", id="2900002"),
            wire(status="open", id="2000004"),
        )
    )
    assert [override.status for override in found] == [
        "closed",
        "delayed",
        "early_dismissal",
        "open",
    ]
    assert found[1].minutes == 120
    assert (found[0].days, found[1].days) == ((TODAY, TOMORROW), (TODAY,))
    assert (found[0].time_zone, found[1].time_zone) == (None, "America/Chicago")
    assert found[2].clock_minute == 12 * 60 + 30
    assert not hasattr(found[1], "note")  # the API never sends one; it would not be kept


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        b"[]",
        b'{"items": []}',
        body(wire(status="remote")),
        body(wire(scope="county")),
        body(wire(id="")),
        body(wire(id="29 00001")),
        body(wire(minutes=60)),
        body(wire(status="open", at_local_time="09:00")),
        body(wire(status="delayed", minutes=0)),
        body(wire(status="delayed", minutes=721)),
        body(wire(status="delayed", minutes="120")),
        body(wire(status="delayed", minutes=True)),
        body(wire(status="delayed", at_local_time="24:00")),
        body(wire(status="delayed", at_local_time="9:00")),
        # a delay has its minutes and no time; an early dismissal its time and no minutes
        body(wire(status="delayed")),
        body(wire(status="delayed", minutes=120, at_local_time="10:00")),
        body(wire(status="delayed", at_local_time="10:00")),
        body(wire(status="early_dismissal")),
        body(wire(status="early_dismissal", minutes=60)),
        body(wire(status="early_dismissal", minutes=60, at_local_time="12:30")),
        # days: one or two, ascending and next to each other, local dates
        body(wire(days=[])),
        body(wire(days="2026-11-17")),
        body(wire(days=["2026-11-17", "2026-11-18", "2026-11-19"])),
        body(wire(days=["2026-11-18", "2026-11-17"])),
        body(wire(days=["2026-11-17", "2026-11-17"])),
        body(wire(days=["2026-11-17", "2026-11-19"])),
        body(wire(days=["2026-11-17T00:00:00Z"])),
        body(wire(days=["17/11/2026"])),
        body(wire(days=[None])),
        body({key: value for key, value in wire().items() if key != "days"}),
        body(wire(time_zone="")),
        body(wire(time_zone="UTC")),
        body(wire(time_zone="../etc")),
        body({key: value for key, value in wire().items() if key != "time_zone"}),
        body(wire(set_at="2026-11-17T12:40:00")),
        body(wire(expires_at="2026-11-17T12:40:00Z")),
        body(wire(expires_at=None)),
        body({key: value for key, value in wire().items() if key != "set_at"}),
    ],
)
def test_a_malformed_answer_is_refused_whole(data: bytes) -> None:
    with pytest.raises(OverridesError):
        parse(data)


def test_an_oversized_answer_is_refused() -> None:
    with pytest.raises(OverridesError, match="too large"):
        parse(b" " * (2 * 1024 * 1024 + 1))


def test_api_url() -> None:
    assert api_url("https://snowlight-api.synthetic.workers.dev/") == (
        "https://snowlight-api.synthetic.workers.dev/v1/overrides"
    )
    assert api_url("https://api.synthetic.example") == "https://api.synthetic.example/v1/overrides"
    assert api_url("http://127.0.0.1:8787/") == "http://127.0.0.1:8787/v1/overrides"
    for bad in ("http://api.synthetic.example/", "ftp://x/", "https:///", "https://x/?a=1"):
        with pytest.raises(OverridesError):
            api_url(bad)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(500), "HTTP 500"),
        (httpx.Response(404), "HTTP 404"),
        (httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"}), "JSON"),
        (httpx.Response(200, json={"overrides": [{"scope": "x"}]}), "malformed"),
    ],
)
def test_fetch_refuses_anything_but_a_good_answer(response: httpx.Response, message: str) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: response))
    with pytest.raises(OverridesError, match=message):
        fetch(client, "https://api.synthetic.example/")


def test_fetch_names_a_network_error_by_type_only() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic words", request=request)

    with pytest.raises(OverridesError, match="ConnectError") as caught:
        fetch(httpx.Client(transport=httpx.MockTransport(fail)), "https://api.synthetic.example/")
    assert "synthetic words" not in str(caught.value)


# --- the directory check and the day rule ----------------------------------------------------


def lit(statuses: tuple[AdminStatus, ...]) -> dict[tuple[int, date], Status | None]:
    return {(status.school, status.day): status.status for status in statuses}


def test_a_district_override_covers_each_of_its_schools() -> None:
    found = resolve(parse(body(wire())), schools(), MORNING)
    assert lit(found.statuses) == {(0, TODAY): Status.CLOSED, (1, TODAY): Status.CLOSED}
    assert found.withheld == {}
    assert {status.nces_id for status in found.statuses} == {SCHOOL_IDS[0], SCHOOL_IDS[1]}


def test_a_school_override_covers_that_school_only() -> None:
    found = resolve(parse(body(wire(scope="school", id=SCHOOL_IDS[3]))), schools(), MORNING)
    assert lit(found.statuses) == {(3, TODAY): Status.CLOSED}


def test_an_id_the_deployed_directory_does_not_hold_lights_nothing() -> None:
    found = resolve(
        parse(body(wire(id="9999999"), wire(scope="school", id="999999999999"))),
        schools(),
        MORNING,
    )
    assert found.statuses == ()
    assert found.withheld == {"not_in_directory": 2}


def test_a_school_id_is_not_read_as_a_district_or_the_other_way() -> None:
    found = resolve(
        parse(body(wire(scope="school", id="2900001"), wire(id=SCHOOL_IDS[0]))),
        schools(),
        MORNING,
    )
    assert found.statuses == ()
    assert found.withheld == {"not_in_directory": 2}


def test_expired_overrides_drop_out() -> None:
    later = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)
    found = resolve(parse(body(wire())), schools(), later)
    assert found.statuses == ()
    assert found.withheld == {"expired": 1}


def test_today_lights_today_whenever_it_was_set() -> None:
    for set_at in ("2026-11-17T12:40:00Z", "2026-11-17T17:59:00Z", "2026-11-18T01:20:00Z"):
        now = datetime.fromisoformat(set_at) + timedelta(minutes=5)
        found = resolve(parse(body(wire(set_at=set_at))), schools(), now)
        assert lit(found.statuses) == {(0, TODAY): Status.CLOSED, (1, TODAY): Status.CLOSED}


def test_tomorrow_lights_tomorrow_only_even_in_the_morning() -> None:
    found = resolve(parse(body(wire(**TOMORROW_ONLY))), schools(), MORNING)
    assert lit(found.statuses) == {(0, TOMORROW): Status.CLOSED, (1, TOMORROW): Status.CLOSED}


@pytest.mark.parametrize(
    "set_at",
    [
        "2026-11-17T12:40:00Z",  # 06:40 in Kansas City
        "2026-11-17T18:00:00Z",  # noon
        "2026-11-18T01:00:00Z",  # 19:00, in the evening (critic round 3)
    ],
)
def test_today_and_tomorrow_lights_both_whenever_it_was_set(set_at: str) -> None:
    now = datetime.fromisoformat(set_at) + timedelta(minutes=5)
    found = resolve(parse(body(wire(set_at=set_at, **BOTH_DAYS))), schools(), now)
    assert lit(found.statuses) == {
        (0, TODAY): Status.CLOSED,
        (1, TODAY): Status.CLOSED,
        (0, TOMORROW): Status.CLOSED,
        (1, TOMORROW): Status.CLOSED,
    }


def test_a_listed_day_that_has_ended_or_is_not_yet_tomorrow_lights_nothing() -> None:
    # The next morning: the API no longer lists the 17th; were it still listed, it is over.
    next_morning = MORNING + timedelta(days=1)
    for days in (["2026-11-18"], ["2026-11-17", "2026-11-18"]):
        found = resolve(parse(body(wire(**{**BOTH_DAYS, "days": days}))), schools(), next_morning)
        assert lit(found.statuses) == {
            (0, TOMORROW): Status.CLOSED,
            (1, TOMORROW): Status.CLOSED,
        }
    # Days after tomorrow wait (the API never lists them; nothing is guessed either way).
    later = wire(days=["2026-11-19"], expires_at="2026-11-20T06:00:00Z")
    found = resolve(parse(body(later)), schools(), MORNING)
    assert found.statuses == ()
    assert found.withheld == {"not_today_or_tomorrow": 2}


def test_the_listed_days_are_lit_whatever_the_expiry_says() -> None:
    # The expiry only ends an override; it never adds a day.
    found = resolve(parse(body(wire(expires_at="2026-11-19T06:00:00Z"))), schools(), MORNING)
    assert {status.day for status in found.statuses} == {TODAY}


# --- edits: exactly the listed days, with the override's current details (critic round 3) ---

AFTERNOON_NOW = datetime(2026, 11, 17, 20, 5, tzinfo=UTC)  # 14:05 in Kansas City
FIRST_POSTED = datetime(2026, 11, 17, 12, 40, tzinfo=UTC)


def shown_file(
    rows: Mapping[tuple[int, date], tuple[Status, int | None, int | None]],
    *,
    posted: datetime = FIRST_POSTED,
    at: datetime = AFTERNOON_NOW - timedelta(minutes=5),
    stamp: DirectoryStamp = STAMP,
    manual: bool = True,
) -> ClosingsFile:
    """A public closings file that shows ``rows`` (SYNTHETIC), posted at ``posted``."""
    return ClosingsFile.encode(
        [
            Closing(
                school=school,
                day=day,
                status=status,
                announced_at=posted,
                reason=None,
                shift_minutes=shift,
                clock_minute=clock,
                manual=manual,
            )
            for (school, day), (status, shift, clock) in rows.items()
        ],
        generated_at=at,
        directory=stamp,
    )


def on(
    days: Sequence[date], row: tuple[Status, int | None, int | None]
) -> dict[tuple[int, date], tuple[Status, int | None, int | None]]:
    """District 2900001's two schools showing ``row`` on each of ``days``."""
    return {(school, day): row for school in (0, 1) for day in days}


def details(statuses: tuple[AdminStatus, ...]) -> dict[tuple[int, date], tuple[Any, ...]]:
    return {
        (status.school, status.day): (status.status, status.shift_minutes, status.clock_minute)
        for status in statuses
    }


def posted(statuses: tuple[AdminStatus, ...]) -> dict[tuple[int, date], datetime]:
    return {(status.school, status.day): status.set_at for status in statuses}


def test_an_after_noon_edit_of_todays_dismissal_time_publishes_the_new_time() -> None:
    # 06:40: early dismissal at 13:00 today and tomorrow, on the map; at 12:15 the admin
    # moves it to 12:30. The panel must say 12:30 today, not keep 1:00 PM.
    shown = shown_file(on((TODAY, TOMORROW), (Status.EARLY_DISMISSAL, None, 13 * 60)))
    edited = wire(
        status="early_dismissal",
        at_local_time="12:30",
        set_at="2026-11-17T18:15:00Z",
        **BOTH_DAYS,
    )
    now = datetime(2026, 11, 17, 18, 20, tzinfo=UTC)
    found = resolve(parse(body(edited)), schools(), now, shown)
    assert details(found.statuses) == on((TODAY, TOMORROW), (Status.EARLY_DISMISSAL, None, 750))
    # a changed status is posted anew on every day it changed
    assert set(posted(found.statuses).values()) == {datetime(2026, 11, 17, 18, 15, tzinfo=UTC)}


def test_a_resave_that_changes_nothing_keeps_every_days_first_posted_time() -> None:
    shown = shown_file(on((TODAY, TOMORROW), (Status.CLOSED, None, None)))
    resaved = wire(set_at="2026-11-17T20:00:00Z", **BOTH_DAYS)  # a new note, say
    found = resolve(parse(body(resaved)), schools(), AFTERNOON_NOW, shown)
    assert details(found.statuses) == on((TODAY, TOMORROW), (Status.CLOSED, None, None))
    assert set(posted(found.statuses).values()) == {FIRST_POSTED}


def test_adding_tomorrow_keeps_todays_posted_time_and_posts_tomorrow_now() -> None:
    shown = shown_file(on((TODAY,), (Status.CLOSED, None, None)))
    extended = wire(set_at="2026-11-17T20:00:00Z", **BOTH_DAYS)
    found = resolve(parse(body(extended)), schools(), AFTERNOON_NOW, shown)
    assert details(found.statuses) == on((TODAY, TOMORROW), (Status.CLOSED, None, None))
    times = posted(found.statuses)
    assert times[0, TODAY] == FIRST_POSTED
    assert times[0, TOMORROW] == datetime(2026, 11, 17, 20, 0, tzinfo=UTC)


def test_a_day_no_longer_listed_goes_whatever_the_map_shows() -> None:
    shown = shown_file(on((TODAY, TOMORROW), (Status.CLOSED, None, None)))
    tomorrow_only = wire(set_at="2026-11-17T20:00:00Z", **TOMORROW_ONLY)
    found = resolve(parse(body(tomorrow_only)), schools(), AFTERNOON_NOW, shown)
    assert details(found.statuses) == on((TOMORROW,), (Status.CLOSED, None, None))
    assert set(posted(found.statuses).values()) == {FIRST_POSTED}  # tomorrow is unchanged


def test_a_status_of_another_kind_replaces_the_listed_days_only() -> None:
    # Delayed 2 hours today and tomorrow; at 14:00 tomorrow becomes Closed (today unlisted).
    shown = shown_file(on((TODAY, TOMORROW), (Status.DELAYED, 120, None)))
    closed = wire(set_at="2026-11-17T20:00:00Z", **TOMORROW_ONLY)
    found = resolve(parse(body(closed)), schools(), AFTERNOON_NOW, shown)
    assert details(found.statuses) == on((TOMORROW,), (Status.CLOSED, None, None))
    assert set(posted(found.statuses).values()) == {datetime(2026, 11, 17, 20, 0, tzinfo=UTC)}
    # Listing both days instead: Closed on both, nothing of the delay stays.
    both = wire(set_at="2026-11-17T20:00:00Z", **BOTH_DAYS)
    found = resolve(parse(body(both)), schools(), AFTERNOON_NOW, shown)
    assert details(found.statuses) == on((TODAY, TOMORROW), (Status.CLOSED, None, None))


def test_delete_then_re_add() -> None:
    shown = shown_file(on((TODAY, TOMORROW), (Status.CLOSED, None, None)))
    # deleted: no day is kept, whatever the map shows
    assert resolve((), schools(), AFTERNOON_NOW, shown).statuses == ()
    # deleted and set again for tomorrow before the next pass: today goes, tomorrow stays
    again = wire(set_at="2026-11-17T20:01:00Z", **TOMORROW_ONLY)
    found = resolve(parse(body(again)), schools(), AFTERNOON_NOW, shown)
    assert details(found.statuses) == on((TOMORROW,), (Status.CLOSED, None, None))
    # set again after a pass took it down: a new posting
    taken_down = shown_file({})
    found = resolve(parse(body(again)), schools(), AFTERNOON_NOW, taken_down)
    assert set(posted(found.statuses).values()) == {datetime(2026, 11, 17, 20, 1, tzinfo=UTC)}


def test_open_takes_the_day_down() -> None:
    shown = shown_file(on((TODAY,), (Status.CLOSED, None, None)))
    opened = wire(status="open", set_at="2026-11-17T20:00:00Z")
    found = resolve(parse(body(opened)), schools(), AFTERNOON_NOW, shown)
    assert lit(found.statuses) == {(0, TODAY): None, (1, TODAY): None}
    merged = with_overrides(EMPTY, found.statuses, AFTERNOON_NOW)
    assert merged.closings == ()
    assert {(signal.school, signal.day) for signal in merged.opens} == {(0, TODAY), (1, TODAY)}


def test_a_list_rows_time_is_not_taken_for_the_admins() -> None:
    # The same status shown from a list (not manual) is posted at the admin's own time.
    shown = shown_file(on((TODAY,), (Status.CLOSED, None, None)), manual=False)
    found = resolve(
        parse(body(wire(set_at="2026-11-17T20:00:00Z"))), schools(), AFTERNOON_NOW, shown
    )
    assert set(posted(found.statuses).values()) == {datetime(2026, 11, 17, 20, 0, tzinfo=UTC)}


def test_a_map_file_of_another_directory_gives_no_posted_time() -> None:
    other = DirectoryStamp(
        generated_on=date(2026, 10, 1), schools=STAMP.schools, districts=STAMP.districts
    )
    shown = shown_file(on((TODAY,), (Status.CLOSED, None, None)), stamp=other)
    found = resolve(
        parse(body(wire(set_at="2026-11-17T20:00:00Z"))), schools(), AFTERNOON_NOW, shown
    )
    assert details(found.statuses) == on((TODAY,), (Status.CLOSED, None, None))
    assert set(posted(found.statuses).values()) == {datetime(2026, 11, 17, 20, 0, tzinfo=UTC)}


def test_a_changed_delay_is_posted_at_its_new_time() -> None:
    delayed = wire(set_at="2026-11-17T13:00:00Z", status="delayed", minutes=60)
    shown = shown_file({(0, TODAY): (Status.DELAYED, 120, None)}, at=MORNING)
    found = resolve(parse(body(delayed)), schools(), MORNING, shown)
    assert details(found.statuses)[0, TODAY] == (Status.DELAYED, 60, None)
    assert posted(found.statuses)[0, TODAY] == datetime(2026, 11, 17, 13, 0, tzinfo=UTC)


def test_the_day_follows_each_schools_own_time_zone() -> None:
    # 06:30 UTC on the 18th: still the 17th in Utah (23:30), already the 18th in Missouri.
    late = datetime(2026, 11, 18, 6, 30, tzinfo=UTC)
    mountain = wire(
        id="4900005",
        time_zone="America/Denver",
        set_at="2026-11-18T06:00:00Z",
        expires_at="2026-11-18T07:00:00Z",
    )
    found = resolve(parse(body(mountain)), schools(), late)
    assert lit(found.statuses) == {(6, TODAY): Status.CLOSED}


def test_an_override_whose_days_were_named_in_another_zone_lights_nothing() -> None:
    # The admin view listed the Utah district's days in Central time (an hour ahead): at
    # 23:30 in Utah its "today" would be the 18th, which is the school's tomorrow.
    late = datetime(2026, 11, 18, 6, 30, tzinfo=UTC)
    central = wire(
        id="4900005",
        days=["2026-11-18"],
        set_at="2026-11-18T06:00:00Z",
        expires_at="2026-11-19T06:00:00Z",
    )
    found = resolve(parse(body(central)), schools(), late)
    assert found.statuses == ()
    assert found.withheld == {"zone_differs": 1}
    # A district's schools all take its zone: each one is withheld.
    other = resolve(parse(body(wire(time_zone="America/Denver"))), schools(), MORNING)
    assert (other.statuses, other.withheld) == ((), {"zone_differs": 2})
    # A status set before days were stored names no zone: its one day is the school's.
    before = wire(id="4900005", time_zone=None, set_at="2026-11-18T06:00:00Z")
    found = resolve(parse(body(before | {"expires_at": "2026-11-18T07:00:00Z"})), schools(), late)
    assert lit(found.statuses) == {(6, TODAY): Status.CLOSED}


def test_a_school_without_a_district_takes_the_nearest_schools_time_zone() -> None:
    # SYNTHETIC places: the private school (7) beside the Utah school (6), the rest far east.
    count = len(SCHOOL_DISTRICTS)
    places = replace(
        schools(),
        lon_e6=tuple(-111_900_000 if index in {6, 7} else -94_580_000 for index in range(count)),
        lat_e6=tuple(40_760_000 if index in {6, 7} else 39_100_000 for index in range(count)),
    )
    late = datetime(2026, 11, 18, 6, 30, tzinfo=UTC)  # 23:30 on the 17th in Utah
    found = resolve(
        parse(
            body(
                wire(
                    scope="school",
                    id=SCHOOL_IDS[7],
                    time_zone="America/Denver",
                    set_at="2026-11-18T06:00:00Z",
                    expires_at="2026-11-18T06:59:00Z",
                )
            )
        ),
        places,
        late,
    )
    assert lit(found.statuses) == {(7, TODAY): Status.CLOSED}  # Mountain time: still the 17th
    assert found.borrowed == {7: "America/Denver"}
    assert places.live_directory(found.borrowed).schools[SCHOOL_IDS[7]].zones == ("America/Denver",)
    assert schools().live_directory().schools[SCHOOL_IDS[7]].zones == ()


def test_a_school_whose_time_zone_cannot_be_known_lights_nothing() -> None:
    nowhere = replace(schools(), lon_e6=(), lat_e6=())
    found = resolve(parse(body(wire(scope="school", id=SCHOOL_IDS[7]))), nowhere, MORNING)
    assert found.statuses == ()
    assert found.withheld == {"no_time_zone": 1}
    unknown = replace(schools(), zones=(None,) * len(DISTRICTS))
    assert resolve(parse(body(wire(id="2000004"))), unknown, MORNING).withheld == {
        "no_time_zone": 1
    }
    bad = replace(schools(), zones=("Not/A_Zone", *schools().zones[1:]))
    assert resolve(parse(body(wire(id="2000004"))), bad, MORNING).withheld == {"no_time_zone": 1}


def test_the_places_must_cover_every_school_or_none() -> None:
    with pytest.raises(ValueError, match="stamp"):
        replace(schools(), lon_e6=(1,), lat_e6=(1,))


def test_set_at_ahead_of_the_clock() -> None:
    near = resolve(parse(body(wire(set_at="2026-11-17T13:05:40Z"))), schools(), MORNING)
    assert {status.set_at for status in near.statuses} == {MORNING.replace(second=0)}
    far = resolve(parse(body(wire(set_at="2026-11-17T13:10:00Z"))), schools(), MORNING)
    assert far.statuses == ()
    assert far.withheld == {"set_ahead": 1}


def test_times_are_kept_for_delays_and_dismissals() -> None:
    found = resolve(
        parse(
            body(
                wire(status="delayed", minutes=120),
                wire(id="2900002", status="early_dismissal", at_local_time="12:30"),
                wire(id="2900003", status="open"),
            )
        ),
        schools(),
        MORNING,
    )
    by_school = {status.school: status for status in found.statuses}
    assert (by_school[0].status, by_school[0].shift_minutes, by_school[0].clock_minute) == (
        Status.DELAYED,
        120,
        None,
    )
    assert (by_school[2].status, by_school[2].shift_minutes, by_school[2].clock_minute) == (
        Status.EARLY_DISMISSAL,
        None,
        750,
    )
    assert by_school[4].status is None


def test_from_deployed_refuses_a_meta_of_another_directory() -> None:
    other = meta().model_copy(update={"generated_on": date(2026, 10, 15)})
    with pytest.raises(ValueError, match=r"meta\.json"):
        DeployedSchools.from_deployed(deployed(), other, ZONES)
    with pytest.raises(ValueError, match="content digest"):
        DeployedSchools.from_deployed(deployed(None), meta(), ZONES)


def test_the_committed_model_gives_every_district_a_time_zone() -> None:
    zones = zone_table()
    assert len(zones) > 10_000
    assert zones["0100005"] == "America/Chicago"


# --- the admin's precedence in the merge -----------------------------------------------------


def admin(school: int, status: Status | None, **fields: Any) -> AdminStatus:
    value: dict[str, Any] = {
        "school": school,
        "nces_id": SCHOOL_IDS[school],
        "day": TODAY,
        "status": status,
        "shift_minutes": None,
        "clock_minute": None,
        "set_at": datetime(2026, 11, 17, 12, 40, tzinfo=UTC),
        "level": "district",
        "key": f"k{school}",
    }
    value.update(fields)
    return AdminStatus(**value)


def listed() -> Merged:
    """SYNTHETIC list statuses: school 0 delayed, school 1 closed, school 2 says open."""
    rows = (
        Closing(0, TODAY, Status.DELAYED, None, None, 120, None),
        Closing(1, TODAY, Status.CLOSED, None, None),
    )
    return replace(
        EMPTY,
        closings=rows,
        provenance=tuple(
            {"nces_id": SCHOOL_IDS[row.school], "source_id": "gray-synthetic"} for row in rows
        ),
        opens=(OpenSignal(2, SCHOOL_IDS[2], TODAY, MORNING, "gray-synthetic", "x", 0.95),),
    )


def test_the_admin_outranks_every_list_read() -> None:
    merged = with_overrides(
        listed(),
        [
            admin(0, Status.CLOSED),
            admin(1, None),
            admin(2, Status.EARLY_DISMISSAL, clock_minute=750),
        ],
        MORNING,
    )
    shown = {(row.school, row.day): row.status for row in merged.closings}
    assert shown == {(0, TODAY): Status.CLOSED, (2, TODAY): Status.EARLY_DISMISSAL}
    assert [(signal.school, signal.source_id) for signal in merged.opens] == [(1, ADMIN_SOURCE)]
    assert [line["source_type"] for line in merged.provenance] == ["admin", "admin"]
    assert merged.counts["overridden"] == 2
    assert merged.closings[0].announced_at == datetime(2026, 11, 17, 12, 40, tzinfo=UTC)


def test_a_schools_own_override_beats_its_districts_and_then_the_later_wins() -> None:
    earlier = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
    merged = with_overrides(
        EMPTY,
        [
            admin(0, Status.CLOSED, level="school", set_at=earlier, key="a"),
            admin(0, Status.DELAYED, shift_minutes=60, key="b"),
            admin(1, Status.DELAYED, shift_minutes=60, set_at=earlier, key="c"),
            admin(1, Status.CLOSED, key="d"),
        ],
        MORNING,
    )
    assert [(row.school, row.status) for row in merged.closings] == [
        (0, Status.CLOSED),
        (1, Status.CLOSED),
    ]


def test_an_admin_open_until_tomorrow_replaces_a_list_closed_today() -> None:
    """Set this morning to correct a list's false Closed: open today and tomorrow."""
    resolved = resolve(parse(body(wire(status="open", **BOTH_DAYS))), schools(), MORNING)
    merged = with_overrides(listed(), resolved.statuses, MORNING)
    assert {(row.school, row.day) for row in merged.closings} == set()
    assert {(signal.school, signal.day) for signal in merged.opens} == {
        (0, TODAY),
        (1, TODAY),
        (0, TODAY + timedelta(days=1)),
        (1, TODAY + timedelta(days=1)),
        (2, TODAY),  # the list's own open statement stays
    }
    assert merged.counts["overridden"] == 2


def test_no_admin_status_leaves_the_merge_as_it_is() -> None:
    assert with_overrides(listed(), [], MORNING) == listed()


def test_an_admin_status_set_after_the_file_is_refused() -> None:
    with pytest.raises(ValueError, match="after"):
        with_overrides(
            EMPTY, [admin(0, Status.CLOSED, set_at=MORNING + timedelta(seconds=1))], MORNING
        )


def test_only_delays_and_dismissals_have_times() -> None:
    with pytest.raises(ValueError, match="times"):
        admin(0, Status.CLOSED, shift_minutes=60)


# --- the pass: a stub API on a loopback port, a folder host ---------------------------------


@dataclass
class Api:
    """A SYNTHETIC API: the overrides answer it is given, on a loopback port."""

    status: int = 200
    data: bytes = field(default_factory=body)
    content_type: str = "application/json"
    gets: int = 0
    url: str = ""


@pytest.fixture
def api() -> Iterator[Api]:
    stub = Api()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002, ARG002
            return

        def do_GET(self) -> None:
            stub.gets += 1
            if self.path != "/v1/overrides":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(stub.status)
            self.send_header("Content-Type", stub.content_type)
            self.send_header("Content-Length", str(len(stub.data)))
            self.end_headers()
            self.wfile.write(stub.data)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    stub.url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield stub
    httpd.shutdown()
    httpd.server_close()


@dataclass
class Clock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Rig:
    api: Api
    clock: Clock
    host: Path
    tmp: Path
    directory_reads: int = 0
    schools: DeployedSchools = field(default_factory=schools)

    def loaders(self, env: Mapping[str, str] | None = None) -> live_cli.Loaders:
        def read_schools(_config: live_cli.LiveConfig, _env: live_cli.Env) -> DeployedSchools:
            self.directory_reads += 1
            return self.schools

        return live_cli.Loaders(
            client=httpx.Client,
            schools=read_schools,
            clock=self.clock,
            env=lambda: dict(env if env is not None else {"LIVE_PUBLISH": "on"}),
        )

    def run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        env: Mapping[str, str] | None = None,
        *,
        none: bool = False,
    ) -> int:
        config = self.tmp / "live.yaml"
        config.write_text(
            f"""host:
  kind: dir
  folder: {self.host}
state:
  kind: local
  folder: {self.tmp / "store"}
site: https://synthetic.example
site_repository: viaate/synthetic
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(live_cli, "LOADERS", self.loaders(env))
        args: argparse.Namespace = cli.build_parser().parse_args(
            [
                "live",
                "overrides",
                *(["--none"] if none else ["--api", self.api.url]),
                "--config",
                str(config),
                "--state",
                str(self.tmp / "state"),
                "--internal",
                str(self.tmp / "internal"),
            ]
        )
        return int(args.handler(args))

    def public(self, prefix: str = "v1") -> ClosingsFile | None:
        data = DirPublisher(self.host).read(f"{prefix}/live/closings.json")
        return None if data is None else ClosingsFile.model_validate_json(data)

    def shown(self) -> dict[tuple[int, str], tuple[Status, int | None, int | None]]:
        public = self.public()
        assert public is not None
        assert public.directory == self.schools.stamp
        return {
            (row.school, row.day.isoformat()): (row.status, row.shift_minutes, row.clock_minute)
            for row in public.closings()
        }


@pytest.fixture
def rig(api: Api, tmp_path: Path) -> Rig:
    return Rig(api, Clock(MORNING), tmp_path / "host", tmp_path)


def test_no_override_and_no_public_file_writes_nothing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rig.run(monkeypatch) == 0
    assert not rig.host.exists()
    assert rig.directory_reads == 0
    assert "nothing to publish" in capsys.readouterr().out


def test_a_manual_closing_and_delay_are_published_on_the_deployed_stamp(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.api.data = body(
        wire(),
        wire(scope="school", id=SCHOOL_IDS[2], status="delayed", minutes=120),
        wire(scope="school", id="999999999999"),
    )
    assert rig.run(monkeypatch) == 0
    assert rig.shown() == {
        (0, "2026-11-17"): (Status.CLOSED, None, None),
        (1, "2026-11-17"): (Status.CLOSED, None, None),
        (2, "2026-11-17"): (Status.DELAYED, 120, None),
    }
    public = rig.public()
    assert public is not None
    assert {row.announced_at for row in public.closings()} == {
        datetime(2026, 11, 17, 12, 40, tzinfo=UTC)
    }
    assert DirPublisher(rig.host).read("v1-shadow/live/closings.json") is None
    provenance = (rig.tmp / "internal" / "provenance.jsonl").read_text().splitlines()
    assert {json.loads(line)["source_type"] for line in provenance} == {"admin"}


def test_unchanged_within_the_heartbeat_uploads_nothing_then_the_heartbeat_does(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.api.data = body(wire())
    assert rig.run(monkeypatch) == 0
    first = rig.public()
    rig.clock.now = MORNING + timedelta(minutes=2)
    assert rig.run(monkeypatch) == 0
    assert rig.public() == first
    # The 5-minute pass: still within the overrides pass's 10-minute heartbeat.
    rig.clock.now = MORNING + timedelta(minutes=5)
    assert rig.run(monkeypatch) == 0
    assert rig.public() == first
    rig.clock.now = MORNING + timedelta(minutes=10)
    assert rig.run(monkeypatch) == 0
    later = rig.public()
    assert later is not None
    assert first is not None
    assert later.generated_at == MORNING + timedelta(minutes=10)
    assert later.closings()
    assert len(later.closings()) == len(first.closings())


def test_a_changed_override_publishes_at_once(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    rig.api.data = body(wire(status="delayed", minutes=60))
    assert rig.run(monkeypatch) == 0
    rig.clock.now = MORNING + timedelta(minutes=1)
    rig.api.data = body(wire(set_at="2026-11-17T13:05:30Z"))
    assert rig.run(monkeypatch) == 0
    assert set(rig.shown().values()) == {(Status.CLOSED, None, None)}


def test_the_map_follows_each_save_of_the_listed_days(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.api.data = body(wire())  # 06:40 "Closed today"
    assert rig.run(monkeypatch) == 0
    assert set(rig.shown()) == {(0, "2026-11-17"), (1, "2026-11-17")}
    # 14:00: today and tomorrow; the API replaces the override and set_at moves
    rig.clock.now = AFTERNOON_NOW
    rig.api.data = body(wire(set_at="2026-11-17T20:00:00Z", **BOTH_DAYS))
    for _ in range(3):  # and stays so on every pass
        assert rig.run(monkeypatch) == 0
        assert set(rig.shown()) == {
            (0, "2026-11-17"),
            (1, "2026-11-17"),
            (0, "2026-11-18"),
            (1, "2026-11-18"),
        }
        rig.clock.now += timedelta(minutes=5)
    public = rig.public()
    assert public is not None
    times = {(row.school, row.day.isoformat()): row.announced_at for row in public.closings()}
    assert times[0, "2026-11-17"] == FIRST_POSTED  # unchanged today: first posted
    assert times[0, "2026-11-18"] == datetime(2026, 11, 17, 20, 0, tzinfo=UTC)
    assert all(row.manual for row in public.closings())
    # 14:30: a 1 PM early dismissal tomorrow only: today goes, tomorrow shows the dismissal
    rig.clock.now = datetime(2026, 11, 17, 20, 35, tzinfo=UTC)
    rig.api.data = body(
        wire(
            set_at="2026-11-17T20:30:00Z",
            status="early_dismissal",
            at_local_time="13:00",
            **TOMORROW_ONLY,
        )
    )
    assert rig.run(monkeypatch) == 0
    assert rig.shown() == {
        (0, "2026-11-18"): (Status.EARLY_DISMISSAL, None, 780),
        (1, "2026-11-18"): (Status.EARLY_DISMISSAL, None, 780),
    }
    # deleted: every day goes at the next pass
    rig.clock.now += timedelta(minutes=5)
    rig.api.data = body()
    assert rig.run(monkeypatch) == 0
    assert rig.shown() == {}


def test_an_unreadable_map_file_publishes_nothing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.api.data = body(wire())
    assert rig.run(monkeypatch) == 0
    first = rig.public()

    def fail(_self: DirPublisher, _name: str) -> bytes | None:
        raise OSError("SYNTHETIC")

    monkeypatch.setattr(DirPublisher, "read", fail)
    rig.clock.now = AFTERNOON_NOW
    rig.api.data = body(wire(set_at="2026-11-17T20:00:00Z", **BOTH_DAYS))
    assert rig.run(monkeypatch) == 1
    monkeypatch.undo()
    assert rig.public() == first


def test_cleared_and_expired_overrides_drop_out_then_nothing_is_written(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.api.data = body(wire(), wire(id="2900002", expires_at="2026-11-17T14:00:00Z"))
    assert rig.run(monkeypatch) == 0
    assert len(rig.shown()) == 4
    rig.clock.now = datetime(2026, 11, 17, 14, 0, tzinfo=UTC)  # the second one expired
    assert rig.run(monkeypatch) == 0
    assert set(rig.shown()) == {(0, "2026-11-17"), (1, "2026-11-17")}
    rig.clock.now += timedelta(minutes=1)
    rig.api.data = body()  # the admin cleared it
    assert rig.run(monkeypatch) == 0
    assert rig.shown() == {}
    published = rig.public()
    rig.clock.now += timedelta(minutes=10)
    reads = rig.directory_reads
    assert rig.run(monkeypatch) == 0
    assert rig.public() == published  # nothing to publish: no heartbeat of an empty file
    assert rig.directory_reads == reads


@pytest.mark.parametrize(
    ("status", "data", "content_type"),
    [
        (200, b'{"overrides": [{"scope": "district"}]}', "application/json"),
        (200, b"<html></html>", "text/html"),
        (500, b"{}", "application/json"),
        (
            200,
            b'{"overrides": [{"scope": "district", "id": "2900001", "status": "remote"}]}',
            "application/json",
        ),
    ],
)
def test_a_bad_answer_publishes_nothing_and_keeps_the_last_file(  # noqa: PLR0913, PLR0917 - the cases
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
    data: bytes,
    content_type: str,
) -> None:
    rig.api.data = body(wire())
    assert rig.run(monkeypatch) == 0
    kept = rig.public()
    rig.clock.now += timedelta(minutes=6)
    rig.api.status, rig.api.data, rig.api.content_type = status, data, content_type
    assert rig.run(monkeypatch) == 1
    assert rig.public() == kept
    assert "OverridesError" in capsys.readouterr().err


def test_an_unreadable_deployed_directory_publishes_nothing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig.api.data = body(wire())

    def broken(_config: live_cli.LiveConfig, _env: live_cli.Env) -> DeployedSchools:
        raise DeployedEditionError("edition: a deploy is in progress")

    loaders = replace(rig.loaders(), schools=broken)
    real = rig.loaders
    monkeypatch.setattr(rig, "loaders", lambda _env=None: loaders)
    assert rig.run(monkeypatch) == 1
    assert rig.public() is None
    assert "deploy is in progress" in capsys.readouterr().err
    monkeypatch.setattr(rig, "loaders", real)


def test_the_hold_keeps_the_map_dark(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    earlier = MORNING - timedelta(minutes=1)
    hold = LiveHold(schema_version=1, held=True, at=earlier, held_at=earlier).to_json_bytes()
    DirPublisher(rig.host).write({f"v1/{HOLD}": hold})
    rig.api.data = body(wire())
    assert rig.run(monkeypatch) == 3
    public = rig.public()
    assert public is None or public.days == ()


def test_publishing_off_and_shadow(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    rig.api.data = body(wire())
    assert rig.run(monkeypatch, {"LIVE_PUBLISH": "off"}) == 0
    assert not rig.host.exists()
    assert rig.run(monkeypatch, {"LIVE_PUBLISH": "shadow"}) == 0
    assert rig.public() is None
    assert rig.public("v1-shadow") is not None


def test_an_admin_open_leaves_no_status_and_is_kept_as_an_open_statement(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.api.data = body(wire(status="open"))
    assert rig.run(monkeypatch) == 0
    assert rig.shown() == {}
    opens = DirPublisher(rig.host).read("v1/live/opens.json")
    assert opens is not None
    assert {row.school for row in OpensFile.model_validate_json(opens).opens} == {0, 1}


def test_nothing_to_publish_reads_the_public_files(tmp_path: Path) -> None:
    host = DirPublisher(tmp_path)
    assert not nothing_to_publish(True, host, "v1")
    assert nothing_to_publish(False, host, "v1")
    assert nothing_to_publish(False, host, None)
    lit_file = ClosingsFile.encode(
        [Closing(0, TODAY, Status.CLOSED, None, None)],
        generated_at=MORNING,
        directory=schools().stamp,
    )
    host.write({"v1/live/closings.json": lit_file.to_json_bytes()})
    assert not nothing_to_publish(False, host, "v1")
    host.write({"v1/live/closings.json": b'{"not": "a closings file"}'})
    assert not nothing_to_publish(False, host, "v1")
    empty = ClosingsFile.encode([], generated_at=MORNING, directory=schools().stamp)
    host.write({"v1/live/closings.json": empty.to_json_bytes()})
    assert nothing_to_publish(False, host, "v1")
    # an open statement still shown is taken down too
    opens = OpensFile.model_validate(
        {
            "schema_version": 1,
            "generated_at": MORNING,
            "directory": schools().stamp,
            "opens": (
                {"school": 0, "day": TODAY, "kind": "open", "at": MORNING, "confidence": 1.0},
            ),
        }
    )
    host.write({"v1/live/opens.json": opens.to_json_bytes()})
    assert not nothing_to_publish(False, host, "v1")
    host.write({"v1/live/opens.json": b"[]"})
    assert not nothing_to_publish(False, host, "v1")


def test_overrides_that_light_nothing_write_nothing_on_a_quiet_map(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    after_tomorrow = wire(days=["2026-11-19"], expires_at="2026-11-20T06:00:00Z")
    rig.api.data = body(wire(scope="school", id="999999999999"), after_tomorrow)
    for minutes in (0, 5, 10):
        rig.clock.now = MORNING + timedelta(minutes=minutes)
        assert rig.run(monkeypatch) == 0
    assert not rig.host.exists()  # no heartbeat of an empty file
    assert "none lights a status" in capsys.readouterr().out


def test_overrides_that_light_nothing_take_down_what_the_map_shows(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.api.data = body(wire())
    assert rig.run(monkeypatch) == 0
    assert rig.shown()
    rig.clock.now += timedelta(minutes=1)
    rig.api.data = body(wire(scope="school", id="999999999999"))
    assert rig.run(monkeypatch) == 0
    assert rig.shown() == {}


def test_none_takes_every_status_down_and_then_writes_nothing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.api.data = body(wire(), wire(id="2900003", status="open"))
    assert rig.run(monkeypatch) == 0
    assert rig.shown()
    rig.clock.now += timedelta(minutes=1)
    gets = rig.api.gets
    assert rig.run(monkeypatch, none=True) == 0
    assert rig.api.gets == gets  # no API was read
    assert rig.shown() == {}
    opens = DirPublisher(rig.host).read("v1/live/opens.json")
    assert opens is not None
    assert OpensFile.model_validate_json(opens).opens == ()
    published = rig.public()
    rig.clock.now += timedelta(minutes=10)
    assert rig.run(monkeypatch, none=True) == 0
    assert rig.public() == published


def test_a_private_school_status_is_published_in_the_nearest_schools_zone(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.api.data = body(wire(scope="school", id=SCHOOL_IDS[7]))
    assert rig.run(monkeypatch) == 0
    assert rig.shown() == {(7, "2026-11-17"): (Status.CLOSED, None, None)}


def test_the_api_and_none_cannot_both_be_named() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["live", "overrides", "--api", "https://x/", "--none"])
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["live", "overrides"])


def test_printed_lines_carry_counts_and_codes_only(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig.api.data = body(wire(), wire(scope="school", id="999999999999"))
    assert rig.run(monkeypatch) == 0
    out = capsys.readouterr()
    text = out.out + out.err
    assert "overrides: 2 active; 2 statuses, 0 open; withheld not_in_directory 1" in text
    for school_id in (*SCHOOL_IDS, "999999999999", "2900001"):
        assert school_id not in text


def test_an_override_is_a_model_with_no_note() -> None:
    assert "note" not in Override.model_fields


# --- the web's manual statuses file, written here -------------------------------------------

GOLDEN = Path(__file__).parent / "golden"
MANUAL = "synthetic_manual_closings"
"""The file web/e2e/live-origin.spec.ts serves as the admin's statuses, and the web's
closings contract test reads back to its rows (like every ``golden/synthetic_*.json``)."""


def test_the_webs_manual_statuses_file_is_what_the_overrides_pass_writes(tmp_path: Path) -> None:
    """The e2e's SYNTHETIC directory (four schools of one district in Central time): Alpha
    closed and Beta on a 2-hour delayed start, set at 6:40 AM on 2026-01-12 until the end of
    the day, published at 6:50 AM through the resolver, the merge and the publisher."""
    stamp = DirectoryStamp(generated_on=date(2026, 9, 25), schools=4, districts=1)
    four = DeployedSchools(
        stamp=stamp,
        content_sha256=CONTENT,
        school_ids=tuple(f"29000000000{index}" for index in range(1, 5)),
        district_ids=("2900000",),
        district_of=(0, 0, 0, 0),
        zones=("America/Chicago",),
    )
    now = datetime(2026, 1, 12, 12, 50, tzinfo=UTC)
    times = {
        "scope": "school",
        "days": ["2026-01-12"],  # "Today"
        "set_at": "2026-01-12T12:40:00Z",
        "expires_at": "2026-01-13T06:00:00Z",
    }
    overrides = parse(
        body(
            wire(**times, id="290000000001"),
            wire(**times, id="290000000002", status="delayed", minutes=120),
        )
    )
    resolved = resolve(overrides, four, now)
    publisher = LivePublisher(
        host=DirPublisher(tmp_path / "host"),
        directory=four.live_directory(),
        state_dir=tmp_path / "state",
        internal_dir=tmp_path / "internal",
        mode=Mode.ON,
    )
    report = publisher.publish(
        with_overrides(EMPTY, resolved.statuses, now),
        now=now,
        healthy_share=1.0,
        edition=EditionVerdict(EditionState.EQUAL, now, stamp=stamp, deployed=stamp),
        alerted=lambda _school: True,
        started=now,
    )
    assert int(report.exit) == 0
    data = (tmp_path / "host" / "v1" / CLOSINGS).read_bytes()
    file = ClosingsFile.from_json_bytes(data)
    pretty = json.dumps(json.loads(data), indent=2, sort_keys=True).encode() + b"\n"
    rows = [
        {
            "school": row.school,
            "day": row.day.isoformat(),
            "status": int(row.status),
            "announced_at": None
            if row.announced_at is None
            else row.announced_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reason": None if row.reason is None else int(row.reason),
            "shift_minutes": row.shift_minutes,
            "clock_minute": row.clock_minute,
            "manual": row.manual,
        }
        for row in sorted(file.closings(), key=lambda item: (item.day, item.school))
    ]
    pretty_rows = json.dumps(rows, indent=2, sort_keys=True).encode() + b"\n"
    golden, golden_rows = GOLDEN / f"{MANUAL}.json", GOLDEN / f"{MANUAL}.rows.json"
    if os.environ.get("SNOWLIGHT_WRITE_GOLDEN") == "1":
        golden.write_bytes(pretty)
        golden_rows.write_bytes(pretty_rows)
    assert golden.read_bytes() == pretty
    assert golden_rows.read_bytes() == pretty_rows
    assert [(row["school"], row["status"], row["shift_minutes"]) for row in rows] == [
        (0, int(Status.CLOSED), None),
        (1, int(Status.DELAYED), 120),
    ]


BORROWED = "borrowed_zones"
"""The zones :meth:`DeployedSchools.borrowed_zones` gives the schools without a district of a
SYNTHETIC directory, which web/src/admin/tests/overview.test.ts checks the admin view works
out the same (its days are named in the zone the overrides pass lights them in). Not named
``synthetic_*``: those are closings files, which the web's closings contract test reads."""


def test_the_admin_views_borrowed_zones_are_the_overrides_pass(tmp_path: Path) -> None:
    """SYNTHETIC: 120 schools across the Pacific-Mountain line of Oregon and Idaho and the
    Central-Eastern line of Tennessee and Kentucky, in 12 districts of four zones by their
    longitude, every fourth school (and every school of district 11) without a zone."""
    del tmp_path
    rng = np.random.default_rng(20261021)
    count = 120
    west = np.arange(count) < count // 2
    lon_e6 = np.where(
        west,
        rng.integers(-121_000_000, -114_000_000, count),
        rng.integers(-89_000_000, -84_000_000, count),
    )
    lat_e6 = np.where(
        west,
        rng.integers(42_000_000, 46_000_000, count),
        rng.integers(35_000_000, 38_000_000, count),
    )
    lines = {True: -117_000_000, False: -86_500_000}
    zones = ("America/Los_Angeles", "America/Boise", "America/Chicago", "America/New_York")
    district_zone = tuple(zones[index // 3] for index in range(12))
    district: list[int | None] = []
    for index in range(count):
        side = bool(west[index])
        band = (0 if side else 2) + int(lon_e6[index] >= lines[side])
        mine = band * 3 + index % 3
        district.append(None if index % 4 == 3 else mine)
    zones_of: list[str | None] = [*district_zone[:11], None]  # district 11: no zone known
    stamp = DirectoryStamp(generated_on=date(2026, 10, 14), schools=count, districts=12)
    places = DeployedSchools(
        stamp=stamp,
        content_sha256=CONTENT,
        school_ids=tuple(f"SYN{index:05d}" for index in range(count)),
        district_ids=tuple(f"99{index:05d}" for index in range(12)),
        district_of=tuple(district),
        zones=tuple(zones_of),
        lon_e6=tuple(int(value) for value in lon_e6),
        lat_e6=tuple(int(value) for value in lat_e6),
    )
    wanted = [index for index in range(count) if places.zone_of(index) is None]
    borrowed = places.borrowed_zones(wanted)
    found = {
        "lon_e6": [int(value) for value in lon_e6],
        "lat_e6": [int(value) for value in lat_e6],
        "district": [-1 if value is None else value for value in district],
        "zones": zones_of,
        "borrowed": {str(index): borrowed[index] for index in sorted(borrowed)},
    }
    pretty = json.dumps(found, indent=1, sort_keys=True).encode() + b"\n"
    golden = GOLDEN / f"{BORROWED}.json"
    if os.environ.get("SNOWLIGHT_WRITE_GOLDEN") == "1":
        golden.write_bytes(pretty)
    assert golden.read_bytes() == pretty
    assert sorted(borrowed) == wanted  # every school without a zone borrows one
    # Each borrows from across a zone line somewhere: the state's one zone would be wrong.
    assert len({borrowed[index] for index in wanted}) == len(zones)


@pytest.mark.parametrize("value", ["On", "ON", "shadow ", "yes"])
def test_the_overrides_job_refuses_a_mode_it_never_took_and_publishes_nothing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    # live overrides reads LIVE_PUBLISH exactly as before the reader landed (the reader's
    # own reading folds case; the admin's job does not change)
    rig.api.data = body(wire())
    assert rig.run(monkeypatch, {"LIVE_PUBLISH": value}) == 1
    assert not rig.host.exists()


def test_the_overrides_job_keeps_its_commit_message_and_its_state_holds_only_its_memory(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[bool] = []
    real = live_cli.make_host

    def host(
        config: live_cli.LiveConfig, env: live_cli.Env, client: httpx.Client, **kwargs: bool
    ) -> Publisher:
        made.append(kwargs.get("name_run", True))
        return real(config, env, client, **kwargs)

    monkeypatch.setattr(live_cli, "make_host", host)
    rig.api.data = body(wire())
    assert rig.run(monkeypatch) == 0
    assert made == [False]  # "Publish the live files", as every commit of the job before
    # the publish job's cache (live-overrides-state) holds this folder: its memory and change
    # log only, never a ledger, unmatched rows, robots rules or a pacer
    state = rig.tmp / "state"
    names = {path.relative_to(state).as_posix() for path in state.rglob("*") if path.is_file()}
    assert "publish.json" in names
    assert all(name == "publish.json" or name.startswith("changes/") for name in names), names
    config = live_cli.LiveConfig(
        host={"kind": "github", "repository": "viaate/snowlight-synthetic"},
        state={},
        site="",
        site_repository="",
    )
    env = {
        "LIVE_HOST_TOKEN": "synthetic",
        "GITHUB_RUN_ID": "4242",
        "GITHUB_WORKFLOW": "live-ingest",
    }
    kept = real(config, env, httpx.Client(), name_run=False)
    assert isinstance(kept, GitHubPublisher)
    assert kept.default_message == DEFAULT_MESSAGE

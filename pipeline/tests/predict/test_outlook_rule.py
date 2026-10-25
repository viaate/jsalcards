"""S7-F's one withdrawal rule (D2), heads-ups and the 05:00 record (spec-f s. 2, 3, 5; GF9's
history cases). SYNTHETIC rows and features only, in a Kansas City zone (America/Chicago)."""

import csv
import io
import itertools
import random
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from predict import world
from snowlight.predict import inputs
from snowlight.predict.alerts_history import HistoryRow, Reach, days_touched, read_season
from snowlight.predict.alerts_live import Memory, live_events, live_heads_ups
from snowlight.predict.outlook_states import (
    INDEX_OF,
    LATE,
    MOMENTS,
    RECORD,
    SAMPLES,
    slot_at,
    slot_of_clock,
    sweep,
    unit_states,
)
from snowlight.predict.situations import (
    HEADS_UP_BY_CODE,
    HeadsUp,
    WeatherClass,
    Window,
    district_class,
    district_heads_up,
    issued_counts,
    morning_record,
    school_class,
    school_state,
)
from snowlight.sources.nws.alerts import parse_active

WINDOW = Window(time(18), time(9), 21)
KC = "America/Chicago"
DAY = date(2025, 1, 7)
"""School day D (a Tuesday); D-1 is Monday 6 January. KC is UTC-6 in January."""


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def local(clock: str, *, before: bool = True) -> datetime:
    """``clock`` local in KC on D-1 (``before``) or D, as UTC."""
    on = DAY - timedelta(days=1) if before else DAY
    return datetime.combine(on, time.fromisoformat(clock), tzinfo=ZoneInfo(KC)).astimezone(UTC)


def row(  # noqa: PLR0913, PLR0917 - one history row's fields
    code: str,
    issued: datetime,
    start: datetime,
    end: datetime | None,
    final_end: datetime | None = None,
    status: str = "EXP",
) -> HistoryRow:
    return HistoryRow(
        2024, f"EAX.{code}.0001.2025", "MOZ028", 1.0, code, issued, start, end,
        final_end or end or start + timedelta(days=3), status,
    )  # fmt: skip


def state(rows: list[HistoryRow], at: datetime) -> tuple[WeatherClass, HeadsUp]:
    return school_state([item.event_issued(at) for item in rows], DAY, KC, WINDOW, at)


# --- rule D2 ------------------------------------------------------------------------------------


def test_a_cancel_after_six_pm_stops_counting_from_its_issue_time() -> None:
    warning = row(
        "WS.W", local("15:00"), local("23:00"), local("12:00", before=False),
        final_end=local("19:30"), status="CAN",
    )  # fmt: skip
    assert state([warning], local("19:15")) == (WeatherClass.SNOW_WARNING, HeadsUp.NONE)
    assert state([warning], local("20:00"))[0] is WeatherClass.NONE
    assert state([warning], morning_record(DAY, KC))[0] is WeatherClass.NONE


def test_a_cancel_after_nine_pm_counts_as_issued_before_it() -> None:
    warning = row(
        "WS.W", local("15:00"), local("23:00"), local("12:00", before=False),
        final_end=local("23:30"), status="CAN",
    )  # fmt: skip
    for clock in ("20:00", "21:00", "22:15"):
        assert state([warning], local(clock))[0] is WeatherClass.SNOW_WARNING
    assert state([warning], local("01:15", before=False))[0] is WeatherClass.NONE
    # The shipped 21:00 snapshot (today's rule) still counts it: D2 is S7-F's alone until F3.
    assert school_class([warning.event(local("21:00"))], DAY, KC, WINDOW, local("21:00")) is (
        WeatherClass.SNOW_WARNING
    )


def test_a_downgrade_reads_as_the_advisory_the_district_woke_up_to() -> None:
    warning = row(
        "WS.W", local("15:00"), local("23:00"), local("12:00", before=False),
        final_end=local("22:00"), status="CAN",
    )  # fmt: skip
    advisory = row("WW.Y", local("22:00"), local("23:00"), local("12:00", before=False))
    assert state([warning, advisory], local("20:00"))[0] is WeatherClass.SNOW_WARNING
    assert state([warning, advisory], morning_record(DAY, KC))[0] is WeatherClass.ADVISORY


def test_an_upgrade_withdraws_the_advisory_for_the_warning() -> None:
    advisory = row(
        "WW.Y", local("12:00"), local("23:00"), local("09:00", before=False),
        final_end=local("21:30"), status="UPG",
    )  # fmt: skip
    warning = row("WS.W", local("21:30"), local("23:00"), local("12:00", before=False))
    assert state([advisory, warning], local("20:00"))[0] is WeatherClass.ADVISORY
    assert state([advisory, warning], local("22:15"))[0] is WeatherClass.SNOW_WARNING


def test_a_watch_cancelled_after_its_start_and_one_cancelled_at_seven_thirty() -> None:
    started = row(
        "WS.A", local("10:00"), local("00:00", before=False), local("12:00", before=False),
        final_end=local("02:00", before=False), status="CAN",
    )  # fmt: skip
    assert state([started], local("01:15", before=False)) == (
        WeatherClass.NONE,
        HeadsUp.WINTER_STORM_WATCH,
    )
    assert state([started], morning_record(DAY, KC))[1] is HeadsUp.NONE
    early = row(
        "WS.A", local("10:00"), local("03:00", before=False), local("12:00", before=False),
        final_end=local("19:30"), status="CAN",
    )  # fmt: skip
    assert state([early], local("19:15"))[1] is HeadsUp.WINTER_STORM_WATCH
    assert state([early], local("20:00"))[1] is HeadsUp.NONE


def test_an_extreme_cold_watch_becomes_a_cold_weather_advisory() -> None:
    watch = row(
        "EC.A", local("04:00"), local("00:00", before=False), local("10:00", before=False),
        final_end=local("15:00"), status="UPG",
    )  # fmt: skip
    advisory = row(
        "CW.Y", local("15:00"), local("00:00", before=False), local("10:00", before=False)
    )
    assert state([watch, advisory], local("14:00"))[1] is HeadsUp.EXTREME_COLD_WATCH
    assert state([watch, advisory], local("16:15"))[1] is HeadsUp.COLD_WEATHER_ADVISORY
    # A heads-up never makes a class.
    assert state([watch, advisory], local("16:15"))[0] is WeatherClass.NONE


def test_an_empty_span_never_counts() -> None:
    empty = row("WS.W", local("15:00"), local("23:00"), local("23:00"))
    assert state([empty], local("20:00"))[0] is WeatherClass.NONE
    backwards = row("WS.W", local("15:00"), local("23:00"), local("22:00"))
    assert not issued_counts(
        backwards.event_issued(local("20:00")), DAY, KC, WINDOW, local("20:00")
    )


def test_a_product_issued_after_the_moment_never_counts_and_the_record_is_at_five() -> None:
    late = row(
        "WS.W",
        local("05:30", before=False),
        local("06:00", before=False),
        local("12:00", before=False),
    )
    assert state([late], morning_record(DAY, KC))[0] is WeatherClass.NONE
    assert state([late], local("05:31", before=False))[0] is WeatherClass.SNOW_WARNING
    assert morning_record(DAY, KC) == local("05:00", before=False)


def test_the_strongest_heads_up_wins_and_the_district_takes_the_half_rule() -> None:
    watch = row("WS.A", local("10:00"), local("23:00"), local("12:00", before=False))
    tropical = row("TR.A", local("09:00"), local("23:00"), None)
    assert state([tropical, watch], local("20:00"))[1] is HeadsUp.WINTER_STORM_WATCH
    heads = [HeadsUp.WINTER_STORM_WATCH, HeadsUp.COLD_WEATHER_ADVISORY, HeadsUp.NONE]
    assert district_heads_up(heads, 0.5) is HeadsUp.COLD_WEATHER_ADVISORY
    assert district_heads_up(heads[:1] * 2 + [HeadsUp.NONE], 0.5) is HeadsUp.WINTER_STORM_WATCH
    assert district_heads_up([], 0.5) is HeadsUp.NONE
    assert district_heads_up([HeadsUp.NONE, HeadsUp.NONE], 0.5) is HeadsUp.NONE


def _counting_matches_the_rule(item: HistoryRow, day: date) -> None:
    found = item.counting(day, KC, WINDOW)
    start = datetime.combine(day - timedelta(days=2), time(0), tzinfo=UTC)
    for step in range(4 * 24 * 4):
        at = start + timedelta(minutes=15 * step)
        expected = issued_counts(item.event_issued(at), day, KC, WINDOW, at)
        inside = found is not None and found[0] <= at and (found[1] is None or at < found[1])
        assert inside is expected, (item, day, at, found)


def test_the_counting_interval_is_the_rule_at_every_moment() -> None:
    rng = random.Random(7)  # noqa: S311 - a fixed sample of rows, not a secret
    base = local("00:00")
    for _ in range(300):
        issued = base + timedelta(minutes=30 * rng.randint(-40, 60))
        start = issued + timedelta(minutes=30 * rng.randint(-10, 40))
        end = None if rng.random() < 0.1 else start + timedelta(minutes=30 * rng.randint(-2, 60))
        final = (end or start) + timedelta(minutes=30 * rng.randint(-50, 20))
        status = rng.choice(["EXP", "CAN", "UPG", "CON"])
        item = row(rng.choice(["WS.W", "WW.Y", "WS.A"]), issued, start, end, final, status)
        for day in days_touched(item, KC):
            _counting_matches_the_rule(item, day)


# --- the sweep ----------------------------------------------------------------------------------


def test_the_sweep_gives_each_moment_the_rule_and_the_district_the_half_rule() -> None:
    rows = [
        row(
            "WS.W", local("15:00"), local("23:00"), local("12:00", before=False),
            final_end=local("23:30"), status="CAN",
        ),
        row("WW.Y", local("23:30"), local("23:00"), local("12:00", before=False)),
        row("WS.A", local("09:00"), local("23:00"), local("12:00", before=False)),
    ]  # fmt: skip
    reach = Reach(
        members={"MOZ028/a": np.array([0, 1], dtype=np.int64)},
        extra={},
        key_of={("MOZ028", 1.0): "MOZ028/a"},
    )
    found = sweep(rows, reach, [KC, KC, KC], WINDOW)
    assert found.rows == 3
    assert sorted(set(found.school.tolist())) == [0, 1]
    day_number = (DAY - date(1970, 1, 1)).days
    mine = (found.school == 0) & (found.day == day_number)
    for k, moment in enumerate(MOMENTS):
        at = moment.at(DAY, KC)
        weather, heads = state(rows, at)
        assert found.weather[mine][0, k] == int(weather), moment.label
        assert (6 - found.heads[mine][0, k]) % 6 == int(heads), moment.label
    # District a holds schools 0, 1 and 2 (school 2 reached by nothing): 2 of 3 is half or more.
    units = unit_states(
        found, np.array([0, 0, 0], dtype=np.int64), np.array([3], dtype=np.int64), 0.5
    )
    on_day = units.day == day_number
    k20 = INDEX_OF["20:00"]
    assert units.weather[on_day][0, k20] == int(WeatherClass.SNOW_WARNING)
    assert units.heads[on_day][0, k20] == int(HeadsUp.WINTER_STORM_WATCH)
    assert units.weather[on_day][0, INDEX_OF["05:00"]] == int(WeatherClass.ADVISORY)
    assert district_class([WeatherClass.ADVISORY] * 2 + [WeatherClass.NONE], 0.5) is (
        WeatherClass.ADVISORY
    )
    # One school of four is not half: district b sees nothing.
    thin = unit_states(
        found, np.array([0, -1, -1], dtype=np.int64), np.array([4], dtype=np.int64), 0.5
    )
    assert not thin.unit.size


def test_moments_never_read_a_forecast_from_after_them() -> None:
    for moment in MOMENTS:
        if moment.sample < 0:
            continue
        sample = SAMPLES[moment.sample]
        assert sample.at(DAY, KC) <= moment.at(DAY, KC), moment.label
        assert sample.slot == moment.slot
    assert [moment.slot for moment in SAMPLES] == [1 + i // 3 for i in range(21)]
    assert [moment.label for moment in LATE] == [
        "10:15", "13:15", "16:15", "19:15", "22:15", "01:15", "04:15",
    ]  # fmt: skip
    assert RECORD.slot == 0


@pytest.mark.parametrize(
    ("clock", "before", "slot"),
    [
        ("06:00", True, 1), ("10:29", True, 1), ("10:30", True, 2), ("13:30", True, 3),
        ("16:30", True, 4), ("19:29", True, 4), ("19:30", True, 5), ("22:30", True, 6),
        ("23:59", True, 6), ("01:29", False, 6), ("01:30", False, 7), ("04:59", False, 7),
        ("05:00", False, 0), ("08:00", False, 0),
    ],
)  # fmt: skip
def test_slots(clock: str, before: bool, slot: int) -> None:
    assert slot_of_clock(time.fromisoformat(clock), before) == slot
    assert slot_at(DAY, KC, local(clock, before=before)) == slot


def test_a_pass_two_days_ahead_is_slot_one_and_after_the_day_is_identity() -> None:
    assert slot_at(DAY, KC, local("20:00") - timedelta(days=1)) == 1
    assert slot_at(DAY, KC, local("20:00") + timedelta(days=2)) == 0


# --- history and live replays agree (GF9) -------------------------------------------------------

COLUMNS = (
    "wfo", "utc_issue", "utc_expire", "utc_prodissue", "utc_init_expire", "phenomena", "gtype",
    "significance", "eventid", "status", "ugc", "area2d", "utc_updated", "product_id", "vtec_year",
)  # fmt: skip


def season_csv(records: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    for record in records:
        writer.writerow(
            {
                "wfo": "EAX", "gtype": "C", "ugc": "MOZ028", "area2d": "1000.5", "utc_updated": "",
                "product_id": "x", "vtec_year": "2025", "eventid": "1", **record,
            }
        )  # fmt: skip
    return out.getvalue()


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


def vtec_time(moment: datetime) -> str:
    return moment.strftime("%y%m%dT%H%MZ")


@pytest.mark.parametrize(
    ("cancel", "action"),
    [("19:30", "CAN"), ("23:30", "CAN"), ("19:30", "UPG"), ("23:30", "UPG")],
)
def test_history_and_the_live_memory_agree_on_a_cancel(cancel: str, action: str) -> None:
    issued, start, end = local("15:00"), local("23:00"), local("12:00", before=False)
    cancelled = local(cancel)
    text = season_csv(
        [
            {
                "phenomena": "WS", "significance": "W", "status": action,
                "utc_issue": stamp(start), "utc_expire": stamp(cancelled),
                "utc_prodissue": stamp(issued), "utc_init_expire": end.strftime("%Y%m%d%H%M"),
            }
        ]
    )  # fmt: skip
    history = read_season(text, 2024)[0]
    assert history.status == action
    assert history.withdrawn_at == cancelled
    vtec = f"KEAX.WS.W.0001.{vtec_time(start)}-{vtec_time(end)}"
    new = world.feature(
        f"/O.NEW.{vtec}/", ("MOZ028",), sent=issued.isoformat(),
        onset=start.isoformat(), ends=end.isoformat(),
    )  # fmt: skip
    can = world.feature(
        f"/O.{action}.{vtec}/", ("MOZ028",), sent=cancelled.isoformat(),
        onset=start.isoformat(), ends=end.isoformat(), message_type="Cancel",
    )  # fmt: skip
    products = [(issued, new), (cancelled, can)]
    for label in ("20:00", "22:15", "05:00"):
        at = MOMENTS[INDEX_OF[label]].at(DAY, KC)
        from_history = school_state([history.event_issued(at)], DAY, KC, WINDOW, at)[0]
        memory = Memory(30)
        alerts = parse_active(
            world.feed_bytes([feature for sent, feature in products if sent <= at], at.isoformat())
        ).alerts
        memory.rebuild(alerts, at)
        events = [item.event.event for item in memory.seen.values()]
        from_live = school_class(events, DAY, KC, WINDOW, at)
        assert from_history is from_live, (cancel, label)


def test_history_and_the_live_memory_agree_on_a_downgrade() -> None:
    # WS.W issued 15:00 for 23:00-12:00, cancelled at 22:00 by the WW.Y that replaces it.
    issued, start, end = local("15:00"), local("23:00"), local("12:00", before=False)
    downgraded = local("22:00")
    text = season_csv(
        [
            {
                "phenomena": "WS", "significance": "W", "status": "CAN", "eventid": "1",
                "utc_issue": stamp(start), "utc_expire": stamp(downgraded),
                "utc_prodissue": stamp(issued), "utc_init_expire": end.strftime("%Y%m%d%H%M"),
            },
            {
                "phenomena": "WW", "significance": "Y", "status": "EXP", "eventid": "2",
                "utc_issue": stamp(start), "utc_expire": stamp(end),
                "utc_prodissue": stamp(downgraded), "utc_init_expire": end.strftime("%Y%m%d%H%M"),
            },
        ]
    )  # fmt: skip
    history = read_season(text, 2024)
    assert [item.code for item in history] == ["WS.W", "WW.Y"]
    warning = f"KEAX.WS.W.0001.{vtec_time(start)}-{vtec_time(end)}"
    advisory = f"KEAX.WW.Y.0002.{vtec_time(start)}-{vtec_time(end)}"
    products = [
        (issued, world.feature(
            f"/O.NEW.{warning}/", ("MOZ028",), sent=issued.isoformat(),
            onset=start.isoformat(), ends=end.isoformat(),
        )),
        (downgraded, world.feature(
            f"/O.CAN.{warning}/", ("MOZ028",), sent=downgraded.isoformat(),
            onset=start.isoformat(), ends=end.isoformat(), message_type="Cancel",
        )),
        (downgraded, world.feature(
            f"/O.NEW.{advisory}/", ("MOZ028",), sent=downgraded.isoformat(),
            onset=start.isoformat(), ends=end.isoformat(), event="Winter Weather Advisory",
        )),
    ]  # fmt: skip
    expected = {
        "20:00": WeatherClass.SNOW_WARNING,
        "22:15": WeatherClass.ADVISORY,
        "05:00": WeatherClass.ADVISORY,
    }
    for label, want in expected.items():
        at = MOMENTS[INDEX_OF[label]].at(DAY, KC)
        from_history = school_state(
            [item.event_issued(at) for item in history], DAY, KC, WINDOW, at
        )
        memory = Memory(30)
        alerts = parse_active(
            world.feed_bytes([feature for sent, feature in products if sent <= at], at.isoformat())
        ).alerts
        memory.rebuild(alerts, at)
        events = [item.event.event for item in memory.seen.values()]
        from_live = school_class(events, DAY, KC, WINDOW, at)
        assert from_history[0] is from_live is want, label
        assert from_history[1] is HeadsUp.NONE, label


def test_a_watch_reads_alike_as_a_csv_row_and_as_a_cap_feature() -> None:
    issued, start, end = local("10:00"), local("23:00"), local("12:00", before=False)
    text = season_csv(
        [
            {
                "phenomena": "WS", "significance": "A", "status": "EXP",
                "utc_issue": stamp(start), "utc_expire": stamp(end),
                "utc_prodissue": stamp(issued), "utc_init_expire": end.strftime("%Y%m%d%H%M"),
            },
            {
                "phenomena": "WS", "significance": "W", "status": "EXP",
                "utc_issue": stamp(start), "utc_expire": stamp(end),
                "utc_prodissue": stamp(issued), "utc_init_expire": end.strftime("%Y%m%d%H%M"),
            },
        ]
    )  # fmt: skip
    history = read_season(text, 2024, codes=HEADS_UP_BY_CODE.keys())
    assert [item.code for item in history] == ["WS.A"]
    vtec = f"KEAX.WS.A.0001.{vtec_time(start)}-{vtec_time(end)}"
    feed = parse_active(
        world.feed_bytes(
            [
                world.feature(
                    f"/O.NEW.{vtec}/", ("MOZ028",), sent=issued.isoformat(),
                    onset=start.isoformat(), ends=end.isoformat(), event="Winter Storm Watch",
                )
            ],
            issued.isoformat(),
        )
    )  # fmt: skip
    assert live_events(feed) == []  # the pass reads no heads-up yet (F3)
    live = live_heads_ups(feed)[0].event
    at = local("20:00")
    assert school_state([live], DAY, KC, WINDOW, at) == school_state(
        [history[0].event_issued(at)], DAY, KC, WINDOW, at
    )
    assert (live.code, live.issued, live.start, live.end) == (
        "WS.A",
        history[0].issued,
        history[0].start,
        history[0].end,
    )


def test_retired_codes_read_as_the_heads_up_that_replaced_them() -> None:
    for retired, current in (
        ("BZ.A", "WS.A"),
        ("LE.A", "WS.A"),
        ("WC.A", "EC.A"),
        ("WC.Y", "CW.Y"),
    ):
        assert HEADS_UP_BY_CODE[retired] is HEADS_UP_BY_CODE[current]
    counts = {2016: {"BZ.A": 3, "WC.Y": 1}, 2017: {"BZ.A": 1}, 2023: {"EC.A": 2}, 2024: {"WC.A": 1}}
    assert inputs.code_problems(counts) == [
        "2017-18: 1 rows of BZ.A",
        "2023-24: 2 rows of EC.A",
        "2024-25: 1 rows of WC.A",
    ]
    assert all(code in inputs.HEADS_UP_CODES for code in HEADS_UP_BY_CODE)


def test_tropical_watches_run_until_their_event_ended() -> None:
    text = season_csv(
        [
            {
                "phenomena": "TR", "significance": "A", "status": "UPG", "eventid": "1009",
                "utc_issue": "2024-09-24 21:06", "utc_expire": "2024-09-25 03:05",
                "utc_prodissue": "2024-09-24 21:06", "utc_init_expire": "202410152106",
            }
        ]
    )  # fmt: skip
    found = read_season(text, 2024, codes=HEADS_UP_BY_CODE.keys())[0]
    assert found.end is None
    assert found.withdrawn_at == utc("2024-09-25T03:05:00")


def test_every_combination_of_moments_is_ordered_within_a_night() -> None:
    times = [moment.at(DAY, KC) for moment in (*SAMPLES, RECORD)]
    assert all(a < b for a, b in itertools.pairwise(times))

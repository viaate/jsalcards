"""The real status reader behind :class:`~snowlight.live.resolve.StatusReader` (T22), and the
live guards run with it end to end."""

from datetime import timedelta

import pytest

from live.world import ALPHA_DISTRICT, ALPHA_SCHOOL, CHICAGO, World, at, lit, reasons, row
from snowlight.live.resolve import f5_reader

READER = f5_reader()


def test_t22_the_probe_matrix() -> None:
    def read(text: str, when: str) -> tuple[str, list[str], float]:
        parsed = READER(text, posted_at=at(when), tz=CHICAGO)
        days = sorted(day.isoformat() for item in parsed.schedule for day in item.dates)
        return parsed.kind, days, parsed.confidence

    assert read("Closed", "2026-11-17 11:00") == ("closed", ["2026-11-17"], 0.9)  # 05:00
    assert read("Closed", "2026-11-17 18:00")[:2] == ("other", [])  # noon: undated
    assert read("Closed", "2026-11-18 01:00") == ("closed", ["2026-11-18"], 0.9)  # 19:00
    assert read("Closed Monday", "2026-11-18 12:00") == ("other", [], 0.3)  # two days later
    assert READER("Open", posted_at=at("2026-11-17 11:00"), tz=CHICAGO).says_open


def _world() -> World:
    world = World(reader=READER)
    world.read(at("2026-11-17 02:00"), [])
    world.read(at("2026-11-17 11:00"), [])
    return world


def test_real_reader_dates_a_watched_row_and_never_a_later_day() -> None:
    world = _world()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-17 11:06"))) == {(0, "2026-11-17"): "CLOSED"}
    world.read(at("2026-11-18 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-18 11:01"))) == {}


def test_real_reader_overnight_outage_and_day_long_outage() -> None:
    world = World(reader=READER)
    world.read(at("2026-11-17 02:00"), [])
    world.read(at("2026-11-17 04:00"), [])
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-17 11:01"))) == {(0, "2026-11-17"): "CLOSED"}
    long = World(reader=READER)
    long.read(at("2026-11-16 11:00"), [])
    long.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL)])
    assert reasons(long.resolve()) == ["interval_disagrees"]


def test_real_reader_cold_rows_stay_dark() -> None:
    world = World(reader=READER)
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL), row(ALPHA_DISTRICT, "Closed Monday")])
    assert reasons(world.resolve()) == ["unknown_start", "unknown_start"]


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Activities cancelled", "not_status"),
        ("Closed Saturday", "weak"),
        ("Possible closing", "not_status"),
        ("Closed due to water main break", "not_weather"),
        ("Closed - teacher work day", "not_weather"),
        ("2 hour delay - opening at 10:00", None),
        ("Remote learning", None),
        ("Early dismissal at 1:00 PM", None),
        # the wording classes the replay builder left open (addendum 6)
        ("Closing rescinded Monday evening", "note"),
        ("Closings cancelled for Nov 17, 18 and 19", "note"),
        ("Closed. Snow packet day, buses resume Wednesday", "wording"),
        ("Closed - Flexible Learning Day", "wording"),
        ("Closed - Digital Day", "wording"),
        ("Closed - Flex learning", "wording"),
        ("SAT testing moved, closed", "wording"),
        ("Closed Monday, 16th & 17th", "wording"),
        ("Closed - Lincoln Elementary only", "note"),
    ],
)
def test_real_reader_gates(text: str, reason: str | None) -> None:
    world = _world()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, text)])
    assert reasons(world.resolve()) == [reason]
    assert bool(lit(world.publish(at("2026-11-17 11:06")))) == (reason is None)


def test_real_reader_a_district_row_narrowed_to_some_schools_lights_none() -> None:
    world = _world()
    rows = [
        row(ALPHA_DISTRICT, "Closed - intermediate schools"),
        row("SYNTHETIC Escambia County Public Schools", "Bus routes 4 and 7 cancelled, closed"),
    ]
    world.read(at("2026-11-17 11:05"), rows)
    assert lit(world.publish(at("2026-11-17 11:06"))) == {}


def test_real_reader_a_retraction_naming_its_time_still_retracts() -> None:
    world = World(reader=READER)
    for minute in ("02:00", "11:00"):
        world.read(at(f"2026-11-17 {minute}"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_DISTRICT)])
    assert len(lit(world.publish(at("2026-11-17 11:06")))) == 2
    world.read(at("2026-11-17 11:30"), [row(ALPHA_DISTRICT, "Closing rescinded Monday evening")])
    merged = world.publish(at("2026-11-17 11:31"))
    assert lit(merged) == {}
    assert merged.withheld["superseded"] == 2  # the old row gives nothing
    dissents = [r.derived.dissent for source in world.resolve() for r in source.rows if r.present]
    assert dissents == [()]  # and the retraction stands against every day


def test_real_reader_open_statements() -> None:
    world = _world()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "School is open")])
    merged = world.publish(at("2026-11-17 11:06"))
    assert lit(merged) == {}
    assert [(s.school, s.day.isoformat()) for s in merged.opens] == [(0, "2026-11-17")]
    evening = _world()
    evening.read(at("2026-11-17 23:00"), [])
    evening.read(at("2026-11-17 23:05"), [row(ALPHA_SCHOOL, "Open")])
    assert evening.publish(at("2026-11-17 23:06")).opens == ()
    tomorrow = _world()
    tomorrow.read(at("2026-11-17 23:00"), [])
    tomorrow.read(at("2026-11-17 23:05"), [row(ALPHA_SCHOOL, "School is open tomorrow")])
    opens = tomorrow.publish(at("2026-11-17 23:06")).opens
    assert [s.day.isoformat() for s in opens] == ["2026-11-18"]
    assert opens[0].at - at("2026-11-17 23:05") == timedelta(0)

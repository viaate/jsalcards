"""The reviewers' probes of rounds 1-4, kept as a regression suite: every scenario they
built must stay dark, or show exactly the status it shows now. Every name and status is
SYNTHETIC; the probes model real posting sequences (scratchpad critic-r1-*, critic-r2-*,
critic-r3-*, and round 4's critic-r1-0/probes v1-v4). A case marked "follow-up" shows a
reviewer's should-fix item kept for a later round: its kind is pinned, not its detail."""

import dataclasses
import random
import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from live.world import (
    ALPHA,
    ALPHA_DISTRICT,
    ALPHA_SCHOOL,
    World,
    _school,
    accepted,
    at,
    default_matcher,
    directory,
    district_schools,
    lit,
    reasons,
    row,
    station,
    stub_reader,
)
from snowlight.classify import ParsedStatus, parse_status
from snowlight.live.ledger import Outcome, SeenRow
from snowlight.live.resolve import LiveDirectory, ParsedLike, StatusReader, f5_reader

A = "gray-synthetic"
TEGNA = "tegna-synthetic"
FLASH = "flashalert-synthetic"
NEXSTAR = "nexstar-synthetic"
F5 = f5_reader()
READERS: tuple[tuple[str, StatusReader], ...] = (("stub", stub_reader), ("f5", F5))
type Lit = dict[tuple[int, str], str]


def _many(count: int = 10, reader: StatusReader = stub_reader) -> World:
    extra = [
        _school(f"5000000000{n:02d}", 100 + n, name=f"SYNTHETIC S{n}", district=f"50000{n:02d}")
        for n in range(count)
    ]
    world = World(reader=reader, dir=directory(extra))
    for n in range(count):
        world.matcher.table[f"SYNTHETIC S{n}"] = accepted(direct=(f"5000000000{n:02d}",))
    return world


def _rows(texts: list[str]) -> list[SeenRow]:
    return [row(f"SYNTHETIC S{n}", text) for n, text in enumerate(texts)]


def _each(texts: list[str], day: str) -> Lit:
    shown = {"Closed": "CLOSED", "2 hour delay": "DELAYED"}
    return {(100 + n, day): shown[text] for n, text in enumerate(texts)}


def _warm_monday(world: World) -> None:
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:00"), [])


def _weak(text: str, *, posted_at: datetime, tz: str) -> ParsedLike:
    """The real reader, at 0.75 for a text marked ``[weak]``."""
    parsed: ParsedStatus = parse_status(text.replace(" [weak]", ""), posted_at=posted_at, tz=tz)
    return parsed._replace(confidence=0.75) if "[weak]" in text else parsed


# --- round 1 (critic-r1-0 p1-p7, critic-r1-1 probe_version) ----------------------------------


def test_r1_p1_rows_with_no_read_the_school_day_before_stay_dark() -> None:
    world = _many()
    world.read(at("2026-11-16 09:00"), [], outcome=Outcome.EMPTY)
    world.read(at("2026-11-16 10:00"), _rows(["2 hour delay"] * 10))
    assert lit(world.publish(at("2026-11-16 10:05"))) == {}
    world.read(at("2026-11-16 11:00"), _rows(["Closed"] * 6 + ["2 hour delay"] * 4))
    assert lit(world.publish(at("2026-11-16 11:05"))) == {}
    assert set(reasons(world.resolve())) == {"stale_unproven"}


def test_r1_p1_an_empty_spell_then_the_same_rows_stays_dark() -> None:
    world = World()
    world.read(at("2026-11-16 09:00"), [], outcome=Outcome.EMPTY)
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-16 11:05"))) == {}
    moment = at("2026-11-16 12:00")
    while moment < at("2026-11-17 10:55"):
        world.read(moment, [], outcome=Outcome.EMPTY)
        moment += timedelta(hours=1)
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-17 11:05"))) == {}
    other = World()
    other.read(at("2026-11-16 09:00"), [], outcome=Outcome.EMPTY)
    other.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    other.read(at("2026-11-16 23:00"), [])
    other.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(other.publish(at("2026-11-17 11:05"))) == {}


@pytest.mark.parametrize("successor", ["Open", "See district website", "2 hour delay [conf=0.75]"])
def test_r1_p1_p2_a_withheld_successor_darkens_its_listing(successor: str) -> None:
    cold = World()
    cold.read(at("2026-11-16 09:00"), [], outcome=Outcome.EMPTY)
    cold.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    cold.read(at("2026-11-16 17:55"), [row(ALPHA_SCHOOL)])
    cold.read(at("2026-11-16 18:00"), [row(ALPHA_SCHOOL, successor)])
    merged = cold.publish(at("2026-11-16 18:05"))
    assert (lit(merged), merged.opens) == ({}, ())
    warm = World()
    _warm_monday(warm)
    warm.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(warm.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}
    warm.read(at("2026-11-16 17:55"), [row(ALPHA_SCHOOL)])
    warm.read(at("2026-11-16 18:00"), [row(ALPHA_SCHOOL, successor)])
    merged = warm.publish(at("2026-11-16 18:05"))
    assert (lit(merged), merged.opens) == ({}, ())


def test_r1_p2_a_batch_of_upgrades_lights_the_new_statuses() -> None:
    for changed in (6, 5):
        world = _many()
        _warm_monday(world)
        world.read(at("2026-11-16 10:30"), _rows(["2 hour delay"] * 10))
        assert lit(world.publish(at("2026-11-16 10:35"))) == _each(
            ["2 hour delay"] * 10, "2026-11-16"
        )
        texts = ["Closed"] * changed + ["2 hour delay"] * (10 - changed)
        world.read(at("2026-11-16 11:00"), _rows(texts))
        assert lit(world.publish(at("2026-11-16 11:05"))) == _each(texts, "2026-11-16")
        for moment in ("2026-11-16 15:00", "2026-11-16 20:00"):
            world.read(at(moment), _rows(texts))
            assert lit(world.publish(at(moment))) == _each(texts, "2026-11-16")


def test_r1_p2_rows_taken_down_and_back_the_next_morning_stay_dark() -> None:
    world = World()
    _warm_monday(world)
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}
    world.read(at("2026-11-16 23:00"), [])
    world.publish(at("2026-11-16 23:05"))
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-17 11:05"))) == {}


def test_r1_p2_a_school_row_older_than_a_district_closing_from_another_list() -> None:
    world = World(stations={A: station(A), TEGNA: station(TEGNA)})
    _warm_monday(world)
    world.read(at("2026-11-13 15:00"), [], source=TEGNA)
    world.read(at("2026-11-16 11:20"), [], source=TEGNA)
    world.read(at("2026-11-16 11:25"), [row(ALPHA_SCHOOL, "2 hour delay")])
    world.read(at("2026-11-16 11:30"), [row(ALPHA_SCHOOL, "2 hour delay")])
    world.read(at("2026-11-16 11:40"), [row(ALPHA_DISTRICT, "Closed")], source=TEGNA)
    assert lit(world.publish(at("2026-11-16 11:45"))) == {(1, "2026-11-16"): "CLOSED"}


def test_r1_p3_the_reader_changes_its_answer_only_at_whole_and_half_hours() -> None:
    """The interval samples read every :00 and :30, so every stretch of constant answer is
    read: the real reader's answer for these texts changes only on those minutes."""
    tz = "America/Chicago"
    start = datetime(2026, 11, 16, 0, 0, tzinfo=ZoneInfo(tz))
    texts = [
        "Closed",
        "2 Hour Delay",
        "Open",
        "Open today",
        "Closed - Opening Tuesday",
        "Early dismissal",
        "Closed tomorrow",
        "Open on regular schedule",
        "Remote learning",
    ]
    for text in texts:
        before: tuple[object, ...] | None = None
        for minute in range(24 * 60):
            moment = (start + timedelta(minutes=minute)).astimezone(UTC)
            parsed = parse_status(text, posted_at=moment, tz=tz)
            now = (
                parsed.kind,
                tuple((entry.kind, tuple(entry.dates)) for entry in parsed.schedule),
                round(parsed.confidence, 2),
                parsed.says_open,
                tuple(sorted(parsed.notes)),
            )
            assert before is None or now == before or minute % 30 == 0, (text, minute)
            before = now


@pytest.mark.parametrize(
    ("successor", "opens"),
    [
        ("Open", []),
        ("Open on regular schedule", []),
        ("Open Tuesday", ["2026-11-17"]),
        ("Will be open", []),
    ],
)
def test_r1_p4_an_evening_closing_reversed_at_21_00_is_dark_on_tuesday(
    successor: str, opens: list[str]
) -> None:
    world = World(reader=F5)
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 22:00"), [])
    world.read(at("2026-11-17 00:00"), [row(ALPHA_SCHOOL)])  # Monday 18:00 CT
    assert lit(world.publish(at("2026-11-17 00:05"))) == {(0, "2026-11-17"): "CLOSED"}
    world.read(at("2026-11-17 02:55"), [row(ALPHA_SCHOOL)])
    world.read(at("2026-11-17 03:00"), [row(ALPHA_SCHOOL, successor)])  # 21:00 CT
    assert lit(world.publish(at("2026-11-17 03:05"))) == {}
    world.read(at("2026-11-17 12:55"), [row(ALPHA_SCHOOL, successor)])
    merged = world.publish(at("2026-11-17 13:00"))
    assert lit(merged) == {}
    assert [o.day.isoformat() for o in merged.opens] == opens


def test_r1_p5_a_future_day_taken_down_early_and_a_cold_retraction() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-17 23:55"), [])
    world.read(at("2026-11-18 00:00"), [row(ALPHA_SCHOOL, "Closed Thursday")])
    assert lit(world.publish(at("2026-11-18 00:05"))) == {}
    moment = at("2026-11-18 11:00")
    while moment <= at("2026-11-19 13:00"):
        world.read(moment, [])
        moment += timedelta(hours=1)
    assert lit(world.publish(at("2026-11-19 13:00"))) == {}
    two = World(stations={A: station(A), TEGNA: station(TEGNA)})
    two.read(at("2026-11-13 15:00"), [])
    two.read(at("2026-11-16 10:55"), [])
    two.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(two.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}
    two.read(at("2026-11-16 12:00"), [row(ALPHA_SCHOOL, "Closing rescinded")], source=TEGNA)
    assert lit(two.publish(at("2026-11-16 12:05"))) == {}


P6_LIT: dict[str, str] = {
    "Closed - NTI Day": "REMOTE",
    "Closed - AMI Day": "REMOTE",
    "Closed. Blizzard bag day": "REMOTE",
    "Closed - eLearning day": "REMOTE",
    "Closed; virtual learning day": "REMOTE",
    "Closed - Non-Traditional Instruction day": "REMOTE",
    "Closed for students, staff report": "CLOSED",
    "Closed - power outage": "CLOSED",
    "Closed today; open tomorrow": "CLOSED",
    "No school": "CLOSED",
    "Asynchronous learning day": "REMOTE",
    "Closed - Virtual Day": "REMOTE",
    "Closed, Remote Instruction Day": "REMOTE",
    "Closed - Distance learning": "REMOTE",
    "Closed - Cyber day": "REMOTE",
    "Closed - snow day #3": "CLOSED",
}
P6_DARK = (
    "Closing rescinded Monday evening",
    "Snow packet day, buses resume Wednesday",
    "Flexible Learning Day",
    "Digital Day",
    "Closed - SAT testing moved",
    "Closings cancelled for Nov 16, 17 and 18",
    "Closed Monday, 16th & 17th",
    "Closed - Remote learning for grades 6-12",
    "Closed - Staff development day",
    "Closed for Thanksgiving break",
    "Closed - no heat",
    "Closed - Elementary schools only",
    "Closed - Middle school only",
    "Closed - North campus",
    "Closed - bus routes 12 and 14 on snow routes",
    "Closed except Lincoln Elementary",
    "2 Hour Delay - No AM Pre-K",
    "Closed - All schools except high school",
    "Was closed, now on 2 hour delay",
    "Closed (updated: now 2 hour delay)",
    "Delay cancelled - schools open on time",
    "Closed - Teacher workday",
    "Closed - Election day",
    "Closed - Weather permitting",
    "May close early",
    "Closed. Activities cancelled",
)


@pytest.mark.parametrize("text", [*P6_LIT, *P6_DARK])
def test_r1_p6_a_district_rows_wording_classes(text: str) -> None:
    world = World(reader=F5)
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:55"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_DISTRICT, text)])
    shown = lit(world.publish(at("2026-11-16 11:05")))
    status = P6_LIT.get(text)
    expected = {} if status is None else {(0, "2026-11-16"): status, (1, "2026-11-16"): status}
    assert shown == expected


def test_r1_p7_a_district_retraction_whose_interval_overlaps_a_school_closing() -> None:
    world = World(reader=F5, stations={A: station(A), TEGNA: station(TEGNA)})
    for source in (A, TEGNA):
        world.read(at("2026-11-13 15:00"), [], source=source)
    world.read(at("2026-11-16 10:30"), [], source=TEGNA)
    world.read(at("2026-11-16 10:50"), [])
    world.read(at("2026-11-16 10:55"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-16 10:56"))) == {(0, "2026-11-16"): "CLOSED"}
    world.read(at("2026-11-16 11:00"), [row(ALPHA_DISTRICT, "Closing rescinded")], source=TEGNA)
    assert lit(world.publish(at("2026-11-16 11:05"))) == {}


def test_r1_version_a_vanished_retraction_holds_across_a_new_process() -> None:
    other = "gray-other"
    world = World()
    world.stations[other] = station(other)
    for source in (A, other):
        for moment in ("2026-11-16 15:00", "2026-11-17 10:00", "2026-11-17 10:55"):
            world.read(at(moment), [], source=source)
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 11:05"), [], source=other)
    assert lit(world.publish(at("2026-11-17 11:06"))) == {(0, "2026-11-17"): "CLOSED"}
    world.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL, "Closing rescinded")], source=other)
    assert lit(world.publish(at("2026-11-17 11:21"))) == {}
    world.read(at("2026-11-17 11:40"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 11:40"), [], source=other)
    assert lit(world.publish(at("2026-11-17 11:41"))) == {}
    world.version += "|other-seed"
    assert lit(world.publish(at("2026-11-17 11:42"))) == {}


# --- round 2 (critic-r2-0 q1-q5, critic-r2-1 pa, pb, pe) --------------------------------------

Q1 = [
    ("stub", "Closed", "Closed due to snow"),
    ("stub", "2 hour delay", "2 hour delay due to snow"),
    ("stub", "Closed", "Closed until further notice"),
    ("f5", "Closed", "Closed due to snow"),
    ("f5", "Closed", "Closed - Snow"),
    ("f5", "Closed", "Closed - weather"),
    ("f5", "2 Hour Delay", "2 Hour Delay - 10:00 AM start"),
    ("f5", "Closed", "CLOSED: Inclement weather"),
    ("f5", "2 Hour Delay", "2 Hour Delay, no AM pre-K"),
    ("f5", "Closed", "Closed. No activities"),
]


@pytest.mark.parametrize(("label", "before", "after"), Q1)
def test_r2_q1_a_monday_row_re_worded_on_tuesday_is_dark_on_tuesday(
    label: str, before: str, after: str
) -> None:
    world = World(reader=dict(READERS)[label])
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 09:55"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL, before)])
    assert len(lit(world.publish(at("2026-11-16 11:05")))) == 1
    moment = at("2026-11-16 12:00")
    while moment < at("2026-11-17 11:00"):
        world.read(moment, [row(ALPHA_SCHOOL, before)])
        world.publish(moment + timedelta(minutes=1))
        moment += timedelta(hours=1)
    world.read(at("2026-11-17 10:55"), [row(ALPHA_SCHOOL, before)])
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL, after)])
    assert lit(world.publish(at("2026-11-17 11:05"))) == {}
    assert lit(world.publish(at("2026-11-17 15:00"))) == {}


def test_r2_q2_a_whole_list_re_rendered_overnight_is_dark_on_tuesday() -> None:
    extra = district_schools("2000009", 10, 20)
    for label, reader in READERS:
        for before, after in (("Closed", "Closed due to snow"), ("Closed", "Closed - Snow")):
            matcher = default_matcher()
            names = [f"SYNTHETIC Row {school.record.id}" for school in extra]
            for name, school in zip(names, extra, strict=True):
                matcher.table[name] = accepted(direct=(school.record.id,))
            world = World(reader=reader, dir=directory(extra), matcher=matcher)
            world.read(at("2026-11-13 15:00"), [])
            world.read(at("2026-11-16 09:55"), [])
            world.read(at("2026-11-16 11:00"), [row(name, before) for name in names])
            assert len(lit(world.publish(at("2026-11-16 11:05")))) == 10, label
            moment = at("2026-11-16 12:00")
            while moment <= at("2026-11-17 10:55"):
                world.read(moment, [row(name, before) for name in names])
                moment += timedelta(hours=1)
            world.read(at("2026-11-17 11:00"), [row(name, after) for name in names])
            assert lit(world.publish(at("2026-11-17 15:00"))) == {}, (label, after)


def test_r2_q2_a_repeat_closing_a_week_later_and_a_cold_upgrade() -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 09:55"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}
    world.read(at("2026-11-16 18:00"), [])
    world.read(at("2026-11-16 18:05"), [])
    moment = at("2026-11-16 19:00")
    while moment < at("2026-11-23 10:55"):
        world.read(moment, [])
        moment += timedelta(hours=2)
    world.read(at("2026-11-23 10:55"), [])
    world.read(at("2026-11-23 11:00"), [row(ALPHA_SCHOOL), row(ALPHA_DISTRICT, "2 hour delay")])
    assert lit(world.publish(at("2026-11-23 11:05"))) == {(1, "2026-11-23"): "DELAYED"}
    cold = World()
    cold.read(at("2026-11-16 10:00"), [row(ALPHA_SCHOOL, "2 hour delay")])
    cold.read(at("2026-11-16 10:55"), [row(ALPHA_SCHOOL, "2 hour delay")])
    cold.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(cold.publish(at("2026-11-16 11:05"))) == {}


@pytest.mark.parametrize("school_text", ["Closed [conf=0.75]", "Closed possible", None])
def test_r2_q3_a_schools_own_withheld_row_stands_against_its_district(
    school_text: str | None,
) -> None:
    world = World()
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 09:55"), [])
    if school_text is None:
        world.read(at("2026-11-16 11:00"), [row(ALPHA_DISTRICT, "2 hour delay")])
        world.read(at("2026-11-16 19:00"), [row(ALPHA_DISTRICT, "2 hour delay"), row(ALPHA_SCHOOL)])
        merged = world.publish(at("2026-11-16 19:05"))
    else:
        rows = [row(ALPHA_DISTRICT, "2 hour delay"), row(ALPHA_SCHOOL, school_text)]
        world.read(at("2026-11-16 11:00"), rows)
        merged = world.publish(at("2026-11-16 11:05"))
    assert lit(merged) == {(1, "2026-11-16"): "DELAYED"}


Q4_LIT: dict[str, tuple[str, ...]] = {
    "E-learning day": ("REMOTE",),
    "Remote learning day": ("REMOTE",),
    "Virtual learning day": ("REMOTE",),
    "Closed today. Open tomorrow": ("CLOSED",),
    "No school Monday, school Tuesday": ("CLOSED",),
    "Closed Monday; Tuesday 2 hour delay": ("CLOSED", "DELAYED"),
    "Closed Mon 11/16": ("CLOSED",),
    "Closed due to power outage": ("CLOSED",),
    "Closed (staff report)": ("CLOSED",),
    "Closed for in-person, virtual day": ("REMOTE",),
}
Q4_DARK_ALONE = (
    "Closing rescinded Monday evening",
    "Closings cancelled for Nov 16, 17 and 18",
    "Snow packet day, buses resume Wednesday",
    "Flexible Learning Day",
    "Digital Day",
    "Flex learning",
    "Closed for SAT testing",
    "SAT",
    "Closed Monday, 16th & 17th",
    "Intermediate schools closed",
    "Closed: bus routes 5 and 7 only",
    "Closed - North side schools only",
    "Lincoln and Adams Elementary closed",
    "Closed for Thanksgiving break",
    "Closure cancelled",
    "Not closed",
    "Closing lifted",
    "Will open on time",
    "Schools will reopen Monday",
    "Delay cancelled - schools open on time",
    "2 hour delay rescinded",
    "Early dismissal at 1pm canceled",
    "Closed due to water main break",
    "Closed - no heat",
    "Teacher workday",
    "Closed for students, staff report on time",
)
Q4_OLDER_CLOSING_STANDS = (
    "Schools will reopen Monday",
    "Closed for students, staff report on time",
)
"""Rows that leave an older "Closed" lit (neither says the school is open that day)."""


@pytest.mark.parametrize("text", [*Q4_LIT, *Q4_DARK_ALONE])
def test_r2_q4_wording_classes_alone_and_against_an_older_closing(text: str) -> None:
    alone = World(reader=F5)
    alone.read(at("2026-11-13 15:00"), [])
    alone.read(at("2026-11-16 10:55"), [])
    alone.read(at("2026-11-16 11:00"), [row(ALPHA_DISTRICT, text)])
    shown = lit(alone.publish(at("2026-11-16 11:05")))
    assert tuple(sorted(set(shown.values()))) == Q4_LIT.get(text, ())
    versus = World(reader=F5)
    versus.stations[FLASH] = station(FLASH)
    versus.read(at("2026-11-13 15:00"), [])
    versus.read(at("2026-11-16 10:25"), [])
    versus.read(at("2026-11-16 10:30"), [row(ALPHA_DISTRICT)])
    versus.read(at("2026-11-13 15:00"), [], source=FLASH)
    versus.read(at("2026-11-16 10:55"), [], source=FLASH)
    versus.read(at("2026-11-16 11:00"), [row(ALPHA_DISTRICT, text)], source=FLASH)
    shown = lit(versus.publish(at("2026-11-16 11:05")))
    expected = Q4_LIT.get(text, ("CLOSED",) if text in Q4_OLDER_CLOSING_STANDS else ())
    assert tuple(sorted(set(shown.values()))) == expected


def test_r2_q5_a_two_day_storm_with_the_list_cleared_between() -> None:
    for label, reader in READERS:
        for second in (A, FLASH):
            world = World(reader=reader)
            world.stations[FLASH] = station(FLASH)
            for source in (A, FLASH):
                world.read(at("2026-11-13 15:00"), [], source=source)
            world.read(at("2026-11-16 10:55"), [])
            world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
            assert lit(world.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}
            moment = at("2026-11-16 16:00")
            while moment <= at("2026-11-17 10:55"):
                world.read(moment, [])
                world.read(moment, [], source=FLASH)
                moment += timedelta(minutes=30)
            if second == A:
                world.read(
                    at("2026-11-17 11:00"), [row(ALPHA_SCHOOL), row(ALPHA_DISTRICT, "2 hour delay")]
                )
            else:
                world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL)])
                world.read(
                    at("2026-11-17 11:00"), [row(ALPHA_DISTRICT, "2 hour delay")], source=FLASH
                )
            shown = lit(world.publish(at("2026-11-17 11:05")))
            assert shown == {(1, "2026-11-17"): "DELAYED"}, (label, second)


def _retraction_then_vanish(world: World) -> None:
    for source in (A, NEXSTAR):
        for moment in ("2026-11-16 08:00", "2026-11-17 09:00", "2026-11-17 10:00"):
            world.read(at(moment), [], source=source)
    world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 10:12"))) == {(0, "2026-11-17"): "CLOSED"}
    world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, "Closing rescinded")], source=NEXSTAR)
    assert lit(world.publish(at("2026-11-17 10:22"))) == {}
    world.read(at("2026-11-17 10:30"), [row("SYNTHETIC Pacific School")], source=NEXSTAR)
    world.read(at("2026-11-17 10:30"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 10:32"))) == {(7, "2026-11-17"): "CLOSED"}


def test_r2_pa_a_vanished_retraction_follows_its_school_to_a_new_edition() -> None:
    world = World(stations={A: station(A), NEXSTAR: station(NEXSTAR)})
    _retraction_then_vanish(world)
    swap = {0: 6, 6: 0}
    old = world.dir
    world.dir = LiveDirectory(
        schools={
            sid: dataclasses.replace(school, index=swap.get(school.index, school.index))
            for sid, school in old.schools.items()
        },
        district_sizes=old.district_sizes,
        edition="synthetic-edition-2",
    )
    world.read(at("2026-11-17 10:40"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 10:40"), [row("SYNTHETIC Pacific School")], source=NEXSTAR)
    assert lit(world.publish(at("2026-11-17 10:42"))) == {(7, "2026-11-17"): "CLOSED"}
    assert world.dir.schools[ALPHA[0]].index == 6


@pytest.mark.parametrize("bad", ["{not json", '"just a string"', '{"withheld": null}'])
def test_r2_pb_a_damaged_payload_of_a_present_row_is_derived_again(bad: str) -> None:
    world = World()
    world.read(at("2026-11-16 08:00"), [])
    world.read(at("2026-11-17 10:00"), [])
    world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.publish(at("2026-11-17 10:12"))
    world.ledger._db.execute("UPDATE derived SET payload = ?", (bad,))
    world.ledger._db.commit()
    assert lit(world.publish(at("2026-11-17 10:14"))) == {(0, "2026-11-17"): "CLOSED"}
    with pytest.raises(sqlite3.IntegrityError):
        world.ledger._db.execute("UPDATE derived SET payload = NULL")


def test_r2_pe_terms_that_stop_permitting_polling_darken_the_source() -> None:
    world = World()
    world.read(at("2026-11-16 08:00"), [])
    world.read(at("2026-11-17 10:00"), [])
    world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 10:12"))) == {(0, "2026-11-17"): "CLOSED"}
    world.pollable["gray"] = False
    world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 10:22"))) == {}
    assert reasons(world.resolve()) == ["terms"]


# --- round 3 (critic-r3-0 c1-c4, critic-r3-1 c1-c4) -------------------------------------------

C1: list[tuple[str, str, Lit]] = [
    ("Closed tomorrow", "2026-11-18 00:00", {}),
    ("Closed tomorrow", "2026-11-17 11:00", {}),
    ("Closed tomorrow due to snow", "2026-11-18 00:00", {}),
    ("2 hour delay tomorrow", "2026-11-18 00:00", {(0, "2026-11-18"): "DELAYED"}),
    # reads Wednesday either way, so it is dated from Monday's posting (R4C-B1): 37 hours,
    # longer than any interval read, so it is dark (fail dark)
    ("Closed Wednesday", "2026-11-18 00:00", {}),
    ("Closed Wednesday", "2026-11-17 22:00", {(0, "2026-11-18"): "CLOSED"}),
    ("Closed tomorrow", "2026-11-17 02:00", {(0, "2026-11-17"): "CLOSED"}),
]


@pytest.mark.parametrize(("text", "when", "shown"), C1)
def test_r3_c1_a_monday_closing_re_worded_later(text: str, when: str, shown: Lit) -> None:
    world = World(reader=F5)
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:55"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}
    moment = at("2026-11-16 11:30")
    while moment < at(when):
        world.read(moment, [row(ALPHA_SCHOOL)])
        moment += timedelta(minutes=30)
    world.read(at(when), [row(ALPHA_SCHOOL, text)])
    assert lit(world.publish(at(when) + timedelta(minutes=5))) == shown


C2_TEXTS = (
    "Open",
    "Open - normal schedule",
    "School is open",
    "Schools will be open",
    "Will be open as normal",
    "Open on time",
    "Normal schedule",
)


@pytest.mark.parametrize("text", C2_TEXTS)
def test_r3_c2_an_open_statement_from_another_source(text: str) -> None:
    cases = [
        ("2026-11-17 01:00", "2026-11-17 03:00", "2026-11-17 11:00", []),
        ("2026-11-17 11:00", "2026-11-17 19:00", "2026-11-17 19:05", []),
        ("2026-11-17 11:00", "2026-11-17 12:30", "2026-11-17 12:35", [(0, "2026-11-17")]),
    ]
    for close_at, open_at, publish, opens in cases:
        world = World(reader=F5)
        world.stations[FLASH] = station(FLASH)
        for source in (A, FLASH):
            world.read(at("2026-11-13 15:00"), [], source=source)
            world.read(at("2026-11-16 15:00"), [], source=source)
            world.read(at(close_at) - timedelta(minutes=5), [], source=source)
        world.read(at(close_at), [row(ALPHA_SCHOOL)])
        world.read(at(open_at) - timedelta(minutes=5), [], source=FLASH)
        world.read(at(open_at), [row(ALPHA_SCHOOL)])
        world.read(at(open_at), [row(ALPHA_SCHOOL, text)], source=FLASH)
        merged = world.publish(at(publish))
        assert lit(merged) == {}, (text, open_at)
        assert [(o.school, o.day.isoformat()) for o in merged.opens] == opens, (text, open_at)


def _district_delay_then_school(reader: StatusReader, school_text: str, school_at: str) -> Lit:
    world = World(reader=reader)
    world.stations[FLASH] = station(FLASH)
    for source in (A, FLASH):
        world.read(at("2026-11-16 15:00"), [], source=source)
        world.read(at("2026-11-17 10:55"), [], source=source)
    world.read(at("2026-11-17 11:00"), [row(ALPHA_DISTRICT, "2 hour delay")])
    world.read(at(school_at) - timedelta(minutes=5), [], source=FLASH)
    world.read(at(school_at), [row(ALPHA_DISTRICT, "2 hour delay")])
    world.read(at(school_at), [row(ALPHA_SCHOOL, school_text)], source=FLASH)
    return lit(world.publish(at(school_at) + timedelta(minutes=5)))


@pytest.mark.parametrize(
    ("label", "text", "when", "shown"),
    [
        ("stub", "3 hour delay [conf=0.75]", "2026-11-17 11:30", {0: "DELAYED", 1: "DELAYED"}),
        ("stub", "3 hour delay", "2026-11-17 11:30", {0: "DELAYED", 1: "DELAYED"}),
        ("f5", "3 hour delay", "2026-11-17 11:30", {0: "DELAYED", 1: "DELAYED"}),
        ("f5", "Delayed 3 hours, opens at 11:00", "2026-11-17 11:30", {0: "DELAYED", 1: "DELAYED"}),
        ("f5", "2 hour delay, opens at 10:30", "2026-11-17 11:30", {0: "DELAYED", 1: "DELAYED"}),
        ("f5", "Early dismissal at 1 pm", "2026-11-17 11:30", {0: "EARLY_DISMISSAL", 1: "DELAYED"}),
        ("f5", "Early dismissal at 1 pm", "2026-11-17 19:00", {0: "EARLY_DISMISSAL", 1: "DELAYED"}),
    ],
)
def test_r3_c3_a_schools_own_newer_row_beside_its_districts_delay(
    label: str, text: str, when: str, shown: dict[int, str]
) -> None:
    found = _district_delay_then_school(dict(READERS)[label], text, when)
    assert {school: status for (school, day), status in found.items() if day == "2026-11-17"} == (
        shown
    )


@pytest.mark.parametrize(
    ("text", "kinds"),
    [
        ("3 hour delay [weak]", {"DELAYED"}),  # follow-up: the weak row's detail is not compared
        ("Delayed 3 hours, opens at 11:00 [weak]", {"DELAYED"}),  # follow-up, as above
        ("Closed [weak]", set()),  # another kind: the school's own row stands, dark
    ],
)
def test_r3_c3b_a_schools_own_weak_row_beside_its_districts_delay(
    text: str, kinds: set[str]
) -> None:
    found = _district_delay_then_school(_weak, text, "2026-11-17 11:30")
    assert {status for (school, _day), status in found.items() if school == 0} == kinds
    assert found[(1, "2026-11-17")] == "DELAYED"


@pytest.mark.parametrize(
    ("closed", "other", "text", "when", "shown"),
    [
        (ALPHA_DISTRICT, ALPHA_DISTRICT, "Open", "2026-11-17 19:00", {}),
        (
            ALPHA_DISTRICT,
            ALPHA_DISTRICT,
            "Schools will be open",  # Tuesday 21:00 CT: Wednesday open, Tuesday stays closed
            "2026-11-18 03:00",
            {(0, "2026-11-17"): "CLOSED", (1, "2026-11-17"): "CLOSED"},
        ),
        # follow-up: a newer weak row of another kind at the same level leaves the closing lit
        (ALPHA_SCHOOL, ALPHA_SCHOOL, "2 hour delay [weak]", "2026-11-17 11:30", None),
        (ALPHA_DISTRICT, ALPHA_DISTRICT, "2 hour delay [weak]", "2026-11-17 11:30", None),
    ],
)
def test_r3_c4_a_newer_row_at_the_same_level_from_another_source(
    closed: str, other: str, text: str, when: str, shown: Lit | None
) -> None:
    world = World(reader=_weak)
    world.stations[FLASH] = station(FLASH)
    for source in (A, FLASH):
        world.read(at("2026-11-16 15:00"), [], source=source)
        world.read(at("2026-11-17 10:55"), [], source=source)
    world.read(at("2026-11-17 11:00"), [row(closed)])
    world.read(at(when) - timedelta(minutes=5), [], source=FLASH)
    world.read(at(when), [row(closed)])
    world.read(at(when), [row(other, text)], source=FLASH)
    found = lit(world.publish(at(when) + timedelta(minutes=5)))
    if shown is None:
        assert set(found.values()) <= {"CLOSED"}  # never the weak row's own status
    else:
        assert found == shown


@pytest.mark.parametrize("change", ["terms", "no_endpoint"])
def test_r3_c1_a_retraction_from_a_source_whose_terms_or_status_change(change: str) -> None:
    world = World(stations={A: station(A), NEXSTAR: station(NEXSTAR)})
    for source in (A, NEXSTAR):
        for moment in ("2026-11-16 08:00", "2026-11-17 09:00", "2026-11-17 10:00"):
            world.read(at(moment), [], source=source)
    world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 10:12"))) == {(0, "2026-11-17"): "CLOSED"}
    world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, "Closing rescinded")], source=NEXSTAR)
    assert lit(world.publish(at("2026-11-17 10:22"))) == {}
    if change == "terms":
        world.pollable["nexstar"] = False
    else:
        world.stations[NEXSTAR] = world.stations[NEXSTAR].model_copy(update={"status": change})
    world.read(at("2026-11-17 10:30"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 10:32"))) == {}


@pytest.mark.parametrize("fix", ["states", "leaids"])
def test_r3_c2_a_registry_correction(fix: str) -> None:
    world = World()
    world.read(at("2026-11-16 08:00"), [])
    world.read(at("2026-11-17 10:00"), [])
    world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 10:12"))) == {(0, "2026-11-17"): "CLOSED"}
    if fix == "states":
        world.stations[A] = station(A, states=("CA", "FL", "MO", "MT"))
    else:
        world.stations[A] = station(A, leaids=("9999999",))
    world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 10:22"))) == {}


@pytest.mark.parametrize("damage", ["drift", "corrupt"])
def test_r3_c3_a_vanished_retraction_whose_stored_derivation_no_longer_reads(
    damage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from snowlight.live import resolve  # noqa: PLC0415 - patched below

    world = World(stations={A: station(A), NEXSTAR: station(NEXSTAR)})
    _retraction_then_vanish(world)
    if damage == "drift":
        monkeypatch.setattr(resolve, "MATCH_REASONS", resolve.MATCH_REASONS - {"alias"})
        world.version += "|synthetic-f6-v2"
    else:
        world.ledger._db.execute("UPDATE derived SET payload = '{not json'")
        world.ledger._db.commit()
    world.read(at("2026-11-17 10:40"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 10:40"), [row("SYNTHETIC Pacific School")], source=NEXSTAR)
    assert lit(world.publish(at("2026-11-17 10:42"))) == {(7, "2026-11-17"): "CLOSED"}


def test_r3_c4_the_same_reads_into_two_ledgers_publish_the_same() -> None:
    names = [ALPHA_SCHOOL, ALPHA_DISTRICT, "SYNTHETIC Pacific School", "SYNTHETIC Eastern School"]
    texts = ["Closed", "Closed due to snow", "2 hour delay", "Closing rescinded", "Open",
             "Closed [conf=0.75]", "Remote learning"]  # fmt: skip
    for seed in range(25):
        rnd = random.Random(seed)  # noqa: S311 - a seeded test sequence
        worlds = [World(stations={A: station(A), NEXSTAR: station(NEXSTAR)}) for _ in range(2)]
        moment = at("2026-11-16 20:00")
        outs: list[list[object]] = [[], []]
        for _step in range(rnd.randint(4, 14)):
            moment += timedelta(minutes=rnd.choice([5, 10, 30, 60, 200]))
            for source in (A, NEXSTAR):
                rows: list[SeenRow] = []
                for name in names:
                    if rnd.random() < 0.5:
                        rows.append(row(name, rnd.choice(texts)))
                        if rnd.random() < 0.15:
                            rows.append(row(name, rnd.choice(texts)))
                for world in worlds:
                    world.read(moment, list(rows), source=source)
            for number, world in enumerate(worlds):
                merged = world.publish(moment + timedelta(minutes=1))
                outs[number].append((lit(merged), [o.to_public_json() for o in merged.opens]))
        assert outs[0] == outs[1], seed


# --- round 4 (critic-r1-0/probes v1_reword_order, v2_open_cross, v3_terms, v4_schedule) -------


def _v1(  # noqa: PLR0913 - one posting sequence
    reader: StatusReader,
    first: str,
    reworded: str,
    reversal: str,
    *,
    posted: str = "2026-11-16 16:00",
    reversed_at: str = "2026-11-17 16:00",
    reworded_at: str = "2026-11-17 18:00",
    name: str = ALPHA_SCHOOL,
) -> tuple[Lit, Lit]:
    world = World(reader=reader)
    world.stations[FLASH] = station(FLASH)
    for source in (A, FLASH):
        world.read(at("2026-11-13 15:00"), [], source=source)
        world.read(at("2026-11-16 15:00"), [], source=source)
        world.read(at(posted) - timedelta(minutes=5), [], source=source)
    world.read(at(posted), [row(name, first)])
    moment = at(posted) + timedelta(minutes=30)
    while moment < at(reversed_at):
        world.read(moment, [row(name, first)])
        world.read(moment, [], source=FLASH)
        moment += timedelta(minutes=30)
    world.read(at(reversed_at), [row(name, reversal)], source=FLASH)
    world.read(at(reversed_at), [row(name, first)])
    after_reversal = lit(world.publish(at(reversed_at) + timedelta(minutes=5)))
    moment = at(reversed_at) + timedelta(minutes=30)
    while moment < at(reworded_at):
        world.read(moment, [row(name, first)])
        world.read(moment, [row(name, reversal)], source=FLASH)
        moment += timedelta(minutes=30)
    world.read(at(reworded_at), [row(name, reworded)])
    world.read(at(reworded_at), [row(name, reversal)], source=FLASH)
    return after_reversal, lit(world.publish(at(reworded_at) + timedelta(minutes=5)))


V1_MORNING = {"posted": "2026-11-17 11:00", "reversed_at": "2026-11-17 12:30",
              "reworded_at": "2026-11-17 13:00"}  # fmt: skip
type V1Case = tuple[str, StatusReader, str, str, str, dict[str, str]]
V1: list[V1Case] = [
    ("f5", F5, "Closed Wednesday", "Closed Wednesday due to snow", "Open Wednesday", {}),
    ("f5", F5, "Closed Wednesday", "Closed Wednesday due to snow",
     "Schools will be open Wednesday", {}),
    ("f5", F5, "Closed Wed Nov 18", "Closed Wednesday, Nov. 18", "Open Wednesday", {}),
    ("f5", F5, "Closed Wednesday", "Closed Wednesday due to snow", "Closing canceled", {}),
    ("f5", F5, "Closed Wednesday", "Closed Wednesday due to snow", "Open Wednesday",
     {"name": ALPHA_DISTRICT}),
    ("stub", stub_reader, "Closed Wednesday", "Closed Wednesday due to snow", "Open Wednesday",
     {}),
    ("f5", F5, "Closed", "Closed due to snow", "Open", V1_MORNING),
    ("f5", F5, "Closed", "Closed due to snow", "Closing canceled", V1_MORNING),
    ("stub", stub_reader, "Closed", "Closed due to snow", "Open", V1_MORNING),
]  # fmt: skip


@pytest.mark.parametrize("case", V1)
def test_r4_v1_a_re_worded_row_after_another_sources_reversal_stays_dark(case: V1Case) -> None:
    label, reader, first, reworded, reversal, extra = case
    assert _v1(reader, first, reworded, reversal, **extra) == ({}, {}), label


EVE = ("2026-11-17 01:00", "2026-11-17 03:00", "2026-11-17 11:00")
MID = ("2026-11-17 11:00", "2026-11-17 19:00", "2026-11-17 19:05")
MORN = ("2026-11-17 11:00", "2026-11-17 12:30", "2026-11-17 12:35")
V2_LEVELS: list[tuple[tuple[str, str, str], str, str, str, Lit]] = [
    # the district's other school stays closed when only one school says open
    *((when, ALPHA_DISTRICT, ALPHA_SCHOOL, "Open", {(1, "2026-11-17"): "CLOSED"})
      for when in (EVE, MID, MORN)),
    *((when, ALPHA_SCHOOL, ALPHA_DISTRICT, text, {})
      for when in (EVE, MID, MORN) for text in ("Open", "Schools will be open")),
]  # fmt: skip
V2_STAYS = {
    # about another day: correct
    ("mid", "Open tomorrow"),
    ("mid", "Will be open tomorrow"),
    ("eve", "Open today"),
    # follow-up for the f5 reader (R4C-S1): read as not_status
    ("eve", "Reopened"),
    ("mid", "Reopened"),
    ("eve", "Rescinded"),
    ("mid", "Rescinded"),
}
V2_TEXTS = ["Open tomorrow", "Will open on time", "Open regular hours", "Classes as scheduled",
            "School is in session", "Closing canceled", "Closure canceled", "No longer closed",
            "Reopened", "Now open", "Back to normal schedule", "Regular schedule", "On time",
            "Open as usual", "Normal hours", "Closing cancelled - schools open",
            "Open, normal schedule", "Will be open tomorrow", "Open today",
            "Rescinded"]  # fmt: skip


def _v2(times: tuple[str, str, str], a_name: str, b_name: str, text: str) -> Lit:
    close_at, open_at, publish_at = times
    world = World(reader=F5)
    world.stations[FLASH] = station(FLASH)
    for source in (A, FLASH):
        world.read(at("2026-11-13 15:00"), [], source=source)
        world.read(at("2026-11-16 15:00"), [], source=source)
        world.read(at(close_at) - timedelta(minutes=5), [], source=source)
    world.read(at(close_at), [row(a_name, "Closed")])
    world.read(at(open_at) - timedelta(minutes=5), [], source=FLASH)
    world.read(at(open_at), [row(a_name, "Closed")])
    world.read(at(open_at), [row(b_name, text)], source=FLASH)
    return lit(world.publish(at(publish_at)))


@pytest.mark.parametrize(("times", "a_name", "b_name", "text", "shown"), V2_LEVELS)
def test_r4_v2_an_open_statement_across_levels(
    times: tuple[str, str, str], a_name: str, b_name: str, text: str, shown: Lit
) -> None:
    assert _v2(times, a_name, b_name, text) == shown


@pytest.mark.parametrize("when", ["eve", "mid"])
@pytest.mark.parametrize("text", V2_TEXTS)
def test_r4_v2_open_and_retraction_wordings_from_another_source(text: str, when: str) -> None:
    found = _v2(EVE if when == "eve" else MID, ALPHA_SCHOOL, ALPHA_SCHOOL, text)
    assert found == ({(0, "2026-11-17"): "CLOSED"} if (when, text) in V2_STAYS else {})


@pytest.mark.parametrize("vanish", [False, True])
@pytest.mark.parametrize("bump", [False, True])
@pytest.mark.parametrize("mode", ["terms", "no_endpoint"])
@pytest.mark.parametrize(
    "text", ["Closing rescinded", "Open", "Closing canceled", "Open on time", "Not closed"]
)
def test_r4_v3_a_reversal_from_a_source_then_refused_or_inactive(
    text: str, mode: str, *, bump: bool, vanish: bool
) -> None:
    world = World(reader=F5, stations={A: station(A), NEXSTAR: station(NEXSTAR)})
    for source in (A, NEXSTAR):
        for moment in ("2026-11-16 08:00", "2026-11-17 09:00", "2026-11-17 10:00"):
            world.read(at(moment), [], source=source)
    world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, text)], source=NEXSTAR)
    assert lit(world.publish(at("2026-11-17 10:22"))) == {}
    if vanish:
        world.read(at("2026-11-17 10:25"), [], source=NEXSTAR)
        world.read(at("2026-11-17 10:27"), [], source=NEXSTAR)
    if mode == "terms":
        world.pollable["nexstar"] = False
    else:
        world.stations[NEXSTAR] = world.stations[NEXSTAR].model_copy(update={"status": mode})
    if bump:
        world.version += "-bumped"
    world.read(at("2026-11-17 10:30"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 10:32"))) == {}


V4: list[tuple[str, str | None]] = [
    ("Normal schedule", "2026-11-17"),
    ("Open - normal schedule", "2026-11-17"),
    ("On a regular schedule", "2026-11-17"),
    ("Regular schedule", "2026-11-17"),
    ("Normal schedule today", "2026-11-17"),
    ("Open - regular schedule", "2026-11-17"),
    ("Open on a normal schedule", "2026-11-17"),
    ("Schools will operate on a normal schedule", "2026-11-17"),
    ("Open, regular hours", "2026-11-17"),
    ("Normal school day", "2026-11-17"),
    ("Regular school hours", None),  # follow-up for the f5 reader (R4C-S1): not_status
    ("Open - normal schedule tomorrow", "2026-11-18"),
]


@pytest.mark.parametrize(("text", "day"), V4)
def test_r4_v4_normal_schedule_wordings_in_the_morning_are_open_signals(
    text: str, day: str | None
) -> None:
    world = World(reader=F5)
    world.read(at("2026-11-16 15:00"), [])
    world.read(at("2026-11-17 12:25"), [])
    world.read(at("2026-11-17 12:30"), [row(ALPHA_SCHOOL, text)])
    merged = world.publish(at("2026-11-17 12:35"))
    assert lit(merged) == {}
    assert [(o.school, o.day.isoformat()) for o in merged.opens] == (
        [] if day is None else [(0, day)]
    )

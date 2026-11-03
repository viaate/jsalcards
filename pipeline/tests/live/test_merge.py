"""Merge: latest wins, conflicts, open signals, vanished rows, ufn, holds, expiry, breaker (T8,
T9, T12)."""

import dataclasses
import itertools
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from live.world import (
    ALPHA_DISTRICT,
    ALPHA_SCHOOL,
    World,
    accepted,
    at,
    directory,
    district_schools,
    lit,
    row,
    station,
    stub_reader,
)
from snowlight.live import merge as merge_module
from snowlight.live.guards import Rules
from snowlight.live.merge import Item, school_today
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import Closing, ClosingsFile
from snowlight.schemas.vocab import REASON_BY_LABEL, Reason

A = "gray-synthetic"
B = "nexstar-synthetic"


def _two() -> World:
    world = World(stations={A: station(A), B: station(B)})
    for source in (A, B):
        world.read(at("2026-11-17 02:00"), [], source=source)  # Monday evening local
        world.read(at("2026-11-17 11:00"), [], source=source)
    return world


def test_t8a_the_latest_first_sighting_wins() -> None:
    world = _two()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "2 hour delay")], source=A)
    world.read(at("2026-11-17 11:10"), [], source=B)
    world.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL)], source=B)
    assert lit(world.publish(at("2026-11-17 11:21"))) == {(0, "2026-11-17"): "CLOSED"}
    downgrade = _two()
    downgrade.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=A)
    downgrade.read(at("2026-11-17 11:10"), [], source=B)
    downgrade.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL, "2 hour delay")], source=B)
    merged = downgrade.publish(at("2026-11-17 11:21"))
    assert lit(merged) == {(0, "2026-11-17"): "DELAYED"}
    (closing,) = merged.closings
    assert (closing.shift_minutes, closing.clock_minute) == (120, 600)


def test_rows_whose_posting_intervals_overlap_cannot_be_ordered() -> None:
    world = _two()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "2 hour delay")], source=A)
    world.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL)], source=B)  # posted 11:00 to 11:20
    merged = world.publish(at("2026-11-17 11:21"))
    assert lit(merged) == {}
    assert merged.withheld["conflict"] == 1


def test_t8b_a_conflicting_tie_is_withheld_and_an_identical_one_merges() -> None:
    world = _two()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "2 hour delay")], source=A)
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=B)
    merged = world.publish(at("2026-11-17 11:06"))
    assert lit(merged) == {}
    assert merged.withheld["conflict"] == 1
    same = _two()
    same.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=A)
    same.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed due to snow")], source=B)
    merged = same.publish(at("2026-11-17 11:06"))
    assert lit(merged) == {(0, "2026-11-17"): "CLOSED"}
    assert merged.closings[0].reason is Reason.WINTER_STORM  # the one reason a row names
    assert merged.provenance[0]["sources"] == 2


def test_t8c_a_newer_open_statement_retracts_and_is_kept_as_a_signal() -> None:
    world = _two()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=A)
    world.read(at("2026-11-17 11:10"), [], source=B)
    world.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL, "Open")], source=B)
    merged = world.publish(at("2026-11-17 11:21"))
    assert lit(merged) == {}
    assert merged.withheld["retracted"] == 1
    (signal,) = merged.opens
    assert (signal.school, signal.day.isoformat(), signal.source_id) == (0, "2026-11-17", B)
    assert signal.to_public_json() == {
        "school": 0,
        "day": "2026-11-17",
        "kind": "open",
        "at": "2026-11-17T11:20:00+00:00",
        "confidence": 0.9,
    }
    assert signal.to_private_json()["source_id"] == B
    older = _two()
    older.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Open")], source=A)
    older.read(at("2026-11-17 11:10"), [], source=B)
    older.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL)], source=B)
    merged = older.publish(at("2026-11-17 11:21"))
    assert lit(merged) == {(0, "2026-11-17"): "CLOSED"}
    assert merged.opens == ()


def test_open_signals_never_light_and_never_come_from_an_evening_undated_banner() -> None:
    world = _two()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Open")], source=A)
    merged = world.publish(at("2026-11-17 11:06"))
    assert lit(merged) == {}
    assert [(s.school, s.day.isoformat()) for s in merged.opens] == [(0, "2026-11-17")]
    evening = _two()
    evening.read(at("2026-11-17 23:00"), [], source=A)
    evening.read(at("2026-11-17 23:05"), [row(ALPHA_SCHOOL, "Open")], source=A)
    assert evening.publish(at("2026-11-17 23:06")).opens == ()
    dated = _two()
    dated.read(at("2026-11-17 23:00"), [], source=A)
    dated.read(at("2026-11-17 23:05"), [row(ALPHA_SCHOOL, "Open Wednesday")], source=A)
    assert [s.day.isoformat() for s in dated.publish(at("2026-11-17 23:06")).opens] == [
        "2026-11-18"
    ]


def test_t8d_a_vanished_row_is_kept_through_its_day_and_fast_vanishes_are_logged() -> None:
    world = _two()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=A)
    world.publish(at("2026-11-17 11:06"))
    world.read(at("2026-11-17 11:25"), [], source=A)  # unconfirmed: the list emptied
    world.read(at("2026-11-17 11:30"), [], source=A)
    merged = world.publish(at("2026-11-17 11:31"))
    assert lit(merged) == {(0, "2026-11-17"): "CLOSED"}
    (vanish,) = merged.fast_vanishes
    assert (vanish.school, vanish.sources) == (0, (A,))
    assert vanish.gone_at - vanish.first_seen == timedelta(minutes=25)
    (held,) = merged.held_vanishes
    assert (held.school, held.sources, held.gone_at) == (0, (A,), at("2026-11-17 11:30"))
    assert merged.provenance[0]["present"] is False
    world.read(at("2026-11-17 16:00"), [], source=A)
    assert lit(world.publish(at("2026-11-17 16:01"))) == {(0, "2026-11-17"): "CLOSED"}
    world.read(at("2026-11-18 11:00"), [], source=A)
    assert lit(world.publish(at("2026-11-18 11:01"))) == {}
    retracting = _two()
    retracting.rules = Rules(vanish_retracts=True)
    retracting.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=A)
    retracting.publish(at("2026-11-17 11:06"))
    retracting.read(at("2026-11-17 11:25"), [], source=A)
    retracting.read(at("2026-11-17 11:30"), [], source=A)
    assert lit(retracting.publish(at("2026-11-17 11:31"))) == {}


def test_a_slow_vanish_is_not_logged() -> None:
    world = _two()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=A)
    world.publish(at("2026-11-17 11:06"))
    world.read(at("2026-11-17 12:55"), [], source=A)
    world.read(at("2026-11-17 13:00"), [], source=A)
    assert world.publish(at("2026-11-17 13:01")).fast_vanishes == ()


def test_t8e_a_school_row_beats_its_district_row_at_equal_time() -> None:
    world = _two()
    world.read(
        at("2026-11-17 11:05"),
        [row(ALPHA_DISTRICT, "2 hour delay"), row(ALPHA_SCHOOL)],
        source=A,
    )
    assert lit(world.publish(at("2026-11-17 11:06"))) == {
        (0, "2026-11-17"): "CLOSED",
        (1, "2026-11-17"): "DELAYED",
    }


def test_t8f_until_further_notice_covers_at_most_three_school_days() -> None:
    world = World()
    world.read(at("2026-11-13 02:00"), [])  # Thursday evening local
    world.read(at("2026-11-13 11:00"), [])  # Friday morning
    world.read(at("2026-11-13 11:05"), [row(ALPHA_SCHOOL, "Closed until further notice")])
    found = {}
    for day in ("2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18"):
        world.read(at(f"{day} 12:00"), [row(ALPHA_SCHOOL, "Closed until further notice")])
        found[day] = sorted(lit(world.publish(at(f"{day} 12:01"))))
    assert found == {
        "2026-11-13": [(0, "2026-11-13")],
        "2026-11-16": [(0, "2026-11-16")],
        "2026-11-17": [(0, "2026-11-17")],
        "2026-11-18": [],
    }
    gone = World()
    gone.read(at("2026-11-13 02:00"), [])
    gone.read(at("2026-11-13 11:00"), [])
    gone.read(at("2026-11-13 11:05"), [row(ALPHA_SCHOOL, "Closed until further notice")])
    gone.publish(at("2026-11-13 11:06"))
    gone.read(at("2026-11-16 11:55"), [])
    gone.read(at("2026-11-16 12:00"), [])
    assert lit(gone.publish(at("2026-11-16 12:01"))) == {}


def test_t8g_announced_is_the_earliest_since_the_status_last_changed() -> None:
    world = _two()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=A)
    world.read(at("2026-11-17 11:10"), [row(ALPHA_SCHOOL, "Closed due to snow")], source=B)
    (closing,) = world.publish(at("2026-11-17 11:11")).closings
    assert closing.announced_at == at("2026-11-17 11:05")
    stamped = _two()
    stamp = at("2026-11-17 10:58")
    stamped.read(
        at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, row_stamp=stamp, row_date="4:58 AM")], source=A
    )
    (closing,) = stamped.publish(at("2026-11-17 11:06")).closings
    assert closing.announced_at == stamp


def test_t8h_a_source_not_held_contributes_nothing() -> None:
    world = _two()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=A)
    merged = world.publish(at("2026-11-17 11:06"), held={A: False, B: True})
    assert lit(merged) == {}
    assert merged.withheld["stale_source"] == 1


def test_t9a_expiry_follows_each_school_s_own_zone() -> None:
    world = World()
    world.read(at("2026-10-26 23:00"), [])  # Monday evening Central
    world.read(at("2026-10-27 14:00"), [])
    world.read(
        at("2026-10-27 14:05"),
        [row(ALPHA_SCHOOL, "Closed Oct 27"), row("SYNTHETIC Pacific School", "Closed Oct 27")],
    )
    merged = world.publish(at("2026-10-28 05:30"))  # 00:30 CDT, 22:30 PDT the day before
    assert lit(merged) == {(7, "2026-10-27"): "CLOSED"}
    assert merged.withheld["past_day"] == 1


def test_t9b_a_future_day_appears_once_inside_the_window() -> None:
    world = World()
    world.read(at("2026-11-17 02:00"), [])
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed Nov 20")])
    merged = world.publish(at("2026-11-17 12:00"))
    assert lit(merged) == {}
    assert merged.withheld["out_of_window"] == 1
    world.read(at("2026-11-19 18:00"), [row(ALPHA_SCHOOL, "Closed Nov 20")])
    assert lit(world.publish(at("2026-11-19 18:01"))) == {(0, "2026-11-20"): "CLOSED"}


def test_t12_the_breaker_drops_a_source_over_its_limit() -> None:
    schools = district_schools("6000000", 60, 200)
    world = World(dir=directory(schools))
    world.matcher.table["SYNTHETIC Wide District"] = accepted(
        via=tuple(s.record.id for s in schools)
    )
    world.read(at("2026-11-17 02:00"), [])
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row("SYNTHETIC Wide District")])
    merged = world.publish(at("2026-11-17 11:06"))
    assert lit(merged) == {}
    assert merged.breakers == ("gray-synthetic",)
    assert merged.withheld["breaker"] == 60
    world.rules = Rules(breaker_limits={"gray-synthetic": 20})
    assert len(lit(world.publish(at("2026-11-17 11:06")))) == 60


def test_school_today_takes_the_latest_zone() -> None:
    moment = at("2026-11-17 05:30")
    assert school_today(("America/Chicago",), moment).isoformat() == "2026-11-16"
    assert school_today(("America/Chicago", "America/New_York"), moment).isoformat() == "2026-11-17"


def test_a_newer_dissent_from_a_source_no_longer_held_still_stands() -> None:
    world = _two()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=A)
    world.publish(at("2026-11-17 11:06"))
    world.read(at("2026-11-17 11:10"), [], source=B)  # B's rows are surely newer than A's
    world.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL, "Closing rescinded")], source=B)
    world.resolve()
    world.read(at("2026-11-17 11:25"), [row(ALPHA_SCHOOL, "Open")], source=B)
    merged = world.publish(at("2026-11-17 12:30"), held={A: True, B: False})
    assert lit(merged) == {}
    assert merged.opens == ()  # B's open statement only darkens: B is not held
    assert merged.withheld["retracted"] == 1


def test_the_merged_rows_encode_into_the_published_file() -> None:
    world = _two()
    world.read(
        at("2026-11-17 11:05"),
        [row(ALPHA_DISTRICT, "2 hour delay due to snow"), row("SYNTHETIC Pacific School")],
        source=A,
    )
    merged = world.publish(at("2026-11-17 11:06"))
    stamp = DirectoryStamp(generated_on=date(2026, 11, 1), schools=11, districts=8)
    encoded = ClosingsFile.encode(
        merged.closings, generated_at=at("2026-11-17 11:06"), directory=stamp
    )
    assert sorted((c.school, c.status.name) for c in encoded.closings()) == [
        (0, "DELAYED"),
        (1, "DELAYED"),
        (7, "CLOSED"),
    ]


C = "scripps-synthetic"


def _ice_reader(text: str, *, posted_at: datetime, tz: str) -> Any:
    """The stub reader, which also reads "ice" as the reason Ice (SYNTHETIC)."""
    parsed = stub_reader(text, posted_at=posted_at, tz=tz)
    if parsed.schedule and "ice" in text.casefold().split():
        return dataclasses.replace(parsed, names_weather=True, reason="Ice")
    return parsed


def _three() -> World:
    world = World(reader=_ice_reader, stations={s: station(s) for s in (A, B, C)})
    for source in (A, B, C):
        world.read(at("2026-11-17 02:00"), [], source=source)
        world.read(at("2026-11-17 11:00"), [], source=source)
    return world


def _reason(world: World) -> Reason | None:
    merged = world.publish(at("2026-11-17 11:59"))
    (closing,) = [c for c in merged.closings if c.school == 0]
    return closing.reason


def test_a_reason_one_list_names_is_shown_when_another_names_none() -> None:
    world = _three()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed")], source=A)
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed due to ice")], source=B)
    assert _reason(world) is Reason.ICE
    two = _three()
    two.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed due to ice")], source=A)
    two.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed due to snow")], source=B)
    assert _reason(two) is None  # two reasons: none is shown


def test_an_earlier_row_of_the_same_status_since_the_change_gives_the_reason() -> None:
    world = _three()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed due to ice")], source=A)
    world.read(at("2026-11-17 11:10"), [], source=B)
    world.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL, "Closed")], source=B)
    assert _reason(world) is Reason.ICE
    changed = _three()
    changed.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed due to ice")], source=A)
    changed.read(at("2026-11-17 11:10"), [], source=B)
    changed.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL, "2 hour delay")], source=B)
    changed.read(at("2026-11-17 11:30"), [], source=C)
    changed.read(at("2026-11-17 11:40"), [row(ALPHA_SCHOOL, "Closed")], source=C)
    assert _reason(changed) is None  # the row naming ice came before the delay


def test_a_district_row_gives_no_reason_when_a_real_tie_chose_the_school_row() -> None:
    world = _three()
    world.read(
        at("2026-11-17 11:05"),
        [row(ALPHA_DISTRICT, "2 hour delay due to ice"), row(ALPHA_SCHOOL, "Closed")],
        source=A,
    )
    world.read(at("2026-11-17 11:05"), [row(ALPHA_DISTRICT, "Closed due to ice")], source=B)
    merged = world.publish(at("2026-11-17 11:59"))
    closing = {c.school: c for c in merged.closings}[0]
    assert closing.status.name == "CLOSED"
    assert closing.reason is None


_TEXTS = (
    None,
    "Closed",
    "Closed due to ice",
    "Closed due to snow",
    "2 hour delay",
    "2 hour delay due to ice",
)
_GRID = list(itertools.product(_TEXTS, _TEXTS, _TEXTS, (True, False)))


def _no_reason_reader(text: str, *, posted_at: datetime, tz: str) -> Any:
    """:func:`_ice_reader` with every reason left out (SYNTHETIC)."""
    return dataclasses.replace(_ice_reader(text, posted_at=posted_at, tz=tz), reason=None)


def _grid_world(texts: tuple[str | None, ...], district: bool, reader: Any) -> World:
    world = _three()
    world.reader = reader
    for source, text, minute in zip((A, B, C), texts, (5, 20, 5), strict=True):
        if minute == 20:
            world.read(at("2026-11-17 11:10"), [], source=source)
        name = ALPHA_DISTRICT if district and source == C else ALPHA_SCHOOL
        world.read(
            at(f"2026-11-17 11:{minute:02d}"),
            [] if text is None else [row(name, text)],
            source=source,
        )
    return world


@pytest.mark.parametrize(("first", "second", "third", "district"), _GRID)
def test_the_new_reason_rule_keeps_every_reason_the_old_one_showed(
    monkeypatch: pytest.MonkeyPatch,
    first: str | None,
    second: str | None,
    third: str | None,
    district: bool,
) -> None:
    """Over a grid of groups (B's row posted after A's and C's; C a district row or not):
    wherever the old rule (one reason over the winning rows, a row naming none counting as
    one) showed a reason, the new rule shows the same; and the reasons rows name change
    nothing published but the reason (status, times, shift, clock, what is withheld)."""
    real = merge_module._closing
    seen: list[tuple[Reason | None, Reason | None]] = []

    def checked(  # noqa: PLR0913 - the arguments of _closing
        school: int,
        day: date,
        *,
        winner: Item,
        top: Sequence[Item],
        group: Sequence[Item],
        narrowed: bool,
        generated_at: datetime,
    ) -> tuple[Closing, Item | None]:
        found = real(
            school,
            day,
            winner=winner,
            top=top,
            group=group,
            narrowed=narrowed,
            generated_at=generated_at,
        )
        reasons = {item.claim.reason for item in top if item.claim is not None}
        old = reasons.pop() if len(reasons) == 1 else None
        seen.append((found[0].reason, None if old is None else REASON_BY_LABEL[old]))
        return found

    monkeypatch.setattr(merge_module, "_closing", checked)
    texts = (first, second, third)
    named = _grid_world(texts, district, _ice_reader).publish(at("2026-11-17 11:59"))
    for new, old in seen:
        if old is not None:
            assert new is old
    plain = _grid_world(texts, district, _no_reason_reader).publish(at("2026-11-17 11:59"))

    def fields(closing: Closing) -> tuple[object, ...]:
        return (
            closing.school,
            closing.day,
            closing.status,
            closing.announced_at,
            closing.shift_minutes,
            closing.clock_minute,
        )

    assert [fields(c) for c in named.closings] == [fields(c) for c in plain.closings]
    assert named.withheld == plain.withheld

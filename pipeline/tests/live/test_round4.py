"""False states the third review found (round 4), each fixed as a class and failing dark:
a re-worded successor read at its predecessor's posting time, an undatable open statement,
a source whose terms or status stop it being read, a registry correction, and a stored
derivation that no longer reads. Every name and status is SYNTHETIC."""

import logging
from collections.abc import Sequence
from datetime import timedelta

import numpy as np
import pytest

from live.world import (
    ALPHA,
    ALPHA_DISTRICT,
    ALPHA_SCHOOL,
    World,
    at,
    lit,
    reasons,
    row,
    station,
    stub_reader,
)
from snowlight.listed.located import Gazetteer
from snowlight.live import resolve as resolve_module
from snowlight.live.guards import Withheld, open_wording_reason
from snowlight.live.ledger import Darkens, Ledger, SeenRow, Start
from snowlight.live.resolve import (
    MATCH_REASONS,
    Derived,
    Resolver,
    StatusReader,
    Target,
    darkens_of,
    f5_reader,
    gazetteer_digest,
    matcher_fn,
    station_version,
)
from snowlight.live.versions import PACKAGE, live_files

A = "gray-synthetic"
B = "flashalert-synthetic"
F5 = f5_reader()
READERS: tuple[tuple[str, StatusReader], ...] = (("stub", stub_reader), ("f5", F5))


def _two(reader: StatusReader = stub_reader) -> World:
    world = World(reader=reader)
    world.stations[B] = station(B)
    return world


# --- R3-B1: a re-worded successor is never read at its predecessor's posting time -------------


def _monday_closed_until(world: World, until: str) -> None:
    """A row "Closed" first seen Monday 05:00 CT, read every 30 minutes until ``until``."""
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 10:55"), [])
    world.read(at("2026-11-16 11:00"), [row(ALPHA_SCHOOL, "Closed")])
    assert lit(world.publish(at("2026-11-16 11:05"))) == {(0, "2026-11-16"): "CLOSED"}
    moment = at("2026-11-16 11:30")
    while moment < at(until):
        world.read(moment, [row(ALPHA_SCHOOL, "Closed")])
        moment += timedelta(minutes=30)


@pytest.mark.parametrize(
    ("text", "when"),
    [
        ("Closed tomorrow", "2026-11-18 00:00"),  # Tuesday 18:00 CT: for Wednesday
        ("Closed tomorrow", "2026-11-17 11:00"),  # Tuesday 05:00 CT: for Wednesday
        ("Closed tomorrow due to snow", "2026-11-18 00:00"),
    ],
)
def test_r3_b1_closed_re_worded_to_tomorrow_on_a_later_day_lights_neither_day(
    text: str, when: str
) -> None:
    for label, reader in READERS:
        world = World(reader=reader)
        _monday_closed_until(world, when)
        world.read(at(when), [row(ALPHA_SCHOOL, text)])
        end = at(when) + timedelta(minutes=5)
        assert lit(world.publish(end)) == {}, (label, text, when)  # never Tuesday
        (source,) = world.resolve()
        (present,) = [result for result in source.rows if result.present]
        assert present.derived.withheld is Withheld.REWORDED, label
        assert (present.row.lo, present.row.start) == (None, Start.REWORDED)
        # and it stays dark on later passes and under a later version
        world.read(end, [row(ALPHA_SCHOOL, text)])
        assert lit(world.publish(end + timedelta(minutes=5))) == {}, label
        world.version += "|bumped"
        assert lit(world.publish(end + timedelta(minutes=10))) == {}, label
        assert lit(world.publish(at("2026-11-18 13:00"))) == {}, label  # Wednesday 07:00 CT


def test_r3_b1_a_successor_whose_reading_does_not_depend_on_its_dating_still_lights() -> None:
    cases = [
        # Tuesday 16:00 CT, dated from Monday's posting (R4C-B1): 35 hours, still read
        ("Closed Wednesday", "2026-11-17 22:00", {(0, "2026-11-18"): "CLOSED"}),
        ("2 hour delay tomorrow", "2026-11-18 00:00", {(0, "2026-11-18"): "DELAYED"}),  # a new kind
        ("Closed tomorrow", "2026-11-17 02:00", {(0, "2026-11-17"): "CLOSED"}),  # Monday 20:00
    ]
    for label, reader in READERS:
        for text, when, shown in cases:
            world = World(reader=reader)
            _monday_closed_until(world, when)
            world.read(at(when), [row(ALPHA_SCHOOL, text)])
            assert lit(world.publish(at(when) + timedelta(minutes=5))) == shown, (label, text)


def test_r3_b1_a_successor_with_no_readable_predecessor_derivation_is_left_undated() -> None:
    world = World()
    _monday_closed_until(world, "2026-11-17 10:55")
    (pred,) = world.ledger.rows(A)
    world.ledger._db.execute("UPDATE derived SET payload = '{not json' WHERE key = ?", (pred.key,))
    world.ledger._db.commit()
    world.read(at("2026-11-17 11:00"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 11:05"))) == {}
    assert sorted(map(str, reasons(world.resolve()))) == ["not_derived", "reworded"]


# --- R3-B2: an undatable open statement dissents and is never an open signal ------------------

STUB_OPEN = ("Open", "School is open", "Schools will be open", "Normal schedule")
F5_OPEN = (
    "Open",
    "Open - normal schedule",
    "School is open",
    "Schools will be open",
    "Will be open as normal",
    "Open on time",
    "Normal schedule",
)


def _closed_then_open(  # noqa: PLR0913 - the two rows and their times
    reader: StatusReader,
    close_at: str,
    open_text: str,
    open_at: str,
    *,
    name: str = ALPHA_SCHOOL,
    open_name: str | None = None,
) -> World:
    """A "Closed" from source A, then an open statement from source B."""
    world = _two(reader)
    for source in (A, B):
        world.read(at("2026-11-13 15:00"), [], source=source)
        world.read(at("2026-11-16 15:00"), [], source=source)
        world.read(at(close_at) - timedelta(minutes=5), [], source=source)
    world.read(at(close_at), [row(name, "Closed")])
    world.read(at(open_at) - timedelta(minutes=5), [], source=B)
    world.read(at(open_at), [row(name, "Closed")])
    world.read(at(open_at), [row(open_name or name, open_text)], source=B)
    return world


@pytest.mark.parametrize(
    ("close_at", "open_at", "publish"),
    [
        ("2026-11-17 01:00", "2026-11-17 03:00", "2026-11-17 11:00"),  # Mon 19:00, 21:00 CT
        ("2026-11-17 11:00", "2026-11-17 19:00", "2026-11-17 19:05"),  # Tue 05:00, 13:00 CT
    ],
)
def test_r3_b2_an_evening_or_midday_open_statement_from_another_source_darkens(
    close_at: str, open_at: str, publish: str
) -> None:
    for label, reader, texts in (("stub", stub_reader, STUB_OPEN), ("f5", F5, F5_OPEN)):
        for text in texts:
            for name in (ALPHA_SCHOOL, ALPHA_DISTRICT):
                world = _closed_then_open(reader, close_at, text, open_at, name=name)
                merged = world.publish(at(publish))
                assert lit(merged) == {}, (label, text, name, open_at)
                assert merged.opens == (), (label, text)  # never an open signal
                withheld = {r.derived.withheld for s in world.resolve() for r in s.rows}
                assert Withheld.OPEN_UNDATED in withheld, (label, text)


def test_r3_b2_a_morning_open_statement_is_an_open_signal_for_its_day() -> None:
    for label, reader, texts in (("stub", stub_reader, STUB_OPEN), ("f5", F5, F5_OPEN)):
        for text in texts:
            world = _closed_then_open(reader, "2026-11-17 11:00", text, "2026-11-17 12:30")
            merged = world.publish(at("2026-11-17 12:35"))
            assert lit(merged) == {}, (label, text)
            assert [(o.school, o.day.isoformat()) for o in merged.opens] == [(0, "2026-11-17")], (
                label,
                text,
            )


def test_r3_b2_an_evening_open_statement_darkens_only_the_day_a_bare_status_names() -> None:
    """A district closed Wednesday (posted Tuesday 19:00 CT) and "Schools will be open" at
    21:00 CT from another list: Wednesday is dark; Tuesday's own status is not touched."""
    for label, reader in READERS:
        world = _two(reader)
        for source in (A, B):
            world.read(at("2026-11-16 15:00"), [], source=source)
            world.read(at("2026-11-17 10:55"), [], source=source)
        world.read(at("2026-11-17 11:00"), [row(ALPHA_DISTRICT, "2 hour delay")])  # Tue 05:00
        world.read(at("2026-11-18 01:00"), [row(ALPHA_DISTRICT, "2 hour delay")])
        world.read(at("2026-11-18 02:55"), [], source=B)
        world.read(at("2026-11-18 03:00"), [row(ALPHA_DISTRICT, "Schools will be open")], source=B)
        merged = world.publish(at("2026-11-18 03:05"))  # Tuesday 21:05 CT
        assert set(lit(merged)) == {(0, "2026-11-17"), (1, "2026-11-17")}, label
        assert merged.opens == (), label
        found = [r.derived for s in world.resolve() for r in s.rows if s.source_id == B]
        assert [d.dissent for d in found] == [(at("2026-11-18").date(),)], label


def test_r3_b2_an_open_statement_naming_a_day_out_of_reach_dissents_every_day() -> None:
    for label, reader in READERS:
        world = _closed_then_open(reader, "2026-11-17 11:00", "Open Dec 25", "2026-11-17 12:30")
        merged = world.publish(at("2026-11-17 12:35"))
        assert lit(merged) == {}, label
        assert merged.opens == (), label
        found = [r.derived for s in world.resolve() for r in s.rows if s.source_id == B]
        assert [(d.withheld, d.dissent) for d in found] == [(Withheld.OPEN_UNDATED, ())], label


# --- R3-S3: "Normal schedule" is an open statement (owner Q8) ---------------------------------


@pytest.mark.parametrize(
    "text", ["Normal schedule", "Open - normal schedule", "On a regular schedule"]
)
def test_r3_s3_normal_schedule_words_are_kept_as_open_signals(text: str) -> None:
    world = World(reader=F5)
    world.read(at("2026-11-16 15:00"), [])
    world.read(at("2026-11-17 12:25"), [])
    world.read(at("2026-11-17 12:30"), [row(ALPHA_SCHOOL, text)])  # Tuesday 06:30 CT
    merged = world.publish(at("2026-11-17 12:35"))
    assert [(o.school, o.day.isoformat(), o.confidence) for o in merged.opens] == [
        (0, "2026-11-17", 0.9)
    ]
    assert open_wording_reason(text, ALPHA_SCHOOL) is None


def test_r3_s3_planned_days_beside_open_words_still_dissent() -> None:
    assert open_wording_reason("Open - teacher workday", ALPHA_SCHOOL) == "planned"
    assert (
        open_wording_reason("Open - regularly scheduled early release", ALPHA_SCHOOL) == "planned"
    )
    assert open_wording_reason("Open on a normal schedule", ALPHA_SCHOOL) is None


# --- R3P-B1: a source no longer read keeps what darkens of what it last said -----------------


def _retracted(world: World) -> None:
    for source in (A, B):
        world.read(at("2026-11-16 08:00"), [], source=source)
        world.read(at("2026-11-17 09:00"), [], source=source)
        world.read(at("2026-11-17 10:00"), [], source=source)
    world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 10:12"))) == {(0, "2026-11-17"): "CLOSED"}
    world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 10:20"), [row(ALPHA_SCHOOL, "Closing rescinded")], source=B)
    assert lit(world.publish(at("2026-11-17 10:22"))) == {}


@pytest.mark.parametrize("change", ["terms", "status", "terms_unreadable"])
def test_r3p_b1_a_retraction_from_a_source_no_longer_read_still_darkens(change: str) -> None:
    world = _two()
    _retracted(world)
    if change == "status":
        world.stations[B] = world.stations[B].model_copy(update={"status": "no_endpoint"})
    else:
        world.pollable = {**world.pollable, "flashalert": False}
    if change == "terms_unreadable":
        world.ledger._db.execute("UPDATE derived SET payload = '{not json'")
        world.ledger._db.commit()
    world.read(at("2026-11-17 10:30"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    merged = world.publish(at("2026-11-17 10:32"))
    assert lit(merged) == {}, change
    refused = [r.derived for s in world.resolve() if s.source_id == B for r in s.rows]
    assert [(d.withheld, d.dissent, d.claims) for d in refused] == [(Withheld.TERMS, (), ())]


def test_r3p_b1_a_source_no_longer_read_lights_none_of_its_own_statuses() -> None:
    world = _two()
    for source in (A, B):
        world.read(at("2026-11-16 08:00"), [], source=source)
        world.read(at("2026-11-17 10:00"), [], source=source)
    world.read(at("2026-11-17 10:10"), [row(ALPHA_SCHOOL, "Closed due to snow")], source=B)
    assert lit(world.publish(at("2026-11-17 10:12"))) == {(0, "2026-11-17"): "CLOSED"}
    world.pollable = {**world.pollable, "flashalert": False}
    assert lit(world.publish(at("2026-11-17 10:14"))) == {}


# --- R3P-B2: a registry correction, the gazetteer and the vocabularies re-derive -----------


@pytest.mark.parametrize("fix", ["states", "leaids"])
def test_r3p_b2_a_registry_correction_reaches_rows_already_derived(fix: str) -> None:
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
    expected = Withheld.OUT_OF_STATE if fix == "states" else Withheld.EXCLUDED_PLATFORM
    assert reasons(world.resolve()) == [expected.value]


def test_r3p_b2_the_station_part_digests_what_a_derivation_reads() -> None:
    base = station(A)
    assert station_version(base) == station_version(station(A))
    for changed in (
        station(A, states=("KS",)),
        station(A, leaids=("2000001",)),
        base.model_copy(update={"status": "no_endpoint"}),
        base.model_copy(update={"market": "SYNTHETIC other market"}),
    ):
        assert station_version(changed) != station_version(base)
    assert station_version(base.model_copy(update={"evidence": "SYNTHETIC note"})) == (
        station_version(base)
    )


def _gazetteer(lat: float) -> Gazetteer:
    return Gazetteer({("KS", "synthetic town"): np.array([[lat, -97.0]])}, {}, {})


def test_r3p_b2_the_gazetteer_and_its_data_are_in_the_version() -> None:
    assert gazetteer_digest(_gazetteer(38.0)) == gazetteer_digest(_gazetteer(38.0))
    assert gazetteer_digest(_gazetteer(38.0)) != gazetteer_digest(_gazetteer(39.0))
    bare = matcher_fn(object())  # type: ignore[arg-type]
    placed = matcher_fn(object(), _gazetteer(38.0))  # type: ignore[arg-type]
    assert bare.version == "gaz-none"
    assert placed.version == f"gaz-{gazetteer_digest(_gazetteer(38.0))}"
    other = matcher_fn(object(), _gazetteer(39.0))  # type: ignore[arg-type]
    world = World()
    versions = {
        Resolver(
            reader=world.reader,
            match=match,
            directory=world.dir,
            ledger=world.ledger,
            pollable=world.pollable,
            version=world.version,
        ).version
        for match in (bare, placed, other)
    }
    assert len(versions) == 3


def test_r3p_b2_the_vocabularies_are_in_the_live_version() -> None:
    assert PACKAGE / "schemas" / "vocab.py" in live_files()


# --- R3P-B3: a stored derivation that no longer reads keeps darkening -------------------------


def _vanished_retraction(world: World) -> None:
    _retracted(world)
    world.read(at("2026-11-17 10:30"), [row("SYNTHETIC Pacific School", "Closed")], source=B)
    world.read(at("2026-11-17 10:30"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    assert lit(world.publish(at("2026-11-17 10:32"))) == {(7, "2026-11-17"): "CLOSED"}


@pytest.mark.parametrize("damage", ["drift", "corrupt", "wrong_shape"])
def test_r3p_b3_an_unreadable_stored_retraction_still_darkens(
    damage: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    world = _two()
    _vanished_retraction(world)
    if damage == "drift":
        # a later matcher drops a reason code and the version moves
        monkeypatch.setattr(resolve_module, "MATCH_REASONS", MATCH_REASONS - {"alias"})
        world.version += "|f6-v2"
    else:
        payload = "{not json" if damage == "corrupt" else '{"withheld": null}'
        world.ledger._db.execute("UPDATE derived SET payload = ?", (payload,))
        world.ledger._db.commit()
    world.read(at("2026-11-17 10:40"), [row(ALPHA_SCHOOL, "Closed due to snow")])
    world.read(at("2026-11-17 10:40"), [row("SYNTHETIC Pacific School", "Closed")], source=B)
    with caplog.at_level(logging.WARNING, logger="snowlight.live.resolve"):
        merged = world.publish(at("2026-11-17 10:42"))
    assert lit(merged) == {(7, "2026-11-17"): "CLOSED"}, damage  # Alpha stays dark
    assert caplog.records, damage
    keys = [entry.key.hex() for source in (A, B) for entry in world.ledger.rows(source)]
    for record in caplog.records:
        message = record.getMessage()
        assert B in message or A in message
        assert "SYNTHETIC" not in message
        assert "rescinded" not in message.casefold()
        assert not any(key[:12] in message for key in keys)


def test_r3p_b3_the_plain_darkening_part_always_reads_and_only_darkens_more() -> None:
    ledger = Ledger(":memory:")
    key = b"k" * 32
    day = at("2026-11-17 12:00").date()
    ledger.store_derived(key, "v", {}, Darkens(schools=("2", "1"), days=(day,)))
    assert ledger.darkens(key) == Darkens(schools=("1", "2"), days=(day,))
    ledger.store_derived(key, "v", {}, None)
    assert ledger.darkens(key) is None
    for part, value in (("day", "not a date"), ("other", "x"), ("every", "")):
        ledger.store_derived(key, "v", {}, Darkens(schools=("1",), days=(day,)))
        ledger._db.execute("INSERT INTO darkens VALUES (?, ?, ?)", (key, part, value))
        assert ledger.darkens(key) == Darkens(schools=("1",), days=None), part
    ledger.store_derived(key, "v", {}, Darkens(schools=("1",), days=(day,)))
    ledger._db.execute("DELETE FROM darkens WHERE part = 'day'")
    assert ledger.darkens(key) == Darkens(schools=("1",), days=None)  # no day kept: every day


def test_r3p_b3_the_darkening_part_holds_dissents_and_open_statements() -> None:
    school = Target(0, ALPHA[0], "school")
    day = at("2026-11-17 12:00").date()
    assert darkens_of(Derived(withheld=None, claims=(), targets=(school,))) is None
    assert darkens_of(Derived(withheld=None, opens=(day,), targets=(school,))) == Darkens(
        (ALPHA[0],), (day,)
    )
    assert darkens_of(Derived(withheld=Withheld.NOTE, dissent=(), voters=(school,))) == Darkens(
        (ALPHA[0],), None
    )


# --- R3P-S5: a row's repr holds no raw text ---------------------------------------------------


def test_r3p_s5_a_seen_rows_repr_holds_no_raw_name_text_or_date() -> None:
    seen: Sequence[SeenRow] = [
        row(ALPHA_SCHOOL, "Closed due to snow", section="SYNTHETIC Section", row_date="Nov 17")
    ]
    shown = repr(seen)
    for raw in (ALPHA_SCHOOL, "snow", "SYNTHETIC Section", "Nov 17"):
        assert raw not in shown

"""The row ledger: keys, first sightings, cold starts, churn, flaps and partial reads (T1)."""

from live.world import ALPHA_DISTRICT, ALPHA_SCHOOL, World, at, lit, reasons, row
from snowlight.live.ledger import Ledger, Outcome, SeenRow, Start, norm, row_key, seen_row
from snowlight.sources.stations.model import RawRow

SECRET = b"synthetic-secret"


def _rows(count: int, text: str = "Closed") -> list[SeenRow]:
    return [row(f"SYNTHETIC Listing {number}", text) for number in range(count)]


def test_t1a_a_row_between_two_reads_is_dated_and_published() -> None:
    world = World()
    world.read(at("2026-11-16 20:00"), [])
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)])
    (entry,) = world.ledger.rows("gray-synthetic")
    assert entry.lo == at("2026-11-17 11:00")
    assert entry.hi == at("2026-11-17 11:05")
    assert entry.start is Start.WARM
    merged = world.publish(at("2026-11-17 11:06"))
    assert lit(merged) == {(0, "2026-11-17"): "CLOSED"}
    (closing,) = merged.closings
    assert closing.announced_at == at("2026-11-17 11:05")  # watched within 15 min (owner Q6)


def test_t1b_a_re_read_never_moves_the_first_sighting() -> None:
    world = World()
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)])
    for later in ("2026-11-17 17:00", "2026-11-18 11:00", "2026-11-20 11:00"):
        world.read(at(later), [row(ALPHA_SCHOOL)])
        (entry,) = world.ledger.rows("gray-synthetic")
        assert entry.hi == at("2026-11-17 11:05")
        assert entry.lo == at("2026-11-17 11:00")
        assert entry.last_seen == at(later)


def test_t1c_cold_start_withholds_undated_rows_and_page_stamps() -> None:
    world = World()
    page = RawRow(
        source_id="gray-synthetic",
        fetched_at=at("2026-11-17 11:05"),
        raw_name="SYNTHETIC Listing page",
        raw_status="Closed",
        raw_updated_text="Updated 11/17/2026 5:00 AM",
        raw_extra={"updated_scope": "page"},
    )
    stamped = RawRow(
        source_id="gray-synthetic",
        fetched_at=at("2026-11-17 11:05"),
        raw_name=ALPHA_DISTRICT,
        raw_status="Closed",
        raw_updated_text="11/17/2026 5:01 AM",
        raw_extra={"updated_scope": "row"},
    )
    stamped_row = seen_row(stamped, variant="synthetic", platform="gray", zone="America/Chicago")
    page_row = seen_row(page, variant="synthetic", platform="gray", zone="America/Chicago")
    assert page_row.row_stamp is None
    assert page_row.row_date == ""
    assert stamped_row.row_stamp == at("2026-11-17 11:01")
    world = World()
    world.matcher.table["SYNTHETIC Listing page"] = world.matcher.table[ALPHA_SCHOOL]
    world.read(
        at("2026-11-17 11:05"),
        [row(ALPHA_SCHOOL), row(ALPHA_SCHOOL, "Closed Monday"), page_row, stamped_row],
    )
    found = sorted(r for r in reasons(world.resolve()) if r is not None)
    assert found == ["unknown_start", "unknown_start", "unknown_start"]
    merged = world.publish(at("2026-11-17 11:06"))
    # The stamped district row lights its schools, except school 0: its own "Closed Monday"
    # (posted Tuesday) names a day the reader cannot place, so it stands against the
    # district's status.
    assert lit(merged) == {(1, "2026-11-17"): "CLOSED"}
    assert merged.counts["school_row_stands"] == 1
    assert {c.announced_at for c in merged.closings} == {at("2026-11-17 11:01")}


def test_t1d_case_and_spacing_changes_keep_keys() -> None:
    rows = _rows(50)
    changed = [
        row(f"  synthetic   LISTING {number} ", " closed. ") if number < 40 else rows[number]
        for number in range(50)
    ]
    ledger = Ledger(":memory:")
    assert [ledger.key("s", r) for r in rows] == [ledger.key("s", r) for r in changed]
    assert norm("  ¡Hello,   World! ") == "hello, world"


def test_t1e_churn_unknown_start_but_growth_is_warm() -> None:
    churn = Ledger(":memory:")
    churn.observe("s", Outcome.OK, at("2026-11-17 11:00"), _rows(10))
    renamed = [row(f"SYNTHETIC Other {number}") for number in range(10)]
    churn.observe("s", Outcome.OK, at("2026-11-17 11:05"), renamed)
    fresh = [r for r in churn.rows("s") if r.hi == at("2026-11-17 11:05")]
    assert len(fresh) == 10
    assert all(r.lo is None and r.start is Start.CHURN for r in fresh)
    growth = Ledger(":memory:")
    growth.observe("s", Outcome.OK, at("2026-11-17 11:00"), _rows(5))
    observed = growth.observe("s", Outcome.OK, at("2026-11-17 11:05"), _rows(300))
    assert not observed.churn
    new = [r for r in growth.rows("s") if r.hi == at("2026-11-17 11:05")]
    assert len(new) == 295
    assert all(r.lo == at("2026-11-17 11:00") for r in new)


def test_t1e_growth_publishes() -> None:
    world = World()
    world.read(at("2026-11-16 20:00"), [])
    world.read(at("2026-11-17 11:00"), _rows(5))
    world.read(at("2026-11-17 11:05"), [*_rows(5), row(ALPHA_SCHOOL)])
    assert lit(world.publish(at("2026-11-17 11:06"))) == {(0, "2026-11-17"): "CLOSED"}


def test_t1f_a_short_flap_keeps_the_first_sighting_a_long_one_does_not() -> None:
    ledger = Ledger(":memory:")
    ledger.observe("s", Outcome.OK, at("2026-11-17 10:00"), [])
    ledger.observe("s", Outcome.OK, at("2026-11-17 10:05"), _rows(1))
    ledger.observe("s", Outcome.OK, at("2026-11-17 10:10"), [])
    ledger.observe("s", Outcome.OK, at("2026-11-17 12:00"), [])
    ledger.observe("s", Outcome.OK, at("2026-11-17 12:30"), _rows(1))
    (entry,) = ledger.rows("s")
    assert entry.hi == at("2026-11-17 10:05")
    assert entry.absent_since is None
    other = row("SYNTHETIC Other listing")
    ledger.observe("s", Outcome.OK, at("2026-11-17 12:35"), [other])  # live: something new
    ledger.observe("s", Outcome.OK, at("2026-11-17 15:40"), [other])
    assert [r.gone for r in ledger.rows("s")] == [True, False]
    ledger.observe("s", Outcome.OK, at("2026-11-17 15:45"), [*_rows(1), other])
    entry = ledger.rows("s")[-1]
    assert entry.hi == at("2026-11-17 15:45")
    assert entry.lo == at("2026-11-17 15:40")
    assert not entry.gone


def test_t1f_a_partial_read_deletes_nothing_until_it_repeats() -> None:
    ledger = Ledger(":memory:")
    ledger.observe("s", Outcome.OK, at("2026-11-17 10:00"), _rows(10))
    observed = ledger.observe("s", Outcome.OK, at("2026-11-17 10:05"), _rows(4))
    assert observed.outcome is Outcome.PARTIAL
    assert all(r.absent_since is None for r in ledger.rows("s"))
    state = ledger.source("s")
    assert state is not None
    assert state.last_good_at == at("2026-11-17 10:00")
    assert state.last_outcome is Outcome.PARTIAL
    again = ledger.observe("s", Outcome.OK, at("2026-11-17 10:10"), _rows(4))
    assert again.outcome is Outcome.OK
    assert len([r for r in ledger.rows("s") if r.absent_since is not None]) == 6


LEDGER = Ledger(":memory:")


def test_t1g_a_page_stamp_that_changes_every_read_keeps_keys() -> None:
    keys = set()
    for minute in range(0, 30, 5):
        raw = RawRow(
            source_id="fox-owned-synthetic",
            fetched_at=at(f"2026-11-17 11:{minute:02d}"),
            raw_name=ALPHA_DISTRICT,
            raw_status="Closed",
            raw_updated_text=f"Updated 5:{minute:02d} AM",
            raw_extra={"updated_scope": "page"},
        )
        seen = seen_row(raw, variant="synthetic", platform="fox-owned", zone="America/Chicago")
        assert seen.row_stamp is None
        keys.add(LEDGER.key("fox-owned-synthetic", seen))
    assert len(keys) == 1


def test_bad_reads_change_no_sightings_and_late_reads_are_ignored() -> None:
    ledger = Ledger(":memory:")
    assert ledger.observe("s", Outcome.ERROR, at("2026-11-17 10:00")).outcome is Outcome.ERROR
    ledger.observe("s", Outcome.OK, at("2026-11-17 10:05"), _rows(2))
    assert ledger.observe("s", Outcome.BLOCKED, at("2026-11-17 10:10")).outcome is Outcome.BLOCKED
    late = ledger.observe("s", Outcome.OK, at("2026-11-17 10:00"), _rows(3))
    assert late.outcome is Outcome.LATE
    assert len(ledger.rows("s")) == 2
    state = ledger.source("s")
    assert state is not None
    assert state.last_good_at == at("2026-11-17 10:05")


def test_cold_after_a_long_gap_and_pruning() -> None:
    ledger = Ledger(":memory:")
    ledger.observe("s", Outcome.OK, at("2026-11-10 10:00"), _rows(1))
    ledger.observe("s", Outcome.OK, at("2026-11-12 10:00"), _rows(2))
    second = [r for r in ledger.rows("s") if r.hi == at("2026-11-12 10:00")]
    assert second[0].lo is None
    assert second[0].start is Start.COLD
    ledger.observe("s", Outcome.EMPTY, at("2026-11-27 10:00"), [])  # unconfirmed
    ledger.observe("s", Outcome.EMPTY, at("2026-11-27 10:05"), [])
    assert ledger.rows("s") == []
    assert ledger.good_reads("s") == [at("2026-11-27 10:05")]


def test_fetch_state_and_derived_store() -> None:
    ledger = Ledger(":memory:")
    ledger.set_fetch_state(
        "s", blocked_until=at("2026-11-18 10:00"), etag='"x"', next_due=at("2026-11-17 10:05")
    )
    state = ledger.source("s")
    assert state is not None
    assert state.blocked_until == at("2026-11-18 10:00")
    assert state.etag == '"x"'
    assert state.last_good_at is None
    ledger.observe("s", Outcome.OK, at("2026-11-17 10:00"), _rows(1))
    key = ledger.rows("s")[0].key
    ledger.store_derived(key, "v1", {"a": 1})
    assert ledger.derived(key, "v1") == {"a": 1}
    assert ledger.derived(key, "v2") is None
    assert ledger.row(key) is not None
    assert [s.source_id for s in ledger.sources()] == ["s"]
    ledger.close()


def test_the_key_names_source_name_section_words_and_row_date() -> None:
    base = row_key(SECRET, "s", "SYNTHETIC A", None, "Closed", row_date="")
    assert base == row_key(SECRET, "s", "synthetic a", "", "closed", row_date="")
    assert base != row_key(SECRET, "t", "SYNTHETIC A", None, "Closed", row_date="")
    assert base != row_key(SECRET, "s", "SYNTHETIC A", "Private", "Closed", row_date="")
    assert base != row_key(SECRET, "s", "SYNTHETIC A", None, "Closed Monday", row_date="")
    assert base != row_key(SECRET, "s", "SYNTHETIC A", None, "Closed", row_date="2026-11-17")
    assert base != row_key(b"another-secret", "s", "SYNTHETIC A", None, "Closed", row_date="")

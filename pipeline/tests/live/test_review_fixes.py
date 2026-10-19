"""Round 2's code-quality fixes: open-signal order, provenance, stored derivations read
defensively, terms re-checked in resolve, keyed hashes, reprs and the reader cache."""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from live.world import (
    ALPHA_SCHOOL,
    SynParsed,
    World,
    at,
    lit,
    row,
    station,
    stub_reader,
)
from snowlight.live.guards import Withheld
from snowlight.live.ledger import SCHEMA_VERSION, Ledger
from snowlight.live.merge import merge
from snowlight.live.resolve import CachedReader, pollable_platforms
from snowlight.sources.stations.registry import load_registry

A = "gray-synthetic"
B = "nexstar-synthetic"
SOURCES = Path(__file__).resolve().parents[2] / "config" / "sources"


def _two() -> World:
    world = World(stations={A: station(A), B: station(B)})
    for source in (A, B):
        world.read(at("2026-11-17 02:00"), [], source=source)
        world.read(at("2026-11-17 11:00"), [], source=source)
    return world


def _sure(text: str, *, posted_at: datetime, tz: str) -> SynParsed:
    """The stub reader, with ``[open=0.95]`` setting an open statement's confidence."""
    parsed = stub_reader(text, posted_at=posted_at, tz=tz)
    if "[open=0.95]" in text and parsed.says_open:
        return replace(parsed, confidence=0.95)
    return parsed


# --- S5: the open signal does not depend on input order ---------------------------------------


def test_s5_the_open_signal_takes_the_lowest_confidence_in_any_order() -> None:
    world = _two()
    world.reader = _sure
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=A)
    world.resolve()
    world.read(at("2026-11-17 11:06"), [], source=B)
    world.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL, "Open [open=0.95]")], source=A)
    world.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL, "Open")], source=B)
    resolved = world.resolve()
    found = set()
    for order in (resolved, resolved[::-1]):
        merged = merge(
            order, held={A: True, B: True}, directory=world.dir, generated_at=at("2026-11-17 11:21")
        )
        (signal,) = merged.opens
        found.add((signal.source_id, signal.confidence, json.dumps(signal.to_private_json())))
    assert len(found) == 1
    assert found.pop()[:2] == (A, 0.9)


# --- S6: provenance explains the status --------------------------------------------------------


def test_s6_provenance_names_the_version_every_contributing_row_and_the_posted_row() -> None:
    world = _two()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)], source=A)
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed.")], source=B)
    merged = world.publish(at("2026-11-17 11:06"))
    (line,) = merged.provenance
    assert line["derived_version"] == world.resolver().version_for(world.stations[A])
    keys = {source.source_id: source.rows[0].row.key.hex() for source in world.resolve()}
    assert line["contributing"] == [
        [A, "broadcaster_list", keys[A]],
        [B, "broadcaster_list", keys[B]],
    ]
    assert line["announced_by"] == keys[A]
    assert line["present"] is True
    assert line["sources"] == 2


# --- S8: a stored derivation of the wrong shape is never fatal ---------------------------------


def test_s8_a_malformed_stored_derivation_is_counted_and_never_raises() -> None:
    world = World()
    world.read(at("2026-11-17 02:00"), [])
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL), row("SYNTHETIC Other 1")])
    keys = [entry.key for entry in world.ledger.rows(A)]
    version = world.resolver().version
    for key in keys:
        world.ledger.store_derived(key, version, {"withheld": None, "claims": "not a list"})
    (source,) = world.resolve()
    assert source.counts["bad_derived"] == 2
    assert lit(world.publish(at("2026-11-17 11:06"))) == {(0, "2026-11-17"): "CLOSED"}  # re-derived
    for key in keys:
        world.ledger.store_derived(key, "older", {"claims": [["x"]]})
    world.read(at("2026-11-17 11:30"), [row("SYNTHETIC Other 1"), row("SYNTHETIC Other 2")])
    world.read(at("2026-11-17 11:35"), [row("SYNTHETIC Other 1"), row("SYNTHETIC Other 2")])
    (source,) = world.resolve()
    vanished = [r for r in source.rows if not r.present]
    assert [r.derived.withheld for r in vanished] == [Withheld.NOT_DERIVED]


# --- S9: resolve checks the terms again --------------------------------------------------------


def test_s9_a_station_not_active_or_not_pollable_lights_nothing() -> None:
    for change in ("status", "terms"):
        world = World()
        if change == "status":
            world.stations[A] = station(A).model_copy(update={"status": "no_endpoint"})
        else:
            world.pollable = {**world.pollable, "gray": False}
        world.read(at("2026-11-17 02:00"), [])
        world.read(at("2026-11-17 11:00"), [])
        world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)])
        (source,) = world.resolve()
        assert [r.derived.withheld for r in source.rows] == [Withheld.TERMS]
        assert lit(world.publish(at("2026-11-17 11:06"))) == {}
    verdicts = pollable_platforms(load_registry(SOURCES))
    assert verdicts
    assert all(isinstance(value, bool) for value in verdicts.values())


# --- S10: keys are keyed hashes under the ledger's own secret ----------------------------------


def test_s10_keys_hold_across_reopening_and_differ_between_ledgers(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite"
    first = Ledger(path)
    key = first.key(A, row(ALPHA_SCHOOL))
    first.close()
    again = Ledger(path)
    assert again.key(A, row(ALPHA_SCHOOL)) == key
    again.close()
    assert Ledger(":memory:").key(A, row(ALPHA_SCHOOL)) != key
    import sqlite3  # noqa: PLC0415 - only to age the file

    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
    with pytest.raises(ValueError, match="schema"):
        Ledger(path)


# --- S11: no raw text in a repr, and a bounded reader cache -----------------------------------


def test_s11_resolved_hides_its_queue_and_the_reader_cache_is_bounded() -> None:
    world = World()
    world.read(at("2026-11-17 02:00"), [])
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row("SYNTHETIC Unlisted Name")])
    (source,) = world.resolve()
    assert source.unmatched
    assert "Unlisted" not in repr(source)
    cache = CachedReader(stub_reader, limit=2)
    for text in ("Closed", "2 hour delay", "Closed", "Remote learning", "2 hour delay"):
        cache(text, posted_at=at("2026-11-17 11:00"), tz="America/Chicago")
    assert len(cache) == 2
    assert cache.calls == 4  # "Closed" was kept on its second read, "2 hour delay" was not
    assert "Closed" not in repr(cache)
    cache.clear()
    assert len(cache) == 0

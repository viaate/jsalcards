"""Properties of the live ingest over generated inputs: keys, samples, sightings, the stored
derivation and the merge's order independence."""

import random
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from live.world import (
    ALPHA_DISTRICT,
    ALPHA_SCHOOL,
    CHICAGO,
    DENVER,
    LOS_ANGELES,
    NEW_YORK,
    World,
    at,
    row,
    station,
)
from snowlight.live.guards import Withheld
from snowlight.live.ledger import FLAP, Ledger, Outcome, Start, norm, row_key
from snowlight.live.merge import merge
from snowlight.live.resolve import MATCH_LEVELS, MATCH_REASONS, DayClaim, Derived, Target, samples
from snowlight.schemas.vocab import REASON_BY_LABEL, STATUS_BY_KIND

ZONES = (CHICAGO, DENVER, LOS_ANGELES, NEW_YORK, "America/St_Johns", "Asia/Kathmandu")
START = at("2026-11-14 00:00")
SECRET = b"synthetic-secret"


# --- keys ------------------------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(st.text())
def test_norm_is_idempotent(text: str) -> None:
    once = norm(text)
    assert norm(once) == once


_WORDS = st.lists(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8), min_size=1, max_size=5
)


@settings(max_examples=200, deadline=None)
@given(_WORDS, _WORDS, st.lists(st.sampled_from([" ", "  ", "\t", " \n "]), min_size=1, max_size=5))
def test_row_key_ignores_case_and_spacing(
    name: list[str], text: list[str], gaps: list[str]
) -> None:
    def spaced(words: list[str]) -> str:
        return "".join(word + gaps[number % len(gaps)] for number, word in enumerate(words))

    plain = row_key(SECRET, "s", " ".join(name), None, " ".join(text), row_date="")
    loud = row_key(SECRET, "s", spaced(name).upper(), "", "  " + spaced(text).title(), row_date="")
    assert plain == loud


# --- samples ---------------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    st.integers(min_value=0, max_value=4 * 24 * 60),
    st.integers(min_value=0, max_value=36 * 60),
    st.lists(st.sampled_from(ZONES), min_size=1, max_size=3, unique=True),
)
def test_samples_are_sorted_bounded_and_hold_every_local_half_hour(
    start: int, length: int, zones: list[str]
) -> None:
    lo = START + timedelta(minutes=start)
    hi = lo + timedelta(minutes=length)
    found = samples(lo, hi, zones)
    assert found == sorted(set(found))
    assert found[0] == lo
    assert found[-1] == hi
    assert all(lo <= moment <= hi for moment in found)
    kept = set(found)
    for minute in range(1, length):
        moment = lo + timedelta(minutes=minute)
        for zone in zones:
            if moment.astimezone(ZoneInfo(zone)).minute in {0, 30}:
                assert moment in kept, (moment, zone)


# --- sightings ---------------------------------------------------------------------------------

_NAMES = [f"SYNTHETIC Listing {number}" for number in range(6)]
_LIST = st.lists(st.sampled_from(_NAMES), unique=True, max_size=6)
_READ: st.SearchStrategy[tuple[str, list[str]]] = st.one_of(
    st.just(("error", [])),  # a failed read
    st.tuples(st.just("ok"), _LIST),
    st.just(("empty", [])),
    # a 304 with the cached rows (without any, it is a confirming 304)
    st.tuples(st.just("not_modified"), _LIST.filter(bool)),
    st.just(("confirm", [])),  # a 304 without rows: it confirms the last good read
)
_OUTCOMES = {
    "error": Outcome.ERROR,
    "ok": Outcome.OK,
    "empty": Outcome.EMPTY,
    "not_modified": Outcome.NOT_MODIFIED,
    "confirm": Outcome.NOT_MODIFIED,
}


@settings(max_examples=200, deadline=None)
@given(st.lists(st.tuples(st.integers(min_value=5, max_value=240), _READ), min_size=1, max_size=25))
def test_sightings_never_move_and_a_partial_read_deletes_nothing(
    reads: list[tuple[int, tuple[str, list[str]]]],
) -> None:
    """A key's ``hi`` and ``lo`` move only when it comes back as a new appearance (T1f);
    a failed, partial or late read changes nothing; a confirming 304 changes no presence;
    a good read leaves exactly its own rows present. (Only the resolver changes a
    successor's dating, through :meth:`Ledger.reword`: see the next property.)"""
    ledger = Ledger(":memory:")
    moment = START
    good = False
    for gap, (kind, names) in reads:
        moment += timedelta(minutes=gap)
        before = {entry.key: entry for entry in ledger.rows("s")}
        if kind == "confirm" and not good:
            with pytest.raises(ValueError, match="earlier good read"):
                ledger.observe("s", Outcome.NOT_MODIFIED, moment)
            continue
        found = ledger.observe("s", _OUTCOMES[kind], moment, [row(name) for name in names])
        after = {entry.key: entry for entry in ledger.rows("s")}
        if found.outcome in {Outcome.PARTIAL, Outcome.ERROR, Outcome.LATE}:
            assert after == before
            continue
        good = True
        if kind == "confirm":
            assert {k: e.absent_since for k, e in after.items()} == {
                k: e.absent_since for k, e in before.items()
            }
            assert {k: (e.hi, e.lo, e.gone) for k, e in after.items() if not e.gone} == {
                k: (e.hi, e.lo, e.gone)
                for k, e in before.items()
                if k in after and not after[k].gone
            }
            continue
        for key, entry in after.items():
            old = before.get(key)
            if old is None or old.gone:
                continue
            if key in found.reappeared:
                absent = old.absent_since
                assert absent is not None
                assert moment - absent >= FLAP
                assert entry.hi == moment
            else:
                assert (entry.hi, entry.lo) == (old.hi, old.lo)
        present = {ledger.key("s", row(name)) for name in names}
        assert {key for key, entry in after.items() if entry.absent_since is None} == present


@settings(max_examples=100, deadline=None)
@given(
    st.integers(min_value=5, max_value=600),
    st.integers(min_value=5, max_value=600),
    st.sampled_from(["Closed due to snow", "2 hour delay", "Closing rescinded"]),
)
def test_reword_leaves_a_successor_undated(first: int, second: int, words: str) -> None:
    ledger = Ledger(":memory:")
    ledger.observe("s", Outcome.OK, START, [])
    ledger.observe("s", Outcome.OK, START + timedelta(minutes=first), [row("SYNTHETIC A")])
    later = START + timedelta(minutes=first + second)
    found = ledger.observe("s", Outcome.OK, later, [row("SYNTHETIC A", words)])
    (key,) = found.successors
    entry = ledger.row(key)
    assert entry is not None
    assert entry.pred is not None
    assert (entry.hi, entry.lo) == (later, START + timedelta(minutes=first))
    ledger.reword(key)
    moved = ledger.row(key)
    assert moved is not None
    assert (moved.hi, moved.lo, moved.start, moved.pred) == (later, None, Start.REWORDED, None)


# --- the stored derivation ----------------------------------------------------------------------

_DAYS = st.dates(min_value=date(2026, 11, 10), max_value=date(2026, 11, 30))
_TARGETS = st.lists(
    st.builds(
        Target,
        st.integers(min_value=0, max_value=10**6),
        st.from_regex(r"[0-9]{12}", fullmatch=True),
        st.sampled_from(["school", "district"]),
    ),
    max_size=3,
).map(tuple)
_CLAIMS = st.lists(
    st.builds(
        DayClaim,
        _DAYS,
        st.sampled_from(sorted(STATUS_BY_KIND)),
        st.one_of(st.none(), st.sampled_from(sorted(REASON_BY_LABEL))),
        st.one_of(st.none(), st.integers(min_value=0, max_value=600)),
        st.one_of(st.none(), st.integers(min_value=0, max_value=1439)),
        st.booleans(),
    ),
    max_size=3,
).map(tuple)
_DERIVED = st.builds(
    Derived,
    withheld=st.one_of(st.none(), st.sampled_from(list(Withheld))),
    claims=_CLAIMS,
    opens=st.lists(_DAYS, max_size=2).map(tuple),
    dissent=st.one_of(st.none(), st.lists(_DAYS, max_size=2).map(tuple)),
    targets=_TARGETS,
    voters=_TARGETS,
    announced_at=st.one_of(
        st.none(), st.datetimes(timezones=st.just(UTC), min_value=datetime(2026, 1, 1))
    ),
    confidence=st.one_of(st.none(), st.floats(min_value=0, max_value=1)),
    notes=st.lists(st.sampled_from(["undated", "unread_words", "revoked"]), max_size=2).map(tuple),
    match_reason=st.one_of(st.none(), st.sampled_from(sorted(MATCH_REASONS))),
    match_level=st.one_of(st.none(), st.sampled_from(sorted(MATCH_LEVELS))),
    match_confidence=st.one_of(st.none(), st.floats(min_value=0, max_value=1)),
    source_type=st.one_of(st.none(), st.sampled_from(["broadcaster_list", "state_board"])),
    target_drops=st.dictionaries(
        st.sampled_from(["not_in_directory", "section", "unanchored"]), st.integers(0, 50)
    ),
)


@settings(max_examples=300, deadline=None)
@given(_DERIVED)
def test_the_stored_derivation_round_trips(derived: Derived) -> None:
    assert Derived.from_json(derived.to_json()) == derived


# --- merge order ------------------------------------------------------------------------------

_SOURCES = ("gray-synthetic", "nexstar-synthetic", "tegna-synthetic")
_ROWS = [
    (ALPHA_SCHOOL, "Closed"),
    (ALPHA_SCHOOL, "2 hour delay"),
    (ALPHA_SCHOOL, "Open"),
    (ALPHA_SCHOOL, "Closing rescinded"),
    (ALPHA_DISTRICT, "Closed"),
    (ALPHA_DISTRICT, "2 hour delay due to snow"),
    ("SYNTHETIC Pacific School", "Closed"),
    ("SYNTHETIC Eastern School", "Open"),
]
_LIST = st.lists(st.sampled_from(range(len(_ROWS))), unique=True, max_size=4)


@settings(max_examples=100, deadline=None)
@given(
    st.lists(st.tuples(st.sampled_from(_SOURCES), st.integers(0, 30), _LIST), max_size=8),
    st.randoms(use_true_random=False),
)
def test_the_merge_does_not_depend_on_input_order(
    reads: list[tuple[str, int, list[int]]], shuffle: random.Random
) -> None:
    world = World(stations={source: station(source) for source in _SOURCES})
    for source in _SOURCES:
        world.read(at("2026-11-17 02:00"), [], source=source)
        world.read(at("2026-11-17 11:00"), [], source=source)
    moment = at("2026-11-17 11:00")
    for source, gap, picks in reads:
        moment += timedelta(minutes=gap)
        world.read(moment, [row(*_ROWS[pick]) for pick in picks], source=source)
        world.resolve()
    resolved = world.resolve()
    held = dict.fromkeys(_SOURCES, True)
    now = moment + timedelta(minutes=1)
    first = merge(resolved, held=held, directory=world.dir, generated_at=now)
    mixed = [
        replace(source, rows=tuple(shuffle.sample(source.rows, len(source.rows))))
        for source in resolved
    ]
    shuffle.shuffle(mixed)
    second = merge(mixed, held=held, directory=world.dir, generated_at=now)
    assert first == second

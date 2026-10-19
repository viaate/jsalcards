"""The false state the fourth review found (round 5): a re-worded successor that reads the
same at its own interval and at its predecessor's is dated, for merge, from the earliest
its predecessor can have been posted, so it never passes for words newer than a reversal
another source posted in between. Every name and status is SYNTHETIC."""

from datetime import datetime, timedelta

import pytest

from live.world import ALPHA_DISTRICT, ALPHA_SCHOOL, World, at, lit, row, station, stub_reader
from snowlight.live.ledger import LedgerRow, Start
from snowlight.live.resolve import StatusReader, f5_reader

A = "gray-synthetic"
B = "flashalert-synthetic"
F5 = f5_reader()
type Lit = dict[tuple[int, str], str]


def _reword_after_reversal(  # noqa: PLR0913 - one posting sequence
    reader: StatusReader,
    *,
    first: str,
    reworded: str,
    reversal: str,
    posted: str,
    reversed_at: str,
    reworded_at: str,
    name: str = ALPHA_SCHOOL,
) -> tuple[Lit, Lit, World]:
    """A posts ``first`` at ``posted``; B posts ``reversal`` at ``reversed_at``; A re-words
    its row to ``reworded`` at ``reworded_at``. Both are read every 30 minutes. Returns the
    map after the reversal and after the re-word."""
    world = World(reader=reader)
    world.stations[B] = station(B)
    for source in (A, B):
        world.read(at("2026-11-13 15:00"), [], source=source)
        world.read(at("2026-11-16 08:00"), [], source=source)
        world.read(at(posted) - timedelta(minutes=5), [], source=source)
    world.read(at(posted), [row(name, first)])
    moment = at(posted) + timedelta(minutes=30)
    while moment < at(reversed_at):
        world.read(moment, [row(name, first)])
        world.read(moment, [], source=B)
        moment += timedelta(minutes=30)
    world.read(at(reversed_at), [row(name, first)])
    world.read(at(reversed_at), [row(name, reversal)], source=B)
    after_reversal = lit(world.publish(at(reversed_at) + timedelta(minutes=5)))
    moment = at(reversed_at) + timedelta(minutes=30)
    while moment < at(reworded_at):
        world.read(moment, [row(name, first)])
        world.read(moment, [row(name, reversal)], source=B)
        moment += timedelta(minutes=30)
    world.read(at(reworded_at), [row(name, reworded)])
    world.read(at(reworded_at), [row(name, reversal)], source=B)
    after_reword = lit(world.publish(at(reworded_at) + timedelta(minutes=5)))
    return after_reversal, after_reword, world


# Monday 10:00 CT "Closed Wednesday"; Tuesday 10:00 CT B reverses it; Tuesday 12:00 CT A re-words.
NEXT_DAY = {"posted": "2026-11-16 16:00", "reversed_at": "2026-11-17 16:00",
            "reworded_at": "2026-11-17 18:00"}  # fmt: skip
# Tuesday 05:00 CT "Closed"; 06:30 CT B reverses it; 07:00 CT A re-words.
SAME_MORNING = {"posted": "2026-11-17 11:00", "reversed_at": "2026-11-17 12:30",
                "reworded_at": "2026-11-17 13:00"}  # fmt: skip

type Case = tuple[str, StatusReader, str, str, str, dict[str, str], str]
CASES: list[Case] = [
    ("f5", F5, "Closed Wednesday", "Closed Wednesday due to snow", "Open Wednesday", NEXT_DAY,
     ALPHA_SCHOOL),
    ("f5", F5, "Closed Wednesday", "Closed Wednesday due to snow",
     "Schools will be open Wednesday", NEXT_DAY, ALPHA_SCHOOL),
    ("f5", F5, "Closed Wed Nov 18", "Closed Wednesday, Nov. 18", "Open Wednesday", NEXT_DAY,
     ALPHA_SCHOOL),
    ("f5", F5, "Closed Wednesday", "Closed Wednesday due to snow", "Closing canceled", NEXT_DAY,
     ALPHA_SCHOOL),
    ("f5", F5, "Closed Wednesday", "Closed Wednesday due to snow", "Open Wednesday", NEXT_DAY,
     ALPHA_DISTRICT),
    ("f5", F5, "Closed", "Closed due to snow", "Open", SAME_MORNING, ALPHA_SCHOOL),
    ("f5", F5, "Closed", "Closed due to snow", "Closing canceled", SAME_MORNING, ALPHA_SCHOOL),
    ("f5", F5, "Closed", "Closed due to snow", "Open", SAME_MORNING, ALPHA_DISTRICT),
    ("stub", stub_reader, "Closed Wednesday", "Closed Wednesday due to snow", "Open Wednesday",
     NEXT_DAY, ALPHA_SCHOOL),
    ("stub", stub_reader, "Closed Wednesday", "Closed Wednesday due to snow",
     "Closing rescinded", NEXT_DAY, ALPHA_DISTRICT),
    ("stub", stub_reader, "Closed", "Closed due to snow", "Open", SAME_MORNING, ALPHA_SCHOOL),
    ("stub", stub_reader, "Closed", "Closed due to snow", "Closing rescinded", SAME_MORNING,
     ALPHA_SCHOOL),
]  # fmt: skip


@pytest.mark.parametrize("case", CASES, ids=[f"{c[0]}-{c[2]}-{c[4]}-{c[6][10:]}" for c in CASES])
def test_r4c_b1_a_re_worded_row_never_overrides_a_reversal_posted_since(case: Case) -> None:
    label, reader, first, reworded, reversal, times, name = case
    after_reversal, after_reword, world = _reword_after_reversal(
        reader, first=first, reworded=reworded, reversal=reversal, name=name, **times
    )
    assert after_reversal == {}, label
    assert after_reword == {}, label
    successor = next(r for s in world.resolve() if s.source_id == A for r in s.rows if r.present)
    assert successor.row.lo is not None
    assert successor.row.lo <= at(times["posted"]) - timedelta(minutes=5)


LONE: list[tuple[str, str, dict[str, str], Lit]] = [
    ("Closed Wednesday", "Closed Wednesday due to snow", NEXT_DAY, {(0, "2026-11-18"): "CLOSED"}),
    ("Closed", "Closed due to snow", SAME_MORNING, {(0, "2026-11-17"): "CLOSED"}),
]


@pytest.mark.parametrize(("label", "reader"), [("stub", stub_reader), ("f5", F5)])
@pytest.mark.parametrize("case", LONE, ids=["next-day", "same-morning"])
def test_r4c_b1_a_re_worded_row_with_nothing_posted_since_still_lights(
    label: str, reader: StatusReader, case: tuple[str, str, dict[str, str], Lit]
) -> None:
    first, reworded, times, shown = case
    world = World(reader=reader)
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 08:00"), [])
    world.read(at(times["posted"]) - timedelta(minutes=5), [])
    world.read(at(times["posted"]), [row(ALPHA_SCHOOL, first)])
    world.read(at(times["reworded_at"]) - timedelta(minutes=5), [row(ALPHA_SCHOOL, first)])
    assert lit(world.publish(at(times["reworded_at"]) - timedelta(minutes=4))) == shown, label
    world.read(at(times["reworded_at"]), [row(ALPHA_SCHOOL, reworded)])
    assert lit(world.publish(at(times["reworded_at"]) + timedelta(minutes=5))) == shown, label


@pytest.mark.parametrize(("label", "reader"), [("stub", stub_reader), ("f5", F5)])
def test_r4c_b1_a_reversal_posted_before_the_first_posting_does_not_darken_the_re_word(
    label: str, reader: StatusReader
) -> None:
    world = World(reader=reader)
    world.stations[B] = station(B)
    for source in (A, B):
        world.read(at("2026-11-13 15:00"), [], source=source)
        world.read(at("2026-11-16 13:55"), [], source=source)
    world.read(at("2026-11-16 14:00"), [row(ALPHA_SCHOOL, "Open Wednesday")], source=B)
    world.read(at("2026-11-16 15:55"), [], source=A)
    world.read(at("2026-11-16 16:00"), [row(ALPHA_SCHOOL, "Closed Wednesday")])
    shown = {(0, "2026-11-18"): "CLOSED"}
    world.read(at("2026-11-17 17:55"), [row(ALPHA_SCHOOL, "Closed Wednesday")])
    world.read(at("2026-11-17 17:55"), [row(ALPHA_SCHOOL, "Open Wednesday")], source=B)
    assert lit(world.publish(at("2026-11-17 17:56"))) == shown, label
    world.read(at("2026-11-17 18:00"), [row(ALPHA_SCHOOL, "Closed Wednesday due to snow")])
    world.read(at("2026-11-17 18:00"), [row(ALPHA_SCHOOL, "Open Wednesday")], source=B)
    assert lit(world.publish(at("2026-11-17 18:05"))) == shown, label


def test_r4c_b1_the_dating_is_kept_in_the_ledger_and_carried_down_a_chain_of_re_words() -> None:
    world = World(reader=F5)
    world.read(at("2026-11-13 15:00"), [])
    world.read(at("2026-11-16 15:55"), [])
    world.read(at("2026-11-16 16:00"), [row(ALPHA_SCHOOL, "Closed Wednesday")])
    world.publish(at("2026-11-16 16:05"))
    texts = ["Closed Wednesday due to snow", "Closed Wednesday due to snow and ice"]
    for hour, text in zip(("2026-11-17 10:00", "2026-11-17 18:00"), texts, strict=True):
        world.read(at(hour) - timedelta(minutes=5), world.last[A])
        world.read(at(hour), [row(ALPHA_SCHOOL, text)])
        assert lit(world.publish(at(hour) + timedelta(minutes=5))) == {(0, "2026-11-18"): "CLOSED"}
        (present,) = [r for r in world.ledger.rows(A) if r.hi == at(hour)]
        assert (present.lo, present.start, present.pred) == (
            at("2026-11-16 15:55"),
            Start.WARM,
            None,
        )
    counts = world.resolve()[0].counts
    assert counts.get("successor:same_either_way") is None  # settled once, on the first pass


def _entry(hi: datetime, lo: datetime | None, start: Start, stamp: datetime | None) -> LedgerRow:
    return LedgerRow(
        key=b"k",
        source_id=A,
        hi=hi,
        lo=lo,
        start=start,
        row_stamp=stamp,
        last_seen=hi,
        absent_since=None,
        gone=False,
        ident=b"i",
        pred=None,
        lapsed=False,
    )


def test_r4c_b1_the_widened_interval_starts_at_the_earliest_known_posting() -> None:
    resolver = World().resolver()
    own = _entry(at("2026-11-17 18:00"), at("2026-11-17 17:30"), Start.WARM, None)
    warm = _entry(at("2026-11-16 16:00"), at("2026-11-16 15:55"), Start.WARM, None)
    stamped = _entry(at("2026-11-16 16:00"), None, Start.COLD, at("2026-11-16 15:00"))
    stale_stamp = _entry(at("2026-11-16 16:00"), None, Start.COLD, at("2026-11-10 15:00"))
    cold = _entry(at("2026-11-16 16:00"), None, Start.CHURN, None)
    assert resolver._widened(own, warm).lo == at("2026-11-16 15:55")
    assert resolver._widened(own, stamped).lo == at("2026-11-16 15:00")
    assert (resolver._widened(own, stale_stamp).lo, resolver._widened(own, cold).start) == (
        None,
        Start.CHURN,
    )
    undated = own._replace(lo=None, start=Start.COLD)
    assert resolver._widened(undated, warm) == undated  # an unknown start stays unknown

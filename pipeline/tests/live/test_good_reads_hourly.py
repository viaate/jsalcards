"""``good_reads`` keeps each source's first good read of every UTC hour (S8-E state size).

The resolver asks the table one question: was the source read on local date D in zone Z
(the previous-school-day rule). A property test checks that the thinned table answers it
exactly as the table of every read does, for every US zone, across DST changes.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.live.ledger import Ledger, Outcome

ZONES = (
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Phoenix",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "America/Puerto_Rico",
    "Pacific/Guam",
    "Pacific/Pago_Pago",
)
START = datetime(2026, 10, 30, 0, tzinfo=UTC)  # the days around the end of DST (Nov 1)


def _days(reads: list[datetime], zone: str) -> set[date]:
    tz = ZoneInfo(zone)
    return {read.astimezone(tz).date() for read in reads}


@settings(max_examples=60, deadline=None)
@given(st.lists(st.integers(min_value=1, max_value=400), min_size=1, max_size=120))
def test_the_thinned_table_answers_every_local_date_as_every_read_does(gaps: list[int]) -> None:
    ledger = Ledger(":memory:")
    moment = START
    every: list[datetime] = []
    for gap in gaps:
        moment += timedelta(minutes=gap, seconds=gap % 7)
        ledger.observe("synthetic-src", Outcome.EMPTY, moment)
        every.append(moment)
    kept = ledger.good_reads("synthetic-src")
    hours = {(read.year, read.month, read.day, read.hour) for read in every}
    assert len(kept) == len(hours)  # one per UTC hour
    for zone in ZONES:
        assert _days(kept, zone) == _days(every, zone)
    assert ledger.source("synthetic-src").last_good_at == every[-1]  # type: ignore[union-attr]


def test_a_pass_every_5_minutes_keeps_12_times_fewer_rows() -> None:
    ledger = Ledger(":memory:")
    for step in range(24 * 12):
        ledger.observe("synthetic-src", Outcome.EMPTY, START + timedelta(minutes=5 * step))
    kept = ledger.good_reads("synthetic-src")
    assert len(kept) == 24
    assert kept[:2] == [START, START + timedelta(hours=1)]  # the first of each hour
    # a 304 that confirms the last read counts the same way
    ledger.observe("synthetic-src", Outcome.NOT_MODIFIED, START + timedelta(hours=24, minutes=1))
    ledger.observe("synthetic-src", Outcome.NOT_MODIFIED, START + timedelta(hours=24, minutes=6))
    assert len(ledger.good_reads("synthetic-src")) == 25


def test_sources_are_thinned_apart() -> None:
    ledger = Ledger(":memory:")
    ledger.observe("synthetic-a", Outcome.EMPTY, START + timedelta(minutes=10))
    ledger.observe("synthetic-b", Outcome.EMPTY, START + timedelta(minutes=12))
    ledger.observe("synthetic-a", Outcome.EMPTY, START + timedelta(minutes=15))
    assert len(ledger.good_reads("synthetic-a")) == 1
    assert len(ledger.good_reads("synthetic-b")) == 1

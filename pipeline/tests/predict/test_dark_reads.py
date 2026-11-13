"""The prediction reads a status whose reason code is above 7 as the dark it replaces
(ALL-CLOSINGS lane T, docs/predict.md "Stated causes read as dark"): through one loader per
input, so every term and label that reads it gives what the file without that status gives.
Each test holds a head file (a code above 7 lit where the weather left a school dark) beside
its base file (the same file without it), and a mutation check: the raw read differs. Every
school, status and day here is SYNTHETIC.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from predict import world
from predict.test_learn import WHOLE, listing, state_source
from predict.test_opens import TODAY, TOMORROW, closings, opens
from predict.test_publish import NOW, MemoryHost, make_pass
from snowlight.live.history import BY, BY_HOLD, ChangeLog, Event, Shown
from snowlight.live.history import Change as LogChange
from snowlight.live.morning import ANY_KIND, MorningLog
from snowlight.predict import call_time, cli, dark_reads, host_files
from snowlight.predict.live_labels import Morning, lit_of
from snowlight.predict.live_read import StateReadSource
from snowlight.predict.serve import closed_districts
from snowlight.schemas.live import Closing, ClosingsFile, DayTimeline, as_dark
from snowlight.schemas.vocab import Reason, Status

OPENS, CLOSINGS = "v1/live/opens.json", "v1/live/closings.json"
DAY = date(2026, 1, 6)
DAY_FILE = f"v1/live/days/{DAY.isoformat()}.json"
W = Reason.WINTER_STORM


@pytest.fixture(autouse=True)
def _forgotten() -> Iterator[None]:
    host_files.forget()
    yield
    host_files.forget()


def day_file(*, head: bool) -> DayTimeline:
    """Schools 0 and 1 (district 1) closed and remote for snow, school 4 closed with no reason
    named, private school 7 closed for snow from minute 400. The head also lit school 1 for
    code 13 after its remote day was taken back, school 2 (district 2) for code 99 alone, and
    private school 7 for code 13 before its snow closing."""
    if head:
        columns = {
            "gaps": (0, 0, 0, 1, 2),
            "counts": (1, 2, 1, 1, 2),
            "minutes": (-120, -100, 200, 100, 300, 50, 400),
            "statuses": (Status.CLOSED, Status.REMOTE, Status.CLOSED, Status.CLOSED,
                         Status.CLOSED, Status.CLOSED, Status.CLOSED),
            "reasons": (W, W, 13, 99, None, 13, W),
        }  # fmt: skip
    else:
        columns = {
            "gaps": (0, 0, 2, 2),
            "counts": (1, 2, 1, 1),
            "minutes": (-120, -100, 200, 300, 400),
            "statuses": (Status.CLOSED, Status.REMOTE, None, Status.CLOSED, Status.CLOSED),
            "reasons": (W, W, None, None, W),
        }
    return DayTimeline.model_validate(
        {
            "schema_version": 1,
            "day": DAY,
            "generated_at": world.utc("2026-01-07T05:00:00"),
            "directory": world.STAMP,
            "content_sha256": None,
            "final": True,
            "shifts": (),
            "clocks": (),
            **columns,
        }
    )


def closings_file(*, head: bool) -> ClosingsFile:
    """School 4 closed and school 5 delayed for snow; the head also lists school 0 (district
    1, said open) closed for code 13, and both schools of district 2 for codes 13 and 99."""
    base = closings([(4, TODAY, Status.CLOSED), (5, TODAY, Status.DELAYED)])
    if not head:
        return base
    stated = [
        Closing(0, TODAY, Status.CLOSED, NOW - timedelta(hours=1), 13),
        Closing(2, TODAY, Status.CLOSED, NOW - timedelta(hours=1), 13),
        Closing(3, TODAY, Status.CLOSED, None, 99),
        Closing(3, TOMORROW, Status.CLOSED, None, 13),
    ]
    return ClosingsFile.encode(
        [*base.closings(), *stated], generated_at=base.generated_at, directory=base.directory
    )


def host(*, head: bool) -> MemoryHost:
    found = MemoryHost()
    found.files[OPENS] = opens([(0, TODAY), (1, TODAY)]).to_json_bytes()
    found.files[CLOSINGS] = closings_file(head=head).to_json_bytes()
    found.files[DAY_FILE] = day_file(head=head).to_json_bytes()
    return found


def test_the_loaders_read_the_head_as_its_base() -> None:
    head, base = day_file(head=True), day_file(head=False)
    assert as_dark(head) == base
    assert dark_reads.timeline(head.to_json_bytes(), where=DAY_FILE) == base
    assert dark_reads.closings(closings_file(head=True).to_json_bytes(), where=CLOSINGS) == (
        closings_file(head=False)
    )
    # The raw reader stays raw (the notifier reads every status as it is).
    assert host_files.timeline(head.to_json_bytes(), where=DAY_FILE) == head
    assert host_files.closings(closings_file(head=True).to_json_bytes(), where=CLOSINGS) == (
        closings_file(head=True)
    )
    # On named codes the loaders give the raw read.
    assert dark_reads.timeline(base.to_json_bytes(), where=DAY_FILE) == base


def test_the_labels_and_the_call_times_read_the_head_as_the_base(tmp_path: Path) -> None:
    files = {
        f"live/days/{DAY.isoformat()}.json": day_file(head=True).to_json_bytes(),
    }
    source = state_source(tmp_path)

    def read_file(path: str) -> bytes | None:
        return files.get(path)

    source.read_file = read_file
    read = source.timeline(DAY)
    assert read == day_file(head=False)
    assert read is not None
    assert lit_of(read) == lit_of(day_file(head=False))
    assert call_time._runs(read) == call_time._runs(day_file(head=False))
    # Mutation check: read raw, the head does not give the base (and its codes cannot be
    # named as a weather reason at all).
    with pytest.raises(ValueError, match="is not a valid Reason"):
        lit_of(day_file(head=True))
    with pytest.raises(ValueError, match="is not a valid Reason"):
        call_time._runs(day_file(head=True))


def test_the_day_after_reads_the_head_as_the_base() -> None:
    found = []
    for head in (True, False):
        run = make_pass(host(head=head), directory=world.directory())
        model = run.serve_model(world.directory())
        districts = cli._closed_on(run, model)(DAY)
        schools = cli._closed_on(run, model, private=True)(DAY)
        found.append((districts, schools))
    assert found[0] == found[1]
    assert found[0][0] == frozenset({1})
    # The day after reads the weather reasons alone, so even a raw read gives the base here;
    # the loader is the same one every other input's reader takes.
    model = make_pass(host(head=True), directory=world.directory()).serve_model(world.directory())
    raw = host_files.timeline(day_file(head=True).to_json_bytes(), where=DAY_FILE)
    assert closed_districts(raw, model, world.CONFIG.weather.covered_share) == found[1][0]


def test_the_neighbors_term_and_said_open_read_the_head_as_the_base() -> None:
    days = (TODAY, TOMORROW)
    neighbors, said = [], []
    for head in (True, False):
        run = make_pass(host(head=head), directory=world.directory())
        model = run.serve_model(world.directory())
        neighbors.append(cli._neighbors(run, model, days, NOW))
        said.append(cli._said_open(run, model, NOW))
    assert neighbors[0] == neighbors[1]
    assert neighbors[0].read
    assert said[0] == said[1]
    # District 1 said school is on, and only a code above 7 lists one of its schools: it is
    # still said open, as on the base.
    assert said[0].district(TODAY, 1)


def xlisting(day: date, nces: str, source: str, code: int) -> LogChange:
    at = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=11)
    shown = Shown(int(Status.CLOSED), code, None, None)
    return LogChange(at, day, nces, Event.LIT, shown, {"source_id": source})


def morning_folder(folder: Path, *, head: bool) -> None:
    """The record of test_learn's state folder; the head's change log also holds the TV list
    lighting district 2900003 for code 13 on Jan 2 (a second day would make the list carry
    it), and district 2900001 for code 99 alone on the day, held dark by the stop."""
    log = MorningLog(folder / "morning")
    log.record(world.utc("2026-01-06T13:00:00"), shown="v1", reads={"tv": WHOLE}, unknown=(),
               named={"2900002": {"*": {ANY_KIND}}})  # fmt: skip
    log.record(world.utc("2026-01-05T23:00:00"), shown="v1", reads={}, unknown=(),
               named={"2900003": {DAY.isoformat(): {"closed"}}})  # fmt: skip
    log.record(world.utc("2026-01-06T17:00:00"), shown="v1", reads={}, unknown=(), named={})
    lines = [
        listing(date(2026, 1, 2), "290000200003", "tv"),
        listing(date(2026, 1, 5), "290000200003", "tv"),
        listing(date(2026, 1, 5), "290000300004", "tv"),
    ]
    if head:
        lines += [
            xlisting(date(2026, 1, 2), "290000300004", "tv", 13),
            xlisting(DAY, "290000100001", "tv", 99),
            LogChange(world.utc("2026-01-06T14:00:00"), DAY, "290000100001", Event.DARK, None,
                      {BY: BY_HOLD}),
        ]  # fmt: skip
    ChangeLog(folder / "changes").commit(lines)


def test_the_live_audience_and_the_stop_read_the_head_as_the_base(tmp_path: Path) -> None:
    found: list[Morning] = []
    read: list[Morning] = []
    lit: list[object] = []
    for head in (True, False):
        folder = tmp_path / str(head)
        morning_folder(folder, head=head)
        morning = state_source(folder).morning(DAY)
        assert isinstance(morning, Morning)
        found.append(morning)
        later = StateReadSource(state_source(folder))
        reads = later.morning(DAY)
        assert isinstance(reads, Morning)
        read.append(reads)
        lit.append((later.lit_by(DAY), later.lit_by(date(2026, 1, 2))))
    assert found[0] == found[1]
    assert found[0].audience == {"tv": {"2900002": date(2026, 1, 2)}}
    assert not found[0].held
    assert read[0] == read[1]
    assert lit[0] == lit[1]
    # Mutation check: the raw log carries 2900003 for the list and holds the day.
    raw = ChangeLog(tmp_path / "True" / "changes")
    from snowlight.predict.live_labels import audience_of, held_on  # noqa: PLC0415

    assert "2900003" in audience_of(raw, DAY, world.CONFIG.labels.audience_days)["tv"]
    assert held_on(raw, DAY)

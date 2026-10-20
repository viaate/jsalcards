"""One live pass, wired (SYNTHETIC world): every known source resolved, holds only for sources
read in this process, orphans darken only, the healthy share, and the read conversion."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from live.test_edition import OWN, Source
from live.world import ALPHA_SCHOOL, World, at, row, station
from snowlight.live.edition import EditionWatch
from snowlight.live.ingest import Ingest, SourceRead
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.publish import Exit, LivePublisher
from snowlight.live.publishers import DirPublisher
from snowlight.live.reads import source_read
from snowlight.schemas.directory import DirectoryEdition
from snowlight.schemas.live import ClosingsFile
from snowlight.sources.stations.fetch import RunResult
from snowlight.sources.stations.model import HealthStatus, RawRow, SourceHealth

A, B = "gray-synthetic", "gray-other"
EDITION = DirectoryEdition.model_validate(
    {**OWN.model_dump(mode="json"), "schools": 11, "districts": 6}
)


def _world() -> World:
    world = World()
    world.stations[B] = station(B)
    return world


def _ingest(
    world: World, tmp_path: Path, name: str = "run", due: frozenset[str] = frozenset({A})
) -> Ingest:
    publisher = LivePublisher(
        host=DirPublisher(tmp_path / "host"),
        directory=world.dir,
        state_dir=tmp_path / "state",
        internal_dir=tmp_path / "internal",
    )
    return Ingest(
        ledger=world.ledger,
        resolver=world.resolver(),
        stations=world.stations,
        publisher=publisher,
        watch=EditionWatch(own=EDITION, source=Source([EDITION])),
        internal_dir=tmp_path / name,
        due=due,
    )


def _published(tmp_path: Path) -> set[tuple[int, str]]:
    data = (tmp_path / "host" / "v1-shadow" / "live" / "closings.json").read_bytes()
    return {(c.school, c.status.name) for c in ClosingsFile.from_json_bytes(data).closings()}


def _warm(world: World, source: str, when: datetime) -> None:
    world.read(when - timedelta(days=1), [], source=source)
    world.read(when - timedelta(minutes=5), [], source=source)


CLOSED = (row(ALPHA_SCHOOL, "Closed due to snow"),)
RESCINDED = (row(ALPHA_SCHOOL, "Closing rescinded"),)


def test_a_pass_lights_what_it_reads(tmp_path: Path) -> None:
    world = _world()
    now = at("2026-11-17 11:05")
    _warm(world, A, now)
    ingest = _ingest(world, tmp_path)
    report = ingest.run_pass([SourceRead(A, ReadOutcome.OK, now, CLOSED)], now)
    assert report.exit is Exit.OK
    assert _published(tmp_path) == {(0, "CLOSED")}
    assert (tmp_path / "run" / "health.json").is_file()


def test_a_retraction_from_a_source_not_read_since_the_start_still_darkens(
    tmp_path: Path,
) -> None:
    world = _world()
    morning = at("2026-11-17 11:05")
    _warm(world, A, morning)
    _warm(world, B, morning + timedelta(minutes=15))
    world.read(morning, list(CLOSED), source=A)
    world.read(morning + timedelta(minutes=15), list(RESCINDED), source=B)
    # A process that read both and resolved before it stopped: B's retraction is derived.
    world.resolve()
    ingest = _ingest(world, tmp_path)
    later = morning + timedelta(minutes=20)
    report = ingest.run_pass([SourceRead(A, ReadOutcome.OK, later, CLOSED)], later)
    assert report.exit is Exit.OK
    assert _published(tmp_path) == set()


def test_a_row_never_derived_withholds_its_sources_states_until_it_is_read(
    tmp_path: Path,
) -> None:
    world = _world()
    morning = at("2026-11-17 11:05")
    _warm(world, A, morning)
    _warm(world, B, morning + timedelta(minutes=15))
    world.read(morning, list(CLOSED), source=A)
    # a process read B's retraction and stopped before it resolved it
    world.read(morning + timedelta(minutes=15), list(RESCINDED), source=B)
    ingest = _ingest(world, tmp_path)
    later = morning + timedelta(minutes=20)
    report = ingest.run_pass([SourceRead(A, ReadOutcome.OK, later, CLOSED)], later)
    # B covers the school's state and may have taken it back: its states stay dark
    assert report.exit is Exit.OK
    assert _published(tmp_path) == set()
    health = json.loads((tmp_path / "run" / "health.json").read_text())
    assert health["withheld"]["source_unknown"] == 1
    assert report.counts["unknown_states"] == 5
    # B read again: its retraction is derived, and the closing stays dark
    again = later + timedelta(minutes=5)
    report = ingest.run_pass([SourceRead(B, ReadOutcome.OK, again, RESCINDED)], again)
    assert report.exit is Exit.OK
    assert _published(tmp_path) == set()
    # a row never derived and first seen more than 36 hours ago no longer holds anything
    world2 = _world()
    _warm(world2, B, morning)
    world2.read(morning, list(RESCINDED), source=B)
    ingest2 = _ingest(world2, tmp_path / "second")
    assert ingest2.undecided(morning + timedelta(hours=36)) == {B: 1}
    assert ingest2.undecided(morning + timedelta(hours=36, seconds=1)) == {}
    # a source the registry no longer lists is never read again: its rows are left out
    del world2.stations[B]
    assert ingest2.undecided(morning + timedelta(hours=1)) == {}


def test_a_row_never_derived_elsewhere_leaves_other_states_lit(tmp_path: Path) -> None:
    world = World()
    world.stations[B] = station(B, states=("WY",))
    morning = at("2026-11-17 11:05")
    _warm(world, A, morning)
    _warm(world, B, morning)
    world.read(morning, list(RESCINDED), source=B)  # never derived
    ingest = _ingest(world, tmp_path)
    later = morning + timedelta(minutes=5)
    report = ingest.run_pass([SourceRead(A, ReadOutcome.OK, later, CLOSED)], later)
    assert report.exit is Exit.OK
    assert _published(tmp_path) == {(0, "CLOSED")}


def test_a_source_not_read_since_the_start_lights_nothing(tmp_path: Path) -> None:
    world = _world()
    morning = at("2026-11-17 11:05")
    _warm(world, B, morning)
    world.read(morning, list(CLOSED), source=B)
    world.resolve()  # the process that read it resolved it
    _warm(world, A, morning)
    ingest = _ingest(world, tmp_path)
    later = morning + timedelta(minutes=5)
    assert ingest.held(later)[B] is False
    report = ingest.run_pass([SourceRead(A, ReadOutcome.OK, later, ())], later)
    assert report.exit is Exit.OK
    assert _published(tmp_path) == set()
    # once B is read in this process, its closing stands
    again = later + timedelta(minutes=5)
    ingest.run_pass([SourceRead(B, ReadOutcome.OK, again, CLOSED)], again)
    assert _published(tmp_path) == {(0, "CLOSED")}


def test_a_source_gone_from_the_registry_only_darkens(tmp_path: Path) -> None:
    world = _world()
    morning = at("2026-11-17 11:05")
    _warm(world, A, morning)
    _warm(world, "gray-retired", morning + timedelta(minutes=15))
    world.read(morning, list(CLOSED), source=A)
    world.stations["gray-retired"] = station("gray-retired")
    world.read(morning + timedelta(minutes=15), list(RESCINDED), source="gray-retired")
    world.resolve()  # derived while it was listed
    del world.stations["gray-retired"]
    ingest = _ingest(world, tmp_path)
    later = morning + timedelta(minutes=20)
    ingest.run_pass([SourceRead(A, ReadOutcome.OK, later, CLOSED)], later)
    assert _published(tmp_path) == set()
    # and its own closings would never light
    world2 = _world()
    _warm(world2, "gray-retired", morning)
    world2.stations["gray-retired"] = station("gray-retired")
    world2.read(morning, list(CLOSED), source="gray-retired")
    world2.resolve()
    del world2.stations["gray-retired"]
    _warm(world2, A, morning)
    ingest2 = _ingest(world2, tmp_path / "second")
    ingest2.run_pass([SourceRead(A, ReadOutcome.OK, later, ())], later)
    assert _published(tmp_path / "second") == set()


def test_the_healthy_share_counts_each_source_once_in_15_minutes(tmp_path: Path) -> None:
    world = _world()
    ingest = _ingest(world, tmp_path, due=frozenset({A, B, "gray-third"}))
    now = at("2026-11-17 11:05")
    ingest.observe(
        [
            SourceRead(A, ReadOutcome.ERROR, now - timedelta(minutes=20)),
            SourceRead(B, ReadOutcome.OK, now - timedelta(minutes=10), ()),
            SourceRead(A, ReadOutcome.OK, now - timedelta(minutes=5), ()),
            SourceRead("gray-third", ReadOutcome.BLOCKED, now - timedelta(minutes=1)),
        ]
    )
    assert ingest.healthy_share(now) == pytest.approx(2 / 3)
    # a source due and not read counts as not healthy; one read and not due does not count
    ingest.due = frozenset({A, B, "gray-fourth"})
    assert ingest.healthy_share(now) == pytest.approx(2 / 3)
    ingest.due = None  # the active stations of the registry: A and B
    assert ingest.healthy_share(now) == 1.0
    assert ingest.healthy_share(now + timedelta(hours=1)) == 0.0


def test_a_pass_with_nothing_healthy_is_refused(tmp_path: Path) -> None:
    world = _world()
    now = at("2026-11-17 11:05")
    ingest = _ingest(world, tmp_path)
    report = ingest.run_pass([SourceRead(A, ReadOutcome.ERROR, now)], now)
    assert (report.exit, report.refusals) == (Exit.REFUSED, ("health",))


def _health(status: HealthStatus, **extra: object) -> SourceHealth:
    return SourceHealth.model_validate(
        {
            "source_id": A,
            "url": "https://example.invalid/closings",
            "checked_at": "2026-11-17T11:05:00Z",
            "status": status,
            "rows": 1 if status is HealthStatus.OK else 0,
            **(
                {"reason": "SYNTHETIC reason"}
                if status not in {HealthStatus.OK, HealthStatus.EMPTY}
                else {}
            ),
            **extra,
        }
    )


def _raw() -> RawRow:
    return RawRow.model_validate(
        {
            "source_id": A,
            "fetched_at": "2026-11-17T11:04:30Z",
            "raw_name": ALPHA_SCHOOL,
            "raw_status": "Closed",
            "raw_updated_text": None,
            "raw_extra": {},
        }
    )


@pytest.mark.parametrize(
    ("health", "outcome", "rows"),
    [
        (_health(HealthStatus.OK, variant="v"), ReadOutcome.OK, 1),
        (_health(HealthStatus.OK, not_modified=True), ReadOutcome.NOT_MODIFIED, 1),
        (_health(HealthStatus.EMPTY), ReadOutcome.EMPTY, 0),
        (_health(HealthStatus.ERROR, http_status=403), ReadOutcome.BLOCKED, 0),
        (_health(HealthStatus.ERROR, http_status=500), ReadOutcome.ERROR, 0),
        (_health(HealthStatus.STALE), ReadOutcome.ERROR, 0),
    ],
)
def test_station_reads_become_ledger_reads(
    health: SourceHealth, outcome: ReadOutcome, rows: int
) -> None:
    world = _world()
    result = RunResult(health=[health], rows=[_raw()])
    read = source_read(world.stations[A], result, world.dir)
    assert read is not None
    assert (read.outcome, len(read.rows)) == (outcome, rows)
    if rows:
        assert read.fetched_at == at("2026-11-17 11:04").replace(second=30)
        assert read.rows[0].name == ALPHA_SCHOOL


def test_a_skipped_station_gives_no_read() -> None:
    world = _world()
    skipped = RunResult(health=[_health(HealthStatus.SKIPPED)])
    assert source_read(world.stations[A], skipped, world.dir) is None
    assert source_read(world.stations[A], RunResult(), world.dir) is None

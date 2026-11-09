"""The season counts (live/season.json, snowlight.live.season): only final days count, each
school once a day under the status its day ended on, by NCES id across directory editions,
within the school year. Every school, status and day here is SYNTHETIC."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from live.world import ALPHA, ALPHA_SCHOOL, EASTERN, PACIFIC, World, at, directory, row
from snowlight.live.edition import EditionState, EditionVerdict
from snowlight.live.history import Change, Event, Shown, content_of, timeline
from snowlight.live.merge import AdminStatus, Merged, with_overrides
from snowlight.live.publish import LivePublisher, Memory, Mode, blank_files
from snowlight.live.publishers import DirPublisher, PublishError
from snowlight.live.resolve import LiveDirectory, LiveSchool
from snowlight.live.season import (
    LEDGER,
    SEASON,
    SeasonLedger,
    build_season,
    edition_ids,
    final_statuses,
    last_final_day,
    school_year,
    season_file,
)
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import DayTimeline, SeasonFile
from snowlight.schemas.vocab import Status

STAMP = DirectoryStamp(generated_on=date(2026, 10, 14), schools=11, districts=6)
SHADOW = "v1-shadow"
CLOSED, DELAYED, REMOTE, EARLY = (
    Status.CLOSED,
    Status.DELAYED,
    Status.REMOTE,
    Status.EARLY_DISMISSAL,
)
WORLD = directory()
IDS = edition_ids(WORLD)

type Run = Sequence[tuple[str, Status | None]]
"""One school's changes on a day: the UTC time ("HH:MM") and what the map showed then."""


def day_file(
    day: date,
    runs: Mapping[str, Run],
    *,
    final: bool = True,
    on: LiveDirectory = WORLD,
    stamp: DirectoryStamp = STAMP,
) -> DayTimeline:
    """A day timeline built as the publisher builds one, from change lines (by NCES id)."""
    changes: list[Change] = []
    for nces_id, run in runs.items():
        before: Status | None = None
        for clock, status in run:
            hour, minute = (int(part) for part in clock.split(":"))
            moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)
            shift = 60 if status in {DELAYED, EARLY} else None
            shown = None if status is None else Shown(int(status), None, shift, None)
            event = Event.DARK if status is None else Event.LIT if before is None else Event.CHANGED
            changes.append(Change(moment, day, nces_id, event, shown, {}))
            before = status
    made = timeline(
        day,
        changes,
        directory=on,
        stamp=stamp,
        generated_at=datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=2),
        final=final,
    )
    assert made is not None
    return made


def counts(season: SeasonFile | None) -> dict[int, tuple[int, int, int, int]]:
    assert season is not None
    return season.rows()


def ours(made: DayTimeline) -> Mapping[int, str] | None:
    """The current edition's ids, for a timeline built from it."""
    return IDS if made.content_sha256 == content_of(WORLD) and made.directory == STAMP else None


def season_of(archives: Sequence[DayTimeline], through: date) -> SeasonFile | None:
    return build_season(archives, ids_of=ours, through=through, directory=WORLD, stamp=STAMP)


# The rules ------------------------------------------------------------------------------


def test_a_day_in_progress_never_counts() -> None:
    open_day = day_file(date(2026, 11, 18), {ALPHA[0]: [("12:00", CLOSED)]}, final=False)
    with pytest.raises(ValueError, match="in progress"):
        final_statuses(open_day, IDS)
    done = day_file(date(2026, 11, 17), {ALPHA[0]: [("12:00", CLOSED)]})
    season = season_of([done, open_day], date(2026, 11, 18))
    assert counts(season) == {0: (1, 0, 0, 0)}
    assert season is not None
    assert (season.since, season.through) == (date(2026, 11, 17), date(2026, 11, 18))
    assert season_of([open_day], date(2026, 11, 18)) is None


def test_a_status_taken_back_by_the_end_of_the_day_counts_nowhere() -> None:
    made = day_file(
        date(2026, 11, 17),
        {
            ALPHA[0]: [("11:00", CLOSED), ("13:00", None)],  # retracted
            PACIFIC: [("12:00", DELAYED), ("13:00", None), ("15:00", CLOSED)],  # lit again
            EASTERN: [("11:00", REMOTE), ("23:00", None)],  # taken down that evening
        },
    )
    assert final_statuses(made, IDS) == {PACIFIC: CLOSED}
    assert counts(season_of([made], date(2026, 11, 17))) == {7: (1, 0, 0, 0)}


def test_a_status_changed_during_the_day_counts_once_under_the_last() -> None:
    made = day_file(
        date(2026, 11, 17),
        {ALPHA[0]: [("10:00", DELAYED), ("11:30", CLOSED), ("13:00", REMOTE)]},
    )
    assert final_statuses(made, IDS) == {ALPHA[0]: REMOTE}
    assert counts(season_of([made], date(2026, 11, 17))) == {0: (0, 0, 1, 0)}


def test_each_status_counts_in_its_own_column_once_a_day() -> None:
    first = day_file(
        date(2026, 11, 16),
        {
            ALPHA[0]: [("12:00", CLOSED)],
            ALPHA[1]: [("12:00", DELAYED)],
            PACIFIC: [("16:00", REMOTE)],
            EASTERN: [("15:00", EARLY)],
        },
    )
    second = day_file(
        date(2026, 11, 17),
        {ALPHA[0]: [("12:00", CLOSED)], ALPHA[1]: [("12:00", CLOSED)], EASTERN: [("15:00", EARLY)]},
    )
    season = season_of([first, second], date(2026, 11, 17))
    assert counts(season) == {
        0: (2, 0, 0, 0),
        1: (1, 1, 0, 0),
        7: (0, 0, 1, 0),
        10: (0, 0, 0, 2),
    }
    assert season is not None
    assert season.gaps == (0, 0, 5, 2)


def test_two_timelines_for_one_day_are_refused() -> None:
    made = day_file(date(2026, 11, 17), {ALPHA[0]: [("12:00", CLOSED)]})
    with pytest.raises(ValueError, match="two timelines"):
        season_of([made, made], date(2026, 11, 17))


def test_the_school_year_runs_july_1_to_june_30() -> None:
    assert school_year(date(2027, 6, 30)) == "2026-2027"
    assert school_year(date(2027, 7, 1)) == "2027-2028"
    assert school_year(date(2026, 12, 31)) == "2026-2027"
    june = day_file(date(2027, 6, 30), {ALPHA[0]: [("12:00", CLOSED)]})
    july = day_file(date(2027, 7, 1), {ALPHA[0]: [("12:00", DELAYED)]})
    october = day_file(date(2026, 10, 27), {ALPHA[0]: [("12:00", CLOSED)]})
    old = season_of([october, june, july], date(2027, 6, 30))
    assert old is not None
    assert (old.season, old.since, old.through) == ("2026-2027", date(2026, 10, 27), june.day)
    assert counts(old) == {0: (2, 0, 0, 0)}
    new = season_of([october, june, july], date(2027, 7, 1))
    assert new is not None
    assert (new.season, new.since, new.through) == ("2027-2028", july.day, july.day)
    assert counts(new) == {0: (0, 1, 0, 0)}
    # the ledger keeps only the school year of the day it counts through
    ledger = SeasonLedger(since=date(2026, 10, 27)).with_days(
        {june.day: {ALPHA[0]: CLOSED}, july.day: {ALPHA[0]: DELAYED}}, through=july.day
    )
    assert list(ledger.days) == [july.day]
    kept = ledger.season(through=july.day, directory=WORLD, stamp=STAMP)
    assert kept is not None
    assert (kept.since, counts(kept)) == (july.day, {0: (0, 1, 0, 0)})


def test_the_last_day_counted_is_the_last_day_over_everywhere() -> None:
    assert last_final_day(at("2026-11-18 07:59")) == date(2026, 11, 16)
    assert last_final_day(at("2026-11-18 08:00")) == date(2026, 11, 17)


def _school(nces_id: str, index: int) -> LiveSchool:
    return replace(WORLD.schools[nces_id], index=index)


def test_another_edition_is_mapped_by_nces_id_never_by_position() -> None:
    gone = "990000000001"
    old = LiveDirectory(
        schools={
            PACIFIC: _school(PACIFIC, 0),
            ALPHA[0]: _school(ALPHA[0], 5),
            gone: replace(WORLD.schools[ALPHA[1]], index=7),
        },
        district_sizes={},
        edition="synthetic-old-edition",
    )
    old_stamp = DirectoryStamp(generated_on=date(2026, 9, 1), schools=8, districts=3)
    before = day_file(
        date(2026, 11, 16),
        {PACIFIC: [("16:00", DELAYED)], ALPHA[0]: [("12:00", CLOSED)], gone: [("12:00", CLOSED)]},
        on=old,
        stamp=old_stamp,
    )
    # by position, index 0 would be Alpha and index 7 Pacific in the current edition
    assert before.schools() == (0, 5, 7)
    now = day_file(date(2026, 11, 17), {ALPHA[0]: [("12:00", CLOSED)]})
    olds = edition_ids(old)

    def ids_of(made: DayTimeline) -> Mapping[int, str] | None:
        return olds if made.directory == old_stamp else ours(made)

    season = build_season(
        [before, now], ids_of=ids_of, through=now.day, directory=WORLD, stamp=STAMP
    )
    assert counts(season) == {0: (2, 0, 0, 0), 7: (0, 1, 0, 0)}  # the gone school: left out
    assert season is not None
    assert (season.directory, season.since) == (STAMP, before.day)


def test_a_day_whose_edition_is_not_known_is_left_out_and_counting_begins_after_it() -> None:
    old_stamp = DirectoryStamp(generated_on=date(2026, 9, 1), schools=11, districts=6)
    first = day_file(date(2026, 11, 13), {ALPHA[0]: [("12:00", CLOSED)]})
    unknown = day_file(date(2026, 11, 16), {ALPHA[0]: [("12:00", CLOSED)]}, stamp=old_stamp)
    last = day_file(date(2026, 11, 17), {ALPHA[0]: [("12:00", DELAYED)]})

    def ids_of(made: DayTimeline) -> Mapping[int, str] | None:
        return None if made.directory == old_stamp else IDS

    season = build_season(
        [first, unknown, last], ids_of=ids_of, through=last.day, directory=WORLD, stamp=STAMP
    )
    assert season is not None
    assert (season.since, counts(season)) == (date(2026, 11, 17), {0: (0, 1, 0, 0)})
    alone = build_season([unknown], ids_of=ids_of, through=last.day, directory=WORLD, stamp=STAMP)
    assert alone is None


def test_a_school_the_current_edition_does_not_hold_is_left_out() -> None:
    season = season_file(
        {date(2026, 11, 17): {"990000000001": CLOSED, ALPHA[0]: CLOSED}},
        since=date(2026, 11, 17),
        through=date(2026, 11, 17),
        directory=WORLD,
        stamp=STAMP,
    )
    assert counts(season) == {0: (1, 0, 0, 0)}


# The file -------------------------------------------------------------------------------


def _encode(rows: Mapping[int, tuple[int, int, int, int]], **changed: object) -> SeasonFile:
    fields: dict[str, object] = {
        "season": "2026-2027",
        "since": date(2026, 10, 27),
        "through": date(2026, 11, 17),
        "directory": STAMP,
        "content_sha256": "5" * 64,
    }
    fields.update(changed)
    return SeasonFile.encode(rows, **fields)  # type: ignore[arg-type]


def test_the_file_round_trips_its_rows_and_leaves_out_schools_with_none() -> None:
    rows = {3: (2, 1, 0, 0), 0: (0, 0, 0, 1), 10: (1, 0, 4, 0), 6: (0, 0, 0, 0)}
    made = _encode(rows)
    assert made.gaps == (0, 2, 6)
    data = made.to_json_bytes()
    back = SeasonFile.from_json_bytes(data)
    assert back == made
    assert back.rows() == {0: (0, 0, 0, 1), 3: (2, 1, 0, 0), 10: (1, 0, 4, 0)}
    assert _encode(dict(reversed(list(rows.items())))).to_json_bytes() == data


@pytest.mark.parametrize(
    ("rows", "changed", "words"),
    [
        ({0: (20, 3, 0, 0)}, {}, "more days counted"),
        ({11: (1, 0, 0, 0)}, {}, "not in the directory"),
        ({0: (1, 0, 0, 0)}, {"content_sha256": None}, "emptied file"),
        ({}, {"since": date(2026, 6, 30)}, "school year"),
        ({}, {"since": date(2026, 11, 18)}, "school year"),
        ({}, {"through": date(2027, 7, 1)}, "school year"),
    ],
)
def test_the_file_refuses_counts_it_cannot_hold(
    rows: Mapping[int, tuple[int, int, int, int]], changed: dict[str, object], words: str
) -> None:
    with pytest.raises(ValidationError, match=words):
        _encode(rows, **changed)


def test_the_ledger_round_trips_and_gives_the_same_bytes_from_the_same_days() -> None:
    days = {
        date(2026, 11, 17): {PACIFIC: DELAYED, ALPHA[0]: CLOSED},
        date(2026, 11, 16): {EASTERN: EARLY, ALPHA[1]: REMOTE},
    }
    ledger = SeasonLedger(since=date(2026, 11, 16), days=days)
    data = ledger.to_json_bytes()
    turned = {day: dict(reversed(list(found.items()))) for day, found in reversed(days.items())}
    assert SeasonLedger(since=date(2026, 11, 16), days=turned).to_json_bytes() == data
    back = SeasonLedger.from_bytes(data)
    assert back.to_json_bytes() == data
    assert back.days[date(2026, 11, 17)] == {ALPHA[0]: CLOSED, PACIFIC: DELAYED}
    assert b"SYNTHETIC" not in data
    with pytest.raises(ValueError, match="once a day"):
        SeasonLedger.from_bytes(data.replace(b'"3":["360000000001"]', b'"3":["200000100002"]'))


def test_a_first_ledger_counts_from_its_oldest_day_or_from_the_next_day() -> None:
    through = date(2026, 11, 17)
    found = {through: {ALPHA[0]: CLOSED}, date(2026, 11, 3): {PACIFIC: CLOSED}}
    assert SeasonLedger().with_days(found, through=through).since == date(2026, 11, 3)
    empty = SeasonLedger().with_days({}, through=through)
    assert empty.since == date(2026, 11, 18)
    assert empty.season(through=through, directory=WORLD, stamp=STAMP) is None
    # once set, it stays (a day it already holds is replaced by the newer build)
    later = SeasonLedger(since=date(2026, 11, 10)).with_days(found, through=through)
    assert later.since == date(2026, 11, 10)
    assert SeasonLedger().season(through=through, directory=WORLD, stamp=STAMP) is None


def test_a_ledger_that_does_not_read_begins_again(tmp_path: Path) -> None:
    path = tmp_path / LEDGER
    assert SeasonLedger.load(path) == SeasonLedger()
    path.write_bytes(b'{"schema_version": 2}')
    assert SeasonLedger.load(path) == SeasonLedger()


# The publisher --------------------------------------------------------------------------


def equal(now: datetime) -> EditionVerdict:
    return EditionVerdict(EditionState.EQUAL, now, stamp=STAMP, deployed=STAMP)


@dataclass
class Host:
    """A SYNTHETIC host: a folder, with failures on demand."""

    root: Path
    fail_write: bool = False
    writes: list[dict[str, bytes]] = field(default_factory=list)

    def read(self, key: str) -> bytes | None:
        return DirPublisher(self.root).read(key)

    def write(self, files: Mapping[str, bytes]) -> None:
        if self.fail_write:
            raise PublishError("put: HTTP 503")
        self.writes.append(dict(files))
        DirPublisher(self.root).write(files)

    def file(self, path: str, prefix: str = SHADOW) -> bytes | None:
        found = self.root / prefix / path
        return found.read_bytes() if found.is_file() else None


@dataclass
class Rig:
    world: World
    host: Host
    state: Path
    internal: Path

    def publisher(self, mode: Mode = Mode.SHADOW, *, reader: bool = True) -> LivePublisher:
        return LivePublisher(
            host=self.host,
            directory=self.world.dir,
            state_dir=self.state,
            internal_dir=self.internal,
            mode=mode,
            reader=reader,
        )

    def season(self, prefix: str = SHADOW) -> SeasonFile | None:
        data = self.host.file(SEASON, prefix)
        return None if data is None else SeasonFile.from_json_bytes(data)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(World(), Host(tmp_path / "host"), tmp_path / "state", tmp_path / "internal")


STORM = [
    row(ALPHA_SCHOOL, "Closed due to snow"),
    row("SYNTHETIC Pacific School", "2 hour delay due to snow"),
    row("SYNTHETIC Eastern School", "Schools are open"),
]
DAY = date(2026, 11, 17)
MORNING = at("2026-11-17 11:05")
OVER = at("2026-11-18 20:00")
"""The next afternoon: the storm day is over everywhere."""


def storm(world: World, rows: Sequence[object] = STORM, when: datetime = MORNING) -> Merged:
    world.read(when - timedelta(days=1), [])
    world.read(when - timedelta(minutes=5), [])
    world.read(when, rows)  # type: ignore[arg-type]
    return world.publish(when)


def over(rig: Rig, publisher: LivePublisher, when: datetime = OVER) -> tuple[str, ...]:
    rig.world.read(when, [])
    report = publisher.publish(
        rig.world.publish(when), now=when, healthy_share=1.0, edition=equal(when)
    )
    return report.uploaded


def test_the_season_file_goes_up_once_its_first_day_is_over_and_again_only_on_change(
    rig: Rig,
) -> None:
    publisher = rig.publisher()
    first = publisher.publish(
        storm(rig.world), now=MORNING, healthy_share=1.0, edition=equal(MORNING)
    )
    assert f"{SHADOW}/{SEASON}" not in first.uploaded  # nothing is over yet: no file
    assert rig.season() is None
    assert f"{SHADOW}/{SEASON}" in over(rig, publisher)
    season = rig.season()
    assert season is not None
    assert (season.season, season.since, season.through) == ("2026-2027", DAY, DAY)
    assert (season.directory, season.content_sha256) == (STAMP, DayTimeline.from_json_bytes(
        rig.host.file(f"live/days/{DAY.isoformat()}.json") or b""
    ).content_sha256)  # fmt: skip
    assert season.rows() == {0: (1, 0, 0, 0), 7: (0, 1, 0, 0)}
    assert f"{SHADOW}/{SEASON}" not in over(rig, publisher, OVER + timedelta(minutes=10))
    # the next day over moves the last day counted on, with the same counts
    assert f"{SHADOW}/{SEASON}" in over(rig, publisher, OVER + timedelta(days=1))
    later = rig.season()
    assert later is not None
    assert (later.since, later.through, later.rows()) == (
        DAY,
        DAY + timedelta(days=1),
        season.rows(),
    )
    kept = SeasonLedger.load(rig.state / LEDGER)
    assert kept.since == DAY
    assert kept.days == {DAY: {ALPHA[0]: CLOSED, PACIFIC: DELAYED}}


def test_rebuilding_from_the_same_days_gives_the_same_bytes(rig: Rig) -> None:
    publisher = rig.publisher()
    publisher.publish(storm(rig.world), now=MORNING, healthy_share=1.0, edition=equal(MORNING))
    over(rig, publisher)
    data = rig.host.file(SEASON)
    # a process that lost the ledger and the memory rebuilds the same file from the change log
    (rig.state / LEDGER).unlink()
    (rig.state / "publish.v1-shadow.json").unlink()
    again = rig.publisher()
    uploaded = over(rig, again, OVER + timedelta(minutes=10))
    assert f"{SHADOW}/{SEASON}" in uploaded
    assert rig.host.file(SEASON) == data


def test_a_status_taken_back_during_the_day_is_not_counted(rig: Rig) -> None:
    publisher = rig.publisher()
    publisher.publish(storm(rig.world), now=MORNING, healthy_share=1.0, edition=equal(MORNING))
    later = at("2026-11-17 13:20")
    rescinded = [row(ALPHA_SCHOOL, "2 hour delay due to snow"), row(
        "SYNTHETIC Pacific School", "Delay rescinded"), STORM[2]]  # fmt: skip
    publisher.publish(
        storm(rig.world, rescinded, later), now=later, healthy_share=1.0, edition=equal(later)
    )
    over(rig, publisher)
    season = rig.season()
    assert season is not None
    assert season.rows() == {0: (0, 1, 0, 0)}  # Alpha's last status; Pacific's was taken back


def test_a_manual_status_counts_like_any_other(rig: Rig) -> None:
    publisher = rig.publisher()
    admin = AdminStatus(
        school=1,
        nces_id=ALPHA[1],
        day=DAY,
        status=Status.REMOTE,
        shift_minutes=None,
        clock_minute=None,
        set_at=MORNING - timedelta(minutes=1),
        level="school",
        key="synthetic",
    )
    merged = with_overrides(storm(rig.world), [admin], MORNING)
    assert any(closing.manual for closing in merged.closings)
    publisher.publish(merged, now=MORNING, healthy_share=1.0, edition=equal(MORNING))
    over(rig, publisher)
    season = rig.season()
    assert season is not None
    assert season.rows() == {0: (1, 0, 0, 0), 1: (0, 0, 1, 0), 7: (0, 1, 0, 0)}


def test_a_failed_upload_keeps_no_ledger_and_the_next_one_publishes(rig: Rig) -> None:
    publisher = rig.publisher()
    publisher.publish(storm(rig.world), now=MORNING, healthy_share=1.0, edition=equal(MORNING))
    rig.host.fail_write = True
    over(rig, publisher)
    assert not (rig.state / LEDGER).exists()
    assert rig.season() is None
    rig.host.fail_write = False
    assert f"{SHADOW}/{SEASON}" in over(rig, publisher, OVER + timedelta(minutes=5))
    season = rig.season()
    assert season is not None
    assert season.rows() == {0: (1, 0, 0, 0), 7: (0, 1, 0, 0)}


def test_the_overrides_job_never_publishes_the_season_nor_keeps_a_ledger(rig: Rig) -> None:
    publisher = rig.publisher(Mode.ON, reader=False)
    publisher.publish(storm(rig.world), now=MORNING, healthy_share=1.0, edition=equal(MORNING))
    uploaded = over(rig, publisher)
    assert "v1/live/days/2026-11-17.json" in uploaded
    assert "v1/live/season.json" not in uploaded
    assert not (rig.state / LEDGER).exists()


def test_a_blank_empties_the_season_file_and_the_next_upload_puts_it_back(rig: Rig) -> None:
    publisher = rig.publisher()
    publisher.publish(storm(rig.world), now=MORNING, healthy_share=1.0, edition=equal(MORNING))
    over(rig, publisher)
    full = rig.host.file(SEASON)
    report = publisher.blank(now=OVER + timedelta(minutes=5), stamp=None)
    assert f"{SHADOW}/{SEASON}" in report.uploaded
    blank = rig.season()
    assert blank is not None
    assert (blank.gaps, blank.content_sha256, blank.directory) == ((), None, STAMP)
    assert Memory.load(rig.state / "publish.v1-shadow.json").season == {}
    assert f"{SHADOW}/{SEASON}" in over(rig, publisher, OVER + timedelta(minutes=10))
    assert rig.host.file(SEASON) == full


def test_every_blank_carries_an_empty_season_file() -> None:
    files = blank_files(STAMP, OVER, [DAY])
    season = SeasonFile.from_json_bytes(files[SEASON])
    assert (season.season, season.since, season.through) == ("2026-2027", DAY, DAY)
    assert (season.gaps, season.content_sha256) == ((), None)


def test_a_day_published_final_before_the_ledger_is_counted_without_going_up_again(
    rig: Rig,
) -> None:
    """The first pass after the season counts land: the day files are final already, and the
    ledger and the season file are new."""
    publisher = rig.publisher()
    publisher.publish(storm(rig.world), now=MORNING, healthy_share=1.0, edition=equal(MORNING))
    over(rig, publisher)
    day_file_path = f"{SHADOW}/live/days/{DAY.isoformat()}.json"
    published = rig.host.file(f"live/days/{DAY.isoformat()}.json")
    (rig.state / LEDGER).unlink()
    memory_path = rig.state / "publish.v1-shadow.json"
    memory = Memory.load(memory_path)
    memory.season = {}
    memory.save(memory_path)
    uploaded = over(rig, rig.publisher(), OVER + timedelta(minutes=10))
    assert day_file_path not in uploaded
    assert rig.host.file(f"live/days/{DAY.isoformat()}.json") == published
    assert f"{SHADOW}/{SEASON}" in uploaded
    season = rig.season()
    assert season is not None
    assert (season.since, season.rows()) == (DAY, {0: (1, 0, 0, 0), 7: (0, 1, 0, 0)})
    assert SeasonLedger.load(rig.state / LEDGER).days == {DAY: {ALPHA[0]: CLOSED, PACIFIC: DELAYED}}

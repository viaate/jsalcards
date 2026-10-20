"""The publisher and its gate (spec 7.7): T10a-f, T10e, T13d, T16, heartbeats, the change log
and the day timelines. Every name, status and school here is SYNTHETIC."""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from live.world import (
    ALPHA,
    ALPHA_SCHOOL,
    EASTERN,
    PACIFIC,
    World,
    at,
    row,
)
from snowlight.live import guards
from snowlight.live.edition import EditionState, EditionVerdict
from snowlight.live.history import ChangeLog, Event
from snowlight.live.merge import Merged, OpenSignal
from snowlight.live.publish import (
    CLOSINGS,
    DAYS,
    OPENS,
    Exit,
    LivePublisher,
    Memory,
    Mode,
    day_path,
    opens_file,
)
from snowlight.live.publishers import DirPublisher, PublishError
from snowlight.live.versions import PACKAGE, PUBLISHING_FILES, live_files
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import Closing, ClosingsFile, DayIndex, DayTimeline, OpensFile
from snowlight.schemas.vocab import Status

STAMP = DirectoryStamp(generated_on=date(2026, 10, 14), schools=11, districts=6)
SHADOW = "v1-shadow"


def equal(now: datetime, stamp: DirectoryStamp = STAMP) -> EditionVerdict:
    return EditionVerdict(EditionState.EQUAL, now, stamp=stamp, deployed=stamp)


@dataclass
class Host:
    """A SYNTHETIC host: a folder, a clock of its own and failures on demand."""

    root: Path
    server_time: datetime | None = None
    fail_write: bool = False
    fail_read: bool = False
    writes: list[dict[str, bytes]] = field(default_factory=list)

    def read(self, key: str) -> bytes | None:
        if self.fail_read:
            raise PublishError("read v1-shadow/live/closings.json: HTTP 503")
        return DirPublisher(self.root).read(key)

    def write(self, files: Mapping[str, bytes]) -> None:
        if self.fail_write:
            raise PublishError("put: HTTP 503")
        self.writes.append(dict(files))
        DirPublisher(self.root).write(files)

    def file(self, path: str) -> bytes:
        return (self.root / SHADOW / path).read_bytes()


@dataclass
class Rig:
    world: World
    host: Host
    publisher: LivePublisher
    state: Path
    internal: Path

    def again(self, mode: Mode = Mode.SHADOW) -> LivePublisher:
        """A new publisher process on the same state."""
        return LivePublisher(
            host=self.host,
            directory=self.world.dir,
            state_dir=self.state,
            internal_dir=self.internal,
            mode=mode,
        )


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    world = World()
    host = Host(tmp_path / "host")
    state, internal = tmp_path / "state", tmp_path / "internal"
    publisher = LivePublisher(
        host=host, directory=world.dir, state_dir=state, internal_dir=internal
    )
    return Rig(world, host, publisher, state, internal)


STORM = [
    row(ALPHA_SCHOOL, "Closed due to snow"),
    row("SYNTHETIC Pacific School", "2 hour delay due to snow"),
    row("SYNTHETIC Eastern School", "Schools are open"),
]


MORNING = at("2026-11-17 11:05")


def storm(world: World, when: datetime = MORNING) -> Merged:
    """A SYNTHETIC storm morning: Alpha closed, Pacific delayed, Eastern says open."""
    world.read(when - timedelta(days=1), [])  # a read on the previous school day
    world.read(when - timedelta(minutes=5), [])
    world.read(when, STORM)
    return world.publish(when)


def test_a_good_pass_publishes_every_file(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    report = rig.publisher.publish(storm(rig.world), now=now, healthy_share=1.0, edition=equal(now))
    assert report.exit is Exit.OK
    assert set(report.uploaded) == {
        f"{SHADOW}/{CLOSINGS}",
        f"{SHADOW}/{OPENS}",
        f"{SHADOW}/{DAYS}",
        f"{SHADOW}/{day_path(date(2026, 11, 17))}",
    }
    closings = ClosingsFile.from_json_bytes(rig.host.file(CLOSINGS))
    assert closings.generated_at == now
    assert closings.directory == STAMP
    shown = {(row.school, row.day.isoformat(), row.status) for row in closings.closings()}
    assert shown == {(0, "2026-11-17", Status.CLOSED), (7, "2026-11-17", Status.DELAYED)}
    opens = OpensFile.from_json_bytes(rig.host.file(OPENS))
    assert [(item.school, item.day.isoformat()) for item in opens.opens] == [(10, "2026-11-17")]
    assert opens.generated_at == closings.generated_at
    assert opens.directory == closings.directory


def test_unchanged_inputs_give_the_same_bytes_apart_from_generated_at(
    rig: Rig, tmp_path: Path
) -> None:
    now = at("2026-11-17 11:05")
    merged = storm(rig.world)
    rig.publisher.publish(merged, now=now, healthy_share=1.0, edition=equal(now))
    first = rig.host.file(CLOSINGS)
    # The same statuses in another order, from another process, at the same moment:
    # byte for byte the same.
    other = Host(tmp_path / "other")
    again = LivePublisher(
        host=other,
        directory=rig.world.dir,
        state_dir=tmp_path / "other-state",
        internal_dir=tmp_path / "other-internal",
    )
    flipped = replace(merged, closings=merged.closings[::-1], provenance=merged.provenance[::-1])
    again.publish(flipped, now=now, healthy_share=1.0, edition=equal(now))
    assert other.file(CLOSINGS) == first
    # Five minutes later (a heartbeat): only generated_at (and the minutes counted back
    # from it) differ; the statuses read back the same.
    later = now + timedelta(minutes=5)
    report = rig.publisher.publish(merged, now=later, healthy_share=1.0, edition=equal(later))
    assert report.exit is Exit.OK
    assert report.uploaded
    old, new = (
        ClosingsFile.from_json_bytes(first),
        ClosingsFile.from_json_bytes(rig.host.file(CLOSINGS)),
    )
    assert new.generated_at == later
    assert new.closings() == old.closings()


def test_unchanged_statuses_within_the_heartbeat_upload_nothing(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    merged = storm(rig.world)
    rig.publisher.publish(merged, now=now, healthy_share=1.0, edition=equal(now))
    soon = now + timedelta(minutes=1)
    report = rig.publisher.publish(merged, now=soon, healthy_share=1.0, edition=equal(soon))
    assert (report.exit, report.uploaded, report.note) == (Exit.OK, (), "unchanged")
    assert len(rig.host.writes) == 1


@pytest.mark.parametrize(
    ("state", "refusal"),
    [
        (EditionState.DIFFERENT, "edition"),
        (EditionState.NONE_DEPLOYED, "edition"),
        (EditionState.UNREADABLE, "edition"),
    ],
)
def test_t10a_an_edition_that_does_not_match_refuses(
    rig: Rig, state: EditionState, refusal: str
) -> None:
    now = at("2026-11-17 11:05")
    verdict = EditionVerdict(state, now, deployed=STAMP)
    report = rig.publisher.publish(storm(rig.world), now=now, healthy_share=1.0, edition=verdict)
    assert (report.exit, report.refusals, report.uploaded) == (Exit.REFUSED, (refusal,), ())
    assert rig.host.writes == []


def test_t10b_too_few_healthy_sources_refuses_and_two_in_a_row_alert(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    merged = storm(rig.world)
    first = rig.publisher.publish(merged, now=now, healthy_share=0.59, edition=equal(now))
    assert (first.exit, first.refusals, first.alert) == (Exit.REFUSED, ("health",), False)
    later = now + timedelta(minutes=5)
    second = rig.publisher.publish(merged, now=later, healthy_share=0.5, edition=equal(later))
    assert (second.refusals, second.alert) == (("health",), True)
    assert rig.host.writes == []
    # a recovered pass publishes and resets the count
    last = later + timedelta(minutes=5)
    assert rig.publisher.publish(merged, now=last, healthy_share=0.9, edition=equal(last)).exit is (
        Exit.OK
    )
    assert rig.publisher.memory.refused_streak == 0


def test_t10b_a_share_below_half_the_previous_refuses(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    merged = storm(rig.world)
    rig.publisher.publish(merged, now=now, healthy_share=1.0, edition=equal(now))
    later = now + timedelta(minutes=5)
    rig.publisher.memory.previous_healthy_share = 1.4  # an earlier pass counted more
    report = rig.publisher.publish(merged, now=later, healthy_share=0.65, edition=equal(later))
    assert report.refusals == ("health",)


def test_t10c_a_stamp_not_newer_than_the_last_refuses_across_processes(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    merged = storm(rig.world)
    rig.publisher.publish(merged, now=now, healthy_share=1.0, edition=equal(now))
    # the remote file is gone (a host reset): the remembered stamp still holds
    (rig.host.root / SHADOW / CLOSINGS).unlink()
    restarted = rig.again()
    report = restarted.publish(merged, now=now, healthy_share=1.0, edition=equal(now))
    assert report.refusals == ("not_newer",)
    earlier = now - timedelta(minutes=1)
    refused = restarted.publish(merged, now=earlier, healthy_share=1.0, edition=equal(earlier))
    assert "not_newer" in refused.refusals


def test_t10d_an_oversized_file_refuses(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guards, "MAX_GZIP_BYTES", 10)
    now = at("2026-11-17 11:05")
    report = rig.publisher.publish(storm(rig.world), now=now, healthy_share=1.0, edition=equal(now))
    assert report.refusals == ("oversize",)


def test_t10d_a_file_that_does_not_validate_refuses(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    small = DirectoryStamp(generated_on=date(2026, 10, 14), schools=5, districts=6)
    report = rig.publisher.publish(
        storm(rig.world), now=now, healthy_share=1.0, edition=equal(now, small)
    )
    assert (report.exit, report.refusals) == (Exit.REFUSED, ("invalid",))
    assert rig.host.writes == []


def test_t10_read_back_of_a_newer_remote_file_refuses(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    other = LivePublisher(
        host=rig.host,
        directory=rig.world.dir,
        state_dir=rig.state.parent / "second-writer",
        internal_dir=rig.internal,
    )
    newer = now + timedelta(minutes=2)
    assert other.blank(now=newer, stamp=STAMP).uploaded == ()
    rig.host.write(
        {
            f"{SHADOW}/{CLOSINGS}": ClosingsFile.encode(
                (), generated_at=newer, directory=STAMP
            ).to_json_bytes()
        }
    )
    report = rig.publisher.publish(storm(rig.world), now=now, healthy_share=1.0, edition=equal(now))
    assert report.refusals == ("not_newer",)
    assert ClosingsFile.from_json_bytes(rig.host.file(CLOSINGS)).generated_at == newer


def test_t10f_a_box_clock_ahead_of_the_host_refuses(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    rig.host.server_time = now - timedelta(seconds=61)
    report = rig.publisher.publish(storm(rig.world), now=now, healthy_share=1.0, edition=equal(now))
    assert report.refusals == ("clock_ahead",)
    rig.host.server_time = now - timedelta(seconds=60)
    assert (
        rig.publisher.publish(storm(rig.world), now=now, healthy_share=1.0, edition=equal(now)).exit
        is Exit.OK
    )


def _many(count: int, day: date, *, first: int = 0) -> Merged:
    closings = tuple(
        Closing(school=first + n, day=day, status=Status.CLOSED, announced_at=None, reason=None)
        for n in range(count)
    )
    lines = tuple(
        {"nces_id": f"9{first + n:011d}", "school": first + n, "day": day.isoformat()}
        for n in range(count)
    )
    return Merged(
        closings=closings,
        opens=(),
        provenance=lines,  # type: ignore[arg-type]
        withheld={},
        breakers=(),
        fast_vanishes=(),
    )


def test_t10e_a_spike_holds_once_then_publishes_on_confirmation(rig: Rig) -> None:
    big = DirectoryStamp(generated_on=date(2026, 10, 14), schools=5000, districts=6)
    now = at("2026-11-17 11:05")
    day = date(2026, 11, 17)
    merged = _many(2001, day)
    held = rig.publisher.publish(merged, now=now, healthy_share=1.0, edition=equal(now, big))
    assert (held.exit, held.refusals) == (Exit.REFUSED, ("spike_hold",))
    later = now + timedelta(minutes=5)
    shown = rig.publisher.publish(merged, now=later, healthy_share=1.0, edition=equal(later, big))
    assert shown.exit is Exit.OK


def test_t10e_a_spike_that_changes_holds_again(rig: Rig) -> None:
    big = DirectoryStamp(generated_on=date(2026, 10, 14), schools=5000, districts=6)
    now = at("2026-11-17 11:05")
    day = date(2026, 11, 17)
    rig.publisher.publish(_many(2001, day), now=now, healthy_share=1.0, edition=equal(now, big))
    later = now + timedelta(minutes=5)
    other = _many(2001, day, first=2500)
    again = rig.publisher.publish(other, now=later, healthy_share=1.0, edition=equal(later, big))
    assert again.refusals == ("spike_hold",)


def test_t10e_a_spike_under_alerts_publishes_at_once(rig: Rig) -> None:
    big = DirectoryStamp(generated_on=date(2026, 10, 14), schools=5000, districts=6)
    now = at("2026-11-17 11:05")
    report = rig.publisher.publish(
        _many(2001, date(2026, 11, 17)),
        now=now,
        healthy_share=1.0,
        edition=equal(now, big),
        alerted=lambda school: school % 2 == 0,
    )
    assert report.exit is Exit.OK


def test_t13d_content_changed_under_the_last_stamp_publishes_one_blank_and_refuses(
    rig: Rig,
) -> None:
    now = at("2026-11-17 11:05")
    merged = storm(rig.world)
    rig.publisher.publish(merged, now=now, healthy_share=1.0, edition=equal(now))
    later = now + timedelta(minutes=1)
    changed = EditionVerdict(EditionState.DIFFERENT, later, blank=STAMP, deployed=STAMP)
    report = rig.publisher.publish(merged, now=later, healthy_share=1.0, edition=changed)
    assert (report.exit, report.refusals, report.blank, report.alert) == (
        Exit.REFUSED,
        ("edition",),
        True,
        True,
    )
    blank = ClosingsFile.from_json_bytes(rig.host.file(CLOSINGS))
    assert (blank.days, blank.generated_at, blank.directory) == ((), later, STAMP)
    assert OpensFile.from_json_bytes(rig.host.file(OPENS)).opens == ()
    # the map went dark: the change log says so
    events = [
        change.event for change in ChangeLog(rig.state / "changes").changes(date(2026, 11, 17))
    ]
    assert events.count(Event.DARK) == 2


def test_t16_blank_is_a_valid_empty_file_with_a_monotonic_stamp(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    rig.publisher.publish(storm(rig.world), now=now, healthy_share=1.0, edition=equal(now))
    report = rig.publisher.blank(now=now, stamp=STAMP)  # health is not checked
    assert report.exit is Exit.OK
    blank = ClosingsFile.from_json_bytes(rig.host.file(CLOSINGS))
    assert blank.closings() == []
    # never refused for a clash within a second: a second after the file it replaces
    assert blank.generated_at == now + timedelta(seconds=1)
    assert rig.publisher.blank(now=now, stamp=STAMP).uploaded == ()  # already blank
    later = now + timedelta(minutes=2)
    rig.publisher.publish(
        storm(rig.world, later), now=later, healthy_share=1.0, edition=equal(later)
    )
    # never ahead of the host's clock
    rig.host.server_time = later - timedelta(seconds=60)
    again = rig.publisher.blank(now=later, stamp=STAMP)
    assert (again.exit, again.refusals) == (Exit.REFUSED, ("clock_ahead",))
    # another stamp's file is not this blank's to replace
    other = DirectoryStamp(generated_on=date(2026, 10, 15), schools=11, districts=6)
    assert rig.publisher.blank(now=now, stamp=other).uploaded == ()


def test_a_host_error_publishes_nothing_and_changes_nothing(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    merged = storm(rig.world)
    rig.host.fail_write = True
    report = rig.publisher.publish(merged, now=now, healthy_share=1.0, edition=equal(now))
    assert report.exit is Exit.ERROR
    assert rig.publisher.memory.last_published is None
    assert ChangeLog(rig.state / "changes").days() == []
    rig.host.fail_write, rig.host.fail_read = False, True
    assert rig.publisher.publish(merged, now=now, healthy_share=1.0, edition=equal(now)).exit is (
        Exit.ERROR
    )
    rig.host.fail_read = False
    assert rig.publisher.publish(merged, now=now, healthy_share=1.0, edition=equal(now)).exit is (
        Exit.OK
    )


def test_publishing_off_writes_nothing_and_on_writes_under_v1(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    merged = storm(rig.world)
    off = rig.again(Mode.OFF)
    assert off.publish(merged, now=now, healthy_share=1.0, edition=equal(now)).note == (
        "publishing is off"
    )
    assert rig.host.writes == []
    on = rig.again(Mode.ON)
    report = on.publish(merged, now=now, healthy_share=1.0, edition=equal(now))
    assert all(key.startswith("v1/live/") for key in report.uploaded)


def test_the_memory_survives_a_restart_and_refuses_a_damaged_file(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    rig.publisher.publish(storm(rig.world), now=now, healthy_share=0.8, edition=equal(now))
    memory = Memory.load(rig.state / "publish.json")
    assert memory.last_published == now
    assert memory.last_stamp == STAMP
    assert memory.previous_healthy_share == 0.8
    assert memory.lit == {(0, "2026-11-17"), (7, "2026-11-17")}
    (rig.state / "publish.json").write_text('{"lit": 3}', encoding="utf-8")
    with pytest.raises(ValueError, match="not the publisher's memory"):
        Memory.load(rig.state / "publish.json")


# --- the change log and the day timelines -------------------------------------------------------


def test_the_change_log_and_timeline_follow_a_day(rig: Rig) -> None:
    world, publisher = rig.world, rig.publisher
    day = date(2026, 11, 17)
    first = at("2026-11-17 11:05")  # 05:05 in Chicago
    publisher.publish(storm(world), now=first, healthy_share=1.0, edition=equal(first))
    # 06:10 Chicago: Alpha upgrades from closed to a delay (a new posting)
    second = at("2026-11-17 12:10")
    world.read(second, [row(ALPHA_SCHOOL, "2 hour delay due to snow"), *STORM[1:]])
    publisher.publish(world.publish(second), now=second, healthy_share=1.0, edition=equal(second))
    # 07:20 Chicago: Pacific's delay is taken back
    third = at("2026-11-17 13:20")
    world.read(
        third,
        [
            row(ALPHA_SCHOOL, "2 hour delay due to snow"),
            row("SYNTHETIC Pacific School", "Delay rescinded"),
            STORM[2],
        ],
    )
    publisher.publish(world.publish(third), now=third, healthy_share=1.0, edition=equal(third))
    log = ChangeLog(rig.state / "changes")
    events = [(change.nces_id, change.event, change.at) for change in log.changes(day)]
    assert events == [
        (PACIFIC, Event.LIT, first),
        (ALPHA[0], Event.LIT, first),
        (ALPHA[0], Event.CHANGED, second),
        (PACIFIC, Event.DARK, third),
    ]
    timeline = DayTimeline.from_json_bytes(rig.host.file(day_path(day)))
    assert (timeline.day, timeline.final, timeline.schools()) == (day, False, (0, 7))
    assert timeline.counts == (2, 2)
    # minutes in each school's own zone: Chicago 05:05 and 06:10, Los Angeles 03:05 and 05:20
    assert timeline.minutes == (305, 370, 185, 320)
    assert timeline.statuses == (Status.CLOSED, Status.DELAYED, Status.DELAYED, None)
    index = DayIndex.from_json_bytes(rig.host.file(DAYS))
    assert [(entry.day, entry.schools, entry.final) for entry in index.days] == [(day, 2, False)]
    # Nothing in the private log or the public files is raw text.
    for path in [*rig.state.rglob("*"), *rig.host.root.rglob("*"), *rig.internal.rglob("*")]:
        if path.is_file():
            text = path.read_text(encoding="utf-8").casefold()
            for words in ("synthetic alpha", "synthetic pacific", "synthetic eastern"):
                assert words not in text, path
            for words in ("closed", "due to snow", "rescinded", "schools are open", "delay"):
                assert words not in text, path


def test_a_day_over_everywhere_is_published_final_once(rig: Rig) -> None:
    world, publisher = rig.world, rig.publisher
    day = date(2026, 11, 17)
    first = at("2026-11-17 11:05")
    publisher.publish(storm(world), now=first, healthy_share=1.0, edition=equal(first))
    # the next afternoon, the day is over everywhere; the statuses left with it
    late = at("2026-11-18 20:00")
    world.read(late, STORM)
    merged = world.publish(late)
    assert merged.closings == ()
    report = publisher.publish(merged, now=late, healthy_share=1.0, edition=equal(late))
    assert f"{SHADOW}/{day_path(day)}" in report.uploaded
    final = DayTimeline.from_json_bytes(rig.host.file(day_path(day)))
    assert final.final
    assert final.statuses == (Status.CLOSED, Status.DELAYED)  # expiry is not a change
    events = [change.event for change in ChangeLog(rig.state / "changes").changes(day)]
    assert events[-2:] == [Event.EXPIRED, Event.EXPIRED]
    later = late + timedelta(minutes=10)
    again = publisher.publish(merged, now=later, healthy_share=1.0, edition=equal(later))
    assert f"{SHADOW}/{day_path(day)}" not in again.uploaded
    index = DayIndex.from_json_bytes(rig.host.file(DAYS))
    assert [(entry.day, entry.schools, entry.final) for entry in index.days] == [(day, 2, True)]
    record = Memory.load(rig.state / "publish.json").days[f"{SHADOW}/{day.isoformat()}"]
    assert (record.schools, record.final) == (2, True)


def test_an_evening_announcement_shows_before_its_day(rig: Rig) -> None:
    world, publisher = rig.world, rig.publisher
    evening = at("2026-11-17 02:00")  # Monday 20:00 in Chicago
    world.read(evening - timedelta(days=1), [])
    world.read(evening - timedelta(minutes=5), [])
    world.read(evening, [row(ALPHA_SCHOOL, "Closed tomorrow due to snow")])
    merged = world.publish(evening)
    publisher.publish(merged, now=evening, healthy_share=1.0, edition=equal(evening))
    timeline = DayTimeline.from_json_bytes(rig.host.file(day_path(date(2026, 11, 17))))
    assert timeline.minutes == (-240,)


def test_logs_name_no_school_and_no_words(
    rig: Rig, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    now = at("2026-11-17 11:05")
    merged = storm(rig.world)
    rig.publisher.publish(merged, now=now, healthy_share=0.1, edition=equal(now))
    rig.publisher.publish(merged, now=now, healthy_share=1.0, edition=equal(now))
    rig.host.fail_write = True
    later = now + timedelta(minutes=5)
    rig.publisher.publish(merged, now=later, healthy_share=1.0, edition=equal(later))
    captured = capsys.readouterr()
    messages = [record.getMessage() for record in caplog.records]
    # the logger names ("snowlight.live...") are ours, not a status's words
    text = "\n".join([*messages, captured.out, captured.err]).casefold().replace("snowlight", "")
    assert caplog.records
    for word in ("synthetic", "alpha", "pacific", "snow", "open", "delay"):
        assert word not in text


def test_provenance_of_the_last_publish_is_kept_privately(rig: Rig) -> None:
    now = at("2026-11-17 11:05")
    rig.publisher.publish(storm(rig.world), now=now, healthy_share=1.0, edition=equal(now))
    lines = [
        json.loads(line)
        for line in (rig.internal / "provenance.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert sorted(line["nces_id"] for line in lines) == sorted([ALPHA[0], PACIFIC])
    assert {line["source_id"] for line in lines} == {"gray-synthetic"}
    assert EASTERN not in {line["nces_id"] for line in lines}
    assert datetime.fromisoformat(lines[0]["generated_at"]) == now.astimezone(UTC)


def test_publishing_modules_leave_stored_derivations_valid() -> None:
    names = {path.name for path in live_files() if path.parent == PACKAGE / "live"}
    assert {"ledger.py", "resolve.py", "merge.py", "guards.py", "provenance.py"} <= names
    assert not names & PUBLISHING_FILES
    assert all(
        (PACKAGE / "live" / name).is_file()
        for name in PUBLISHING_FILES - {"cli.py", "health.py", "ingest.py", "state.py"}
    )


def test_open_confidence_is_published_in_hundredths() -> None:
    signal = OpenSignal(
        school=1,
        nces_id=ALPHA[1],
        day=date(2026, 11, 17),
        at=at("2026-11-17 11:00"),
        source_id="gray-synthetic",
        source_type="broadcaster_list",
        confidence=0.57,
    )
    file = opens_file([signal], [], generated_at=at("2026-11-17 11:05"), stamp=STAMP)
    assert [item.confidence for item in file.opens] == [0.57]

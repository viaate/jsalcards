"""live-403: a GitHub rate limit refuses passes (exit 3) and never fails them, nothing is sent
until the time GitHub gave, and the first pass allowed after it uploads every change kept.

``live run`` drives the test_cli rig (its SYNTHETIC world, fake clock and stub edition), with
a :class:`~snowlight.live.publishers.GitHubPublisher` on the SYNTHETIC GitHub repository of
``github_fake`` (on the rig's clock) as the live host. Every row and message is SYNTHETIC.
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from live.github_fake import PRIMARY_MESSAGE, TOKEN, USER_ID, GitHubFake, Kind, Request
from live.test_cli import OWN, STORM, Clock, Rig, _loaders, _run, make_rig
from live.test_edition import Source
from live.test_ingest import CLOSED, EDITION, A, _warm, _world
from live.test_publish import _many, equal, storm
from live.world import World, at, row
from snowlight.live import cli as live_cli
from snowlight.live.alerts import annotate
from snowlight.live.edition import EditionWatch
from snowlight.live.history import ChangeLog
from snowlight.live.ingest import Ingest, SourceRead
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.merge import AdminStatus
from snowlight.live.overrides import read_shown
from snowlight.live.publish import AdminPart, Exit, LivePublisher, Memory, Mode
from snowlight.live.publishers import HostRefusedError
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import ClosingsFile, DayTimeline
from snowlight.schemas.vocab import Status

CLOSINGS = "v1/live/closings.json"
NEW_ROW = row("SYNTHETIC Split School", "Closed Tuesday due to snow")
"""A SYNTHETIC closing that appears in the reads from :data:`NEW_FROM` (Nov 17 2026 is a
Tuesday: the row is dated whatever the hour)."""
NEW_FROM = at("2026-11-17 17:10")
LAG = timedelta(seconds=20)


@dataclass
class Live:
    """One ``live run`` setup: the rig, its clock, the fake GitHub and the folders."""

    rig: Rig
    clock: Clock
    fake: GitHubFake
    tmp: Path
    hosts: list[object]

    def argv(self, until: str) -> list[str]:
        return [
            "live",
            "run",
            "--until",
            until,
            "--config",
            str(self.config()),
            "--state",
            str(self.tmp / "state"),
            "--internal",
            str(self.tmp / "internal"),
        ]

    def config(self) -> Path:
        path = self.tmp / "live.yaml"
        path.write_text(
            "host:\n  kind: github\n  repository: viaate/snowlight-synthetic\n"
            f"state:\n  kind: local\n  folder: {self.tmp / 'store'}\n"
            "site: https://synthetic.example\nsite_repository: viaate/synthetic\n",
            encoding="utf-8",
        )
        return path

    def loaders(self) -> live_cli.Loaders:
        base = _loaders(self.rig, self.clock)
        clock = self.clock

        def parts(
            config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
        ) -> live_cli.Parts:
            made = base.parts(config, env, args)

            def reads(
                started: datetime, _only: Sequence[str], tick: Callable[[], None]
            ) -> Sequence[SourceRead]:
                tick()
                clock.sleep(LAG.total_seconds())
                rows = (*STORM, NEW_ROW) if started >= NEW_FROM else STORM
                return [SourceRead("gray-synthetic", ReadOutcome.OK, clock.now, rows)]

            return live_cli.Parts(made.ingest, reads)

        def env() -> dict[str, str]:
            return {"LIVE_PUBLISH": "on", "LIVE_HOST_TOKEN": TOKEN}

        return replace(base, parts=parts, env=env)

    def run(self, until: str, monkeypatch: pytest.MonkeyPatch) -> int:
        def host(*_args: object, **_kwargs: object) -> object:
            made = self.fake.publisher(now=self.clock)
            self.hosts.append(made)
            return made

        monkeypatch.setattr(live_cli, "make_host", host)
        return _run(self.argv(until), self.loaders(), monkeypatch)

    def memory(self) -> Memory:
        return Memory.load(self.tmp / "state" / "publish.json")


def _live(tmp_path: Path, start: datetime) -> Live:
    tmp_path.mkdir(parents=True, exist_ok=True)
    clock = Clock(start)
    rig = make_rig()
    return Live(rig, clock, GitHubFake(clock), tmp_path, [])


def _closings(files: dict[str, bytes]) -> ClosingsFile:
    return ClosingsFile.from_json_bytes(files[CLOSINGS])


@pytest.fixture
def quiet_logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG, logger="snowlight")
    return caplog


START = at("2026-11-17 16:54") + timedelta(seconds=30)
WINDOW = (
    at("2026-11-17 17:00") + timedelta(seconds=15),
    at("2026-11-17 17:26") + timedelta(seconds=15),
)
ALLOWED = WINDOW[1] + timedelta(seconds=1)


def test_a_26_minute_rate_limit_window_publishes_on_the_first_allowed_pass_with_no_restart_and_no_lost_state(  # noqa: E501 - one replay
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_logs: pytest.LogCaptureFixture,
) -> None:
    control = _live(tmp_path / "control", START)
    assert control.run("+60m", monkeypatch) == 0
    capsys.readouterr()
    quiet_logs.clear()

    live = _live(tmp_path / "refused", START)
    live.fake.refuse(*WINDOW)
    assert live.run("+60m", monkeypatch) == 3
    out = capsys.readouterr().out
    logs = quiet_logs.text

    # one request in the window, refused; nothing else is sent until the reset
    inside = live.fake.sent(WINDOW[0], ALLOWED)
    assert [(str(one), one.status) for one in inside] == [("GET contents/v1/live/hold.json", 403)]
    # one clean warning: GitHub's reason, never its words, the user id or the token
    warnings = [
        rec.getMessage()
        for rec in quiet_logs.records
        if rec.levelno == logging.WARNING and "primary_rate_limit" in rec.getMessage()
    ]
    assert len(warnings) == 1
    assert "0 of 5000 left" in warnings[0]
    assert "resets 17:26:15Z" in warnings[0]
    assert "request SYNT:" in warnings[0]
    for text in (out, logs):
        assert TOKEN not in text
        assert USER_ID not in text
        assert "exceeded" not in text
        assert PRIMARY_MESSAGE[:20] not in text
    # each pass in the window is refused for the host (exit 3), the gate alert from the second
    lines = out.splitlines()
    refused = [line for line in lines if line.startswith("exit 3: refusals host")]
    assert len(refused) == 6  # 17:00 to 17:25
    assert all("host refused until 17:26:16Z (primary_rate_limit)" in line for line in refused)
    assert "ALERT" not in refused[0]
    assert all("ALERT" in line for line in refused[1:])
    assert "failed passes in a row" not in out
    assert "live-read end passes" not in out
    assert lines[-1] == "::notice::live-read end until"
    assert out.count("::notice::live-read host refused primary_rate_limit until") == 1
    assert "live-read host answers 2026-11-17T17:26:36+00:00" in out
    # the first allowed pass starts at the reset + 1 s (before 17:30) and uploads
    uploads = [(when, files) for when, files in live.fake.uploads if CLOSINGS in files]
    first = next((when, files) for when, files in uploads if when >= WINDOW[0])
    assert first[0] == ALLOWED + LAG
    published = _closings(first[1])
    assert len(published.closings()) == 3  # the storm's 2 and the 17:10 closing
    # nothing lost: the change log, what is lit and the day timeline have the closing
    memory = live.memory()
    assert memory.refused_streak == 0
    assert len(memory.lit) == 3
    timeline = DayTimeline.from_json_bytes(first[1]["v1/live/days/2026-11-17.json"])
    assert {closing.school for closing in published.closings()} <= set(timeline.schools())
    # nothing published changes: the uploads before the window are byte-identical, and the
    # first allowed upload shows the control's 17:30 rows
    before = [files for when, files in live.fake.uploads if when < WINDOW[0]]
    control_before = [files for when, files in control.fake.uploads if when < WINDOW[0]]
    assert before == control_before
    control_1730 = next(
        files for when, files in control.fake.uploads if when == at("2026-11-17 17:30") + LAG
    )
    # (decoded: the file keeps announce times as minutes before its generated_at)
    assert published.closings() == _closings(control_1730).closings()
    # the change log holds the 17:10 closing from the pass that first showed it
    logged = ChangeLog(live.tmp / "state" / "changes").changes(date(2026, 11, 17))
    control_logged = ChangeLog(control.tmp / "state" / "changes").changes(date(2026, 11, 17))
    assert {change.nces_id for change in logged} == {change.nces_id for change in control_logged}
    assert len({change.nces_id for change in logged}) == 3


def test_a_refusal_mid_commit_writes_nothing_and_the_next_allowed_pass_uploads_every_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = _live(tmp_path, at("2026-11-17 17:04"))
    assert live.run("+5m", monkeypatch) == 0  # 17:04 and 17:05 publish the storm
    before = len(live.fake.uploads)
    live.fake.refuse_from("POST git/trees", timedelta(minutes=10))
    live.clock.now = NEW_FROM  # the successor starts as the 17:10 closing appears
    assert live.run("+20m", monkeypatch) == 3
    out = capsys.readouterr().out
    refused = [one for one in live.fake.log if one.status == httpx.codes.FORBIDDEN]
    assert [str(one) for one in refused] == ["POST git/trees"]
    start = refused[0].at
    # nothing was written: no commit until the first pass after the refusal
    assert all(when > start + timedelta(minutes=10) for when, _ in live.fake.uploads[before:])
    assert not live.fake.sent(start + timedelta(seconds=1), start + timedelta(minutes=10))
    assert "exit 3: refusals host" in out
    when, files = live.fake.uploads[before]
    assert when == start + timedelta(minutes=10, seconds=1) + LAG
    assert len(_closings(files).closings()) == 3
    memory = live.memory()
    assert len(memory.lit) == 3
    assert memory.refused_streak == 0
    logged = ChangeLog(live.tmp / "state" / "changes").changes(date(2026, 11, 17))
    assert len({change.nces_id for change in logged}) == 3
    assert "v1/live/days/2026-11-17.json" in files


def _server_ahead(fake: GitHubFake, clock: Clock, ahead: timedelta) -> None:
    """The fake answers on its own clock, ``ahead`` of the reader's (a skewed server)."""
    fake.clock = lambda: clock.now + ahead


def test_a_secondary_limit_waits_retry_after_from_the_servers_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = _live(tmp_path, START)
    _server_ahead(live.fake, live.clock, timedelta(seconds=30))
    server_start = WINDOW[0] + timedelta(seconds=30)
    live.fake.refuse(server_start, server_start + timedelta(minutes=3), "secondary")
    assert live.run("+15m", monkeypatch) == 3
    out = capsys.readouterr().out
    refused = [one for one in live.fake.log if one.status == httpx.codes.FORBIDDEN]
    assert len(refused) >= 2
    # each next request goes out 60 s after the refusal, by the reader's clock (the server's
    # Date is 30 s ahead: retry-after counts from it, moved onto the local clock)
    after = [live.fake.log[live.fake.log.index(one) + 1] for one in refused]
    assert [(nxt.at - one.at).total_seconds() for one, nxt in zip(refused, after, strict=True)] == [
        60.0 + LAG.total_seconds()
    ] * len(refused)
    assert "secondary_rate_limit" in out
    assert "failed passes" not in out


def test_a_secondary_limit_without_headers_backs_off_60_120_240_and_caps_at_15_minutes() -> None:
    clock = Clock(START)
    fake = GitHubFake(clock)
    fake.refuse(START, START + timedelta(hours=2), "secondary-bare")
    host = fake.publisher()
    waits = []
    for _ in range(7):
        with pytest.raises(HostRefusedError) as raised:
            host.read(CLOSINGS)
        until = raised.value.refusal.until
        assert until is not None
        waits.append((until - clock.now).total_seconds())
        with pytest.raises(HostRefusedError, match="not sent"):
            host.read(CLOSINGS)  # nothing goes out before it
        clock.now = until
    assert waits == [60, 120, 240, 480, 900, 900, 900]
    assert len(fake.log) == 7


@pytest.mark.parametrize("kind", ["plain", "server"])
def test_a_plain_403_or_a_5xx_is_a_failed_pass_and_three_stop_for_the_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_logs: pytest.LogCaptureFixture,
    kind: Kind,
) -> None:
    live = _live(tmp_path, START)
    live.fake.refuse(WINDOW[0], WINDOW[0] + timedelta(hours=1), kind)
    assert live.run("+60m", monkeypatch) == 1
    out = capsys.readouterr().out
    assert f"{live_cli.FAILED_TO_STOP} failed passes in a row; stopping for the successor" in out
    assert out.splitlines()[-1] == "::notice::live-read end passes"
    assert "host refused until" not in out
    # today's rule: each pass asks again (no wait), and each answer's reason is logged
    refused = [one for one in live.fake.log if one.at >= WINDOW[0]]
    assert len(refused) == live_cli.FAILED_TO_STOP
    reason = "no_permission" if kind == "plain" else "server"
    warnings = [
        rec.getMessage()
        for rec in quiet_logs.records
        if rec.levelno == logging.WARNING and rec.getMessage().startswith("live host refused")
    ]
    assert len(warnings) == live_cli.FAILED_TO_STOP
    assert all(reason in line for line in warnings)
    if kind == "plain":
        assert all("needs contents=write" in line for line in warnings)
    assert "SYNTHETIC" not in quiet_logs.text


def test_the_third_failed_pass_in_a_row_stops_the_run_but_a_refused_one_resets_the_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """FAILED_TO_STOP counts exceptions and exit-1 passes in a row only: a rate-limited
    pass between them starts the count again."""
    live = _live(tmp_path, START)
    five = timedelta(minutes=5)
    first = WINDOW[0]
    live.fake.refuse(first, first + timedelta(seconds=10), "server")  # 17:00 fails
    live.fake.refuse(first + five, first + five + timedelta(seconds=10), "server")  # 17:05
    # 17:10 is refused for a rate limit until 17:14:31 (too near 17:15 for a pass of its own)
    live.fake.refuse(first + 2 * five, first + 2 * five + timedelta(minutes=4, seconds=15))
    live.fake.refuse(first + 3 * five, first + 3 * five + timedelta(seconds=10), "server")
    assert live.run("+25m", monkeypatch) == 3  # a failed pass counts as 3 in the run's exit
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.startswith(("exit ", "the pass"))]
    assert [line.split(";")[0] for line in lines[-1:]] == ["exit 3: refusals host"]
    assert "failed passes in a row" not in out
    assert out.splitlines()[-1] == "::notice::live-read end until"
    assert [one.status for one in live.fake.log if one.status in {403, 502}] == [502, 502, 403, 502]


def test_a_refusal_longer_than_the_run_ends_at_until_with_exit_3_and_its_successor_sends_one_request(  # noqa: E501
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = _live(tmp_path, START)
    end = WINDOW[0] + timedelta(hours=1)
    live.fake.refuse(WINDOW[0], end)
    assert live.run("+30m", monkeypatch) == 3
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == "::notice::live-read end until"
    assert "failed passes" not in out
    assert len(live.fake.sent(WINDOW[0], end)) == 1
    # the successor learns of it from its first call (its start-up read), then waits
    successor = at("2026-11-17 17:30")
    live.clock.now = successor
    assert live.run("+30m", monkeypatch) == 3
    out = capsys.readouterr().out
    assert len(live.hosts) == 2
    sent = live.fake.sent(successor, end + timedelta(seconds=1))
    assert [(str(one), one.status) for one in sent] == [("GET contents/v1/live/alerts.json", 403)]
    assert out.splitlines()[-1] == "::notice::live-read end until"
    assert "exit 3: refusals host" in out


def test_an_edition_blank_refused_by_the_host_waits_for_the_reset_not_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = _live(tmp_path, START)
    assert live.run("+5m", monkeypatch) == 0  # 16:54:30 and 16:55 publish under OWN
    shown = ClosingsFile.from_json_bytes(live.fake.tree()[CLOSINGS])
    assert shown.days
    # other content is deployed under the same stamp while the host refuses
    live.rig.edition[:] = [OWN.model_copy(update={"content_sha256": "c" * 64})]
    live.fake.refuse(WINDOW[0], WINDOW[1])
    live.clock.now = WINDOW[0] + timedelta(minutes=1)
    assert live.run("+60m", monkeypatch) == 3
    out = capsys.readouterr().out
    assert "live-read end blank" not in out
    assert "exit 1" not in out
    assert out.splitlines()[-1] == "::notice::live-read end edition"
    assert "the live host refused the blank until 2026-11-17T17:26:16+00:00" in out
    # one request (the start-up read) in the window; the blank goes out at the first check
    # after the reset
    assert len(live.fake.sent(WINDOW[0], ALLOWED)) == 1
    when, files = live.fake.uploads[-1]
    assert ALLOWED <= when <= ALLOWED + timedelta(seconds=60)
    assert _closings(files).days == ()


@pytest.mark.parametrize("kind", ["primary", "plain"])
def test_an_overrides_read_refused_by_the_host_is_a_host_refusal(
    tmp_path: Path, kind: Kind
) -> None:
    now = at("2026-11-17 11:05")
    clock = Clock(now)
    fake = GitHubFake(clock)
    fake.refuse(now, now + timedelta(minutes=30), kind)
    world = _world()
    _warm(world, A, now)
    publisher = LivePublisher(
        host=fake.publisher(),
        directory=world.dir,
        state_dir=tmp_path / "state",
        internal_dir=tmp_path / "internal",
        mode=Mode.ON,
    )

    def overrides(_now: datetime) -> Sequence[AdminStatus]:
        read_shown(publisher.host, publisher.prefix)  # the admin's statuses check the file
        return ()

    ingest = Ingest(
        ledger=world.ledger,
        resolver=world.resolver(),
        stations=world.stations,
        publisher=publisher,
        watch=EditionWatch(own=EDITION, source=Source([EDITION])),
        internal_dir=tmp_path / "run",
        due=frozenset({A}),
        overrides=overrides,
    )
    report = ingest.run_pass([SourceRead(A, ReadOutcome.OK, now, CLOSED)], now)
    assert report.exit is Exit.REFUSED
    assert len(fake.log) == 1  # the overrides' read, refused; the pass sends nothing more
    if kind == "primary":
        assert report.refusals == ("host",)
        assert report.retry_at == now + timedelta(minutes=30, seconds=1)
        assert report.note == "host refused until 11:35:01Z (primary_rate_limit)"
    else:
        assert report.refusals == ("overrides",)
        assert report.retry_at is None


def _budget(sent: Sequence[Request]) -> tuple[int, int, int]:
    return len(sent), sum(one.counted for one in sent), sum(one.write for one in sent)


def test_a_steady_hour_costs_at_most_80_counted_host_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hour = (at("2026-11-17 17:00"), at("2026-11-17 18:00"))
    steady = _live(tmp_path / "steady", START)
    for minute in (7, 37):  # predict.yml's two commits an hour
        steady.fake.later(
            hour[0] + timedelta(minutes=minute), {"v1/predictions/latest.json": b'{"SYNTHETIC":1}'}
        )
    assert steady.run("+70m", monkeypatch) == 0
    sent, counted, writes = _budget(steady.fake.sent(*hour))
    refused = _live(tmp_path / "refused", START)
    refused.fake.refuse(WINDOW[0], WINDOW[0] + timedelta(hours=1))
    assert refused.run("+70m", monkeypatch) == 3
    in_window = refused.fake.sent(WINDOW[0], WINDOW[0] + timedelta(hours=1, seconds=1))
    capsys.readouterr()
    with capsys.disabled():
        sys.stdout.write(
            "\nlive host calls in one hour (12 grid passes, predict's 2 commits)\n"
            f"  steady: {sent} sent, {counted} counted, {writes} writes\n"
            f"  refused all hour: {len(in_window)} sent\n"
        )
    assert sent <= 90
    assert counted <= 80
    assert writes == 36
    assert len(in_window) == 1


def _on_fake(tmp_path: Path, now: datetime) -> tuple[Clock, GitHubFake, World, LivePublisher]:
    """A publisher on the SYNTHETIC GitHub, publishing on (its own memory under tmp_path)."""
    clock = Clock(now)
    fake = GitHubFake(clock)
    world = World()
    publisher = LivePublisher(
        host=fake.publisher(),
        directory=world.dir,
        state_dir=tmp_path / "state",
        internal_dir=tmp_path / "internal",
        mode=Mode.ON,
    )
    return clock, fake, world, publisher


def test_a_refusal_mid_commit_on_the_pass_that_confirms_a_spike_keeps_it_pending(
    tmp_path: Path,
) -> None:
    """The gate's memory (the spike, the last healthy share, the refused streak) is put back
    when the host refuses the commit: the first allowed pass confirms the spike and
    publishes, and the gate alert opens on the same pass it would without the refusal."""
    now = at("2026-11-17 11:05")
    clock, fake, _, publisher = _on_fake(tmp_path, now)
    big = DirectoryStamp(generated_on=date(2026, 10, 14), schools=5000, districts=6)
    merged = _many(2001, date(2026, 11, 17))
    held = publisher.publish(merged, now=now, healthy_share=1.0, edition=equal(now, big))
    assert held.refusals == ("spike_hold",)
    pending = Memory.load(tmp_path / "state" / "publish.json")
    assert pending.spike is not None
    assert pending.refused_streak == 1
    fake.refuse_from("POST git/trees", timedelta(minutes=3))
    clock.now = later = now + timedelta(minutes=5)
    refused = publisher.publish(merged, now=later, healthy_share=1.0, edition=equal(later, big))
    assert refused.refusals == ("host",)
    assert refused.retry_at == later + timedelta(minutes=3, seconds=1)
    assert refused.alert  # the second refused pass in a row, as a spike_hold would be
    kept = Memory.load(tmp_path / "state" / "publish.json")
    assert kept.spike == pending.spike
    assert kept.previous_healthy_share == pending.previous_healthy_share
    assert kept.refused_streak == 2
    assert kept.lit == frozenset()
    assert not fake.uploads
    assert refused.retry_at is not None
    clock.now = refused.retry_at
    first = publisher.publish(
        merged, now=clock.now, healthy_share=1.0, edition=equal(clock.now, big), always=True
    )
    assert (first.exit, first.refusals) == (Exit.OK, ())
    assert len(_closings(fake.uploads[-1][1]).closings()) == 2001
    after = Memory.load(tmp_path / "state" / "publish.json")
    assert (after.spike, after.refused_streak) == (None, 0)


def test_a_refusal_of_the_admins_statuses_alone_is_a_host_refusal_and_the_next_pass_publishes(
    tmp_path: Path,
) -> None:
    """The gate refused the lists (health) and the admin's statuses go up alone: a host
    that refuses their commit refuses the pass for ``host`` (not the gate's codes), counts
    once toward the alert, and the first allowed pass publishes them."""
    now = at("2026-11-17 11:05")
    clock, fake, world, publisher = _on_fake(tmp_path, now)
    assert (
        publisher.publish(storm(world, now), now=now, healthy_share=1.0, edition=equal(now)).exit
        is Exit.OK
    )
    clock.now = later = now + timedelta(minutes=5)
    admin = AdminPart(
        (
            AdminStatus(school=3, nces_id=next(iter(world.dir.schools)), day=date(2026, 11, 17),
                        status=Status.CLOSED, shift_minutes=None, clock_minute=None,
                        set_at=later - timedelta(minutes=1), level="school", key="synthetic"),
        )
    )  # fmt: skip
    fake.refuse_from("POST git/trees", timedelta(minutes=2))
    uploads = len(fake.uploads)
    refused = publisher.publish(
        storm(world, later), now=later, healthy_share=0.1, edition=equal(later), admin=admin
    )
    assert (refused.exit, refused.refusals) == (Exit.REFUSED, ("host",))
    assert refused.note == "host refused until 11:12:01Z (primary_rate_limit)"
    assert not refused.alert
    kept = Memory.load(tmp_path / "state" / "publish.json")
    assert (kept.refused_streak, kept.last_admin) == (1, None)
    assert len(fake.uploads) == uploads
    assert refused.retry_at is not None
    clock.now = refused.retry_at
    admin_only = publisher.publish(
        storm(world, clock.now), now=clock.now, healthy_share=0.1, edition=equal(clock.now),
        admin=admin,
    )  # fmt: skip
    assert admin_only.note == "the admin's statuses on the last list rows"
    assert admin_only.uploaded
    assert admin_only.alert  # the lists were refused twice in a row
    assert Memory.load(tmp_path / "state" / "publish.json").last_admin == admin.digest


def test_a_run_that_ends_while_the_host_refuses_the_edition_blank_ends_host_not_blank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nobody can write the blank while the host refuses: a run that ends then ends with
    exit 3 and ``end host`` (its successor waits the same way), never exit 1."""
    live = _live(tmp_path, START)
    assert live.run("+5m", monkeypatch) == 0
    live.rig.edition[:] = [OWN.model_copy(update={"content_sha256": "c" * 64})]
    end = WINDOW[0] + timedelta(hours=2)
    live.fake.refuse(WINDOW[0], end)
    live.clock.now = WINDOW[0] + timedelta(minutes=1)
    assert live.run("+30m", monkeypatch) == 3
    out = capsys.readouterr().out
    assert "edition: the run ended while the live host refused the blank" in out
    assert out.splitlines()[-1] == "::notice::live-read end host"
    assert "live-read end blank" not in out
    assert "exit 1" not in out
    assert len(live.fake.sent(WINDOW[0], end)) == 1  # the start-up read; then nothing


def test_a_blank_that_fails_for_another_reason_after_the_host_allows_it_stops_with_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The blank's 10 minutes start when the host allows calls again: a blank that then
    fails for any other reason (a 502) stops the run with exit 1, ``end blank``, as today."""
    live = _live(tmp_path, START)
    assert live.run("+5m", monkeypatch) == 0
    live.rig.edition[:] = [OWN.model_copy(update={"content_sha256": "c" * 64})]
    reset = WINDOW[0] + timedelta(minutes=5)
    live.fake.refuse(WINDOW[0], reset)
    live.fake.refuse(reset, reset + timedelta(hours=2), "server")
    live.clock.now = WINDOW[0] + timedelta(minutes=1)
    assert live.run("+60m", monkeypatch) == 1
    out = capsys.readouterr().out
    assert "edition: different and the blank keeps failing; stopping" in out
    assert out.splitlines()[-2:] == ["exit 1: blank", "::notice::live-read end blank"]
    failed = [one for one in live.fake.log if one.status == httpx.codes.BAD_GATEWAY]
    assert failed[0].at < reset + timedelta(minutes=1)
    # it stopped once 10 minutes had passed since the reset, not since the first failure
    assert failed[-1].at - (reset + timedelta(seconds=1)) >= live_cli.BLANK_RETRY
    assert failed[-1].at - (reset + timedelta(seconds=1)) < live_cli.BLANK_RETRY + timedelta(
        minutes=1
    )


def test_a_run_prints_at_most_two_host_notices_and_plain_lines_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live = _live(tmp_path, START)
    for minutes in (0, 10, 20):  # three refusals, each met by a grid pass's first call
        start = WINDOW[0] + timedelta(minutes=minutes)
        live.fake.refuse(start, start + timedelta(minutes=2))
    assert live.run("+30m", monkeypatch) == 3
    lines = capsys.readouterr().out.splitlines()
    news = [line for line in lines if "live-read host refused" in line]
    assert [line.startswith("::notice::") for line in news] == [True, True, False]
    assert news[2] == "live-read host refused primary_rate_limit until 2026-11-17T17:22:16+00:00"
    assert len([line for line in lines if line.startswith("live-read host answers")]) == 3
    assert lines[-1] == "::notice::live-read end until"


def test_a_refusal_first_met_by_the_alerts_write_is_announced_at_the_next_check_and_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate alert closes after a pass and its alerts.json commit is the first request
    the host refuses: the next 60-s check announces it, and the next pass sends nothing
    until the time it gave."""
    live = _live(tmp_path, START)
    live.fake.refuse(WINDOW[0], WINDOW[0] + timedelta(minutes=8))  # 17:00 and 17:05 refused
    live.fake.refuse_from("POST git/trees", timedelta(minutes=5), body="alerts.json")
    said: list[tuple[datetime, str]] = []

    def recorded(level: str, text: str) -> None:
        said.append((live.clock.now, text))
        annotate(level, text)

    monkeypatch.setattr(live_cli, "annotate", recorded)
    assert live.run("+30m", monkeypatch) == 3
    out = capsys.readouterr().out
    assert "::warning::live alert gate closed at 2026-11-17T17:08:36Z (v1)" in out
    refused = [one for one in live.fake.log if one.status == httpx.codes.FORBIDDEN]
    assert [(str(one), one.at) for one in refused[1:]] == [
        ("POST git/trees", at("2026-11-17 17:08") + timedelta(seconds=36))
    ]
    until = "2026-11-17T17:13:37+00:00"
    told = [(when, text) for when, text in said if text.endswith(f"until {until}")]
    assert len(told) == 1
    assert told[0][0] - refused[1].at <= timedelta(seconds=61)
    assert told[0][0] < at("2026-11-17 17:10")  # at the check, before the next pass
    assert not live.fake.sent(refused[1].at + timedelta(seconds=1), at("2026-11-17 17:13:37"))
    assert "exit 3: refusals host; uploaded 0; edition equal; host refused until 17:13:37Z" in out


def test_a_refusal_at_the_hold_read_after_an_upload_fails_that_pass_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    quiet_logs: pytest.LogCaptureFixture,
) -> None:
    """The hold read after an upload keeps its rule (exit 1: the hold is unknown), and the
    passes the host refuses after it are no failed passes: the run never ends ``passes``."""
    live = _live(tmp_path, START)
    assert live.run("+5m", monkeypatch) == 0
    # a successor's first pass: the hold, the guard in the commit, then the hold after it
    live.fake.refuse_from("GET contents/v1/live/hold.json", timedelta(minutes=25), skip=2)
    live.clock.now = WINDOW[0]
    assert live.run("+40m", monkeypatch) == 3
    out = capsys.readouterr().out
    refused = [one for one in live.fake.log if one.status == httpx.codes.FORBIDDEN]
    assert [str(one) for one in refused] == ["GET contents/v1/live/hold.json"]
    lines = [line for line in out.splitlines() if line.startswith("exit ")]
    errors = [rec.getMessage() for rec in quiet_logs.records if rec.levelno >= logging.ERROR]
    assert any(line.startswith("read hold after the upload: ") for line in errors)
    assert len([line for line in lines if line.startswith("exit 3: refusals host;")]) >= 4
    assert "failed passes in a row" not in out
    assert "live-read end passes" not in out
    assert out.splitlines()[-1] == "::notice::live-read end until"
    after = [when for when, files in live.fake.uploads if when > refused[0].at]
    assert after
    assert after[0] == refused[0].at + timedelta(minutes=25, seconds=1) + LAG

"""The Flights live loop (snowlight.flights.loop) on a fake clock: a pass per 20 minutes, the
freshness rule, a failed pass that never ends the loop, and the deadline."""

from datetime import UTC, datetime, timedelta

import pytest

from snowlight.flights import loop

START = datetime(2026, 11, 26, 15, 0, 7, tzinfo=UTC)


class World:
    """A fake clock and host: each pass takes ``pass_minutes`` and, when it exits 0, makes the
    host's ``latest.json`` stamp its start (as a real pass does)."""

    def __init__(
        self,
        codes: list[int] | None = None,
        made: datetime | None = None,
        pass_minutes: float = 4.0,
        alert_codes: list[int] | None = None,
    ) -> None:
        self.now = START
        self.codes = list(codes or [])
        self.stamp = made
        self.pass_minutes = pass_minutes
        self.alert_codes = list(alert_codes or [])
        self.starts: list[datetime] = []
        self.alerted: list[datetime] = []
        self.lines: list[str] = []
        self.reads = 0

    def clock(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds >= 1.0
        self.now += timedelta(seconds=seconds)

    def made(self) -> datetime | None:
        self.reads += 1
        return self.stamp

    def one_pass(self) -> int:
        started = self.now
        self.starts.append(started)
        self.now += timedelta(minutes=self.pass_minutes)
        code = self.codes.pop(0) if self.codes else 0
        if code == 0:
            self.stamp = started
        return code

    def alerts(self) -> int:
        self.alerted.append(self.now)
        self.now += timedelta(seconds=30)
        return self.alert_codes.pop(0) if self.alert_codes else 0

    def run(self, minutes: float = 300) -> loop.Outcome:
        return loop.run(
            deadline=START + timedelta(minutes=minutes),
            clock=self.clock,
            sleep=self.sleep,
            made=self.made,
            one_pass=self.one_pass,
            alerts=self.alerts,
            log=self.lines.append,
        )


def test_a_pass_every_20_minutes_until_the_deadline() -> None:
    world = World(made=START - timedelta(minutes=40))
    outcome = world.run(300)
    assert outcome == loop.Outcome(passes=15, written=15, failed=0)
    assert world.starts == [START + timedelta(minutes=20 * n) for n in range(15)]
    # The trip alerts follow every pass that wrote; no pass starts at or after the deadline.
    assert len(world.alerted) == 15
    assert max(world.starts) < START + timedelta(minutes=300)
    # The loop ends right after its last pass, not at the deadline.
    assert world.now < START + timedelta(minutes=285)
    assert world.lines[-1] == "flights loop: 15 passes, 15 written, 0 failed"


def test_a_failed_pass_never_ends_the_loop() -> None:
    world = World(codes=[0, 3, 1, loop.EXIT_TIMEOUT, 0], made=None)
    outcome = world.run(100)
    assert outcome == loop.Outcome(passes=5, written=2, failed=3)
    # Each failed pass waits its 20 minutes too: no tight chain of retries.
    assert world.starts == [START + timedelta(minutes=20 * n) for n in range(5)]
    assert len(world.alerted) == 2
    warnings = [line for line in world.lines if line.startswith("::warning::")]
    assert len(warnings) == 3
    assert "exit 3 (nothing written" in warnings[0]
    assert "exit 1 (an error)" in warnings[1]
    assert "exit 124 (ended at its time limit)" in warnings[2]


def test_failed_alerts_never_end_the_loop() -> None:
    world = World(alert_codes=[1, loop.EXIT_TIMEOUT])
    outcome = world.run(60)
    assert outcome == loop.Outcome(passes=3, written=3, failed=0)
    assert sum("trip alerts ended with exit" in line for line in world.lines) == 2
    assert not any(line.startswith("::warning::") for line in world.lines)


def test_a_fresh_file_waits_until_it_is_15_minutes_old() -> None:
    # The previous loop's last pass was 6 minutes ago: the first pass waits 9 more.
    world = World(made=START - timedelta(minutes=6))
    world.run(60)
    first = START + timedelta(minutes=9)
    assert world.starts == [first, first + timedelta(minutes=20), first + timedelta(minutes=40)]
    assert any("is fresh: no pass yet" in line for line in world.lines)


def test_another_writer_holds_the_next_pass_back() -> None:
    world = World(made=None)
    stamps = iter([None, START + timedelta(minutes=25), START + timedelta(minutes=25)])

    def made() -> datetime | None:
        return next(stamps, world.stamp)

    outcome = loop.run(
        deadline=START + timedelta(minutes=60),
        clock=world.clock,
        sleep=world.sleep,
        made=made,
        one_pass=world.one_pass,
        alerts=world.alerts,
        log=world.lines.append,
    )
    # Pass at 0; at 20 the host holds a pass of minute 25 (ahead of the clock by 5 minutes: not
    # believed, so a pass runs); at 40 that stamp is 15 minutes old: a pass runs.
    assert world.starts == [START, START + timedelta(minutes=20), START + timedelta(minutes=40)]
    assert outcome.passes == 3
    assert any("is ahead of the clock: a pass runs" in line for line in world.lines)


def test_a_writer_just_before_the_tick_delays_it() -> None:
    world = World(made=None)
    stamps = iter([None, START + timedelta(minutes=18)])

    def made() -> datetime | None:
        return next(stamps, world.stamp)

    loop.run(
        deadline=START + timedelta(minutes=50),
        clock=world.clock,
        sleep=world.sleep,
        made=made,
        one_pass=world.one_pass,
        alerts=world.alerts,
        log=world.lines.append,
    )
    # At 20 the host holds a pass of minute 18: the next pass waits until minute 33.
    assert world.starts == [START, START + timedelta(minutes=33)]


def test_a_fresh_file_until_the_deadline_runs_nothing() -> None:
    world = World(made=START - timedelta(minutes=1))
    outcome = world.run(10)
    assert outcome == loop.Outcome(passes=0, written=0, failed=0)
    assert world.starts == []


def test_a_slow_pass_starts_the_next_at_once_when_due() -> None:
    # A pass that runs to its hard limit (9 minutes): the next still starts 20 minutes after it.
    world = World(pass_minutes=9, codes=[loop.EXIT_TIMEOUT])
    world.run(45)
    assert world.starts == [START, START + timedelta(minutes=20), START + timedelta(minutes=40)]


@pytest.mark.parametrize(
    ("body", "made"),
    [
        (b'{"generated_at": "2026-11-26T15:01:00Z"}', datetime(2026, 11, 26, 15, 1, tzinfo=UTC)),
        (
            b'{"generated_at": "2026-11-26T10:01:00-05:00"}',
            datetime(2026, 11, 26, 15, 1, tzinfo=UTC),
        ),
        (b'{"generated_at": "2026-11-26T15:01:00"}', None),
        (b'{"generated_at": 5}', None),
        (b'{"slot": "slot-1"}', None),
        (b"[1]", None),
        (b"not json", None),
        (None, None),
    ],
)
def test_the_stamp_of_latest(body: bytes | None, made: datetime | None) -> None:
    assert loop.made_of(body) == made


def test_until_and_the_child_environment() -> None:
    assert loop.until_of("+300m", START) == START + timedelta(minutes=300)
    assert loop.until_of("5h", START) == START + timedelta(hours=5)
    env = {"LIVE_HOST_TOKEN": "a", "CLOUDFLARE_API_TOKEN": "b", "PATH": "/bin"}
    assert loop.without(env, ["CLOUDFLARE_API_TOKEN", "GITHUB_TOKEN"]) == {
        "LIVE_HOST_TOKEN": "a",
        "PATH": "/bin",
    }

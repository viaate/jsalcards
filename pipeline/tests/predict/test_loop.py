"""The serving loop: the grid and heartbeat, retries after a dark pass, the day file, the alert
memory across a lost state, the hold, cancelled warnings, and the worst-case file size."""

import random
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Any, Final

import pytest

from predict import world
from predict.test_publish import NOW, MemoryHost, feed, make_pass
from snowlight.live.publishers import PublishError
from snowlight.predict import artifact, cli
from snowlight.predict.alerts_live import Memory, alerts_digest, live_events, withdrawn
from snowlight.predict.publish import Dark, DarkError, State, check_budget, due
from snowlight.predict.why import ALERT_KIND
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.predictions import (
    AlertBase,
    DistrictForecast,
    Forecast,
    PastDay,
    PastRecord,
    PooledBase,
    PredictionsFile,
    PreviousChance,
    Why,
)
from snowlight.schemas.vocab import Reason, Status
from snowlight.sources.nws.alerts import parse_active

KEY = "v1/predictions/latest.json"
SETTINGS = world.CONFIG.serve


def chances(host: MemoryHost) -> list[list[float | None]]:
    found = PredictionsFile.from_json_bytes(host.files[KEY])
    return [[getattr(day, "p_no_school", None) for day in entry.days] for entry in found.districts]


def simulate(rng: random.Random, monkeypatch: Any) -> tuple[list[datetime], list[datetime]]:
    """One 320-minute run with passes of 30 s to 150 s and checks of up to 8 s on unchanged
    content: (uploads, grid pass starts)."""
    clock = [datetime(2026, 10, 20, 12, 0, tzinfo=UTC) + timedelta(seconds=rng.uniform(0, 3600))]
    uploads: list[datetime] = []
    starts: list[datetime] = []

    def fake_pass(run: cli.Pass, *, grid: bool) -> int:
        now = clock[0]
        if grid:
            starts.append(now)
        run.state.alerts_digest = alerts_digest([])
        if due(run.state, "same", now, SETTINGS, grid=grid):
            run.state.digest, run.state.uploaded_at = "same", now
            uploads.append(now)
        clock[0] += timedelta(seconds=rng.uniform(30, 150))
        return 0

    def alerts() -> tuple[Any, bool]:
        clock[0] += timedelta(seconds=rng.uniform(0.5, 8))
        return feed(updated=clock[0].isoformat(), alerts=0), False

    def sleep(seconds: float) -> None:
        clock[0] += timedelta(seconds=seconds)

    run = make_pass(MemoryHost(), directory=world.directory())
    run.alerts = alerts
    monkeypatch.setattr(cli, "one_pass", fake_pass)
    end = clock[0] + timedelta(minutes=320)
    cli.loop(run, end, cli.Loop(lambda: clock[0], sleep), lambda _s: None)
    return uploads, starts


def test_grid_passes_keep_the_heartbeat_on_every_grid_slot(monkeypatch: Any) -> None:
    """Unchanged content uploads only as the heartbeat. Grid passes start on :07 and :37 and
    every one uploads, so no upload gap passes the heartbeat by more than the skip."""
    rng = random.Random(7)  # noqa: S311 - a reproducible simulation, not a secret
    worst = 0.0
    for _run in range(60):
        uploads, starts = simulate(rng, monkeypatch)
        # On the grid minute, at most a check's few seconds late.
        late = [start for start in starts[1:] if start.minute not in (7, 37) or start.second > 15]
        assert not late, (starts[:6], late[:3])
        worst = max(worst, *((b - a).total_seconds() / 60 for a, b in pairwise(uploads)))
    # A grid pass skips only when an upload went out under heartbeat_skip_minutes before.
    assert worst <= SETTINGS.heartbeat_minutes + SETTINGS.heartbeat_skip_minutes


def test_due_counts_the_heartbeat_on_the_grid() -> None:
    state = State(digest="d", uploaded_at=NOW)
    later = NOW + timedelta(minutes=27)
    assert due(state, "d", later, SETTINGS, grid=True)
    assert not due(state, "d", later, SETTINGS, grid=False)
    assert not due(state, "d", NOW + timedelta(minutes=3), SETTINGS, grid=True)
    assert due(state, "d", NOW + timedelta(minutes=30), SETTINGS, grid=False)
    assert due(state, "e", NOW + timedelta(minutes=1), SETTINGS, grid=False)


class RaceHost(MemoryHost):
    """A host whose next write fails once (another writer moved the branch first)."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next = False

    def write(self, files: Mapping[str, bytes]) -> None:
        if self.fail_next:
            self.fail_next = False
            raise PublishError("move branch: not a fast forward")
        super().write(files)


def test_a_dark_pass_after_an_alert_change_is_tried_again_at_the_next_check(
    monkeypatch: Any,
) -> None:
    host = RaceHost()
    clock = [NOW]
    storm = [False]

    def alerts() -> tuple[Any, bool]:
        return feed(
            updated=(clock[0] - timedelta(minutes=1)).isoformat(), alerts=int(storm[0])
        ), True

    run = make_pass(host, directory=world.directory())
    run.now = lambda: clock[0]
    run.alerts = alerts
    published: list[tuple[datetime, float]] = []
    original = cli.one_pass

    def watched(run: cli.Pass, *, grid: bool) -> int:
        code = original(run, grid=grid)
        if KEY in host.files and code == 0:
            published.append((clock[0], max(p or 0 for row in chances(host) for p in row)))
        return code

    def sleep(seconds: float) -> None:
        clock[0] += timedelta(seconds=seconds)
        if clock[0] >= NOW + timedelta(minutes=12) and not storm[0]:
            storm[0] = True
            host.fail_next = True  # the pass the warning starts loses an upload race

    monkeypatch.setattr(cli, "one_pass", watched)
    dark = cli.loop(
        run, NOW + timedelta(minutes=40), cli.Loop(lambda: clock[0], sleep), lambda _s: None
    )
    assert dark == 1
    issued = NOW + timedelta(minutes=12)
    stormy = [at for at, top in published if top > 0.01]
    assert stormy
    # The retry comes at the next check after the dark pass (at most min_gap after it), long
    # before the next grid pass.
    assert stormy[0] - issued <= timedelta(
        minutes=SETTINGS.check_minutes + SETTINGS.min_gap_minutes
    )


def test_an_unexpected_error_is_a_dark_pass_and_the_loop_goes_on() -> None:
    run = make_pass(MemoryHost(), directory=world.directory())
    clock = [NOW]
    run.now = lambda: clock[0]
    run.alerts = lambda: (feed(updated=(clock[0] - timedelta(minutes=1)).isoformat()), True)
    calls = [0]
    bare = run.model

    def model() -> Any:
        calls[0] += 1
        if calls[0] == 1:
            raise KeyError("a broken model")
        return bare()

    run.model = model

    def sleep(seconds: float) -> None:
        clock[0] += timedelta(seconds=seconds)

    dark = cli.loop(
        run, NOW + timedelta(minutes=20), cli.Loop(lambda: clock[0], sleep), lambda _s: None
    )
    assert dark == 1
    assert KEY in run.host.files  # type: ignore[union-attr]


class FlakyDays(MemoryHost):
    def read(self, key: str) -> bytes | None:
        if "/live/days/" in key:
            raise PublishError(f"read {key}: HTTP 502")
        return super().read(key)


def test_a_day_file_that_cannot_be_read_darkens_the_pass(capsys: Any) -> None:
    flaky = FlakyDays()
    assert cli.one_pass(make_pass(flaky, directory=world.directory(), alerts=feed(alerts=0))) == 3
    assert KEY not in flaky.files
    assert "day_file_unreadable" in capsys.readouterr().err
    # A host that holds no day file at all: no district had a day off; the pass publishes.
    plain = MemoryHost()
    assert cli.one_pass(make_pass(plain, directory=world.directory(), alerts=feed(alerts=0))) == 0


def storm_product() -> Any:
    return world.feature(
        "/O.NEW.KEAX.WS.W.0001.260107T0600Z-260108T0000Z/",
        ("MOZ028",),
        sent="2026-01-06T20:00:00+00:00",
        onset="2026-01-07T06:00:00+00:00",
        ends="2026-01-08T00:00:00+00:00",
    )


def test_a_lost_state_rebuilds_the_alert_memory_or_goes_dark() -> None:
    # The warning was in the feed at 02:00 and has left it by 07:00 (ended early, or the feed
    # dropped it); the 07:00 pass must still count it for today.
    host = MemoryHost()
    run = make_pass(host, directory=world.directory())
    assert cli.one_pass(run) == 0
    later = NOW + timedelta(hours=5)
    empty = feed(updated=(later - timedelta(minutes=2)).isoformat(), alerts=0)
    run.now = lambda: later
    run.alerts = lambda: (empty, True)
    run.state.observed_at = later - timedelta(minutes=5)  # read all along
    assert cli.one_pass(run) == 0
    kept = chances(host)
    assert max(p or 0 for row in kept for p in row) > 0.01
    # The state is lost: the memory is rebuilt from the NWS alert history, so the chances
    # are the same.
    history = parse_active(world.feed_bytes([storm_product()], "2026-01-07T06:58:00+00:00"))
    seen: list[tuple[datetime, datetime]] = []

    def read_history(start: datetime, end: datetime) -> list[Any]:
        seen.append((start, end))
        return list(history.alerts)

    lost_host = MemoryHost()
    lost = make_pass(lost_host, directory=world.directory(), now=later, alerts=empty)
    lost.history = read_history
    assert cli.one_pass(lost) == 0
    assert chances(lost_host) == kept
    assert seen
    assert seen[0][0] <= datetime(2026, 1, 6, 0, 0, tzinfo=UTC)  # 18:00 Jan 5 east, less 48 h
    assert lost.state.memory_since is not None
    # A stale state (the feed unread for hours) is a gap too.
    stale = make_pass(MemoryHost(), directory=world.directory(), now=later, alerts=empty)
    stale.state = State(memory=run.state.memory, memory_since=NOW - timedelta(days=1),
                        observed_at=later - timedelta(hours=3))  # fmt: skip
    stale.history = read_history
    calls = len(seen)
    assert cli.one_pass(stale) == 0
    assert len(seen) == calls + 1
    # No history to read (or it fails): dark, never a 1% from a forgotten warning.
    blind = make_pass(MemoryHost(), directory=world.directory(), now=later, alerts=empty)
    blind.history = None
    assert cli.one_pass(blind) == cli.EXIT_DARK

    def broken(_start: datetime, _end: datetime) -> list[Any]:
        raise DarkError(Dark.MEMORY, "alert history: HTTP 503")

    failing_host = MemoryHost()
    failing = make_pass(failing_host, directory=world.directory(), now=later, alerts=empty)
    failing.history = broken
    assert cli.one_pass(failing) == cli.EXIT_DARK
    assert KEY not in failing_host.files


def test_a_cancelled_warning_leaves_the_memory() -> None:
    issued = parse_active(world.feed_bytes([storm_product()], "2026-01-06T20:05:00+00:00"))
    memory = Memory(30)
    memory.update(live_events(issued), datetime(2026, 1, 6, 20, 5, tzinfo=UTC))
    assert memory.seen
    cancel = world.feature(
        "/O.CAN.KEAX.WS.W.0001.000000T0000Z-260108T0000Z/",
        ("MOZ028",),
        sent="2026-01-07T01:00:00+00:00",
        onset=None,
        ends=None,
        message_type="Cancel",
    )
    later = parse_active(world.feed_bytes([cancel], "2026-01-07T01:05:00+00:00"))
    counted = memory.update(
        live_events(later), datetime(2026, 1, 7, 1, 5, tzinfo=UTC), withdrawn(later.alerts)
    )
    assert counted == []
    assert memory.seen == {}
    # A cancel of some zones keeps the others.
    two = world.feature(
        "/O.NEW.KEAX.WS.W.0002.260107T0600Z-260108T0000Z/",
        ("MOZ028", "MOZ029"),
        sent="2026-01-06T20:00:00+00:00",
        onset="2026-01-07T06:00:00+00:00",
        ends="2026-01-08T00:00:00+00:00",
    )
    both = Memory(30)
    both.rebuild(
        list(parse_active(world.feed_bytes([two], "2026-01-06T20:05:00+00:00")).alerts), NOW
    )
    part = world.feature(
        "/O.CAN.KEAX.WS.W.0002.000000T0000Z-260108T0000Z/",
        ("MOZ029",),
        sent="2026-01-07T01:00:00+00:00",
        onset=None,
        ends=None,
        message_type="Cancel",
    )
    both.withdraw(
        withdrawn(parse_active(world.feed_bytes([part], "2026-01-07T01:05:00+00:00")).alerts)
    )
    assert [key[1] for key in both.seen] == [frozenset({"MOZ028"})]


def test_blank_holds_every_chance_dark_until_release() -> None:
    host = MemoryHost()
    run = make_pass(host, directory=world.directory())
    assert cli.one_pass(run) == 0
    assert cli.blank(host, world.STAMP, world.CONFIG, NOW + timedelta(minutes=1)) == 0
    assert PredictionsFile.from_json_bytes(host.files[KEY]).districts == ()
    assert "v1/predictions/hold.json" in host.files
    assert "v1-shadow/predictions/hold.json" in host.files
    # The heartbeat and an alert change both find the hold: nothing uploads.
    run.now = lambda: NOW + timedelta(minutes=31)
    run.alerts = lambda: (feed(updated="2026-01-07T02:30:00+00:00", alerts=2), True)
    assert cli.one_pass(run) == cli.EXIT_DARK
    assert PredictionsFile.from_json_bytes(host.files[KEY]).districts == ()
    assert cli.release(host, NOW + timedelta(minutes=32)) == 0
    assert cli.one_pass(run) == 0
    assert len(PredictionsFile.from_json_bytes(host.files[KEY]).districts) == 5
    # A hold file that does not read holds too.
    host.files["v1/predictions/hold.json"] = b"nonsense"
    run.now = lambda: NOW + timedelta(minutes=64)  # the heartbeat is due
    run.alerts = lambda: (feed(updated="2026-01-07T03:03:00+00:00"), True)
    assert cli.one_pass(run) == cli.EXIT_DARK


# The longest alert name a base can carry (a winter storm warning day, and every day that
# borrows its rates), so no real day's entry is longer than the worst case's.
LONGEST_ALERT: Final = max(ALERT_KIND.values(), key=len)


def worst_case_file(districts: int, with_record: int) -> bytes:
    """Every district under a warning on both days, with a previous chance, the longest alert
    name and the longest zone name; ``with_record`` of them with a full 8-day record (an own
    base)."""
    day = date(2026, 1, 7)
    at = datetime(2026, 1, 7, 1, 30, tzinfo=UTC)
    record = PastRecord(
        proves="base",
        inches=None,
        days=tuple(
            PastDay(day=date(2025, 1, d + 1), inches=None, status=Status.CLOSED) for d in range(8)
        ),
    )
    plain = Forecast(
        state="forecast",
        p_no_school=0.57,
        p_delay=0.13,
        reasons=(Reason.WINTER_STORM,),
        previous=PreviousChance(p_no_school=0.43, at=at - timedelta(minutes=30)),
        announces_at=None,
        buses_at=None,
        hours=None,
        why=Why(
            base=PooledBase(
                kind="pooled",
                scope="nation",
                points=57,
                alert=LONGEST_ALERT,
                borrowed=False,
                live=False,
            ),
            reasons=(),
        ),
        record=None,
        events=(),
    )
    own = plain.model_copy(
        update={
            "why": Why(
                base=AlertBase(
                    kind="alert", points=57, alert=LONGEST_ALERT, borrowed=False, live=False
                ),
                reasons=(),
            ),
            "record": record,
        }
    )
    entries = tuple(
        DistrictForecast(
            district=i,
            time_zone="America/North_Dakota/New_Salem",
            neighbors=tuple(range(max(0, i - 12), i)) if i >= 12 else tuple(range(i + 1, i + 13)),
            days=(own, own) if i < with_record else (plain, plain),
        )
        for i in range(districts)
    )
    return PredictionsFile(
        schema_version=1,
        generated_at=at,
        directory=DirectoryStamp(
            generated_on=date(2026, 10, 14), schools=118_211, districts=districts
        ),
        days=(day, day + timedelta(days=1)),
        districts=entries,
    ).to_json_bytes()


def test_the_worst_case_file_fits_the_size_budget() -> None:
    """Every deployed district (18,227) under a warning on both days with a previous chance,
    and every district the committed model gives a record to with a full record: the file must
    still fit, or a storm over the whole country would darken every chance."""
    model = artifact.load()
    with_record = sum(1 for entry in model.districts.values() if entry.record)
    worst = worst_case_file(18_227, with_record)
    packed = check_budget(worst, SETTINGS)
    assert len(worst) <= SETTINGS.budget_raw_bytes
    assert packed <= SETTINGS.budget_gzip_bytes
    with pytest.raises(DarkError, match="size"):
        check_budget(worst + b" " * (SETTINGS.budget_raw_bytes - len(worst) + 1), SETTINGS)

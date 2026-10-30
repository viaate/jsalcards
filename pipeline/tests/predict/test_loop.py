"""The serving loop: the grid and heartbeat, retries after a dark pass, the day file, the alert
memory across a lost state, the hold, cancelled warnings, and the worst-case file size."""

import functools
import json
import math
import random
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise, product
from typing import Any, Final
from zoneinfo import available_timezones

import pytest

from predict import world
from predict.test_publish import NOW, MemoryHost, feed, make_pass
from snowlight.live.publishers import PublishError
from snowlight.predict import artifact, cli, serve
from snowlight.predict.alerts_live import Memory, alerts_digest, live_events, withdrawn
from snowlight.predict.artifact import RecordDay
from snowlight.predict.pool import SCOPES
from snowlight.predict.publish import Dark, DarkError, State, check_budget, due
from snowlight.predict.situations import SITUATIONS
from snowlight.predict.why import ALERT_KIND, Of, sayable
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.predictions import (
    MAX_OUTLOOKS,
    MAX_SCHOOL_NEIGHBORS,
    MAX_ZONES,
    AlertBase,
    DistrictForecast,
    Forecast,
    NightSnow,
    OutlookReason,
    PastDay,
    PastRecord,
    PooledBase,
    PredictionsFile,
    PreviousChance,
    SchoolForecast,
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


def _event_passes(tail: float, monkeypatch: Any) -> list[tuple[datetime, bool]]:
    """Every pass of a 6 h loop (start, grid) whose alerts change at fixed moments, each pass
    taking 40 s and then ``tail`` seconds more after it publishes (the shadow chart)."""
    start = datetime(2026, 1, 13, 0, 0, 30, tzinfo=UTC)
    clock = [start]
    changes = [start + timedelta(minutes=m) for m in (3, 19, 44, 71, 128, 133, 205, 290, 333)]
    passes: list[tuple[datetime, bool]] = []

    def digest(at: datetime) -> str:
        return str(sum(1 for change in changes if change <= at))

    def fake_pass(run: cli.Pass, *, grid: bool) -> int:
        passes.append((clock[0], grid))
        run.state.alerts_digest = digest(clock[0])
        clock[0] += timedelta(seconds=40 + tail)
        return 0

    def alerts() -> tuple[Any, bool]:
        return feed(updated=clock[0].isoformat(), alerts=0), False

    run = make_pass(MemoryHost(), directory=world.directory())
    run.alerts = alerts
    monkeypatch.setattr(cli, "one_pass", fake_pass)
    monkeypatch.setattr(cli, "alerts_digest", lambda _events: digest(clock[0]))

    def sleep(seconds: float) -> None:
        clock[0] += timedelta(seconds=seconds)

    cli.loop(run, start + timedelta(hours=6), cli.Loop(lambda: clock[0], sleep), lambda _s: None)
    return passes


def test_a_shadow_chart_s_tail_never_moves_an_alert_pass_later(monkeypatch: Any) -> None:
    """Critic r2 S3: the shadow chart reads and builds after its pass publishes (up to about
    80 s with its read budget). The loop counts its next check from the pass's start, so every
    pass an alert change brings starts when it would with no chart at all."""
    bare = _event_passes(0, monkeypatch)
    for tail in (25.0, 90.0):
        assert _event_passes(tail, monkeypatch) == bare
    events = [at for at, grid in bare if not grid]
    assert len(events) >= 6


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
# borrows its rates), so no real day's entry is longer than the worst case's: asserted over
# every day the pass can make (test_no_day_the_pass_can_make_is_longer_than_the_worst_case).
LONGEST_ALERT: Final = max(ALERT_KIND.values(), key=len)
LONGEST_ZONE: Final = "America/North_Dakota/New_Salem"
LONGEST_ZONES: Final = tuple(
    sorted((z for z in available_timezones() if "/" in z), key=lambda z: (-len(z), z))[:MAX_ZONES]
)
DEPLOYED_SCHOOLS: Final = 118_211
"""The deployed directory's schools: every private school's index has its six digits."""
GROWTH: Final = 1.05
"""A new directory edition may add this share of districts and private schools (one edition
to the next has moved by well under 1%) and the worst case must still fit."""


def _record() -> PastRecord:
    return PastRecord(
        proves="base",
        inches=None,
        days=tuple(
            PastDay(day=date(2025, 1, d + 1), inches=None, status=Status.CLOSED) for d in range(8)
        ),
    )


def _worst_day(
    at: datetime, *, own: bool, of: str = "districts", minutes: int = 30, previous: bool = True
) -> Forecast:
    """A day under a warning with a previous chance (none with ``previous`` false), its base
    carrying the longest alert and both flags (borrowed and live); ``own``: an own base with a
    full 8-day record. No day said open is longer: its said_open line comes with no previous
    chance (contract C3)."""
    base: AlertBase | PooledBase = (
        AlertBase(kind="alert", points=57, alert=LONGEST_ALERT, borrowed=True, live=True)
        if own
        else PooledBase(
            kind="pooled",
            scope="nearby",
            points=57,
            alert=LONGEST_ALERT,
            borrowed=True,
            live=True,
            of="private_schools" if of == "private_schools" else "districts",
        )
    )
    return Forecast(
        state="forecast",
        p_no_school=0.57,
        p_delay=0.13,
        reasons=(Reason.WINTER_STORM,),
        previous=PreviousChance(p_no_school=0.43, at=at - timedelta(minutes=minutes))
        if previous
        else None,
        why=Why(base=base, reasons=()),
        record=_record() if own else None,
    )


OF: Final[tuple[Of, ...]] = ("districts", "private_schools")


def _every_day(at: datetime) -> list[Forecast]:
    """Every kind of school day the pass can make (serve._forecast): each situation counted
    over each one it may truly be, an own base or each pooled scope, districts' or private
    schools' days, read live or not, said open or not, with a previous chance or none, with a
    full record or none, a nation base thin or not (the flag is as long as ``live``, which it
    never comes with)."""
    found: list[Forecast] = []
    day = date(2026, 1, 7)
    earlier = (
        0.43,
        PreviousChance(p_no_school=0.41, at=at - timedelta(minutes=60)),
        at - timedelta(minutes=30),
    )
    full = tuple(RecordDay(day=date(2025, 1, d + 1), did="closed") for d in range(8))
    for counted in SITUATIONS:
        for situation in SITUATIONS:
            if not sayable(situation, counted):
                continue
            for own, scope, live, of, said, last, records, thin in product(
                (False, True),
                SCOPES,
                (False, True),
                OF,
                (False, True),
                (None, earlier),
                ({}, {counted.key: full}),
                (False, True),
            ):
                if own and scope != SCOPES[0]:
                    continue
                if thin and (own or scope != "nation"):
                    continue  # only a nation base is thin (and never one read live)
                cell = serve._Cell(
                    p=0.57, q=0.13, own=own, scope=scope, counted=counted, live=live,
                    records=records, of=of, thin=thin,
                )  # fmt: skip
                found.append(serve._forecast(cell, situation, day, last, at, said_open=said))
    return found


def test_no_day_the_pass_can_make_is_longer_than_the_worst_case() -> None:
    """The worst case's days are the longest the pass can write: a district's day with a
    record no longer than the own worst day, one without no longer than the pooled worst day,
    a private school's outlook no longer than the own worst day (each outlook in the worst
    case's table), and one without a record no longer than the pooled worst day over private
    schools, so the worst-case files below are the real maximum (a day said open included)."""
    at = datetime(2026, 1, 7, 1, 30, tzinfo=UTC)
    days = _every_day(at)
    assert any(any(r.kind == "said_open" for r in d.why.reasons) for d in days)
    assert any(d.record is not None for d in days)
    own = len(_worst_day(at, own=True).to_json_bytes())
    plain = len(_worst_day(at, own=False).to_json_bytes())
    plain_private = len(_worst_day(at, own=False, of="private_schools").to_json_bytes())
    for found in days:
        size = len(found.to_json_bytes())
        assert size <= own, found
        base = found.why.base
        if found.record is None:
            assert size <= plain_private, found
            if not isinstance(base, PooledBase) or base.of == "districts":
                assert size <= plain, found


def _longest_bare(at: datetime, of: Of) -> Forecast:
    """The longest day with no previous chance and no record the pass can make over ``of``'s
    days (a district's base names no ``of``): a day said open (:func:`_every_day`)."""
    return max(
        (
            d
            for d in _every_day(at)
            if d.previous is None
            and d.record is None
            and getattr(d.why.base, "of", "districts") == of
        ),
        key=lambda d: len(d.to_json_bytes()),
    )


BARE_CELLS: Final = tuple(
    (scope, p, q)
    for p in range(10, 90)
    for q in range(10, 101 - p)
    for scope in ("nearby", "county", "region", "nation")
)
"""Distinct (scope, chance, delay chance) cells: a scope of six letters, chances of two
digits."""


def _bare_outlook(at: datetime, k: int) -> Forecast:
    """The ``k``-th distinct private outlook with no previous chance and no record, the worst
    day's but for its cell (the test adds what a day said open has over it)."""
    scope, p, q = BARE_CELLS[k]
    day = _worst_day(at, own=False, of="private_schools", previous=False)
    base = day.why.base
    assert isinstance(base, PooledBase)
    return day.model_copy(
        update={
            "p_no_school": p / 100,
            "p_delay": q / 100,
            "why": Why(base=base.model_copy(update={"scope": scope, "points": p}), reasons=()),
        }
    )


@functools.cache  # one build per shape: the size tests share them (CI's pipeline job is tight)
def worst_case_file(  # noqa: PLR0913 - the file's counts and what it leaves out
    districts: int,
    with_record: int,
    *,
    schools: int = 0,
    outlooks: int = 0,
    records: bool = True,
    previous: bool = True,
) -> bytes:
    """Every district under a warning on both days, with a previous chance, the longest alert
    name, both base flags, the longest zone name and twelve districts next door with the
    highest indexes; ``with_record`` of them with a full 8-day record (an own base). With
    ``schools``, that many private schools (the highest indexes, as many zones as the file
    may hold, the longest, nearly all named with two digits, a full list of districts next
    door) naming ``outlooks`` distinct outlooks, each the longest one (an own base with a
    full record). ``records=False``: the file a pass makes with no record days
    (:attr:`serve.Fit.NO_RECORDS`), every day and outlook the longest without one;
    ``previous=False`` also with no previous chance (:attr:`serve.Fit.NO_PREVIOUS`)."""
    day = date(2026, 1, 7)
    at = datetime(2026, 1, 7, 1, 30, tzinfo=UTC)
    plain = _worst_day(at, own=False) if previous else _longest_bare(at, "districts")
    own = _worst_day(at, own=True) if records else plain
    top = tuple(range(districts - 13, districts))
    entries = tuple(
        DistrictForecast(
            district=i,
            time_zone=LONGEST_ZONE,
            neighbors=tuple(n for n in top if n != i)[:12],
            days=(own, own) if i < with_record else (plain, plain),
        )
        for i in range(districts)
    )
    table = tuple(
        _worst_day(at, own=True, minutes=30 + k)
        if records
        else _worst_day(at, own=False, of="private_schools", minutes=30 + k)
        if previous
        else _bare_outlook(at, k)
        for k in range(outlooks)
    )
    first = DEPLOYED_SCHOOLS - schools
    private = tuple(
        SchoolForecast(
            school=first + i,
            zone=i if i < MAX_ZONES else 10 + i % (MAX_ZONES - 10),
            neighbors=tuple(range(districts - MAX_SCHOOL_NEIGHBORS, districts)),
            days=(
                (outlooks - 1 - (2 * i) % outlooks, outlooks - 1 - (2 * i + 1) % outlooks)
                if i < outlooks
                else (outlooks - 1, outlooks - 2)
            ),
        )
        for i in range(schools)
    )
    return PredictionsFile(
        schema_version=1,
        generated_at=at,
        directory=DirectoryStamp(
            generated_on=date(2026, 10, 14), schools=DEPLOYED_SCHOOLS, districts=districts
        ),
        days=(day, day + timedelta(days=1)),
        districts=entries,
        schools=private,
        outlooks=table,
        zones=LONGEST_ZONES[: min(schools, MAX_ZONES)],
    ).to_json_bytes()


KEEPS_PREVIOUS: Final = 2000
"""Up to this many distinct private outlooks, the file with every previous chance and no
record days fits the worst case (above, the pass may leave the previous chances out)."""


def test_the_worst_case_file_fits_the_size_budget() -> None:
    """Every district and every private school of the committed model, and 5% more of each
    (a new edition's growth), under a warning on both days, each day and outlook the longest:

    * with no record days and no previous chances (:attr:`serve.Fit.NO_PREVIOUS`, the last
      step that keeps the private schools) and as many distinct private outlooks as the
      table holds, the file must fit whatever a learned file gives (it may give every
      district an own base with 8 live days, and count private schools over the districts
      around each one), so the size budget never takes a chance away;
    * with no record days (:attr:`serve.Fit.NO_RECORDS`) and every previous chance, the file
      fits with up to :data:`KEEPS_PREVIOUS` private outlooks;
    * with the committed model alone (every district it gives a record to with a full one)
      and as many outlooks, the whole file fits, so it keeps its record days.

    The table here holds :data:`MAX_OUTLOOKS`, the most it may hold however many parts make
    an outlook distinct (the weather flag of addendum e, E2, may double them, see
    ``test_a_pass_with_no_private_previous_chances_names_only_the_possible_outlooks``): a
    pass that would name more publishes the districts alone (:class:`serve.Fit`)."""
    model = artifact.load()
    districts = math.ceil(len(model.districts) * GROWTH)
    with_record = math.ceil(sum(1 for entry in model.districts.values() if entry.record) * GROWTH)
    schools = math.ceil(len(model.private) * GROWTH)
    assert len(model.districts) >= 18_000
    assert len(model.private) >= 22_000
    least = worst_case_file(
        districts, districts, schools=schools, outlooks=MAX_OUTLOOKS, records=False,
        previous=False,
    )  # fmt: skip
    made = PredictionsFile.from_json_bytes(least)
    assert len(made.outlooks) == MAX_OUTLOOKS
    # The table's outlooks must be distinct; a day said open is a little longer than each:
    # count that much more for every one.
    at = made.generated_at
    longest = len(_longest_bare(at, "private_schools").to_json_bytes())
    short = min(len(item.to_json_bytes()) for item in made.outlooks)
    assert 0 <= longest - short < 64
    least += b" " * (MAX_OUTLOOKS * (longest - short))
    bare = worst_case_file(
        districts, districts, schools=schools, outlooks=KEEPS_PREVIOUS, records=False
    )
    committed = worst_case_file(districts, with_record, schools=schools, outlooks=KEEPS_PREVIOUS)
    for worst in (least, bare, committed):
        packed = check_budget(worst, SETTINGS)
        assert len(worst) <= SETTINGS.budget_raw_bytes
        assert packed <= SETTINGS.budget_gzip_bytes
    with pytest.raises(DarkError, match="size"):
        check_budget(bare + b" " * (SETTINGS.budget_raw_bytes - len(bare) + 1), SETTINGS)


LONGEST_OUTLOOK: Final = OutlookReason(
    kind="outlook", points=-99, now=11, f=(1, 99.99, 119.99), like=(13, 13, 6), to=7, share=100,
    scope=2,
)  # fmt: skip
"""An outlook line of 107 bytes: with its base at 100 points (a byte longer than the worst
case's 57) and the chance at 1%, each day is as long as with the longest line (108 bytes,
docs/predict.md: ``points`` -100), and its sum adds up."""
OUTLOOK_FITS_SHARE: Final = 0.15
"""With an outlook line on this share of the district-days (both days) of the worst case and
every private school with no previous chance (:attr:`serve.Fit.NO_PREVIOUS`), the file keeps
every line; a night with lines on every district-day falls to :attr:`serve.Fit.NO_REASONS`."""


def with_outlook_lines(data: bytes, share: float) -> bytes:
    """The worst-case file with the longest outlook line, three weather reasons and the file's
    forecast time on both days of the first ``share`` of its districts (an outlook line comes
    only under no class or an advisory; the warning base kept here is longer than either)."""
    made = PredictionsFile.from_json_bytes(data)
    count = math.ceil(len(made.districts) * share)

    def lined(day: Forecast | Any) -> Forecast | Any:
        if not isinstance(day, Forecast):
            return day
        base = day.why.base.model_copy(update={"points": 100})
        return day.model_copy(
            update={
                "p_no_school": 0.01,
                "reasons": (Reason.WINTER_STORM, Reason.ICE, Reason.EXTREME_COLD),
                "why": Why(base=base, reasons=(LONGEST_OUTLOOK,)),
            }
        )

    entries = tuple(
        entry.model_copy(update={"days": tuple(lined(day) for day in entry.days)})
        if i < count
        else entry
        for i, entry in enumerate(made.districts)
    )
    return made.model_copy(
        update={"districts": entries, "forecast_at": made.generated_at - timedelta(minutes=21)}
    ).to_json_bytes()


def test_the_outlook_worst_case_falls_to_the_issued_alerts_only_chances_and_never_dark() -> None:
    """Spec-f s. 9's worst case with the private schools' table (which s. 9 predates): an
    outlook line on every district-day on both days does not fit at any step that keeps lines,
    so such a night falls to :attr:`serve.Fit.NO_REASONS` (every chance the issued-alerts-only
    one, no line, no ``forecast_at``: never a false or a dark chance), which fits (above). On
    up to :data:`OUTLOOK_FITS_SHARE` of the district-days, the lines are kept. The lead picks
    the size policy before ``on`` (docs/predict.md, Size)."""
    assert len(json.dumps(LONGEST_OUTLOOK.to_json_value(), separators=(",", ":"))) == 107
    model = artifact.load()
    districts = math.ceil(len(model.districts) * GROWTH)
    schools = math.ceil(len(model.private) * GROWTH)
    least = worst_case_file(
        districts, districts, schools=schools, outlooks=MAX_OUTLOOKS, records=False,
        previous=False,
    )  # fmt: skip
    # The least step that keeps the lines is over the budget with a line on every
    # district-day, so every step before it is too (each holds more: records, previous chances).
    assert len(with_outlook_lines(least, 1.0)) > SETTINGS.budget_raw_bytes
    # The districts alone with every line fit, but the pass keeps the private schools'
    # chances (every school gets a chance every day) and drops the lines instead.
    districts_only = worst_case_file(districts, districts, records=False, previous=False)
    assert len(with_outlook_lines(districts_only, 1.0)) <= SETTINGS.budget_raw_bytes
    # A night with lines on 15% of the district-days keeps them at NO_PREVIOUS.
    some = with_outlook_lines(least, OUTLOOK_FITS_SHARE)
    packed = check_budget(some, SETTINGS)
    assert len(some) <= SETTINGS.budget_raw_bytes
    assert packed <= SETTINGS.budget_gzip_bytes


# The night chart (option (iv), docs/predict.md "The night chart") --------------------------

LONGEST_NIGHT: Final = NightSnow(least=(99.0,) * 13, low=99.0, high=99.0, heavy=(10, 13))
"""The longest night the contract allows: 13 bars of four characters (the last at or under
``high``, 99, and none falling, so 99.0 throughout), a 2-digit span."""
NIGHTS_FIT: Final = 10_787
"""Districts with the longest night that fit the night cap at the worst case's base."""


def test_the_longest_nights_on_every_district_step_down_to_no_nights() -> None:
    """With the longest night on every district, the file with no record days is over the
    night cap (today's worst case), so such a pass publishes at NO_NIGHTS, which is today's
    NO_RECORDS file and fits; up to :data:`NIGHTS_FIT` districts fit with nights."""
    field = b',"night":' + LONGEST_NIGHT.to_json_bytes()
    assert len(field) == 124
    night_at = b',"night_at":"2026-01-07T00:00:00Z"'
    assert len(night_at) == 34
    model = artifact.load()
    districts = math.ceil(len(model.districts) * GROWTH)
    schools = math.ceil(len(model.private) * GROWTH)
    bare = worst_case_file(
        districts, districts, schools=schools, outlooks=KEEPS_PREVIOUS, records=False
    )
    every = len(bare) + districts * len(field) + len(night_at)
    assert every > SETTINGS.night_max_raw_bytes
    assert len(bare) <= SETTINGS.night_max_raw_bytes
    assert (SETTINGS.night_max_raw_bytes - len(bare) - len(night_at)) // len(field) == NIGHTS_FIT
    assert SETTINGS.night_max_raw_bytes <= SETTINGS.budget_raw_bytes


class _Sized:
    """A file of a given length (``fitted`` reads only its bytes)."""

    def __init__(self, size: int, fit: serve.Fit, nights: bool) -> None:
        self.size, self.fit, self.nights = size, fit, nights

    def to_json_bytes(self) -> bytes:
        return b"{" + b" " * (self.size - 2) + b"}"


def _ladder(
    sizes: Mapping[tuple[serve.Fit, bool], int], nights: Any, settings: Any = SETTINGS
) -> tuple[Any, list[Any]]:
    tried: list[Any] = []

    def make(fit: serve.Fit, carried: Any) -> Any:
        tried.append((fit, bool(carried)))
        return _Sized(sizes.get((fit, bool(carried)), 15_000_000), fit, bool(carried))

    # The sized stand-ins are no file: the strict parse a file with nights gets passes here.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(PredictionsFile, "from_json_bytes", lambda _data: None)
        made, _data, _packed, withheld = cli.fitted(make, settings, nights)
    return (made, withheld), tried


def _some_nights() -> Any:
    from snowlight.predict.night_serve import Nights  # noqa: PLC0415

    return Nights({(date(2026, 1, 7), 0): LONGEST_NIGHT}, datetime(2026, 1, 7, tzinfo=UTC))


def test_a_file_with_nights_over_the_cap_publishes_at_no_nights() -> None:
    sizes = {
        (serve.Fit.WHOLE, True): 17_651_973,
        (serve.Fit.NO_RECORDS, True): SETTINGS.night_max_raw_bytes + 1,
    }
    (made, withheld), tried = _ladder(sizes, _some_nights())
    assert tried == [
        (serve.Fit.WHOLE, True),
        (serve.Fit.NO_RECORDS, True),
        (serve.Fit.NO_NIGHTS, False),
    ]
    assert made.fit is serve.Fit.NO_NIGHTS
    assert withheld.line() == "chart: withheld, size"


def test_with_reasons_on_nights_never_cost_a_record_day(capsys: Any) -> None:
    """Critic r1/r2 S6, the lead's recorded order: with ``serve.reasons`` on, the reasons' text
    reads the record days, so the whole file without nights comes before any fit without
    them; a storm night's charts never change a reason's sentence."""
    reasons = SETTINGS.model_copy(update={"reasons": True})
    over = SETTINGS.night_max_raw_bytes + 1
    sizes = {(serve.Fit.WHOLE, True): over, (serve.Fit.WHOLE, False): 15_500_000}
    (made, withheld), tried = _ladder(sizes, _some_nights(), reasons)
    assert tried == [(serve.Fit.WHOLE, True), (serve.Fit.WHOLE, False)]
    assert made.fit is serve.Fit.WHOLE
    assert not made.nights
    assert withheld.line() == "chart: withheld, size"
    assert "published it with no night charts" in capsys.readouterr().err
    # Only when the whole file is over the budget even without nights do the record days go,
    # and then the nights come back on the next fit (nights did not cost them).
    sizes = {(serve.Fit.WHOLE, True): over, (serve.Fit.WHOLE, False): 17_000_000}
    (made, withheld), tried = _ladder(sizes, _some_nights(), reasons)
    assert tried == [
        (serve.Fit.WHOLE, True),
        (serve.Fit.WHOLE, False),
        (serve.Fit.NO_RECORDS, True),
    ]
    assert made.fit is serve.Fit.NO_RECORDS
    assert made.nights
    assert withheld.line() is None
    # Reasons off: record days show nowhere, and the chart keeps its place before them.
    (made, _withheld), tried = _ladder(sizes, _some_nights())
    assert tried == [(serve.Fit.WHOLE, True), (serve.Fit.NO_RECORDS, True)]
    assert made.nights


def test_with_reasons_on_a_table_error_skips_the_whole_file_without_nights() -> None:
    reasons = SETTINGS.model_copy(update={"reasons": True})
    tried: list[Any] = []

    def make(fit: serve.Fit, carried: Any) -> Any:
        tried.append((fit, bool(carried)))
        if fit in {serve.Fit.WHOLE, serve.Fit.NO_RECORDS}:
            raise serve.TableError("too many outlooks")
        return _Sized(15_000_000, fit, bool(carried))

    made: Any
    made, _data, _packed, _withheld = cli.fitted(make, reasons, _some_nights())
    assert tried == [
        (serve.Fit.WHOLE, True),
        (serve.Fit.NO_RECORDS, True),
        (serve.Fit.NO_PRIVATE_PREVIOUS, False),
    ]
    assert made.fit is serve.Fit.NO_PRIVATE_PREVIOUS


def test_with_no_nights_the_ladder_is_today_s() -> None:
    from snowlight.predict.night_serve import NO_NIGHTS  # noqa: PLC0415

    sizes = {(fit, False): 17_000_000 for fit in serve.Fit}
    sizes[(serve.Fit.NO_REASONS, False)] = 15_000_000
    (made, withheld), tried = _ladder(sizes, NO_NIGHTS)
    assert [fit for fit, _carried in tried] == [
        serve.Fit.WHOLE,
        serve.Fit.NO_RECORDS,
        serve.Fit.NO_PRIVATE_PREVIOUS,
        serve.Fit.NO_PREVIOUS,
        serve.Fit.NO_REASONS,
    ]
    assert made.fit is serve.Fit.NO_REASONS
    assert withheld.line() is None


def test_a_table_error_skips_no_nights() -> None:
    tried: list[serve.Fit] = []

    def make(fit: serve.Fit, carried: Any) -> Any:
        tried.append(fit)
        if fit in {serve.Fit.WHOLE, serve.Fit.NO_RECORDS}:
            raise serve.TableError("too many outlooks")
        return _Sized(15_000_000, fit, bool(carried))

    made: Any
    made, _data, _packed, withheld = cli.fitted(make, SETTINGS, _some_nights())
    assert tried == [serve.Fit.WHOLE, serve.Fit.NO_RECORDS, serve.Fit.NO_PRIVATE_PREVIOUS]
    assert made.fit is serve.Fit.NO_PRIVATE_PREVIOUS
    assert withheld.line() == "chart: withheld, size"


def test_no_nights_holds_what_no_records_holds() -> None:
    fit = serve.Fit.NO_NIGHTS
    same = serve.Fit.NO_RECORDS
    assert not fit.nights
    assert same.nights
    assert serve.Fit.WHOLE.nights
    assert (fit.records, fit.previous, fit.reasons, fit.private_previous, fit.schools) == (
        same.records, same.previous, same.reasons, same.private_previous, same.schools
    )  # fmt: skip
    assert not any(step.nights for step in list(serve.Fit)[3:])

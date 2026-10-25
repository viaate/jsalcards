"""The serving loop: the grid and heartbeat, retries after a dark pass, the day file, the alert
memory across a lost state, the hold, cancelled warnings, and the worst-case file size."""

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

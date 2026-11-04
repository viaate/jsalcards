"""The serving pass's live view (predict-next LIVE-READS: shadow). SYNTHETIC mornings only.

**Parity.** Each morning is driven pass by pass through the live reader's record
(:meth:`snowlight.live.morning.MorningLog.record`, the call :class:`~snowlight.live.ingest.
Ingest` makes after each pass), shipped at each :00 and :30 mark by the live shipper into the
in-memory D1 stand-in, and viewed 15 minutes after each mark. At every slot end the view's
proof equals :func:`snowlight.predict.call_time.proven` on that version's cut, and on the final
record (waived for a back clock jump only): two lists read whole, a dark carrier, refused reads
(401, 403, 429: no whole read), a stale empty, a voided morning, a pass gap, a restart (the
record cut to the last push, the shipper's memory lost), recovery after a refusal, and a back
clock jump.

**Wiring.** Each no-proof code; D1 raising and hanging; a view never raises; only
``read_cli.py`` and ``live_reads.py`` import ``call_time``; the view sends SELECTs only.
"""

import ast
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from predict.test_call_time import COVERAGE, LISTS, MARKETS, RULE, SETTINGS, STATS
from predict.test_frozen import FakeD1 as FrozenD1
from predict.test_live_read import stats_of
from snowlight.live import d1
from snowlight.live.d1 import Answer, D1StateStore, MorningReader, MorningShipper, Statement
from snowlight.live.morning import MorningDay, MorningLog, Read, slot_start
from snowlight.predict import live_reads
from snowlight.predict.call_time import Case, Cuts, Required, SlotProof, proven
from snowlight.predict.config import PIPELINE_ROOT
from snowlight.predict.live_labels import Directory, Morning, named_every_day, named_for
from snowlight.predict.live_reads import Code, Context, LiveReads, at_mark, mark_of

DAY = date(2026, 1, 14)
EAST = "America/New_York"
CENTRAL = "America/Chicago"
EAST_ID = "3600001"
CENTRAL_ID = "1700001"
WHOLE: Read = (10, 10, 0)
START = datetime(2026, 1, 14, 9, 0, tzinfo=UTC)
STOP = datetime(2026, 1, 14, 16, 30, tzinfo=UTC)
STEP = timedelta(minutes=5)
NEEDED = Required(LISTS)
RECENT = dict.fromkeys(LISTS, 1)


ENV = {"GITHUB_WORKFLOW": "live-read", "GITHUB_RUN_ID": "1001"}


@dataclass
class FakeD1(FrozenD1):
    """SYNTHETIC: the predict tests' D1 stand-in, keeping every statement sent."""

    sent: list[str] = field(default_factory=list)

    def run(self, database: str, statements: Sequence[Statement]) -> list[Answer]:
        self.sent.extend(sql for sql, _ in statements)
        return super().run(database, statements)

    @property
    def db(self) -> Any:
        return next(iter(self.dbs.values()))


@dataclass
class Clock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


def _store(api: FakeD1, clock: Clock) -> D1StateStore:
    return D1StateStore(api, ENV, clock)


EMPTY_BEFORE = MorningDay(DAY - timedelta(days=1))


def context(
    needed: Required = NEEDED,
    *,
    warning: bool = False,
    before: MorningDay | None = EMPTY_BEFORE,
    before_final: bool = True,
) -> Context:
    """SYNTHETIC: two districts (Eastern and Central) whose required lists are ``needed``;
    ``before``: the export's D-1 record (``None``: none), final when ``before_final`` (the
    export records a pass of D)."""
    return Context(
        day=DAY,
        content="synthetic",
        settings=SETTINGS,
        rule=RULE,
        coverage=COVERAGE,
        inputs=SimpleNamespace(stats=STATS, recent=RECENT),
        cases=(Case(EAST_ID, EAST, needed, warning), Case(CENTRAL_ID, CENTRAL, needed, warning)),
        audience={},
        market_of=MARKETS,
        station_stats=stats_of(*MARKETS),
        prefix="v1",
        before=before,
        before_final=before_final,
    )


def reference(
    data: bytes, case: Case, *, warning: bool = False, before: MorningDay | None = None
) -> list[SlotProof]:
    """``call_time.proven`` on the record ``data`` (built here, apart from the view's code),
    with D-1's record ``before`` read as the learning step's source reads it."""
    found = MorningDay.from_bytes(data)
    morning = Morning(
        day=DAY, slots={slot_start(DAY, k): v for k, v in found.slots.items()}, audience={},
        market_of=MARKETS, stats=stats_of(*MARKETS), prefix="v1",
        named_before=named_for(before, DAY),
    )  # fmt: skip
    cuts = Cuts(morning, RULE, STATS, frozenset(), SETTINGS)
    return proven(
        cuts, case.leaid, case.needed, zone=case.zone, storm=True, warning=warning,
        recent=RECENT,
        every_before=named_every_day(before.slots.values() if before is not None else ()),
    )  # fmt: skip


type Reads = Callable[[datetime], Mapping[str, Read] | None]
"""Each pass's whole reads by its start (``None``: no pass then)."""


def every_pass(_at: datetime) -> Mapping[str, Read]:
    return dict.fromkeys(LISTS, WHOLE)


@dataclass
class Morningful:
    """SYNTHETIC: one morning driven pass by pass, shipped and viewed."""

    tmp: Path
    reads: Reads = every_pass
    by: Callable[[datetime], Mapping[str, Sequence[str]]] = lambda _at: {}
    stale: Callable[[datetime], Sequence[str]] = lambda _at: ()
    needed: Required = NEEDED
    warning: bool = False
    restart_at: datetime | None = None
    """The runner is lost just before this pass; its successor pulls the state of the last
    push (the :30 mark before) and ships from a fresh memory."""
    jump: Mapping[datetime, datetime] = field(default_factory=dict)
    """Passes whose clock reads another time (a clock that went back)."""
    yesterday: MorningDay | None = field(default_factory=lambda: EMPTY_BEFORE)
    """D-1's record in the export (``None``: none)."""
    shipped_yesterday: MorningDay | None = None
    """D-1's record shipped before the morning (``None``: none shipped)."""
    shipped_yesterday_at: datetime = START
    """When D-1's record was shipped (before 00:00 UTC of D: a version that is not final)."""
    yesterday_parts_lost: bool = False
    """The shipped D-1 version's parts are gone from the database."""
    yesterday_final: bool = True
    """The export records a pass of D (its D-1 is final)."""
    expected_before: MorningDay | None = None
    """D-1's record the view must read (``None``: the shipped one, else the export's)."""
    view: LiveReads | None = None
    api: FakeD1 = field(default_factory=FakeD1)
    seen: list[tuple[datetime, dict[str, SlotProof] | None, bytes]] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    def run(self) -> bytes:
        folder = self.tmp / "run1"
        clock = Clock(START)
        store = _store(self.api, clock)
        store.take(folder)
        shipper = MorningShipper(store)
        view = LiveReads(MorningReader(self.api), lambda _day: self.context(), self.lines.append)
        self.view = view
        self._ship_yesterday(folder, shipper, clock)
        pushed: Path | None = None
        shipped: bytes | None = None
        at = START
        runs = 1
        while at <= STOP:
            if self.restart_at is not None and at == self.restart_at:
                assert pushed is not None
                runs += 1
                folder = self.tmp / f"run{runs}"
                shutil.copytree(pushed, folder)
                store = _store(self.api, clock)
                store.take(folder)
                shipper = MorningShipper(store)  # its memory is lost
            reads = self.reads(at)
            if reads is not None:
                moment = self.jump.get(at, at) + timedelta(seconds=30)
                MorningLog(folder / "morning").record(
                    moment, shown="v1", reads=reads, unknown=(), named={}, health=0.95,
                    by={s: d for s, d in self.by(at).items() if s in reads},
                    stale=[s for s in self.stale(at) if s in reads],
                )  # fmt: skip
            clock.now = at + timedelta(minutes=1)
            if at.minute % 30 == 0:
                path = MorningLog(folder / "morning").path(DAY)
                if path.is_file():
                    data = path.read_bytes()
                    through = MorningDay.from_bytes(data).through
                    assert through is not None
                    found = shipper.ship(
                        folder, DAY, data, through, deadline=clock.now + timedelta(minutes=1)
                    )
                    if found.outcome in ("shipped", "same"):
                        shipped = data
                # the push after the ship (what a successor would pull)
                pushed = self.tmp / f"pushed{runs}"
                shutil.rmtree(pushed, ignore_errors=True)
                shutil.copytree(folder, pushed)
            if (at - live_reads.LAG).minute % 30 == 0 and at - live_reads.LAG >= START:
                now = at + timedelta(minutes=1)
                found_at = view.step(now, "synthetic")
                if found_at is not None:
                    assert shipped is not None
                self.seen.append((mark_of(now), found_at, shipped or b""))
            at += STEP
        return MorningLog(folder / "morning").path(DAY).read_bytes()

    def _ship_yesterday(self, folder: Path, shipper: MorningShipper, clock: Clock) -> None:
        """D-1's record shipped before the morning, when the test sets one."""
        if self.shipped_yesterday is None:
            return
        old = self.shipped_yesterday.to_bytes()
        log = MorningLog(folder / "morning")
        log.root.mkdir(parents=True, exist_ok=True)
        log.path(self.shipped_yesterday.day).write_bytes(old)
        assert self.shipped_yesterday.through is not None
        now, clock.now = clock.now, self.shipped_yesterday_at
        found = shipper.ship(
            folder, self.shipped_yesterday.day, old, self.shipped_yesterday.through,
            deadline=clock.now + timedelta(minutes=1),
        )  # fmt: skip
        assert found.outcome == "shipped"
        clock.now = now
        if self.yesterday_parts_lost:
            import hashlib  # noqa: PLC0415

            sha = hashlib.sha256(old).hexdigest()
            self.api.db.execute("DELETE FROM morning_parts WHERE sha256 = ?", (sha,))
            self.api.db.commit()

    def context(self) -> Context:
        return context(
            self.needed, warning=self.warning, before=self.yesterday,
            before_final=self.yesterday_final,
        )  # fmt: skip

    @property
    def before(self) -> MorningDay | None:
        """D-1's record the view reads: the one the test names, else the shipped one, else
        the export's."""
        return self.expected_before or self.shipped_yesterday or self.yesterday


def parity(morning: Morningful, *, final: bool = True) -> list[dict[str, SlotProof | None]]:
    """Every view equals ``proven`` on its version's cut (and on the final record, when
    ``final``); the views' proofs by district."""
    last = morning.run()
    cases = morning.context().cases
    views: list[dict[str, SlotProof | None]] = []
    for s, found_at, version in morning.seen:
        if found_at is None:
            views.append({})
            continue
        here: dict[str, SlotProof | None] = {}
        for case in cases:
            mine = found_at.get(case.leaid)
            made = reference(version, case, warning=morning.warning, before=morning.before)
            cut = at_mark(made, DAY, case.zone, s)
            assert mine == cut, (s, case.leaid)
            if final:
                whole = reference(last, case, warning=morning.warning, before=morning.before)
                assert mine == at_mark(whole, DAY, case.zone, s), (s, case.leaid)
            here[case.leaid] = mine
        views.append(here)
    return views


def p_star_at(views: Sequence[Mapping[str, SlotProof | None]], leaid: str) -> list[int | None]:
    found = []
    for view in views:
        item = view.get(leaid)
        found.append(None if item is None else item.p_star)
    return found


def test_two_lists_read_whole_prove_both_districts_at_every_slot_end(tmp_path: Path) -> None:
    morning = Morningful(tmp_path)
    views = parity(morning)
    assert [s.strftime("%H:%M") for s, *_ in morning.seen][::6] == ["09:00", "12:00", "15:00"]
    assert views[0] == {}  # 09:00Z: the record holds no slot before it (stale)
    east = p_star_at(views, EAST_ID)
    # 05:30 EST is 10:30Z: no slot end before it; then each slot end proves its own end, and
    # the 10:00 row holds 09:30's
    assert east == [None, None, None, 330, 360, 390, 420, 450, 480, 510, 540, 570, 600, 600, 600]
    central = p_star_at(views, CENTRAL_ID)
    assert central == [None] * 5 + [330, 360, 390, 420, 450, 480, 510, 540, 570, 600]
    assert any("live reads (off) 2026-01-14" in line for line in morning.lines)
    assert all(line.count(EAST_ID) == 0 for line in morning.lines)


def test_a_dark_carrier_blocks_proof(tmp_path: Path) -> None:
    needed = Required(("paper", *LISTS), dark=("paper",))
    views = parity(Morningful(tmp_path, needed=needed))
    assert set(p_star_at(views, EAST_ID)) == {None}


def refused_between(first: str, last: str, source: str = "tv") -> Reads:
    """SYNTHETIC: ``source`` refused (a 401, 403 or 429: no whole read) from ``first`` to
    ``last`` UTC, then read again."""

    def reads(at: datetime) -> Mapping[str, Read]:
        found = dict.fromkeys(LISTS, WHOLE)
        if time.fromisoformat(first) <= at.time() <= time.fromisoformat(last):
            del found[source]
        return found

    return reads


def test_refused_reads_hold_and_proof_recovers_after(tmp_path: Path) -> None:
    views = parity(Morningful(tmp_path, reads=refused_between("12:00", "12:55")))
    east = p_star_at(views, EAST_ID)
    # tv refused from 07:00 to 08:00 EST: P* holds at 07:00, then moves again
    assert east[6:10] == [420, 420, 420, 510]
    assert east == sorted(east, key=lambda p: -1 if p is None else p)


def test_a_stale_empty_proves_nothing_for_its_list(tmp_path: Path) -> None:
    def reads(at: datetime) -> Mapping[str, Read]:
        found = dict.fromkeys(LISTS, WHOLE)
        if at.time() >= time(12):
            found["tv"] = (0, 0, 0)
        return found

    def stale(at: datetime) -> Sequence[str]:
        return ("tv",) if at.time() >= time(12) else ()

    views = parity(Morningful(tmp_path, reads=reads, stale=stale))
    east = p_star_at(views, EAST_ID)
    assert east[-1] == 420


def test_a_voided_morning_ends_proof(tmp_path: Path) -> None:
    def by(at: datetime) -> Mapping[str, Sequence[str]]:
        return {"radio": ["3699999"]} if at.time() >= time(12) else {}

    views = parity(Morningful(tmp_path, by=by, warning=True))
    ended = [None if v.get(EAST_ID) is None else v[EAST_ID].ended for v in views]  # type: ignore[union-attr]
    assert "void" in ended


def test_a_pass_gap_is_stale_and_proof_holds_over_it(tmp_path: Path) -> None:
    def reads(at: datetime) -> Mapping[str, Read] | None:
        return None if time(12) <= at.time() < time(12, 30) else every_pass(at)

    morning = Morningful(tmp_path, reads=reads)
    views = parity(morning)
    # s 12:00Z and 12:30Z: no pass reached s: stale (no proof those passes)
    assert views[6] == {}
    assert views[7] == {}
    assert any("no proof: stale" in line for line in morning.lines)
    east = p_star_at(views, EAST_ID)
    assert east[5] == 390
    assert east[8] == 480  # 13:00Z: the slot after the gap qualifies again


def test_a_restart_cut_to_the_last_push_with_its_memory_lost(tmp_path: Path) -> None:
    restart = datetime(2026, 1, 14, 12, 10, tzinfo=UTC)
    morning = Morningful(tmp_path, restart_at=restart)
    views = parity(morning)
    assert p_star_at(views, EAST_ID)[3:13] == [330, 360, 390, 420, 450, 480, 510, 540, 570, 600]
    heads = morning.api.db.execute("SELECT epoch FROM morning_head").fetchall()
    assert heads == [(2,)]


def test_a_back_clock_jump_keeps_version_parity(tmp_path: Path) -> None:
    # the 13:10Z pass's clock reads 12:40Z and its tv read holds an unplaced row: the 12:30Z
    # slot changes after it was shipped and viewed (history changed: final equality waived)
    jumped = datetime(2026, 1, 14, 13, 10, tzinfo=UTC)

    def reads(at: datetime) -> Mapping[str, Read]:
        found = dict.fromkeys(LISTS, WHOLE)
        if at == jumped:
            found["tv"] = (10, 9, 0)
        return found

    morning = Morningful(
        tmp_path, reads=reads, jump={jumped: datetime(2026, 1, 14, 12, 40, tzinfo=UTC)}
    )
    views = parity(morning, final=False)
    east = p_star_at(views, EAST_ID)
    assert east[8] == 480  # s 13:00Z, viewed on the version shipped before the jump
    whole = reference(MorningLog(tmp_path / "run1" / "morning").path(DAY).read_bytes(),
                      morning.context().cases[0])  # fmt: skip
    later = at_mark(whole, DAY, EAST, datetime(2026, 1, 14, 13, 0, tzinfo=UTC))
    assert later is not None
    assert later.p_star == 450


# --- wiring -------------------------------------------------------------------------------------


@dataclass
class StubChannel:
    """SYNTHETIC: a channel whose answers a test sets."""

    heads_of: Callable[[], dict[date, d1.MorningHead]]
    parts_of: Callable[[str, int | None], list[str] | None] = lambda _sha, _n: None
    deadline: float | None = None

    def heads(self, days: Sequence[date]) -> dict[date, d1.MorningHead]:  # noqa: ARG002
        return self.heads_of()

    def parts(self, sha: str, count: int | None) -> list[str] | None:
        return self.parts_of(sha, count)


NOW = datetime(2026, 1, 14, 13, 16, tzinfo=UTC)


def _shipped(tmp_path: Path, through: datetime = NOW) -> tuple[bytes, d1.MorningHead]:
    log = MorningLog(tmp_path / "morning")
    at = START
    while at <= through:
        log.record(at, shown="v1", reads=every_pass(at), unknown=(), named={}, health=0.95)
        at += STEP
    data = log.path(DAY).read_bytes()
    texts = d1.pack_morning(data)
    import hashlib  # noqa: PLC0415

    head = d1.MorningHead(
        day=DAY, sha256=hashlib.sha256(data).hexdigest(), parts=len(texts), bytes=len(data),
        through=MorningDay.from_bytes(data).through or through, epoch=1, shipped_at=through,
        prev_sha256=None,
    )  # fmt: skip
    return data, head


def _view(channel: Any, made: Context | None = None) -> tuple[LiveReads, list[str]]:
    lines: list[str] = []
    return LiveReads(channel, lambda _day: made, lines.append), lines


def test_each_no_proof_code_is_one_line_a_run(tmp_path: Path) -> None:
    data, head = _shipped(tmp_path)
    texts = d1.pack_morning(data)
    ok = StubChannel(lambda: {DAY: head}, lambda _sha, _n: texts)
    old_data, old_head = _shipped(tmp_path / "old", through=NOW - timedelta(hours=1))
    old_texts = d1.pack_morning(old_data)
    ahead = replace(head, through=NOW + timedelta(hours=1))
    cut = [texts[0][:-8]]
    cases: list[tuple[Code, Any, Context | None]] = [
        (Code.NONE, ok, None),
        (Code.D1, None, context()),
        (Code.MISSING, StubChannel(dict), context()),
        (Code.MISMATCHED, StubChannel(lambda: {DAY: ahead}), context()),
        (Code.UNREADABLE, StubChannel(lambda: {DAY: head}), context()),
        (Code.UNREADABLE, StubChannel(lambda: {DAY: head}, lambda _s, _n: cut), context()),
        (Code.STALE, StubChannel(lambda: {DAY: old_head}, lambda _s, _n: old_texts), context()),
    ]  # fmt: skip
    for code, channel, made in cases:
        view, lines = _view(channel, made)
        assert view.step(NOW, "synthetic") is None
        assert view.step(NOW + timedelta(minutes=5), "synthetic") is None
        assert dict(view.codes) == {code.value: 2}, code
        assert len(lines) == 1
        assert lines[0].endswith(f"no proof: {code.value}")
    # another directory's content
    view, lines = _view(ok, context())
    assert view.step(NOW, "another") is None
    assert dict(view.codes) == {"mismatched": 1}
    # the slot before s absent: stale (a version whose through reaches s from a later pass)
    gap = MorningDay.from_bytes(data)
    gap.slots.pop("12:30")
    gapped = gap.to_bytes()
    import hashlib  # noqa: PLC0415

    sha = hashlib.sha256(gapped).hexdigest()
    channel = StubChannel(
        lambda: {DAY: replace(head, sha256=sha)}, lambda _s, _n: d1.pack_morning(gapped)
    )
    view, lines = _view(channel, context())
    assert view.step(NOW, "synthetic") is None
    assert dict(view.codes) == {"stale": 1}
    # a whole version proves; the same (version, s) prints one line
    view, lines = _view(ok, context())
    assert view.step(NOW, "synthetic") is not None
    assert view.step(NOW + timedelta(minutes=5), "synthetic") is not None
    assert len(lines) == 1
    assert "version " in lines[0]
    assert view.codes == {}


def test_d1_raising_or_hanging_is_d1_or_late_and_never_raises(tmp_path: Path) -> None:
    _data, head = _shipped(tmp_path)

    def raising() -> dict[date, d1.MorningHead]:
        raise d1.D1Error("query: HTTP 500")

    view, _lines = _view(StubChannel(raising), context())
    assert view.step(NOW, "synthetic") is None
    assert dict(view.codes) == {"d1": 1}
    # a hang: the request's own bound ran past the pass's 10 s
    clock = {"now": 0.0}

    def hanging() -> dict[date, d1.MorningHead]:
        clock["now"] += 11.0
        raise d1.D1Error("query: out of time")

    lines: list[str] = []
    view = LiveReads(StubChannel(hanging), lambda _day: context(), lines.append,
                     monotonic=lambda: clock["now"])  # fmt: skip
    assert view.step(NOW, "synthetic") is None
    assert dict(view.codes) == {"late": 1}

    # anything else is coded none, never raised
    def broken() -> dict[date, d1.MorningHead]:
        raise RuntimeError("synthetic")

    view, lines = _view(StubChannel(broken), context())
    assert view.step(NOW, "synthetic") is None
    assert lines == ["live reads (off) 2026-01-14 13:00Z: no proof: none (RuntimeError)"]
    # outside the read band: nothing at all
    view, lines = _view(StubChannel(broken), context())
    assert view.step(datetime(2026, 1, 14, 22, 0, tzinfo=UTC), "synthetic") is None
    assert lines == []
    assert view.codes == {}
    assert head.parts >= 1


def test_the_view_sends_selects_of_the_two_tables_only(tmp_path: Path) -> None:
    morning = Morningful(tmp_path)
    morning.run()
    sent = [sql for sql in morning.api.sent if sql in d1.MORNING_READS]
    assert sent
    reader_statements = {
        sql
        for sql in morning.api.sent
        if sql.startswith("SELECT") and ("morning_head" in sql or "morning_parts" in sql)
    }
    assert reader_statements <= d1.MORNING_READS
    source = (PIPELINE_ROOT / "snowlight" / "predict" / "live_reads.py").read_text()
    assert "INSERT" not in source
    assert "DELETE" not in source
    assert "UPDATE" not in source


def test_only_read_cli_and_live_reads_import_call_time() -> None:
    importers = set()
    for path in sorted((PIPELINE_ROOT / "snowlight").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            if "snowlight.predict.call_time" in names:
                importers.add(path.name)
    assert sorted(importers) == ["live_reads.py", "read_cli.py"]


def test_the_mark_is_15_minutes_back_on_the_half_hour() -> None:
    assert mark_of(datetime(2026, 1, 14, 13, 16, tzinfo=UTC)) == datetime(
        2026, 1, 14, 13, 0, tzinfo=UTC
    )
    assert mark_of(datetime(2026, 1, 14, 13, 14, tzinfo=UTC)) == datetime(
        2026, 1, 14, 12, 30, tzinfo=UTC
    )
    assert mark_of(datetime(2026, 1, 14, 13, 45, tzinfo=UTC)) == datetime(
        2026, 1, 14, 13, 30, tzinfo=UTC
    )


@pytest.mark.parametrize("hours", [0, 1])
def test_no_class_morning_is_none(hours: int) -> None:
    view, lines = _view(StubChannel(dict), None)
    assert view.step(NOW + timedelta(hours=hours), "synthetic") is None
    assert dict(view.codes) == {"none": 1}
    assert len(lines) == 1
    assert view.context_times == []  # a quiet day's no is not a build


def test_a_view_of_proofs_moves_no_served_or_frozen_byte(tmp_path: Path) -> None:
    from predict.test_frozen import _passes, adjusting_pass  # noqa: PLC0415
    from snowlight.predict import cli  # noqa: PLC0415
    from snowlight.predict.config import (  # noqa: PLC0415
        LIVE_SCORE_SHA256,
        PredictConfig,
        live_score_sha256,
    )

    calls: list[datetime] = []

    class Proofs:
        """SYNTHETIC: a view that holds a proof for every pass."""

        def step(self, now: datetime, _content: str | None) -> dict[str, SlotProof]:
            calls.append(now)
            return {EAST_ID: SlotProof(450, 450)}

    class Broken:
        def step(self, _now: datetime, _content: str | None) -> dict[str, SlotProof]:
            raise RuntimeError("synthetic")

    def with_view(view: Any) -> Callable[..., cli.Pass]:
        def make(folder: Path | None, clock: Any, host: Any) -> cli.Pass:
            run = adjusting_pass(folder, clock, host)
            run.live_reads = view
            return run

        return make

    off = _passes(adjusting_pass, tmp_path / "off")
    on = _passes(with_view(Proofs()), tmp_path / "on")
    broken = _passes(with_view(Broken()), tmp_path / "broken")
    assert on == off == broken
    assert calls
    for name in ("on", "broken"):
        theirs = {
            p.relative_to(tmp_path / name): p.read_bytes()
            for p in (tmp_path / name).rglob("*")
            if p.is_file()
        }
        mine = {
            p.relative_to(tmp_path / "off"): p.read_bytes()
            for p in (tmp_path / "off").rglob("*")
            if p.is_file()
        }
        assert theirs == mine
        assert mine
    shipped = PredictConfig.load()
    assert shipped.serve.live_reads is True
    assert live_score_sha256(shipped) == LIVE_SCORE_SHA256


def test_only_the_serving_commands_take_the_view() -> None:
    from snowlight.cli import build_parser  # noqa: PLC0415

    parser = build_parser()
    for argv, view in (
        (["predict", "run", "--until", "+5m"], True),
        (["predict", "once"], True),
        (["predict", "learn"], False),
        (["predict", "read-labels"], False),
    ):
        assert getattr(parser.parse_args(argv), "live_view", False) is view


# --- D-1, the version before, history changed ---------------------------------------------------


YESTERDAY_EVENING = datetime(2026, 1, 13, 23, 0, 30, tzinfo=UTC)


def _yesterday(
    named: Mapping[str, Mapping[str, Sequence[str]]], log_at: datetime = YESTERDAY_EVENING
) -> MorningDay:
    """SYNTHETIC: a D-1 record whose pass at ``log_at`` (its last) named districts (for D, or
    ``*``)."""
    found = MorningDay(DAY - timedelta(days=1))
    from snowlight.live.morning import Slot, slot_of  # noqa: PLC0415

    slot = found.slots.setdefault(slot_of(log_at), Slot())
    slot.shown.add("v1")
    for leaid, days in named.items():
        into = slot.named.setdefault(leaid, {})
        for when, kinds in days.items():
            into.setdefault(when, set()).update(kinds)
    found.through = log_at
    return MorningDay.from_bytes(found.to_bytes())


def test_the_shared_d_minus_1_rules() -> None:
    before = _yesterday({EAST_ID: {DAY.isoformat(): ["closed"]}, CENTRAL_ID: {"*": ["closed"]},
                         "3600002": {"2026-01-20": ["closed"]}})  # fmt: skip
    assert named_for(before, DAY) == {EAST_ID: frozenset({"closed"})}
    assert named_every_day(before.slots.values()) == frozenset({CENTRAL_ID})
    assert named_for(None, DAY) == {}
    assert named_every_day(()) == frozenset()
    # the learning step's source, read-labels and the view all call the one implementation
    for name in ("live_labels.py", "read_cli.py", "live_reads.py", "call_time.py"):
        text = (PIPELINE_ROOT / "snowlight" / "predict" / name).read_text(encoding="utf-8")
        assert text.count("if EVERY_DAY in named") == (name == "live_labels.py"), name
    labels = (PIPELINE_ROOT / "snowlight" / "predict" / "live_labels.py").read_text()
    assert "named_before=named_for(before, day)" in labels


@pytest.mark.parametrize(
    ("named", "ended"),
    [({EAST_ID: {DAY.isoformat(): ["closed"]}}, "named"), ({EAST_ID: {"*": ["closed"]}}, "named")],
    ids=["d-1 names d", "d-1 names every day"],
)
def test_a_night_before_call_ends_proof_as_named(
    tmp_path: Path, named: Mapping[str, Mapping[str, Sequence[str]]], ended: str
) -> None:
    morning = Morningful(tmp_path, yesterday=_yesterday(named))
    views = parity(morning)
    east = [v.get(EAST_ID) for v in views if v]
    assert east
    assert {item.ended for item in east if item is not None} == {ended}
    central = p_star_at(views, CENTRAL_ID)
    assert central[-1] == 600  # the other district proves as before


def test_the_shipped_d_minus_1_wins_over_the_exports(tmp_path: Path) -> None:
    shipped = _yesterday({EAST_ID: {DAY.isoformat(): ["closed"]}})
    morning = Morningful(tmp_path, yesterday=EMPTY_BEFORE, shipped_yesterday=shipped)
    views = parity(morning)
    assert {v[EAST_ID].ended for v in views if v.get(EAST_ID) is not None} == {"named"}  # type: ignore[union-attr]
    # the export's D-1 alone (no naming) proves the district
    plain = parity(Morningful(tmp_path / "plain"))
    assert p_star_at(plain, EAST_ID)[-1] == 600


def test_no_d_minus_1_record_is_missing(tmp_path: Path) -> None:
    morning = Morningful(tmp_path, yesterday=None)
    views = parity(morning)
    assert all(view == {} for view in views)
    assert morning.view is not None
    assert set(morning.view.codes) == {"missing"}


NOT_FINAL_AT = datetime(2026, 1, 13, 21, 0, 40, tzinfo=UTC)
"""The 21:00Z mark of D-1: its last ship before the final one after 00:00 UTC of D."""


@pytest.mark.parametrize("export_final", [True, False], ids=["export final", "export not final"])
def test_a_shipped_d_minus_1_older_than_the_exports_gives_way(
    tmp_path: Path, export_final: bool
) -> None:
    """The final ship of D-1 never landed: the head is D-1's 21:00Z version, which misses the
    evening's naming of EAST for D. The export's newer D-1 (by ``through``) is read: final, it
    ends EAST's proof as named; not final either, no proof at all (``stale``)."""
    early = _yesterday({}, datetime(2026, 1, 13, 20, 55, 30, tzinfo=UTC))
    final = _yesterday({EAST_ID: {DAY.isoformat(): ["closed"]}})
    morning = Morningful(
        tmp_path, yesterday=final, yesterday_final=export_final, shipped_yesterday=early,
        shipped_yesterday_at=NOT_FINAL_AT, expected_before=final,
    )  # fmt: skip
    views = parity(morning)
    assert morning.view is not None
    if export_final:
        east = [v[EAST_ID] for v in views if v.get(EAST_ID) is not None]
        assert east
        assert {item.ended for item in east if item is not None} == {"named"}
        assert p_star_at(views, CENTRAL_ID)[-1] == 600
        assert set(morning.view.codes) <= {"stale"}  # the 09:00Z mark: no 08:30 slot yet
        assert not any("d-1 not final" in line for line in morning.lines)
    else:
        assert all(view == {} for view in views)
        assert set(morning.view.codes) == {"stale"}
        assert any(line.endswith("no proof: stale (d-1 not final)") for line in morning.lines)


def test_a_newer_shipped_d_minus_1_that_does_not_read_gives_no_proof(tmp_path: Path) -> None:
    """The head of D-1 is newer than the export's D-1 but its parts are gone: no proof, coded
    ``unreadable``, never the older export (which would prove EAST)."""
    shipped = _yesterday({EAST_ID: {DAY.isoformat(): ["closed"]}})
    older = _yesterday({}, datetime(2026, 1, 13, 20, 55, 30, tzinfo=UTC))
    morning = Morningful(
        tmp_path, yesterday=older, yesterday_final=False, shipped_yesterday=shipped,
        yesterday_parts_lost=True,
    )  # fmt: skip
    views = parity(morning)
    assert all(view == {} for view in views)
    assert morning.view is not None
    assert set(morning.view.codes) == {"unreadable"}


def _head_of(record: MorningDay, shipped_at: datetime) -> tuple[d1.MorningHead, list[str]]:
    import hashlib  # noqa: PLC0415

    data = record.to_bytes()
    texts = d1.pack_morning(data)
    assert record.through is not None
    head = d1.MorningHead(
        day=record.day, sha256=hashlib.sha256(data).hexdigest(), parts=len(texts),
        bytes=len(data), through=record.through, epoch=1, shipped_at=shipped_at,
        prev_sha256=None,
    )  # fmt: skip
    return head, texts


AFTER_MIDNIGHT = datetime(2026, 1, 14, 0, 0, 40, tzinfo=UTC)


@pytest.mark.parametrize(
    ("shipped", "shipped_at", "readable", "export", "export_final", "expected"),
    [
        ("evening", AFTER_MIDNIGHT, True, "early", False, "shipped"),
        ("evening", NOT_FINAL_AT, True, "early", False, "stale"),
        ("early", NOT_FINAL_AT, True, "evening", True, "export"),
        ("early", NOT_FINAL_AT, True, "evening", False, "stale"),
        ("evening", NOT_FINAL_AT, True, "evening", True, "shipped"),  # a tie: the shipped one
        ("evening", AFTER_MIDNIGHT, False, "early", True, "unreadable"),
        ("early", AFTER_MIDNIGHT, False, "evening", True, "export"),  # never read
        (None, None, True, "evening", True, "export"),
        (None, None, True, "evening", False, "stale"),
        ("evening", AFTER_MIDNIGHT, True, None, False, "shipped"),
        ("evening", NOT_FINAL_AT, True, None, False, "stale"),
        (None, None, True, None, False, "missing"),
    ],
)
def test_d_minus_1_is_chosen_by_its_through_and_proves_only_when_final(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    shipped: str | None,
    shipped_at: datetime | None,
    readable: bool,
    export: str | None,
    export_final: bool,
    expected: str,
) -> None:
    records = {
        "early": _yesterday({}, datetime(2026, 1, 13, 20, 55, 30, tzinfo=UTC)),
        "evening": _yesterday({}, datetime(2026, 1, 13, 23, 55, 30, tzinfo=UTC)),
    }
    data, head = _shipped(tmp_path)
    texts = d1.pack_morning(data)
    heads = {DAY: head}
    parts = {head.sha256: texts}
    if shipped is not None:
        assert shipped_at is not None
        before_head, before_texts = _head_of(records[shipped], shipped_at)
        heads[before_head.day] = before_head
        if readable:
            parts[before_head.sha256] = before_texts
    asked: list[str] = []

    def parts_of(sha: str, _count: int | None) -> list[str] | None:
        asked.append(sha)
        return parts.get(sha)

    made = context(before=None if export is None else records[export], before_final=export_final)
    view, lines = _view(StubChannel(lambda: heads, parts_of), made)
    found = view.step(NOW, "synthetic")
    if expected in ("shipped", "export"):
        assert found is not None
        assert view.codes == {}
        if expected == "export":
            assert asked == [head.sha256]  # the older shipped D-1 is never read
    else:
        assert found is None
        assert dict(view.codes) == {expected: 1}
        assert "no proof: " + expected in lines[-1]


def test_a_fallback_to_the_version_before_is_kept_under_its_own_sha(tmp_path: Path) -> None:
    """A reader racing the shipper's delete reads the version before; the line names that
    version and its through, and the next pass reads the head's parts again (never a false
    ``stale`` from the old record kept under the new sha)."""
    import hashlib  # noqa: PLC0415

    old_data, _old_head = _shipped(tmp_path / "old", through=NOW)
    new_data, _new_head = _shipped(tmp_path / "new", through=NOW + timedelta(minutes=24))
    old_sha = hashlib.sha256(old_data).hexdigest()
    new_sha = hashlib.sha256(new_data).hexdigest()
    head = d1.MorningHead(
        day=DAY, sha256=new_sha, parts=1, bytes=len(new_data),
        through=MorningDay.from_bytes(new_data).through or NOW, epoch=1, shipped_at=NOW,
        prev_sha256=old_sha,
    )  # fmt: skip
    whole = {"yes": False}

    def parts(sha: str, _count: int | None) -> list[str] | None:
        if sha == old_sha:
            return d1.pack_morning(old_data)
        return d1.pack_morning(new_data) if whole["yes"] else None

    view, lines = _view(StubChannel(lambda: {DAY: head}, parts), context())
    first = NOW + timedelta(minutes=25)  # s 13:00Z: the old version reaches it
    assert view.step(first, "synthetic") is not None
    assert f"version {old_sha[:12]} (through 13:15Z)" in lines[-1]
    whole["yes"] = True
    later = NOW + timedelta(minutes=45)  # s 13:30Z: only the new version reaches it
    assert view.step(later, "synthetic") is not None
    assert f"version {new_sha[:12]}" in lines[-1]
    assert view.codes == {}


def test_history_changed_is_counted_only_when_a_shipped_slot_changes(tmp_path: Path) -> None:
    plain = Morningful(tmp_path / "plain")
    parity(plain)
    assert plain.view is not None
    assert plain.view.history_changed == 0
    assert "history changed 0" in plain.view.summary()
    jumped = datetime(2026, 1, 14, 13, 10, tzinfo=UTC)

    def reads(at: datetime) -> Mapping[str, Read]:
        found = dict.fromkeys(LISTS, WHOLE)
        if at == jumped:
            found["tv"] = (10, 9, 0)
        return found

    back = Morningful(
        tmp_path / "back", reads=reads, jump={jumped: datetime(2026, 1, 14, 12, 40, tzinfo=UTC)}
    )
    parity(back, final=False)
    assert back.view is not None
    assert back.view.history_changed >= 1
    assert any("history changed 1" in line or "history changed 2" in line for line in back.lines)


# --- the context's bound, its lazy setup and the run's end ---------------------------------------


def test_a_context_past_its_bound_is_none_and_the_pass_goes_on() -> None:
    import threading  # noqa: PLC0415

    release = threading.Event()

    def slow(_day: date) -> Context:
        release.wait(5)
        return context()

    lines: list[str] = []
    view = LiveReads(StubChannel(dict), slow, lines.append, context_seconds=0.05)
    began = datetime.now(UTC)
    assert view.step(NOW, "synthetic") is None
    assert (datetime.now(UTC) - began).total_seconds() < 2
    assert lines == ["live reads (off) 2026-01-14 13:00Z: no proof: none (TimeoutError)"]
    # not tried again that run
    assert view.step(NOW + timedelta(minutes=30), "synthetic") is None
    assert dict(view.codes) == {"none": 2}
    assert len(view.context_times) == 1
    release.set()
    assert "context 0." in view.summary()


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, cases: Sequence[Case] = (),
    source: bool = True,
) -> tuple[live_reads.Setup, Counter[str]]:  # fmt: skip
    """SYNTHETIC: a class morning's setup whose export phases are stand-ins counting their
    calls; ``cases``: the population ``cases_of`` finds."""
    from snowlight.predict import call_time, live_read, read_cli  # noqa: PLC0415
    from snowlight.predict.config import PredictConfig  # noqa: PLC0415
    from snowlight.predict.situations import WeatherClass  # noqa: PLC0415

    calls: Counter[str] = Counter()

    def counted[T](name: str, value: T) -> Callable[..., T]:
        def call(*_a: Any, **_k: Any) -> T:
            calls[name] += 1
            return value

        return call

    monkeypatch.setattr(read_cli, "classes_on", counted("classes", [WeatherClass.SNOW_WARNING]))
    monkeypatch.setattr(live_read, "closing_of", counted("closing", None))
    inputs = SimpleNamespace(classes={}, record=None, stats=STATS, recent=RECENT)
    monkeypatch.setattr(read_cli, "proof_inputs", counted("inputs", inputs))
    monkeypatch.setattr(live_read, "audience_before", counted("audience", {}))
    monkeypatch.setattr(call_time, "cases_of", counted("cases", list(cases)))
    state = SimpleNamespace(prefix="v1", folder=tmp_path, market_of=MARKETS)
    found = SimpleNamespace(timeline=None, state=state, _log=lambda: None) if source else None
    setup = live_reads.Setup(
        config=PredictConfig.load(),
        load=live_reads.Once(counted("load", live_reads.Loaded(found, COVERAGE))),
        directory=lambda: cast("Directory", SimpleNamespace(content="synthetic")),
        snapshots=dict,
    )
    return setup, calls


@pytest.mark.parametrize(("source", "reason"), [(True, "no population"), (False, "no live state")])
def test_a_class_morning_with_no_context_is_built_once_a_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: bool, reason: str
) -> None:
    """A class morning whose districts have no covered list (or no live state) reads the
    export once and is a final no that run, counted as a build; only the quick no before
    anything is read (no class at D's snapshot) is asked again at the next mark."""
    setup, calls = _setup(tmp_path, monkeypatch, source=source)
    lines: list[str] = []
    view = LiveReads(StubChannel(dict), lambda day: live_reads.build_context(setup, day),
                     lines.append)  # fmt: skip
    at = datetime(2026, 1, 14, 9, 20, tzinfo=UTC)
    while at <= datetime(2026, 1, 14, 21, 15, tzinfo=UTC):
        assert view.step(at, "synthetic") is None
        at += STEP
    assert calls["load"] == 1
    assert calls["classes"] == 1
    assert calls["cases"] == (1 if source else 0)
    assert set(view.codes) == {"none"}
    assert lines == [f"live reads (off) 2026-01-14 09:00Z: no proof: none ({reason})"]
    assert len(view.context_times) == 1
    assert "context 0." in view.summary()


def test_the_export_s_d_minus_1_is_final_once_it_records_a_pass_of_d(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = Case(EAST_ID, EAST, NEEDED, False)
    setup, _calls = _setup(tmp_path, monkeypatch, cases=[case])
    log = MorningLog(tmp_path / "morning")
    evening = datetime(2026, 1, 13, 23, 55, 30, tzinfo=UTC)
    log.record(evening, shown="v1", reads={}, unknown=(), named={}, health=0.95)
    made = live_reads.build_context(setup, DAY)
    assert made is not None
    assert made.before is not None
    assert made.before.through == evening
    assert made.before_final is False  # the run that wrote it ended before D: maybe not final
    log.record(START, shown="v1", reads={}, unknown=(), named={}, health=0.95)
    made = live_reads.build_context(setup, DAY)
    assert made is not None
    assert made.before_final is True
    assert made.cases == (case,)


def test_a_build_ended_by_a_base_exception_is_coded_none_and_the_loop_goes_on() -> None:
    def leaving(_day: date) -> Context:
        raise SystemExit(3)

    view, lines = _view(StubChannel(dict))
    view.context = leaving
    assert view.step(NOW, "synthetic") is None
    assert view.step(NOW + timedelta(minutes=30), "synthetic") is None
    assert lines == ["live reads (off) 2026-01-14 13:00Z: no proof: none (SystemExit)"]
    assert dict(view.codes) == {"none": 2}
    assert len(view.context_times) == 1
    with pytest.raises(live_reads.WorkerExitError, match="KeyboardInterrupt"):
        live_reads.bounded(lambda: (_ for _ in ()).throw(KeyboardInterrupt()), 1.0)


def test_each_build_keeps_its_own_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A later build never moves a stalled earlier build's deadline."""
    import threading  # noqa: PLC0415

    setup, _calls = _setup(tmp_path, monkeypatch)
    clock = {"now": 0.0}
    release = threading.Event()
    stalled_in = threading.Event()
    seen: dict[str, str] = {}

    def directory() -> Any:
        if threading.current_thread().name == "first":
            stalled_in.set()
            release.wait(5)
            try:
                live_reads.check_bound()
            except TimeoutError as error:
                seen["first"] = str(error)
            return None
        live_reads.check_bound()
        seen["second"] = "in time"
        return None

    setup = replace(setup, directory=directory)

    def build() -> None:
        live_reads.build_context(setup, DAY, monotonic=lambda: clock["now"])

    first = threading.Thread(target=build, name="first")
    first.start()
    assert stalled_in.wait(5)
    clock["now"] = 100.0  # past the first build's 90 s, inside the second's
    second = threading.Thread(target=build, name="second")
    second.start()
    second.join(5)
    release.set()
    first.join(5)
    assert seen == {"first": "past the context's bound", "second": "in time"}
    live_reads.check_bound()  # outside a build: nothing


def test_the_run_s_end_stops_a_running_build_before_removing_its_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading  # noqa: PLC0415

    setup, _calls = _setup(tmp_path, monkeypatch)
    stop = threading.Event()
    setup = replace(setup, stop=stop)
    folder = tmp_path / "unpacked"
    folder.mkdir()
    ended: list[str] = []

    def directory() -> Any:
        stop.wait(5)  # a build still running at the run's end
        try:
            live_reads.check_bound()
        finally:
            (folder / "late").write_text("synthetic")  # what it writes before it ends
            ended.append("build")
        return None

    setup = replace(setup, directory=directory)
    view = LiveReads(
        StubChannel(dict), lambda day: live_reads.build_context(setup, day), lambda _l: None,
        context_seconds=0.05, stop=stop,
        cleanup=[lambda: shutil.rmtree(folder, ignore_errors=True)],
    )  # fmt: skip
    assert view.step(NOW, "synthetic") is None
    assert dict(view.codes) == {"none": 1}
    assert folder.is_dir()
    view.close()
    assert ended == ["build"]
    assert not folder.exists()


def test_a_build_past_the_run_s_end_removes_the_folder_itself(tmp_path: Path) -> None:
    import threading  # noqa: PLC0415

    folder = tmp_path / "unpacked"
    folder.mkdir()
    release = threading.Event()
    done = threading.Event()

    def stuck(_day: date) -> Context:
        release.wait(5)  # never asks its bound
        (folder / "late").write_text("synthetic")
        return context()

    def remove() -> None:
        shutil.rmtree(folder, ignore_errors=True)
        done.set()

    view = LiveReads(StubChannel(dict), stuck, lambda _l: None, context_seconds=0.05,
                     cleanup=[remove])  # fmt: skip
    assert view.step(NOW, "synthetic") is None
    view.close(wait=0.05)
    assert folder.is_dir()  # left to the build
    assert not done.is_set()
    release.set()
    assert done.wait(5)
    assert not folder.exists()
    view.close()  # nothing left to do


def test_once_keeps_the_value_or_the_error() -> None:
    calls = {"n": 0}

    def make() -> int:
        calls["n"] += 1
        raise ValueError("synthetic")

    once = live_reads.Once(make)
    for _ in range(3):
        with pytest.raises(ValueError, match="synthetic"):
            once()
    assert calls["n"] == 1
    assert live_reads.Once(lambda: 7)() == 7


def _damaged_archive() -> bytes:
    """SYNTHETIC: a packed state whose deflate stream breaks past its first block, so the
    raw tar reader raises ``zlib.error`` (no ``OSError``)."""
    import hashlib  # noqa: PLC0415
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415
    import zlib  # noqa: PLC0415

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for n in range(4):
            data = hashlib.sha256(str(n).encode()).digest() * 600 + b"x" * 200_000
            info = tarfile.TarInfo(f"f{n}.bin")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    good = buffer.getvalue()

    def raw(data: bytes) -> None:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                handle = tar.extractfile(member)
                assert handle is not None
                handle.read()

    for at in range(20, len(good), 7):
        bad = bytearray(good)
        for k in range(min(8, len(bad) - at)):
            bad[at + k] ^= 0xFF
        try:
            raw(bytes(bad))
        except zlib.error:
            return bytes(bad)
        except Exception:  # noqa: S112 - another damage: try the next place
            continue
    raise AssertionError("no zlib.error damage found")


def test_a_damaged_state_archive_is_a_state_error(tmp_path: Path) -> None:
    from snowlight.live.state import ARCHIVE, StateError, check_export, unpack  # noqa: PLC0415
    from snowlight.predict.cli import live_state_folder  # noqa: PLC0415

    bad = _damaged_archive()
    with pytest.raises(StateError, match="error"):
        unpack(bad, tmp_path / "out")
    with pytest.raises(StateError):
        check_export(bad)
    store = tmp_path / "store"
    store.mkdir()
    (store / ARCHIVE).write_bytes(bad)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(StateError):
        live_state_folder(tmp_path / "no state", store, scratch)
    # a damaged morning part is unreadable, never an error out of the decode
    texts = d1.pack_morning(b'{"schema_version": 1}' * 4000)
    import base64  # noqa: PLC0415

    raw_bytes = bytearray(base64.b64decode(texts[0]))
    for k in range(40, 48):
        raw_bytes[k] ^= 0xFF
    assert d1.unpack_morning([base64.b64encode(bytes(raw_bytes)).decode()], "0" * 64) is None


def _serving_run() -> Any:
    from snowlight.predict.config import PredictConfig  # noqa: PLC0415

    return SimpleNamespace(
        config=PredictConfig.load(),
        mode=SimpleNamespace(key="v1/predictions/latest.json"),
        _built=(None, SimpleNamespace(directory=None)),
        state=SimpleNamespace(snapshots={}),
    )


def test_the_view_setup_reads_nothing_and_a_raising_registry_is_coded_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``make_pass``'s view reads nothing before the first serving pass: the registry, the
    coverage and the export are read on the view's bounded thread at the first class
    morning, so a raising registry is one ``none`` line, never a raise out of ``make_pass``
    or a pass; a setup that fails outright is one warning and no view."""
    from snowlight.predict import cli, learn, read_cli  # noqa: PLC0415
    from snowlight.predict.situations import WeatherClass  # noqa: PLC0415

    monkeypatch.setattr(learn, "directory_of", lambda _model: SimpleNamespace(content="c"))
    monkeypatch.setattr(read_cli, "classes_on", lambda *_a: [WeatherClass.SNOW_WARNING])
    args = SimpleNamespace(
        registry=tmp_path / "no registry.json", read_sources=tmp_path / "r.json",
        audiences=tmp_path / "a.json", live_state=tmp_path / "state", live_store=tmp_path,
    )  # fmt: skip
    out: list[str] = []
    monkeypatch.setattr(cli, "_out", out.append)
    opened: list[str] = []

    def client() -> Any:
        opened.append("client")
        raise AssertionError("no host read before a class morning's context")

    # a raising registry: the setup itself reads nothing, so it never raises
    view = cli._make_live_reads(args, {}, _serving_run(), None, client=client)  # type: ignore[arg-type]
    assert view is not None
    assert view.channel is None  # no secrets here
    assert view.step(NOW, None) is None
    assert out[-1].startswith("live reads (off) 2026-01-14 13:00Z: no proof: none (")
    assert dict(view.codes) == {"none": 1}
    assert opened == []
    view.close()
    # and a setup that fails outright is one warning and no view
    warned: list[str] = []
    monkeypatch.setattr(cli, "_warn", warned.append)
    assert cli._make_live_reads(args, {}, SimpleNamespace(), None, client=client) is None  # type: ignore[arg-type]
    assert warned == ["predict: live reads: no view (AttributeError)"]


def test_a_damaged_export_is_coded_none_and_its_folder_removed_at_the_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A damaged archive (``zlib.error``, no ``OSError``) past the registry and the coverage
    is one ``none`` line, never a raise; the unpacked folder goes at the run's end."""
    import zlib  # noqa: PLC0415

    from snowlight.predict import cli, learn, read_cli  # noqa: PLC0415
    from snowlight.predict.situations import WeatherClass  # noqa: PLC0415
    from snowlight.sources.stations import registry  # noqa: PLC0415

    made: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def mkdtemp(prefix: str) -> str:
        found = str(real_mkdtemp(prefix=prefix, dir=tmp_path))
        made.append(Path(found))
        return found

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(learn, "directory_of", lambda _model: SimpleNamespace(content="c"))
    monkeypatch.setattr(read_cli, "classes_on", lambda *_a: [WeatherClass.SNOW_WARNING])
    args = SimpleNamespace(
        registry=tmp_path / "r", read_sources=tmp_path / "s", audiences=tmp_path / "a",
        live_state=tmp_path / "state", live_store=tmp_path / "store",
    )  # fmt: skip
    out: list[str] = []
    monkeypatch.setattr(cli, "_out", out.append)

    monkeypatch.setattr(registry, "load_registry", lambda _p: SimpleNamespace(stations={}))
    monkeypatch.setattr(read_cli, "coverage_of", lambda *_a, **_k: None)
    monkeypatch.setattr(read_cli, "current_coverage", lambda found, _day: found)

    def broken(_state: Path, _store: Path, _scratch: Path) -> Path | None:
        raise zlib.error("Error -3 while decompressing data: invalid distance too far back")

    monkeypatch.setattr(cli, "live_state_folder", broken)
    view = cli._make_live_reads(args, {}, _serving_run(), None, client=dict)  # type: ignore[arg-type]
    assert view is not None
    assert view.step(NOW, None) is None
    assert view.step(NOW + timedelta(minutes=5), None) is None
    assert dict(view.codes) == {"none": 2}
    assert out == [
        "predict: live reads (off): no channel",
        "live reads (off) 2026-01-14 13:00Z: no proof: none (error)",
    ]
    assert made
    assert all(folder.is_dir() for folder in made)
    view.close()
    assert not any(folder.exists() for folder in made)

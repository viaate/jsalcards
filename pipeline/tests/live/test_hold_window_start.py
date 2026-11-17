"""FLICKER-23Z: a list read under the quiet cadence keeps its statuses into a window or an
alert that opens after the read (``ingest.hold_end``, ``Ingest.note_boost``).

On Nov 9 at 23:00Z (18:00 in New York, the evening window's opening) one list's five statuses
went dark for one pass and came back with the same announcement at 23:05Z: its last good read,
made at a quiet pass, was judged by the in-window 45-minute bound the moment the window
opened. The shorter bound now counts from the start of the first boosted pass after such a
read, never past the read's 90 minutes. All rows, names and ids here are SYNTHETIC (the Nov 9
shape, no list text). The real ``Ingest.run_pass``, the real ``Cadence.boosted`` over an
America/New_York county (FIPS 20091 in the test world) and the real merge and publish run; a
pass is every 5 minutes, its reads at the pass start and its clock 50 seconds on (the
23:00:56Z shape).
"""

import inspect
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from live.test_edition import OWN, Source
from live.world import NEW_YORK, World, _school, accepted, at, row, station
from snowlight.live.cadence import Cadence
from snowlight.live.carry import Carried
from snowlight.live.edition import EditionWatch
from snowlight.live.guards import FUTURE_LEEWAY, Rules, held
from snowlight.live.ingest import Ingest, SourceRead
from snowlight.live.ledger import Outcome
from snowlight.live.publish import LivePublisher
from snowlight.live.publishers import DirPublisher
from snowlight.live.versions import PUBLISHING_FILES, live_files
from snowlight.schemas.directory import DirectoryEdition
from snowlight.schemas.live import ClosingsFile
from snowlight.schemas.vocab import Status

S = "gray-synthetic"  # the list that carries the district row
HEALTHY = ("gray-one", "gray-two", "gray-three")  # other lists, read fine every pass
DISTRICT = "1399999"
IDS = tuple(f"{DISTRICT}{n:05d}" for n in range(5))
NAME = "SYNTHETIC Ridge County Schools"
POSTED = at("2026-11-08 23:30")  # Sunday 18:30 local: the announcement the rows keep
OK, ERR = Outcome.OK, Outcome.ERROR
CLOSED = (row(NAME, "Closed", row_stamp=POSTED),)
CLOCK = timedelta(seconds=50)  # a pass's clock after its reads
Boosted = Callable[[object, datetime], bool]


def _world() -> World:
    w = World()
    extra = [
        _school(sid, 11 + n, zones=(NEW_YORK,), district=DISTRICT) for n, sid in enumerate(IDS)
    ]
    w.dir = type(w.dir)(
        schools={**w.dir.schools, **{s.record.id: s for s in extra}},
        district_sizes={**w.dir.district_sizes, DISTRICT: 5},
        edition=w.dir.edition,
    )
    w.matcher.table[NAME] = accepted(via=IDS)
    for sid in HEALTHY:
        w.stations[sid] = station(sid)
    for sid in (S, *HEALTHY):
        w.read(at("2026-11-06 14:00"), [], source=sid, outcome=Outcome.EMPTY)
    w.read(at("2026-11-08 23:00"), [], source=S, outcome=Outcome.EMPTY)
    w.read(POSTED, list(CLOSED), source=S)
    return w


def _ingest(w: World, tmp: Path, boosted: Boosted | None = None) -> Ingest:
    edition = DirectoryEdition.model_validate(
        {**OWN.model_dump(mode="json"), "schools": len(w.dir.schools), "districts": 7}
    )
    publisher = LivePublisher(
        host=DirPublisher(tmp / "host"),
        directory=w.dir,
        state_dir=tmp / "state",
        internal_dir=tmp / "internal",
    )
    cadence = Cadence(w.stations, {"20091": NEW_YORK}, lambda _s: 30)
    return Ingest(
        ledger=w.ledger,
        resolver=w.resolver(),
        stations=w.stations,
        publisher=publisher,
        watch=EditionWatch(own=edition, source=Source([edition])),
        internal_dir=tmp / "run",
        due=frozenset({S, *HEALTHY}),
        boosted=cadence.boosted if boosted is None else boosted,
    )


def _published(tmp: Path) -> tuple[int, set[datetime | None]]:
    found = ClosingsFile.from_json_bytes(
        (tmp / "host" / "v1-shadow" / "live" / "closings.json").read_bytes()
    )
    closings = found.closings()
    return len(closings), {c.announced_at for c in closings}


def _passes(first: str, last: str) -> list[datetime]:
    out, t = [], at(first)
    while t <= at(last):
        out.append(t)
        t += timedelta(minutes=5)
    return out


def _run(
    tmp: Path,
    plan: Mapping[str, Outcome],
    span: tuple[str, str],
    *,
    boosted: Boosted | None = None,
    ing: Ingest | None = None,
) -> list[tuple[str, int, set[datetime | None]]]:
    """Pass every 5 minutes over ``span`` (UTC, both ends); the list is read at the
    ``HH:MM`` keys of ``plan`` with that outcome. Returns (HH:MM, lit, announcements)."""
    ing = _ingest(_world(), tmp, boosted) if ing is None else ing
    out = []
    for t in _passes(*span):
        hm = f"{t:%H:%M}"
        reads = [SourceRead(sid, Outcome.EMPTY, t) for sid in HEALTHY]
        if hm in plan:
            reads.append(SourceRead(S, plan[hm], t, CLOSED if plan[hm] is OK else ()))
        ing.run_pass(reads, t + CLOCK, started=t, always=True)
        lit, announced = _published(tmp)
        out.append((hm, lit, announced))
    return out


def _dark(seq: list[tuple[str, int, set[datetime | None]]]) -> list[str]:
    return [hm for hm, lit, _ in seq if lit == 0]


# The list's read phase is in no public file. Most likely :05/:35 (a list holding rows is read
# first by a new process, from its 18:35 pass): good 22:05, bad 22:35 and 23:00, good 23:05.
REAL = {"22:05": OK, "22:35": ERR, "23:00": ERR, "23:05": OK, "23:10": OK}
PLANS = {
    "phase-0535-two": (REAL, ("2026-11-09 22:05", "2026-11-09 23:15")),
    "phase-0535-three": (
        {"21:35": OK, "22:05": ERR, "22:35": ERR, "23:00": ERR, "23:05": OK, "23:10": OK},
        ("2026-11-09 21:35", "2026-11-09 23:15"),
    ),
    "phase-2555-three": (
        {"21:55": OK, "22:25": ERR, "22:55": ERR, "23:00": ERR, "23:05": OK, "23:10": OK},
        ("2026-11-09 21:55", "2026-11-09 23:15"),
    ),
}


@pytest.mark.parametrize("name", PLANS)
def test_flicker_23z_replay(tmp_path: Path, name: str) -> None:
    plan, span = PLANS[name]
    seq = _run(tmp_path, plan, span)
    assert _dark(seq) == []  # HEAD: ['23:00'] for each plan
    assert all(lit == 5 for _, lit, _ in seq)
    assert all(announced == {POSTED} for _, _, announced in seq)  # one unchanged posting


def test_the_read_before_the_window_still_ends_at_90_minutes(tmp_path: Path) -> None:
    # the last good read at 21:25: past 90 minutes at the 22:55 pass (a quiet pass), as HEAD
    plan = {"21:25": OK, "21:55": ERR, "22:25": ERR, "22:55": ERR, "23:00": ERR, "23:05": OK}
    seq = _run(tmp_path, plan, ("2026-11-09 21:25", "2026-11-09 23:10"))
    assert _dark(seq) == ["22:55", "23:00"]


def test_window_start_still_darkens_a_list_that_keeps_failing(tmp_path: Path) -> None:
    plan = {"21:55": OK} | {f"{h}:{m:02d}": ERR for h in (22, 23) for m in range(0, 60, 5)}
    seq = _run(tmp_path, plan, ("2026-11-09 21:55", "2026-11-09 23:45"))
    # min(21:55 + 90, 23:00 + 45) = 23:25: lit through the 23:20 pass (HEAD: dark from 23:00)
    assert _dark(seq)[0] == "23:25"
    assert _dark(seq) == [hm for hm, _, _ in seq if hm >= "23:25"]


def test_a_read_inside_the_window_keeps_45_minutes(tmp_path: Path) -> None:
    plan = {"23:05": OK} | {f"23:{m:02d}": ERR for m in range(10, 60, 5)}
    seq = _run(tmp_path, {"22:55": OK, **plan}, ("2026-11-09 22:55", "2026-11-09 23:55"))
    assert _dark(seq) == ["23:50", "23:55"]  # 23:05 + 45 = 23:50:00 < the 23:50:50 clock


def _boosted_from(start: str, *, off: tuple[str, ...] = ()) -> Boosted:
    def boosted(_station: object, now: datetime) -> bool:
        return now >= at(start) and f"{now:%H:%M}" not in off

    return boosted


def test_an_alert_start_is_a_spell_start(tmp_path: Path) -> None:
    # Monday afternoon, a quiet station; an alert from 20:20Z; the last good read at 19:25Z
    plan = {"19:25": OK} | {f"20:{m:02d}": ERR for m in range(0, 60, 5)}
    seq = _run(
        tmp_path,
        plan,
        ("2026-11-09 19:25", "2026-11-09 21:00"),
        boosted=_boosted_from("2026-11-09 20:20"),
    )
    # HEAD: dark from 20:20 (55 minutes old). Now: min(19:25 + 90, 20:20 + 45) = 20:55
    assert _dark(seq) == ["20:55", "21:00"]


def test_a_quiet_pass_inside_a_spell_moves_nothing(tmp_path: Path) -> None:
    # boosted from 23:00Z, judged quiet at the 23:25 pass only; good 23:00 and 23:05, then errors
    plan = {"23:00": OK, "23:05": OK} | {f"23:{m:02d}": ERR for m in range(10, 60, 5)}
    plan |= {f"00:{m:02d}": ERR for m in range(0, 25, 5)}
    flap = _boosted_from("2026-11-09 23:00", off=("23:25",))
    seq = _run(tmp_path, plan, ("2026-11-09 23:00", "2026-11-10 00:20"), boosted=flap)
    assert _dark(seq)[0] == "23:50"  # 23:05 + 45, as HEAD (critic r1-2's probe: the r1 fix 00:15)
    assert _dark(seq) == [hm for hm, _, _ in seq if hm >= "23:50" or hm < "23:00"]


def test_a_read_at_a_quiet_pass_counts_from_the_next_boosted_pass(tmp_path: Path) -> None:
    # the good read falls in the one quiet pass (23:25); the spell resumes at 23:30
    plan = {"23:00": OK, "23:25": OK} | {f"23:{m:02d}": ERR for m in range(30, 60, 5)}
    plan |= {f"00:{m:02d}": ERR for m in range(0, 25, 5)}
    flap = _boosted_from("2026-11-09 23:00", off=("23:25",))
    seq = _run(tmp_path, plan, ("2026-11-09 23:00", "2026-11-10 00:20"), boosted=flap)
    # HEAD: 23:25 + 45 = 00:10 (dark at the 00:10 pass); now 23:30 + 45 = 00:15: one pass more
    assert _dark(seq) == ["00:15", "00:20"]


def test_hold_end_bounds() -> None:
    from snowlight.live.ingest import hold_end  # noqa: PLC0415 - absent on HEAD

    rules = Rules()
    good = at("2026-11-09 22:00")
    quiet, short = rules.hold_quiet, rules.hold_boosted
    # second offsets: the read and the spell start need not fall on a pass's minute
    starts = (None, *(good + timedelta(seconds=s) for s in range(-7200, 7201, 290)))
    for boosted in (False, True):
        for since in starts:
            for s in range(-125, 7300, 37):
                now = good + timedelta(seconds=s)
                end = hold_end(good, now, boosted=boosted, boosted_from=since, rules=rules)
                old = held(good, now, boosted=boosted, rules=rules)
                head = good + (short if boosted else quiet)  # HEAD's end where it holds
                assert end is None or (now <= end <= good + quiet)  # never past the 90
                assert old <= (end is not None)  # never darker than HEAD
                if old:
                    assert end is not None
                    assert end >= head  # never ends before HEAD's end
                spell = since if boosted and since is not None and since > good else None
                if spell is None:  # no spell credit
                    assert (end is not None) is old  # HEAD exactly, flag and end
                    assert end is None or end == head
                elif now - good >= -FUTURE_LEEWAY and now <= min(good + quiet, spell + short):
                    assert end == min(good + quiet, spell + short)  # section 8's end
                else:
                    assert end is None


def test_the_hold_rule_keeps_the_carry_key() -> None:
    # FLICKER-23Z changes when a list is held, never a derivation: its code is in modules
    # live_version() does not digest, so derived_version and the carry key stay as before
    # and the first handover after it lands still carries (critic r1-1: guards.py is digested)
    from snowlight.live import ingest  # noqa: PLC0415

    digested = {path.resolve() for path in live_files()}
    for code in (ingest.hold_end, Ingest.note_boost, Ingest.hold_until):
        assert Path(inspect.getfile(code)).name in PUBLISHING_FILES
        assert Path(inspect.getfile(code)).resolve() not in digested


def test_matches_the_old_rule_where_no_spell_starts(tmp_path: Path) -> None:
    # every pass boosted (the ingest default): each read is made in the spell; the old rule,
    # computed inline, decides every pass
    plan = {"22:00": OK, "22:20": ERR, "22:35": OK, "23:30": ERR, "23:50": ERR}
    seq = _run(
        tmp_path, plan, ("2026-11-09 22:00", "2026-11-10 00:30"), boosted=lambda _s, _n: True
    )
    good = None
    for (hm, lit, _), t in zip(seq, _passes("2026-11-09 22:00", "2026-11-10 00:30"), strict=True):
        good = t if plan.get(hm) is OK else good
        old = good is not None and t + CLOCK - good <= Rules().hold_boosted
        assert (lit == 5) is old, hm


def test_carried_source_keeps_its_own_read_time(tmp_path: Path) -> None:
    # a successor holding the run before's 22:05 read: at the window start it counts from that
    # read's own time, as HEAD (no spell credit), and the carried end still caps it
    w = _world()
    w.read(at("2026-11-09 22:05"), list(CLOSED), source=S)
    ing = _ingest(w, tmp_path)
    ing.carried = {S: Carried(at("2026-11-09 22:05"), at("2026-11-09 23:35"))}
    quiet, window = at("2026-11-09 22:59"), at("2026-11-09 23:00") + CLOCK
    ing.run_pass([SourceRead(sid, Outcome.EMPTY, quiet) for sid in HEALTHY], quiet, started=quiet)
    assert ing.held(quiet)[S] is True
    assert S not in ing.boost_from
    assert ing.held(window)[S] is False  # 55 minutes old in the window: 45 counts from 22:05


def test_carry_records_the_hold_end(tmp_path: Path) -> None:
    ing = _ingest(_world(), tmp_path)
    path = tmp_path / "carry.json"
    ing.start_carry(path, at("2026-11-09 22:05"))
    _run(tmp_path, REAL, ("2026-11-09 22:05", "2026-11-09 23:00"), ing=ing)
    entry = json.loads(path.read_text())["sources"][S]
    # min(22:05 + 90, 23:00 + 45) = 23:35 (HEAD: dark at 23:00, so not listed)
    assert entry == {"good": "2026-11-09T22:05:00+00:00", "until": "2026-11-09T23:35:00+00:00"}


T = "gray-other"  # a second list naming the same made-up district, read well every pass


def _two_lists(tmp: Path, t_stamp: datetime) -> list[tuple[str, int, set[Status]]]:
    """S on the primary plan; T says Delayed with the row stamp ``t_stamp``, read well every
    pass. Returns (HH:MM, lit, statuses) per pass, 22:05-23:15."""
    w = _world()
    w.stations[T] = station(T)
    t_rows = (row(NAME, "Delayed", row_stamp=t_stamp),)
    w.read(at("2026-11-06 14:00"), [], source=T, outcome=Outcome.EMPTY)
    w.read(t_stamp, list(t_rows), source=T)
    ing = _ingest(w, tmp)
    ing.due = frozenset({S, *HEALTHY, T})
    out = []
    for t in _passes("2026-11-09 22:05", "2026-11-09 23:15"):
        hm = f"{t:%H:%M}"
        reads = [SourceRead(sid, Outcome.EMPTY, t) for sid in HEALTHY]
        reads.append(SourceRead(T, OK, t, t_rows))
        if hm in REAL:
            reads.append(SourceRead(S, REAL[hm], t, CLOSED if REAL[hm] is OK else ()))
        ing.run_pass(reads, t + CLOCK, started=t, always=True)
        found = ClosingsFile.from_json_bytes(
            (tmp / "host" / "v1-shadow" / "live" / "closings.json").read_bytes()
        ).closings()
        out.append((hm, len(found), {c.status for c in found}))
    return out


def test_two_lists_at_one_posting_time_stay_withheld(tmp_path: Path) -> None:
    # S says Closed and T says Delayed at the same posting time: CONFLICT withholds both while
    # S is held. The fix keeps S held at 23:00, so the school stays dark at every pass.
    # HEAD: S drops at 23:00 and T's Delayed lights for that one pass (0, ..., 5, 0, 0, 0).
    # Only the held flag moves: merge rule 3, vanish_retracts and absent_since are untouched,
    # so a held list's vanished rows behave exactly as at HEAD (FALSE-LIGHT-FIX owns those).
    seq = _two_lists(tmp_path, POSTED)
    assert [lit for _, lit, _ in seq] == [0] * len(seq)


def test_the_later_word_keeps_showing_at_the_window_start(tmp_path: Path) -> None:
    # T's Delayed was posted an hour before S's Closed, so S's later word shows while S is
    # held. The fix keeps Closed at 23:00. HEAD: T's older Delayed shows at 23:00 only.
    # As in the test above, a held list's vanished rows behave exactly as at HEAD: the fix
    # changes whether S is held at a pass, never what the merge does with a held list's rows.
    seq = _two_lists(tmp_path, POSTED - timedelta(hours=1))
    assert all(lit == 5 and statuses == {Status.CLOSED} for _, lit, statuses in seq)


# LR9 by behaviour: S's row is read, then a good read without it (the row vanishes), then
# errors. Each plan runs twice, with the fix and with HEAD's rule (no spell credit: test 8
# shows hold_end is then HEAD's end exactly).
VANISH = {"21:35": "row", "22:05": "gone", "22:35": "err", "23:00": "err", "23:05": "gone"}


def _vanish(tmp: Path, boosted: Boosted | None, *, credit: bool) -> list[tuple[str, int, bool]]:
    ing = _ingest(_world(), tmp, boosted)
    out = []
    with pytest.MonkeyPatch.context() as patch:
        if not credit:
            patch.setattr(Ingest, "note_boost", lambda *_args: None)
        for t in _passes("2026-11-09 21:35", "2026-11-10 00:00"):
            hm = f"{t:%H:%M}"
            reads = [SourceRead(sid, Outcome.EMPTY, t) for sid in HEALTHY]
            kind = VANISH.get(hm)
            if kind == "row":
                reads.append(SourceRead(S, OK, t, CLOSED))
            elif kind == "gone":
                reads.append(SourceRead(S, Outcome.EMPTY, t, ()))
            elif kind == "err":
                reads.append(SourceRead(S, ERR, t, ()))
            ing.run_pass(reads, t + CLOCK, started=t, always=True)
            out.append((hm, _published(tmp)[0], ing.held(t + CLOCK).get(S, False)))
    return out


def test_vanished_rows_behave_as_at_head_when_every_pass_is_boosted(tmp_path: Path) -> None:
    always: Boosted = lambda _s, _n: True  # noqa: E731
    fix = _vanish(tmp_path / "fix", always, credit=True)
    head = _vanish(tmp_path / "head", always, credit=False)
    assert fix == head  # pass by pass: lit count and held flag
    lit = [n for _, n, _ in fix]
    assert 5 in lit  # the planted row lights
    assert 0 in lit  # and the vanish darkens it


def test_vanished_rows_differ_from_head_only_where_the_hold_does(tmp_path: Path) -> None:
    # the real cadence: the vanish read is made at a quiet pass, the window opens at 23:00
    fix = _vanish(tmp_path / "fix", None, credit=True)
    head = _vanish(tmp_path / "head", None, credit=False)
    moved = [hm for (hm, _, a), (_, _, b) in zip(fix, head, strict=True) if a != b]
    assert moved == ["23:00"]  # the spell credit, nothing else
    for (hm, a, held_a), (_, b, held_b) in zip(fix, head, strict=True):
        if held_a == held_b:
            assert a == b, hm

"""Staying on air (predict-next ON-AIR): Nov 9 replayed, the loop's early end for a newer
branch head and the causes that never end a run, each pass's line, the branch head question,
and the start-up on a saved zone map. SYNTHETIC files only."""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from predict import world
from predict.test_host_files import LATER, grown
from predict.test_opens import TODAY, TOMORROW, closings, opens
from predict.test_publish import NOW, MemoryHost, feed, make_pass
from snowlight.directory import deployed
from snowlight.directory.points import PointsFormatError
from snowlight.live.publishers import PublishError
from snowlight.predict import cli, host_files, inputs
from snowlight.predict.live_labels import StateSource
from snowlight.predict.nowcast import UNREAD
from snowlight.predict.opens import NOTHING_SAID
from snowlight.predict.publish import Dark, DarkError, State
from snowlight.predict.serve import ServeError
from snowlight.schemas.directory import DirectoryStamp, written_edition
from snowlight.schemas.live import DayEntry, DayIndex
from snowlight.schemas.vocab import Status
from snowlight.sources.nws.boundaries import BoundaryError
from snowlight.sources.nws.http import FetchError

KEY = "v1/predictions/latest.json"
OPENS, CLOSINGS = "v1/live/opens.json", "v1/live/closings.json"
DAY_FILE = "v1/live/days/2026-01-06.json"
MINE, NEWER = "a" * 40, "b" * 40
GRID = datetime(2026, 1, 7, 2, 7, 0, tzinfo=UTC)
"""A grid minute: a loop started here makes no second grid pass for 30 minutes."""


@pytest.fixture(autouse=True)
def _forgotten() -> Iterator[None]:
    host_files.forget()
    cli._HEAD_SAID.clear()
    yield
    host_files.forget()
    cli._HEAD_SAID.clear()


def host_of(*, more: bool, only: str | None = None) -> MemoryHost:
    """A host with an opens file (district 1 said school is on), a closings file with rows
    and yesterday's timeline; ``more``: each (or ``only`` one) with a key added to every
    object."""
    files = {
        OPENS: opens([(0, TODAY), (1, TODAY), (0, TOMORROW), (1, TOMORROW)]).to_json_bytes(),
        CLOSINGS: closings([(4, TODAY, Status.CLOSED), (5, TODAY, Status.DELAYED)]).to_json_bytes(),
        DAY_FILE: world.timeline().to_json_bytes(),
    }
    host = MemoryHost()
    for key, data in files.items():
        host.files[key] = grown(data)[0] if more and only in {None, key} else data
    return host


def test_nov_9_replayed(capsys: Any) -> None:
    host = host_of(more=True)
    for key in (OPENS, CLOSINGS, DAY_FILE):
        assert LATER.encode() in host.files[key]
    run = make_pass(host, directory=world.directory())
    assert cli.one_pass(run) == 0
    assert KEY in host.files
    assert run._newer_code is False
    captured = capsys.readouterr()
    assert "dark" not in captured.err
    assert captured.err.count("unknown keys dropped") == 3
    assert LATER not in captured.err + captured.out
    # The files were read, not skipped: district 1 said school is on.
    model = run.serve_model(world.directory())
    assert cli._said_open(run, model, NOW).district(TODAY, 1)
    assert cli._said_open(run, model, NOW) != NOTHING_SAID


def test_the_file_equals_the_one_made_without_the_key() -> None:
    plain, more = host_of(more=False), host_of(more=True)
    assert cli.one_pass(make_pass(plain, directory=world.directory())) == 0
    assert cli.one_pass(make_pass(more, directory=world.directory())) == 0
    assert more.files[KEY] == plain.files[KEY]
    assert cli.content_digest(more.files[KEY]) == cli.content_digest(plain.files[KEY])
    # The host files matter to the file: without them it differs.
    bare = MemoryHost()
    assert cli.one_pass(make_pass(bare, directory=world.directory())) == 0
    assert bare.files[KEY] != plain.files[KEY]
    for only in (DAY_FILE, OPENS, CLOSINGS):
        one = host_of(more=True, only=only)
        assert cli.one_pass(make_pass(one, directory=world.directory())) == 0
        assert one.files[KEY] == plain.files[KEY]


def test_the_neighbours_and_the_labels_read_the_grown_files(capsys: Any, tmp_path: Path) -> None:
    days = (TODAY, TODAY + timedelta(days=1))
    found = []
    for more in (False, True):
        run = make_pass(host_of(more=more), directory=world.directory())
        model = run.serve_model(world.directory())
        found.append(cli._neighbors(run, model, days, NOW))
    assert found[0] == found[1]
    assert found[1] != UNREAD
    assert found[1].read
    assert "no neighbors reasons" not in capsys.readouterr().err
    index = DayIndex(
        schema_version=1,
        generated_at=NOW,
        days=(DayEntry(day=date(2026, 1, 6), schools=3, final=True),),
    )
    files = {
        "live/days/index.json": grown(index.to_json_bytes())[0],
        "live/days/2026-01-06.json": grown(world.timeline().to_json_bytes())[0],
    }
    source = StateSource(
        folder=tmp_path,
        market_of={},
        zone_of=dict(world.ZONES),
        settings=world.CONFIG.labels,
        prefix="v1",
        read_file=files.get,
    )
    assert source.index() == index
    assert source.timeline(date(2026, 1, 6)) == world.timeline()
    assert source.timeline(date(2026, 1, 5)) is None
    err = capsys.readouterr().err
    assert "predict: live/days/index.json: 2 unknown keys dropped (in (top), days[])" in err
    assert "predict: live/days/2026-01-06.json: 2 unknown keys dropped" in err
    # A file the labels cannot validate still fails their step, as today.
    files["live/days/index.json"] = b'{"schema_version":2}'
    with pytest.raises(ValidationError):
        source.index()


def code_99(host: MemoryHost) -> None:
    doc = json.loads(host.files[CLOSINGS])
    doc["days"][0]["statuses"][0] = 99
    host.files[CLOSINGS] = json.dumps(doc).encode()


def version_2(host: MemoryHost) -> None:
    doc = json.loads(host.files[DAY_FILE])
    doc["schema_version"] = 2
    host.files[DAY_FILE] = json.dumps(doc).encode()


def test_a_file_the_code_cannot_validate_darkens_as_today(capsys: Any) -> None:
    lines = {
        code_99: "predict: dark (opens_unreadable: v1/live: ValidationError)\n",
        version_2: f"predict: dark (day_file_unreadable: {DAY_FILE} does not validate)\n",
    }
    for more in (False, True):
        for change, line in lines.items():
            host = host_of(more=more)
            change(host)
            run = make_pass(host, directory=world.directory())
            called: list[int] = []
            run.notify = lambda _file, _directory, _now: str(called.append(1))  # noqa: B023
            assert cli.one_pass(run) == cli.EXIT_DARK
            assert capsys.readouterr().err.endswith(line)
            assert KEY not in host.files
            assert host.writes == 0
            assert called == []
            assert run._newer_code is True


# --- the loop -----------------------------------------------------------------------------------


class Ran:
    """One loop on a fake clock: what it did."""

    def __init__(self) -> None:
        self.passes: list[datetime] = []
        self.saves: list[datetime] = []
        self.asked: list[datetime] = []
        self.events: list[str] = []
        self.dark = 0
        self.out = ""
        self.err = ""


def looped(  # noqa: PLR0913 - one loop and everything a test may swap
    capsys: Any,
    monkeypatch: Any,
    *,
    script: list[str] | None = None,
    run: cli.Pass | None = None,
    start: datetime = GRID,
    minutes: int = 65,
    head: Any = NEWER,
    commit: str | None = MINE,
    config: Any = world.CONFIG,
    save_fails_on: int = 0,
) -> Ran:
    """Run the real loop. ``script``: what each pass does, the last entry repeated (``good``,
    ``curable``: an error no one foresaw, ``feed``: dark for a cause no restart cures); with
    none, ``run``'s own passes. ``head``: the branch head's answer (a commit, ``None``, an
    exception to raise, or ``"absent"`` for no reader at all)."""
    ran = Ran()
    clock = [start]
    the_run = run or make_pass(MemoryHost(), directory=world.directory(), config=config)
    the_run.now = lambda: clock[0]
    if run is None:
        the_run.alerts = lambda: (
            feed(updated=(clock[0] - timedelta(minutes=1)).isoformat()),
            True,
        )
    real = cli.one_pass

    def one_pass(found: cli.Pass, *, grid: bool = True) -> int:
        ran.passes.append(clock[0])
        ran.events.append("pass")
        if script is None:
            return real(found, grid=grid)
        what = script[min(len(ran.passes), len(script)) - 1]
        if what == "curable":
            raise RuntimeError("no one foresaw this")
        return 0 if what == "good" else cli.EXIT_DARK

    def ask() -> str | None:
        ran.asked.append(clock[0])
        ran.events.append("asked")
        if isinstance(head, Exception):
            raise head
        return None if head is None else str(head)

    def save(_state: State) -> None:
        if len(ran.saves) + 1 == save_fails_on and len(ran.passes) == save_fails_on:
            ran.events.append("save failed")
            raise OSError("no room")
        ran.saves.append(clock[0])
        ran.events.append("saved")

    def sleep(seconds: float) -> None:
        clock[0] += timedelta(seconds=seconds)

    monkeypatch.setattr(cli, "one_pass", one_pass)
    capsys.readouterr()
    clock_of = cli.Loop(
        now=lambda: clock[0], sleep=sleep, head=None if head == "absent" else ask, commit=commit
    )
    ran.dark = cli.loop(the_run, start + timedelta(minutes=minutes), clock_of, save)
    monkeypatch.setattr(cli, "one_pass", real)
    captured = capsys.readouterr()
    ran.out, ran.err = captured.out, captured.err
    return ran


def at(start: datetime, *offsets: tuple[int, int]) -> list[datetime]:
    return [start + timedelta(minutes=minute, seconds=second) for minute, second in offsets]


ENDING = (
    "predict run: ending early: 3 dark passes since the last good pass that newer code may "
    "cure; the branch head bbbbbbb is not this run's aaaaaaa\n"
)


def test_three_curable_dark_passes_and_a_newer_head_end_the_loop(
    capsys: Any, monkeypatch: Any
) -> None:
    assert world.CONFIG.serve.restart_after_dark == 3
    ran = looped(capsys, monkeypatch, script=["curable"])
    assert ran.dark == 3
    assert ran.passes == at(GRID, (0, 0), (10, 0), (20, 0))  # :07, :17, :27
    assert len(ran.asked) == 1
    assert len(ran.saves) == 3
    assert ran.events[-3:] == ["pass", "saved", "asked"]  # saved before the question
    assert ran.out.endswith(ENDING)
    assert ran.out.count("ending early") == 1
    # Started between grid minutes, a grid pass comes inside the 10-minute gap.
    start = datetime(2026, 1, 7, 2, 33, 20, tzinfo=UTC)
    early = looped(capsys, monkeypatch, script=["curable"], start=start)
    assert early.dark == 3
    assert early.passes == at(start, (0, 0), (3, 40), (13, 40))  # :33:20, :37:00, :47:00
    assert len(early.asked) == 1
    assert early.out.endswith(ENDING)


def test_the_same_head_or_no_answer_changes_nothing(capsys: Any, monkeypatch: Any) -> None:
    never = world.CONFIG.model_copy(
        update={"serve": world.CONFIG.serve.model_copy(update={"restart_after_dark": 0})}
    )
    until = GRID + timedelta(minutes=65)
    for case in (
        {"head": MINE},
        {"head": None},
        {"head": RuntimeError("the question broke")},
        {"head": "absent"},
        {"commit": None},
        {"commit": ""},
        {"config": never},
    ):
        ran = looped(capsys, monkeypatch, script=["curable"], **case)  # type: ignore[arg-type]
        assert ran.passes[-1] > until - timedelta(minutes=10), case  # it ran to `until`
        assert ran.dark == len(ran.passes) >= 7, case
        assert "ending early" not in ran.out, case
        asks = "head" in case and case["head"] != "absent"
        assert len(ran.asked) == (ran.dark - 2 if asks else 0), case
        if asks:
            assert ran.asked == ran.passes[2:], case
    # A state that did not save: no question, and the next counted dark pass asks again.
    ran = looped(capsys, monkeypatch, script=["curable"], save_fails_on=3)
    assert ran.dark == 4
    assert ran.asked == [ran.passes[3]]
    assert ran.events[-5:] == ["pass", "save failed", "pass", "saved", "asked"]
    assert "the state did not save: no room" in ran.err
    assert ran.out.endswith(ENDING.replace("3 dark", "4 dark"))


def raising(error: Exception) -> Callable[..., Any]:
    def raise_it(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    return raise_it


class Flaky(MemoryHost):
    """A host whose read of one path fails."""

    def __init__(self, part: str) -> None:
        super().__init__()
        self.part = part

    def read(self, key: str) -> bytes | None:
        if self.part in key:
            raise PublishError(f"read {key}: HTTP 502")
        return super().read(key)


def flaky(part: str) -> Flaky:
    host = Flaky(part)
    host.files.update(host_of(more=False).files)
    return host


def other_directory() -> MemoryHost:
    host = host_of(more=False)
    other = DirectoryStamp(generated_on=date(2026, 10, 1), schools=11, districts=5)
    host.files[OPENS] = opens([(0, TODAY)], stamp=other).to_json_bytes()
    return host


def not_the_deployed_edition() -> DarkError:
    meta, points = world.meta_bytes(), world.points_bytes()
    edition = written_edition(meta, points)
    other = edition.model_copy(update={"content_sha256": "0" * 64})
    with pytest.raises(DarkError) as dark:
        inputs.directory_from_files(other, meta, points)
    assert type(dark.value) is DarkError
    return dark.value


def bad_date() -> DarkError:
    """A ``meta.json`` whose date is not written as the build writes it: a plain ValueError."""
    dated = b'"generated_on":"2026-10-14"'
    meta = world.meta_bytes().replace(dated, dated.replace(b":", b": "))
    assert meta != world.meta_bytes()
    edition = written_edition(world.meta_bytes(), world.points_bytes())
    with pytest.raises(DarkError) as dark:
        inputs.directory_from_files(edition, meta, world.points_bytes())
    assert type(dark.value) is DarkError
    assert str(dark.value) == "edition_unreadable: directory files: ValueError"
    return dark.value


def mismatch() -> deployed.EditionMismatchError:
    edition = written_edition(world.meta_bytes(), world.points_bytes())
    return deployed.EditionMismatchError("another directory", claimed=edition, made=edition)


def not_json() -> Exception:
    try:
        json.loads("<html>")
    except ValueError as error:
        return error
    raise AssertionError


INCURABLE: dict[str, tuple[Callable[[Any, cli.Pass], None], str]] = {
    "the feed unreadable": (
        lambda _m, run: setattr(run, "alerts", raising(DarkError(Dark.ALERTS, "HTTP 503"))),
        "alerts_unreadable: HTTP 503",
    ),
    "the feed stale": (
        lambda _m, run: setattr(
            run, "alerts", lambda: (feed(updated="2026-01-06T20:00:00+00:00"), True)
        ),
        "alerts_stale",
    ),
    "the feed collapsed": (
        lambda m, _run: m.setattr(
            cli, "check_collapse", raising(DarkError(Dark.COLLAPSE, "9 to 0"))
        ),
        "alert_collapse: 9 to 0",
    ),
    "the history failing": (
        lambda _m, run: setattr(
            run, "history", raising(DarkError(Dark.MEMORY, "alert history: HTTP 500"))
        ),
        "alert_memory: alert history: HTTP 500",
    ),
    "the directory: the handshake": (
        lambda _m, run: setattr(
            run,
            "directory",
            raising(inputs.edition_dark(deployed.DeployedEditionError("the API said no"))),
        ),
        "edition_unreadable: DeployedEditionError",
    ),
    "the directory: a deploy in progress": (
        lambda _m, run: setattr(
            run,
            "directory",
            raising(inputs.edition_dark(deployed.DeployInProgressError("deploying"))),
        ),
        "edition_unreadable: DeployInProgressError",
    ),
    "the directory: another directory named": (
        lambda _m, run: setattr(run, "directory", raising(inputs.edition_dark(mismatch()))),
        "edition_unreadable: EditionMismatchError",
    ),
    "the directory: the CDN": (
        lambda _m, run: setattr(
            run, "directory", raising(inputs.edition_dark(httpx.ConnectError("no route")))
        ),
        "edition_unreadable: ConnectError",
    ),
    "the directory: an API answer that is not JSON": (
        lambda _m, run: setattr(run, "directory", raising(inputs.edition_dark(not_json()))),
        "edition_unreadable: JSONDecodeError",
    ),
    "the directory: a date not written as the build writes it": (
        lambda _m, run: setattr(run, "directory", raising(bad_date())),
        "edition_unreadable: directory files: ValueError",
    ),
    "the directory: not the deployed edition": (
        lambda _m, run: setattr(run, "directory", raising(not_the_deployed_edition())),
        "meta.json and points.bin are not the deployed edition",
    ),
    "coverage": (
        lambda m, _run: m.setattr(cli, "check_coverage", raising(DarkError(Dark.COVERAGE, "0.4"))),
        "coverage: 0.4",
    ),
    "size": (
        lambda m, _run: m.setattr(cli, "check_budget", raising(DarkError(Dark.SIZE, "too large"))),
        "size: too large",
    ),
    "forecast_stale": (
        lambda m, _run: m.setattr(cli, "_pass_file", raising(DarkError(Dark.FORECAST, "9 rows"))),
        "forecast_stale: 9 rows",
    ),
    "the upload held": (
        lambda m, _run: m.setattr(cli, "upload", raising(DarkError(Dark.HELD, "on purpose"))),
        "held: on purpose",
    ),
    "the upload not read back": (
        lambda m, _run: m.setattr(cli, "upload", raising(DarkError(Dark.READ_BACK, "other bytes"))),
        "read_back: other bytes",
    ),
    "the upload refused": (
        lambda m, _run: m.setattr(cli, "upload", raising(PublishError("write: HTTP 500"))),
        "write: HTTP 500",
    ),
    "a host read error on the opens file": (
        lambda _m, run: setattr(run, "host", flaky("/live/opens.json")),
        "opens_unreadable: v1/live/opens.json: read v1/live/opens.json: HTTP 502",
    ),
    "a host read error on a timeline": (
        lambda _m, run: setattr(run, "host", flaky("/live/days/")),
        "day_file_unreadable: v1/live/days/",
    ),
    "another directory's opens file": (
        lambda _m, run: setattr(run, "host", other_directory()),
        "opens_unreadable: ",
    ),
    "a serving error": (
        lambda m, _run: m.setattr(cli, "_pass_file", raising(ServeError("no rates"))),
        "ServeError: no rates",
    ),
}


@pytest.mark.parametrize("case", sorted(INCURABLE))
def test_a_cause_a_restart_cannot_cure_never_asks(case: str, capsys: Any, monkeypatch: Any) -> None:
    arrange, line = INCURABLE[case]
    run = make_pass(MemoryHost(), directory=world.directory())
    run.alerts = lambda: (feed(updated=(run.now() - timedelta(minutes=1)).isoformat()), True)
    arrange(monkeypatch, run)
    ran = looped(capsys, monkeypatch, run=run, minutes=45)
    assert ran.dark == len(ran.passes) >= 5  # every pass dark, well past the row of 3
    assert ran.asked == []
    assert "ending early" not in ran.out
    assert ran.err.count(f"predict: dark ({line}") + ran.err.count(f": {line}") >= ran.dark, ran.err
    assert "unexpected" not in ran.err
    assert ran.out.count(", 0 since the last good pass that newer code may cure") == ran.dark
    assert run._newer_code is False


def refused_edition() -> DarkError:
    """What the handshake gives for an ``edition.json`` with a new key."""
    edition = json.loads(written_edition(world.meta_bytes(), world.points_bytes()).to_json_bytes())
    edition[LATER] = 1
    with pytest.raises(deployed.DeployedEditionError) as refused:
        deployed._checked(json.dumps(edition).encode(), "the CDN")
    assert isinstance(refused.value.__cause__, ValidationError)
    return inputs.edition_dark(refused.value)


def refused_meta() -> DarkError:
    """What the handshake gives for a ``meta.json`` that does not validate."""
    meta = json.loads(world.meta_bytes())
    meta[LATER] = 1
    files = deployed.DirectoryFiles(
        meta_path="schools/meta.json",
        meta=json.dumps(meta).encode(),
        points_path="schools/points.bin",
        points=world.points_bytes(),
        edition=None,
    )
    with pytest.raises(deployed.DeployedEditionError) as refused:
        deployed._edition_of_files(files, "the artifact")
    assert isinstance(refused.value.__cause__, ValidationError)
    return inputs.edition_dark(refused.value)


def refused_files(*, meta: bool) -> DarkError:
    """What ``directory_from_files`` gives for a ``meta.json`` with a new key, or a
    ``points.bin`` that does not decode."""
    edition = written_edition(world.meta_bytes(), world.points_bytes())
    grown_meta = json.loads(world.meta_bytes())
    grown_meta[LATER] = 1
    meta_bytes = json.dumps(grown_meta).encode() if meta else world.meta_bytes()
    points_bytes = world.points_bytes() if meta else b"not points"
    with pytest.raises(DarkError) as dark:
        inputs.directory_from_files(edition, meta_bytes, points_bytes)
    return dark.value


def with_code_99(_m: Any, run: cli.Pass) -> None:
    host = host_of(more=False)
    code_99(host)
    run.host = host


CURABLE: dict[str, tuple[Callable[[Any, cli.Pass], None], str]] = {
    "a status code of 99": (with_code_99, "opens_unreadable: v1/live: ValidationError"),
    "a timeline of another version": (
        lambda _m, run: (setattr(run, "host", host_of(more=True)), version_2(run.host))[0],  # type: ignore[arg-type]
        f"day_file_unreadable: {DAY_FILE} does not validate",
    ),
    "our own file does not validate": (
        lambda m, _run: m.setattr(cli, "checked", raising(DarkError(Dark.INVALID, "1 problem"))),
        "invalid: 1 problem",
    ),
    "the deployed edition.json has a new key": (
        lambda _m, run: setattr(run, "directory", raising(refused_edition())),
        "edition_unreadable: DeployedEditionError",
    ),
    "the deployed meta.json does not validate": (
        lambda _m, run: setattr(run, "directory", raising(refused_meta())),
        "edition_unreadable: DeployedEditionError",
    ),
    "the meta.json read has a new key": (
        lambda _m, run: setattr(run, "directory", raising(refused_files(meta=True))),
        "edition_unreadable: directory files: ValidationError",
    ),
    "a points.bin that does not decode": (
        lambda _m, run: setattr(run, "directory", raising(refused_files(meta=False))),
        "edition_unreadable: directory files: PointsFormatError",
    ),
}


@pytest.mark.parametrize("case", sorted(CURABLE))
def test_a_file_of_ours_that_does_not_validate_counts(
    case: str, capsys: Any, monkeypatch: Any
) -> None:
    arrange, line = CURABLE[case]
    run = make_pass(MemoryHost(), directory=world.directory())
    run.alerts = lambda: (feed(updated=(run.now() - timedelta(minutes=1)).isoformat()), True)
    arrange(monkeypatch, run)
    ran = looped(capsys, monkeypatch, run=run)
    assert ran.dark == 3
    assert ran.passes == at(GRID, (0, 0), (10, 0), (20, 0))
    assert len(ran.asked) == 1
    assert ran.err.count(f"predict: dark ({line})\n") == 3, ran.err
    assert ran.out.endswith(ENDING)
    assert run._newer_code is True


def test_the_directory_marker() -> None:
    assert type(refused_edition()) is host_files.Refused
    assert type(refused_meta()) is host_files.Refused
    assert type(refused_files(meta=True)) is host_files.Refused
    assert type(refused_files(meta=False)) is host_files.Refused
    assert isinstance(refused_files(meta=False).__cause__, PointsFormatError)
    assert issubclass(host_files.Refused, DarkError)
    for error in (
        deployed.DeployedEditionError("the API said no"),
        deployed.DeployInProgressError("deploying"),
        mismatch(),
        httpx.ConnectError("no route"),
        httpx.ReadTimeout("slow"),
        not_json(),
        ValueError("its date is not written once as the build writes it"),
    ):
        dark = inputs.edition_dark(error)
        assert type(dark) is DarkError
        assert str(dark) == f"edition_unreadable: {type(error).__name__}"
    assert str(inputs.edition_dark(ValueError("x"), "directory files: ")) == (
        "edition_unreadable: directory files: ValueError"
    )


def test_only_a_good_pass_breaks_the_row(capsys: Any, monkeypatch: Any) -> None:
    # Curable, curable, good, curable, curable, then good for the rest: never three in a row.
    ran = looped(
        capsys, monkeypatch, script=["curable", "curable", "good", "curable", "curable", "good"]
    )
    assert ran.asked == []
    assert ran.dark == 4
    assert "ending early" not in ran.out
    # A dark pass of another cause neither counts nor resets: the third curable pass ends it.
    ran = looped(capsys, monkeypatch, script=["curable", "curable", "feed", "curable"])
    assert ran.asked == [ran.passes[3]]
    assert len(ran.passes) == ran.dark == 4
    assert ran.out.endswith(ENDING)
    lines = [text for text in ran.out.splitlines() if text.startswith("predict: pass")]
    assert [text.rsplit(", ", 1)[1].split(" ", 1)[0] for text in lines] == ["1", "2", "2", "3"]
    # On the same head the row reaches 3 and stays: a dark pass of another cause asks nothing.
    ran = looped(
        capsys, monkeypatch, script=["curable", "curable", "curable", "feed"], head=MINE, minutes=35
    )
    assert ran.asked == [ran.passes[2]]
    assert len(ran.passes) >= 4
    assert ran.out.count(", 3 since the last good pass") == len(ran.passes) - 2


def test_each_pass_prints_its_two_times(capsys: Any, monkeypatch: Any) -> None:
    clock = [GRID]
    run = make_pass(MemoryHost(), directory=world.directory())
    run.now = lambda: clock[0]
    run.alerts = lambda: (feed(updated=clock[0].isoformat()), True)
    served = [0]

    def serve_pass(_run: cli.Pass, *, grid: bool) -> int:  # noqa: ARG001 - the pass's own signature
        served[0] += 1
        if served[0] == 1:
            clock[0] += timedelta(seconds=41.2)
            return 0
        clock[0] += timedelta(seconds=9.8)
        raise RuntimeError("before the view")

    def view(_run: cli.Pass) -> None:
        clock[0] += timedelta(seconds=6.0)

    def sleep(seconds: float) -> None:
        clock[0] += timedelta(seconds=seconds)

    monkeypatch.setattr(cli, "_serve_pass", serve_pass)
    monkeypatch.setattr(cli, "live_view", view)
    capsys.readouterr()
    until = GRID + timedelta(minutes=12)
    assert cli.loop(run, until, cli.Loop(lambda: clock[0], sleep), lambda _s: None) == 1
    lines = [text for text in capsys.readouterr().out.splitlines() if "pass" in text]
    assert lines == [
        "predict: pass 1 (grid) ok in 41.2 s, the live view 6.0 s more",
        "predict: pass 2 (extra) dark in 9.8 s, the live view 0.0 s more, 1 since the last good "
        "pass that newer code may cure",
    ]
    # A clock that steps back during a pass prints 0.0, never a time below it.
    back = cli.Pass.__new__(cli.Pass)
    back._served_at = GRID - timedelta(seconds=5)
    assert cli._pass_times(back, 3, GRID, GRID - timedelta(seconds=9), grid=True, dark=False) == (
        "predict: pass 3 (grid) ok in 0.0 s, the live view 0.0 s more"
    )


# --- the branch head ----------------------------------------------------------------------------

BRANCH = "claude/keen-faraday-oy7yqw"
ENV = {
    "GITHUB_SHA": MINE,
    "GITHUB_REPOSITORY": "viaate/jsalcards",
    "GITHUB_REF_NAME": BRANCH,
    "GITHUB_REF_TYPE": "branch",
    "GITHUB_TOKEN": "the-job-token",
    "LIVE_HOST_TOKEN": "the-live-host-token",
}


def answering(answer: Any, seen: list[httpx.Request]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(answer, Exception):
            raise answer
        return answer  # type: ignore[no-any-return]

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_the_branch_head_question(capsys: Any) -> None:
    seen: list[httpx.Request] = []
    good = httpx.Response(200, json={"ref": f"refs/heads/{BRANCH}", "object": {"sha": NEWER}})
    with answering(good, seen) as http:
        assert cli.branch_head(http, "viaate/jsalcards", BRANCH, "the-job-token") == NEWER
        ask = cli.head_reader(ENV, http)
        assert ask is not None
        assert ask() == NEWER
        assert (
            cli.head_reader({**ENV, "GITHUB_API_URL": "https://ghe.example/api/v3/"}, http)()
            == NEWER
        )  # type: ignore[misc]
    first, second, third = seen
    for request in (first, second):
        assert request.method == "GET"
        assert request.url.host == "api.github.com"
        # The branch's slash is literal.
        assert request.url.raw_path == b"/repos/viaate/jsalcards/git/ref/heads/" + BRANCH.encode()
        assert request.headers["Accept"] == "application/vnd.github+json"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert request.headers["Authorization"] == "Bearer the-job-token"
        assert request.extensions["timeout"] == {
            "connect": 5.0,
            "read": 10.0,
            "write": 10.0,
            "pool": 10.0,
        }
    assert (
        str(third.url)
        == f"https://ghe.example/api/v3/repos/viaate/jsalcards/git/ref/heads/{BRANCH}"
    )
    for request in seen:
        assert "the-live-host-token" not in str(request.url)
        assert all("the-live-host-token" not in value for value in request.headers.values())
    assert capsys.readouterr().err == ""
    # A branch name with other characters is quoted, its slashes kept.
    with answering(good, seen) as http:
        cli.branch_head(http, "viaate/jsalcards", "fix/a b#c", "t")
    assert seen[-1].url.raw_path.endswith(b"/git/ref/heads/fix/a%20b%23c")
    failures = {
        "HTTP 404": httpx.Response(404, json={"message": "Not Found"}),
        "HTTP 500": httpx.Response(500, text="the-live-host-token"),
        "ReadTimeout": httpx.ReadTimeout("slow"),
        "ConnectError": httpx.ConnectError("no route"),
        "JSONDecodeError": httpx.Response(200, text="<html>"),
        "not a commit id": httpx.Response(200, json={"object": {"sha": NEWER[:39]}}),
        "KeyError": httpx.Response(200, json={"object": {}}),
        "TypeError": httpx.Response(200, json={"object": None}),
    }
    for why, answer in failures.items():
        cli._HEAD_SAID.clear()
        with answering(answer, []) as http:
            assert cli.branch_head(http, "viaate/jsalcards", BRANCH, "the-job-token") is None, why
            assert cli.branch_head(http, "viaate/jsalcards", BRANCH, "the-job-token") is None
        err = capsys.readouterr().err
        # Two failures in one process: one warning. Never a token or a body.
        assert err == f"warning: predict: the branch head did not answer ({why}): the run goes on\n"
    assert cli.branch_head(answering(httpx.Response(200, json=[1]), []), "r/r", "b", "t") is None
    assert capsys.readouterr().err == ""  # still the same process: said once


def test_the_head_is_asked_only_by_a_job_on_a_branch() -> None:
    seen: list[httpx.Request] = []
    http = answering(httpx.Response(200, json={"object": {"sha": NEWER}}), seen)
    assert cli.head_reader(ENV, http) is not None
    for name in ("GITHUB_SHA", "GITHUB_REPOSITORY", "GITHUB_REF_NAME", "GITHUB_TOKEN"):
        assert (
            cli.head_reader({key: value for key, value in ENV.items() if key != name}, http) is None
        )
        assert cli.head_reader({**ENV, name: ""}, http) is None
    assert cli.head_reader({**ENV, "GITHUB_REF_TYPE": "tag"}, http) is None
    assert (
        cli.head_reader(
            {key: value for key, value in ENV.items() if key != "GITHUB_REF_TYPE"}, http
        )
        is None
    )
    assert cli.head_reader({**ENV, "GITHUB_SHA": "abc1234"}, http) is None
    assert cli.head_reader({}, http) is None
    assert seen == []  # making the reader asks nothing


def test_the_start_up_line() -> None:
    assert cli.head_line(MINE, MINE) == "predict run: on aaaaaaa, the branch head"
    assert cli.head_line(MINE, NEWER) == "predict run: on aaaaaaa; the branch head is bbbbbbb"
    assert cli.head_line(MINE, None) == "predict run: on aaaaaaa; the branch head did not answer"


# --- the start-up without the weather service ---------------------------------------------------


class Catalog:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def boundaries_for(self, kind: str, _day: date) -> Any:
        self.asked.append(kind)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer.get(kind)


def test_start_up_fails_cleanly_without_any_boundaries() -> None:
    today = date(2026, 11, 10)
    for error in (FetchError("giving up"), BoundaryError("no release is listed")):
        with pytest.raises(cli.ConfigError) as refused:
            cli.load_boundaries(Catalog(error), today)  # type: ignore[arg-type]
        assert str(refused.value) == (
            "the NWS boundaries cannot be had and no cached copy holds them "
            f"({type(error).__name__})"
        )
    for answer in ({}, {"zone": object()}, {"county": object()}):
        with pytest.raises(cli.ConfigError, match=r"^no NWS boundary release is in effect$"):
            cli.load_boundaries(Catalog(answer), today)  # type: ignore[arg-type]
    zones, counties = object(), object()
    both = Catalog({"zone": zones, "county": counties})
    assert cli.load_boundaries(both, today) == (zones, counties)  # type: ignore[arg-type]
    assert both.asked == ["zone", "county"]
    # Another error is not swallowed.
    with pytest.raises(KeyError):
        cli.load_boundaries(Catalog(KeyError("x")), today)  # type: ignore[arg-type]


def test_a_saved_zone_map_is_reported(capsys: Any, tmp_path: Path) -> None:
    now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    output = tmp_path / "output"
    env = {"GITHUB_OUTPUT": str(output)}
    run = make_pass(MemoryHost(), directory=world.directory())
    newest = date(2026, 3, 18)

    def pages(days: int) -> dict[str, tuple[datetime, date]]:
        checked = now - timedelta(days=days)
        return {"zone": (checked, newest), "county": (checked, date(2026, 3, 5))}

    # A start on a fresh answer: nothing kept, nothing said.
    assert cli.note_boundaries(run, now, env) is False
    assert run.state.boundaries_held_since is None
    # The first held start sets the time; the second keeps it.
    run.boundaries_held, run.boundaries_pages = True, pages(6)
    assert cli.note_boundaries(run, now, env) is False
    assert run.state.boundaries_held_since == now
    assert cli.note_boundaries(run, now + timedelta(hours=23), env) is False
    assert run.state.boundaries_held_since == now
    assert capsys.readouterr().err == ""
    assert not output.exists()
    # The key is in the state file only while it is set, and reads back.
    path = tmp_path / "state.json"
    cli.save_state(path, run.state)
    assert json.loads(path.read_text())["boundaries_held_since"] == now.isoformat()
    assert cli.load_state(path).boundaries_held_since == now
    # A day on the saved copy: the warning and the step output.
    assert cli.note_boundaries(run, now + timedelta(hours=24), env) is True
    assert capsys.readouterr().err == (
        "warning: predict run: the NWS boundaries come from a saved copy since "
        "2026-11-10T12:00Z (county: page checked 2026-11-04T12:00Z, newest release listed "
        "2026-03-05; zone: page checked 2026-11-04T12:00Z, newest release listed 2026-03-18): "
        "the zones may be out of date\n"
    )
    assert output.read_text() == "boundaries=held\n"
    # Only a release file fell back: no page is named.
    run.boundaries_pages = {}
    assert cli.note_boundaries(run, now + timedelta(hours=30), {}) is True
    assert capsys.readouterr().err == (
        "warning: predict run: the NWS boundaries come from a saved copy since "
        "2026-11-10T12:00Z: the zones may be out of date\n"
    )
    assert output.read_text() == "boundaries=held\n"
    # A start on a fresh answer clears the time, and the key leaves the file.
    run.boundaries_held = False
    assert cli.note_boundaries(run, now + timedelta(hours=31), env) is False
    assert run.state.boundaries_held_since is None
    cli.save_state(path, run.state)
    assert "boundaries_held_since" not in json.loads(path.read_text())
    assert cli.load_state(path).boundaries_held_since is None
    for unreadable in ("yesterday", 7, None, "2026-11-10T12:00:00"):
        assert State.from_json({"boundaries_held_since": unreadable}).boundaries_held_since is None
    # A saved page checked over 7 days ago: both on the first held start.
    output.unlink()
    old = make_pass(MemoryHost(), directory=world.directory())
    old.boundaries_held, old.boundaries_pages = True, {"zone": pages(8)["zone"]}
    assert cli.note_boundaries(old, now, env) is True
    assert old.state.boundaries_held_since == now
    assert "zone: page checked 2026-11-02T12:00Z, newest release listed 2026-03-18" in (
        capsys.readouterr().err
    )
    assert output.read_text() == "boundaries=held\n"
    # Exactly 7 days is not yet old.
    edge = make_pass(MemoryHost(), directory=world.directory())
    edge.boundaries_held, edge.boundaries_pages = True, pages(7)
    assert cli.note_boundaries(edge, now, {}) is False

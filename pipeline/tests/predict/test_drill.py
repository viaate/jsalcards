"""The storm drill (predict-next STORM-DRILL): one scripted storm through the real loop and pass,
and the storm-size night at a small scale. Every district is a real LEAID of the committed
model on a made-up point; every product, run and night value is made up."""

import ast
import builtins
import copy
import dataclasses
import fcntl
import io
import json
import math
import os
import pickle
import re
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import httpx
import pytest
import shapely

from snowlight.cli import main
from snowlight.predict import (
    artifact,
    cli,
    drill,
    exposure,
    forecast_adjust,
    forecast_history,
    forecast_live,
    inputs,
    ndfd,
    outlook_live,
    serve,
)
from snowlight.predict.alerts_live import live_events, live_heads_ups
from snowlight.predict.config import PIPELINE_ROOT, PredictConfig
from snowlight.predict.publish import Mode
from snowlight.predict.situations import Situation, WeatherClass
from snowlight.schemas.live import DayTimeline
from snowlight.schemas.predictions import Forecast, PredictionsFile
from snowlight.sources.nws.alerts import parse_active

PIPELINE: Path = PIPELINE_ROOT
WEB: Path = PIPELINE_ROOT.parent / "web" / "src"
TIMING: frozenset[str] = frozenset({"seconds", "cpu", "xz_seconds", "rss_mb"})
SIZE_KEYS: frozenset[str] = frozenset({"size", "frozen_size", "rss_mb"})


@dataclasses.dataclass
class Inputs:
    config: PredictConfig
    committed: artifact.ModelArtifact
    exposure: exposure.Exposure


@dataclasses.dataclass
class Spied:
    result: drill.Result
    """The run's result, its ``Pass`` dropped (it holds the pass's closures): what a test reads
    of the ``Pass`` is kept beside it."""
    loops: int
    nows: list[datetime]
    sleeps: list[float]
    host: object
    """The ``Pass``'s host."""
    mode: Mode
    """The ``Pass``'s mode."""


def _once[T](factory: pytest.TempPathFactory, name: str, build: Callable[[], T]) -> T:
    """``build()`` once in the session: under pytest-xdist the first worker that needs it builds
    it under a lock and leaves it pickled in the session's shared temp folder, and every other
    worker loads that (each worker would otherwise run the whole drill again)."""
    if os.environ.get("PYTEST_XDIST_WORKER") is None:
        return build()
    shared = factory.getbasetemp().parent
    kept = shared / f"drill-{name}.pickle"
    with (shared / f"drill-{name}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if kept.exists():
            return cast(T, pickle.loads(kept.read_bytes()))  # noqa: S301 - this session's own
        value = build()
        kept.write_bytes(pickle.dumps(value))
        return value


@pytest.fixture(scope="module")
def world_inputs() -> Inputs:
    return Inputs(PredictConfig.load(), artifact.load(), exposure.load())


@pytest.fixture(scope="module")
def story(world_inputs: Inputs, tmp_path_factory: pytest.TempPathFactory) -> Spied:
    """One plain run, with wrapping spies on ``cli.loop`` and ``cli.one_pass`` for it only, and
    ``time.sleep`` raising (a read-back that waited would fail the story in seconds)."""

    def build() -> Spied:
        loops: list[int] = []
        nows: list[datetime] = []
        sleeps: list[float] = []
        real_loop, real_pass = cli.loop, cli.one_pass

        def loop(*args: Any, **kwargs: Any) -> int:
            loops.append(1)
            return real_loop(*args, **kwargs)

        def one_pass(run: cli.Pass, *, grid: bool = True) -> int:
            nows.append(run.now())
            return real_pass(run, grid=grid)

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            raise AssertionError(f"the story slept {seconds} s for real")

        temp = tmp_path_factory.mktemp("drill-story")
        labels = temp / "labels"
        labels.mkdir()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(cli, "loop", loop)
            patch.setattr(cli, "one_pass", one_pass)
            patch.setattr(time, "sleep", sleep)
            result = drill.run_story(
                world_inputs.config, world_inputs.committed, world_inputs.exposure, labels, temp
            )
        run = result.story.run
        kept = dataclasses.replace(result.story, run=cast(cli.Pass, None))
        return Spied(
            dataclasses.replace(result, story=kept), len(loops), nows, sleeps, run.host, run.mode
        )

    return _once(tmp_path_factory, "story", build)


@dataclasses.dataclass
class Guarded:
    document: dict[str, Any]
    printed: list[str]
    code: int
    calls: Counter[str]
    sleeps: list[float]
    writes: list[str]
    tmpdir: Path
    json_path: Path
    out_before: dict[str, tuple[int, int]]
    out_after: dict[str, tuple[int, int]]
    left: list[str]


def _snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    if not folder.exists():
        return {}
    return {
        str(p.relative_to(folder)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(folder.rglob("*"))
    }


_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND
GUARDED_ARGS: tuple[str, ...] = ("predict", "drill", "--size", "--scale", "0.01")


def _at(path: Any, dir_fd: int | None) -> str:
    """A path as written: relative to ``dir_fd``'s folder where one is given."""
    if dir_fd is None:
        return str(os.fspath(path))
    folder: Path = Path(f"/proc/self/fd/{dir_fd}").readlink()
    return str(folder / os.fspath(path))


@pytest.fixture(scope="module")
def guarded(tmp_path_factory: pytest.TempPathFactory) -> Guarded:
    """One run of the command, ``snowlight predict drill --size --scale 0.01 --json FILE``
    through the CLI's ``main`` (test 13's run), under test 3's patches (every way out of the
    process records the call and raises) and test 4's sandbox (cwd, ``HOME`` and ``TMPDIR`` in
    a test folder; every write spied, through a folder's descriptor too), undone after it."""
    return _once(tmp_path_factory, "guarded", lambda: _guarded(tmp_path_factory))


def _guarded(tmp_path_factory: pytest.TempPathFactory) -> Guarded:
    home = tmp_path_factory.mktemp("drill-guarded")
    tmpdir = home / "tmp"
    tmpdir.mkdir()
    json_path = home / "out" / "drill.json"
    json_path.parent.mkdir()
    calls: Counter[str] = Counter()
    sleeps: list[float] = []
    writes: list[str] = []

    def refuse(name: str) -> Callable[..., Any]:
        def call(*_args: Any, **_kwargs: Any) -> Any:
            calls[name] += 1
            raise AssertionError(f"the drill called {name}")

        return call

    real_open, real_os_open = builtins.open, os.open
    real_replace, real_rename, real_mkdir = os.replace, os.rename, os.mkdir

    def spy_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, str | os.PathLike) and any(c in mode for c in "wax+"):
            writes.append(os.fspath(file))
        return real_open(file, mode, *args, **kwargs)

    def spy_os_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if flags & _WRITE_FLAGS:
            writes.append(_at(path, kwargs.get("dir_fd")))
        return real_os_open(path, flags, *args, **kwargs)

    def spy_replace(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
        writes.append(_at(dst, kwargs.get("dst_dir_fd")))
        real_replace(src, dst, *args, **kwargs)

    def spy_rename(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
        writes.append(_at(dst, kwargs.get("dst_dir_fd")))
        real_rename(src, dst, *args, **kwargs)

    def spy_mkdir(path: Any, *args: Any, **kwargs: Any) -> None:
        writes.append(_at(path, kwargs.get("dir_fd")))
        real_mkdir(path, *args, **kwargs)

    out = PIPELINE_ROOT / "out"
    before = _snapshot(out)
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(home)
        patch.setenv("HOME", str(home))
        patch.setenv("TMPDIR", str(tmpdir))
        patch.setattr(tempfile, "tempdir", str(tmpdir))
        patch.setattr(sys, "dont_write_bytecode", True)
        for owner, name in (
            (socket.socket, "connect"),
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (httpx.Client, "send"),
            (httpx.AsyncClient, "send"),
            (cli, "make_pass"),
            (cli, "make_host"),
            (inputs, "read_deployed"),
        ):
            patch.setattr(owner, name, refuse(name))
        patch.setattr(time, "sleep", sleeps.append)
        patch.setattr(builtins, "open", spy_open)
        patch.setattr(io, "open", spy_open)
        patch.setattr(os, "open", spy_os_open)
        patch.setattr(os, "replace", spy_replace)
        patch.setattr(os, "rename", spy_rename)
        patch.setattr(os, "mkdir", spy_mkdir)
        with io.StringIO() as sink, pytest.MonkeyPatch.context() as quiet:
            quiet.setattr(sys, "stdout", sink)
            code = main([*GUARDED_ARGS, "--json", str(json_path)])
            printed = sink.getvalue().splitlines()
    return Guarded(
        document=json.loads(json_path.read_text()),
        printed=printed,
        code=code,
        calls=calls,
        sleeps=sleeps,
        writes=writes,
        tmpdir=tmpdir,
        json_path=json_path,
        out_before=before,
        out_after=_snapshot(out),
        left=[p.name for p in tmpdir.iterdir()],
    )


SIZE_WORLDS: tuple[tuple[float, str | None], ...] = ((0.0, None), (1.0, "typical"))
"""Test 10's worlds: the calibration world and the typical mix at 100% (the gate's world, 37%
worst, runs in ``guarded``, and the night's other four in the CI job's and the hand's runs)."""


@pytest.fixture(scope="module")
def sizes(world_inputs: Inputs, tmp_path_factory: pytest.TempPathFactory) -> drill.SizeNight:
    def build() -> drill.SizeNight:
        temp = tmp_path_factory.mktemp("drill-sizes")
        labels = temp / "labels"
        labels.mkdir()
        lines: list[str] = []
        night = drill.size_night(
            world_inputs.config,
            world_inputs.committed,
            labels,
            temp,
            scale=0.01,
            worlds=SIZE_WORLDS,
            say=lines.append,
        )
        night.worlds.extend(lines)
        return night

    return _once(tmp_path_factory, "sizes", build)


def _cells(result: drill.Result, key: str, moment: str) -> list[drill.Cell]:
    found = [result.cells[(i, moment)] for i in result.story.world.of(key)]
    assert all(isinstance(c, drill.Cell) for c in found)
    return cast(list[drill.Cell], found)


def _without_timing(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_timing(v) for k, v in value.items() if k not in TIMING}
    if isinstance(value, list):
        return [_without_timing(v) for v in value]
    return value


def _feed_changes(products: tuple[drill.Product, ...]) -> list[datetime]:
    found = set()
    for p in products:
        found.add(p.sent)
        found.add(p.sent + timedelta(hours=1) if p.ending else p.ends)
    return sorted(t for t in found if drill.START < t < drill.UNTIL)


def _pass(**changes: Any) -> drill.SizePass:
    base = drill.SizePass(
        share=0.37,
        mix="worst",
        at="02:30Z",
        seconds=1.0,
        cpu=1.0,
        dark=False,
        raw=100,
        gzip=10,
        lines=5,
        previous=5,
        nights=4,
        storm=4,
        covered=4,
        schools=3,
        outlooks=3,
        private_previous=2,
        records=0,
        own=0,
        ladder=(),
    )
    return dataclasses.replace(base, **changes)


def _night(
    *changed: drill.SizePass, others: tuple[drill.SizePass, ...] = ()
) -> list[drill.SizePass]:
    """The gate world's nine whole passes, each of ``changed`` in place of the one at its time,
    then ``others``."""
    by_at = {p.at: p for p in changed}
    ats = [f"{t:%H:%M}Z" for t in drill.PASSES]
    assert set(by_at) <= set(ats)
    return [by_at.get(at, _pass(at=at)) for at in ats] + list(others)


_TOP_IMPORTS = """
import ast, importlib, json, sys
tree = ast.parse(open(sys.argv[1]).read())
names = []
for node in tree.body:
    if isinstance(node, ast.Import):
        names += [a.name for a in node.names]
    elif isinstance(node, ast.ImportFrom) and node.module:
        names += [node.module] + [f"{node.module}.{a.name}" for a in node.names]
for name in names:
    try:
        importlib.import_module(name)
    except ModuleNotFoundError:
        pass  # a name the module defines, not a submodule
before = set(sys.modules)
opened = []
sys.addaudithook(lambda e, a: opened.append(str(a[0])) if e == "open" else None)
import snowlight.predict.drill
mark = len(opened)
unloaded = "snowlight.predict.cli" not in sys.modules
import snowlight.predict.cli
print(json.dumps({"opened": opened[:mark], "cli_unloaded": unloaded,
                  "new": sorted(set(sys.modules) - before)}))
"""

_IMPORT_COST = """
import json, sys, time, types
if sys.argv[1] == "base":
    stub = types.ModuleType("snowlight.predict.drill")
    stub.register = lambda actions: None
    sys.modules["snowlight.predict.drill"] = stub
started = time.perf_counter()
import snowlight.predict.cli
took = time.perf_counter() - started
print(json.dumps({"took": took, "modules": sorted(sys.modules)}))
"""


def _python(code: str, *args: str, env: dict[str, str] | None = None) -> str:
    found = subprocess.run(  # noqa: S603 - this interpreter, a fixed script
        [sys.executable, "-c", code, *args],
        cwd=PIPELINE,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return found.stdout.strip().splitlines()[-1]


class _NoListing:
    """A fetcher whose day listings fail (the real reader's runs then read as unknown)."""

    def get(self, url: str) -> bytes:
        raise ndfd.NdfdError(f"no listing in the drill's test ({url})")

    def opener(self) -> Callable[[ndfd.Listed], bytes]:
        def opened(listed: ndfd.Listed) -> bytes:
            raise ndfd.NdfdError(listed.url)

        return opened


_AUDIT = """
import json, os, sys
import snowlight.predict.cli, snowlight.predict.drill
from snowlight.cli import main
opened = []
def hook(event, args):
    if event == "open":
        path = "" if isinstance(args[0], int) else os.fspath(args[0])
        opened.append([path, args[1], args[2]])
sys.addaudithook(hook)
code = main(["predict", "drill", "--labels", sys.argv[1]])
print(json.dumps({"code": code, "opened": opened}))
"""

_WRITE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _read_only(mode: str | None, flags: int) -> bool:
    if mode is not None and any(c in mode for c in "wax+"):
        return False
    return not flags & _WRITE


# The tests run in this order so that under pytest-xdist each of the first four workers starts a
# different build (the story, the guarded command, the size night, the subprocesses), and the
# tests that only read a build come after it is made.


def test_the_drill_runs_the_real_loop_and_pass_on_its_clock(
    story: Spied, world_inputs: Inputs
) -> None:
    result = story.result
    run = result.story
    assert story.loops == 1
    assert len(story.nows) == run.passes == 96
    assert run.dark == 0
    assert story.sleeps == []  # every read-back confirmed at once: no real wait
    uploads = [when for when, _data in run.host.uploads()]
    assert story.nows == uploads  # each pass's own clock is the faked one, and it published
    assert all(
        PredictionsFile.from_json_bytes(data).generated_at == when
        for when, data in run.host.uploads()
    )
    grid = [t for t in uploads if t.minute in {7, 37}]
    expected_grid = []
    t = drill.START.replace(minute=7)
    while t < drill.UNTIL:
        expected_grid.append(t)
        t += timedelta(minutes=30)
    assert grid == expected_grid
    changes = _feed_changes(run.world.products)
    for change in changes:
        assert any(change <= t <= change + timedelta(minutes=10) for t in uploads), change
    for extra in (t for t in uploads if t.minute not in {7, 37} and t != drill.START):
        assert any(c <= extra <= c + timedelta(minutes=10) for c in changes), extra
    # The late story's 4 PM Pacific Monday cell is the upload current at 00:00Z Tuesday.
    late = run.world.of("late")[0]
    at = drill.moment_at(run.world, late, drill.MOMENTS[0])
    assert at == datetime(2027, 1, 12, 0, 0, tzinfo=UTC)
    when, data = [(w, d) for w, d in run.host.uploads() if w <= at][-1]
    assert when == datetime(2027, 1, 11, 23, 37, tzinfo=UTC)
    entry = PredictionsFile.from_json_bytes(data).districts[late].days[1]
    assert isinstance(entry, Forecast)
    cell = result.cells[(late, "d1_1600")]
    assert isinstance(cell, drill.Cell)
    assert cell.p == drill.percent(entry.p_no_school)
    # The panel heads the moment's own day at every moment of the story.
    assert drill.OTHER_DAY not in result.cells.values()
    # With the uploads after 20:00Z Monday struck, no 9:30 PM cell shows a number.
    cut = drill.DrillHost(run.host._now)
    cut.log = [
        item
        for item in run.host.log
        if item[1] != drill.LATEST or item[0] <= datetime(2027, 1, 11, 20, tzinfo=UTC)
    ]
    struck = drill.cells(dataclasses.replace(run, host=cut), world_inputs.config)
    nine = [struck[(i, "d1_2130")] for i in range(len(run.world.leaids))]
    assert nine == [drill.NO_NUMBER] * len(run.world.leaids)
    assert not any(drill.calm(c) for c in nine)


def test_every_risk_row_shows_today(story: Spied) -> None:
    result = story.result
    model, world = result.story.model, result.story.world
    assert [v.row for v in result.verdicts] == [
        "B1", "C3", "B3", "B4", "B2", "B5", "B6", "C1", "C2", "C4",
    ]  # fmt: skip
    assert all(v.shows for v in result.verdicts), [v.text() for v in result.verdicts]
    assert all(c.calm for c in _cells(result, "watch", "d1_1600"))
    eight = _cells(result, "watch", "d1_2000")
    late = _cells(result, "watch", "d1_2130")
    assert all(c.p == c.points and not c.forecast for c in eight)
    assert [c.p for c in eight] == [49, 45, 44, 41, 38, 29]
    picks = world.of("watch")
    assert [c.p for i, c in zip(picks, late, strict=True) if world.inches[i] == 20.0] == [
        90,
        91,
        87,
    ]
    assert [c.p for i, c in zip(picks, late, strict=True) if world.inches[i] == 3.0] == [
        39,
        34,
        29,
    ]
    cancel = _cells(result, "cancel", "d0_0500")
    nine = _cells(result, "cancel", "d1_2130")
    assert [c.p for c in nine] == [65, 46, 47, 38]
    assert all(c.calm and c.said == "down" for c in cancel)
    assert [c.prev for c in cancel] == [c.p for c in nine]
    for key, moment in (("late", "d0_0630"), ("half", "d1_2130"), ("coldadv", "d0_0500")):
        assert all(c.calm for c in _cells(result, key, moment)), key
    two = _cells(result, "daytwo", "d0_1600")
    assert all(c.calm and c.after and c.borrowed for c in two)
    assert not any(
        isinstance(c, drill.Cell) and c.after
        for (i, _m), c in result.cells.items()
        if world.stories[i].key != "daytwo"
    )
    blizzard = _cells(result, "blizzard", "d1_2130")
    assert [c.p for c in blizzard] == [42, 39, 38, 35]
    assert [c.p for c in blizzard] == [
        drill.level(model, i, WeatherClass.SNOW_WARNING) for i in world.of("blizzard")
    ]
    assert not any(c.forecast for c in blizzard)
    cold = _cells(result, "extcold", "d1_2130")
    assert [c.p for c in cold] == [6, 10, 10, 12]
    assert [c.p for c in cold] == [
        drill.level(model, i, WeatherClass.COLD) for i in world.of("extcold")
    ]
    assert all(c.base == "class" and not c.forecast for c in cold)
    for key, weather in (("blizzard", WeatherClass.SNOW_WARNING), ("extcold", WeatherClass.COLD)):
        position = serve.SITUATION_POSITION[Situation.of(weather, False).key]
        for i in world.of(key):
            p = float(model.p[i, position])
            assert round(p, 2) == p  # the level the file serves, in hundredths
            assert drill.level(model, i, weather) == drill.percent(p)
    assert "the cold class starts at 0.10" in result.verdicts[8].line
    over = _cells(result, "overnight", "d0_0500")
    assert [(c.points, c.p) for c in over] == [(7, 4), (7, 4), (7, 4), (6, 3)]
    assert all(c.forecast for c in over)


def test_the_drill_never_leaves_the_process(guarded: Guarded) -> None:
    assert sum(guarded.calls.values()) == 0, guarded.calls
    assert guarded.sleeps == []  # every read-back confirmed at once: no wait at all
    assert guarded.code == 0
    assert guarded.document["run"]["passes"] == 96
    assert len(guarded.document["size"]) == len(drill.PASSES)


def test_the_drill_writes_only_its_own_folder(guarded: Guarded) -> None:
    assert guarded.writes
    for path in guarded.writes:
        resolved = Path(path).resolve()
        assert resolved == guarded.json_path.resolve() or resolved.is_relative_to(
            guarded.tmpdir.resolve()
        ), path
    assert any("snowlight-drill-" in path for path in guarded.writes)
    assert guarded.left == []
    assert guarded.out_after == guarded.out_before


def test_the_size_night_at_a_small_scale(sizes: drill.SizeNight, world_inputs: Inputs) -> None:
    passes = sizes.passes
    assert len(passes) == 1 + len(drill.PASSES)
    quiet = [p for p in passes if p.share == 0]
    assert len(quiet) == 1
    assert quiet[0].covered == 0
    assert quiet[0].whole is None
    assert quiet[0].mix is None
    storm = [p for p in passes if p.share > 0]
    assert all(not p.dark for p in passes)
    assert all(p.whole for p in storm), [(p.share, p.mix, p.at, p.missing()) for p in storm]
    assert all(p.own == 0 for p in passes)
    assert [(p.share, p.mix) for p in passes] == [SIZE_WORLDS[0]] + [SIZE_WORLDS[1]] * len(
        drill.PASSES
    )
    assert [p.at for p in storm] == [f"{t:%H:%M}Z" for t in drill.PASSES]
    assert "183 districts" in sizes.worlds[0]
    assert "221 private" in sizes.worlds[0]
    assert "lattice side 14" in sizes.worlds[0]
    assert sum(1 for line in sizes.worlds if "under the night limit" in line) == len(passes)
    assert len(sizes.frozen) == len(SIZE_WORLDS)
    for item in sizes.frozen:
        assert item.lines > 0
        assert item.xz > 0
        assert item.d1_rows >= 2
    for item in sizes.frozen[1:]:
        assert item.taken == 4 * item.zones
        assert item.missed == 0
        assert item.late_s <= 3600
    assert sizes.rss_mb > 0
    # The full night's worlds, in order, and each share's storm on the same lattice.
    assert drill.worlds_of(full=False) == [drill.GATE]
    assert drill.worlds_of(full=True) == [(0.0, None)] + [
        (s, m) for s in drill.SHARES for m in drill.MIXES
    ]
    grid = drill.lattice(world_inputs.committed, 0.01)
    covered = []
    for share in (0.0, *drill.SHARES):
        n, areas = drill.storm_zones(grid, share)
        covered.append(n)
        assert n == math.ceil(share * grid.districts)
        assert set(areas) == (
            {drill.QUIET_ZONE} if n == 0 else {drill.QUIET_ZONE, drill.STORM_ZONE}
        )
        if n:
            overlap = shapely.intersection(areas[drill.STORM_ZONE], areas[drill.QUIET_ZONE])
            assert shapely.area(overlap) == 0
    assert covered == sorted(covered)
    assert covered[-1] == grid.districts


def test_the_live_command_does_not_run_the_drill(capsys: pytest.CaptureFixture[str]) -> None:
    source = Path(drill.__file__)
    found = json.loads(_python(_TOP_IMPORTS, str(source)))
    assert found["cli_unloaded"]
    stem = "drill"
    assert all(Path(p).name.split(".")[0] == stem for p in found["opened"]), found["opened"]
    # Importing cli costs what it cost before the drill: the drill and the store's pure
    # functions are the only modules it adds, and the time stays within a generous bound.
    base = json.loads(_python(_IMPORT_COST, "base"))
    now = json.loads(_python(_IMPORT_COST, "now"))
    added = set(now["modules"]) - set(base["modules"])
    assert added <= {"snowlight.predict.drill", "snowlight.live.evidence", "resource"}, added
    assert now["took"] < 1.5 * base["took"] + 1.0
    with pytest.raises(SystemExit):
        main(["predict", "--help"])
    assert " drill " in capsys.readouterr().out


def test_the_default_run_reads_only_committed_files(tmp_path: Path) -> None:
    """The default run, its record folder given (``--labels DIR``, where the default makes an
    empty one in its temp folder: the one code path), in a fresh process."""
    labels = tmp_path / "labels"
    labels.mkdir()
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    env = {**os.environ, "TMPDIR": str(tmpdir)}
    found = json.loads(_python(_AUDIT, str(labels), env=env))
    assert found["code"] == 0
    prefixes = [Path(p).resolve() for p in {sys.prefix, sys.base_prefix}]
    committed = [(PIPELINE / "config").resolve(), (PIPELINE / "data").resolve()]
    held = {"labels", "frozen"}

    def allowed(path: str, mode: str | None, flags: int) -> bool:
        if not path:
            return True
        name = Path(path)
        if name.suffix in {".py", ".pyc", ".so"} or "zoneinfo" in name.parts:
            return True
        if not name.is_absolute():
            return path in held
        resolved = name.resolve()
        if resolved.is_relative_to(tmpdir.resolve()):
            return True
        reading = _read_only(mode, flags)
        if resolved.is_relative_to(labels.resolve()):
            return reading
        return reading and any(resolved.is_relative_to(p) for p in [*prefixes, *committed])

    bad = [item for item in found["opened"] if not allowed(*item)]
    assert bad == [], bad
    assert any(Path(p).name == "predict.yaml" for p, _m, _f in found["opened"])
    assert any(Path(p).is_relative_to(tmpdir) for p, _m, _f in found["opened"])
    assert list(tmpdir.iterdir()) == []


def test_size_code() -> None:
    said: list[str] = []
    others = (
        _pass(share=0.7, storm=0),
        _pass(share=1.0, mix="typical", lines=0),
        _pass(share=0.0, mix=None, covered=0, storm=0, nights=0, lines=0),
    )
    assert drill.size_code(_night(_pass(at="10:07Z", storm=1, previous=0), others=others)) == 0
    assert drill.size_code(_night(_pass(dark=True)), said.append) == 3
    assert said == ["size gate: 02:30Z dark"]
    for ladder in ((), ("predict: warning: reworded; published it with no night charts",)):
        said.clear()
        assert drill.size_code(_night(_pass(storm=3, ladder=ladder)), said.append) == 3
        assert said == ["size gate: 02:30Z nights on 3 of 4 storm districts"]
    for change, line in (
        ({"lines": 0}, "no forecast line"),
        ({"previous": 0}, "no district previous chance"),
        ({"schools": 0}, "no private school"),
        ({"private_previous": 0}, "no private previous chance"),
    ):
        said.clear()
        assert drill.size_code(_night(_pass(**change)), said.append) == 3
        assert said == [f"size gate: 02:30Z {line}"]
    assert drill.size_code(_night(_pass(at="00:37Z", previous=0, private_previous=0))) == 0
    said.clear()
    assert drill.size_code(_night(_pass(own=7)), said.append) == 3
    assert said == ["records: 02:30Z 7 own bases, no record day"]
    assert drill.size_code(_night(_pass(own=7, records=2))) == 0
    # The gate's world missing, or short of a pass, never passes.
    said.clear()
    assert drill.size_code(list(others), said.append) == 3
    assert said == ["size gate: 0 of 9 passes of the 37% worst world"]
    said.clear()
    assert drill.size_code(_night()[1:], said.append) == 3
    assert said == ["size gate: 8 of 9 passes of the 37% worst world"]


def test_the_host_is_the_drills_and_only_the_public_keys_move(story: Spied) -> None:
    run = story.result.story
    assert story.host is run.host
    assert isinstance(story.host, drill.DrillHost)
    assert story.mode == Mode.ON
    written = {key for _when, key, _data in run.host.log}
    # The stamp beside the chances (predict-next, after the spec) goes up in the same commit.
    assert written == {drill.LATEST, "v1/predictions/stamp.json", drill.TIMELINE}
    assert run.host.reads
    assert all(key.startswith("v1/") for key in run.host.reads)


def test_the_picks_are_real_districts_by_rule(world_inputs: Inputs, story: Spied) -> None:
    committed, places = world_inputs.committed, world_inputs.exposure
    world = story.result.story.world
    assert len(world.leaids) == len(set(world.leaids)) == 38
    for story_ in drill.STORIES:
        chosen = [world.leaids[i] for i in world.of(story_.key)]
        zones = Counter(
            v.time_zone for v in committed.districts.values() if v.state == story_.state
        )
        common = zones.most_common(1)[0][0]
        order = sorted(
            ((places.of(k, v.county)[0] or (0.0, 0.0))[1], k)
            for k, v in committed.districts.items()
            if v.state == story_.state and v.time_zone == common
        )
        n, k = len(order), story_.count
        assert chosen == [order[round(i * (n - 1) / (k - 1))][1] for i in range(k)]
        assert all(committed.districts[x].state == story_.state for x in chosen)
        assert all(committed.districts[x].time_zone == common for x in chosen)
    big = drill.Story("huge", "", "ND", 100_000)
    with pytest.raises(ValueError, match="huge"):
        drill.pick(committed, places, big)


def test_the_feed_and_the_day_read_as_the_services_give_them(
    story: Spied, world_inputs: Inputs
) -> None:
    run = story.result.story
    world, products = run.world, run.world.products
    for p in products:
        feed = parse_active(drill.active_feed(products, p.sent + timedelta(minutes=1)))
        events = [e for e in live_events(feed) + live_heads_ups(feed) if p.zone in e.ugcs]
        parts = [v.strip("/").split(".") for v in p.vtec]
        codes = {(x[1], f"{x[3]}.{x[4]}") for x in parts}
        if p.ending:
            assert not events
            assert any(a.id == drill.feature(p)["properties"]["id"] for a in feed.alerts)  # type: ignore[index]
        else:
            new = {(e.action, e.key.split(".")[1] + "." + e.key.split(".")[2]) for e in events}
            assert {c for c in codes if c[0] == "NEW"} <= {(a, c) for a, c in new}, p
    cancel = next(p for p in products if p.ending)
    alive = cancel.sent + timedelta(minutes=59)
    assert cancel in drill.active_at(products, alive)
    assert cancel not in drill.active_at(products, cancel.sent + timedelta(minutes=60))
    upgrade = [p for p in products if any(".UPG." in v for v in p.vtec)]
    assert len(upgrade) == 1
    assert len(upgrade[0].vtec) == 2
    assert any(".NEW." in v and ".WS.W." in v for v in upgrade[0].vtec)
    history = drill.history_of(products, drill.START - timedelta(days=1), drill.UNTIL)
    assert sorted(a.id for a in history) == sorted({a.id for a in history})
    assert len(history) == len(products) == 11
    data = run.host.held_at(drill.TIMELINE, drill.UNTIL)
    assert data is not None
    timeline = DayTimeline.model_validate_json(data)
    closers = [j for j, d in enumerate(world.district_of) if world.stories[d].key == "daytwo"]
    assert timeline.schools() == tuple(closers)
    closed = serve.closed_districts(timeline, run.model, world_inputs.config.weather.covered_share)
    assert closed == frozenset(world.of("daytwo"))
    assert all(c.base == "pooled" and c.borrowed for c in _cells(story.result, "daytwo", "d0_1600"))
    assert not any(
        isinstance(c, drill.Cell) and c.borrowed
        for (i, _m), c in story.result.cells.items()
        if world.stories[i].key != "daytwo"
    )


def test_the_forecast_and_the_night_go_through_the_real_readers(
    story: Spied, world_inputs: Inputs
) -> None:
    run = story.result.story
    world, model = run.world, run.model
    read = drill.adjust_reader(world_inputs.config, drill.story_script(world))
    for key in ("watch", "late", "daytwo", "extcold"):
        zone = world.tz_of[key]
        before = drill.local(zone, drill.DAY - timedelta(days=1), dtime(20, 59))
        at = drill.local(zone, drill.DAY - timedelta(days=1), dtime(21, 0))
        early = read(model, (drill.DAY,), before).by_day.get(drill.DAY, {})
        assert not any(i in early for i in world.of(key)), key
        found = read(model, (drill.DAY,), at).by_day[drill.DAY]
        for i in world.of(key):
            assert found[i].snow == pytest.approx(world.inches[i]), (key, i)
    zone = world.tz_of["overnight"]
    nine = drill.local(zone, drill.DAY - timedelta(days=1), dtime(21, 0))
    found = read(model, (drill.DAY,), nine).by_day[drill.DAY]
    assert all(found[i].ice == 0.0 for i in world.of("overnight"))
    runs = drill.runs_for(drill.DAY)
    assert runs
    assert all(r.available_at == r.time + timedelta(minutes=50) for r in runs)
    assert all(
        story.result.cells[(i, "d1_2130")].night  # type: ignore[union-attr]
        for i in world.of("watch")
    )
    assert not any(
        story.result.cells[(i, "d1_2130")].night  # type: ignore[union-attr]
        for i in world.of("coldadv")
    )


def test_the_cell_heads_the_panels_day(story: Spied, world_inputs: Inputs) -> None:
    run = story.result.story
    world = run.world
    late = world.of("late")
    zone = ZoneInfo(world.tz_of["late"])
    moment = next(m for m in drill.MOMENTS if m.name == "d0_0630")
    at = drill.moment_at(world, late[0], moment)
    when, data = [(w, d) for w, d in run.host.uploads() if w <= at][-1]
    made = PredictionsFile.from_json_bytes(data)
    nxt = drill.DAY + timedelta(days=1)
    entry = next(e for e in made.districts if e.district == late[0])
    item, then = entry.days[made.days.index(drill.DAY)], entry.days[made.days.index(nxt)]
    assert isinstance(item, Forecast)
    assert isinstance(then, Forecast)
    buses = datetime.combine(drill.DAY, dtime(6, 0), zone).astimezone(UTC)
    early = item.model_copy(update={"buses_at": buses, "announces_at": None})
    # The day is under way once its buses ran that day, or from 7:30 AM on its clock.
    assert drill.under_way(drill.DAY, at, zone, buses)
    assert not drill.under_way(drill.DAY, at, zone, None)
    assert not drill.under_way(drill.DAY, at, zone, buses + timedelta(days=1))
    seven = datetime.combine(drill.DAY, dtime(7, 29), zone)
    assert not drill.under_way(drill.DAY, seven, zone, None)
    assert drill.under_way(drill.DAY, seven + timedelta(minutes=1), zone, None)
    plain = [(drill.DAY, item), (nxt, then)]
    assert drill.headline_day(plain, at, zone, ()) == drill.DAY
    assert drill.headline_day([(drill.DAY, early), (nxt, then)], at, zone, ()) == nxt
    assert drill.headline_day(plain, at, zone, {drill.DAY}) == nxt
    assert drill.headline_day([(drill.DAY, "unknown"), (nxt, then)], at, zone, ()) == nxt
    assert drill.headline_day([(drill.DAY, early)], at, zone, ()) is None
    # A file whose late districts' buses run at 6 AM: at 6:30 AM the panel heads Wednesday, so
    # Tuesday's cell is off, and no other cell moves.
    districts = []
    for each in made.districts:
        if each.district in late:
            days = list(each.days)
            k = made.days.index(drill.DAY)
            day_item = days[k]
            assert isinstance(day_item, Forecast)
            days[k] = day_item.model_copy(update={"buses_at": buses, "announces_at": None})
            districts.append(each.model_copy(update={"days": tuple(days)}))
        else:
            districts.append(each)
    moved = made.model_copy(update={"districts": tuple(districts)}).to_json_bytes()
    cut = drill.DrillHost(run.host._now)
    cut.log = [
        (w, key, moved if (w, key) == (when, drill.LATEST) else d) for w, key, d in run.host.log
    ]
    found = drill.cells(dataclasses.replace(run, host=cut), world_inputs.config)
    assert [found[(i, "d0_0630")] for i in late] == [drill.OTHER_DAY] * len(late)
    changed = {key for key, value in found.items() if value != story.result.cells[key]}
    assert changed == {(i, "d0_0630") for i in late}


def test_b6_counts_the_schools_its_warning_reaches(story: Spied, world_inputs: Inputs) -> None:
    result = story.result
    run, config = result.story, world_inputs.config
    b6 = next(v for v in result.verdicts if v.row == "B6")
    assert b6.shows
    assert drill.warned_schools(run, "half", drill.MOMENTS[2]) == [2, 2, 2, 2]
    assert b6.line.endswith("schools under the warning 2, 2, 2, 2 of 5 (a class covers 50%)")
    weather = config.weather.model_copy(update={"covered_share": 0.4})
    tight = config.model_copy(update={"weather": weather})
    flipped = drill.verdicts(run, result.cells, tight)
    assert [v.row for v in flipped if not v.shows] == ["B6"]
    world = dataclasses.replace(
        run.world, products=tuple(p for p in run.world.products if p.story != "half")
    )
    quiet = dataclasses.replace(run, world=world)
    assert drill.warned_schools(quiet, "half", drill.MOMENTS[2]) == [0, 0, 0, 0]
    assert not next(v for v in drill.verdicts(quiet, result.cells, config) if v.row == "B6").shows


def test_the_forecast_copy_follows_the_live_reader(
    story: Spied, world_inputs: Inputs, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[list[str], set[str]]] = []
    real = forecast_live.forecasts

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(([type(a).__name__ for a in args], set(kwargs)))
        return real(*args, **kwargs)

    monkeypatch.setattr(forecast_live, "forecasts", spy)
    model = story.result.story.model
    share = world_inputs.config.weather.covered_share
    live = outlook_live.forecast_reader(cast(forecast_history.Fetcher, _NoListing()), share)
    ours = drill.drill_read(share, drill.story_script(story.result.story.world))
    at = datetime(2027, 1, 12, 3, 0, tzinfo=UTC)
    zones = sorted(set(model.time_zone))
    live(model, (drill.DAY,), at, forecast_adjust.snapshot, zones)
    ours(model, (drill.DAY,), at, forecast_adjust.snapshot, zones)
    assert len(seen) == 2
    assert len(seen[0][0]) == 7
    assert seen[0] == seen[1]
    assert seen[0][1] == {"moment", "zones"}
    tree = ast.parse(Path(cli.__file__).read_text())
    adjust = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_adjust_reader"
    )
    returned = [node for node in ast.walk(adjust) if isinstance(node, ast.Return)]
    assert len(returned) == 1
    assert returned[0].value is not None
    assert ast.unparse(returned[0].value) == drill.ADJUST_COMPOSITION, (
        "cli._adjust_reader changed: follow it in drill.adjust_reader and ADJUST_COMPOSITION"
    )


def test_the_panel_rules_follow_the_web_source() -> None:
    day = (WEB / "data" / "school-day.ts").read_text()
    chance = (WEB / "app" / "chance.ts").read_text()
    detail = (WEB / "data" / "forecast-detail.ts").read_text()
    words = (WEB / "copy-chance.ts").read_text()

    def minutes(name: str) -> timedelta:
        found = re.search(rf"export const {name} = (\d+) \* 60_000;", day)
        assert found, name
        return timedelta(minutes=int(found[1]))

    assert minutes("PREDICTIONS_FRESH_MS") == drill.FRESH
    assert minutes("PREDICTIONS_AHEAD_MS") == drill.AHEAD
    assert "if (!(age <= PREDICTIONS_FRESH_MS && age >= -PREDICTIONS_AHEAD_MS)) return null;" in day
    found = re.search(
        r"export const UNDER_WAY_AT = \{ hour: (\d+), minute: (\d+) \} as const;", chance
    )
    assert found
    assert dtime(int(found[1]), int(found[2])) == drill.UNDER_WAY_AT
    assert "if (buses !== null && now >= buses) return true;" in chance
    assert (
        "if (underWay(dated.day, now, outlook.timeZone, dated.detail?.busesAt ?? null)) continue;"
        in chance
    )
    assert (
        "const days = [decided.today ? null : outlook.today, "
        "decided.tomorrow ? null : outlook.tomorrow];" in chance
    )
    assert (
        "const busesAt = buses !== null && dayIn(buses, timeZone) === day ? buses : null;" in detail
    )
    found = re.search(
        r"if \(days < 0 \|\| days > (\d+) \|\| at\.getTime\(\) > now\.getTime\(\)\) return null;",
        words,
    )
    assert found
    assert int(found[1]) == drill.MOVE_DAYS
    assert "const before = Math.round(previous * 100);" in words
    # Math.round takes a half up, where Python's round takes it to the even number.
    assert drill.percent(0.125) == 13
    assert round(12.5) == 12
    assert drill.percent(0.285) == 28  # 28.499999999999996, as Math.round reads it too
    assert [drill.percent(x / 100) for x in range(101)] == list(range(101))


def test_the_command_says_its_own_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["predict", "drill", "--full"]) == 1
    assert capsys.readouterr().out == "predict drill: --full needs --size\n"
    missing = tmp_path / "missing.json"
    assert main(["predict", "drill", "--against", str(missing)]) == 1
    assert capsys.readouterr().out.splitlines() == [
        f"predict drill: error: FileNotFoundError: [Errno 2] No such file or directory: '{missing}'"
    ]


def test_the_world_and_the_story_refuse_what_they_cannot_be(
    world_inputs: Inputs, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    committed = world_inputs.committed
    leaid = next(iter(committed.districts))
    blind = committed.districts[leaid].model_copy(update={"time_zone": None})
    unzoned = committed.model_copy(update={"districts": {**committed.districts, leaid: blind}})
    monkeypatch.setattr(drill, "pick", lambda *_args: (leaid,))
    with pytest.raises(ValueError, match="watch: no time zone"):
        drill.build_world(unzoned, world_inputs.exposure)
    monkeypatch.setattr(drill, "is_school_day", lambda _day: False)
    with pytest.raises(ValueError, match="2027-01-11 is not a school day"):
        drill.story_drill(
            world_inputs.config, committed, world_inputs.exposure, tmp_path, tmp_path / "frozen"
        )


def test_against_names_only_the_cells_that_differ(guarded: Guarded) -> None:
    before = guarded.document
    after = copy.deepcopy(before)
    assert drill.differences(before, after) == ["0 cells differ, 0 verdicts differ"]
    leaid = before["districts"][0]["leaid"]
    after["cells"][leaid]["d1_1600"]["p"] = 5
    after["verdicts"][0]["shows"] = False
    lines = drill.differences(before, after)
    assert lines == [
        f"{leaid} watch d1_1600: 1% P -> 5% P",
        f"B1: shows ({before['verdicts'][0]['line']}) -> gone ({before['verdicts'][0]['line']})",
        "1 cells differ, 1 verdicts differ",
    ]


def test_the_command_prints_the_table_and_the_verdicts(guarded: Guarded) -> None:
    printed = guarded.printed
    assert guarded.code == 0
    assert printed[0].split()[4:] == [m.name for m in drill.MOMENTS]
    rows = [line for line in printed if line.split()[:1] and line.split()[0] in {
        s.key for s in drill.STORIES
    }]  # fmt: skip
    assert len(rows) == 38
    assert any(line.startswith("legend: ") and " b a borrowed base" in line for line in printed)
    assert sum(1 for line in printed if line.split(":")[0] in {
        "B1", "C3", "B3", "B4", "B2", "B5", "B6", "C1", "C2", "C4"
    } and (": shows" in line or ": gone" in line)) == 10  # fmt: skip
    assert any(line.startswith("anchor: ") for line in printed)
    assert any(line.startswith("drill: 96 passes (0 dark)") for line in printed)
    assert sum(1 for line in printed if line.startswith("  ") and "Z published" in line) == 9
    assert any(line.startswith("size 37% worst: ") for line in printed)
    assert not any(line.startswith("size gate: ") for line in printed)
    document = guarded.document
    assert document["schema"] == 1
    # The gate's world (37% worst, the size night's at --size): its nine passes and its day.
    gate = document["size"]
    assert [[p["share"], p["mix"]] for p in gate] == [list(drill.GATE)] * len(drill.PASSES)
    assert [p["at"] for p in gate] == [f"{t:%H:%M}Z" for t in drill.PASSES]
    assert all(p["whole"] and not p["dark"] and p["own"] == 0 for p in gate)
    (frozen,) = document["frozen_size"]
    assert frozen["lines"] > 0
    assert frozen["xz"] > 0
    assert frozen["d1_rows"] >= 2
    assert frozen["taken"] == 4 * frozen["zones"]
    assert frozen["missed"] == 0
    assert frozen["late_s"] <= 3600
    assert not any(name.startswith("snowlight-drill-") for name in guarded.left)


def test_the_drill_is_the_same_every_run(story: Spied, guarded: Guarded) -> None:
    plain = json.loads(drill.as_json(story.result))
    assert plain["schema"] == 1
    story_part = {k: v for k, v in guarded.document.items() if k not in SIZE_KEYS}
    assert _without_timing(plain) == _without_timing(story_part)

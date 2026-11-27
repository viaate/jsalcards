"""``snowlight flights``: the Flights commands (docs/flights.md).

* ``flights live``: one live pass (D10): read the newest inputs, write ``flights/live/<slot>.json``
  and ``flights/latest.json`` to the live host (``--host github``, needs ``LIVE_HOST_TOKEN``) or
  to a folder (``--host dir --host-dir DIR``, the dry run). Exit 0 when the files were written,
  3 when nothing could be (no forecast and no FAA status read), 1 on an error.
* ``flights loop``: live passes on the live host about every 20 minutes until ``--until``, each a
  child under a hard time limit and followed by the trip alerts (the flights-live workflow;
  :mod:`snowlight.flights.loop`). Exit 0 when a pass wrote, 3 when none did.
* ``flights train``: fit on the history kept in RAM, test on the held-out year, and write the
  model file, the held-out report and the track record and past storm files.
* ``flights static``: write the airports, usual flights and own record files from the history.
* ``flights monthly``: fetch a newly posted BTS month, score the logged chances of it, refit
  and write everything again (the monthly workflow).

Raw downloads live under ``--raw`` (``/dev/shm/flights`` by default) and are never committed.
"""

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

import polars as pl

from snowlight.flights import airports as airports_module
from snowlight.flights import artifact as artifact_module
from snowlight.flights import fetch, inputs, live, nbs, obs, pull
from snowlight.flights.airports import Airport
from snowlight.schemas.flights import FlightsLive

RAW: Final = Path("/dev/shm/flights")  # noqa: S108 - RAM for raw downloads, never shared
LIVE_REPOSITORY: Final = "viaate/snowlight-live"
ROOT: Final = "v1"

EXIT_OK: Final = 0
EXIT_ERROR: Final = 1
EXIT_DARK: Final = 3


def _say(line: str) -> None:
    """One output line, written at once."""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def register(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add ``flights`` and its subcommands."""
    parser = commands.add_parser("flights", help="the Flights files (docs/flights.md)")
    sub = parser.add_subparsers(title="flights commands", metavar="<flights command>")

    run = sub.add_parser("live", help="one live pass")
    run.add_argument("--host", choices=("github", "dir"), default="dir")
    run.add_argument("--host-dir", type=Path, default=None)
    run.add_argument("--model", type=Path, default=artifact_module.MODEL_FILE)
    run.set_defaults(handler=run_live)

    chain = sub.add_parser("loop", help="live passes about every 20 minutes until --until")
    chain.add_argument("--until", required=True, help="how long, e.g. +300m")
    chain.set_defaults(handler=run_loop)

    fit = sub.add_parser("train", help="fit, test and write the model and its report")
    fit.add_argument("--raw", type=Path, default=RAW)
    fit.add_argument("--out", type=Path, required=True, help="folder for the report and files")
    fit.add_argument("--model", type=Path, default=artifact_module.MODEL_FILE)
    fit.add_argument("--first-run", type=date.fromisoformat, default=date(2020, 6, 1))
    fit.set_defaults(handler=run_train)

    month = sub.add_parser("monthly", help="fetch a new BTS month, score it, refit, publish")
    month.add_argument("--raw", type=Path, default=RAW)
    month.add_argument("--out", type=Path, required=True)
    month.add_argument("--host", choices=("github", "dir"), default="dir")
    month.add_argument("--host-dir", type=Path, default=None)
    month.set_defaults(handler=run_monthly)

    seeding = sub.add_parser("seed", help="publish a checked local build to the live host once")
    seeding.add_argument("--out", type=Path, required=True, help="the build: files/, model.json.gz")
    seeding.add_argument("--host", choices=("github", "dir"), default="dir")
    seeding.add_argument("--host-dir", type=Path, default=None)
    seeding.set_defaults(handler=run_seed)

    windy = sub.add_parser("wind", help="score the test year's chances on windy blocks")
    windy.add_argument("--raw", type=Path, default=RAW)
    windy.add_argument("--out", type=Path, required=True)
    windy.add_argument("--model", type=Path, default=artifact_module.MODEL_FILE)
    windy.add_argument(
        "--gusts", type=Path, default=None, help="hourly peaks: station, hour, gust, wind"
    )
    windy.set_defaults(handler=run_wind)

    static = sub.add_parser("static", help="write the airports, usual flights and records")
    static.add_argument("--raw", type=Path, default=RAW)
    static.add_argument("--out", type=Path, required=True)
    static.set_defaults(handler=run_static)


# --- live ----------------------------------------------------------------------------------------

NBS_DAYS_BACK: Final = 3
"""The 00Z runs looked for: today's (UTC) and the days before, until two are found."""
NBS_RUNS: Final = 2


def newest_runs(
    http: object, now: datetime, get: Callable[[str], bytes | None]
) -> list[nbs.StationRun]:
    """The two newest 00Z bulletins out by ``now``, parsed (only our airports): the only runs
    the held-out test scored (:mod:`snowlight.flights.live`)."""
    del http
    wanted = frozenset(a.icao for a in airports_module.load())
    found: list[nbs.StationRun] = []
    midnight = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    runs = 0
    for back in range(NBS_DAYS_BACK):
        run = midnight - timedelta(days=back)
        body = get(nbs.run_url(run))
        if body is None:
            continue
        rows = list(nbs.parse(body.decode("ascii", "replace"), wanted, run))
        if not rows:  # an error page or a cut-off body is no run: the day before is tried
            continue
        found.extend(rows)
        runs += 1
        if runs == NBS_RUNS:
            break
    return found


def read_inputs(
    get: Callable[[str], bytes | None],
    airports: Sequence[Airport],
    now: datetime,
    log: Callable[[str], None],
) -> live.Inputs:
    """Read every live input; each one that fails, in any way (a refused request, a body that
    does not read), is left out as not read and said, and the pass goes on."""
    read = live.Inputs()

    def attempt(name: str, step: Callable[[], None]) -> None:
        with inputs.counting() as dropped:
            try:
                step()
            except Exception as error:  # any failure of one source is that source's alone
                log(f"flights: {name} not read ({type(error).__name__}: {error})")
        if dropped:
            # The values out of range read as none, and the times off the pass's clock left out.
            log(
                f"flights: {name}: {dropped['values']} values out of range read as none, "
                f"{dropped['times']} times off the clock left out"
            )

    def forecast() -> None:
        read.runs = newest_runs(None, now, get)

    def faa() -> None:
        body = get(inputs.FAA_URL)
        if body is not None:
            read.faa = inputs.read_faa(body, now)

    def alerts() -> None:
        body = get(inputs.ALERTS_URL)
        if body is not None:
            read.alerts = inputs.read_alerts(
                body, {a.code: (a.zone, a.county) for a in airports}, now
            )

    def weather() -> None:
        body = get(inputs.METARS_URL)
        if body is not None:
            stations = {a.icao: a.code for a in airports} | {f"K{a.code}": a.code for a in airports}
            read.weather = inputs.read_metars(body, stations, now)
            read.weather_at = now.replace(microsecond=0)

    def observed() -> None:
        runs = [run.run for run in read.runs if run.run.hour == 0]
        if not runs:
            return
        start, end = inputs.observed_window(runs)
        body = get(obs.window_url(sorted({a.wx for a in airports}), start, end))
        if body is None:
            raise inputs.InputError("observed reports: not there")
        read.observed = inputs.read_observed(body, max(runs))

    attempt("forecast", forecast)
    attempt("FAA status", faa)
    attempt("NWS alerts", alerts)
    attempt("weather reports", weather)
    attempt("observed reports (every chance is the usual rate)", observed)
    return read


MODEL_URL: Final = "https://viaate.github.io/snowlight-live/v1/flights/model.json"
"""The model the monthly job refit and published (plain JSON, as the host takes); used when it
is newer than the committed one."""
MODEL_KEY: Final = "flights/model.json"


def choose_model(
    committed: artifact_module.Artifact, served: bytes | None
) -> artifact_module.Artifact:
    """The served refit when it validates against its schema (``flights/model.json``) and its
    test year is newer, else the committed model."""
    if served is None:
        return committed
    try:
        refit = artifact_module.Artifact.from_bytes(served)
    except ValueError:
        return committed
    return refit if refit.test_last > committed.test_last else committed


PASS_SECONDS: Final = 360.0
"""A live pass stops asking for inputs after this long (the step's timeout is 8 minutes): what
was read by then is written, the rest is published as not read."""
SOURCE_SECONDS: Final = 20.0
"""Each request waits this long at most."""


class OutOfTimeError(fetch.FetchError):
    """The pass's time ran out before this request."""


def budgeted(
    get: Callable[[str, float], bytes | None],
    clock: Callable[[], float] = time.monotonic,
    seconds: float = PASS_SECONDS,
) -> Callable[[str], bytes | None]:
    """``get`` that refuses every request once ``seconds`` have passed since it was made, and
    hands each request the pass's end (``get(url, end)``) so none runs past it."""
    end = clock() + seconds

    def bounded(url: str) -> bytes | None:
        if clock() >= end:
            raise OutOfTimeError(f"{url}: the pass is out of time")
        return get(url, end)

    return bounded


def live_pass(  # noqa: PLR0913, PLR0917 - the pass's reads, writes, model and clock
    get: Callable[[str], bytes | None],
    write: Callable[[Mapping[str, bytes]], None],
    model_path: Path,
    now: datetime,
    log: Callable[[str], None],
    read_host: Callable[[str], bytes | None] | None = None,
) -> int:
    """One live pass; the exit code. The slot and ``latest.json`` go in one write; the day's
    archive snapshot (:func:`snowlight.flights.live.archive_day`), when it is due and not yet
    kept (read back from the host with ``read_host``), goes in a write of its own after it, so
    a refused or failed archive never stops the live file."""
    airports = airports_module.load()
    try:
        served = get(MODEL_URL)
    except Exception as error:  # the committed model then serves
        log(f"flights: the served model not read ({type(error).__name__}: {error})")
        served = None
    artifact = choose_model(artifact_module.read(model_path), served)
    read = read_inputs(get, airports, now, log)
    if not read.runs and read.faa is None:
        log("flights: dark: neither the forecast nor the FAA status could be read")
        return EXIT_DARK
    started = time.monotonic()
    slot = None
    if read_host is not None:
        try:
            slot = live.next_slot(read_host(f"{ROOT}/flights/latest.json"), now)
        except Exception as error:  # the slot then follows the clock
            log(f"flights: latest.json not read back ({type(error).__name__}: {error})")
    document = live.Pass(
        artifact=artifact, airports=airports, now=now, read=read, slot=slot
    ).build()
    write({f"{ROOT}/{path}": data for path, data in live.files(document).items()})
    runs = sorted({r.run for r in read.runs})
    log(
        f"flights: wrote {document.slot} ({len(document.airports)} airports, runs "
        f"{', '.join(r.strftime('%Y-%m-%dT%HZ') for r in runs) or 'none'}, FAA "
        f"{'read' if read.faa else 'not read'}, alerts {'read' if read.alerts else 'not read'}, "
        f"weather {'read' if read.weather is not None else 'not read'}, observed "
        f"{'read' if read.observed is not None else 'not read'}) in "
        f"{time.monotonic() - started:.1f} s"
    )
    archive(get, write, read_host, document, read, artifact, now, log)
    return EXIT_OK


def archive(  # noqa: PLR0913, PLR0917 - one pass's parts
    get: Callable[[str], bytes | None],
    write: Callable[[Mapping[str, bytes]], None],
    read_host: Callable[[str], bytes | None] | None,
    document: FlightsLive,
    read: live.Inputs,
    artifact: artifact_module.Artifact,
    now: datetime,
    log: Callable[[str], None],
) -> bool:
    """Keep the day's snapshot when it is due and not kept yet; whether one was written. Every
    failure here is said and ends nothing."""
    day = live.archive_day(document, now)
    if day is None or read_host is None:
        return False
    key = live.archive_path(day)
    try:
        held = live.kept_day(read_host(f"{ROOT}/{key}"))
        if held == day:
            return False
        if held is not None:
            # The monthly job keeps its own copy of every day it may still score
            # (monthly.keep_archive) and says a day it lost.
            log(f"flights: the archive slot {key} held {held}, rewritten")
    except Exception as error:
        log(f"flights: archive not checked ({type(error).__name__}: {error})")
        return False
    tafs: dict[str, str] = {}
    try:
        body = get(inputs.TAFS_URL)
        if body is not None:
            tafs = inputs.read_tafs(body, {a.icao: a.code for a in airports_module.load()})
    except Exception as error:  # the archive keeps what it has without the TAFs
        log(f"flights: TAFs not read for the archive ({type(error).__name__}: {error})")
    try:
        write({f"{ROOT}/{key}": live.archive_bytes(document, read, artifact, tafs, day)})
    except Exception as error:
        log(f"flights: archive of {day} not written ({type(error).__name__}: {error})")
        return False
    log(f"flights: kept the archive of {day} at {key}")
    return True


def run_live(args: argparse.Namespace) -> int:  # pragma: no cover - the network and the host
    """``snowlight flights live``."""
    now = datetime.now(UTC)
    read_back: Callable[[str], bytes | None]
    if args.host == "dir":
        if args.host_dir is None:
            sys.stderr.write("flights live: --host dir needs --host-dir" + "\n")
            return EXIT_ERROR
        root: Path = args.host_dir

        def write(files: Mapping[str, bytes]) -> None:
            for key, data in files.items():
                path = root / key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

        def read_dir(key: str) -> bytes | None:
            path = root / key
            return path.read_bytes() if path.is_file() else None

        read_back = read_dir

    else:
        token = os.environ.get("LIVE_HOST_TOKEN", "")
        if not token:
            sys.stderr.write("flights live: needs LIVE_HOST_TOKEN" + "\n")
            return EXIT_ERROR
        from snowlight.live.publishers import GitHubPublisher  # noqa: PLC0415
        from snowlight.predict.inputs import client as host_client  # noqa: PLC0415

        host = GitHubPublisher(
            repository=LIVE_REPOSITORY, token=token, client=host_client(), branch="main"
        )
        host.message = "Flights: live pass"

        def write(files: Mapping[str, bytes]) -> None:
            host.write(dict(files))

        read_back = host.read

    with fetch.client(timeout=SOURCE_SECONDS) as http:

        def plain(url: str, end: float) -> bytes | None:
            return fetch.get_bytes(http, url, tries=2, pause=3, deadline=end)

        return live_pass(budgeted(plain), write, args.model, now, _say, read_back)


PAGES_LATEST: Final = "https://viaate.github.io/snowlight-live/v1/flights/latest.json"
FRESH_READ_SECONDS: Final = 15.0
PASS_DROPS: Final = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "GITHUB_TOKEN")
"""Secrets the pass child never sees (the trip alerts' own)."""
ALERTS_DROPS: Final = ("LIVE_HOST_TOKEN",)
"""The secret the trip alerts' child never sees (the pass's own)."""


def run_loop(args: argparse.Namespace) -> int:  # pragma: no cover - children, network, clock
    """``snowlight flights loop``: :func:`snowlight.flights.loop.run` with each pass and the
    trip alerts in a child of this interpreter, the host's ``latest.json`` read through the
    contents API (no cache) and, only when that fails, the Pages copy past its cache."""
    import subprocess  # noqa: PLC0415

    from snowlight.flights import loop  # noqa: PLC0415
    from snowlight.live.publishers import GitHubPublisher  # noqa: PLC0415
    from snowlight.predict.inputs import client as host_client  # noqa: PLC0415

    token = os.environ.get("LIVE_HOST_TOKEN", "")
    if not token:
        sys.stderr.write("flights loop: needs LIVE_HOST_TOKEN" + "\n")
        return EXIT_ERROR
    deadline = loop.until_of(args.until, datetime.now(UTC))
    host = GitHubPublisher(
        repository=LIVE_REPOSITORY, token=token, client=host_client(), branch="main"
    )

    def made() -> datetime | None:
        try:
            stamp = loop.made_of(host.read(f"{ROOT}/flights/latest.json"))
        except Exception as error:  # the Pages copy then decides
            _say(f"flights loop: latest.json not read from the host ({type(error).__name__})")
            stamp = None
        if stamp is not None:
            return stamp
        try:
            with fetch.client(timeout=FRESH_READ_SECONDS) as http:
                url = f"{PAGES_LATEST}?t={int(time.time())}"
                return loop.made_of(fetch.get_bytes(http, url, tries=1))
        except Exception as error:  # unreadable: a pass runs
            _say(f"flights loop: latest.json not read from Pages ({type(error).__name__})")
            return None

    def child(arguments: Sequence[str], seconds: float, drops: Sequence[str]) -> int:
        command = [sys.executable, "-m", "snowlight", *arguments]
        env = loop.without(os.environ, drops)
        try:
            return subprocess.run(command, env=env, timeout=seconds, check=False).returncode  # noqa: S603
        except subprocess.TimeoutExpired:  # the child is killed and reaped
            return loop.EXIT_TIMEOUT

    outcome = loop.run(
        deadline=deadline,
        clock=lambda: datetime.now(UTC),
        sleep=time.sleep,
        made=made,
        one_pass=lambda: child(
            ["flights", "live", "--host", "github"], loop.PASS_SECONDS, PASS_DROPS
        ),
        alerts=lambda: child(["notify", "flights"], loop.ALERTS_SECONDS, ALERTS_DROPS),
        log=_say,
    )
    return EXIT_OK if outcome.written or not outcome.passes else EXIT_DARK


# --- train ---------------------------------------------------------------------------------------


def run_train(args: argparse.Namespace) -> int:  # pragma: no cover - hours of data in RAM
    """``snowlight flights train``."""
    from snowlight.flights import build  # noqa: PLC0415

    return build.train_all(args.raw, args.out, args.model, args.first_run)


def run_wind(args: argparse.Namespace) -> int:  # pragma: no cover - a year of data on disk
    """``snowlight flights wind``."""
    from snowlight.flights import wind  # noqa: PLC0415

    return wind.run(args.raw, args.model, args.out, args.gusts)


def run_static(args: argparse.Namespace) -> int:  # pragma: no cover - the data in RAM
    """``snowlight flights static``."""
    from snowlight.flights import build  # noqa: PLC0415

    return build.static_all(args.raw, args.out)


def write_files(out: Path, files: Mapping[str, bytes]) -> None:
    """Write published files under ``out`` at their paths."""
    for key, data in files.items():
        path = out / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def dumps(value: object) -> str:
    """JSON for a report file."""
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def frame_rows(frame: pl.DataFrame) -> int:
    """Rows of a frame (for log lines)."""
    return frame.height


def run_monthly(args: argparse.Namespace) -> int:
    """``snowlight flights monthly``: the steps of :func:`snowlight.flights.monthly.run` on the
    network and the live host. Writes ``fetched=true`` or ``false`` to ``$GITHUB_OUTPUT`` (the
    workflow saves the history cache only when something new was kept)."""
    from snowlight.flights import build, history, monthly  # noqa: PLC0415

    read, write = _host(args)
    table = airports_module.load()
    before = history.kept_files(args.raw)
    code = EXIT_ERROR
    kept_new = False
    try:
        with fetch.client(timeout=300) as http:

            def get(url: str) -> bytes | None:  # pragma: no cover - the network
                return fetch.get_bytes(http, url)

            pacer = pull.Pacer(args.raw / "iem.last", pull.gap_at)

            def get_iem(url: str) -> bytes | None:  # pragma: no cover - the network
                return pull.get_politely(pull.requester(http), url, pacer, _say)

            outcome = monthly.run(
                raw=args.raw,
                out=args.out,
                get=get,
                read_host=read,
                write_host=write,
                log=_say,
                today=datetime.now(UTC).date(),
                committed_last=artifact_module.read(artifact_module.MODEL_FILE).test_last,
                train_all=build.train_all,
                static_all=build.static_all,
                stations=sorted({a.wx for a in table}),
                wanted=frozenset(a.icao for a in table),
                get_iem=get_iem,
            )
        _say(f"flights monthly: {outcome.said}")
        code = outcome.code
        kept_new = outcome.fetched
    finally:
        # Whatever happened, the cache is saved when the run kept a file it did not have.
        write_fetched(
            os.environ.get("GITHUB_OUTPUT"), kept_new or history.kept_files(args.raw) != before
        )
    return code


def write_fetched(output: str | None, fetched: bool) -> None:
    """Say ``fetched=true`` or ``false`` to the workflow (``$GITHUB_OUTPUT``), which saves the
    history cache only when something new was kept."""
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"fetched={'true' if fetched else 'false'}\n")


def run_seed(args: argparse.Namespace) -> int:  # pragma: no cover - the live host
    """``snowlight flights seed``: publish a checked local build once (the integrator's step)."""
    from snowlight.flights import monthly  # noqa: PLC0415

    _, write = _host(args)
    return monthly.seed(args.out, write, _say)


def _host(
    args: argparse.Namespace,
) -> tuple[
    Callable[[str], bytes | None], Callable[[Mapping[str, bytes]], None]
]:  # pragma: no cover
    """The live host's read and write (``v1/`` keys), or a folder's."""
    if args.host == "dir":
        root: Path = args.host_dir

        def read_dir(key: str) -> bytes | None:
            path = root / ROOT / key
            return path.read_bytes() if path.is_file() else None

        def write_dir(files: Mapping[str, bytes]) -> None:
            write_files(root, files)

        return read_dir, write_dir
    from snowlight.live.publishers import GitHubPublisher  # noqa: PLC0415
    from snowlight.predict.inputs import client as host_client  # noqa: PLC0415

    host = GitHubPublisher(
        repository=LIVE_REPOSITORY,
        token=os.environ["LIVE_HOST_TOKEN"],
        client=host_client(),
        branch="main",
    )

    def read_host(key: str) -> bytes | None:
        return host.read(f"{ROOT}/{key}")

    def write_host(files: Mapping[str, bytes]) -> None:
        host.write(dict(files))

    return read_host, write_host

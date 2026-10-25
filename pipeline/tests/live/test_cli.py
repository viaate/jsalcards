"""``snowlight live`` against a local stub bucket server (a real HTTP server on 127.0.0.1).

The acceptance bar of S8-D: the file is written; unchanged inputs give the same bytes apart
from ``generated_at``; refusals exit 3; nothing printed or logged names a school or a status's
words. The ingest is the SYNTHETIC world of ``world.py``; the bucket checks every signature.
"""

import argparse
import hashlib
import logging
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from live.test_edition import Source
from live.world import ALPHA_SCHOOL, World, at, row
from snowlight import cli
from snowlight.live import cli as live_cli
from snowlight.live.edition import EditionWatch
from snowlight.live.ingest import Ingest, SourceRead, orphan_station, station_zone
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.publish import LivePublisher
from snowlight.live.publishers import Credentials, sign
from snowlight.schemas.directory import DirectoryEdition
from snowlight.schemas.live import ClosingsFile

ACCESS, SECRET = "SYNTHETICKEY", "SYNTHETIC/secret"
KEYS = Credentials(ACCESS, SECRET, "auto", "s3")
OWN = DirectoryEdition.model_validate(
    {
        "schema_version": 1,
        "generated_on": "2026-10-14",
        "schools": 11,
        "districts": 6,
        "content_sha256": "a" * 64,
    }
)
MORNING = at("2026-11-17 11:05")
STORM = (
    row(ALPHA_SCHOOL, "Closed due to snow"),
    row("SYNTHETIC Pacific School", "2 hour delay due to snow"),
)


@dataclass
class Server:
    """A SYNTHETIC S3-style bucket on a loopback port that checks SigV4 like the real one."""

    clock: Callable[[], datetime]
    objects: dict[str, bytes] = field(default_factory=dict)
    puts: list[str] = field(default_factory=list)
    url: str = ""
    fail_puts: bool = False

    def handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def date_time_string(self, timestamp: float | None = None) -> str:  # noqa: ARG002
                return format_datetime(server.clock(), usegmt=True)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002, ARG002
                return

            def _signed(self, body: bytes) -> bool:
                header = self.headers.get("authorization", "")
                if "SignedHeaders=" not in header:
                    return False
                names = header.split("SignedHeaders=")[1].split(",")[0].split(";")
                headers = {name: self.headers.get(name, "") for name in names}
                moment = datetime.strptime(self.headers["x-amz-date"], "%Y%m%dT%H%M%SZ")
                digest = hashlib.sha256(body).hexdigest()
                expected = sign(
                    self.command,
                    self.path,
                    {},
                    headers,
                    digest,
                    credentials=KEYS,
                    now=moment.replace(tzinfo=UTC),
                )
                return header == expected

            def do_GET(self) -> None:
                if not self._signed(b""):
                    self.send_response(403)
                    self.end_headers()
                    return
                found = server.objects.get(self.path)
                if found is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(found)))
                self.end_headers()
                self.wfile.write(found)

            def do_PUT(self) -> None:
                body = self.rfile.read(int(self.headers["content-length"]))
                if server.fail_puts:
                    self.send_response(503)
                    self.end_headers()
                    return
                if not self._signed(body):
                    self.send_response(403)
                    self.end_headers()
                    return
                server.objects[self.path] = body
                server.puts.append(self.path)
                self.send_response(200)
                self.end_headers()

        return Handler


@dataclass
class Clock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock(MORNING)


@pytest.fixture
def server(clock: Clock) -> Iterator[Server]:
    yield from serve(clock)


def serve(clock: Clock) -> Iterator[Server]:
    """The stub bucket on a loopback port, until the generator is closed."""
    stub = Server(clock)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), stub.handler())
    stub.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield stub
    httpd.shutdown()
    httpd.server_close()


def _config(tmp_path: Path, server: Server) -> Path:
    path = tmp_path / "live.yaml"
    path.write_text(
        f"""host:
  kind: r2
  endpoint: {server.url}
  bucket: snowlight-live
state:
  kind: local
  folder: {tmp_path / "store"}
site: https://synthetic.example
site_repository: viaate/synthetic
""",
        encoding="utf-8",
    )
    return path


@dataclass
class Rig:
    world: World
    reads: list[SourceRead]
    ingests: list[Ingest] = field(default_factory=list)
    edition: list[DirectoryEdition | Exception | None] = field(default_factory=lambda: [OWN])
    lag: timedelta = timedelta(0)
    """How long after the pass's start each read finishes (a real read takes time)."""
    seen: list[int] = field(default_factory=list)
    """What a test saw while a pass read (statuses in the public file)."""


def _loaders(rig: Rig, clock: Clock) -> live_cli.Loaders:
    def parts(
        config: live_cli.LiveConfig, env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        world = rig.world
        publisher = LivePublisher(
            host=live_cli.make_host(config, env, httpx.Client()),
            directory=world.dir,
            state_dir=args.state,
            internal_dir=args.internal,
            mode=live_cli.mode_of(env),
            rehearse=bool(getattr(args, "rehearse", False)),
        )
        ingest = Ingest(
            ledger=world.ledger,
            resolver=world.resolver(),
            stations=world.stations,
            publisher=publisher,
            watch=EditionWatch(own=OWN, source=Source(rig.edition)),
            internal_dir=args.internal,
        )
        rig.ingests.append(ingest)

        def reads(
            now: datetime, only: Sequence[str], tick: Callable[[], None]
        ) -> Sequence[SourceRead]:
            tick()
            return [
                SourceRead(read.source_id, read.outcome, now + rig.lag, read.rows)
                for read in rig.reads
                if not only or read.source_id in only
            ]

        return live_cli.Parts(ingest, reads)

    def watch(_config: live_cli.LiveConfig, _env: live_cli.Env, _site_data: Path) -> EditionWatch:
        return EditionWatch(own=OWN, source=Source(rig.edition))

    return live_cli.Loaders(
        parts=parts,
        client=httpx.Client,
        watch=watch,
        deployed=lambda _config, _env: Source(rig.edition),
        clock=clock,
        sleep=clock.sleep,
        env=lambda: {
            "LIVE_PUBLISH": "shadow",
            "LIVE_R2_ACCESS_KEY_ID": ACCESS,
            "LIVE_R2_SECRET_ACCESS_KEY": SECRET,
        },
    )


@pytest.fixture
def rig() -> Rig:
    return make_rig()


def make_rig() -> Rig:
    """The SYNTHETIC world warmed up, and one read of the storm."""
    world = World()
    world.read(MORNING - timedelta(days=1), [])
    world.read(MORNING - timedelta(minutes=5), [])
    return Rig(world, [SourceRead("gray-synthetic", ReadOutcome.OK, MORNING, STORM)])


def _run(argv: list[str], loaders: live_cli.Loaders, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(live_cli, "LOADERS", loaders)
    parser = cli.build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


def _common(tmp_path: Path, server: Server) -> list[str]:
    return [
        "--config",
        str(_config(tmp_path, server)),
        "--state",
        str(tmp_path / "state"),
        "--internal",
        str(tmp_path / "internal"),
    ]


CLOSINGS_PATH = "/snowlight-live/v1-shadow/live/closings.json"


def test_once_publishes_and_unchanged_inputs_give_the_same_statuses(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    loaders = _loaders(rig, clock)
    assert _run(["live", "once", *_common(tmp_path, server)], loaders, monkeypatch) == 0
    first = server.objects[CLOSINGS_PATH]
    assert {
        "/snowlight-live/v1-shadow/live/opens.json",
        "/snowlight-live/v1-shadow/live/days/index.json",
        "/snowlight-live/v1-shadow/live/days/2026-11-17.json",
    } <= set(server.objects)
    published = ClosingsFile.from_json_bytes(first)
    assert {(item.school, item.status.name) for item in published.closings()} == {
        (0, "CLOSED"),
        (7, "DELAYED"),
    }
    # the same reads five minutes later, in a new process on the same state
    clock.now = MORNING + timedelta(minutes=5)
    rig.world.ledger.observe(
        "gray-synthetic", ReadOutcome.OK, MORNING + timedelta(minutes=1), STORM
    )
    assert _run(["live", "once", *_common(tmp_path, server)], loaders, monkeypatch) == 0
    second = ClosingsFile.from_json_bytes(server.objects[CLOSINGS_PATH])
    assert second.generated_at == clock.now
    assert second.closings() == published.closings()
    assert second.directory == published.directory
    rebuilt = ClosingsFile.encode(
        second.closings(), generated_at=published.generated_at, directory=second.directory
    )
    assert rebuilt.to_json_bytes() == first  # the same bytes apart from generated_at
    assert (tmp_path / "internal" / "health.json").is_file()
    out = capsys.readouterr()
    ours = [r.getMessage() for r in caplog.records if r.name.startswith("snowlight")]
    assert ours
    text = "\n".join([out.out, out.err, *ours]).casefold()
    for words in ("synthetic alpha", "synthetic pacific", "due to snow", "closed", "delay"):
        assert words not in text


def test_refusals_exit_3_and_upload_nothing(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.reads = [SourceRead("gray-synthetic", ReadOutcome.ERROR, MORNING)]
    loaders = _loaders(rig, clock)
    assert _run(["live", "once", *_common(tmp_path, server)], loaders, monkeypatch) == 3
    assert server.puts == []
    # the deployed directory has other content: refused too
    rig.reads = [SourceRead("gray-synthetic", ReadOutcome.OK, MORNING, STORM)]
    rig.edition = [OWN.model_copy(update={"content_sha256": "b" * 64})]
    assert _run(["live", "once", *_common(tmp_path, server)], loaders, monkeypatch) == 3
    assert server.puts == []


def test_a_host_clock_behind_the_box_refuses(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaders = _loaders(rig, clock)
    server.clock = lambda: MORNING - timedelta(minutes=5)
    assert _run(["live", "once", *_common(tmp_path, server)], loaders, monkeypatch) == 3
    assert server.puts == []


def test_blank_check_and_state(  # noqa: PLR0913, PLR0917
    tmp_path: Path,
    server: Server,
    clock: Clock,
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    assert _run(["live", "once", *common], loaders, monkeypatch) == 0
    public = "https://synthetic.example/v1-shadow/live/closings.json"
    clock.now = MORNING + timedelta(minutes=1)
    assert _run(["live", "blank", *common], loaders, monkeypatch) == 0
    blank = ClosingsFile.from_json_bytes(server.objects[CLOSINGS_PATH])
    assert (blank.days, blank.generated_at) == ((), clock.now)

    # the watchdog reads the public file as a page does (a plain GET)
    def plain(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=server.objects[CLOSINGS_PATH])

    check_loaders = replace(
        loaders, client=lambda: httpx.Client(transport=httpx.MockTransport(plain))
    )
    assert (
        _run(["live", "check", "--url", public, "--max-age", "15m"], check_loaders, monkeypatch)
        == 0
    )
    clock.now = MORNING + timedelta(minutes=17)
    assert (
        _run(["live", "check", "--url", public, "--max-age", "15m"], check_loaders, monkeypatch)
        == 3
    )
    assert "STALE" in capsys.readouterr().out
    assert _run(["live", "state", "push", *common], loaders, monkeypatch) == 0
    assert (tmp_path / "store" / "live-state.tar.gz").is_file()
    assert (
        _run(
            ["live", "state", "pull", *common[:2], "--state", str(tmp_path / "restored")],
            loaders,
            monkeypatch,
        )
        == 0
    )
    assert (tmp_path / "restored" / "publish.v1-shadow.json").is_file()


def test_run_passes_on_the_grid_and_stops_when_the_directory_changes(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaders = _loaders(rig, clock)
    common = _common(tmp_path, server)
    assert _run(["live", "run", "--until", "+12m", *common], loaders, monkeypatch) == 0
    passes = [path for path in server.puts if path == CLOSINGS_PATH]
    assert len(passes) == 3  # 11:05, 11:10, 11:15
    # the deployed directory changes under the stamp just published: blank, then stop
    changed = OWN.model_copy(update={"content_sha256": "c" * 64})
    rig.edition = [OWN, changed]
    clock.now = at("2026-11-17 11:21")
    assert _run(["live", "run", "--until", "+30m", *common], loaders, monkeypatch) == 3
    final = ClosingsFile.from_json_bytes(server.objects[CLOSINGS_PATH])
    assert final.days == ()
    assert clock.now < at("2026-11-17 11:51")


def test_settings_and_environment_errors_exit_1(
    tmp_path: Path, server: Server, clock: Clock, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaders = _loaders(rig, clock)
    bad = live_cli.Loaders(
        parts=loaders.parts,
        client=loaders.client,
        watch=loaders.watch,
        clock=clock,
        sleep=clock.sleep,
        env=lambda: {"LIVE_PUBLISH": "loud"},
    )
    assert _run(["live", "once", *_common(tmp_path, server)], bad, monkeypatch) == 1
    missing = live_cli.Loaders(
        parts=loaders.parts,
        client=loaders.client,
        watch=loaders.watch,
        clock=clock,
        sleep=clock.sleep,
        env=dict,
    )
    assert _run(["live", "blank", *_common(tmp_path, server)], missing, monkeypatch) == 1
    nothing = tmp_path / "missing.yaml"
    assert _run(["live", "once", "--config", str(nothing)], loaders, monkeypatch) == 1


def test_minutes_reads_lengths() -> None:
    assert live_cli.minutes("+330m") == timedelta(minutes=330)
    assert live_cli.minutes("15m") == timedelta(minutes=15)
    assert live_cli.minutes("2h") == timedelta(hours=2)
    with pytest.raises(argparse.ArgumentTypeError):
        live_cli.minutes("soon")


def test_orphans_and_station_zones(rig: Rig) -> None:
    gone = orphan_station("gray-retired")
    assert gone.status.value == "no_endpoint"
    assert station_zone(rig.world.stations["gray-synthetic"], rig.world.dir) == "America/Chicago"

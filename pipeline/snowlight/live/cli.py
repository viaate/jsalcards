"""``snowlight live``: the live ingest's commands (spec 7.7).

* ``live once [--only ID ...]``: one pass.
* ``live run --until +330m``: passes on a 5-minute grid until then, checking the
  deployed directory every 60 seconds between passes and while a pass reads. It
  stops (exit 3) only when the deployed directory has other content, once the public
  files under that stamp are blank: its successor starts on the new directory. A
  blank that fails (or is refused for the clock) is tried again at every check, with
  no passes, for up to :data:`BLANK_RETRY`, then the loop stops with exit 1 (a run
  that ends meanwhile exits 1 too). A check's alert is printed and recorded in
  ``health.json``; a blank it publishes counts in the exit like a refused pass and the
  state is pushed after it (``--push``). A pass that fails is logged
  and the next one runs. A new deployed stamp for the same directory starts one pass
  at once (not while the hold is set or publishing is off). The loop's exit is the
  worst of its passes' (1 over 3 over 0).
* ``live blank``: the emergency button. Sets the hold and blanks every public
  closings file, in ``v1/`` and ``v1-shadow/`` whatever ``LIVE_PUBLISH`` says; every
  pass stays dark until ``live release``.
* ``live release``: clears the hold.
* ``live check --url URL --max-age 15m``: the watchdog: is the public file fresh, not
  stamped ahead of the clock, and stamped with the deployed directory's stamp?
* ``live state pull`` / ``live state push``: restore or keep the private state.
* ``live overrides --api ROOT``: one pass of the admin's manual statuses
  (:mod:`snowlight.live.overrides`): read the active overrides from the API, check them
  against the deployed directory and publish them through the gate; it stops, writing
  nothing, when the overrides light nothing and the public files show no status.
  ``live overrides --none`` publishes no override (live-ingest.yml takes the statuses
  down with it when no API is left to read).

Exit codes: 0 published or held healthily, 3 the gate refused (or the watchdog found
the file stale, missing, ahead or on another stamp), 1 an error (a state push that
failed after a pass included, whatever the pass's own exit). Settings are in
``pipeline/config/live.yaml``; secrets and the publishing switch come from the
environment only:

* ``LIVE_PUBLISH``: ``on`` (``v1/``), ``shadow`` (``v1-shadow/``, the default) or ``off``;
* ``LIVE_HOST_TOKEN``: a token that may write the Pages repository (host ``github``);
* ``LIVE_R2_ACCESS_KEY_ID`` / ``LIVE_R2_SECRET_ACCESS_KEY``: the bucket keys (``r2``
  host or ``bucket`` state);
* ``GITHUB_TOKEN``: reads the site's deployments for the directory handshake.

Every line printed carries counts, codes and source ids only. Log lines go to stderr
through :class:`RedactingFormatter`: an error shows its type, never its message or a
traceback (an adapter's or a validator's message may quote a page's words).
"""

import argparse
import logging
import os
import ssl
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx
import yaml  # type: ignore[import-untyped, unused-ignore]
from pydantic import ValidationError

from snowlight.directory.deployed import DeployedEditionError
from snowlight.live.edition import (
    DeployedSource,
    EditionState,
    EditionVerdict,
    EditionWatch,
    deployed_edition,
    own_edition,
)
from snowlight.live.guards import Refusal
from snowlight.live.ingest import Ingest, SourceRead
from snowlight.live.merge import with_overrides
from snowlight.live.morning import MorningLog
from snowlight.live.overrides import (
    EMPTY,
    DeployedSchools,
    OverridesError,
    fetch,
    nothing_to_publish,
    read_shown,
    resolve,
    zone_table,
)
from snowlight.live.overrides import (
    HEARTBEAT as OVERRIDES_HEARTBEAT,
)
from snowlight.live.publish import (
    CLOCK_SLACK,
    Exit,
    LivePublisher,
    Mode,
    PassReport,
    emergency_blank,
    release,
)
from snowlight.live.publishers import (
    USER_AGENT,
    Credentials,
    DirPublisher,
    GitHubPublisher,
    Publisher,
    PublishError,
    R2Publisher,
)
from snowlight.live.resolve import LiveDirectory
from snowlight.live.state import LocalStateStore as FolderStore
from snowlight.live.state import StateError, StateStore, bucket_store, cache_store
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import ClosingsFile

PIPELINE_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG: Final = PIPELINE_ROOT / "config" / "live.yaml"
INTERNAL: Final = PIPELINE_ROOT / "out" / "internal" / "live"
DEFAULT_STATE: Final = INTERNAL / "state"
DEFAULT_SITE_DATA: Final = PIPELINE_ROOT / "out" / "site-data"
PASS: Final = timedelta(minutes=5)
BLANK_RETRY: Final = timedelta(minutes=10)
"""How long the loop keeps trying a failed edition blank before it stops."""
_SEVERITY: Final = {Exit.OK: 0, Exit.REFUSED: 1, Exit.ERROR: 2}


def worst(*codes: Exit) -> Exit:
    """The most serious exit: an error over a refusal over a publish."""
    return max(codes, key=_SEVERITY.__getitem__)


LOG: Final = logging.getLogger(__name__)

type Env = Mapping[str, str]
type Tick = Callable[[], None]
type ReadsFn = Callable[[datetime, Sequence[str], Tick], Sequence[SourceRead]]


class ConfigError(ValueError):
    """The live settings or the environment are not usable."""


_OWN_WORDS: Final = (ConfigError, StateError, PublishError, DeployedEditionError, OverridesError)
"""Errors whose messages are this package's own words (ids, codes, file names)."""


def describe(error: BaseException) -> str:
    """What may be printed about ``error``: its message when it is one of this package's
    own, else its type only (a message may quote a page or a listing)."""
    if isinstance(error, _OWN_WORDS):
        return f"{type(error).__name__}: {error}"
    if isinstance(error, OSError) and not isinstance(error, httpx.HTTPError):
        return f"{type(error).__name__}: {error.strerror or ''}".rstrip(": ")
    return type(error).__name__


class RedactingFormatter(logging.Formatter):
    """``time level logger: message``; an exception shows its type only (no message, no
    traceback, no stack)."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        quiet = logging.makeLogRecord(record.__dict__)
        kind = quiet.exc_info[0] if quiet.exc_info else None
        quiet.exc_info, quiet.exc_text, quiet.stack_info = None, None, None
        text = super().format(quiet)
        return text if kind is None else f"{text} [{kind.__name__}]"


class _Stderr(logging.Handler):
    """Writes to the ``sys.stderr`` of the moment."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
        except (OSError, ValueError):  # pragma: no cover - a closed stream
            self.handleError(record)


def configure_logging() -> None:
    """One redacting stderr handler on the ``snowlight`` logger, at INFO (once)."""
    root = logging.getLogger("snowlight")
    if any(isinstance(handler, _Stderr) for handler in root.handlers):
        return
    handler = _Stderr()
    handler.setFormatter(RedactingFormatter())
    root.addHandler(handler)
    if root.level == logging.NOTSET:
        root.setLevel(logging.INFO)


@dataclass(frozen=True, slots=True)
class LiveConfig:
    """``config/live.yaml``."""

    host: Mapping[str, Any]
    state: Mapping[str, Any]
    site: str
    site_repository: str
    pass_minutes: int = 5
    edition_check_seconds: int = 60
    edition_max_wait_seconds: int = 120

    @classmethod
    def load(cls, path: Path) -> "LiveConfig":
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return cls(**data)
        except (OSError, yaml.YAMLError, TypeError) as error:
            raise ConfigError(f"{path.name}: {type(error).__name__}: {error}") from error


def mode_of(env: Env) -> Mode:
    try:
        return Mode(env.get("LIVE_PUBLISH", Mode.SHADOW.value))
    except ValueError as error:
        raise ConfigError("LIVE_PUBLISH is on, shadow or off") from error


def _secret(env: Env, name: str) -> str:
    value = env.get(name, "")
    if not value:
        raise ConfigError(f"needs {name} in the environment")
    return value


def _folder(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else PIPELINE_ROOT / path


def _keys(env: Env) -> Credentials:
    return Credentials(
        _secret(env, "LIVE_R2_ACCESS_KEY_ID"), _secret(env, "LIVE_R2_SECRET_ACCESS_KEY")
    )


def make_host(config: LiveConfig, env: Env, client: httpx.Client) -> Publisher:
    """The host the configuration names (``github``, ``r2`` or ``dir``)."""
    host = config.host
    kind = host.get("kind")
    if kind == "github":
        return GitHubPublisher(
            repository=str(host["repository"]),
            token=_secret(env, "LIVE_HOST_TOKEN"),
            client=client,
            branch=str(host.get("branch", "main")),
        )
    if kind == "r2":
        return R2Publisher(
            endpoint=str(host["endpoint"]),
            bucket=str(host["bucket"]),
            credentials=_keys(env),
            client=client,
        )
    if kind == "dir":
        return DirPublisher(_folder(host["folder"]))
    raise ConfigError(f"host kind {kind!r} is github, r2 or dir")


def make_store(config: LiveConfig, env: Env, client: httpx.Client) -> StateStore:
    """The state store the configuration names (``local``, ``cache`` or ``bucket``)."""
    state = config.state
    kind = state.get("kind")
    if kind == "local":
        return FolderStore(_folder(state["folder"]))
    if kind == "cache":
        return cache_store(_folder(state["folder"]))
    if kind == "bucket":
        return bucket_store(str(state["endpoint"]), str(state["bucket"]), _keys(env), client)
    raise ConfigError(f"state kind {kind!r} is local, cache or bucket")


def _verify() -> ssl.SSLContext | bool:
    # httpx no longer reads SSL_CERT_FILE itself: a proxy's CA bundle is given here.
    bundle = os.environ.get("SSL_CERT_FILE")
    return ssl.create_default_context(cafile=bundle) if bundle else True


def make_client() -> httpx.Client:  # pragma: no cover - a real network client
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(30.0, connect=15.0),
        verify=_verify(),
    )


def make_deployed(config: LiveConfig, env: Env) -> DeployedSource:  # pragma: no cover
    """The deployed site's edition, read through its Pages deployments (S8-0's reader)."""
    from snowlight.directory.deployed import Reader  # noqa: PLC0415 - only the real ingest
    from snowlight.live.edition import PagesDeployed  # noqa: PLC0415

    token = _secret(env, "GITHUB_TOKEN")
    api = httpx.Client(
        base_url="https://api.github.com",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, connect=30.0),
        verify=_verify(),
    )
    cdn = httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        max_redirects=5,
        timeout=httpx.Timeout(60.0, connect=30.0),
        verify=_verify(),
    )
    reader = Reader(
        site_url=config.site,
        repository=config.site_repository,
        api=api,
        cdn=cdn,
        max_wait=timedelta(seconds=config.edition_max_wait_seconds),
    )
    return PagesDeployed(reader)


def make_watch(config: LiveConfig, env: Env, site_data: Path) -> EditionWatch:  # pragma: no cover
    """The directory handshake against the deployed site."""
    return EditionWatch(own=own_edition(site_data), source=make_deployed(config, env))


def make_schools(config: LiveConfig, env: Env) -> DeployedSchools:  # pragma: no cover
    """The deployed directory's schools and districts, as the predictions pass reads them
    (S8-0's reader: the live deploy's artifact or a provably current CDN copy), with each
    district's time zone from the committed model."""
    from snowlight.predict.inputs import read_deployed_meta  # noqa: PLC0415 - overrides only
    from snowlight.predict.publish import DarkError  # noqa: PLC0415

    try:
        directory, meta = read_deployed_meta(
            config.site, config.site_repository, env.get("GITHUB_TOKEN")
        )
    except DarkError as error:
        raise DeployedEditionError(str(error)) from error
    return DeployedSchools.from_deployed(directory, meta, zone_table())


@dataclass(frozen=True, slots=True)
class Parts:
    """What a pass needs, built once per process."""

    ingest: Ingest
    reads: ReadsFn


def build_parts(  # pragma: no cover - loads the directory, the matcher and the registry
    config: LiveConfig, env: Env, args: argparse.Namespace
) -> Parts:
    """The real ingest: the deployed directory's schools and zones, the matcher with its
    place guard, the status reader, the registry, and the live reads (the pool, on the
    cadence)."""
    import polars as pl  # noqa: PLC0415

    from snowlight.directory.zones import ZONES_FILE, read_zones_edition  # noqa: PLC0415
    from snowlight.listed.cli import nws_counties  # noqa: PLC0415
    from snowlight.listed.located import Gazetteer  # noqa: PLC0415
    from snowlight.listed.matching import MatcherSpec  # noqa: PLC0415
    from snowlight.live.edition import check_zones  # noqa: PLC0415
    from snowlight.live.ledger import Ledger  # noqa: PLC0415
    from snowlight.live.reads import due_sources, live_reads  # noqa: PLC0415
    from snowlight.live.resolve import (  # noqa: PLC0415
        Resolver,
        f5_reader,
        matcher_fn,
        pollable_platforms,
    )
    from snowlight.sources.stations.registry import load_registry  # noqa: PLC0415

    directory_dir: Path = args.directory
    own = own_edition(args.site_data)
    check_zones(own, read_zones_edition(directory_dir / ZONES_FILE))
    schools = pl.read_parquet(directory_dir / "schools.parquet")
    districts = pl.read_parquet(directory_dir / "districts.parquet")
    directory = LiveDirectory.from_frames(
        schools, pl.read_parquet(directory_dir / ZONES_FILE), own.content_sha256
    )
    matcher = MatcherSpec(directory_dir, args.aliases).build()
    gazetteer = Gazetteer.build(schools, districts, nws_counties())
    registry = load_registry(args.registry)
    args.state.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(args.state / "ledger.sqlite")
    resolver = Resolver(
        reader=f5_reader(),
        match=matcher_fn(matcher, gazetteer),
        directory=directory,
        ledger=ledger,
        pollable=pollable_platforms(registry),
    )
    client = make_client()
    publisher = LivePublisher(
        host=make_host(config, env, client),
        directory=directory,
        state_dir=args.state,
        internal_dir=args.internal,
        mode=mode_of(env),
    )
    stations = dict(registry.stations)
    reads = live_reads(registry, directory, args.cache_dir, args.state)
    ingest = Ingest(
        ledger=ledger,
        resolver=resolver,
        stations=stations,
        publisher=publisher,
        watch=make_watch(config, env, args.site_data),
        internal_dir=args.internal,
        due=due_sources(registry),
        morning=MorningLog(args.state / "morning"),
        boosted=reads.cadence.boosted,
    )
    reads.ingest = ingest
    return Parts(ingest, reads)


@dataclass(frozen=True, slots=True)
class Loaders:
    """The parts that touch the world; tests replace them."""

    parts: Callable[[LiveConfig, Env, argparse.Namespace], Parts] = build_parts
    client: Callable[[], httpx.Client] = make_client
    watch: Callable[[LiveConfig, Env, Path], EditionWatch] = make_watch
    deployed: Callable[[LiveConfig, Env], DeployedSource] = make_deployed
    schools: Callable[[LiveConfig, Env], DeployedSchools] = make_schools
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    sleep: Callable[[float], None] = time.sleep
    env: Callable[[], Env] = field(default=lambda: dict(os.environ))


LOADERS = Loaders()


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def _fail(text: str) -> int:
    sys.stderr.write(f"snowlight live: error: {text}\n")
    return int(Exit.ERROR)


def minutes(text: str) -> timedelta:
    """``15m``, ``+330m`` or ``2h``: a length of time."""
    body = text.lstrip("+").strip()
    try:
        if body.endswith("h"):
            return timedelta(hours=float(body[:-1]))
        return timedelta(minutes=float(body.removesuffix("m")))
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{text!r} is not a length like 15m or 2h") from error


def _report(report: PassReport) -> None:
    refusals = ",".join(report.refusals) or "-"
    _say(
        f"exit {int(report.exit)}: refusals {refusals}; uploaded {len(report.uploaded)}"
        f"{'; blank' if report.blank else ''}{'; ALERT' if report.alert else ''}"
        f"{'; edition ' + report.edition if report.edition else ''}"
        f"{'; ' + report.note if report.note else ''}"
    )


def _start(args: argparse.Namespace, loaders: Loaders) -> tuple[LiveConfig, Env, Parts] | int:
    configure_logging()
    try:
        config = LiveConfig.load(args.config)
        env = loaders.env()
        return config, env, loaders.parts(config, env, args)
    except Exception as error:
        LOG.error("start: %s", type(error).__name__)
        return _fail(describe(error))


def _pass(parts: Parts, loaders: Loaders, only: Sequence[str]) -> PassReport:
    """One pass: the reads (the handshake ticking while they run), then the pass at the
    clock after them."""
    ingest = parts.ingest
    started = loaders.clock()
    reads = parts.reads(started, only, lambda: ingest.tick(loaders.clock()))
    return ingest.run_pass(reads, loaders.clock(), started=started)


def run_once(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    loaders = loaders or LOADERS
    started = _start(args, loaders)
    if isinstance(started, int):
        return started
    config, env, parts = started
    try:
        report = _pass(parts, loaders, tuple(args.only or ()))
    except Exception as error:
        LOG.error("pass failed: %s", type(error).__name__)
        return _fail(f"the pass failed: {type(error).__name__}")
    _report(report)
    if not _push(args, config, env, loaders):
        return int(Exit.ERROR)
    return int(report.exit)


def _push(args: argparse.Namespace, config: LiveConfig, env: Env, loaders: Loaders) -> bool:
    """Push the state when ``--push``; ``False`` (and an ALERT line) when that failed."""
    if not getattr(args, "push", False):
        return True
    try:
        size = make_store(config, env, loaders.client()).push(args.state)
    except Exception as error:
        _say(f"ALERT state push failed: {describe(error)}")
        return False
    _say(f"state pushed: {size} bytes")
    return True


def _next_grid(now: datetime, step: timedelta) -> datetime:
    seconds = step.total_seconds()
    return datetime.fromtimestamp((now.timestamp() // seconds + 1) * seconds, UTC)


@dataclass(slots=True)
class _Loop:
    """What the loop keeps between its steps."""

    due: datetime
    next_check: datetime
    exit: Exit = Exit.OK
    push_failed: bool = False
    held: bool = False
    """The last pass was refused under the hold."""
    restamped: DirectoryStamp | None = None
    """The deployed stamp the last immediate pass was started for (one per stamp)."""
    blank_failing: datetime | None = None
    """Since when the edition blank has been failing (no passes run meanwhile)."""


def run_loop(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """Passes on the grid until ``--until``; between passes, the handshake every minute."""
    loaders = loaders or LOADERS
    started = _start(args, loaders)
    if isinstance(started, int):
        return started
    config, env, parts = started
    start = loaders.clock()
    until = start + args.until
    step = timedelta(minutes=config.pass_minutes)
    check = timedelta(seconds=config.edition_check_seconds)
    state = _Loop(due=start, next_check=start)
    while (now := loaders.clock()) < until:
        stop = None
        if now >= state.due and state.blank_failing is None:
            stop = _loop_pass(args, (config, env, parts), loaders, state)
            state.due = _next_grid(loaders.clock(), step)
            state.next_check = loaders.clock() + check
        elif now >= state.next_check:
            stop = _loop_check((args, config, env, loaders), parts.ingest, now, state)
            state.next_check = now + check
        if stop is not None:
            return int(worst(state.exit, stop, Exit.ERROR if state.push_failed else Exit.OK))
        wake = min(state.due, state.next_check, until)
        if state.blank_failing is not None:
            wake = min(state.next_check, until)
        loaders.sleep(max(1.0, (wake - loaders.clock()).total_seconds()))
    if state.push_failed or state.blank_failing is not None:
        if state.blank_failing is not None:
            _say("edition: the run ended while the blank was failing")
        return int(Exit.ERROR)
    return int(state.exit)


def _loop_pass(
    args: argparse.Namespace,
    started: tuple[LiveConfig, Env, Parts],
    loaders: Loaders,
    state: _Loop,
) -> Exit | None:
    config, env, parts = started
    try:
        report = _pass(parts, loaders, ())
    except Exception as error:
        LOG.error("pass failed: %s", type(error).__name__)
        _say(f"exit 1: the pass failed: {type(error).__name__}")
        state.exit = Exit.ERROR
        return None
    _report(report)
    state.push_failed |= not _push(args, config, env, loaders)
    state.held = Refusal.HELD.value in report.refusals
    if report.edition == EditionState.DIFFERENT.value:
        state.exit = worst(state.exit, report.exit)
        return _different(state, loaders.clock(), failed=_blank_failed(parts.ingest, report))
    state.exit = worst(state.exit, report.exit)
    return None


def _blank_failed(ingest: Ingest, report: PassReport | None) -> bool:
    """Whether the handshake named a blank that is not done (the host failed, or it was
    refused for the clock): it is tried again."""
    verdict = ingest.last_verdict
    wanted = verdict is not None and verdict.wants_blank
    return wanted and (report is None or not report.blank)


def _different(state: _Loop, now: datetime, *, failed: bool) -> Exit | None:
    """Other content is deployed: stop once the blank is done; while it fails, try again
    at every check (no passes) for up to :data:`BLANK_RETRY`, then stop with an error."""
    if not failed:
        _say("edition: different; stopping for the successor")
        return Exit.REFUSED
    state.exit = worst(state.exit, Exit.ERROR)
    if state.blank_failing is None:
        state.blank_failing = now
    if now - state.blank_failing >= BLANK_RETRY:
        _say("edition: different and the blank keeps failing; stopping")
        return Exit.ERROR
    _say("edition: different and the blank failed; trying again at the next check")
    return None


def _loop_check(
    pushing: tuple[argparse.Namespace, LiveConfig, Env, Loaders],
    ingest: Ingest,
    now: datetime,
    state: _Loop,
) -> Exit | None:
    """The handshake between passes: raise its alert (printed and in ``health.json``), stop
    on other content (after its blank), and pass at once, one time per stamp, when the
    deployed stamp moved under equal content. A blank it publishes counts in the run's
    exit like a refused pass (an error when it failed) and the state is pushed after it."""
    try:
        verdict, blank = ingest.guard(now)
    except Exception as error:
        LOG.error("edition check failed: %s", type(error).__name__)
        return None
    if blank is not None:
        _report(blank)
        state.exit = worst(state.exit, blank.exit)
        if blank.uploaded:
            args, config, env, loaders = pushing
            state.push_failed |= not _push(args, config, env, loaders)
    elif verdict.alert:
        _say(f"ALERT edition: {verdict.state.value}{'; ' + verdict.note if verdict.note else ''}")
    if blank is not None or verdict.alert:
        ingest.record_check(now, verdict, blank)
    if verdict.state is EditionState.DIFFERENT:
        return _different(state, now, failed=_blank_failed(ingest, blank))
    state.blank_failing = None
    last = ingest.publisher.memory.last_stamp
    if (
        verdict.ok
        and last is not None
        and verdict.stamp not in (last, state.restamped)
        and not state.held
        and ingest.publisher.mode is not Mode.OFF
    ):
        _say("edition: a new stamp for the same directory; passing now")
        state.restamped = verdict.stamp
        state.due = now
    return None


def _host_only(args: argparse.Namespace, loaders: Loaders) -> tuple[Publisher, datetime] | int:
    configure_logging()
    try:
        config = LiveConfig.load(args.config)
        host = make_host(config, loaders.env(), loaders.client())
    except Exception as error:
        return _fail(describe(error))
    return host, loaders.clock()


def run_blank(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """The emergency button: hold every pass dark and blank every public closings file, in
    every prefix whatever ``LIVE_PUBLISH`` says (no private state is read or written)."""
    found = _host_only(args, loaders or LOADERS)
    if isinstance(found, int):
        return found
    host, now = found
    try:
        report = emergency_blank(host, now)
    except Exception as error:
        return _fail(f"blank: {describe(error)}")
    _report(report)
    return int(report.exit)


def run_release(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """Clear the hold ``live blank`` set: the next pass publishes again."""
    found = _host_only(args, loaders or LOADERS)
    if isinstance(found, int):
        return found
    host, now = found
    try:
        report = release(host, now)
    except Exception as error:
        return _fail(f"release: {describe(error)}")
    _report(report)
    return int(report.exit)


def run_check(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """The watchdog: 0 when the public file is fresh, not ahead of the clock and on the
    deployed stamp; 3 when it is stale, missing, ahead or on another stamp; 1 when it or
    the deployed edition cannot be read."""
    loaders = loaders or LOADERS
    configure_logging()
    try:
        with loaders.client() as client:
            response = client.get(args.url, headers={"Cache-Control": "no-cache"})
    except httpx.HTTPError as error:
        return _fail(f"read {args.url}: {type(error).__name__}")
    if response.status_code == httpx.codes.NOT_FOUND:
        _say(f"{args.url}: HTTP 404; MISSING")
        return int(Exit.REFUSED)
    if response.status_code != httpx.codes.OK:
        return _fail(f"read {args.url}: HTTP {response.status_code}")
    try:
        found = ClosingsFile.from_json_bytes(response.content)
    except (ValidationError, ValueError):
        return _fail(f"{args.url} is not a closings file")
    age = loaders.clock() - found.generated_at
    flags = [
        name
        for name, on in (
            ("STALE", age > args.max_age),
            ("URGENT", age > 2 * args.max_age),
            ("AHEAD", -age > CLOCK_SLACK),
        )
        if on
    ]
    unreadable = ""
    if not args.no_edition:
        try:
            config = LiveConfig.load(args.config)
            deployed = deployed_edition(loaders.deployed(config, loaders.env()))
        except Exception as error:
            unreadable = describe(error)
        else:
            if deployed is None or deployed.stamp() != found.directory:
                flags.append("STAMP")
    _say(
        f"generated_at {found.generated_at.isoformat()}; age {int(age.total_seconds() // 60)} min; "
        f"{len(found.closings())} statuses; directory {found.directory.generated_on}"
        f"{''.join('; ' + flag for flag in flags)}"
        f"{'; deployed edition unreadable: ' + unreadable if unreadable else ''}"
    )
    if flags:
        return int(Exit.REFUSED)
    return int(Exit.ERROR if unreadable else Exit.OK)


def _always(_school: int) -> bool:
    return True


def _stop_quietly(lit: bool, host: Publisher, prefix: str | None, line: str) -> int | None:
    """Exit 0 after ``line`` when there is nothing to publish (:func:`nothing_to_publish`),
    1 when the public files cannot be read, else ``None``: publish."""
    try:
        if nothing_to_publish(lit, host, prefix):
            _say(line)
            return int(Exit.OK)
    except Exception as error:
        return _fail(f"read back: {describe(error)}")
    return None


def run_overrides(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """One pass of the admin's statuses (:mod:`snowlight.live.overrides`): 0 published,
    unchanged or nothing to publish; 3 the gate refused; 1 the API, the host or the deployed
    directory could not be read (nothing is published: the public file stays)."""
    loaders = loaders or LOADERS
    configure_logging()
    try:
        config = LiveConfig.load(args.config)
        env = loaders.env()
        mode = mode_of(env)
        client = loaders.client()
        host = make_host(config, env, client)
        overrides = () if args.none else fetch(client, args.api)
        # The rows the map shows: an unchanged day keeps its "Posted" time (overrides.resolve).
        shown = read_shown(host, mode.prefix) if overrides else None
    except Exception as error:
        return _fail(describe(error))
    now = loaders.clock()
    line = "overrides: none, and the public files show no status: nothing to publish"
    if (stop := _stop_quietly(bool(overrides), host, mode.prefix, line)) is not None:
        return stop
    try:
        schools = loaders.schools(config, env)
    except Exception as error:
        return _fail(f"the deployed directory: {describe(error)}")
    resolved = resolve(overrides, schools, now, shown)
    merged = with_overrides(EMPTY, resolved.statuses, now.astimezone(UTC).replace(microsecond=0))
    withheld = ", ".join(f"{code} {count}" for code, count in resolved.withheld.items())
    _say(
        f"overrides: {len(overrides)} active; {len(merged.closings)} statuses, "
        f"{len(merged.opens)} open; "
        f"withheld {withheld or 'none'}"
    )
    line = "overrides: none lights a status, and the public files show none: nothing to publish"
    lit = bool(merged.closings or merged.opens)
    if overrides and (stop := _stop_quietly(lit, host, mode.prefix, line)) is not None:
        return stop
    publisher = LivePublisher(
        host=host,
        directory=schools.live_directory(resolved.borrowed),
        state_dir=args.state,
        internal_dir=args.internal,
        mode=mode,
        heartbeat=OVERRIDES_HEARTBEAT,
    )
    stamp = schools.stamp
    verdict = EditionVerdict(EditionState.EQUAL, now, stamp=stamp, deployed=stamp)
    try:
        # The admin's word is its own confirmation: every status counts as under an alert
        # (no spike hold), and the one source is healthy.
        report = publisher.publish(
            merged, now=now, healthy_share=1.0, edition=verdict, alerted=_always, started=now
        )
    except Exception as error:
        LOG.error("publish: %s", type(error).__name__)
        return _fail(f"publish: {describe(error)}")
    _report(report)
    return int(report.exit)


def run_state(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    loaders = loaders or LOADERS
    configure_logging()
    try:
        config = LiveConfig.load(args.config)
        store = make_store(config, loaders.env(), loaders.client())
        if args.state_action == "pull":
            names = store.pull(args.state)
            _say(f"state pulled: {len(names)} files")
        else:
            size = store.push(args.state)
            _say(f"state pushed: {size} bytes")
    except Exception as error:
        return _fail(describe(error))
    return int(Exit.OK)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="live.yaml")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="private state folder")
    parser.add_argument("--internal", type=Path, default=INTERNAL, help="private output folder")
    parser.add_argument(
        "--site-data", type=Path, default=DEFAULT_SITE_DATA, help="this build's site data"
    )


def _inputs(parser: argparse.ArgumentParser) -> None:
    from snowlight.replays.cli import (  # noqa: PLC0415 - the same inputs as the replays
        DEFAULT_ALIASES,
        DEFAULT_DIRECTORY,
        DEFAULT_REGISTRY,
    )

    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=PIPELINE_ROOT / ".cache" / "stations" / "live",
        help="conditional-request bodies (runner disk only)",
    )
    parser.add_argument(
        "--push", action="store_true", help="push the state to its store after every pass"
    )


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``live`` and its actions on ``subparsers``."""
    live = subparsers.add_parser(
        "live",
        help="the live closings ingest: read, resolve, gate and publish",
        description="Publish the live closings file through the publish gate.",
    )
    actions = live.add_subparsers(dest="live_action", metavar="ACTION", required=True)
    once = actions.add_parser("once", help="one pass")
    _common(once)
    _inputs(once)
    once.add_argument("--only", nargs="*", default=(), help="read only these source ids")
    once.set_defaults(handler=run_once)
    loop = actions.add_parser("run", help="passes on a 5-minute grid until --until")
    _common(loop)
    _inputs(loop)
    loop.add_argument("--until", type=minutes, required=True, help="how long, e.g. +330m")
    loop.set_defaults(handler=run_loop)
    blank = actions.add_parser(
        "blank", help="hold the map dark: blank every public file until live release"
    )
    _common(blank)
    blank.set_defaults(handler=run_blank)
    unhold = actions.add_parser("release", help="clear the hold live blank set")
    _common(unhold)
    unhold.set_defaults(handler=run_release)
    check = actions.add_parser("check", help="the watchdog: is the public file fresh?")
    check.add_argument("--url", required=True, help="the public closings.json")
    check.add_argument("--max-age", type=minutes, default=timedelta(minutes=15))
    check.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="live.yaml")
    check.add_argument(
        "--no-edition",
        action="store_true",
        help="skip comparing the file's stamp with the deployed edition",
    )
    check.set_defaults(handler=run_check)
    manual = actions.add_parser("overrides", help="publish the admin's manual statuses (one pass)")
    _common(manual)
    source = manual.add_mutually_exclusive_group(required=True)
    source.add_argument("--api", help="the API root, https://.../")
    source.add_argument(
        "--none", action="store_true", help="publish no override (take the statuses down)"
    )
    manual.set_defaults(handler=run_overrides)
    state = actions.add_parser("state", help="restore or keep the private state")
    state.add_argument("state_action", choices=("pull", "push"))
    _common(state)
    state.set_defaults(handler=run_state)
    from snowlight.live.sweep import add_parser  # noqa: PLC0415 - loads the stations reader
    from snowlight.replays.cli import DEFAULT_REGISTRY  # noqa: PLC0415

    add_parser(actions, DEFAULT_REGISTRY)

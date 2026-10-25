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
import contextlib
import json
import logging
import os
import re
import ssl
import sys
import threading
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
from snowlight.live.alerts import (
    ALERTS,
    Issues,
    Kind,
    ReaderAlerts,
    annotate,
    book_for,
    latest_ingest_run,
    load_book,
    timer_late,
)
from snowlight.live.cadence import active_holds, merge_holds
from snowlight.live.d1 import (
    LostStateError,
    PushResult,
    UnreadableStateError,
    WorkflowError,
    WriteCapError,
)
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
from snowlight.live.merge import AdminStatus, with_overrides
from snowlight.live.morning import MorningLog
from snowlight.live.overrides import (
    EMPTY,
    ApiRoot,
    DeployedSchools,
    OverridesError,
    fetch,
    fetch_live,
    nothing_to_publish,
    read_shown,
    resolve,
    zone_table,
)
from snowlight.live.overrides import (
    HEARTBEAT as OVERRIDES_HEARTBEAT,
)
from snowlight.live.pool import MAX_ABANDONED
from snowlight.live.publish import (
    CLOCK_SLACK,
    PREFIXES,
    REHEARSE,
    Exit,
    LivePublisher,
    Mode,
    PassReport,
    emergency_blank,
    release,
)
from snowlight.live.publishers import (
    DEFAULT_MESSAGE,
    USER_AGENT,
    Credentials,
    DirPublisher,
    GitHubPublisher,
    Publisher,
    PublishError,
    R2Publisher,
)
from snowlight.live.resolve import LiveDirectory
from snowlight.live.state import (
    ALERT_BYTES,
    ARCHIVE,
    StateError,
    StateStore,
    bucket_store,
    check_export,
    export,
)
from snowlight.live.state import LocalStateStore as FolderStore
from snowlight.output import write_bytes_atomic
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
        if quiet.name == "py.warnings" or not quiet.name.startswith("snowlight"):
            # a warning's or a library's words may quote a page: its kind only
            quiet.msg, quiet.args = _library_line(record), None
        text = super().format(quiet)
        return text if kind is None else f"{text} [{kind.__name__}]"


def _library_line(record: logging.LogRecord) -> str:
    """What is printed of a record that is not this package's own: a warning's category, or
    the logger's name and level."""
    if record.name == "py.warnings":
        found = re.search(r":\s*([A-Za-z_]+(?:Warning|Error))\s*:", str(record.msg))
        return f"a warning ({found.group(1) if found else 'Warning'})"
    return "a library message (its words are not printed)"


class _Stderr(logging.Handler):
    """Writes to the ``sys.stderr`` of the moment."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
        except (OSError, ValueError):  # pragma: no cover - a closed stream
            self.handleError(record)


def configure_logging() -> None:
    """The logs of a public Actions run carry no page words (S8-E privacy 4), set up once:

    * one redacting stderr handler on the **root** logger (:class:`RedactingFormatter`: an
      exception shows its type only; a library's or a warning's record shows no words);
    * the ``snowlight`` logger at INFO, ``httpx`` and ``httpcore`` at WARNING;
    * warnings go to the logging system (``logging.captureWarnings``), never raw to stderr;
    * an uncaught exception prints its type only (``sys.excepthook``), in a thread too
      (``threading.excepthook``), and so does one raised where Python cannot raise it, in a
      ``__del__`` or a callback (``sys.unraisablehook``).
    """
    root = logging.getLogger()
    if not any(isinstance(handler, _Stderr) for handler in root.handlers):
        handler = _Stderr()
        handler.setFormatter(RedactingFormatter())
        root.addHandler(handler)
    ours = logging.getLogger("snowlight")
    if ours.level == logging.NOTSET:
        ours.setLevel(logging.INFO)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.captureWarnings(True)
    sys.excepthook = _quiet_excepthook
    threading.excepthook = _quiet_thread_hook
    sys.unraisablehook = _quiet_unraisable_hook


def _quiet_excepthook(kind: type[BaseException], _value: BaseException, _trace: object) -> None:
    """An uncaught exception: its type only (its message may quote a page)."""
    sys.stderr.write(f"snowlight live: error: {kind.__name__}\n")


def _quiet_thread_hook(found: threading.ExceptHookArgs) -> None:
    """An exception that ended a thread: its type only."""
    sys.stderr.write(f"snowlight live: error in a thread: {found.exc_type.__name__}\n")


def _quiet_unraisable_hook(found: "sys.UnraisableHookArgs") -> None:
    """An exception Python could not raise (in a ``__del__``, say): its type only."""
    sys.stderr.write(f"snowlight live: error that could not be raised: {found.exc_type.__name__}\n")


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
    push_every_minutes: int = 30
    """How often the loop pushes its state in idle time (hourly past the write switch)."""

    @classmethod
    def load(cls, path: Path) -> "LiveConfig":
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return cls(**data)
        except (OSError, yaml.YAMLError, TypeError) as error:
            raise ConfigError(f"{path.name}: {type(error).__name__}: {error}") from error


def mode_of(env: Env) -> Mode:
    """``LIVE_PUBLISH`` as Actions compares it (ignoring case, no trimming): ``on``,
    ``shadow`` or ``off``; anything else, unset included, is ``shadow`` (with a warning for a
    value that is set). It never raises, so the reader and the publish job's
    ``vars.LIVE_PUBLISH != 'on'`` always agree on who writes ``v1``."""
    value = env.get("LIVE_PUBLISH", "")
    folded = value.lower() if value.isascii() else value
    for mode in Mode:
        if folded == mode.value:
            return mode
    if value:
        LOG.warning("LIVE_PUBLISH is not on, shadow or off: shadow")
    return Mode.SHADOW


def overrides_mode(env: Env) -> Mode:
    """``LIVE_PUBLISH`` of the overrides job (``live overrides``), read exactly as before the
    reader landed: ``on``, ``shadow`` or ``off`` as written (unset is ``shadow``); any other
    value, another case included, is refused and nothing is published. live-ingest.yml's
    publish job sets it from ``LIVE_OVERRIDES_PUBLISH`` (default ``on``).

    Raises:
        ConfigError: another value.
    """
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


_BEATS: list[Callable[[], None]] = []
"""The running loop's pulse (:meth:`Runner.request_beat`) while ``live run`` runs."""


def beat() -> None:
    """Touch the running loop's pulse, if a loop runs (every request of a client
    :func:`beating` made calls it)."""
    for one in tuple(_BEATS):
        one()


def _on_http(_event: object) -> None:
    beat()


def beating(client: httpx.Client) -> httpx.Client:
    """``client``, calling :func:`beat` as each request goes out and each answer comes back:
    a pass's publish, a push to the state database, a handshake and the timer check show
    progress to the watcher request by request, so its limit (:data:`PULSE_MAX_AGE`) need
    not cover a whole slow publish or push, while a hang that holds the interpreter (no
    request goes out) still stops the pulse."""
    hooks = client.event_hooks
    for name in ("request", "response"):
        if _on_http not in hooks.get(name, []):
            hooks[name] = [*hooks.get(name, []), _on_http]
    client.event_hooks = hooks
    return client


def make_host(
    config: LiveConfig, env: Env, client: httpx.Client, *, name_run: bool = True
) -> Publisher:
    """The host the configuration names (``github``, ``r2`` or ``dir``). ``name_run``: a
    write's default commit message names the Actions run (the overrides job keeps the
    message it has always written)."""
    host = config.host
    kind = host.get("kind")
    if kind == "github":
        message = DEFAULT_MESSAGE
        run, workflow = env.get("GITHUB_RUN_ID", ""), env.get("GITHUB_WORKFLOW", "")
        if name_run and run.isdigit() and re.fullmatch(r"[a-z0-9-]{1,40}", workflow):
            # every write of an Actions run names it, so the public record shows which job
            # made a commit that names no pass (the soak finds a reader's under v1/ by it)
            message = f"{DEFAULT_MESSAGE} ({workflow} run {run})"
        return GitHubPublisher(
            repository=str(host["repository"]),
            token=_secret(env, "LIVE_HOST_TOKEN"),
            client=beating(client),
            branch=str(host.get("branch", "main")),
            message=message,
            default_message=message,
        )
    if kind == "r2":
        return R2Publisher(
            endpoint=str(host["endpoint"]),
            bucket=str(host["bucket"]),
            credentials=_keys(env),
            client=beating(client),
        )
    if kind == "dir":
        return DirPublisher(_folder(host["folder"]))
    raise ConfigError(f"host kind {kind!r} is github, r2 or dir")


def make_store(config: LiveConfig, env: Env, client: httpx.Client) -> StateStore:
    """The state store the configuration names (``d1``, ``local`` or ``bucket``)."""
    state = config.state
    client = beating(client)
    kind = state.get("kind")
    if kind == "d1":
        from snowlight.live.d1 import DATABASE, D1Error  # noqa: PLC0415
        from snowlight.live.d1 import make_store as d1_store  # noqa: PLC0415

        if state.get("database", DATABASE) != DATABASE:
            raise ConfigError(f"the D1 state database is {DATABASE}")
        try:
            return d1_store(env, client)
        except D1Error as error:
            raise ConfigError(str(error)) from error
    if kind == "local":
        return FolderStore(_folder(state["folder"]))
    if kind == "bucket":
        return bucket_store(str(state["endpoint"]), str(state["bucket"]), _keys(env), client)
    raise ConfigError(f"state kind {kind!r} is d1, local or bucket")


def _verify() -> ssl.SSLContext | bool:
    # httpx no longer reads SSL_CERT_FILE itself: a proxy's CA bundle is given here.
    bundle = os.environ.get("SSL_CERT_FILE")
    return ssl.create_default_context(cafile=bundle) if bundle else True


def make_client() -> httpx.Client:  # pragma: no cover - a real network client
    return beating(
        httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(30.0, connect=15.0),
            verify=_verify(),
        )
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
        api=beating(api),
        cdn=beating(cdn),
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
        rehearse=bool(getattr(args, "rehearse", False)),
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
        overrides=reader_overrides(env, client, publisher, lambda: local_schools(args.site_data)),
    )
    reads.ingest = ingest
    return Parts(ingest, reads)


def local_schools(site_data: Path) -> DeployedSchools:  # pragma: no cover - this build's files
    """This build's directory as the overrides need it (``meta.json``, ``points.bin`` and
    ``edition.json`` of the site data): the reader publishes only while the deployed directory
    has this content, so its indexes are the deployed ones."""
    from snowlight.predict.inputs import directory_from_files  # noqa: PLC0415
    from snowlight.predict.publish import DarkError  # noqa: PLC0415

    folder = site_data / "schools"
    try:
        directory, meta = directory_from_files(
            own_edition(site_data),
            (folder / "meta.json").read_bytes(),
            (folder / "points.bin").read_bytes(),
        )
    except DarkError as error:
        raise DeployedEditionError(str(error)) from error
    return DeployedSchools.from_deployed(directory, meta, zone_table())


def reader_overrides(
    env: Env,
    client: httpx.Client,
    publisher: LivePublisher,
    directory: Callable[[], DeployedSchools],
) -> Callable[[datetime], Sequence[AdminStatus]]:
    """The admin's statuses for each pass of the reader (live-ingest.yml's check rules,
    :class:`~snowlight.live.overrides.ApiRoot`): none without an API; an API error raises,
    and the pass is refused. ``directory`` loads this build's directory (once)."""
    finder = ApiRoot(env, client)
    schools: list[DeployedSchools] = []

    def statuses(now: datetime) -> Sequence[AdminStatus]:
        root = finder.find()
        if root is None:
            return ()
        found = fetch_live(client, root)
        if not schools:
            schools.append(directory())
        shown = read_shown(publisher.host, publisher.prefix) if found else None
        return resolve(found, schools[0], now, shown).statuses

    return statuses


def newest_ingest_run(env: Env) -> datetime | None:  # pragma: no cover - GitHub's API
    token = env.get("GITHUB_TOKEN", "")
    repository = env.get("GITHUB_REPOSITORY", "")
    if not token or not repository:
        return None
    with make_client() as client:
        return latest_ingest_run(client, repository, token)


REACHABLE_FOR: Final = 60.0
"""Seconds an overrides-only pass gives its probe of the state database."""


def state_reachable(config: LiveConfig, env: Env) -> bool:  # pragma: no cover - the database
    """Whether a pull would succeed now (:meth:`~snowlight.live.d1.D1StateStore.pullable`:
    ``head`` reads and names bytes that match, or is old enough to start empty), within
    :data:`REACHABLE_FOR` seconds, on a client closed after it."""
    with make_client() as client:
        try:
            store = make_store(config, env, client)
        except ConfigError:
            return False
        limit = getattr(store, "limit", None)
        if callable(limit):
            limit(REACHABLE_FOR)
        probe = getattr(store, "pullable", None)
        return bool(probe()) if callable(probe) else True


def _hard_exit(code: int) -> None:  # pragma: no cover - ends the process (a subprocess test)
    """Flush what was printed and end the process now: the interpreter's own exit joins every
    worker thread, so an abandoned reader thread stuck for good would hold it until the pulse
    watcher kills it."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(OSError, ValueError):
            stream.flush()
    logging.shutdown()
    os._exit(code)


HOST_REPOSITORY: Final = "viaate/snowlight-live"


def run_rehearse(args: argparse.Namespace, loaders: "Loaders | None" = None) -> int:
    """``live rehearse``: the switch rehearsal (:mod:`snowlight.live.rehearse`). 0 when the
    override was served within one pass of each switch; 1 otherwise, or when it may not run
    (a D1 secret is set, or LIVE_PUBLISH is on)."""
    from snowlight import cli  # noqa: PLC0415 - the commands it runs in turn
    from snowlight.live.rehearse import HOST_FOLDER, Rehearsal, preflight  # noqa: PLC0415

    loaders = loaders or LOADERS
    configure_logging()
    env = dict(loaders.env())
    refused = preflight(env, mode_of(env).value)
    if refused is not None:
        return _fail(refused)
    try:
        loaded = LiveConfig.load(args.config)
        # the writers write a folder on this runner, never the public live host: the
        # SYNTHETIC status is committed nowhere and served to no one
        folder = args.state / HOST_FOLDER
        settings = {
            "host": {"kind": "dir", "folder": str(folder)},
            "state": dict(loaded.state),
            "site": loaded.site,
            "site_repository": loaded.site_repository,
        }
        args.state.mkdir(parents=True, exist_ok=True)
        own = args.state / "live.yaml"
        write_bytes_atomic(own, yaml.safe_dump(settings, sort_keys=True).encode())
        config = LiveConfig.load(own)
        host = make_host(config, env, loaders.client())
    except Exception as error:
        return _fail(f"rehearse: {describe(error)}")
    parser = cli.build_parser()

    def step(argv: list[str], stepped: Loaders) -> int:
        found = parser.parse_args(argv)
        return int(found.handler(found, stepped))

    served = loaders.served or host.read
    rehearsal = argparse.Namespace(**{**vars(args), "config": own})
    try:
        return Rehearsal(rehearsal, config, loaders, host, served, step).run(env)
    except Exception as error:
        LOG.error("rehearse: %s", type(error).__name__)
        return _fail(f"rehearse: {describe(error)}")


def host_notice(env: Env) -> str | None:  # pragma: no cover - GitHub's API
    """One line for the soak report: the live host's size, and the repository's
    ``GITHUB_TOKEN`` count of the hour (``X-RateLimit-Used``, ``-Limit``, ``-Reset``) from the
    same answer. ``None`` when it cannot be read."""
    token = env.get("GITHUB_TOKEN", "")
    if not token:
        return None
    api = env.get("GITHUB_API_URL") or "https://api.github.com"
    try:
        with make_client() as client:
            response = client.get(
                f"{api}/repos/{HOST_REPOSITORY}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
        size = response.json().get("size") if response.status_code == httpx.codes.OK else None
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    return limits_line(response.headers, size)


def limits_line(headers: Mapping[str, str], size: object) -> str | None:
    """``live host size N KB; github token used U of L reset R`` from an answer's headers
    (either part alone when the other is missing; ``None`` with neither)."""
    parts = []
    if isinstance(size, int):
        parts.append(f"live host size {size} KB")
    used, cap, reset = (
        headers.get(f"x-ratelimit-{name}", "") for name in ("used", "limit", "reset")
    )
    if used.isdigit() and cap.isdigit() and reset.isdigit():
        parts.append(f"github token used {used} of {cap} reset {reset}")
    return "; ".join(parts) or None


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
    timer: Callable[[Env], datetime | None] = newest_ingest_run
    """When the newest live-ingest run was created (``None``: it cannot be read now)."""
    reachable: Callable[[LiveConfig, Env], bool] = state_reachable
    """Whether the state can be pulled now (overrides-only ends when it can)."""
    hard_exit: Callable[[int], None] = _hard_exit
    """End the process at once (reader threads still running would hold its exit)."""
    notice: Callable[[Env], str | None] = host_notice
    """live finish's line of the live host's size and the token count (GitHub's API)."""
    served: Callable[[str], bytes | None] | None = None
    """The rehearsal's served file by path (``None``: through the CDN)."""


LOADERS = Loaders()


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def abandoned_threads(parts: "Parts") -> int:
    """How many reader threads a cut pass left that are still running."""
    pool = getattr(parts.reads, "pool", None)
    left = getattr(pool, "abandoned", 0)
    return left if isinstance(left, int) else 0


def leave(code: int, parts: "Parts", loaders: "Loaders") -> int:
    """``code``, after ending the process at once when reader threads are still running
    (more than 8 is an exit 1 of its own: :meth:`Runner.check_abandoned`)."""
    left = abandoned_threads(parts)
    if left > 0:
        _say(f"{left} reader threads still running: the process ends now (exit {code})")
        loaders.hard_exit(code)
    return code


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


def _no_beat() -> None:
    return None


def _pass(
    parts: Parts,
    loaders: Loaders,
    only: Sequence[str],
    *,
    always: bool = False,
    beat: Callable[[], None] = _no_beat,
) -> PassReport:
    """One pass: the reads (the handshake ticking while they run), then the pass at the
    clock after them. ``always``: upload even when nothing changed. ``beat`` is called at
    every tick of the reads (every few seconds while the pool's workers run, from this
    thread) and once the reads are done: the loop's pulse, which a hang that holds the
    interpreter stops."""
    ingest = parts.ingest

    def tick() -> None:
        beat()
        ingest.tick(loaders.clock())

    started = loaders.clock()
    reads = parts.reads(started, only, tick)
    beat()
    return ingest.run_pass(reads, loaders.clock(), started=started, always=always)


def no_reads(_now: datetime, _only: Sequence[str], _tick: Tick) -> Sequence[SourceRead]:
    """The switch rehearsal's reads: none. The rehearsal never asks a real source, so it
    never works around a hold, a robots rule or a Crawl-delay the reader keeps (S8-B)."""
    return ()


def run_once(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """One pass (local and tests): it always uploads (nothing is skipped as unchanged)."""
    loaders = loaders or LOADERS
    if getattr(args, "rehearse", False) and args.push:
        return _fail("the switch drill keeps no state: --rehearse takes no --push")
    started = _start(args, loaders)
    if isinstance(started, int):
        return started
    config, env, parts = started
    if getattr(args, "rehearse", False):
        # every due source unread: G12b refuses the lists, and the admin's statuses are
        # published alone under the G12b/G12e exception, as at go-live with no list read
        parts = Parts(parts.ingest, no_reads)
    try:
        report = _pass(parts, loaders, tuple(args.only or ()), always=True)
    except Exception as error:
        LOG.error("pass failed: %s", type(error).__name__)
        return leave(_fail(f"the pass failed: {type(error).__name__}"), parts, loaders)
    _report(report)
    if not _push(args, config, env, loaders):
        return leave(int(Exit.ERROR), parts, loaders)
    return leave(int(report.exit), parts, loaders)


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


def next_grid(now: datetime, step: timedelta) -> datetime:
    """The first grid mark strictly after ``now`` (the grid is every ``step`` from the epoch)."""
    seconds = step.total_seconds()
    return datetime.fromtimestamp((now.timestamp() // seconds + 1) * seconds, UTC)


def on_grid(moment: datetime, step: timedelta) -> bool:
    return moment.timestamp() % step.total_seconds() == 0


FAILED_TO_STOP: Final = 3
"""Failed passes in a row after which the run stops (exit 1): its successor starts clean."""
PUSH_MARGIN: Final = timedelta(seconds=30)
"""A push in the loop's idle time ends this long before the next grid mark."""
MIN_PUSH_TIME: Final = timedelta(seconds=20)
TIMER_EVERY: Final = timedelta(minutes=5)
PULSE: Final = "pulse"
PULSE_MAX_AGE: Final = timedelta(seconds=210)
"""The pulse's age at which live-read.yml's watcher ends the reader (its pulse-watch
argument). The pulse is touched at every tick of a pass's reads (every 5 s), per read
folded into the ledger and per source resolved, at each request to and answer from the
live host, the state database, the deployed site and GitHub's API (:func:`beating`, at most
every :data:`BEAT_EVERY`), and after each pass, push and 60-s check. So a healthy loop's
longest silence is one request (its timeout: 60 s at most, plus a 10-s pause or a 30-s
CDN poll) or the idle wait before a 60-s check, never a whole publish or push. A hang that
holds the interpreter is ended within 4 minutes of its last pulse (this, a 10-s look and
the grace), and the publish gap after it stays near 13 minutes even when the next run's
first sweep reads for 2.5 minutes."""
PULSE_GRACE: Final = timedelta(seconds=10)
"""Between the watcher's TERM and its KILL (the reader keeps TERM's default: it ends at
once)."""
BEAT_EVERY: Final = timedelta(seconds=5)
"""A request's pulse is written at most this often (a publish makes many requests)."""


@dataclass(slots=True)
class _Loop:
    """What the loop keeps between its steps."""

    due: datetime
    next_check: datetime
    grid: bool = False
    """The pass due is a grid pass (it always uploads)."""
    exit: Exit = Exit.OK
    stop: Exit | None = None
    """Set when the run must end, with its exit."""
    held: bool = False
    """The last pass was refused under the hold."""
    restamped: DirectoryStamp | None = None
    """The deployed stamp the last immediate pass was started for (one per stamp)."""
    blank_failing: datetime | None = None
    """Since when the edition blank has been failing (no passes run meanwhile)."""
    failed: int = 0
    """Failed passes in a row."""
    ahead: bool = False
    """The last handshake found this run's directory ahead of the deploy."""
    next_push: datetime | None = None
    push_every: timedelta = timedelta(minutes=30)
    next_timer: datetime | None = None
    causes: list[str] = field(default_factory=list)
    """Why the run exits 1 (codes)."""
    end: str = "until"
    """Why the run ended (a code: ``until``, ``edition``, ``overrides``, or an exit-1 cause),
    in the loop's closing notice the soak report types each boundary by."""
    first_pass: datetime | None = None
    """When the run's first pass started (the notice the soak's cold start ends at)."""

    def fail(self, cause: str) -> Exit:
        self.causes.append(cause)
        self.stop = Exit.ERROR
        return Exit.ERROR


@dataclass(slots=True)
class Runner:
    """``live run``: passes on the grid until the last one that starts before ``--until``
    (see :func:`run_loop`)."""

    args: argparse.Namespace
    config: LiveConfig
    env: Env
    parts: Parts
    loaders: Loaders
    store: Any = None
    """The state store pushed in idle time (``None``: no push, as in overrides-only)."""
    alerts: ReaderAlerts | None = None
    state: _Loop = field(init=False)
    last_pulse: datetime | None = field(default=None, init=False)
    holds: "HoldsSink | None" = field(default=None, init=False)
    """The reads' holds sink (its pending holds are tried again in idle time)."""

    @property
    def ingest(self) -> Ingest:
        return self.parts.ingest

    def step(self) -> timedelta:
        return timedelta(minutes=self.config.pass_minutes)

    def pulse(self) -> None:
        """Touch ``state/pulse`` (the workflow's watcher ends a process whose pulse is
        :data:`PULSE_MAX_AGE` old: a hang that holds the interpreter too)."""
        now = self.loaders.clock()
        try:
            write_bytes_atomic(self.args.state / PULSE, f"{_iso(now)}\n".encode())
        except OSError as error:
            LOG.error("pulse: %s", type(error).__name__)
        self.last_pulse = now

    def request_beat(self) -> None:
        """The pulse from inside a pass or push (a request, a source resolved): written
        when the last one is :data:`BEAT_EVERY` old."""
        last = self.last_pulse
        if last is None or self.loaders.clock() - last >= BEAT_EVERY:
            self.pulse()

    def run(self) -> int:
        _BEATS.append(self.request_beat)
        self.ingest.beat = self.request_beat
        try:
            return self.loop()
        finally:
            _BEATS.remove(self.request_beat)

    def loop(self) -> int:
        clock = self.loaders.clock
        start = clock()
        until = start + self.args.until
        step = self.step()
        check = timedelta(seconds=self.config.edition_check_seconds)
        self.state = _Loop(due=start, next_check=start, grid=on_grid(start, step))
        every = timedelta(minutes=int(getattr(self.args, "push_every", 0) or 0))
        if self.store is not None and every > timedelta(0):
            self.state.push_every = every
            self.state.next_push = next_grid(start, every)
        self.state.next_timer = start
        self.pulse()
        while self.state.stop is None:
            now = clock()
            if self.state.due >= until:
                break  # the run ends right after the last grid pass that starts before --until
            if self.state.blank_failing is not None and now >= until:
                break
            if now >= self.state.due and self.state.blank_failing is None:
                self.loop_pass(now)
                self.pulse()
            elif now >= self.state.next_check:
                self.loop_check(now)
                self.state.next_check = now + check
            else:
                wake = min(self.state.due, self.state.next_check)
                if self.state.blank_failing is not None:
                    wake = self.state.next_check
                self.loaders.sleep(max(1.0, (wake - clock()).total_seconds()))
                continue
            if self.state.stop is None:
                self.idle(clock())
            self.pulse()
        return self.finish()

    def finish(self) -> int:
        state = self.state
        if state.blank_failing is not None and state.stop is None:
            _say("edition: the run ended while the blank was failing")
            state.causes.append("blank")
            annotate("notice", "live-read end blank")
            return int(Exit.ERROR)
        code = state.stop if state.stop is not None else state.exit
        if code is Exit.ERROR and state.causes:
            _say(f"exit 1: {', '.join(state.causes)}")
            state.end = state.causes[0]
        annotate("notice", f"live-read end {state.end}")
        return int(code)

    def loop_pass(self, now: datetime) -> None:
        state = self.state
        grid, started = state.grid, now
        if state.first_pass is None:
            state.first_pass = started
            annotate("notice", f"live-read first pass {_iso(started)}")
        try:
            report = self.one_pass(grid)
        except Exception as error:
            LOG.error("pass failed: %s", type(error).__name__)
            _say(f"the pass failed: {type(error).__name__}")
            report = None
        # the next due mark is the first grid mark after the pass's start: a pass that
        # overran runs the missed mark at once, so no grid slot is skipped
        state.due = next_grid(started, self.step())
        state.grid = True
        state.next_check = self.loaders.clock() + timedelta(
            seconds=self.config.edition_check_seconds
        )
        if report is None or report.exit is Exit.ERROR:
            state.failed += 1
            state.exit = worst(state.exit, Exit.REFUSED)
            if state.failed >= FAILED_TO_STOP:
                _say(f"{FAILED_TO_STOP} failed passes in a row; stopping for the successor")
                state.fail("passes")
            return
        state.failed = 0
        _report(report)
        state.held = Refusal.HELD.value in report.refusals
        state.exit = worst(state.exit, report.exit)
        self.after_report(report)
        if report.blank and report.uploaded:
            self.push(self.loaders.clock(), reason="blank")
        if report.edition == EditionState.DIFFERENT.value and not self.ahead_now():
            self.different(self.loaders.clock(), failed=_blank_failed(self.ingest, report))
        self.check_abandoned()

    def one_pass(self, grid: bool) -> PassReport:
        return _pass(self.parts, self.loaders, (), always=grid, beat=self.pulse)

    def ahead_now(self) -> bool:
        verdict = self.ingest.last_verdict
        return verdict is not None and verdict.ahead

    def after_report(self, report: PassReport) -> None:
        """Turn the pass into alert changes (codes and counts only)."""
        if self.alerts is None:
            return
        health = _read_health(self.args.internal)
        resolve = health.get("resolve") if isinstance(health.get("resolve"), dict) else {}
        share = health.get("healthy_share")
        self.alerts.sources(self.loaders.clock(), self.ingest.last_outcomes, self.step())
        self.alerts.after_pass(
            self.loaders.clock(),
            published=report.exit is Exit.OK and not report.refusals,
            refused_alert=report.alert,
            share=float(share) if isinstance(share, int | float) else None,
            breaker=bool(health.get("breakers")) or Refusal.SPIKE_HOLD.value in report.refusals,
            edition=report.edition or "equal",
            ahead=self.ahead_now(),
            resolve_counts={
                str(k): int(v) for k, v in dict(resolve or {}).items() if isinstance(v, int)
            },
        )

    def check_abandoned(self) -> None:
        left = abandoned_threads(self.parts)
        if left > MAX_ABANDONED:
            _say(f"{left} abandoned reader threads; stopping for the successor")
            self.state.fail("threads")

    def different(self, now: datetime, *, failed: bool) -> None:
        stop = _different(self.state, now, failed=failed)
        if stop is Exit.ERROR:
            self.state.fail("blank")
        elif stop is not None:
            self.state.exit = worst(self.state.exit, stop)
            self.state.stop = worst(self.state.exit, stop)
            self.state.end = "edition"

    def loop_check(self, now: datetime) -> None:
        """The handshake between passes: raise its alert (printed and in ``health.json``);
        on other content, stop once its blank is done (code ahead of the deploy waits
        instead, and passes at once when the deploy matches); pass at once, one time per
        stamp, when the deployed stamp moved under equal content. A blank it publishes
        counts in the run's exit like a refused pass and the state is pushed after it."""
        state, ingest = self.state, self.ingest
        try:
            verdict, blank = ingest.guard(now)
        except Exception as error:
            LOG.error("edition check failed: %s", type(error).__name__)
            return
        if blank is not None:
            _report(blank)
            state.exit = worst(
                state.exit, blank.exit if blank.exit is not Exit.ERROR else Exit.REFUSED
            )
            if blank.uploaded:
                self.push(now, reason="blank")
        elif verdict.alert:
            _say(
                f"ALERT edition: {verdict.state.value}{'; ' + verdict.note if verdict.note else ''}"
            )
        if blank is not None or verdict.alert:
            ingest.record_check(now, verdict, blank)
        if self.alerts is not None:
            self.alerts.edition(
                now, verdict.state.value, ahead=verdict.ahead, blank=blank is not None
            )
        was_ahead, state.ahead = state.ahead, verdict.ahead
        if verdict.state is EditionState.DIFFERENT and not verdict.ahead:
            self.different(now, failed=_blank_failed(ingest, blank))
            return
        state.blank_failing = None
        if was_ahead and verdict.ok:
            _say("edition: the deploy matches this run's directory; passing now")
            state.due, state.grid = now, False
            return
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
            state.due, state.grid = now, False

    def idle(self, now: datetime) -> None:
        """Between passes: the state push on its slot (ending before the next grid mark)
        and the owner's timer check."""
        state = self.state
        if self.holds is not None and self.holds.pending:
            self.holds.retry()
        if state.next_push is not None and now >= state.next_push and now < state.due:
            self.push(now, reason="slot")
        if self.alerts is not None and state.next_timer is not None and now >= state.next_timer:
            state.next_timer = now + TIMER_EVERY
            latest = self.loaders.timer(self.env)
            if latest is not None:  # None: it could not be read; nothing changes
                self.alerts.book.set(Kind.TIMER, timer_late(latest, now), now)

    def push(self, now: datetime, *, reason: str) -> None:
        """One push in the idle time; a failed one is tried again at the next slot only."""
        state = self.state
        if self.store is None:
            return
        deadline = state.due - PUSH_MARGIN
        if deadline - now < MIN_PUSH_TIME:
            # too close to the next grid mark: a slot push waits for the next slot, a push
            # after a blank for the idle time after the next pass (never a false alert)
            state.next_push = now if reason == "blank" else next_grid(now, state.push_every)
            return
        state.next_push = next_grid(now, state.push_every)
        book = self.alerts.book if self.alerts is not None else None
        self.pulse()  # a push is silent until its deadline: it starts on a fresh pulse
        try:
            result = self.store.keep(self.args.state, deadline=deadline)
        except LostStateError:
            _say("ALERT state: another run holds the state; stopping")
            if book is not None:
                book.set(Kind.STATE, True, now, {"why": "lost"})
            state.fail("state")
            return
        except WriteCapError:
            _say("ALERT state: the day's D1 write cap is reached; the loop runs on in memory")
            if book is not None:
                book.set(Kind.STATE, True, now, {"why": "write_cap"})
            return
        except Exception as error:
            _say(f"ALERT state push failed: {describe(error)}")
            if book is not None:
                book.set(Kind.STATE, True, now, {"why": "push"})
            return
        self.ingest.state_bytes = int(result.bytes)
        _say(
            f"state pushed: {result.bytes} bytes, {result.parts} parts, {result.rows_written} rows"
            f" written ({result.day_rows} today){'; hourly' if result.hourly else ''}"
        )
        if result.hourly:
            state.push_every = timedelta(hours=1)
            state.next_push = next_grid(now, state.push_every)
        if book is not None:
            heavy = result.bytes > ALERT_BYTES or result.over_plan
            book.set(
                Kind.STATE, heavy, now, {"why": "size" if result.bytes > ALERT_BYTES else "plan"}
            )


def _read_health(internal: Path) -> dict[str, Any]:
    try:
        found = json.loads((internal / "health.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def run_loop(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """Passes on the 5-minute grid all day until ``--until`` (S8-E section 1):

    * every grid pass uploads (the heartbeat is the grid); the run's first pass and a
      restamp pass are off the grid and skip an unchanged upload only when they start under
      4 minutes after the last uploading pass;
    * the next due mark is the first grid mark after the pass's start (a pass that overran
      runs the missed mark at once);
    * the state is pushed in the idle time after a pass on its slot (``--push-every``
      minutes, hourly past the write cap's switch), ending 30 s before the next grid mark;
      a push that fails is tried again at the next slot; after an edition blank too;
    * the run ends right after the last grid pass that starts before ``--until``;
    * ``state/pulse`` is touched after each pass and check (the workflow's watcher);
    * it exits 1 only for a persistent failure (3 failed passes in a row, a blank that keeps
      failing, a lost state swap, too many abandoned threads); otherwise 3 when a pass was
      refused or the deployed directory changed, else 0.

    ``--overrides-only`` (the state pull failed): no source is read and nothing is pushed;
    each pass publishes the admin's statuses alone, and the run ends (exit 0) as soon as the
    state database answers again, so its successor starts from the pulled state.
    """
    loaders = loaders or LOADERS
    started = _start(args, loaders)
    if isinstance(started, int):
        return started
    config, env, parts = started
    parts.ingest.run_id = env.get("GITHUB_RUN_ID", "-") or "-"
    alerts = _reader_alerts(config, env, parts, loaders)
    store = None
    if not args.overrides_only and args.push_every:
        try:
            store = make_store(config, env, loaders.client())
        except Exception as error:
            _say(f"ALERT state: no store to push to: {describe(error)}")
    sink = None
    if store is not None and hasattr(store, "put_holds"):
        reads = parts.reads
        if hasattr(reads, "on_holds"):
            sink = _holds_sink(store, alerts, loaders.clock)
            reads.on_holds = sink
    runner_type = OverridesOnly if args.overrides_only else Runner
    keeper = store if hasattr(store, "keep") else None if store is None else _LocalKeep(store)
    runner = runner_type(args, config, env, parts, loaders, keeper, alerts)
    runner.holds = sink
    if args.overrides_only and alerts is not None:
        alerts.book.set(Kind.STATE, True, loaders.clock(), {"why": "overrides_only"})
    return leave(runner.run(), parts, loaders)


@dataclass(frozen=True, slots=True)
class _LocalKeep:
    """A folder or bucket store pushed in the loop like the D1 store (no epoch, no cap)."""

    store: StateStore

    def keep(self, folder: Path, *, deadline: datetime | None = None) -> PushResult:
        del deadline
        size = self.store.push(folder)
        return PushResult(bytes=size, parts=1, rows_written=0, day_rows=0, hourly=False)


@dataclass(slots=True)
class HoldsSink:
    """Where the reads send each new block or ``Retry-After`` wait: the state database at
    once (:meth:`~snowlight.live.d1.D1StateStore.put_holds`). A write that fails (the
    database does not answer, or the day's cap and the holds' allowance are spent) keeps
    the holds pending: they go with the next ones and are tried again in the loop's idle
    time (:meth:`retry`), and the end push writes every hold ``cadence.json`` still has, so
    a successor that pulls finds them."""

    store: Any
    alerts: ReaderAlerts | None
    clock: Callable[[], datetime]
    pending: dict[str, tuple[str, datetime, str]] = field(default_factory=dict)

    def __call__(self, holds: Sequence[tuple[str, datetime, str]]) -> None:
        for hold in holds:
            kept = self.pending.get(hold[0])
            if kept is None or kept[1] < hold[1]:
                self.pending[hold[0]] = hold
        self.retry()

    def retry(self) -> None:
        now = self.clock()
        due = [hold for hold in self.pending.values() if hold[1] > now]
        if not due:
            self.pending.clear()
            return
        try:
            self.store.put_holds(due)
        except WriteCapError:
            _say("ALERT state: the day's D1 writes are spent; holds wait for the next try")
            if self.alerts is not None:
                self.alerts.book.set(Kind.STATE, True, now, {"why": "write_cap"})
            return
        except Exception as error:
            LOG.error("holds: %s", type(error).__name__)
            return
        self.pending.clear()


def _holds_sink(
    store: Any, alerts: ReaderAlerts | None, clock: Callable[[], datetime]
) -> HoldsSink:
    return HoldsSink(store, alerts, clock)


def _reader_alerts(
    config: LiveConfig, env: Env, parts: Parts, loaders: Loaders
) -> ReaderAlerts | None:
    """The run's alert book (see :mod:`snowlight.live.alerts`), carrying on with the open
    alerts the last run left in ``alerts.json``."""
    publisher = parts.ingest.publisher
    prefix = publisher.prefix
    if prefix is None and publisher.mode is not Mode.OFF:
        return None
    where = prefix or PREFIXES[0]
    issues = None
    token = env.get("GITHUB_TOKEN", "")
    repository = env.get("GITHUB_REPOSITORY", config.site_repository)
    if publisher.mode is not Mode.SHADOW and token:
        issues = Issues(loaders.client(), repository, token)
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    run = env.get("GITHUB_RUN_ID", "")
    run_url = f"{server}/{repository}/actions/runs/{run}" if run.isdigit() else ""
    book = book_for(
        publisher.mode.value,
        where,
        host=None if prefix is None else publisher.host,
        issues=issues,
        run_url=run_url,
        clock=loaders.clock,
    )
    if prefix is not None:
        try:
            load_book(book, publisher.host.read(f"{prefix}/{ALERTS}"))
        except Exception as error:
            LOG.warning("alerts.json: %s", type(error).__name__)
    return ReaderAlerts(book)


@dataclass(slots=True)
class OverridesOnly(Runner):
    """``live run --overrides-only``: the state database could not be pulled. No source is
    read and nothing is pushed or saved; each grid pass publishes the admin's statuses alone
    (the list rows go dark, never wrong), and the run ends with exit 0 once the database
    answers again (its successor pulls)."""

    def one_pass(self, grid: bool) -> PassReport:
        now = self.loaders.clock()
        report = self.ingest.overrides_pass(now, always=grid)
        if self.loaders.reachable(self.config, self.env):
            _say("state: the state can be pulled again; ending for the successor")
            self.state.stop = Exit.OK
            self.state.end = "overrides"
        return report


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
    if state.blank_failing is None:
        state.blank_failing = now
    if now - state.blank_failing >= BLANK_RETRY:
        _say("edition: different and the blank keeps failing; stopping")
        return Exit.ERROR
    _say("edition: different and the blank failed; trying again at the next check")
    return None


def _host_only(args: argparse.Namespace, loaders: Loaders) -> tuple[Publisher, datetime] | int:
    configure_logging()
    try:
        config = LiveConfig.load(args.config)
        host = make_host(config, loaders.env(), loaders.client())
    except Exception as error:
        return _fail(describe(error))
    return host, loaders.clock()


PREFIX_CHOICES: Final = ("every", *PREFIXES)


def prefixes_of(choice: str) -> tuple[str, ...]:
    """``--prefix``: ``every`` or one prefix."""
    return PREFIXES if choice == "every" else (choice,)


def run_blank(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """The emergency button: hold every pass dark and blank every public closings file, in
    every prefix whatever ``LIVE_PUBLISH`` says (or only ``--prefix``; no private state is
    read or written)."""
    found = _host_only(args, loaders or LOADERS)
    if isinstance(found, int):
        return found
    host, now = found
    try:
        report = emergency_blank(host, now, prefixes_of(args.prefix))
    except Exception as error:
        return _fail(f"blank: {describe(error)}")
    _report(report)
    return int(report.exit)


def run_release(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """Clear the hold ``live blank`` set under ``--prefix`` (required): the next pass there
    publishes again."""
    found = _host_only(args, loaders or LOADERS)
    if isinstance(found, int):
        return found
    host, now = found
    try:
        report = release(host, now, prefixes_of(args.prefix))
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
        mode = overrides_mode(env)
        rehearse = bool(getattr(args, "rehearse", False))
        prefix = REHEARSE if rehearse else mode.prefix
        client = loaders.client()
        # the admin's job publishes v1 exactly as before the reader: its commits keep the
        # message they always had
        host = make_host(config, env, client, name_run=False)
        overrides = () if args.none else fetch(client, args.api)
        # The rows the map shows: an unchanged day keeps its "Posted" time (overrides.resolve).
        shown = read_shown(host, prefix) if overrides else None
    except Exception as error:
        return _fail(describe(error))
    now = loaders.clock()
    line = "overrides: none, and the public files show no status: nothing to publish"
    if (stop := _stop_quietly(bool(overrides), host, prefix, line)) is not None:
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
    if overrides and (stop := _stop_quietly(lit, host, prefix, line)) is not None:
        return stop
    publisher = LivePublisher(
        host=host,
        directory=schools.live_directory(resolved.borrowed),
        state_dir=args.state,
        internal_dir=args.internal,
        mode=mode,
        heartbeat=OVERRIDES_HEARTBEAT,
        rehearse=rehearse,
        reader=False,
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


PULL_TRIES: Final = 3
PULL_PAUSE: Final = 10.0
PULL_AGAIN: Final = 60.0
PULL_FOR: Final = timedelta(minutes=6)
"""A pull is tried 3 times 10 s apart, then every 60 s, for up to 6 minutes in all, the
request in progress included (a hanging API cannot stretch it): a cold start of about 1.5
minutes, the pull and a first overrides-only pass stay well inside the 15-minute gap."""
END_PUSH_FOR: Final = timedelta(seconds=60)
"""The end push's bound, every request included (an 8 MB push is about 19 requests, a few
seconds): it is counted in the handoff and the restart after a kill."""
EXPORT_DIR: Final = INTERNAL / "store"
"""Where ``live state export`` writes the archive the Actions cache saves."""


def _pull(store: StateStore, args: argparse.Namespace, loaders: Loaders) -> list[str]:
    """Pull the state into ``args.state`` (with ``--retry``: the schedule above), merging the
    database's holds into the cadence.

    Raises:
        StateError: it could not be pulled.
    """
    take = getattr(store, "take", None)
    if not callable(take):
        return store.pull(args.state)
    limit = getattr(store, "limit", None)
    if callable(limit) and args.retry:
        limit(PULL_FOR.total_seconds())
    begin = loaders.clock()
    tries = 0
    pulled = None
    while pulled is None:
        tries += 1
        try:
            pulled = take(args.state)
        except Exception as error:
            pause = PULL_PAUSE if tries < PULL_TRIES else PULL_AGAIN
            waited = loaders.clock() - begin
            if (
                not args.retry
                or waited + timedelta(seconds=pause) >= PULL_FOR
                or isinstance(error, (WorkflowError, UnreadableStateError))
            ):
                raise
            _say(f"state pull failed ({describe(error)}); trying again")
            loaders.sleep(pause)
    if pulled.holds:
        merged = merge_holds(args.state / "cadence.json", pulled.holds, loaders.clock())
        _say(f"state holds: {len(pulled.holds)} kept, {merged} merged")
    if pulled.cold:
        why = (
            "an unreadable state over 2 hours old" if pulled.replaced_unreadable else "no state yet"
        )
        _say(f"ALERT state: starting empty ({why}); epoch {pulled.epoch}")
    else:
        _say(f"state epoch {pulled.epoch}")
    return list(pulled.names)


def _end_holds(store: Any, state: Path, now: datetime) -> None:
    """The end push's first write: every block and wait ``cadence.json`` still holds (a
    hold whose own write failed in the loop is kept now, before the successor pulls; a hold
    already kept is written again, a few rows). A failure here never stops the push."""
    put = getattr(store, "put_holds", None)
    holds = active_holds(state / "cadence.json", now)
    if not callable(put) or not holds:
        return
    try:
        put(holds)
    except Exception as error:
        _say(f"ALERT state: the holds were not kept: {describe(error)}")
        return
    _say(f"state holds kept: {len(holds)}")


def run_state(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """``live state pull|push|export``. ``export`` writes the allowlist archive predict learn
    reads (and the Actions cache saves) to ``--out``, checking it holds nothing else."""
    loaders = loaders or LOADERS
    configure_logging()
    if args.state_action == "export":
        try:
            data = export(args.state)
            names = check_export(data)
            write_bytes_atomic(args.out / ARCHIVE, data)
        except Exception as error:
            return _fail(f"export: {describe(error)}")
        _say(f"state exported: {len(names)} files, {len(data)} bytes")
        return int(Exit.OK)
    try:
        config = LiveConfig.load(args.config)
        store = make_store(config, loaders.env(), loaders.client())
        if args.state_action == "pull":
            names = _pull(store, args, loaders)
            _say(f"state pulled: {len(names)} files")
        else:
            keep = getattr(store, "keep", None)
            if callable(keep):
                # bounded like the loop's pushes: a D1 that hangs cannot hold the job (the
                # successor's job waits for it), and an unfinished push leaves head on the
                # last good slot
                limit = getattr(store, "limit", None)
                if callable(limit):
                    limit(END_PUSH_FOR.total_seconds())
                _end_holds(store, args.state, loaders.clock())
                result = keep(args.state, deadline=loaders.clock() + END_PUSH_FOR)
                _say(f"state pushed: {result.bytes} bytes, {result.rows_written} rows written")
            else:
                size = store.push(args.state)
                _say(f"state pushed: {size} bytes")
    except Exception as error:
        code = _fail(describe(error))
        if args.state_action == "push":
            # a failed end push is a persistent failure: the state alert, and live finish
            # (after this step) reports the run's exit 1 for it
            why = "lost" if isinstance(error, LostStateError) else "end_push"
            alert = argparse.Namespace(
                config=args.config, kind=Kind.STATE.value, open=True, detail=[f"why={why}"]
            )
            run_alert(alert, loaders)
        return code
    return int(Exit.OK)


def run_alert(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """``live alert --kind K (--open | --close)``: a workflow step's alert (``chain``): in
    shadow an annotation and ``alerts.json``, in on and off an issue. It never fails the
    step: a problem is printed and the exit is 0."""
    loaders = loaders or LOADERS
    configure_logging()
    try:
        config = LiveConfig.load(args.config)
        env = loaders.env()
        mode = mode_of(env)
        client = loaders.client()
        host = make_host(config, env, client) if mode.prefix is not None else None
        token = env.get("GITHUB_TOKEN", "")
        repository = env.get("GITHUB_REPOSITORY", config.site_repository)
        issues = Issues(client, repository, token) if token and mode is not Mode.SHADOW else None
        prefix = mode.prefix or PREFIXES[0]
        book = book_for(mode.value, prefix, host=host, issues=issues, clock=loaders.clock)
        if host is not None:
            load_book(book, host.read(f"{prefix}/{ALERTS}"))
        detail = dict(item.split("=", 1) for item in args.detail or () if "=" in item)
        book.set(Kind(args.kind), args.open, loaders.clock(), detail)
    except Exception as error:
        _say(f"alert {args.kind}: {describe(error)}")
    return int(Exit.OK)


def run_soak(args: argparse.Namespace, loaders: Loaders | None = None) -> int:  # pragma: no cover
    """``live soak --since T --until T``: the soak report from public records (read only)."""
    from snowlight.live.soak import fetch_history, parse_moment, render, report  # noqa: PLC0415

    loaders = loaders or LOADERS
    configure_logging()
    try:
        since, until = parse_moment(args.since), parse_moment(args.until)
        with loaders.client() as client:
            history = fetch_history(client, since, until, loaders.env().get("GITHUB_TOKEN", ""))
        text = render(report(history))
    except Exception as error:
        return _fail(f"soak: {describe(error)}")
    if args.out is not None:
        write_bytes_atomic(args.out, (text + "\n").encode())
    _say(text)
    return int(Exit.OK)


EXITS: Final = "exits.json"
"""The last runs' exits (codes only), kept in the state for the ``chain`` alert."""
KEEP_EXITS: Final = 5
FAILED_EXITS: Final = frozenset({1, 124})
"""A run's persistent failure: exit 1, or the pulse watcher's 124."""
CAUSES: Final = {
    0: "every pass published or was held healthily",
    1: "a persistent failure (see the run's last exit 1 line)",
    3: "a refused pass or a deployed directory change",
    124: "the pulse watcher stopped a hung reader",
}


def finish_code(args: argparse.Namespace) -> tuple[int | None, str]:
    """The run's exit for the record and its cause: the loop's own; 124 when the watcher
    ended it; 1 when the end push failed (a persistent failure) or the loop could not start
    (the directory step failed); ``None`` when the run was cancelled or never got that far."""
    code = int(args.exit) if str(args.exit).lstrip("-").isdigit() else None
    cause = CAUSES.get(code if code is not None else -1, "the loop did not run")
    if args.killed:
        code, cause = 124, CAUSES[124]
    if code is None and args.directory == "failure":
        code, cause = 1, "the directory could not be built: the loop did not run"
    if args.push == "failure" and code not in FAILED_EXITS:
        code, cause = 1, "end push: the state could not be kept"
    return code, cause


def _exits(path: Path) -> list[tuple[str, int]]:
    """``exits.json``: the last runs' ``(run id, exit)``, oldest first (``-``: no run id)."""
    try:
        found = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    except (OSError, ValueError):
        found = []
    entries: list[tuple[str, int]] = []
    for value in found if isinstance(found, list) else []:
        if isinstance(value, int) and not isinstance(value, bool):
            entries.append(("-", value))
        elif isinstance(value, dict) and isinstance(value.get("exit"), int):
            entries.append((str(value.get("run", "-")), int(value["exit"])))
    return entries


def _keep_exits(path: Path, entries: Sequence[tuple[str, int]]) -> None:
    kept = [{"run": run, "exit": code} for run, code in entries[-KEEP_EXITS:]]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(path, (json.dumps(kept) + "\n").encode())
    except OSError as error:
        LOG.error("exits.json: %s", type(error).__name__)


def _with_exit(
    entries: Sequence[tuple[str, int]], run: str, code: int | None
) -> list[tuple[str, int]]:
    """``entries`` with this run's exit last: the one ``live finish --record`` kept before
    the end push is replaced (the end push may have failed since); none for a cancelled
    run."""
    kept = [entry for entry in entries if run == "-" or entry[0] != run]
    return kept if code is None else [*kept, (run, code)]


def run_finish(args: argparse.Namespace, loaders: Loaders | None = None) -> int:
    """``live finish --exit N``: the closing steps of live-read.yml.

    With ``--record`` (the step before the end push): this run's exit goes into
    ``exits.json`` in the state folder, so the end push carries it to the state database and
    the next run pulls it; nothing else is printed or raised.

    Without it (the step after the end push): one line for the exit and its cause (an
    ``::error::`` annotation for a persistent failure: exit 1, the watcher's 124, a failed end
    push, a directory that could not be built), one ``::notice::`` with the run's counts for
    the soak report (the D1 rows of the day, the live host's size and the ``GITHUB_TOKEN``
    count), and the ``chain`` alert over the pulled runs' exits and this one: open after 2
    runs in a row with a persistent failure or a successor that could not be dispatched or a
    directory step that failed (no successor is started then), closed by a run that records
    any other exit (0, or the routine 3).
    A cancelled run records nothing. It never fails the step."""
    loaders = loaders or LOADERS
    configure_logging()
    code, cause = finish_code(args)
    path = args.state / EXITS
    run = str(loaders.env().get("GITHUB_RUN_ID", "") or "-")
    if args.record:
        if code is not None:
            _keep_exits(path, _with_exit(_exits(path), run, code))
        _say(f"live-read exit {code if code is not None else 'none'} recorded in the state")
        return int(Exit.OK)
    if code in FAILED_EXITS:
        annotate("error", f"live-read exit {code}: {cause}")
    else:
        _say(f"live-read exit {code if code is not None else 'none'}: {cause}")
    epoch: dict[str, Any] = {}
    try:
        epoch = json.loads((args.state / "d1.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        epoch = {}
    extra = loaders.notice(loaders.env())
    annotate(
        "notice",
        f"live-read summary: exit {code if code is not None else 'none'}; state bytes"
        f" {epoch.get('bytes', '-')}; d1 pushes {epoch.get('pushes', '-')}; d1 rows today"
        f" {epoch.get('day_rows', '-')}{'; ' + extra if extra else ''}",
    )
    entries = _with_exit(_exits(path), run, code)
    if code is not None:
        _keep_exits(path, entries)
    exits = [value for _, value in entries]
    broken = len(exits) >= 2 and exits[-1] in FAILED_EXITS and exits[-2] in FAILED_EXITS  # noqa: PLR2004
    # a run whose directory step failed starts no successor (the restarters start the next
    # one), and it pulled no state, so it cannot see the exits before it: the chain is broken
    # by that run alone, as by a successor that could not be dispatched
    chain = broken or args.dispatch_failed or args.directory == "failure"
    # any healthy recorded exit closes it: 0, or 3 (a refused pass or a deployed directory
    # change, routine in a 320-minute run), so an open chain never outlives a mended chain
    if chain or (code is not None and code not in FAILED_EXITS):
        alert = argparse.Namespace(
            config=args.config,
            kind=Kind.CHAIN.value,
            open=chain,
            detail=[f"exits={'-'.join(str(value) for value in exits[-2:])}"],
        )
        run_alert(alert, loaders)
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
    once.add_argument(
        "--rehearse", action="store_true", help=f"the switch drill only: write {REHEARSE}"
    )
    once.set_defaults(handler=run_once)
    loop = actions.add_parser("run", help="passes on a 5-minute grid until --until")
    _common(loop)
    _inputs(loop)
    loop.add_argument("--until", type=minutes, required=True, help="how long, e.g. +320m")
    loop.add_argument(
        "--push-every",
        type=int,
        default=0,
        metavar="MINUTES",
        help="push the state in idle time every this many minutes (0: never)",
    )
    loop.add_argument(
        "--overrides-only",
        action="store_true",
        help="the state pull failed: read nothing, push nothing, publish the admin's statuses",
    )
    loop.set_defaults(handler=run_loop)
    blank = actions.add_parser(
        "blank", help="hold the map dark: blank every public file until live release"
    )
    _common(blank)
    blank.add_argument(
        "--prefix",
        choices=PREFIX_CHOICES,
        default="every",
        help="hold and blank only this prefix (default: every prefix)",
    )
    blank.set_defaults(handler=run_blank)
    unhold = actions.add_parser("release", help="clear the hold live blank set")
    _common(unhold)
    unhold.add_argument(
        "--prefix", choices=PREFIX_CHOICES, required=True, help="the prefix to release, or every"
    )
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
    manual.add_argument(
        "--rehearse", action="store_true", help=f"the switch drill only: write {REHEARSE}"
    )
    manual.set_defaults(handler=run_overrides)
    rehearse = actions.add_parser(
        "rehearse", help=f"the switch rehearsal before go-live, on {REHEARSE} (E8)"
    )
    _common(rehearse)
    _inputs(rehearse)
    rehearse.set_defaults(handler=run_rehearse)
    _register_state(actions)
    from snowlight.live.sweep import add_parser  # noqa: PLC0415 - loads the stations reader
    from snowlight.replays.cli import DEFAULT_REGISTRY  # noqa: PLC0415

    add_parser(actions, DEFAULT_REGISTRY)


def _register_state(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """``live state`` and ``live alert``."""
    state = actions.add_parser("state", help="restore, keep or export the private state")
    state.add_argument("state_action", choices=("pull", "push", "export"))
    _common(state)
    state.add_argument(
        "--retry",
        action="store_true",
        help="pull: 3 tries 10 s apart, then every 60 s, for 6 min in all",
    )
    state.add_argument("--out", type=Path, default=EXPORT_DIR, help="export: the folder to write")
    state.set_defaults(handler=run_state)
    alert = actions.add_parser("alert", help="open or close a workflow step's alert")
    alert.add_argument("--kind", required=True, choices=[kind.value for kind in Kind])
    which = alert.add_mutually_exclusive_group(required=True)
    which.add_argument("--open", dest="open", action="store_true")
    which.add_argument("--close", dest="open", action="store_false")
    alert.add_argument("--detail", nargs="*", default=(), help="key=code pairs (codes only)")
    alert.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="live.yaml")
    alert.set_defaults(handler=run_alert)
    finish = actions.add_parser("finish", help="live-read.yml's closing step: the exit and chain")
    finish.add_argument("--exit", required=True, help="the loop step's exit, or none")
    finish.add_argument("--killed", action="store_true", help="the pulse watcher ended the loop")
    finish.add_argument(
        "--dispatch-failed", action="store_true", help="the successor could not be dispatched"
    )
    finish.add_argument(
        "--directory", default="", help="the directory step's outcome (failure: exit 1)"
    )
    finish.add_argument("--push", default="", help="the end push step's outcome (failure: exit 1)")
    finish.add_argument(
        "--record",
        action="store_true",
        help="before the end push: keep this run's exit in the state (nothing else)",
    )
    _common(finish)
    finish.set_defaults(handler=run_finish)
    soak = actions.add_parser("soak", help="the shadow soak's report, from public records")
    soak.add_argument("--since", required=True, help="e.g. 2026-10-31T18:00Z")
    soak.add_argument("--until", default="now", help="e.g. 2026-11-02T18:00Z (default now)")
    soak.add_argument("--out", type=Path, default=None, help="also write the report here")
    soak.set_defaults(handler=run_soak)

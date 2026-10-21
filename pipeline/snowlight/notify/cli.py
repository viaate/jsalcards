"""``snowlight notify status`` (live-ingest.yml) and the chance notifier (predict.yml).

Both fail dark and stay quiet:

* no ``CLOUDFLARE_API_TOKEN`` or ``CLOUDFLARE_ACCOUNT_ID``: one line, nothing sent, exit 0;
* the notification tables are not there yet, no browser gets notifications, or no VAPID key
  pair yet: one line, exit 0;
* the closings file is missing, stale or for another directory: no status is sent, exit 0;
* the database cannot be read or written, or anything else goes wrong: one warning line
  (the error's type and, for the database, its HTTP status; never a value), exit 0.

A notification problem never turns live-ingest.yml red and never stops the predictions
loop, which only warns too.
"""

import argparse
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

import httpx

from snowlight.notify import store
from snowlight.notify.d1 import D1, RETRY_PAUSE, D1Error, NoTablesError, Secrets
from snowlight.notify.deliver import Clock, Report, Sender, deliver
from snowlight.notify.rules import Account, chance_pushes, status_pushes
from snowlight.notify.sources import fresh, open_days, outlooks, status_days, statuses, zones_for
from snowlight.schemas.live import ClosingsFile, OpensFile

if TYPE_CHECKING:
    from snowlight.live.cli import LiveConfig
    from snowlight.live.overrides import DeployedSchools
    from snowlight.predict.serve import DeployedDirectory
    from snowlight.schemas.predictions import PredictionsFile

type Env = Mapping[str, str]

LIVE_ROOT: Final = "v1"
"""The prefix the site reads (``LIVE_PUBLISH`` on)."""
CLOSINGS: Final = f"{LIVE_ROOT}/live/closings.json"
OPENS: Final = f"{LIVE_ROOT}/live/opens.json"
SENT_DAYS: Final = 2
"""The log is read from this many UTC days back (every school's today is within them)."""


def _say(line: str) -> None:
    sys.stdout.write(f"{line}\n")


def _skip(why: str) -> int:
    """A status pass that sends nothing: one line, exit 0 (a status is never sent from a
    file that is not current)."""
    _say(f"notify: {why}: no status is sent")
    return 0


def _warn(error: Exception) -> int:
    """A pass that could not finish: one warning line for the Actions log, exit 0 (what it
    did not send or log is due again at the next pass)."""
    sys.stdout.write(f"::warning::notify: the pass stopped: {_what(error)}\n")
    return 0


def _what(error: Exception) -> str:
    """An error as the log may show it: a D1Error's own message names only the HTTP status;
    anything else only its type (its message could hold an address or a key)."""
    return str(error) if isinstance(error, D1Error) else type(error).__name__


def public_file(
    client: httpx.Client, repository: str, path: str, env: Env
) -> bytes | None:  # pragma: no cover - GitHub's API
    """A file of the live repository through GitHub's API (never the CDN, whose copy can be
    10 minutes old): its bytes, or ``None`` when it is not there.

    Raises:
        httpx.HTTPError: it could not be read.
    """
    api = env.get("GITHUB_API_URL") or "https://api.github.com"
    headers = {"Accept": "application/vnd.github.raw+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token := env.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    response = client.get(f"{api}/repos/{repository}/contents/{path}", headers=headers)
    if response.status_code == httpx.codes.NOT_FOUND:
        return None
    response.raise_for_status()
    return response.content


def make_client() -> httpx.Client:  # pragma: no cover - a real network client
    from snowlight.live.cli import make_client as live_client  # noqa: PLC0415

    return live_client()


def make_schools(config: "LiveConfig", env: Env) -> "DeployedSchools":  # pragma: no cover
    from snowlight.live.cli import make_schools as live_schools  # noqa: PLC0415

    return live_schools(config, env)


def read_files(
    config: "LiveConfig", env: Env, client: httpx.Client
) -> tuple[bytes | None, bytes | None]:  # pragma: no cover - GitHub's API
    repository = str(config.host.get("repository", ""))
    return (
        public_file(client, repository, CLOSINGS, env),
        public_file(client, repository, OPENS, env),
    )


@dataclass(slots=True)
class World:
    """The parts that touch the world; tests replace them."""

    env: Callable[[], Env] = field(default=lambda: dict(os.environ))
    client: Callable[[], httpx.Client] = make_client
    files: Callable[["LiveConfig", Env, httpx.Client], tuple[bytes | None, bytes | None]] = (
        read_files
    )
    schools: Callable[["LiveConfig", Env], "DeployedSchools"] = make_schools
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    pause: float = RETRY_PAUSE
    loopback: bool = False
    deadline: Callable[[], Clock] = Clock


WORLD = World()


@dataclass(frozen=True, slots=True)
class Ready:
    """A database with browsers to send to, and the key to sign with."""

    db: D1
    sender: Sender
    accounts: list[Account]


def _ready(
    client: httpx.Client, secrets: Secrets, pause: float, loopback: bool, now: datetime
) -> Ready | str:
    """The database, its accounts and the key, or the line that says why nothing is sent.

    Raises:
        D1Error: the database could not be read.
    """
    now_ms = int(now.timestamp() * 1000)
    try:
        db = D1.find(client, secrets, pause=pause)
        count = store.subscription_count(db, now_ms)
    except NoTablesError:
        return "the notification tables are not there yet (api.yml applies 0004_notify.sql)"
    if count == 0:
        return "no browser gets notifications"
    vapid = store.read_vapid(db)
    if vapid is None:
        return "no VAPID key pair yet (api.yml makes it)"
    return Ready(
        db=db, sender=Sender(client, vapid, loopback), accounts=store.read_accounts(db, now_ms)
    )


def run_status(args: argparse.Namespace, world: World | None = None) -> int:
    """Status pushes from the published closings file. Always exit 0: a pass that could not
    finish says so in one warning line."""
    world = world or WORLD
    env = world.env()
    secrets = Secrets.from_env(env)
    if secrets is None:
        _say("notify: no Cloudflare secrets: nothing to send")
        return 0
    try:
        return _status_run(args, world, env, secrets)
    except Exception as error:
        return _warn(error)


def _status_run(args: argparse.Namespace, world: World, env: Env, secrets: Secrets) -> int:
    with world.client() as client:
        ready = _ready(client, secrets, world.pause, world.loopback, world.clock())
        if isinstance(ready, str):
            _say(f"notify: {ready}: nothing to send")
            return 0
        wanted = {
            school.id
            for account in ready.accounts
            if account.settings.status
            for school in account.schools
        }
        if not wanted:
            _say("notify: no saved school with status notifications on: nothing to send")
            return 0
        return _status_pass(args, world, env, client, ready, wanted)


def _status_pass(  # noqa: PLR0911, PLR0913, PLR0917 - one pass's parts and its skips
    args: argparse.Namespace,
    world: World,
    env: Env,
    client: httpx.Client,
    ready: Ready,
    wanted: set[str],
) -> int:
    from snowlight.live.cli import LiveConfig  # noqa: PLC0415 - the status pass only

    now = world.clock()
    try:
        config = LiveConfig.load(args.config)
        closings_bytes, opens_bytes = world.files(config, env, client)
    except Exception as error:
        return _skip(f"the closings file could not be read ({type(error).__name__})")
    if closings_bytes is None:
        return _skip("no closings file")
    try:
        closings = ClosingsFile.from_json_bytes(closings_bytes)
    except ValueError:
        return _skip("the closings file does not validate")
    if not fresh(closings.generated_at, now):
        age = int((now - closings.generated_at).total_seconds() // 60)
        return _skip(f"the closings file is {age} min old")
    try:
        schools = world.schools(config, env)
    except Exception as error:
        return _skip(f"the deployed directory could not be read ({type(error).__name__})")
    if closings.directory != schools.stamp:
        return _skip("the closings file is for another directory")
    opens = None
    if opens_bytes is not None:
        try:
            found: OpensFile | None = OpensFile.from_json_bytes(opens_bytes)
        except ValueError:
            found = None
        if (
            found is not None
            and found.directory == schools.stamp
            and found.generated_at == closings.generated_at
        ):
            opens = found
    ids = schools.school_ids
    index = {school: position for position, school in enumerate(ids)}
    own = {
        index[school]: zone
        for school in wanted
        if school in index and (zone := schools.zone_of(index[school])) is not None
    }
    borrowed = schools.borrowed_zones(
        index[s] for s in wanted if s in index and index[s] not in own
    )
    zones = zones_for(wanted, index, {**own, **borrowed})
    sent = store.read_sent(ready.db, now.date() - timedelta(days=SENT_DAYS))
    pushes = status_pushes(
        ready.accounts,
        statuses(closings, ids, wanted),
        open_days(opens, ids, wanted),
        zones,
        sent,
        now,
    )
    report = deliver(ready.db, pushes, ready.accounts, ready.sender, now, world.deadline())
    store.prune_sent(ready.db, now.date() - timedelta(days=store.KEEP_DAYS))
    _say(f"notify status: {report.line()}")
    return 0


@dataclass(slots=True)
class ChanceNotifier:
    """Chance and night-before pushes after each predictions pass (``predict run``), from
    the file the pass made (the one the site shows) and the public closings file (a
    school-day that shows a status gets no chance push)."""

    secrets: Secrets
    client: httpx.Client
    closings: Callable[[], bytes | None]
    pause: float = RETRY_PAUSE
    loopback: bool = False
    deadline: Callable[[], Clock] = Clock

    def __call__(
        self, file: "PredictionsFile", directory: "DeployedDirectory", now: datetime
    ) -> str:
        """One pass: the line it says (counts only).

        Raises:
            D1Error: the database could not be read or written.
        """
        from snowlight.directory.points import NO_DISTRICT  # noqa: PLC0415

        ready = _ready(self.client, self.secrets, self.pause, self.loopback, now)
        if isinstance(ready, str):
            return f"notify: {ready}: nothing to send"
        wanted = {
            school.id
            for account in ready.accounts
            if account.settings.chance or account.settings.night_before
            for school in account.schools
        }
        if not wanted:
            return "notify: no saved school with chance notifications on: nothing to send"
        ids = directory.school_ids
        if ids is None or file.directory != directory.stamp:
            return "notify: the pass names no school ids for its directory: nothing to send"
        district_of = [
            None if int(value) == NO_DISTRICT else int(value)
            for value in directory.points.district.tolist()
        ]
        try:
            data = self.closings()
            shown = None if data is None else ClosingsFile.from_json_bytes(data)
        except Exception:
            shown = None
        pushes = chance_pushes(
            ready.accounts,
            outlooks(file, ids, district_of, wanted),
            status_days(shown, directory.stamp, ids, wanted, now),
            store.read_sent(ready.db, now.date() - timedelta(days=SENT_DAYS)),
            now,
        )
        report: Report = deliver(
            ready.db, pushes, ready.accounts, ready.sender, now, self.deadline()
        )
        return f"notify chance: {report.line()}"


def chance_notifier(
    env: Env, client: httpx.Client, closings: Callable[[], bytes | None]
) -> ChanceNotifier | None:
    """The predictions loop's notifier, or ``None`` without the Cloudflare secrets."""
    secrets = Secrets.from_env(env)
    if secrets is None:
        return None
    return ChanceNotifier(secrets=secrets, client=client, closings=closings)


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``notify`` and its action on ``subparsers``."""
    from snowlight.live.cli import DEFAULT_CONFIG  # noqa: PLC0415

    notify = subparsers.add_parser(
        "notify",
        help="web push notifications for saved schools",
        description="Send the notifications that are due.",
    )
    actions = notify.add_subparsers(dest="notify_action", metavar="ACTION", required=True)
    status = actions.add_parser(
        "status", help="status pushes from the published closings file (live-ingest.yml)"
    )
    status.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="live.yaml")
    status.set_defaults(handler=run_status)

"""``snowlight live rehearse``: the switch rehearsal before go-live (S8-E E8, live-drill.yml's
``switch``).

The owner's switch moves the admin's statuses from one writer of ``v1`` to another: today the
overrides job (live-ingest.yml's publish job), at go-live the reader in ``on``, and back on a
rollback. The rehearsal runs those three writers in turn against the prefix ``v1-rehearse``
of a **local folder host on the runner** (never the public live host, so the SYNTHETIC
status below is never committed anywhere or served to anyone):

1. the overrides writer (``live overrides --rehearse``), as the publish job runs it;
2. the reader in ``on`` (``live once --rehearse``: one pass that **reads no source**, so the
   rehearsal never asks a station page or a robots.txt again from a second runner, past the
   holds, robots rules and Crawl-delays the live reader keeps; every due source unread,
   G12b refuses the lists and the admin's statuses are published alone under the G12b/G12e
   exception, as at go-live with no list read);
3. the overrides writer again.

Each writer has its own cold state folder, as each has its own memory in production, and
nothing is pushed: the drill holds no Cloudflare secret, so it can neither read nor write
the D1 state (it refuses to run when one is set). The admin's statuses come from a SYNTHETIC
override served on this machine's loopback (one school of the deployed directory, open
today in its own zone), read through the same API path the writers use in production. After
each writer the override must be in the host's file, under that writer's stamp, within one
pass (5 minutes): the switch never drops it. At the end the rehearsal prefix is blanked and
held, and the folder is the runner's alone.
"""

import argparse
import json
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

from snowlight.live.overrides import DeployedSchools
from snowlight.live.publish import OPENS, REHEARSE, emergency_blank, release
from snowlight.live.publishers import Publisher
from snowlight.schemas.live import OpensFile

if TYPE_CHECKING:
    from snowlight.live.cli import LiveConfig, Loaders

SERVED_WITHIN: Final = timedelta(minutes=5)
"""One pass: the switch may not keep the override from being served longer."""
POLL: Final = 5.0
HOST_FOLDER: Final = "host"
"""The rehearsal's own folder host, under its ``--state`` folder."""
FORBIDDEN: Final = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")
"""The D1 secrets: the rehearsal never holds them (its state is local and cold)."""


@dataclass(frozen=True, slots=True)
class Fixture:
    """The SYNTHETIC override: one school (its index in the deployed directory), open today."""

    school: int
    body: bytes


def fixture(schools: DeployedSchools, now: datetime) -> Fixture:
    """An ``open`` override for today of the first school with a known zone.

    Raises:
        ValueError: no school of the directory has a known time zone.
    """
    for index, school_id in enumerate(schools.school_ids):
        zone = schools.zone_of(index)
        if zone is None:
            continue
        today = now.astimezone(ZoneInfo(zone)).date()
        override = {
            "scope": "school",
            "id": school_id,
            "status": "open",
            "days": [today.isoformat()],
            "time_zone": zone,
            "set_at": (now - timedelta(minutes=1)).astimezone(UTC).isoformat(),
            "expires_at": (now + timedelta(hours=3)).astimezone(UTC).isoformat(),
        }
        return Fixture(index, json.dumps({"overrides": [override]}).encode())
    raise ValueError("no school of the directory has a known time zone")


def _server(body: bytes) -> ThreadingHTTPServer:
    """The fixture at ``GET /v1/overrides`` on a loopback port."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.split("?")[0] != "/v1/overrides":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def shows(data: bytes | None, school: int) -> datetime | None:
    """The ``generated_at`` of an opens file that shows ``school``, else ``None``."""
    if data is None:
        return None
    try:
        found = OpensFile.from_json_bytes(data)
    except ValueError:
        return None
    return found.generated_at if any(item.school == school for item in found.opens) else None


type Served = Callable[[str], bytes | None]
type Step = Callable[[list[str], "Loaders"], int]


@dataclass(slots=True)
class Rehearsal:
    """One rehearsal (see the module)."""

    args: argparse.Namespace
    config: "LiveConfig"
    loaders: "Loaders"
    host: Publisher
    served: Served
    step: Step
    monotonic: Callable[[], float] = time.monotonic

    def say(self, text: str) -> None:
        print(f"rehearse: {text}", flush=True)  # noqa: T201 - the drill's log

    def run(self, env: Mapping[str, str]) -> int:
        now = self.loaders.clock()
        release(self.host, now, (REHEARSE,))  # an earlier rehearsal's final hold
        schools = self.loaders.schools(self.config, env)
        made = fixture(schools, now)
        server = _server(made.body)
        root = f"http://127.0.0.1:{server.server_address[1]}/"
        common = ["--config", str(self.args.config), "--internal", str(self.args.internal)]
        common += ["--site-data", str(self.args.site_data)]
        writer = ["live", "overrides", "--api", root, "--rehearse", *common]
        writer += ["--state", str(self.args.state / "overrides")]
        reader = ["live", "once", "--rehearse", *common, "--state", str(self.args.state / "reader")]
        reader += ["--directory", str(self.args.directory), "--aliases", str(self.args.aliases)]
        reader += ["--registry", str(self.args.registry), "--cache-dir", str(self.args.cache_dir)]
        stepped = replace(
            self.loaders, env=lambda: {**env, "LIVE_PUBLISH": "on", "SNOWLIGHT_API_ROOT": root}
        )
        failed: list[str] = []
        last: datetime | None = None
        steps = (
            ("overrides", writer, True),
            ("reader on", reader, True),
            ("overrides", writer, False),
        )
        try:
            for name, argv, must in steps:
                code = self.step(argv, stepped)
                found = self._served(name, code, made.school, last, must_publish=must)
                if found is None:
                    failed.append(name)
                last = found or last
        finally:
            server.shutdown()
            server.server_close()
            emergency_blank(self.host, self.loaders.clock(), (REHEARSE,))
            self.say(f"{REHEARSE} blanked and held")
        if failed:
            self.say(f"FAILED: the override was not served within one pass after {failed}")
            return 1
        self.say("the override was served within one pass of each switch")
        return 0

    def _served(
        self,
        name: str,
        code: int,
        school: int,
        last: datetime | None,
        *,
        must_publish: bool,
    ) -> datetime | None:
        """The stamp of the file showing the override after a writer, once the CDN serves
        it, within one pass; ``None`` when it is not shown or not served in time. The
        overrides writer and the reader in ``on`` must publish it anew after a switch to
        them (``must_publish``); the overrides writer back after the reader may keep the
        reader's file, which shows it, when nothing changed (its heartbeat)."""
        written = shows(self.host.read(f"{REHEARSE}/{OPENS}"), school)
        new = written is not None and (last is None or written > last)
        if written is None or (must_publish and not new):
            self.say(f"{name}: exit {code}; the host's file does not show the override anew")
            return None
        what = "published" if new else "kept"
        begin = self.monotonic()
        while self.monotonic() - begin <= SERVED_WITHIN.total_seconds():
            if shows(self.served(f"{REHEARSE}/{OPENS}"), school) == written:
                took = round(self.monotonic() - begin)
                self.say(
                    f"{name}: exit {code}; {what} {written.isoformat()}; served {took} s later"
                )
                return written
            self.loaders.sleep(POLL)
        self.say(f"{name}: {what} {written.isoformat()}; not served within one pass")
        return None


def preflight(env: Mapping[str, str], publish: str) -> str | None:
    """Why the rehearsal may not run (``None``: it may): a D1 secret in the environment, or
    ``LIVE_PUBLISH`` on (``publish``, normalized: the rehearsal is a before-go-live drill)."""
    held = [name for name in FORBIDDEN if env.get(name)]
    if held:
        return f"the switch rehearsal holds no D1 secret: {', '.join(held)} is set"
    if publish == "on":
        return "LIVE_PUBLISH is on: the switch rehearsal runs before go-live only"
    return None

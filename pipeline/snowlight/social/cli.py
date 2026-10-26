"""``snowlight social post``, ``render`` and ``scan-log`` (social-post.yml).

Every line the command prints passes :func:`snowlight.social.logscan.scrub` against the
secrets in the environment and the tokens it masked, so no secret reaches the log even by
mistake. In GitHub Actions each token the run derives (the access token, the rotated and
the stored refresh token, the Basic credentials) is registered with ``::add-mask::`` before
it is used; elsewhere nothing is printed for it at all.
"""

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, TextIO

import httpx

from snowlight.social import logscan
from snowlight.social.post import Deps, run
from snowlight.social.rules import FactsError, chances_shown, closings_shown, parse_facts
from snowlight.social.xapi import XClient

SECRET_NAMES: Final = (
    "X_CLIENT_ID",
    "X_CLIENT_SECRET",
    "X_REFRESH_TOKEN",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
)
COMMITS_BACK: Final = timedelta(days=3)


class Output:
    """The command's only way to print: scrubbed lines, and masks in Actions only."""

    def __init__(self, env: Mapping[str, str], stream: TextIO | None = None) -> None:
        self._secrets = [env.get(name, "") for name in SECRET_NAMES]
        self._actions = env.get("GITHUB_ACTIONS") == "true"
        self._stream = stream

    def _write(self, text: str) -> None:
        stream = self._stream or sys.stdout
        stream.write(text)
        stream.flush()

    def say(self, line: str) -> None:
        """Write one log line: scrubbed, on one line, and never a workflow command but the
        annotation it starts with (:func:`logscan.one_line`)."""
        self._write(logscan.one_line(logscan.scrub(line, self._secrets)) + "\n")

    def mask(self, value: str) -> None:
        """Register a derived token with ``::add-mask::`` (each whitespace-free piece of it,
        so a value can never end its own command line)."""
        for piece in logscan.CONTROL.sub(" ", value).split():
            if piece in self._secrets:
                continue
            self._secrets.append(piece)
            if self._actions:
                self._write(f"::add-mask::{piece}\n")


def commits(root: Path, since: datetime | None) -> list[str]:
    """The subjects of the commits since the last post (the last 3 days at first)."""
    start = since or datetime.now(UTC) - COMMITS_BACK
    result = subprocess.run(  # noqa: S603 - fixed arguments
        ["git", "log", "--no-merges", "--format=%s", "-n", "30", f"--since={start.isoformat()}"],  # noqa: S607 - git from PATH
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip()[:200] for line in result.stdout.splitlines() if line.strip()]


def _post(args: argparse.Namespace) -> int:
    env = dict(os.environ)
    output = Output(env)
    root = Path(args.root).resolve()
    with httpx.Client() as client:
        deps = Deps(
            http=client,
            x=XClient(client, mask=output.mask),
            say=output.say,
            mask=output.mask,
            commits=lambda since: commits(root, since),
        )
        return run(env, root, args.event, deps, Path(args.picture) if args.picture else None)


def _render(args: argparse.Namespace) -> int:
    # Imported here: the post and scan commands need no browser library.
    from snowlight.social.render import SITE, View, render  # noqa: PLC0415

    output = Output(dict(os.environ))
    if bool(args.view) != bool(args.place):
        output.say("::error::social: --view and --place go together")
        return 2
    root = Path(args.root).resolve()
    try:
        facts = parse_facts((root / "social" / "facts.md").read_text(encoding="utf-8"))
    except (OSError, FactsError) as error:
        output.say(f"::error::social: social/facts.md could not be read ({error})")
        return 1
    if not chances_shown(facts):
        output.say("social: chances are TESTING in social/facts.md: no picture gives a chance")
    if not closings_shown(facts):
        output.say("social: closings are not LIVE in social/facts.md: no picture shows closings")
    taken = render(
        Path(args.out),
        facts=facts,
        site=args.site or SITE,
        say=output.say,
        live=Path(args.live_dir) if args.live_dir else None,
        view=View(args.view, args.place) if args.view else None,
        fallback=args.fallback,
    )
    if taken is None:
        output.say("::warning::social: no fresh picture; the post uses the library's newest one")
        return 1
    return 0


def _relay_out(args: argparse.Namespace) -> int:
    from snowlight.social.relay import RelayError, send  # noqa: PLC0415 - the render job only

    def write(line: str) -> None:
        # The bundle's own lines: base64 of public cards, never through the scrub (which
        # would mask them as secret-shaped), and never a workflow command (they start with
        # the relay's mark).
        sys.stdout.write(line + "\n")

    output = os.environ.get("GITHUB_OUTPUT")
    try:
        digest = send(Path(args.dir), write, Path(output) if output else None)
    except (OSError, RelayError) as error:
        sys.stdout.write(f"::warning::social: the cards were not handed over ({error})\n")
        return 1
    sys.stdout.write(f"social: the cards are handed over (digest {digest})\n")
    return 0


def _relay_in(args: argparse.Namespace) -> int:
    from snowlight.social.relay import RelayError, receive  # noqa: PLC0415 - the post job only

    output = Output(dict(os.environ))
    try:
        names = receive(Path(args.log).read_text(errors="replace"), args.digest, Path(args.out))
    except (OSError, RelayError) as error:
        output.say(f"::warning::social: the render job's cards were not taken ({error})")
        return 1
    output.say(f"social: took the render job's {', '.join(names)}")
    return 0


def _scan(args: argparse.Namespace) -> int:
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(errors="replace")
    found = logscan.findings(text)
    for line in found[:20]:
        sys.stdout.write(f"::error::secret-shaped value at {line}\n")
    if not found:
        sys.stdout.write(f"social: no secret-shaped value in {len(text.splitlines())} log lines\n")
    return 1 if found else 0


def register(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    social = commands.add_parser("social", help="Post on the X account @SnowlightMap.")
    sub = social.add_subparsers(title="social commands", metavar="<social command>", required=True)
    post = sub.add_parser("post", help="Post at most one queued or Haiku-written post.")
    post.add_argument("--root", default="..", help="The repository root (holds social/).")
    post.add_argument(
        "--event", default="push", help="The GitHub event (Haiku writes only on 'schedule')."
    )
    post.add_argument(
        "--picture", default="", help="The fresh picture's folder (picture.json, picture.png)."
    )
    post.set_defaults(handler=_post)
    shot = sub.add_parser("render", help="Take the post's fresh picture of the live site.")
    shot.add_argument(
        "--out", required=True, help="The folder for picture.png, picture.json and the cards."
    )
    shot.add_argument("--root", default="..", help="The repository root (holds social/).")
    shot.add_argument("--site", default="", help="Another site address (a local build).")
    shot.add_argument(
        "--live-dir", default="", help="Serve the live files from this folder (a dry run)."
    )
    shot.add_argument(
        "--view", default="", help="A calm ?at=lat,lon,zoom view (the image library only)."
    )
    shot.add_argument("--place", default="", help="The --view's place, in plain words.")
    shot.add_argument(
        "--fallback",
        action="store_true",
        help='Make dated library cards ("From <date>", no clock) instead of fresh ones.',
    )
    shot.set_defaults(handler=_render)
    out = sub.add_parser("relay-out", help="Print the render job's cards for the post job.")
    out.add_argument("--dir", required=True, help="The render's folder.")
    out.set_defaults(handler=_relay_out)
    take = sub.add_parser("relay-in", help="Take the render job's cards out of its log.")
    take.add_argument("--log", required=True, help="The render job's log, as a file.")
    take.add_argument("--digest", required=True, help="The render job's digest output.")
    take.add_argument("--out", required=True, help="The folder to write the cards to.")
    take.set_defaults(handler=_relay_in)
    scan = sub.add_parser("scan-log", help="Fail when a log holds a secret-shaped value.")
    scan.add_argument("file", help="The log file, or - for standard input.")
    scan.set_defaults(handler=_scan)

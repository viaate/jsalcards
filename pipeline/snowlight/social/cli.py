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
        self._write(logscan.scrub(line, self._secrets) + "\n")

    def mask(self, value: str) -> None:
        if not value:
            return
        self._secrets.append(value)
        if self._actions:
            self._write(f"::add-mask::{value}\n")


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
    from snowlight.social.render import SITE, render  # noqa: PLC0415

    output = Output(dict(os.environ))
    taken = render(
        Path(args.out),
        site=args.site or SITE,
        say=output.say,
        live=Path(args.live_dir) if args.live_dir else None,
    )
    if taken is None:
        output.say("::warning::social: no fresh picture; the post uses the library's newest one")
        return 1
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
    shot.add_argument("--out", required=True, help="The folder for picture.png and picture.json.")
    shot.add_argument("--site", default="", help="Another site address (a local build).")
    shot.add_argument(
        "--live-dir", default="", help="Serve the live files from this folder (a dry run)."
    )
    shot.set_defaults(handler=_render)
    scan = sub.add_parser("scan-log", help="Fail when a log holds a secret-shaped value.")
    scan.add_argument("file", help="The log file, or - for standard input.")
    scan.set_defaults(handler=_scan)

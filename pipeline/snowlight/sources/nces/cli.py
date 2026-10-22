"""The ``snowlight nces check`` command: the weekly NCES release check."""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

from snowlight.directory.config import DEFAULT_CONFIG_PATH, load_config
from snowlight.places.pins import DEFAULT_PLACES_PINS_PATH, load_places_pins
from snowlight.sources.nces.releases import (
    IssueError,
    Verdict,
    check,
    file_issue,
    issue_body,
    make_client,
)


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``nces`` and its ``check`` action."""
    nces = subparsers.add_parser(
        "nces",
        help="NCES releases",
        description="Whether NCES has published files newer than the pinned ones.",
    )
    actions = nces.add_subparsers(dest="nces_action", metavar="ACTION", required=True)
    run = actions.add_parser(
        "check", help="ask NCES about the next school year of each pinned file family"
    )
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="directory.yaml")
    run.add_argument(
        "--places-pins", type=Path, default=DEFAULT_PLACES_PINS_PATH, help="places.yaml"
    )
    run.add_argument("--report", type=Path, default=None, help="also write the findings as JSON")
    run.add_argument(
        "--issue",
        action="store_true",
        help=(
            "when something new is published, open or update the GitHub issue (needs "
            "GITHUB_TOKEN and GITHUB_REPOSITORY)"
        ),
    )
    run.set_defaults(handler=run_check)


def github_client(token: str) -> httpx.Client:  # pragma: no cover - a real network client
    """A client for the GitHub REST API."""
    return httpx.Client(
        timeout=30.0,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def run_check(args: argparse.Namespace) -> int:
    """Check, print each finding, and file the issue when asked.

    Exit 1 when filing fails, or when no probe could tell (NCES blocked the runner or
    changed its site), so a blind check turns the job red instead of staying quiet.
    """
    config, places = load_config(args.config), load_places_pins(args.places_pins)
    with make_client() as client:
        findings = check(client, config, places)
    for finding in findings:
        line = f"{finding.family}: {finding.url}: {finding.verdict.value} ({finding.detail})"
        sys.stdout.write(line + "\n")
        if finding.verdict is Verdict.UNKNOWN:
            sys.stdout.write(f"::warning::NCES release check could not tell: {line}\n")
    if args.report is not None:
        records = [
            {"family": f.family, "url": f.url, "verdict": f.verdict.value, "detail": f.detail}
            for f in findings
        ]
        args.report.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    if findings and all(f.verdict is Verdict.UNKNOWN for f in findings):
        sys.stdout.write(
            f"::error::NCES release check could not tell for any of {len(findings)} files; "
            "the check is blind until NCES answers the runner again\n"
        )
        return 1
    body = issue_body(findings)
    if body is None:
        sys.stdout.write("nothing newer than the pins is published\n")
        return 0
    sys.stdout.write(f"::notice::NCES has published files newer than the pins\n{body}")
    if not args.issue:
        return 0
    token, repository = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        sys.stderr.write("snowlight nces check --issue needs GITHUB_TOKEN and GITHUB_REPOSITORY\n")
        return 1
    try:
        with github_client(token) as github:
            sys.stdout.write(file_issue(github, repository, body) + "\n")
    except (IssueError, httpx.HTTPError) as error:
        sys.stderr.write(f"snowlight nces check: the issue: {error}\n")
        return 1
    return 0

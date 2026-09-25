"""Command-line entry point for the pipeline."""

import argparse
from collections.abc import Callable, Sequence

from snowlight import __version__
from snowlight.places import cli as places_cli


def build_parser() -> argparse.ArgumentParser:
    """Return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="snowlight",
        description="Build the static files the Snowlight map reads.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(title="commands", metavar="<command>")
    places_cli.register(commands)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code.

    Each command sets a ``handler`` default that takes the parsed arguments and
    returns the exit code; with no command the help text is printed.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Callable[[argparse.Namespace], int] | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)

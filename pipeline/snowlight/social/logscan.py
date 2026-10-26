"""Secret-shaped values in a log, and the scrubbing every line of ``snowlight social`` passes.

A value is secret-shaped when it is a run of at least :data:`MIN_LENGTH` token characters
(letters, digits, ``_ - ~ + = .``) holding an upper-case letter, a lower-case letter and a
digit, or starts like a known key (``sk-ant-``, ``ghs_``, ``ghp_``, ``github_pat_``). Hex
digests, UUIDs, timestamps and paths are not (no mixed case, or split by ``/``). A finding
names its line and length, never the value.
"""

import re
from collections.abc import Iterable
from typing import Final

MIN_LENGTH: Final = 30
RUN: Final = re.compile(r"[A-Za-z0-9_\-~+=.]{%d,}" % MIN_LENGTH)  # noqa: UP031 - a regex
PREFIXES: Final = ("sk-ant-", "ghs_", "ghp_", "gho_", "github_pat_")
MASK: Final = "***"


def _shaped(value: str) -> bool:
    if value.startswith(PREFIXES):
        return True
    return (
        any(char.isupper() for char in value)
        and any(char.islower() for char in value)
        and any(char.isdigit() for char in value)
    )


def findings(text: str) -> list[str]:
    """Where a text holds a secret-shaped value: ``line N: M characters`` each."""
    found: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        found.extend(
            f"line {number}: {len(match)} characters"
            for match in RUN.findall(line)
            if _shaped(match)
        )
    return found


def scrub(line: str, secrets: Iterable[str]) -> str:
    """The line with every known secret and every secret-shaped value replaced by ``***``."""
    for secret in sorted((value for value in secrets if len(value) >= 8), key=len, reverse=True):  # noqa: PLR2004 - too short to be a secret
        line = line.replace(secret, MASK)
    return RUN.sub(lambda match: MASK if _shaped(match.group()) else match.group(), line)

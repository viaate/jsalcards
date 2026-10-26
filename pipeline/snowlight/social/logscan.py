"""Secret-shaped values in a log, and the scrubbing every line of ``snowlight social`` passes.

A value is secret-shaped when it is a run of at least :data:`MIN_LENGTH` token characters
(letters, digits, ``_ - ~ + = .``) holding an upper-case letter, a lower-case letter and a
digit, or starts like a known key (``sk-ant-``, ``ghs_``, ``ghp_``, ``github_pat_``). Hex
digests, UUIDs, timestamps and paths are not (no mixed case, or split by ``/``). A finding
names its line and length, never the value.

Every line the command prints is also made one plain line (:func:`one_line`): no line
break or other control character, and no workflow command (``::stop-commands::``,
``::add-mask::``, ``##[...]``) but the ``::error::``, ``::warning::`` or ``::notice::`` the
code itself starts a line with. Text from outside (Haiku's answers, an error) can then never
start a command line, so it can never stop the runner from reading the run's masks.
"""

import re
from collections.abc import Iterable
from typing import Final

MIN_LENGTH: Final = 30
RUN: Final = re.compile(r"[A-Za-z0-9_\-~+=.]{%d,}" % MIN_LENGTH)  # noqa: UP031 - a regex
PREFIXES: Final = ("sk-ant-", "ghs_", "ghp_", "gho_", "github_pat_")
MASK: Final = "***"
CONTROL: Final = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]")
"""Line breaks and every other control character."""
ANNOTATIONS: Final = ("::error::", "::warning::", "::notice::")
"""The only workflow commands a line may start with (written by the code itself)."""
COMMAND_MARKS: Final = (("::", ": :"), ("##[", "# #["), ("##vso[", "# #vso["))


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


def one_line(line: str) -> str:
    """``line`` as one log line that is no workflow command but its own leading annotation:
    control characters become spaces, and every other ``::`` or ``##[`` is broken up."""
    flat = CONTROL.sub(" ", line).strip()
    head = next((mark for mark in ANNOTATIONS if flat.startswith(mark)), "")
    body = flat[len(head) :]
    for mark, safe in COMMAND_MARKS:
        while mark in body:
            body = body.replace(mark, safe)
    return head + body

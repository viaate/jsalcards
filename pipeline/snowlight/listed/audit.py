"""The precision audit: a stratified random sample of accepted matches, for a person to check.

:func:`accepted_matches` reads ``matches.jsonl`` (written by the build: one line per
distinct listing, a list's name in its context) and keeps the accepted ones. Each
falls in a stratum: the state of the record it names, and its basis (``school``
when it names a school, ``district`` when it names only districts, ``roster``
for a roster entry). :func:`draw` samples ``size`` of them: every stratum gets its
share of the sample in proportion to its size, and at least one, and within a
stratum the matches are drawn at random with a fixed seed, so the same file and
seed always give the same sample. A person then checks each against the raw
rows it came from, and records a verdict (``pipeline/tests/listed/audit/``).
"""

import json
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from snowlight.output import JSONValue, write_json

DEFAULT_SIZE: Final = 200
DEFAULT_SEED: Final = 20260928


@dataclass(frozen=True, slots=True)
class Match:
    """One accepted listing, as ``matches.jsonl`` gives it."""

    stratum: tuple[str, str]
    line: Mapping[str, JSONValue]

    @property
    def key(self) -> tuple[str, str, str]:
        """The listing: source, name and section."""
        return (
            str(self.line.get("source_id")),
            str(self.line.get("name")),
            str(self.line.get("section") or ""),
        )


def basis_of(line: Mapping[str, JSONValue]) -> str:
    """``roster``, ``school`` or ``district``: how a listing reaches its schools."""
    if line.get("kind") == "roster":
        return "roster"
    targets = line.get("targets")
    items = targets if isinstance(targets, list) else []
    kinds = {target.get("kind") for target in items if isinstance(target, dict)}
    return "school" if "school" in kinds else "district"


def state_of(line: Mapping[str, JSONValue]) -> str:
    """The state of the first record a listing names."""
    targets = line.get("targets")
    if isinstance(targets, list) and targets and isinstance(targets[0], dict):
        return str(targets[0].get("state"))
    return ""


def accepted_matches(path: Path) -> list[Match]:
    """The accepted listings of ``matches.jsonl``, in file order."""
    found: list[Match] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, dict) and item.get("accepted") is True:
                found.append(Match((state_of(item), basis_of(item)), item))
    return found


def allocate(sizes: Mapping[tuple[str, str], int], size: int) -> dict[tuple[str, str], int]:
    """How many to draw from each stratum: proportional, at least one, ``size`` in all.

    When there are more strata than ``size``, the largest strata get one each.

    Raises:
        ValueError: ``size`` is not positive.
    """
    if size <= 0:
        raise ValueError("the sample size must be positive")
    strata = sorted(sizes, key=lambda key: (-sizes[key], key))
    total = sum(sizes.values())
    if total <= size:
        return dict(sizes)
    if len(strata) >= size:
        return {key: 1 if position < size else 0 for position, key in enumerate(strata)}
    shares = {key: size * sizes[key] / total for key in strata}
    counts = {key: min(sizes[key], max(1, int(shares[key]))) for key in strata}
    while sum(counts.values()) < size:
        key = max(
            (k for k in strata if counts[k] < sizes[k]),
            key=lambda k: (shares[k] - counts[k], sizes[k], k),
        )
        counts[key] += 1
    while sum(counts.values()) > size:
        key = max((k for k in strata if counts[k] > 1), key=lambda k: (counts[k] - shares[k], k))
        counts[key] -= 1
    return counts


def draw(
    matches: Sequence[Match], *, size: int = DEFAULT_SIZE, seed: int = DEFAULT_SEED
) -> list[Match]:
    """A stratified random sample of ``matches`` (see the module docstring)."""
    by_stratum: dict[tuple[str, str], list[Match]] = defaultdict(list)
    for match in matches:
        by_stratum[match.stratum].append(match)
    counts = allocate({key: len(items) for key, items in by_stratum.items()}, size)
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not a secret
    drawn: list[Match] = []
    for key in sorted(by_stratum):
        items = sorted(by_stratum[key], key=lambda m: m.key)
        drawn.extend(rng.sample(items, counts.get(key, 0)))
    return sorted(drawn, key=lambda m: (m.stratum, m.key))


def write_sample(path: Path, drawn: Sequence[Match], *, seed: int) -> None:
    """Write the sample for review."""
    write_json(
        path,
        {
            "seed": seed,
            "size": len(drawn),
            "matches": [{"stratum": list(match.stratum), **dict(match.line)} for match in drawn],
        },
    )

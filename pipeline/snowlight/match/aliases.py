"""Hand-pinned listings: exact listing text, per market, mapped to NCES ids.

``config/aliases.yaml`` settles the listings the matcher cannot place on its own
(an acronym such as ``"FCPS"``, a nickname, a diocese's name for its school).
An alias always wins: when the listing's market and text are pinned, the matcher
returns those records without scoring anything. Each entry is added by a person
who has checked the listing against the NCES records, usually from the unmatched
queue (:mod:`snowlight.match.queue`), which lists each unplaced listing with its
best candidates.

A listing may name one record or several: a school system NCES splits into
districts that the matcher does not know as one
(:mod:`snowlight.match.systems`) is pinned to every one of them, and the
listing's status reaches the schools of all of them
(:attr:`~snowlight.match.matcher.MatchResult.targets`).

The file::

    schema_version: 1
    markets:
      <market id>:              # the closings source's id, lowercase
        "<listing text>": "<NCES id>"
        "<listing text>": ["<NCES id>", "<NCES id>", ...]

Listing text is compared exactly, except that runs of whitespace count as one
space, the ends are trimmed and case is ignored (:func:`alias_key`).
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped, unused-ignore]
from pydantic import BaseModel, ConfigDict, field_validator

from snowlight.match.directory import Directory

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ALIASES_PATH = PIPELINE_ROOT / "config" / "aliases.yaml"

_MARKET = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_RECORD_ID = re.compile(r"[A-Za-z0-9-]{1,16}")


def alias_key(text: str) -> str:
    """Return the form listing text is compared in: NFC, one-space runs, trimmed, case-folded."""
    return " ".join(unicodedata.normalize("NFC", text).split()).casefold()


type Pinned = str | list[str]
"""One NCES id, or several a listing names together."""


def _ids(pinned: str | Sequence[str]) -> tuple[str, ...]:
    return (pinned,) if isinstance(pinned, str) else tuple(pinned)


class AliasFile(BaseModel):
    """The validated contents of ``aliases.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    markets: dict[str, dict[str, Pinned]]

    @field_validator("markets")
    @classmethod
    def _entries(cls, markets: dict[str, dict[str, Pinned]]) -> dict[str, dict[str, Pinned]]:
        for market, entries in markets.items():
            if not _MARKET.fullmatch(market):
                raise ValueError(f"market id {market!r} must be lowercase letters, digits, . _ -")
            seen: dict[str, str] = {}
            for text, pinned in entries.items():
                key = alias_key(text)
                if not key:
                    raise ValueError(f"{market}: an alias has empty listing text")
                ids = _ids(pinned)
                if not ids:
                    raise ValueError(f"{market}: {text!r} maps to no NCES id")
                for record_id in ids:
                    if not _RECORD_ID.fullmatch(record_id):
                        raise ValueError(
                            f"{market}: {text!r} maps to {record_id!r}, not an NCES id"
                        )
                if len(set(ids)) != len(ids):
                    raise ValueError(f"{market}: {text!r} maps to one NCES id twice")
                if key in seen:
                    raise ValueError(f"{market}: {seen[key]!r} and {text!r} are the same listing")
                seen[key] = text
        return markets


@dataclass(frozen=True, slots=True)
class Aliases:
    """Pinned listings, looked up by market and :func:`alias_key`.

    ``table`` maps a market to its pinned listings' keys, each to one NCES id or
    a tuple of them.
    """

    table: Mapping[str, Mapping[str, str | tuple[str, ...]]] = field(default_factory=dict)

    @classmethod
    def from_file(cls, contents: AliasFile) -> "Aliases":
        """Index a validated alias file."""
        return cls(
            {
                market: {alias_key(text): _ids(pinned) for text, pinned in entries.items()}
                for market, entries in contents.markets.items()
            }
        )

    def __len__(self) -> int:
        return sum(len(entries) for entries in self.table.values())

    def lookup(self, market: str | None, listing: str) -> tuple[str, ...] | None:
        """Return the NCES ids pinned for ``listing`` in ``market`` (one or more), or ``None``."""
        if market is None:
            return None
        pinned = self.table.get(market, {}).get(alias_key(listing))
        return None if pinned is None else _ids(pinned)

    def problems(self, directory: Directory) -> list[str]:
        """Describe every pinned NCES id that is not in ``directory``, sorted."""
        return sorted(
            f"{market}: {text!r} maps to {record_id}, which is not in the directory"
            for market, entries in self.table.items()
            for text, pinned in entries.items()
            for record_id in _ids(pinned)
            if record_id not in directory
        )


def load_aliases(path: Path = DEFAULT_ALIASES_PATH) -> Aliases:
    """Load and validate an alias file (``config/aliases.yaml`` by default)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Aliases.from_file(AliasFile.model_validate(raw))

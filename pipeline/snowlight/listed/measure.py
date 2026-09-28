"""Per-school evidence, and the SEEN, ROSTER and LISTED shares.

For every directory school, :func:`aggregate` gathers what ties it to a closings
list:

* SEEN, directly: an accepted match names the school itself (basis ``school``);
* SEEN, through its district: an accepted match names its district (NCES LEAID),
  and every school of that district counts (basis ``district``);
* ROSTER: an organization a list's published roster registers matches the school
  or its district (basis ``roster`` when the school is not also SEEN).

LISTED is SEEN or ROSTER. Nothing else makes a school listed.

:func:`tally` counts them nationally and per state (the directory's state, as
the coverage measure counts schools), plain and closure-weighted. The weights are
the ones the coverage measure uses (``closure-weights.json``, a weight per NWS
county): each school counts the weight of the NWS county it is placed in
(:func:`snowlight.weights.schools.place_schools`), and a school that no weighted
county holds counts in the plain share only.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import polars as pl

from snowlight.listed.evidence import ListRow
from snowlight.listed.matching import Outcome
from snowlight.listed.rosters import RosterEntry
from snowlight.output import JSONValue
from snowlight.weights.schools import Placement

BASES: Final = ("school", "district", "roster")
FIPS_LENGTH: Final = 5
SHARE_DIGITS: Final = 4
WEIGHT_DIGITS: Final = 1


class MeasureError(ValueError):
    """The inputs to the measure are missing or inconsistent."""


@dataclass(slots=True)
class Evidence:
    """What ties one school to closings lists (mutable while it is gathered)."""

    direct: bool = False
    district: bool = False
    roster: bool = False
    sources: set[str] = field(default_factory=set)
    first_seen: str | None = None
    last_seen: str | None = None
    rows_seen: int = 0

    @property
    def seen(self) -> bool:
        """True when an accepted match of a real row reaches the school."""
        return self.direct or self.district

    @property
    def basis(self) -> str | None:
        """The strongest tie: ``school``, ``district``, ``roster`` or ``None``."""
        if self.direct:
            return "school"
        if self.district:
            return "district"
        return "roster" if self.roster else None


def aggregate(
    rows: Iterable[tuple[ListRow, Outcome]],
    entries: Iterable[tuple[RosterEntry, Outcome]],
) -> dict[str, Evidence]:
    """Gather each school's evidence from matched rows and roster entries.

    A row counts once per school it reaches, whichever way it reaches it.
    """
    found: dict[str, Evidence] = {}
    for row, outcome in rows:
        if not outcome.accepted:
            continue
        for school_id, direct in _reached(outcome):
            evidence = found.setdefault(school_id, Evidence())
            if direct:
                evidence.direct = True
            else:
                evidence.district = True
            evidence.sources.add(row.source_id)
            evidence.rows_seen += 1
            if evidence.first_seen is None or row.fetched_at < evidence.first_seen:
                evidence.first_seen = row.fetched_at
            if evidence.last_seen is None or row.fetched_at > evidence.last_seen:
                evidence.last_seen = row.fetched_at
    for entry, outcome in entries:
        if not outcome.accepted:
            continue
        for school_id, _direct in _reached(outcome):
            evidence = found.setdefault(school_id, Evidence())
            evidence.roster = True
            evidence.sources.add(entry.roster)
    return found


def _reached(outcome: Outcome) -> list[tuple[str, bool]]:
    return [(school, True) for school in outcome.direct] + [
        (school, False) for school in outcome.via_district
    ]


def _instant(text: str | None) -> datetime | None:
    if text is None:
        return None
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


SCHOOL_SCHEMA: Final[dict[str, pl.DataType]] = {
    "id": pl.String(),
    "state": pl.String(),
    "seen": pl.Boolean(),
    "roster": pl.Boolean(),
    "basis": pl.String(),
    "source_ids": pl.List(pl.String()),
    "first_seen": pl.Datetime("us", "UTC"),
    "last_seen": pl.Datetime("us", "UTC"),
    "rows_seen": pl.UInt32(),
}
"""The columns of ``schools.parquet``, one row per directory school in directory order."""


def school_table(
    schools: Sequence[tuple[str, str]], evidence: Mapping[str, Evidence]
) -> pl.DataFrame:
    """One row per directory school (``(id, state)`` in directory order).

    Raises:
        MeasureError: evidence names a school the directory does not hold.
    """
    known = {school_id for school_id, _state in schools}
    stray = sorted(set(evidence) - known)
    if stray:
        raise MeasureError(f"evidence for schools outside the directory: {stray[:5]}")
    empty = Evidence()
    columns: dict[str, list[object]] = {name: [] for name in SCHOOL_SCHEMA}
    for school_id, state in schools:
        item = evidence.get(school_id, empty)
        columns["id"].append(school_id)
        columns["state"].append(state)
        columns["seen"].append(item.seen)
        columns["roster"].append(item.roster)
        columns["basis"].append(item.basis)
        columns["source_ids"].append(sorted(item.sources))
        columns["first_seen"].append(_instant(item.first_seen))
        columns["last_seen"].append(_instant(item.last_seen))
        columns["rows_seen"].append(item.rows_seen)
    return pl.DataFrame(columns, schema=SCHOOL_SCHEMA)


# Weights ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClosureWeights:
    """Closure weights per NWS county, as ``closure-weights.json`` gives them."""

    by_county: Mapping[str, float]
    sha256: str
    generated_at: str


def load_closure_weights(path: Path) -> ClosureWeights:
    """Read ``closure-weights.json`` (each county's ``fips`` and ``weight``).

    Raises:
        MeasureError: the file is not a closure-weights file.
    """
    raw = path.read_bytes()
    data = json.loads(raw)
    counties = data.get("counties") if isinstance(data, dict) else None
    if not isinstance(counties, list) or not counties:
        raise MeasureError(f"{path.name}: no county list")
    by_county: dict[str, float] = {}
    for item in counties:
        fips = item.get("fips") if isinstance(item, dict) else None
        weight = item.get("weight") if isinstance(item, dict) else None
        if (
            not isinstance(fips, str)
            or len(fips) != FIPS_LENGTH
            or isinstance(weight, bool)
            or not isinstance(weight, int | float)
            or weight < 0
        ):
            raise MeasureError(f"{path.name}: a county has no FIPS code or weight: {item!r}")
        if fips in by_county:
            raise MeasureError(f"{path.name}: county {fips} is listed twice")
        by_county[fips] = float(weight)
    generated = data.get("generated_at") if isinstance(data, dict) else None
    return ClosureWeights(by_county, hashlib.sha256(raw).hexdigest(), str(generated))


def school_weights(weights: ClosureWeights, placement: Placement) -> dict[str, float]:
    """Each placed school's weight: its NWS county's, when the weights list that county."""
    found: dict[str, float] = {}
    for school in placement.schools:
        weight = weights.by_county.get(school.nws_fips)
        if weight is not None:
            found[school.school_id] = weight
    return found


# Tallies ---------------------------------------------------------------------------------

_KINDS: Final = ("seen", "roster", "listed")


@dataclass(slots=True)
class Tally:
    """Counts of one group of schools, plain and weighted."""

    schools: int = 0
    weighted: float = 0.0
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_KINDS, 0))
    sums: dict[str, float] = field(default_factory=lambda: dict.fromkeys(_KINDS, 0.0))

    def add(self, flags: Mapping[str, bool], weight: float | None) -> None:
        """Count one school with its flags and weight (``None``: plain share only)."""
        self.schools += 1
        if weight is not None:
            self.weighted += weight
        for kind in _KINDS:
            if flags[kind]:
                self.counts[kind] += 1
                if weight is not None:
                    self.sums[kind] += weight

    def to_json(self) -> dict[str, JSONValue]:
        """The tally as ``listed.json`` gives it."""
        out: dict[str, JSONValue] = {
            "schools": self.schools,
            "weighted_schools": round(self.weighted, WEIGHT_DIGITS),
        }
        for kind in _KINDS:
            count, summed = self.counts[kind], self.sums[kind]
            out[kind] = {
                "count": count,
                "share": round(count / self.schools, SHARE_DIGITS) if self.schools else 0.0,
                "weighted": round(summed, WEIGHT_DIGITS),
                "weighted_share": (
                    round(summed / self.weighted, SHARE_DIGITS) if self.weighted > 0 else 0.0
                ),
            }
        return out


def tally(
    table: pl.DataFrame, weights: Mapping[str, float] | None
) -> tuple[Tally, dict[str, Tally]]:
    """Count SEEN, ROSTER and LISTED nationally and per state (plain and weighted).

    With ``weights`` ``None`` the weighted parts are zero.
    """
    national = Tally()
    states: dict[str, Tally] = {}
    for school_id, state, seen, roster in table.select("id", "state", "seen", "roster").iter_rows():
        flags = {"seen": bool(seen), "roster": bool(roster), "listed": bool(seen or roster)}
        weight = weights.get(school_id) if weights is not None else None
        national.add(flags, weight)
        states.setdefault(str(state), Tally()).add(flags, weight)
    return national, dict(sorted(states.items()))

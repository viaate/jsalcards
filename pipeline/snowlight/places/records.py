"""City and ZIP search records, built from parsed source files.

The functions here are pure: they take parsed Census and NCES rows and return
validated records plus counts for the internal manifest. Nothing is looked up,
estimated or filled in; a value the sources do not give is ``null`` (a city's
population) or an empty list (a ZIP's districts).

Record shapes are documented in :mod:`snowlight.places`.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from snowlight.places.grf import UNASSIGNED_ZCTA, LeaZctaPart
from snowlight.sources.census.gazetteer import GazetteerPlace, GazetteerZcta
from snowlight.sources.census.lsad import base_name
from snowlight.sources.census.popest import PlaceEstimates

# The 48 contiguous states and the District of Columbia: Snowlight's scope.
CONTINENTAL_USPS = frozenset(
    {
        "AL", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "ID", "IL", "IN",
        "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE",
        "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    }
)  # fmt: skip

# NCES computes GRF ``LANDAREA`` as TIGER square meters / 2,589,988, the factor
# the Census Bureau uses for its own square-mile columns. The build verifies
# this on every run: every district's share of a ZCTA must come out <= 1.
SQUARE_METERS_PER_SQUARE_MILE = 2_589_988
SHARE_TOLERANCE = 1e-9
SHARE_SIGNIFICANT_DIGITS = 4
STATISTICAL_FUNCSTAT = "S"

Latitude = Annotated[float, Field(ge=-90.0, le=90.0, allow_inf_nan=False)]
Longitude = Annotated[float, Field(ge=-180.0, le=180.0, allow_inf_nan=False)]
Usps = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]


class CityRecord(BaseModel):
    """One Census place (incorporated place or CDP) in scope."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    geoid: Annotated[str, Field(pattern=r"^\d{7}$")]
    name: Annotated[str, Field(min_length=1)]
    kind: Annotated[str, Field(min_length=1)] | None
    state: Usps
    lat: Latitude
    lon: Longitude
    population: Annotated[int, Field(ge=0)] | None


class DistrictShare(BaseModel):
    """A school district's share of a ZCTA's land area."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    leaid: Annotated[str, Field(pattern=r"^\d{7}$")]
    name: Annotated[str, Field(min_length=1)]
    share: Annotated[float, Field(gt=0.0, le=1.0, allow_inf_nan=False)]


class ZipRecord(BaseModel):
    """One ZIP Code Tabulation Area in scope."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    zcta: Annotated[str, Field(pattern=r"^\d{5}$")]
    lat: Latitude
    lon: Longitude
    states: Annotated[list[Usps], Field(min_length=1)]
    districts: list[DistrictShare]


class SourceMismatchError(ValueError):
    """Raised when two source files that must agree do not."""


@dataclass(slots=True)
class CityCounts:
    """What happened to each Gazetteer place row."""

    source_rows: int = 0
    out_of_scope: int = 0
    records: int = 0
    names_trimmed: int = 0
    names_kept_whole: int = 0
    with_population: int = 0
    statistical_without_population: int = 0
    incorporated_without_estimate: int = 0
    estimate_name_mismatch: int = 0
    estimates_unmatched: int = 0
    kept_whole_codes: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, int | list[str]]:
        """Return the counts as a JSON-ready mapping."""
        return {
            "estimate_name_mismatch": self.estimate_name_mismatch,
            "estimates_unmatched": self.estimates_unmatched,
            "incorporated_without_estimate": self.incorporated_without_estimate,
            "kept_whole_codes": sorted(set(self.kept_whole_codes)),
            "names_kept_whole": self.names_kept_whole,
            "names_trimmed": self.names_trimmed,
            "out_of_scope": self.out_of_scope,
            "records": self.records,
            "source_rows": self.source_rows,
            "statistical_without_population": self.statistical_without_population,
            "with_population": self.with_population,
        }


@dataclass(slots=True)
class ZipCounts:
    """What happened to each Gazetteer ZCTA row and GRF part."""

    source_rows: int = 0
    out_of_scope: int = 0
    records: int = 0
    multi_state: int = 0
    with_districts: int = 0
    without_districts: int = 0
    district_links: int = 0
    parts_without_land: int = 0
    parts_outside_zctas: int = 0
    max_share_unrounded: float = 0.0

    def as_json(self) -> dict[str, int | float]:
        """Return the counts as a JSON-ready mapping."""
        return {
            "district_links": self.district_links,
            "max_share_unrounded": self.max_share_unrounded,
            "multi_state": self.multi_state,
            "out_of_scope": self.out_of_scope,
            "parts_outside_zctas": self.parts_outside_zctas,
            "parts_without_land": self.parts_without_land,
            "records": self.records,
            "source_rows": self.source_rows,
            "with_districts": self.with_districts,
            "without_districts": self.without_districts,
        }


def state_codes(places: Iterable[GazetteerPlace]) -> dict[str, str]:
    """Map state FIPS codes to USPS abbreviations as the places Gazetteer pairs them.

    Raises:
        SourceMismatchError: if a FIPS code or abbreviation is paired two ways.
    """
    fips_to_usps: dict[str, str] = {}
    usps_to_fips: dict[str, str] = {}
    for place in places:
        fips = place.geoid[:2]
        if fips_to_usps.setdefault(fips, place.usps) != place.usps:
            raise SourceMismatchError(f"state FIPS {fips} is paired with two USPS codes")
        if usps_to_fips.setdefault(place.usps, fips) != fips:
            raise SourceMismatchError(f"{place.usps} is paired with two state FIPS codes")
    return fips_to_usps


def _strip_any_suffix(full_name: str, suffixes: Iterable[str]) -> str:
    for suffix in sorted((s for s in suffixes if s), key=len, reverse=True):
        trimmed = base_name(full_name, suffix)
        if trimmed is not None:
            return trimmed
    return full_name


def build_cities(
    places: list[GazetteerPlace],
    suffixes: Mapping[str, str],
    estimates: PlaceEstimates,
) -> tuple[list[CityRecord], CityCounts]:
    """Build one record per in-scope Gazetteer place, sorted by GEOID.

    * ``name`` is the Gazetteer name with its LSAD suffix removed; when the code
      has no suffix in the official list, or the name does not end with it, the
      full name is kept.
    * ``population`` is the place's estimate from ``estimates`` when the place is
      not a statistical entity (CDP) and the estimate row has the same GEOID and
      the same name once each is stripped of its suffix (for the estimate's
      name, the longest place suffix it ends with, since legal status can change
      between vintages, e.g. "Shady Dale town" -> "Shady Dale city"); otherwise
      ``None``.
    """
    counts = CityCounts(source_rows=len(places))
    records: list[CityRecord] = []
    used_estimates: set[str] = set()
    place_suffixes = {suffixes[p.lsad] for p in places if suffixes.get(p.lsad)}
    for place in sorted(places, key=lambda p: p.geoid):
        if place.usps not in CONTINENTAL_USPS:
            counts.out_of_scope += 1
            continue
        suffix = suffixes.get(place.lsad)
        trimmed = base_name(place.name, suffix) if suffix else None
        if suffix and trimmed is not None:
            name, kind = trimmed, suffix
            counts.names_trimmed += 1
        else:
            name, kind = place.name, None
            counts.names_kept_whole += 1
            if suffix != "":
                counts.kept_whole_codes.append(place.lsad)
        population: int | None = None
        estimate = estimates.by_geoid.get(place.geoid)
        if place.funcstat == STATISTICAL_FUNCSTAT:
            counts.statistical_without_population += 1
        elif estimate is None:
            counts.incorporated_without_estimate += 1
        elif _strip_any_suffix(estimate.name, place_suffixes) != name:
            counts.estimate_name_mismatch += 1
        else:
            population = estimate.population
            used_estimates.add(place.geoid)
            counts.with_population += 1
        records.append(
            CityRecord(
                geoid=place.geoid,
                name=name,
                kind=kind,
                state=place.usps,
                lat=place.lat,
                lon=place.lon,
                population=population,
            )
        )
    scope_fips = {p.geoid[:2] for p in places if p.usps in CONTINENTAL_USPS}
    in_scope_estimates = {geoid for geoid in estimates.by_geoid if geoid[:2] in scope_fips}
    counts.estimates_unmatched = len(in_scope_estimates - used_estimates)
    counts.records = len(records)
    return records, counts


def round_share(share: float) -> float:
    """Round a share to :data:`SHARE_SIGNIFICANT_DIGITS` significant digits."""
    return float(f"{share:.{SHARE_SIGNIFICANT_DIGITS}g}")


def build_zips(
    zctas: list[GazetteerZcta],
    zcta_land_m2: Mapping[str, int],
    zcta_state_land: Mapping[str, Mapping[str, int]],
    fips_to_usps: Mapping[str, str],
    parts: list[LeaZctaPart],
) -> tuple[list[ZipRecord], ZipCounts]:
    """Build one record per in-scope ZCTA, sorted by ZCTA code.

    ``zctas`` supplies the codes and internal points (the latest Gazetteer).
    ``zcta_land_m2`` is each ZCTA's land area from the Gazetteer of the same
    TIGER year as ``parts``, so a district's share is its GRF land area over
    the ZCTA land area measured on the same map. ``zcta_state_land`` (from the
    ZCTA-county relationship file) decides which states a ZCTA lies in.

    Raises:
        SourceMismatchError: if the files disagree on which ZCTAs exist, a
            share exceeds 1 (the area vintages do not match), or a ZCTA spans
            the continental US and somewhere outside it.
    """
    codes = {z.geoid for z in zctas}
    for label, other in (("ZCTA land areas", zcta_land_m2), ("ZCTA states", zcta_state_land)):
        if set(other) != codes:
            diff = sorted(set(other) ^ codes)[:5]
            raise SourceMismatchError(f"{label} cover different ZCTAs than the Gazetteer: {diff}")
    counts = ZipCounts(source_rows=len(zctas))
    by_zcta: dict[str, list[LeaZctaPart]] = defaultdict(list)
    for part in parts:
        if part.zcta == UNASSIGNED_ZCTA:
            counts.parts_outside_zctas += 1
        elif part.zcta not in codes:
            raise SourceMismatchError(f"GRF lists ZCTA {part.zcta}, which the Gazetteer lacks")
        elif part.land_sqmi == 0:
            counts.parts_without_land += 1
        else:
            by_zcta[part.zcta].append(part)
    records: list[ZipRecord] = []
    for zcta in sorted(zctas, key=lambda z: z.geoid):
        states = _states_of(zcta.geoid, zcta_state_land[zcta.geoid], fips_to_usps)
        if states is None:
            counts.out_of_scope += 1
            continue
        land_m2 = zcta_land_m2[zcta.geoid]
        if land_m2 <= 0:
            raise SourceMismatchError(f"ZCTA {zcta.geoid} has no land area")
        shares: list[tuple[float, LeaZctaPart]] = []
        for part in by_zcta.get(zcta.geoid, []):
            share = part.land_sqmi * SQUARE_METERS_PER_SQUARE_MILE / land_m2
            if not math.isfinite(share) or share > 1 + SHARE_TOLERANCE:
                raise SourceMismatchError(
                    f"district {part.leaid} covers {share:.6f} of ZCTA {zcta.geoid}: "
                    "the GRF and Gazetteer land areas are not from the same TIGER year"
                )
            counts.max_share_unrounded = max(counts.max_share_unrounded, share)
            shares.append((share, part))
        shares.sort(key=lambda item: (-item[0], item[1].leaid))
        districts = [
            DistrictShare(leaid=p.leaid, name=p.name, share=round_share(s)) for s, p in shares
        ]
        counts.multi_state += len(states) > 1
        counts.with_districts += bool(districts)
        counts.without_districts += not districts
        counts.district_links += len(districts)
        records.append(
            ZipRecord(
                zcta=zcta.geoid,
                lat=zcta.lat,
                lon=zcta.lon,
                states=states,
                districts=districts,
            )
        )
    counts.records = len(records)
    return records, counts


def _states_of(
    zcta: str, land_by_fips: Mapping[str, int], fips_to_usps: Mapping[str, str]
) -> list[str] | None:
    """Return the ZCTA's states, most land first, or ``None`` if out of scope."""
    with_land = sorted(
        ((land, fips) for fips, land in land_by_fips.items() if land > 0),
        key=lambda item: (-item[0], item[1]),
    )
    usps = [fips_to_usps.get(fips) for _land, fips in with_land]
    inside = [code for code in usps if code in CONTINENTAL_USPS]
    if not inside:
        return None
    if len(inside) != len(usps):
        raise SourceMismatchError(f"ZCTA {zcta} spans the continental US and beyond: {usps}")
    return inside

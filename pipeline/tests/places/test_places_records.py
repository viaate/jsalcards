"""Tests for building city and ZIP records from real source slices."""

import io
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from snowlight.places.grf import LeaZctaPart, parse_lea_zcta
from snowlight.places.records import (
    CONTINENTAL_USPS,
    SQUARE_METERS_PER_SQUARE_MILE,
    CityRecord,
    DistrictShare,
    SourceMismatchError,
    ZipRecord,
    build_cities,
    build_zips,
    round_share,
    state_codes,
)
from snowlight.places.xlsx import read_table
from snowlight.sources.census import gazetteer, popest
from snowlight.sources.census.gazetteer import GazetteerPlace, GazetteerZcta
from snowlight.sources.census.lsad import name_suffixes, parse_lsad_codes
from snowlight.sources.census.zcta_county import zcta_state_land

if TYPE_CHECKING:
    from conftest import FixtureKit


@pytest.fixture
def places(kit: "FixtureKit") -> list[GazetteerPlace]:
    return gazetteer.parse_places(kit.text_of("2026_Gaz_place_national.txt"), "places")


@pytest.fixture
def estimates(kit: "FixtureKit") -> popest.PlaceEstimates:
    return popest.parse_place_estimates(kit.bytes_of("sub-est2025.csv"), 2025, "pep")


@pytest.fixture
def suffixes(kit: "FixtureKit") -> dict[str, str]:
    return name_suffixes(parse_lsad_codes(kit.text_of("legal-status-codes.table.html")))


@pytest.fixture
def zctas(kit: "FixtureKit") -> list[GazetteerZcta]:
    return gazetteer.parse_zctas(kit.text_of("2026_Gaz_zcta_national.txt"), "z26")


@pytest.fixture
def land_2025(kit: "FixtureKit") -> dict[str, int]:
    rows = gazetteer.parse_zctas(kit.text_of("2025_Gaz_zcta_national.txt"), "z25")
    return {z.geoid: z.aland for z in rows}


@pytest.fixture
def states(kit: "FixtureKit") -> dict[str, dict[str, int]]:
    return zcta_state_land(kit.text_of("tab20_zcta520_county20_natl.txt"), "rel")


@pytest.fixture
def parts(kit: "FixtureKit") -> list[LeaZctaPart]:
    header, rows = read_table(io.BytesIO(kit.xlsx_of(kit.grf_rows())), "grf")
    return parse_lea_zcta(header, rows, "grf")


def test_scope_is_the_48_contiguous_states_and_dc() -> None:
    assert len(CONTINENTAL_USPS) == 49
    assert "DC" in CONTINENTAL_USPS
    assert not {"AK", "HI", "PR"} & CONTINENTAL_USPS


def test_city_records(
    places: list[GazetteerPlace], suffixes: dict[str, str], estimates: popest.PlaceEstimates
) -> None:
    records, counts = build_cities(places, suffixes, estimates)
    by_geoid = {r.geoid: r for r in records}
    assert by_geoid["0100124"] == CityRecord(
        geoid="0100124",
        name="Abbeville",
        kind="city",
        state="AL",
        lat=31.565164,
        lon=-85.259165,
        population=2378,
    )
    # A CDP has no population estimate, even when an incorporated place with its
    # code had one (Vicco, KY disincorporated after the 2025 vintage).
    assert (by_geoid["0100100"].kind, by_geoid["0100100"].population) == ("CDP", None)
    assert by_geoid["2179590"].population is None
    # Names whose LSAD code has no suffix are kept whole.
    nashville = by_geoid["4752006"]
    assert nashville.name == "Nashville-Davidson metropolitan government (balance)"
    assert (nashville.kind, nashville.population) == (None, 721074)
    # A legal-status change between vintages ("town" -> "city") still matches.
    assert (by_geoid["1369784"].name, by_geoid["1369784"].population) == ("Shady Dale", 294)
    assert by_geoid["0812030"].population == 0
    assert by_geoid["0464210"].population is None  # incorporated after the estimates
    assert by_geoid["0902690"].kind == "borough"
    assert by_geoid["1326156"].name == "Echols County"
    assert by_geoid["5466988"].kind == "corporation"
    assert by_geoid["1150000"].name == "Washington"
    assert [r.geoid for r in records] == sorted(by_geoid)
    assert not {"AK", "HI", "PR"} & {r.state for r in records}
    assert counts.as_json() == {
        "estimate_name_mismatch": 0,
        "estimates_unmatched": 2,  # Vicco (now a CDP) and Poplar Hills (dissolved)
        "incorporated_without_estimate": 2,  # San Tan Valley and Baker (inactive)
        "kept_whole_codes": [],
        "names_kept_whole": 3,
        "names_trimmed": 20,
        "out_of_scope": 5,
        "records": 23,
        "source_rows": 28,
        "statistical_without_population": 2,
        "with_population": 19,
    }


def test_city_population_needs_matching_names(
    places: list[GazetteerPlace], suffixes: dict[str, str], estimates: popest.PlaceEstimates
) -> None:
    renamed = dict(estimates.by_geoid)
    renamed["0100124"] = replace(renamed["0100124"], name="Abbeville town (old)")
    changed = replace(estimates, by_geoid=renamed)
    records, counts = build_cities(places, suffixes, changed)
    assert next(r for r in records if r.geoid == "0100124").population is None
    assert counts.estimate_name_mismatch == 1


def test_city_names_are_kept_whole_for_unknown_codes_or_missing_suffixes(
    places: list[GazetteerPlace], estimates: popest.PlaceEstimates
) -> None:
    records, counts = build_cities(places, {"25": "town"}, estimates)
    abbeville = next(r for r in records if r.geoid == "0100124")
    assert (abbeville.name, abbeville.kind) == ("Abbeville city", None)
    assert counts.names_trimmed == 0
    assert "25" in counts.kept_whole_codes
    assert "57" in counts.kept_whole_codes


def test_state_codes_pairs_fips_and_usps(places: list[GazetteerPlace]) -> None:
    codes = state_codes(places)
    assert codes["01"] == "AL"
    assert codes["11"] == "DC"
    assert codes["72"] == "PR"
    with pytest.raises(SourceMismatchError, match="two USPS"):
        state_codes([*places, replace(places[0], usps="ZZ")])
    with pytest.raises(SourceMismatchError, match="two state FIPS"):
        state_codes([*places, replace(places[0], geoid="9900100")])


def test_zip_records(
    zctas: list[GazetteerZcta],
    land_2025: dict[str, int],
    states: dict[str, dict[str, int]],
    places: list[GazetteerPlace],
    parts: list[LeaZctaPart],
) -> None:
    records, counts = build_zips(zctas, land_2025, states, state_codes(places), parts)
    by_zcta = {r.zcta: r for r in records}
    assert sorted(by_zcta) == [
        "01002",
        "02139",
        "02861",
        "05847",
        "36542",
        "55111",
        "60601",
        "85351",
    ]
    assert by_zcta["02139"] == ZipRecord(
        zcta="02139",
        lat=42.362391,
        lon=-71.102336,
        states=["MA"],
        districts=[DistrictShare(leaid="2503270", name="Cambridge School District", share=1.0)],
    )
    amherst = by_zcta["01002"].districts
    assert [(d.leaid, d.share) for d in amherst] == [
        ("2501920", 1.0),
        ("2501890", 0.5036),
        ("2509390", 0.4288),
        ("2510800", 0.06759),
        ("2505580", 1.386e-05),
    ]
    for district in amherst:
        part = next(p for p in parts if p.leaid == district.leaid and p.zcta == "01002")
        exact = part.land_sqmi * SQUARE_METERS_PER_SQUARE_MILE / land_2025["01002"]
        assert district.share == round_share(exact)
    assert by_zcta["02861"].states == ["RI", "MA"]
    assert by_zcta["55111"].districts == []
    # Orange Beach's piece of 36542 is water only, so it does not serve the ZCTA.
    assert [d.leaid for d in by_zcta["36542"].districts] == ["0100202", "0100270"]
    assert counts.as_json() == {
        "district_links": 20,
        "max_share_unrounded": counts.max_share_unrounded,
        "multi_state": 1,
        "out_of_scope": 3,
        "parts_outside_zctas": 1,
        "parts_without_land": 1,
        "records": 8,
        "source_rows": 11,
        "with_districts": 7,
        "without_districts": 1,
    }
    assert 1.0 <= counts.max_share_unrounded <= 1.0 + 1e-9


def test_zip_records_refuse_disagreeing_sources(
    zctas: list[GazetteerZcta],
    land_2025: dict[str, int],
    states: dict[str, dict[str, int]],
    places: list[GazetteerPlace],
    parts: list[LeaZctaPart],
) -> None:
    fips = state_codes(places)
    with pytest.raises(SourceMismatchError, match="ZCTA land areas cover different"):
        build_zips(zctas, {**land_2025, "99999": 1}, states, fips, parts)
    with pytest.raises(SourceMismatchError, match="ZCTA states cover different"):
        build_zips(zctas, land_2025, {k: v for k, v in states.items() if k != "02139"}, fips, parts)
    with pytest.raises(SourceMismatchError, match="not from the same TIGER year"):
        build_zips(zctas, {**land_2025, "02139": land_2025["02139"] // 2}, states, fips, parts)
    with pytest.raises(SourceMismatchError, match="has no land area"):
        build_zips(zctas, {**land_2025, "02139": 0}, states, fips, parts)
    stray = replace(parts[1], zcta="99999")
    with pytest.raises(SourceMismatchError, match="Gazetteer lacks"):
        build_zips(zctas, land_2025, states, fips, [*parts, stray])
    straddling = {**states, "99501": {"02": 5, "25": 5}}
    with pytest.raises(SourceMismatchError, match="continental US and beyond"):
        build_zips(zctas, land_2025, straddling, fips, parts)


@pytest.mark.parametrize(
    ("share", "rounded"),
    [(1.0000000000000022, 1.0), (0.50364999, 0.5036), (1.3861e-05, 1.386e-05), (0.1, 0.1)],
)
def test_round_share(share: float, rounded: float) -> None:
    assert round_share(share) == rounded


def test_models_refuse_invalid_values() -> None:
    with pytest.raises(ValidationError):
        DistrictShare(leaid="2503270", name="x", share=0.0)
    with pytest.raises(ValidationError):
        CityRecord(
            geoid="0100124",
            name="Abbeville",
            kind="city",
            state="al",
            lat=31.5,
            lon=-85.2,
            population=None,
        )
    with pytest.raises(ValidationError):
        ZipRecord(zcta="02139", lat=42.3, lon=-71.1, states=[], districts=[])

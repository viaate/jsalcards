"""Zone-county correlation releases, the catalog that reads them, and the county list.

Correlation lines come from ``fixtures/bp*.dbx`` and county records from
``fixtures/c_16ap26.zip``, real slices of the NWS files.
"""

from datetime import date
from typing import TYPE_CHECKING

import pytest
import shapely

from snowlight.sources.nws.boundaries import BoundaryRelease
from snowlight.weights import zones

if TYPE_CHECKING:
    from weights.conftest import Kit


def _release(kit: "Kit", name: str) -> zones.ZoneRelease:
    text = kit.bytes(f"{name}.dbx").decode("latin-1")
    return zones.ZoneRelease.from_records(name, zones.read_release(text, name))


def test_release_names_and_urls() -> None:
    assert zones.release_date("bp02ap19") == date(2019, 4, 2)
    assert zones.release_date("bp16ap26") == date(2026, 4, 16)
    assert zones.release_date("bp10oc19") == date(2019, 10, 10)
    assert zones.release_url("bp18mr25") == (
        "https://www.weather.gov/source/gis/Shapefiles/County/bp18mr25.dbx"
    )
    for bad in ("bp31fe19", "bp01xx19", "z_16ap26", "bp1ap19"):
        with pytest.raises(zones.ZoneCountyError):
            zones.release_date(bad)
    dates = [zones.release_date(name) for name in zones.RELEASES]
    assert dates == sorted(dates)
    assert zones.RELEASES[0] == "bp02ap19"


def test_read_release(kit: "Kit") -> None:
    release = _release(kit, "bp16ap26")
    assert release.valid_from == date(2026, 4, 16)
    assert release.counties["RIZ001"] == frozenset({"44007"})
    assert release.counties["RIZ008"] == frozenset({"44009"})
    assert release.names["RIZ008"] == "Block Island"
    assert release.counties["MTZ043"] >= {"30063"}
    assert release.county_names["FLZ014"] == frozenset({"Gulf"})
    assert release.records == len(kit.bytes("bp16ap26.dbx").splitlines())


def test_state_zone_typo_is_kept_under_state_and_zone(kit: "Kit") -> None:
    release = _release(kit, "bp10oc19")
    assert release.state_zone_mismatches == ("WYZ198", "WYZ199")
    assert release.counties["WYZ198"] == frozenset({"56033"})
    assert release.names["WYZ198"] == "Northeast Big Horn Mountains"


def test_read_release_rejects_malformed_lines() -> None:
    """Synthetic lines built from the real RI001 line."""
    good = "RI|001|BOX|Northwest Providence|RI001|Providence|44007|E||41.8908|-71.6203"
    assert zones.read_release(good, "x")[0].ugc == "RIZ001"
    for bad, message in (
        ("RI|001|BOX", "fields"),
        (good.replace("|001|", "|01|"), "zone"),
        (good.replace("44007", "4400"), "FIPS"),
    ):
        with pytest.raises(zones.ZoneCountyError, match=message):
            zones.read_release(bad, "x")
    with pytest.raises(zones.ZoneCountyError, match="no records"):
        zones.read_release("\n", "x")


def test_catalog_resolves_by_date(kit: "Kit") -> None:
    releases = [_release(kit, name) for name in ("bp02ap19", "bp05mr24", "bp16ap26")]
    catalog = zones.ZoneCountyCatalog(releases, {"RI": "44", "WA": "53", "FL": "12"})
    assert catalog.counties("RIZ002", date(2025, 1, 20)) == frozenset({"44007"})
    assert catalog.counties("RIZ002", date(2016, 1, 20)) == frozenset({"44007"})
    # WAZ567 left the zone list before bp16ap26: read in the nearest release that has it.
    assert catalog.counties("WAZ567", date(2026, 5, 1)) == releases[1].counties["WAZ567"]
    assert catalog.counties("IDZ019", date(2016, 1, 20)) == frozenset()
    assert catalog.counties("FLC045", date(2024, 9, 12)) == frozenset({"12045"})
    assert catalog.counties("NYC029", date(2024, 9, 12)) == frozenset()
    stats = catalog.stats
    assert stats.by_resolution == {
        "in_effect": 1,
        "before_first": 1,
        "nearest": 1,
        "unmapped": 2,
        "county": 1,
    }
    assert stats.nearest == {("WAZ567", "bp05mr24"): 1}
    assert stats.unmapped == {"IDZ019": 1, "NYC029": 1}
    assert stats.before_first == {"RIZ002": 1}
    with pytest.raises(zones.ZoneCountyError):
        catalog.counties("RI001", date(2025, 1, 20))
    assert catalog.release_in_effect(date(2019, 4, 1)) is None


def test_catalog_exclusions(kit: "Kit") -> None:
    catalog = zones.ZoneCountyCatalog([_release(kit, "bp02ap19")], {"MT": "30"})
    catalog.exclude("MTZ043", date(2018, 7, 2), date(2019, 4, 2))
    assert catalog.excluded("MTZ043", date(2018, 12, 12))
    assert catalog.counties("MTZ043", date(2018, 12, 12)) == frozenset()
    assert catalog.counties("MTZ043", date(2019, 4, 2)) >= {"30063"}
    assert catalog.stats.left_out == {"MTZ043": 1}
    with pytest.raises(zones.ZoneCountyError):
        zones.ZoneCountyCatalog([], {})


def test_load_releases(kit: "Kit") -> None:
    releases = zones.load_releases(kit.cache(), kit.releases)
    assert [release.name for release in releases] == list(kit.releases)
    assert all(release.file is not None for release in releases)


def test_read_counties(kit: "Kit") -> None:
    listing = zones.read_counties(kit.path("c_16ap26.zip"))
    assert listing.records == 12
    assert sorted(listing.counties) == [
        "09003",
        "12037",
        "12045",
        "16013",
        "30063",
        "44001",
        "44003",
        "44005",
        "44007",
        "44009",
    ]
    gulf = listing.counties["12045"]
    assert gulf.time_zones == ("America/Chicago", "America/New_York")
    assert gulf.state == "FL"
    assert gulf.name == "Gulf"
    assert listing.counties["30063"].time_zones == ("America/Denver",)
    assert listing.state_fips["RI"] == "44"
    assert [county.fips for county in listing.in_state("RI")][:2] == ["44001", "44003"]
    point = shapely.Point(-71.4128, 41.824)  # Providence city hall
    assert shapely.contains(listing.counties["44007"].geometry, point)
    only_ri = zones.read_counties(kit.path("c_16ap26.zip"), states={"RI"})
    assert len(only_ri.counties) == 5


def test_load_counties_checks_md5_and_count(kit: "Kit") -> None:
    release = kit.county_release()
    listing = zones.load_counties(kit.cache(), release)
    assert listing.file is not None
    wrong = BoundaryRelease(
        kind="county", valid_from=release.valid_from, url=release.url, md5=release.md5, records=3
    )
    with pytest.raises(zones.ZoneCountyError, match="records"):
        zones.load_counties(kit.cache(), wrong)


def test_unknown_time_zone_code_is_an_error() -> None:
    with pytest.raises(zones.ZoneCountyError, match="time zone"):
        zones._iana(["h"], "15001")  # Hawaii's code: outside the contiguous states


def test_county_name_conflicts() -> None:
    """Real lines of bp02ap19.dbx: ORZ016 names Hood River County with Jefferson's FIPS code."""
    text = "\n".join(
        [
            "OR|016|PDT|Central Columbia River Gorge|OR016|Hood River|41031|P|cc|45.6845|-121.6091",
            "PA|105|PHI|Bucks|PA105|Upper Bucks|42017|E|se|40.3370|-75.1067",
            "RI|001|BOX|Northwest Providence|RI001|Providence|44007|E||41.8908|-71.6203",
        ]
    )
    release = zones.ZoneRelease.from_records("bp02ap19", zones.read_release(text, "bp02ap19"))
    names = {"41031": "Jefferson", "42017": "Bucks", "44007": "Providence"}
    assert zones.county_name_conflicts(release, names) == [
        ("ORZ016", "41031", "Hood River", "Jefferson")
    ]

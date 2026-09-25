"""Tests for the NWS zone and county boundary releases."""

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from shapely.geometry import Point

from snowlight.sources.nws.boundaries import (
    PAGES,
    BoundaryCatalog,
    BoundaryError,
    parse_releases,
    read_boundary_set,
    ugc_kind,
)
from snowlight.sources.nws.http import ChecksumMismatchError

if TYPE_CHECKING:
    from weather.conftest import Kit

FIXTURES = Path(__file__).parent / "fixtures"
ZONE_PAGE = (FIXTURES / "PublicZones.table.html").read_text()
COUNTY_PAGE = (FIXTURES / "Counties.table.html").read_text()


def test_parses_the_real_release_tables() -> None:
    zones = parse_releases(ZONE_PAGE, "zone", PAGES["zone"])
    assert [(r.valid_from, r.url, r.md5, r.records) for r in zones] == [
        (
            date(2025, 3, 18),
            "https://www.weather.gov/source/gis/Shapefiles/WSOM/z_18mr25.zip",
            "388062c3036e4518d07c9fb09d68ff6f",
            4114,
        ),
        (
            date(2026, 4, 16),
            "https://www.weather.gov/source/gis/Shapefiles/WSOM/z_16ap26.zip",
            "004dc6501dc3d50e7b36652cb9d02bd3",
            4157,
        ),
    ]
    counties = parse_releases(COUNTY_PAGE, "county", PAGES["county"])
    assert [(r.valid_from, r.md5, r.records) for r in counties] == [
        (date(2025, 3, 18), "37feacd979ecdad99550017130023e06", 3359),
        (date(2026, 4, 16), "734d75df3791bdc0cbb29fd6ed75a387", 3352),
    ]
    assert counties[0].as_json()["valid_from"] == "2025-03-18"


def test_incomplete_or_missing_tables_are_errors() -> None:
    with pytest.raises(BoundaryError, match="lacks a valid date or MD5"):
        parse_releases(ZONE_PAGE.replace("388062c3036e4518d07c9fb09d68ff6f", "n/a"), "zone", "p")
    with pytest.raises(BoundaryError, match="no zone release"):
        parse_releases(COUNTY_PAGE, "zone", "p")
    with pytest.raises(BoundaryError, match="share a valid date"):
        parse_releases(ZONE_PAGE.replace("16 April 2026", "18 March 2025"), "zone", "p")
    two_links = ZONE_PAGE.replace(
        ">z_18mr25.zip</a>",
        '>z_18mr25.zip</a><a href="/source/gis/Shapefiles/WSOM/z_01ja20.zip">x</a>',
    )
    with pytest.raises(BoundaryError, match="several release files"):
        parse_releases(two_links, "zone", "p")


def test_ugc_kind() -> None:
    assert ugc_kind("NYZ072") == "zone"
    assert ugc_kind("NMC009") == "county"
    with pytest.raises(ValueError, match="not a UGC"):
        ugc_kind("NY072")


def test_reads_the_real_zone_and_county_slices(kit: "Kit") -> None:
    catalog = kit.catalog()
    zones = catalog.boundaries_for("zone", date(2026, 9, 25))
    counties = catalog.boundaries_for("county", date(2026, 9, 25))
    assert zones is not None
    assert counties is not None
    assert zones.release.url.endswith("/z_16ap26.zip")
    assert {"NCZ204", "NYZ074", "DCZ001", "CTZ002", "FLZ014"} <= set(zones.areas)
    assert zones.county_fips == {}
    assert zones.time_zones["AZZ010"] == ("M",)
    assert zones.time_zones["AZZ014"] == ("Mm",)
    assert counties.county_fips["NMC009"] == "35009"
    assert counties.county_fips["CTC003"] == "09003"
    assert counties.time_zones["FLC045"] == ("CE",)
    # Gulf County, Florida is stored as two records; both are in its geometry.
    assert counties.areas["FLC045"].contains(Point(-85.25, 29.9))
    assert counties.areas["FLC045"].contains(Point(-85.2, 30.15))


def test_record_counts_must_match_the_page(kit: "Kit") -> None:
    catalog = kit.catalog()
    release = catalog.releases("zone")[1]
    loaded = catalog.load(release)
    with pytest.raises(BoundaryError, match="the page lists 4157"):
        read_boundary_set(replace(release, records=4157), loaded.file)
    not_a_shapefile = replace(loaded.file, path=FIXTURES / "alert-types.json")
    with pytest.raises(BoundaryError, match="not a zip"):
        read_boundary_set(release, not_a_shapefile)


def test_catalog_picks_the_release_in_effect(kit: "Kit") -> None:
    catalog = kit.catalog()
    assert catalog.release_for("zone", date(2025, 1, 21)) is None
    assert catalog.boundaries_for("zone", date(2025, 1, 21)) is None
    before = catalog.release_for("zone", date(2026, 4, 15))
    after = catalog.release_for("zone", date(2026, 4, 16))
    assert before is not None
    assert after is not None
    assert (before.valid_from, after.valid_from) == (date(2025, 3, 18), date(2026, 4, 16))
    assert catalog.lookup("LAZ077", date(2025, 1, 21)) == (None, None)
    geometry, boundaries = catalog.lookup("LAZ077", date(2025, 6, 1))
    assert geometry is not None
    assert boundaries is not None
    assert boundaries.release.url.endswith("z_18mr25.zip")
    missing, current = catalog.lookup("LAZ077", date(2026, 9, 25))
    assert missing is None
    assert current is not None
    provenance = catalog.provenance()
    assert provenance["pages"] == {}
    files = provenance["files"]
    assert isinstance(files, list)
    assert len(files) == 2


def test_catalog_reads_the_release_lists_from_the_pages(kit: "Kit") -> None:
    catalog = BoundaryCatalog(kit.cache(), kit.cache_dir)
    assert [r.valid_from for r in catalog.releases("county")] == [
        date(2025, 3, 18),
        date(2026, 4, 16),
    ]
    catalog.releases("county")
    assert kit.server.hits[PAGES["county"]] == 1
    page = kit.cache_dir / "www.weather.gov" / "gis" / "Counties.html"
    assert page.is_file()
    pages = catalog.provenance()["pages"]
    assert isinstance(pages, dict)
    assert set(pages) == {"county"}
    # The fixture slices are not the listed files, so their MD5 sums do not match.
    with pytest.raises(ChecksumMismatchError):
        catalog.load(catalog.releases("county")[0])
    with pytest.raises(BoundaryError, match="unexpected URL"):
        catalog.load(replace(catalog.releases("county")[0], url="https:///../x.zip"))

"""IEM's archived zone outlines and the checks made with them.

``fixtures/ugcs-2019-01-15.geojson``, ``fixtures/ugcs-2020-01-15.geojson`` and
``fixtures/ugcs-2022-01-15.geojson`` hold real features of IEM's ``ugcs.geojson``
answers, cut to the zones of the school-year slices (see
``fixtures/provenance.json``). Two tests change one thing on purpose, and say so:
a correlation release with one zone's county swapped, and an outline book that
lacks one outline.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from snowlight.weights import archive, count, outlines, zones

if TYPE_CHECKING:
    from weights.conftest import Kit


def _book(kit: "Kit") -> outlines.OutlineBook:
    return outlines.OutlineBook(kit.cache(), zones.read_counties(kit.path("c_16ap26.zip")))


class _WithoutOutline(outlines.OutlineBook):
    """Synthetic: the real outlines, less one zone's in one school year."""

    missing: tuple[int, str] = (0, "")

    def outline(self, year: int, ugc: str) -> outlines.Outline | None:
        return None if (year, ugc) == self.missing else super().outline(year, ugc)

    def shares(self, year: int, ugc: str) -> dict[str, float] | None:
        return None if (year, ugc) == self.missing else super().shares(year, ugc)


def _without(kit: "Kit", year: int, ugc: str) -> outlines.OutlineBook:
    book = _WithoutOutline(kit.cache(), zones.read_counties(kit.path("c_16ap26.zip")))
    book.missing = (year, ugc)
    return book


def _setup(
    kit: "Kit", swap: tuple[str, str] | None = None
) -> tuple[list[archive.SchoolYearFile], zones.ZoneCountyCatalog, zones.CountyList, count.Tally]:
    """Read the 2018-19 slice; ``swap`` = (zone, county) lists the zone in that county only.

    MTZ043 is left out for the year, as the build's name check leaves it out.
    """
    releases = zones.load_releases(kit.cache(), kit.releases)
    counties = zones.read_counties(kit.path("c_16ap26.zip"))
    if swap is not None:
        first = releases[0]
        ugc, fips = swap
        releases[0] = replace(first, counties={**first.counties, ugc: frozenset({fips})})
    catalog = zones.ZoneCountyCatalog(releases, counties.state_fips)
    catalog.exclude("MTZ043", archive.request_window(2018)[0], releases[0].valid_from)
    files = archive.load_years(kit.cache(), [2018])
    tally = count.count_years(files, catalog, counties)
    return files, catalog, counties, tally


def test_urls_and_times() -> None:
    assert outlines.outline_valid(2018) == datetime(2019, 1, 15, 12, tzinfo=UTC)
    assert outlines.outlines_url(outlines.outline_valid(2018)) == (
        "https://mesonet.agron.iastate.edu/api/1/nws/ugcs.geojson?valid=2019-01-15T12:00Z"
    )


def test_read_outlines(kit: "Kit") -> None:
    found = outlines.read_outlines(kit.text("ugcs-2019-01-15.geojson"))
    riz001, idz075 = found.get("RIZ001"), found.get("IDZ075")
    assert riz001 is not None
    assert idz075 is not None
    assert riz001.name == "Northwest Providence"
    assert idz075.name == "Wood River Foothills"
    assert found.get("RIZ001") is riz001  # built once
    assert "RIZ008" in found
    assert "RIC007" not in found
    assert found.get("NYZ072") is None
    assert len(found) >= 10
    with pytest.raises(outlines.OutlineError, match="no feature list"):
        outlines.read_outlines('{"type": "FeatureCollection"}')
    with pytest.raises(outlines.OutlineError, match="no ugc"):
        outlines.read_outlines('{"features": [{"properties": {}}]}')
    county_only = '{"features": [{"properties": {"ugc": "RIC007"}, "geometry": null}]}'
    assert len(outlines.read_outlines(county_only)) == 0


def test_shares_and_agreement(kit: "Kit") -> None:
    book = _book(kit)
    shares = book.shares(2018, "RIZ001")
    assert shares is not None
    assert max(shares, key=lambda fips: shares[fips]) == "44007"
    assert shares["44007"] > 0.9
    assert outlines.agrees({"44007"}, shares)
    assert not outlines.agrees({"44003"}, shares)  # listed county not under the outline
    assert not outlines.agrees(set(), shares)  # Providence holds most of it, unlisted
    assert book.shares(2018, "NYZ072") is None
    assert set(book.files) == {2018}
    blaine = book.shares(2018, "IDZ075")
    assert blaine is not None
    assert outlines.agrees({"16013"}, blaine)


def test_check_outlines_reports_left_out_rows(kit: "Kit") -> None:
    releases = zones.load_releases(kit.cache(), kit.releases)
    counties = zones.read_counties(kit.path("c_16ap26.zip"))
    catalog = zones.ZoneCountyCatalog(releases, counties.state_fips)
    files = archive.load_years(kit.cache(), [2018])
    catalog.exclude("MTZ043", archive.request_window(2018)[0], releases[0].valid_from)
    tally = count.count_years(files, catalog, counties)
    report = outlines.check_outlines(_book(kit), files, catalog, counties, tally)
    # Rhode Island's zones were read in the April 2019 release before it took effect;
    # their outlines agree with it.
    assert report.compared[2018] == report.agreed[2018] >= 8
    assert report.disagreements == []
    renamed, partial = report.left_out
    # After the April 2019 release took effect, MTZ043's rows are read in it, which
    # lists three counties the twelve-county slice lacks: those rows reach Missoula
    # only, and the rest of the outline lies outside the slice, so nothing more is marked.
    assert partial["ugc"] == "MTZ043"
    assert partial["why"] == "county_not_in_county_list"
    assert partial["counties_reached"] == ["30063"]
    assert partial["counties_not_in_county_list"] == ["30039", "30047", "30077"]
    assert partial["weighted_days_it_would_add"] == {}
    assert tally.stats.unknown_counties == {"30039": 2, "30047": 2, "30077": 2}
    left = renamed
    assert left["ugc"] == "MTZ043"
    assert left["why"] == "left_out_renamed"
    added = left["weighted_days_it_would_add"]
    assert isinstance(added, dict)
    assert set(added) == {"30063"}
    assert report.gains["30063"]["2018-19"] == pytest.approx(float(str(added["30063"])), abs=0.01)
    record = report.as_json()
    assert record["zones_compared"] == {"2018-19": report.compared[2018]}
    assert record["zones_without_outline"] == []
    # Missoula County held 63% of MTZ043's outline: its 2018-19 count misses those rows,
    # so that school year is incomplete there and is left out of its average.
    assert report.incomplete == {"30063": {2018: {"MTZ043"}}}
    assert report.left_out_years() == {"30063": frozenset({2018})}
    assert record["standing_school_year"] == "2019-20"
    assert record["school_years_left_out"] == {"30063": {"2018-19": ["MTZ043"]}}
    assert record["counties_with_school_years_left_out"] == 1
    assert record["county_school_years_left_out"] == 1
    assert record["below_major_share_kept"] == {"county_school_years": 0, "largest": []}


def test_disagreeing_counties(kit: "Kit") -> None:
    shares = _book(kit).shares(2018, "RIZ001")
    assert shares is not None
    assert outlines.disagreeing({"44007"}, shares) == frozenset()
    # Kent is listed but holds none of it; Providence holds most of it, unlisted.
    assert outlines.disagreeing({"44003"}, shares) == {"44003", "44007"}
    assert outlines.disagreeing(set(), shares) == {"44007"}
    catalog = _setup(kit)[1]
    assert outlines.standing_year(catalog) == 2019  # bp02ap19 took effect in 2018-19


def test_standing_disagreement_leaves_nothing_out(kit: "Kit") -> None:
    # Synthetic: the real first release with RIZ001 listed in Kent County (44003) only.
    files, catalog, counties, tally = _setup(kit, ("RIZ001", "44003"))
    report = outlines.check_outlines(_book(kit), files, catalog, counties, tally)
    (item,) = report.disagreements
    assert item["ugc"] == "RIZ001"
    assert item["listed"] == ["44003"]
    assert item["disagreeing_counties"] == ["44003", "44007"]
    # RIZ001's real outline in 2019-20 is the one of 2018-19: the release reads the zone
    # this way in every school year, so nothing is left out.
    assert item["standing_outline_shares"] == item["outline_shares"]
    assert item["same_in_standing_school_year"] is True
    assert item["counties_left_out_for_the_year"] == []
    assert report.incomplete == {"30063": {2018: {"MTZ043"}}}
    assert set(report.files) == {2018, 2019}


def test_redrawn_zone_leaves_its_counties_out(kit: "Kit") -> None:
    # Synthetic twice over: RIZ001 listed in Kent only, and no 2019-20 outline of it, so
    # the disagreement cannot be shown to stand.
    files, catalog, counties, tally = _setup(kit, ("RIZ001", "44003"))
    report = outlines.check_outlines(_without(kit, 2019, "RIZ001"), files, catalog, counties, tally)
    (item,) = report.disagreements
    assert item["standing_outline_shares"] is None
    assert item["same_in_standing_school_year"] is False
    assert item["counties_left_out_for_the_year"] == ["44003", "44007"]
    assert report.incomplete["44003"] == {2018: {"RIZ001"}}
    assert report.incomplete["44007"] == {2018: {"RIZ001"}}


def test_county_code_missing_from_the_county_list(kit: "Kit") -> None:
    # Synthetic: RIZ001 listed with a county code the county list lacks (as bp08mr23
    # lists PAZ077 with 42603). The rows reach no county; RIZ001's outline lay in
    # Providence County, whose 2018-19 count is then incomplete.
    files, catalog, counties, tally = _setup(kit, ("RIZ001", "44999"))
    report = outlines.check_outlines(_book(kit), files, catalog, counties, tally)
    (item,) = [i for i in report.left_out if i["ugc"] == "RIZ001"]
    assert item["why"] == "county_not_in_county_list"
    assert item["counties_reached"] == []
    assert item["counties_not_in_county_list"] == ["44999"]
    shares = item["outline_counties"]
    assert isinstance(shares, dict)
    assert "44007" in shares
    assert report.incomplete["44007"] == {2018: {"RIZ001"}}
    assert tally.stats.unknown_counties["44999"] > 0


def test_county_ugc_missing_from_the_county_list_stops(kit: "Kit") -> None:
    # Synthetic: a county list without Gulf County, FL, whose FLC045 rows are real.
    counties = zones.read_counties(kit.path("c_16ap26.zip"))
    fewer = replace(counties, counties={k: v for k, v in counties.counties.items() if k != "12045"})
    releases = zones.load_releases(kit.cache(), kit.releases)
    catalog = zones.ZoneCountyCatalog(releases, fewer.state_fips)
    files = archive.load_years(kit.cache(), [2024])
    tally = count.count_years(files, catalog, fewer)
    with pytest.raises(outlines.OutlineError, match="FLC045 2024-25: 11 rows name county 12045"):
        outlines.check_outlines(_book(kit), files, catalog, fewer, tally)


def test_left_out_zone_without_outline_stops(kit: "Kit") -> None:
    files, catalog, counties, tally = _setup(kit)
    with pytest.raises(outlines.OutlineError, match=r"MTZ043 2018-19: \d+ rows left out"):
        outlines.check_outlines(_without(kit, 2018, "MTZ043"), files, catalog, counties, tally)

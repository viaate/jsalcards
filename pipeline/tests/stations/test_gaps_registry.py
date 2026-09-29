"""The registry files of part 4 (the gap states): Cowles' ticker, Flathead County, county sheets.

Every platform file loads, names an adapter that exists, records its terms with the
evidence read, and gives each active station a poll URL, counties on a stated basis
and robots.txt verdicts. Archived captures of every URL a station uses map back to
a station of the part.
"""

from snowlight.sources.stations import archive
from snowlight.sources.stations.adapters import AdapterRegistry, load_adapter
from snowlight.sources.stations.registry import (
    DEFAULT_REGISTRY_DIR,
    AccessPolicy,
    CountyBasis,
    StationStatus,
    load_registry,
)

PLATFORMS = ("coesheet", "cowles", "flathead")
REGISTRY = load_registry()
MINE = sorted(
    (s for s in REGISTRY.stations.values() if s.platform in PLATFORMS), key=lambda s: s.id
)
TICKER = "https://company-wide-tickers.s3.us-west-2.amazonaws.com/KULR_School_Results/closings.html"


def test_every_platform_file_is_present_and_names_a_real_adapter() -> None:
    assert set(PLATFORMS) <= set(REGISTRY.platforms)
    names = AdapterRegistry(DEFAULT_REGISTRY_DIR)
    for platform in PLATFORMS:
        adapter = REGISTRY.platforms[platform].adapter
        assert adapter in names
        assert callable(load_adapter(adapter))


def test_the_stations_and_their_markets() -> None:
    assert [(s.id, s.dma, s.states) for s in MINE] == [
        ("coesheet-shasta", "Chico - Redding, CA DMA", ("CA",)),
        ("coesheet-trinity", "Chico - Redding, CA DMA", ("CA",)),
        ("cowles-kfbb", "Great Falls, MT DMA", ("MT",)),
        ("cowles-khbb", "Helena, MT DMA", ("MT",)),
        ("cowles-ktmf", "Missoula, MT DMA", ("MT",)),
        ("cowles-kulr", "Billings, MT - ID DMA", ("MT", "WY")),
        ("cowles-kwyb", "Butte - Bozeman, MT DMA", ("MT",)),
        ("flathead-county", "Missoula, MT DMA", ("MT",)),
    ]
    assert all(s.status is StationStatus.ACTIVE for s in MINE)


def test_every_cowles_station_reads_the_one_ticker_its_page_frames() -> None:
    cowles = [s for s in MINE if s.platform == "cowles"]
    assert {s.data_url for s in cowles} == {TICKER}
    for station in cowles:
        assert station.poll_url == TICKER
        assert [(f.url, f.loaded_by) for f in station.list_files] == [(TICKER, "frame")]
        assert station.page_url in station.archive_urls
        assert TICKER in station.archive_urls
        assert station.counties is not None
        assert station.counties.basis is CountyBasis.DMA
        assert station.dma is not None
        assert station.dma in station.counties.source


def test_county_lists() -> None:
    counties = {s.id: s.counties for s in MINE}
    flathead = counties["flathead-county"]
    assert flathead is not None
    assert flathead.basis is CountyBasis.OBSERVED
    assert flathead.fips == ("30029",)
    kulr = counties["cowles-kulr"]
    assert kulr is not None
    assert "30111" in kulr.fips  # Yellowstone County (Billings)
    assert {"56003", "56029"} <= set(kulr.fips)  # Big Horn and Park counties, Wyoming
    shasta = counties["coesheet-shasta"]
    assert shasta is not None
    assert shasta.basis is CountyBasis.OBSERVED
    assert shasta.fips == ("06089",)
    trinity = counties["coesheet-trinity"]
    assert trinity is not None
    assert trinity.fips == ("06105",)
    helena = counties["cowles-khbb"]
    assert helena is not None
    assert helena.fips == ("30049",)
    everything = {f for c in counties.values() if c is not None for f in c.fips}
    assert all(f.startswith(("06", "30", "56")) for f in everything)


def test_terms_are_recorded_with_evidence() -> None:
    for platform in PLATFORMS:
        terms = REGISTRY.platforms[platform].terms
        assert terms.automated_access is AccessPolicy.PERMITTED
        assert terms.pollable
        assert terms.evidence
        assert all(item.excerpt for item in terms.evidence)
    google = REGISTRY.platforms["coesheet"].terms
    assert any("robots.txt" in clause for item in google.evidence for clause in item.excerpt)
    cowles = REGISTRY.platforms["cowles"].terms
    assert any("train an LLM" in clause for item in cowles.evidence for clause in item.excerpt)


def test_robots_verdicts_are_recorded_for_every_url_polled() -> None:
    for station in MINE:
        urls = {u for u in (station.page_url, station.data_url) if u}
        assert {check.url for check in station.robots} == urls
        assert all(check.allowed for check in station.robots)


def test_archived_captures_map_back_to_a_station_of_the_part() -> None:
    index = archive.station_index(REGISTRY)
    for station in MINE:
        for url in (station.page_url, *station.archive_urls):
            assert url is not None
            assert index[archive.url_key(url)].platform == station.platform
    # The ticker's captures are read as KULR's (the file is named for it).
    assert index[archive.url_key(TICKER)].id == "cowles-kulr"


def test_shasta_is_read_through_the_page_a_browser_loads() -> None:
    station = REGISTRY.stations["coesheet-shasta"]
    assert station.data_url is None
    assert station.poll_url == "https://www.shastacoe.org/office-of-education/school-closures"
    loaded = [
        (f.loaded_by, f.url.split("/d/e/", 1)[1].split("/", 1)[1]) for f in station.list_files
    ]
    assert loaded == [
        ("frame", "pubhtml?gid=541890420&single=true&widget=true&headers=false"),
        ("script", "pubhtml/sheet?headers=false&gid=541890420"),
        ("unseen", "pub?gid=541890420&single=true&output=csv"),
    ]

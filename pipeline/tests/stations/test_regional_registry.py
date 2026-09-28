"""The registry files of part 3b: Sinclair, Allen, Cox, Graham, Hubbard and the regional lists.

Every platform file loads, names an adapter that exists, records its terms (with the
owner's decision where they forbid automated reading), and gives each active station
a poll URL, counties on a stated basis and robots.txt verdicts. Archived captures of
every URL a station uses map back to that station.
"""

import pytest

from snowlight.sources.stations import archive
from snowlight.sources.stations.adapters import AdapterRegistry, load_adapter
from snowlight.sources.stations.registry import (
    DEFAULT_REGISTRY_DIR,
    AccessPolicy,
    CountyBasis,
    StationStatus,
    load_registry,
)

PLATFORMS = (
    "allen",
    "blox",
    "cox",
    "delaware",
    "eventdelay",
    "graham",
    "hcoe",
    "heritage",
    "hubbard",
    "lockwood",
    "ncpr",
    "news12",
    "radio",
    "riba",
    "santacruzcoe",
    "sinclair",
    "spectrum",
    "townsquare",
    "weatherthreat",
    "whdh",
    "wral",
    "wtop",
    "wveis",
)
REGISTRY = load_registry()
MINE = [s for s in REGISTRY.stations.values() if s.platform in PLATFORMS]
ACTIVE = [s for s in MINE if s.status is StationStatus.ACTIVE]


def test_every_platform_file_is_present_and_names_a_real_adapter() -> None:
    assert set(PLATFORMS) <= set(REGISTRY.platforms)
    names = AdapterRegistry(DEFAULT_REGISTRY_DIR)
    for platform in PLATFORMS:
        adapter = REGISTRY.platforms[platform].adapter
        assert adapter in names
        assert callable(load_adapter(adapter))


def test_station_counts() -> None:
    by_platform = {p: [s for s in MINE if s.platform == p] for p in PLATFORMS}
    active = {p: sum(s.status is StationStatus.ACTIVE for s in by_platform[p]) for p in PLATFORMS}
    assert active == {
        "allen": 7,
        "blox": 7,
        "cox": 6,
        "delaware": 1,
        "eventdelay": 1,
        "graham": 2,
        "hcoe": 1,
        "heritage": 1,
        "hubbard": 6,
        "lockwood": 1,
        "ncpr": 1,
        "news12": 7,
        "radio": 1,
        "riba": 1,
        "santacruzcoe": 1,
        "sinclair": 37,
        "spectrum": 11,
        "townsquare": 1,
        "weatherthreat": 2,
        "whdh": 1,
        "wral": 1,
        "wtop": 1,
        "wveis": 3,
    }


@pytest.mark.parametrize("platform", PLATFORMS)
def test_terms_are_recorded_and_forbidding_terms_carry_the_owner_decision(platform: str) -> None:
    terms = REGISTRY.platforms[platform].terms
    assert terms.automated_access is not AccessPolicy.UNREAD
    assert terms.evidence
    assert terms.pollable
    if terms.automated_access is AccessPolicy.FORBIDDEN:
        assert terms.owner_decision is not None
        assert str(terms.owner_decision.decided_on) == "2026-09-25"


def test_forbidding_platforms_are_the_ones_whose_terms_say_so() -> None:
    forbidden = {
        p
        for p in PLATFORMS
        if REGISTRY.platforms[p].terms.automated_access is AccessPolicy.FORBIDDEN
    }
    assert forbidden == {"blox", "eventdelay", "sinclair", "townsquare", "weatherthreat", "whdh"}


@pytest.mark.parametrize("station", ACTIVE, ids=[s.id for s in ACTIVE])
def test_active_stations_have_counties_and_robots_verdicts(station: object) -> None:
    from snowlight.sources.stations.registry import Station  # noqa: PLC0415

    assert isinstance(station, Station)
    assert station.poll_url is not None
    assert station.counties is not None
    assert station.counties.basis in {CountyBasis.DMA, CountyBasis.STATE, CountyBasis.DISTRICT}
    if station.counties.basis is CountyBasis.DMA:
        assert station.dma is not None
        assert station.dma in station.counties.source
    elif station.counties.basis is CountyBasis.DISTRICT:
        # The county offices' lists (Santa Cruz, Humboldt) speak for their counties' districts.
        assert station.platform in {"santacruzcoe", "hcoe"}
        assert station.leaids
        assert "NCES CCD 2024-25 school directory" in station.counties.source
    else:
        assert station.dma is None
        assert len(station.states) == 1
        assert len({fips[:2] for fips in station.counties.fips}) == 1
    urls = {url for url in (station.page_url, station.data_url) if url}
    assert {check.url for check in station.robots} == urls


def test_statewide_lists_cover_their_whole_state() -> None:
    counts = {
        s.id: (s.states, len(s.counties.fips))
        for s in MINE
        if s.counties is not None and s.counties.basis is CountyBasis.STATE
    }
    assert counts == {
        "delaware-doe": (("DE",), 3),
        "riba-statewide": (("RI",), 5),
        "townsquare-wkxw": (("NJ",), 21),
        "wveis-charter": (("WV",), 55),
        "wveis-private": (("WV",), 55),
        "wveis-statewide": (("WV",), 55),
    }


def test_robots_disallowed_files_are_recorded_not_skipped() -> None:
    wham = REGISTRY.stations["sinclair-wham"]
    verdicts = {check.url: check.allowed for check in wham.robots}
    assert verdicts[wham.page_url or ""] is True
    assert verdicts[wham.data_url or ""] is False
    assert wham.status is StationStatus.ACTIVE


def test_archived_captures_map_to_their_station() -> None:
    index = archive.station_index(REGISTRY)
    for station in ACTIVE:
        for url in (station.page_url, station.data_url, *station.archive_urls):
            if url:
                assert index[archive.url_key(url)].id == station.id, (station.id, url)


def test_region_and_media_id_queries_keep_lists_apart() -> None:
    index = archive.station_index(REGISTRY)
    news12 = "https://itv.news12.com/school_closings/closings.jsp?region="
    assert index[archive.url_key(news12 + "LI")].id == "news12-li"
    assert index[archive.url_key(news12 + "BK&x=1")].id == "news12-bk"
    wt = "https://wt3.weatherthreat.com/wt_list/viewClosings.php?media_id=kneb&t=1&server=wt3"
    # Another WeatherThreat server holds the same list at another host: not this station's URL.
    assert archive.url_key(wt) not in index
    wt1 = "https://wt1.weatherthreat.com/wt_list/viewClosings.php?media_id=ntv&t=17&plugin=1"
    assert index[archive.url_key(wt1)].id == "weatherthreat-ntv"
    assert archive.url_key(wt1) == "wt1.weatherthreat.com/wt_list/viewClosings.php?media_id=ntv"


def test_list_files_are_archive_urls_and_the_poller_reads_the_file() -> None:
    for station in ACTIVE:
        for item in station.list_files:
            assert item.url in station.archive_urls
    assert REGISTRY.stations["sinclair-katv"].data_url == (
        "https://sbgcg.com/Ticker/Stations/KATV/closings.html"
    )
    # The Chameleon key the display page carries is never written into the registry.
    assert all("api_key" not in url for s in MINE for url in s.archive_urls)

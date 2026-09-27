"""The registry files of the network-owned stations, the ECC and FlashAlert."""

import json
from pathlib import Path

from snowlight.sources.stations import archive, flashalert
from snowlight.sources.stations.registry import (
    DEFAULT_REGISTRY_DIR,
    AccessPolicy,
    CountyBasis,
    StationStatus,
    load_registry,
)
from snowlight.sources.stations.robots import RobotsState

REGISTRY = load_registry()
PLATFORMS = ("abc-owned", "nbc-owned", "fox-owned", "cbs-owned", "ecc", "flashalert")
MEMBERS = {
    pid: sorted(s.call_sign for s in REGISTRY.stations.values() if s.platform == pid)
    for pid in PLATFORMS
}


def test_every_network_owned_station_is_registered() -> None:
    assert MEMBERS["abc-owned"] == sorted(
        ["WABC", "WPVI", "WLS", "KABC", "KGO", "KFSN", "WTVD", "KTRK"]
    )
    assert MEMBERS["nbc-owned"] == sorted(
        ["WNBC", "KNBC", "WMAQ", "WCAU", "KXAS", "KNTV", "WRC", "WTVJ", "WBTS", "KNSD", "WVIT"]
    )
    assert len(MEMBERS["fox-owned"]) == 17
    assert len(MEMBERS["cbs-owned"]) == 15
    assert MEMBERS["ecc"] == ["ECC"]


def test_every_flashalert_region_is_registered() -> None:
    regions = sorted(
        int(s.call_sign.removeprefix("FLASH-"))
        for s in REGISTRY.stations.values()
        if s.platform == "flashalert"
    )
    assert regions == sorted(flashalert.REGIONS)
    for station in REGISTRY.stations.values():
        if station.platform == "flashalert":
            region = int(station.call_sign.removeprefix("FLASH-"))
            assert station.data_url == flashalert.REPORT_URL.format(region)
            assert flashalert.XML_URL.format(region) in station.archive_urls


def test_endpoints_by_platform() -> None:
    active = {
        pid: sum(
            s.status is StationStatus.ACTIVE
            for s in REGISTRY.stations.values()
            if s.platform == pid
        )
        for pid in PLATFORMS
    }
    assert active == {
        "abc-owned": 8,
        "nbc-owned": 10,
        "fox-owned": 9,
        "cbs-owned": 8,
        "ecc": 1,
        "flashalert": 9,
    }


def test_terms_are_recorded_with_the_owner_decision_where_they_forbid() -> None:
    for pid in PLATFORMS:
        terms = REGISTRY.platforms[pid].terms
        assert terms.evidence
        assert terms.pollable
        if pid == "flashalert":
            assert terms.automated_access is AccessPolicy.PERMITTED
            assert REGISTRY.platforms[pid].poll_minutes == 15
        else:
            assert terms.automated_access is AccessPolicy.FORBIDDEN
            assert terms.owner_decision is not None


def test_active_stations_record_robots_for_every_url() -> None:
    disallowed = set()
    for station in REGISTRY.active():
        if station.platform not in PLATFORMS:
            continue
        urls = {u for u in (station.page_url, station.data_url) if u}
        assert {check.url for check in station.robots} == urls, station.id
        for check in station.robots:
            assert check.state in {RobotsState.PARSED, RobotsState.UNAVAILABLE}
            if not check.allowed:
                disallowed.add(check.url.split("/")[2])
    # Only CBS's feeds are disallowed (read under the owner's decision of 2026-09-26).
    assert disallowed == {"assets1.cbsnewsstatic.com"}


def test_county_lists_are_market_lists() -> None:
    for station in REGISTRY.stations.values():
        if station.platform in PLATFORMS:
            assert station.counties is not None
            assert station.counties.basis is CountyBasis.DMA
            assert station.dma is not None
            assert station.dma in station.counties.source


def test_list_files_are_archive_urls_and_urls_are_distinct() -> None:
    for station in REGISTRY.active():
        if station.platform not in PLATFORMS:
            continue
        assert station.page_url is None or station.page_url in station.archive_urls
        assert (
            station.data_url is None
            or station.data_url in station.archive_urls
            or (station.id == "ecc-chicago")
        )


def test_the_ecc_file_stays_with_the_station_that_registered_it_first() -> None:
    index = archive.station_index(REGISTRY)
    data = "https://media.psg.nexstardigital.net/WGNR/closings/closings.json"
    # WGN (the Nexstar platform, when its registry file is present) lists the file among
    # its archive URLs, so its captures are WGN's; without it they are the ECC's own.
    owner = "nexstar-wgn" if "nexstar-wgn" in REGISTRY.stations else "ecc-chicago"
    assert index[archive.url_key(data)].id == owner
    app = "https://wgnr-closings.emergencyclosingcenter.com/index.html"
    assert index[archive.url_key(app)].id == "ecc-chicago"


def test_flashalert_region_captures_belong_to_their_region() -> None:
    index = archive.station_index(REGISTRY)
    base = "http://www.flashalertnewswire.net:80/IIN/reportsX/"
    assert index[archive.url_key(f"{base}cwc-closures.php?RegionID=13&Testing=0")].id == (
        "flashalert-columbia"
    )
    assert index[archive.url_key(f"{base}cwc-closures.php?Testing=0&regionid=1")].id == (
        "flashalert-portland"
    )
    assert index[archive.url_key(f"{base}flashnews_xml_emergency.php?RegionID=25")].id == (
        "flashalert-medford"
    )
    # The report address with no region answers region 1's report (see the fixtures
    # portland-bare-live-* and portland-report-live-*): it is region 1's page.
    bare = flashalert.REPORT_URL.split("?", maxsplit=1)[0]
    assert REGISTRY.stations["flashalert-portland"].page_url == bare
    assert index[archive.url_key(f"{base}cwc-closures.php")].id == "flashalert-portland"
    # Every other region with a FlashAlert regional site has that site's emergency
    # reports page (the category order); Colorado Springs has none.
    pages = {s.id: s.page_url for s in REGISTRY.stations.values() if s.platform == "flashalert"}
    assert pages == {
        "flashalert-portland": bare,
        "flashalert-eugene": "https://www.flashalerteugene.net/closures-cats.html",
        "flashalert-colorado-springs": None,
        "flashalert-spokane": "https://www.flashalertspokane.net/closures-cats.html",
        "flashalert-bend": "https://www.flashalertbend.net/closures-cats.html",
        "flashalert-seattle": "https://www.flashalertseattle.net/closures-cats.html",
        "flashalert-columbia": "https://www.flashalertcolumbia.net/closures-cats.html",
        "flashalert-boise": "https://www.flashalertboise.net/closures-cats.html",
        "flashalert-medford": "https://www.flashalertmedford.net/closures-cats.html",
    }
    site = "http://www.flashalertmedford.net:80/closures-time.html"
    assert index[archive.url_key(site)].id == "flashalert-medford"
    assert index[archive.url_key("https://flashalertportland.net/closures-report.html")].id == (
        "flashalert-portland"
    )
    # Any other query is still dropped from the key.
    assert archive.url_key("https://s3.amazonaws.com/b/closings_X.json?rnd=5") == (
        "s3.amazonaws.com/b/closings_X.json"
    )


def test_stale_abc_lists_are_recorded_in_the_evidence() -> None:
    for call in ("KABC", "KGO", "KFSN"):
        station = REGISTRY.stations[f"abc-owned-{call.lower()}"]
        assert "2019-02-12 20:39:39 UTC" in station.evidence
        assert "before 2024" in station.evidence


def test_wanted_archive_captures_cover_every_active_station() -> None:
    wanted = json.loads(
        Path(DEFAULT_REGISTRY_DIR / "archive-wanted-s4c1.json").read_text(encoding="utf-8")
    )
    asked = {item["station"] for item in wanted["snapshots"]}
    active = {s.id for s in REGISTRY.active() if s.platform in PLATFORMS}
    # NBC 6 Miami's market has no winter storm day to ask for.
    assert active - asked == {"nbc-owned-wtvj"}
    for item in wanted["snapshots"]:
        assert len(item["timestamp"]) == 14
        station = REGISTRY.stations[item["station"]]
        # Exact captures of a data file keep the cache-busting query the page added.
        known = {archive.url_key(url) for url in (*station.archive_urls, station.data_url) if url}
        assert archive.url_key(item["url"]) in known
    # The ready 'Run workflow' inputs ask for exactly the listed captures, in order.
    dispatched = [pair for inputs in wanted["dispatch"] for pair in inputs["snapshots"].split()]
    assert dispatched == [f"{item['timestamp']},{item['url']}" for item in wanted["snapshots"]]
    assert all(len(inputs["snapshots"].split()) <= 200 for inputs in wanted["dispatch"])


def test_exact_archive_captures_name_registered_urls() -> None:
    wanted = json.loads(
        Path(DEFAULT_REGISTRY_DIR / "archive-wanted-s4c1.json").read_text(encoding="utf-8")
    )
    exact = wanted["exact"]
    assert exact
    for item in exact:
        assert len(item["timestamp"]) == 14
        station = REGISTRY.stations[item["station"]]
        assert station.platform in PLATFORMS
        known = {archive.url_key(url) for url in (*station.archive_urls, station.data_url) if url}
        assert archive.url_key(item["url"]) in known, item
    pairs = [f"{item['timestamp']},{item['url']}" for item in exact]
    assert len(set(pairs)) == len(pairs)
    dispatched = [
        pair for inputs in wanted["dispatch_exact"] for pair in inputs["snapshots"].split()
    ]
    assert dispatched == pairs

"""The Nexstar, TEGNA and Scripps registry files (config/sources/{nexstar,tegna,scripps}.yaml,
and nexstar-typed.yaml and scripps-typed.yaml for the stations that type their closings).

Every website the first-hand check of 2026-09-26 recorded for the three groups
(docs/research/firsthand/nexstar-tegna-scripps.md) is registered once; the lists
below are its site-level call signs.
"""

import json
import re
from urllib.parse import urlsplit

import pytest

from snowlight.sources.stations import archive, group_fixtures
from snowlight.sources.stations.adapters import ADAPTERS
from snowlight.sources.stations.fetch import skip_reason
from snowlight.sources.stations.model import ListingState, ReadMode
from snowlight.sources.stations.registry import (
    DEFAULT_REGISTRY_DIR,
    AccessPolicy,
    CountyBasis,
    StationStatus,
    load_registry,
)

REGISTRY = load_registry(DEFAULT_REGISTRY_DIR)
GROUPS = ("nexstar", "nexstar-typed", "tegna", "scripps", "scripps-typed")
FAMILIES = {"nexstar": ("nexstar", "nexstar-typed"), "tegna": ("tegna",)}
FAMILIES |= {"scripps": ("scripps", "scripps-typed")}

NEXSTAR_WP = {
    "KAMR", "KARK", "KCAU", "KDVR", "KELO", "KETK", "KFDX", "KFOR", "KLRT", "KLST",
    "KNWA", "KOIN", "KREX", "KRQE", "KSEE", "KSNF", "KSNT", "KTAB", "KTAL", "KTVI", "KTVX",
    "KXMB", "KXRM", "WATE", "WAVY", "WBOY", "WCIA", "WCMH", "WDCW", "WDKY", "WDTN", "WEHT",
    "WETM", "WFFF", "WFRV", "WFXR", "WGHP", "WGMB", "WHO", "WHTM", "WIVT", "WJET",
    "WJHL", "WJTV", "WJW", "WKBN", "WKRN", "WLNS", "WMBD", "WOOD", "WOWK", "WPRI",
    "WQRF", "WREG", "WROC", "WSPA", "WSYR", "WTAJ", "WTEN", "WTNH", "WTRF", "WTWO", "WWLP",
    "WWTI", "WYTV",
}  # fmt: skip
NEXSTAR_FRAMES = {"KSNW": "PSG file", "KOLR": "School Closings Network", "WGN": "ECC JSON"}
NEXSTAR_APP_FEED = {
    "WDAF", "WXIN", "WANE", "WHBF", "WRIC", "KWKT", "WJBF", "WUTR", "WSAV", "WLAX", "WNCN",
    "WVNS", "WNCT", "KLBK", "KMID", "KGET", "WBRE",
}  # fmt: skip
"""Sites whose REST page carries no list but whose archived closings page showed rows: the
poller reads the app feed (``nxd_app/v1/closings_alerts``)."""
MOVED_SITES = {"nexstar-wbre": "https://www.2822news.com"}
"""App-feed sites whose archived page is on a former domain: the feed's origin today."""
NEXSTAR_NONE = {
    "WPIX", "KTLA", "KDAF", "WPHL", "KRON", "WFLA", "KAZT", "KTXL", "WJZY", "KSWB", "KXAN",
    "KLAS", "WIAT", "WGNO", "WKRG", "KVEO", "WCBD", "KTSM", "WBTW", "KLFY",
    "WMBB", "KARD", "KSVI", "WJMN",
}  # fmt: skip
NEXSTAR_TYPED = {"WHNT", "WDHN", "WRBL", "WNTZ", "KIAH", "WIVB"}
"""Sites filed under ``nexstar-typed``: closings pages typed by hand and archived with typed rows
(the poller reads the page's REST object, ``nexstar-wp-typed``); WNTZ, whose closings address
was archived as a typed article (its REST page holds the closings article today); and KIAH and
WIVB, whose closings pages were seen with closings typed beside the empty closings article
(``nexstar-wp-typed-beside``)."""
TEGNA_MODULE = {
    "KAGS", "KARE", "KBMT", "KCEN", "KENS", "KFMB", "KFSM", "KHOU", "KIDY", "KING", "KPNX",
    "KREM", "KSDK", "KTHV", "KTVB", "KUSA", "KVUE", "KWES", "KXTV", "KYTX", "WATN", "WBIR",
    "WBNS", "WCNC", "WCSH", "WFAA", "WFMY", "WGRZ", "WHAS", "WKYC", "WLTX", "WMAZ", "WNEP",
    "WOI", "WPMT", "WQAD", "WTHR", "WTIC", "WTLV", "WTOL", "WTSP", "WUSA", "WVEC", "WXIA",
    "WZDX", "WZZM",
}  # fmt: skip
TEGNA_NONE = {"WWL", "KIII", "KMSB"}
SCRIPPS_MODULE = {
    "KIVI", "KJRH", "KMGH", "KMTV", "KOAA", "KSBY", "KSHB", "KXXV", "WCPO", "WEWS", "WGBA",
    "WKBW", "WLEX", "WMAR", "WTKR", "WTMJ", "WTVF", "WTVR", "WXMI", "WXYZ",
}  # fmt: skip
SCRIPPS_NONE = {
    "KERO", "KGTV", "KJCT", "KKCO", "KKTV", "KMVT", "KNXV", "KRIS", "WFTS", "WPTV", "WTXL",
}  # fmt: skip
MTN_NONE = {"KRTV", "KTVH", "KTVQ", "KXLF", "KXLH"}
"""The Montana stations' Brightspot /weather/closings pages (filed under ``scripps-typed``):
nothing on them in any capture read, no endpoint."""
SCRIPPS_ELSEWHERE = {"KPAX", "KGUN", "KTNV"}
"""The Scripps closings module at an address the first-hand check did not try (KPAX's
``/school-closings-delays``, KGUN's and KTNV's ``/weather/closings-and-delays``), found in the
archive's listings and read live on 2026-09-28."""
SCRIPPS_TYPED = {"KSTU"}
"""A Brightspot closings page typed by hand, archived with typed rows on storm days
(filed under ``scripps-typed``)."""
ON_GRAY = {"tegna-kmsb": "gray-kold", "scripps-kktv": "gray-kktv", "scripps-kkco": "gray-kkco"}
ON_GRAY |= {"scripps-kjct": "gray-kjct", "scripps-kmvt": "gray-kmvt"}


def _members(platform: str) -> dict[str, StationStatus]:
    return {s.call_sign: s.status for s in REGISTRY.stations.values() if s.platform == platform}


def test_every_site_is_registered_with_the_right_status() -> None:
    REGISTRY.check_adapters(ADAPTERS)
    active, none = StationStatus.ACTIVE, StationStatus.NO_ENDPOINT
    expected = {
        "nexstar": dict.fromkeys(NEXSTAR_WP | set(NEXSTAR_FRAMES) | NEXSTAR_APP_FEED, active)
        | dict.fromkeys(NEXSTAR_NONE, none),
        "nexstar-typed": dict.fromkeys(NEXSTAR_TYPED, active),
        "tegna": dict.fromkeys(TEGNA_MODULE | {"KGW"}, active) | dict.fromkeys(TEGNA_NONE, none),
        "scripps": dict.fromkeys(SCRIPPS_MODULE | {"WTVQ"} | SCRIPPS_ELSEWHERE, active)
        | dict.fromkeys(SCRIPPS_NONE, none),
        "scripps-typed": dict.fromkeys(SCRIPPS_TYPED, active) | dict.fromkeys(MTN_NONE, none),
    }
    for platform, members in expected.items():
        assert _members(platform) == members, platform


def test_every_call_sign_the_sites_serve_is_named() -> None:
    # 189 Nexstar, 67 TEGNA and 49 Scripps full-power call signs (the first-hand counts).
    for family, count in (("nexstar", 189), ("tegna", 67), ("scripps", 49)):
        calls: set[str] = set()
        for station in REGISTRY.stations.values():
            if station.platform in FAMILIES[family]:
                calls |= set(station.name.split(" (")[0].split(" / "))
        assert len(calls) == count, family


def test_terms_are_recorded_and_read_under_the_owners_decision() -> None:
    for platform_id in GROUPS:
        platform = REGISTRY.platforms[platform_id]
        assert platform.adapter == platform_id
        terms = platform.terms
        assert terms.automated_access is AccessPolicy.FORBIDDEN
        assert terms.permission is None
        (evidence,) = terms.evidence
        assert evidence.sha256 is not None
        assert any(("robot" in text or "scrape" in text) for text in evidence.excerpt)
        decision = terms.owner_decision
        assert decision is not None
        assert decision.decided_on.isoformat() == "2026-09-25"
        assert "robots.txt" in decision.scope
        assert terms.pollable
    for station in REGISTRY.stations.values():
        if station.platform in GROUPS:
            reason = skip_reason(REGISTRY, station)
            active = station.status is StationStatus.ACTIVE
            assert reason == (None if active else "no known closings endpoint"), station.id


def test_active_stations_have_urls_robots_and_counties() -> None:
    by_id = re.compile(r"^https://[a-z0-9.-]+/wp-json/wp/v2/pages/[0-9]+$")
    for station in REGISTRY.active():
        if station.platform not in GROUPS:
            continue
        assert station.page_url in station.archive_urls, station.id
        if station.data_url is not None:
            assert station.data_url in station.archive_urls, station.id
        checked = {check.url: check for check in station.robots}
        for url in (station.page_url, station.data_url):
            if url is not None:
                assert checked[url].allowed, (station.id, url)
        wp = station.call_sign in NEXSTAR_WP | NEXSTAR_TYPED
        if wp and station.platform in FAMILIES["nexstar"]:
            assert station.data_url is not None
            assert by_id.match(station.data_url), station.id
        counties = station.counties
        assert counties is not None
        assert counties.basis is CountyBasis.DMA
        assert station.dma is not None
        assert station.dma in counties.source
        # One state per state FIPS prefix among the counties.
        assert len({fips[:2] for fips in counties.fips}) == len(station.states), station.id


def test_frames_and_their_files() -> None:
    stations = REGISTRY.stations
    assert stations["nexstar-wtnh"].data_url == "https://www.wtnh.com/wp-json/wp/v2/pages/5894"
    wgn = stations["nexstar-wgn"]
    assert wgn.data_url == "https://media.psg.nexstardigital.net/WGNR/closings/closings.json"
    assert wgn.page_check is not None
    assert wgn.page_check.loads == (wgn.data_url,)
    for station_id, file in (
        (
            "nexstar-ksnw",
            "https://media.psg.nexstardigital.net/ksnw/weather/ksnwx-closings-nwt.html",
        ),
        ("nexstar-kolr", "https://www.schoolclosingsnet.com/report.php?type=html&code=c81e720002"),
        ("tegna-kgw", "https://content.kgw.com/station/flashalert/allclosures.html"),
        ("scripps-wtvq", "https://www.wtvq.com/content/uploads/weather-images/SnoWatch.html"),
    ):
        station = stations[station_id]
        assert station.data_url == file
        assert [item.url for item in station.list_files] == [file]


@pytest.mark.parametrize(("station_id", "gray_id"), sorted(ON_GRAY.items()))
def test_stations_on_gray_sites_point_to_the_gray_source(station_id: str, gray_id: str) -> None:
    station = REGISTRY.stations[station_id]
    assert station.status is StationStatus.NO_ENDPOINT
    assert station.archive_urls == ()
    assert gray_id in station.evidence
    assert gray_id in REGISTRY.stations


def test_archive_captures_of_these_urls_come_back_to_their_station() -> None:
    index = archive.station_index(REGISTRY)
    for station in REGISTRY.stations.values():
        if station.platform not in GROUPS:
            continue
        for url in (station.page_url, station.data_url, *station.archive_urls):
            if url is not None:
                assert index[archive.url_key(url)].id == station.id, (station.id, url)


def test_satellite_markets_are_noted_not_counted() -> None:
    kelo = REGISTRY.stations["nexstar-kelo"]
    assert kelo.dma == "Sioux Falls (Mitchell), SD - IA - MN - NE DMA"
    assert "KCLO" in kelo.evidence
    assert "Rapid City" in kelo.evidence


def test_older_addresses_seen_in_archived_captures_are_their_stations() -> None:
    index = archive.station_index(REGISTRY)
    for url, station_id in [
        ("https://www.wpri.com/weather/closings-delays/", "nexstar-wpri"),
        ("https://fox8.com/closings/school-closings/", "nexstar-wjw"),
        ("https://s3.amazonaws.com/wgnclosings/wgn.html", "nexstar-wgn"),
        ("https://newcdn.tribtv.com/kdvr/schoolclosing/KDVR-Closings.html", "nexstar-kdvr"),
        ("https://newcdn.tribtv.com/wreg/SchoolClosings/closings.html", "nexstar-wreg"),
        (
            "https://media.news10.com/nxs-wtentv-media-us-east-1/closings/school.html",
            "nexstar-wten",
        ),
        ("https://www.woodtv.com/weather/closings-and-delays/", "nexstar-wood"),
        ("https://media.psg.nexstardigital.net/wood/closings/WOODclosings.xml", "nexstar-wood"),
        ("https://media.psg.nexstardigital.net/wowtv/closings/closings.xml", "nexstar-wowk"),
        ("https://www.kshb.com/weather/school-closings", "scripps-kshb"),
        ("https://www.kjrh.com/weather/school-closings", "scripps-kjrh"),
        ("https://www.lex18.com/weather/school-closings", "scripps-wlex"),
    ]:
        assert index[archive.url_key(url)].id == station_id, url
    wood = REGISTRY.stations["nexstar-wood"]
    assert {item.loaded_by for item in wood.list_files} == {"script"}
    assert all(
        "20241205143721" in item.seen or "20190330155239" in item.seen for item in wood.list_files
    )


def _archive_wanted() -> dict[str, list[dict[str, str]]]:
    """The listings, captures and request commits of ``archive-wanted-s4b.json``."""
    path = DEFAULT_REGISTRY_DIR / "archive-wanted-s4b.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        key: [{name: str(value) for name, value in item.items()} for item in data[key]]
        for key in ("cdx", "snapshots", "requests")
    }


def test_app_feed_sites_read_the_feed_and_keep_the_archived_page() -> None:
    fixtures = group_fixtures.load_entries(group_fixtures.DEFAULT_FOLDER)
    for station in REGISTRY.stations.values():
        if station.platform != "nexstar" or station.call_sign not in NEXSTAR_APP_FEED:
            continue
        assert station.page_url is not None
        origin = "https://" + urlsplit(station.page_url).netloc
        if station.id in MOVED_SITES:
            # The archived page is on the site's former domain; the feed is on the new one.
            origin = MOVED_SITES[station.id]
            assert "The site moved from" in station.evidence, station.id
        assert station.data_url == f"{origin}/wp-json/nxd_app/v1/closings_alerts", station.id
        # The page's archived captures are the proof that the station posts closings:
        # a fixture of the page itself, populated, from a real capture.
        populated = [
            entry
            for entry in fixtures
            if entry.source_id == station.id
            and entry.mode is ReadMode.ARCHIVE
            and archive.url_key(entry.url) == archive.url_key(station.page_url)
            and entry.expected.state is ListingState.POPULATED
        ]
        assert populated, station.id
        for entry in populated:
            stamp, rows = f"{entry.captured_at:%Y%m%d%H%M%S}", entry.expected.rows
            assert (
                f"{stamp} ({rows} " in station.evidence or f"{stamp} {rows} row" in station.evidence
            ), (station.id, stamp)


_LISTED = re.compile(r"CDX listings \(2014 to 2026\) of (.+?) \(commit (\w+), run")
_CAPTURED = re.compile(
    r"and (\d+) captures of its closings pages(?: and app feed)? \(commits ([\w, ]+);"
)


def test_no_endpoint_nexstar_evidence_names_only_requests_really_made() -> None:
    wanted = _archive_wanted()
    listed = {item["url"] for item in wanted["cdx"]}
    captured = {(item["timestamp"], item["url"]) for item in wanted["snapshots"]}
    commits = {item["commit"] for item in wanted["requests"]}
    per_site = json.loads(
        (DEFAULT_REGISTRY_DIR / "archive-wanted-s4b.json").read_text(encoding="utf-8")
    )["no_endpoint_nexstar"]
    for station in REGISTRY.stations.values():
        if station.platform != "nexstar" or station.status is not StationStatus.NO_ENDPOINT:
            continue
        assert "archive-wanted-s4b.json)" not in station.evidence.split("Archive check:")[0]
        match = _LISTED.search(station.evidence)
        assert match is not None, station.id
        patterns = match.group(1).split(", ")
        assert match.group(2) in commits
        assert set(patterns) <= listed, station.id
        # Its closings pages and its app feed are among the listings.
        feed = next(url for url in station.archive_urls if "closings_alerts" in url)
        host = urlsplit(feed).netloc.removeprefix("www.")
        assert f"{host}/wp-json/nxd_app/v1/closings_alerts*" in patterns, station.id
        assert f"{host}/weather/clos*" in patterns, station.id
        # The captures it counts are the ones recorded for it, each really requested.
        shots = _CAPTURED.search(station.evidence)
        assert shots is not None, station.id
        record = per_site[station.id]
        assert int(shots.group(1)) == len(record["captures"]), station.id
        assert set(shots.group(2).split(", ")) == {item["commit"] for item in record["captures"]}
        assert set(shots.group(2).split(", ")) <= commits
        for item in record["captures"]:
            assert (item["timestamp"], item["url"]) in captured, (station.id, item)
        for item in record["listings"]:
            assert item["url"] in listed, (station.id, item)
            assert item["commit"] in commits, (station.id, item)


_ST_LISTED = re.compile(
    r"Asked for since, in commits ([^:]+): CDX listings \(2014 to 2026\) of (.+?) and a listing "
    r"of every address of the site"
)
_ST_CAPTURED = re.compile(
    r", and (\d+) captures of its closings pages on storm days and in past winters"
)


def _per_site() -> dict[str, dict[str, list[dict[str, str]]]]:
    """``no_endpoint_scripps_tegna`` of ``archive-wanted-s4b.json``: each site's requests."""
    path = DEFAULT_REGISTRY_DIR / "archive-wanted-s4b.json"
    data = json.loads(path.read_text(encoding="utf-8"))["no_endpoint_scripps_tegna"]
    return {
        sid: {
            kind: [{k: str(v) for k, v in item.items() if k != "filter"} for item in entry[kind]]
            for kind in ("listings", "captures")
        }
        for sid, entry in data.items()
    }


def test_scripps_and_tegna_evidence_names_only_requests_really_made() -> None:
    wanted = _archive_wanted()
    listed = {item["url"] for item in wanted["cdx"]}
    captured = {(item["timestamp"], item["url"]) for item in wanted["snapshots"]}
    runs = {item["commit"]: item["run"] for item in wanted["requests"]}
    per_site = _per_site()
    for station_id, record in per_site.items():
        station = REGISTRY.stations[station_id]
        match = _ST_LISTED.search(station.evidence)
        assert match is not None, station_id
        named = dict(re.findall(r"(\w+) \(run (\d+)\)", match.group(1)))
        asked = {i["commit"] for i in record["listings"] + record["captures"]}
        assert named == {c: str(runs[c]) for c in asked}, station_id
        assert set(match.group(2).split(", ")) <= listed, station_id
        assert {i["url"] for i in record["listings"]} <= listed, station_id
        shots = _ST_CAPTURED.search(station.evidence)
        if record["captures"]:
            assert shots is not None, station_id
            assert int(shots.group(1)) == len(record["captures"]), station_id
        for item in record["captures"]:
            assert (item["timestamp"], item["url"]) in captured, (station_id, item)
            assert item["commit"] in runs, (station_id, item)


def test_every_scripps_and_tegna_site_without_an_endpoint_was_checked_in_the_archive() -> None:
    per_site = _per_site()
    for station in REGISTRY.stations.values():
        if station.platform not in ("scripps", "scripps-typed", "tegna"):
            continue
        if station.status is StationStatus.NO_ENDPOINT or station.id in per_site:
            assert "Archive check:" in station.evidence, station.id
            if station.id in ON_GRAY and station.id not in per_site:
                # A Gray site: its captures are read for the Gray entry, named here.
                assert ON_GRAY[station.id] in station.evidence.split("Archive check:")[1]
            else:
                assert station.id in per_site, station.id

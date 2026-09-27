"""The station registry: the real files in config/sources/ and the loader's checks."""

import json
import re
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.sources.stations.adapters import ADAPTERS
from snowlight.sources.stations.fetch import skip_reason
from snowlight.sources.stations.registry import (
    DEFAULT_REGISTRY_DIR,
    AccessPolicy,
    PlatformFile,
    RegistryError,
    StationStatus,
    dump_platform_file,
    load_registry,
)

GRAY_EXPORT = re.compile(
    r"^https://s3\.amazonaws\.com/grayfilestore-[a-z0-9]+/closingsData/closings_[A-Z0-9]+\.json$"
)


def test_real_registry_loads_and_names_known_adapters() -> None:
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    registry.check_adapters(ADAPTERS)
    assert {"gray", "hearst"} <= set(registry.platforms)


def test_every_gray_export_is_registered() -> None:
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    gray = [s for s in registry.stations.values() if s.platform == "gray" and s.export_url]
    # The 123 exports the research verified, WBBJ's (an archived capture of it) and
    # KATC's (read live in round 2), each kept as its station's export_url.
    assert len(gray) == 125
    assert all(s.export_url and GRAY_EXPORT.match(s.export_url) for s in gray)
    assert all(s.export_url in s.archive_urls for s in gray)
    assert len({s.export_url for s in gray}) == 125
    missing = [s for s in registry.stations.values() if s.status is StationStatus.NO_ENDPOINT]
    assert {s.call_sign for s in missing if s.platform == "gray"} >= {"WAAY", "WDRB", "WREX"}
    assert "arc-site=wbbj" in registry.stations["gray-wbbj"].evidence
    assert "Fusion.arcSite" in registry.stations["gray-katc"].evidence
    kytv = registry.stations["gray-kytv"]
    assert kytv.export_url == (
        "https://s3.amazonaws.com/grayfilestore-ky3/closingsData/closings_KY3.json"
    )
    assert kytv.data_url == kytv.export_url


def test_every_active_gray_station_reads_the_list_its_page_loads() -> None:
    """The live data_url is the list the station's page loaded in a browser check."""
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    gray = [s for s in registry.active() if s.platform == "gray"]
    assert len(gray) == 119
    for station in gray:
        check = station.page_check
        assert check is not None, station.id
        assert station.data_url in check.loads, station.id
        assert check.checked_at.isoformat().startswith("2026-09-26"), station.id
        assert station.page_url is not None, station.id
    stations = registry.stations
    framed = {
        "gray-wfsb": "https://webpubcontent.gray.tv/wfsb/xml/WFSBclosings.html",
        "gray-wggb": "https://webpubcontent.gray.tv/wggb/xml/WMNclosings.html",
        "gray-wlfi": "https://webpubcontent.gray.tv/wlfi/closings/WLFI_schools26.HTM",
        "gray-wlio": "https://webpubcontent.gray.tv/wlio/Closings/closings.html",
        "gray-wthi": "https://webpubcontent.gray.tv/wthi/closings/closings.html",
        "gray-wand": "https://webpubcontent.gray.tv/wand/bti/closings.html",
        "gray-wjrt": "https://ftp2.wjrt.com/school_closings/wjrtclosings.html",
        "gray-kake": "https://www.kake.com/app/closings/closings.xml",
    }
    for station_id, url in framed.items():
        station = stations[station_id]
        assert station.data_url == url, station_id
        assert url in {item.url for item in station.list_files}, station_id
        assert station.export != url  # the archive reader still follows to the export
    wfsb = stations["gray-wfsb"].page_check
    assert wfsb is not None
    assert "First Church/Christ Cong-E Haddam" in wfsb.shows
    # Pages that load a sister station's export.
    assert stations["gray-kjct"].data_url == (
        "https://s3.amazonaws.com/grayfilestore-kkco/closingsData/closings_KKCO.json"
    )
    assert stations["gray-ksnb"].data_url == stations["gray-koln"].data_url
    assert stations["gray-ktre"].data_url == stations["gray-kltv"].data_url
    # No page of their own, or a page that loads no list: no endpoint, with the check.
    for station_id in (
        "gray-kevn", "gray-kmot", "gray-kqcd", "gray-kumv", "gray-kspr", "gray-ktvk",
        "gray-kold", "gray-kvvu", "gray-kcwy", "gray-kgwn", "gray-wevv", "gray-wpga",
    ):  # fmt: skip
        station = stations[station_id]
        assert station.status is StationStatus.NO_ENDPOINT, station_id
        assert "Page check 2026-09-26" in station.evidence, station_id
    assert "HTTP 502" in stations["gray-wevv"].evidence


def test_a_data_url_the_page_does_not_load_is_refused(tmp_path: Path) -> None:
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    content = registry.files["gray"].model_dump(mode="json")
    for station in content["stations"]:
        if station["id"] == "gray-wfsb":
            station["data_url"] = station["export_url"]
    folder = tmp_path / "sources"
    folder.mkdir()
    (folder / "gray.yaml").write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(RegistryError, match="not among the files its page loads"):
        load_registry(folder)


# Every station the navbox Template:Hearst (English Wikipedia, read 2026-09-25) lists under
# Hearst Television with a news site of its own, plus WMOR-TV; sister channels that publish
# through one of these sites are named in the platform notes.
HEARST_CALLS = {
    "KCCI", "KCRA", "KETV", "KHBS", "KMBC", "KOAT", "KOCO", "KSBW", "WAPT", "WBAL",
    "WBBH", "WCVB", "WDSU", "WESH", "WGAL", "WISN", "WJCL", "WLKY", "WLWT", "WMOR",
    "WMTW", "WMUR", "WPBF", "WPTZ", "WTAE", "WVTM", "WXII", "WYFF",
}  # fmt: skip


def test_every_hearst_station_is_registered() -> None:
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    hearst = [s for s in registry.stations.values() if s.platform == "hearst"]
    assert {s.call_sign for s in hearst} == HEARST_CALLS
    notes = registry.platforms["hearst"].notes
    for sister in ("KCWE", "KQCA", "WCWG", "WKCF", "KHOG", "WPXT", "WZVN", "WNNE"):
        assert sister in notes
    for station in hearst:
        if station.page_url:
            assert station.page_url.endswith("/weather/closings"), station.id
            assert station.page_url in station.archive_urls


def test_active_stations_have_counties_matching_their_states() -> None:
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    for station in registry.active():
        assert station.counties is not None, station.id
        assert station.counties.fips, station.id
        assert station.dma, station.id
        assert station.id in station.counties.source or station.dma in station.counties.source


def test_every_active_station_url_has_a_robots_check() -> None:
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    for station in registry.active():
        checked = {check.url: check for check in station.robots}
        for url in (station.page_url, station.data_url):
            if url is not None:
                assert url in checked, (station.id, url)
                assert checked[url].rule, (station.id, url)


def test_every_page_url_is_also_an_archive_url() -> None:
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    for station in registry.stations.values():
        if station.page_url is not None:
            assert station.page_url in station.archive_urls, station.id


def test_forbidding_terms_are_recorded_and_read_under_the_owners_decision() -> None:
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    for platform_id in ("gray", "hearst"):
        terms = registry.platforms[platform_id].terms
        assert terms.automated_access is AccessPolicy.FORBIDDEN
        assert terms.permission is None
        assert terms.evidence
        assert terms.evidence[0].excerpt
        decision = terms.owner_decision
        assert decision is not None
        assert decision.decided_on.isoformat() == "2026-09-25"
        assert "robots.txt" in decision.scope
        assert "decided on 2026-09-26 to read" in decision.scope
        assert "always honored" not in decision.scope
        assert terms.pollable
    for station in registry.stations.values():
        reason = skip_reason(registry, station)
        if station.status is StationStatus.ACTIVE:
            assert reason is None, station.id
        else:
            assert reason == "no known closings endpoint"


def test_registry_files_round_trip() -> None:
    for path in sorted(DEFAULT_REGISTRY_DIR.glob("*.yaml")):
        content = PlatformFile.model_validate_json(
            json.dumps(yaml.safe_load(path.read_text(encoding="utf-8")))
        )
        assert dump_platform_file(content) == path.read_bytes(), path.name


def _write(folder: Path, name: str, content: dict[str, object]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")


def _platform(pid: str = "demo") -> dict[str, object]:
    return {
        "id": pid,
        "name": "Demo platform (synthetic)",
        "operator": "Nobody",
        "adapter": "gray",
        "poll_minutes": 10,
        "terms": {"automated_access": "unread", "summary": "not read", "evidence": []},
        "notes": "synthetic test platform",
    }


def _station(changes: dict[str, object] | None = None) -> dict[str, object]:
    station: dict[str, object] = {
        "id": "demo-wxyz",
        "platform": "demo",
        "call_sign": "WXYZ",
        "name": "Synthetic",
        "market": "Nowhere",
        "dma": None,
        "states": ["KS"],
        "counties": {"basis": "observed", "source": "synthetic", "fips": ["20091"]},
        "page_url": "https://example.test/closings",
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": "active",
        "evidence": "synthetic",
    }
    station.update(changes or {})
    return station


def test_duplicate_station_ids_are_refused(tmp_path: Path) -> None:
    _write(tmp_path, "demo", {"platform": _platform(), "stations": [_station(), _station()]})
    with pytest.raises(RegistryError, match="used twice"):
        load_registry(tmp_path)


def test_platform_must_match_file_name(tmp_path: Path) -> None:
    _write(tmp_path, "other", {"platform": _platform(), "stations": []})
    with pytest.raises(RegistryError, match="holds platform"):
        load_registry(tmp_path)


@pytest.mark.parametrize(
    "changes",
    [
        {"counties": {"basis": "dma", "source": "x", "fips": ["20091", "20001"]}},
        {"counties": {"basis": "dma", "source": "x", "fips": ["2009"]}},
        {"page_url": None},
        {"status": "no_endpoint"},
        {"states": ["MO", "KS"]},
        {"id": "other-wxyz"},
        {"page_url": "ftp://example.test/x"},
    ],
)
def test_bad_stations_are_refused(tmp_path: Path, changes: dict[str, object]) -> None:
    _write(tmp_path, "demo", {"platform": _platform(), "stations": [_station(changes)]})
    with pytest.raises(RegistryError):
        load_registry(tmp_path)


def test_unknown_adapter_is_refused(tmp_path: Path) -> None:
    platform = _platform()
    platform["adapter"] = "nope"
    _write(tmp_path, "demo", {"platform": platform, "stations": [_station()]})
    with pytest.raises(RegistryError, match="unknown adapter"):
        load_registry(tmp_path).check_adapters(ADAPTERS)


def test_read_terms_need_evidence(tmp_path: Path) -> None:
    platform = _platform()
    platform["terms"] = {"automated_access": "permitted", "summary": "x", "evidence": []}
    _write(tmp_path, "demo", {"platform": platform, "stations": []})
    with pytest.raises(RegistryError, match="evidence"):
        load_registry(tmp_path)


def test_permission_lifts_forbidding_terms(tmp_path: Path) -> None:
    platform = _platform()
    platform["terms"] = {
        "automated_access": "forbidden",
        "summary": "x",
        "evidence": [
            {
                "url": "https://example.test/terms",
                "read_at": "2026-09-25T00:00:00Z",
                "sha256": None,
                "excerpt": ["no robots"],
            }
        ],
        "permission": {
            "granted_by": "Synthetic Station",
            "granted_on": "2026-09-30",
            "reference": "letter (synthetic)",
            "scope": "closings list polling",
        },
    }
    _write(tmp_path, "demo", {"platform": platform, "stations": [_station()]})
    registry = load_registry(tmp_path)
    assert registry.platforms["demo"].terms.pollable
    assert skip_reason(registry, registry.stations["demo-wxyz"]) is None


def _forbidding_terms() -> dict[str, object]:
    return {
        "automated_access": "forbidden",
        "summary": "x",
        "evidence": [
            {
                "url": "https://example.test/terms",
                "read_at": "2026-09-25T00:00:00Z",
                "sha256": None,
                "excerpt": ["no robots"],
            }
        ],
    }


def test_forbidding_terms_without_a_decision_hold_the_station(tmp_path: Path) -> None:
    platform = _platform()
    platform["terms"] = _forbidding_terms()
    _write(tmp_path, "demo", {"platform": platform, "stations": [_station()]})
    registry = load_registry(tmp_path)
    assert not registry.platforms["demo"].terms.pollable
    reason = skip_reason(registry, registry.stations["demo-wxyz"])
    assert reason is not None
    assert reason.startswith("terms forbid automated access")


def test_owner_decision_lifts_forbidding_terms_only(tmp_path: Path) -> None:
    decision = {
        "decided_by": "Synthetic Owner",
        "decided_on": "2026-09-25",
        "reference": "synthetic",
        "scope": "synthetic; robots.txt still honored",
    }
    platform = _platform()
    platform["terms"] = {**_forbidding_terms(), "owner_decision": decision}
    _write(tmp_path, "demo", {"platform": platform, "stations": [_station()]})
    registry = load_registry(tmp_path)
    assert registry.platforms["demo"].terms.pollable
    assert skip_reason(registry, registry.stations["demo-wxyz"]) is None
    platform["terms"] = {
        **_forbidding_terms(),
        "automated_access": "unread",
        "owner_decision": decision,
    }
    _write(tmp_path, "demo", {"platform": platform, "stations": [_station()]})
    with pytest.raises(RegistryError, match="owner's decision"):
        load_registry(tmp_path)


def test_empty_folder_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="no registry files"):
        load_registry(tmp_path)


def test_malformed_yaml_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "demo.yaml").write_text("platform: [unclosed", encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(tmp_path)

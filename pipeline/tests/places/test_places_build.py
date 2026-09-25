"""End-to-end tests of ``snowlight places build`` against real source slices.

The fake server holds the real fixture slices at their real URLs, so these tests
run discovery, download, caching, parsing, record building and writing exactly
as production does, with no network.
"""

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

import snowlight
from snowlight.cli import main
from snowlight.places import cli as places_cli
from snowlight.places.build import (
    METHOD,
    Pins,
    PlacesBuildError,
    build_places,
    latest_gazetteer_year,
    latest_grf,
    latest_popest_series,
)
from snowlight.places.download import DownloadError, SourceCache
from snowlight.places.grf import GRF_PAGE_URL
from snowlight.sources.census import gazetteer, popest

if TYPE_CHECKING:
    from conftest import FakeServer

# These lines are copied from the full production build of 2026-09-24 (2026
# Gazetteer, GRF25, Vintage 2025 estimates). The fixture slices hold the same
# source rows, so building from the slices must reproduce them byte for byte.
EXPECTED_CITY_LINES = [
    '{"geoid":"0100100","kind":"CDP","lat":33.091627,"lon":-85.527029,"name":"Abanda",'
    '"population":null,"state":"AL"}',
    '{"geoid":"0100124","kind":"city","lat":31.565164,"lon":-85.259165,"name":"Abbeville",'
    '"population":2378,"state":"AL"}',
    '{"geoid":"0811810","kind":"city","lat":38.441886,"lon":-105.220899,"name":"Cañon City",'
    '"population":17030,"state":"CO"}',
    '{"geoid":"4744382","kind":"metropolitan government","lat":35.288888,"lon":-86.358684,'
    '"name":"Lynchburg, Moore County","population":6920,"state":"TN"}',
]
EXPECTED_ZIP_LINES = [
    '{"districts":[{"leaid":"4400840","name":"Pawtucket School District","share":0.9954},'
    '{"leaid":"2502190","name":"Attleboro School District","share":0.004646}],'
    '"lat":41.878603,"lon":-71.353131,"states":["RI","MA"],"zcta":"02861"}',
    '{"districts":[{"leaid":"5009600","name":"North Country Senior UHSD 22","share":1.0},'
    '{"leaid":"5099931","name":"North Country Supervisory Union","share":1.0},'
    '{"leaid":"5005220","name":"Lowell School District","share":0.9998},'
    '{"leaid":"5008130","name":"Troy School District","share":0.000183},'
    '{"leaid":"5000436","name":"Lake Region Union Elementary Middle School District",'
    '"share":5.614e-06},{"leaid":"5005050","name":"Lake Region UHSD 24","share":5.614e-06},'
    '{"leaid":"5099934","name":"Orleans Central Supervisory Union","share":5.614e-06}],'
    '"lat":44.793437,"lon":-72.458451,"states":["VT"],"zcta":"05847"}',
    '{"districts":[],"lat":44.887342,"lon":-93.192383,"states":["MN"],"zcta":"55111"}',
    '{"districts":[{"leaid":"0406250","name":"Peoria Unified School District","share":0.003599},'
    '{"leaid":"0402690","name":"Dysart Unified District","share":0.001969}],'
    '"lat":33.605791,"lon":-112.28406,"states":["AZ"],"zcta":"85351"}',
]
DATA_URLS = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/"
    "2026_Gaz_place_national.zip",
    "https://nces.ed.gov/programs/edge/data/GRF25.zip",
    "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/cities/totals/"
    "sub-est2025.csv",
)


def _run(cache: SourceCache, tmp_path: Path, pins: Pins | None = None) -> dict[str, object]:
    result = build_places(
        cache, tmp_path / "site" / "search", tmp_path / "manifests" / "places.json", pins
    )
    return result.manifest


def test_build_writes_the_expected_records(cache: SourceCache, tmp_path: Path) -> None:
    manifest = _run(cache, tmp_path)
    cities = (tmp_path / "site" / "search" / "cities.jsonl").read_text(encoding="utf-8")
    zips = (tmp_path / "site" / "search" / "zips.jsonl").read_text(encoding="utf-8")
    city_lines, zip_lines = cities.splitlines(), zips.splitlines()
    assert len(city_lines) == 23
    assert len(zip_lines) == 8
    for line in EXPECTED_CITY_LINES:
        assert line in city_lines
    for line in EXPECTED_ZIP_LINES:
        assert line in zip_lines
    assert cities.endswith("\n")
    assert zips.endswith("\n")
    assert [json.loads(line)["geoid"] for line in city_lines] == sorted(
        json.loads(line)["geoid"] for line in city_lines
    )
    assert manifest["releases"] == {
        "gazetteer_year": 2026,
        "grf_tiger_year": 2025,
        "grf_zcta_vintage": 2020,
        "popest_column": "POPESTIMATE2025",
        "popest_encoding": "iso-8859-1",
        "popest_series": "2020-2025",
        "zcta_area_gazetteer_year": 2025,
    }


def test_published_files_name_no_source(cache: SourceCache, tmp_path: Path) -> None:
    _run(cache, tmp_path)
    for name in ("cities.jsonl", "zips.jsonl"):
        text = (tmp_path / "site" / "search" / name).read_text(encoding="utf-8").lower()
        for word in ("http", "census", "nces", "gazetteer", "estimate", "tiger", "source"):
            assert word not in text, (name, word)
    assert sorted(p.name for p in (tmp_path / "site" / "search").iterdir()) == [
        "cities.jsonl",
        "zips.jsonl",
    ]


def test_manifest_traces_every_output_to_its_sources(
    cache: SourceCache, server: "FakeServer", tmp_path: Path
) -> None:
    manifest = _run(cache, tmp_path)
    sources = manifest["sources"]
    assert isinstance(sources, list)
    roles = {s["role"]: s for s in sources}
    assert set(roles) == {
        "places_gazetteer",
        "zcta_gazetteer",
        "zcta_area_gazetteer",
        "lea_zcta_relationship",
        "place_population_estimates",
        "lsad_codes",
        "zcta_county_relationship",
    }
    for entry in sources:
        assert entry["sha256"] == hashlib.sha256(server.files[entry["url"]]).hexdigest()
        assert entry["bytes"] == len(server.files[entry["url"]])
        assert entry["retrieved_at"].endswith("Z")
    assert roles["lea_zcta_relationship"]["member"] == "GRF25/grf25_lea_zcta5ce20.xlsx"
    assert roles["zcta_area_gazetteer"]["url"].endswith("2025_Gaz_zcta_national.zip")
    outputs = manifest["outputs"]
    assert isinstance(outputs, list)
    for output in outputs:
        data = (tmp_path / "site" / "search" / output["file"]).read_bytes()
        assert output["sha256"] == hashlib.sha256(data).hexdigest()
        assert output["bytes"] == len(data)
        assert output["records"] == data.count(b"\n")
    assert manifest["method"] == METHOD
    consulted = manifest["pages_consulted"]
    assert isinstance(consulted, list)
    assert [p["url"] for p in consulted] == [
        gazetteer.INDEX_URL,
        gazetteer.release_dir_url(2026),
        GRF_PAGE_URL,
        popest.DATASETS_URL,
        popest.totals_dir_url(2020, 2025),
    ]
    on_disk = json.loads((tmp_path / "manifests" / "places.json").read_text(encoding="utf-8"))
    assert on_disk == manifest


def test_rebuild_reuses_the_cache_and_is_byte_identical(
    cache: SourceCache, server: "FakeServer", tmp_path: Path
) -> None:
    _run(cache, tmp_path)
    first = {p.name: p.read_bytes() for p in (tmp_path / "site" / "search").iterdir()}
    _run(cache, tmp_path)
    second = {p.name: p.read_bytes() for p in (tmp_path / "site" / "search").iterdir()}
    assert first == second
    for url in DATA_URLS:
        assert server.hits[url] == 1


def test_pinned_releases_skip_discovery(
    cache: SourceCache, server: "FakeServer", tmp_path: Path
) -> None:
    manifest = _run(cache, tmp_path, Pins(2026, 2025, (2020, 2025)))
    assert manifest["pages_consulted"] == []
    assert server.hits[gazetteer.INDEX_URL] == 0


def test_discovery_skips_incomplete_and_missing_releases(
    server: "FakeServer", tmp_path: Path
) -> None:
    # Synthetic listings: a 2027 Gazetteer directory without a ZCTA file, a
    # 2021-2026 estimates series whose totals directory lacks the national file,
    # and a 2020-2026 series whose totals directory does not exist yet.
    gaz27 = gazetteer.release_dir_url(2027)
    server.files[gazetteer.INDEX_URL] = (
        b'<a href="2027_Gazetteer/"></a><a href="2026_Gazetteer/"></a>'
    )
    server.files[gaz27] = b'<a href="2027_Gaz_place_national.zip"></a>'
    server.files[popest.DATASETS_URL] = (
        b'<a href="2021-2026/"></a><a href="2020-2026/"></a><a href="2020-2025/"></a>'
    )
    server.files[popest.totals_dir_url(2021, 2026)] = b'<a href="sub-est2026_1.csv"></a>'
    with SourceCache(tmp_path, server.client(), sleep=lambda _s: None) as cache:
        assert latest_gazetteer_year(cache) == 2026
        assert latest_popest_series(cache) == (2020, 2025)
        assert latest_grf(cache).tiger_year == 2025
    assert server.hits[gaz27] == 1
    assert server.hits[popest.totals_dir_url(2020, 2026)] == 1


@pytest.mark.parametrize(
    ("url", "finder", "message"),
    [
        (gazetteer.INDEX_URL, latest_gazetteer_year, "no Gazetteer release"),
        (GRF_PAGE_URL, latest_grf, "links no GRF zip"),
        (popest.DATASETS_URL, latest_popest_series, "no Population Estimates series"),
    ],
)
def test_discovery_fails_loudly_when_nothing_is_published(
    server: "FakeServer", tmp_path: Path, url: str, finder: object, message: str
) -> None:
    server.files[url] = b"<p>nothing here</p>"
    with SourceCache(tmp_path, server.client(), sleep=lambda _s: None) as cache:
        assert callable(finder)
        with pytest.raises(PlacesBuildError, match=message):
            finder(cache)


# --- the CLI ------------------------------------------------------------------------


def _patch_client(monkeypatch: pytest.MonkeyPatch, server: "FakeServer") -> None:
    monkeypatch.setattr(places_cli, "make_client", server.client)


def test_cli_places_build(
    monkeypatch: pytest.MonkeyPatch,
    server: "FakeServer",
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_client(monkeypatch, server)
    monkeypatch.setattr(places_cli, "pipeline_root", lambda: tmp_path)
    assert main(["places", "build", "--popest-series", "2020-2025"]) == 0
    out = capsys.readouterr().out
    assert f"wrote 23 records to {tmp_path / 'out/site-data/search/cities.jsonl'}" in out
    assert f"wrote 8 records to {tmp_path / 'out/site-data/search/zips.jsonl'}" in out
    assert (tmp_path / "out" / "manifests" / "places.json").is_file()
    assert (tmp_path / ".cache" / "places" / "nces.ed.gov").is_dir()
    assert server.hits[popest.DATASETS_URL] == 0


def test_cli_places_build_with_explicit_paths(
    monkeypatch: pytest.MonkeyPatch, server: "FakeServer", tmp_path: Path
) -> None:
    _patch_client(monkeypatch, server)
    argv = [
        "places",
        "build",
        "--cache-dir",
        str(tmp_path / "c"),
        "--out-dir",
        str(tmp_path / "o"),
        "--manifest",
        str(tmp_path / "m.json"),
        "--gazetteer-year",
        "2026",
        "--grf-year",
        "2025",
        "--revalidate",
    ]
    assert main(argv) == 0
    assert (tmp_path / "o" / "zips.jsonl").is_file()
    assert (tmp_path / "m.json").is_file()


def test_cli_reports_a_failed_build(
    monkeypatch: pytest.MonkeyPatch,
    server: "FakeServer",
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_client(monkeypatch, server)
    server.overrides[DATA_URLS[1]] = lambda request: httpx.Response(404, request=request)
    argv = ["places", "build", "--cache-dir", str(tmp_path / "c"), "--out-dir", str(tmp_path / "o")]
    assert main([*argv, "--manifest", str(tmp_path / "m.json")]) == 1
    assert "places build failed:" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()
    assert not (tmp_path / "m.json").exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["places"],
        ["places", "build", "--popest-series", "2025"],
        ["places", "build", "--grf-year", "25"],
    ],
)
def test_cli_usage_errors(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == 2
    assert "usage: snowlight places" in capsys.readouterr().err


def test_pipeline_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert (places_cli.pipeline_root() / "pyproject.toml").is_file()
    monkeypatch.setattr(snowlight, "__file__", str(tmp_path / "pkg" / "__init__.py"))
    monkeypatch.chdir(tmp_path)
    assert places_cli.pipeline_root() == tmp_path


def test_popest_discovery_does_not_fall_back_on_server_errors(
    server: "FakeServer", tmp_path: Path
) -> None:
    totals = popest.totals_dir_url(2020, 2025)
    server.overrides[totals] = lambda request: httpx.Response(503, request=request)
    with (
        SourceCache(tmp_path, server.client(), sleep=lambda _s: None) as cache,
        pytest.raises(DownloadError, match="attempts"),
    ):
        latest_popest_series(cache)

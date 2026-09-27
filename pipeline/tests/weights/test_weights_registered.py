"""The read-only registry reader and the market check.

``fixtures/registry/`` holds real line slices of the station registry files (see
``fixtures/provenance.json``); the broken registries built in ``tmp_path`` are
synthetic and named so.
"""

from pathlib import Path

import pytest

from snowlight.weights import markets, registered

FIXTURES = Path(__file__).parent / "fixtures"
REGISTRY = FIXTURES / "registry"


def _crosswalk() -> markets.DmaCounties:
    return markets.read_crosswalk(
        FIXTURES / "usa-tvdma-county.csv",
        markets.read_gazetteer(FIXTURES / "2025_Gaz_counties_national.zip"),
        markets.read_ct_regions(FIXTURES / "ct_cou_to_cousub_crosswalk.xlsx"),
    )


def test_read_registry() -> None:
    stations = registered.read_registry(REGISTRY)
    assert [station.id for station in stations] == [
        "gray-kdlt",
        "gray-kktv",
        "gray-kold",
        "gray-wfsb",
        "gray-wlbt",
        "gray-wtva",
        "nexstar-wjtv",
        "nexstar-wpri",
        "nexstar-wtnh",
        "scripps-kktv",
    ]
    by_id = {station.id: station for station in stations}
    wpri = by_id["nexstar-wpri"]
    assert wpri.platform == "nexstar"
    assert wpri.call_sign == "WPRI"
    assert wpri.status == "active"
    assert wpri.dma == "Providence, RI - New Bedford, MA DMA"
    assert wpri.basis == "dma"
    assert wpri.fips == ("25005", "44001", "44003", "44005", "44007", "44009")
    # Unquoted codes with an 8 or 9 read as strings in YAML 1.1, as the registry relies on.
    assert by_id["gray-kktv"].fips[0] == "08009"
    kdlt = by_id["gray-kdlt"]
    assert (kdlt.basis, kdlt.fips, kdlt.status) == (None, (), "no_endpoint")


def test_by_call_sign_puts_gray_first() -> None:
    grouped = registered.by_call_sign(registered.read_registry(REGISTRY))
    assert [station.id for station in grouped["KKTV"]] == ["gray-kktv", "scripps-kktv"]
    assert [station.id for station in grouped["WJTV"]] == ["nexstar-wjtv"]
    assert list(grouped) == sorted(grouped)


def test_market_agreement() -> None:
    check = registered.market_agreement(registered.read_registry(REGISTRY), _crosswalk())
    assert isinstance(check, dict)
    # KDLT has no county list; the markets of KKTV, KOLD and WTVA are not in the slice.
    assert check["stations_with_dma_county_lists"] == 9
    assert check["agreeing"] == 5
    differing = check["differing"]
    assert isinstance(differing, list)
    rows = {str(row["station"]): row for row in differing if isinstance(row, dict)}
    assert sorted(rows) == ["gray-kktv", "gray-kold", "gray-wtva", "scripps-kktv"]
    kktv = rows["gray-kktv"]
    assert kktv["in_crosswalk"] is False
    assert kktv["registry_counties"] == 12
    assert kktv["market_counties"] == 0
    assert kktv["only_in_market"] == []


def test_market_disagreement_is_reported(tmp_path: Path) -> None:
    """A copy of the real Nexstar slice with one Providence county dropped (synthetic)."""
    folder = tmp_path / "synthetic-registry"
    folder.mkdir()
    text = (REGISTRY / "nexstar.yaml").read_text(encoding="utf-8")
    assert "'25005', " in text
    (folder / "nexstar.yaml").write_text(text.replace("'25005', ", "", 1), encoding="utf-8")
    check = registered.market_agreement(registered.read_registry(folder), _crosswalk())
    assert isinstance(check, dict)
    assert check["agreeing"] == 2
    assert check["differing"] == [
        {
            "station": "nexstar-wpri",
            "dma": "Providence, RI - New Bedford, MA DMA",
            "in_crosswalk": True,
            "registry_counties": 5,
            "market_counties": 6,
            "only_in_registry": [],
            "only_in_market": ["25005"],
        }
    ]


def _write(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return folder


STATION = """platform:
  id: demo
stations:
- id: demo-wxyz
  platform: demo
  call_sign: WXYZ
  status: active
  dma: null
  counties: {counties}
"""


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[1, 2]", "not a mapping"),
        ("stations: []", "no platform block"),
        ("platform: {id: demo}\nstations: {}", "stations is not a list"),
        ("platform: {id: demo}\nstations: [1]", "a station entry is not a mapping"),
        ("platform: {id: ''}\nstations: []", "id is not a non-empty string"),
        ("platform: {id: demo}\nstations: [{id: x, platform: other}]", "in the demo file"),
        ("platform: {id: demo}\nstations: [{id: x, platform: demo}]", "call_sign"),
        (STATION.format(counties="[]"), "neither null nor a mapping"),
        (STATION.format(counties="{basis: dma, fips: '44007'}"), "fips is not a list"),
        (STATION.format(counties="{basis: dma, fips: [01001]}"), "513 is not five digits"),
        (STATION.format(counties="{basis: dma, fips: ['4400']}"), "'4400' is not five digits"),
        (STATION.replace("dma: null", "dma: 7").format(counties="null"), "dma is not a string"),
        ("platform: [unclosed", "demo.yaml"),
    ],
)
def test_registry_errors(tmp_path: Path, text: str, message: str) -> None:
    """Synthetic registry files, each broken in one way."""
    folder = _write(tmp_path / "synthetic-registry", "demo.yaml", text)
    with pytest.raises(registered.RegistryReadError, match=message):
        registered.read_registry(folder)


def test_registry_folder_errors(tmp_path: Path) -> None:
    with pytest.raises(registered.RegistryReadError, match="no registry files"):
        registered.read_registry(tmp_path / "missing")
    folder = _write(tmp_path / "synthetic-registry", "a.yaml", STATION.format(counties="null"))
    _write(folder, "b.yaml", STATION.format(counties="null"))
    with pytest.raises(registered.RegistryReadError, match="'demo-wxyz' is used twice"):
        registered.read_registry(folder)
    (folder / "b.yaml").write_bytes(b"\xff\xfe")
    with pytest.raises(registered.RegistryReadError, match=r"b\.yaml"):
        registered.read_registry(folder)

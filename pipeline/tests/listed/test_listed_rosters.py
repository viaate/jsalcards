"""Reading the published rosters: FlashAlert participants, WRAL organizations, CBS6 SchoolWatch.

The bodies in ``fixtures/rosters`` are real slices of the rosters read on
2026-09-28 (``fixtures/PROVENANCE.json``). The HTTP layer is replaced by a
SYNTHETIC transport that serves those bodies, so the fetch path runs offline.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.listed import rosters
from snowlight.listed.scope import Context
from snowlight.sources.stations.http import ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.registry import PlatformFile, Registry

FIXTURES = Path(__file__).parent / "fixtures" / "rosters"
CONFIG = Path(__file__).resolve().parents[2] / "config" / "sources"


def _registry() -> Registry:
    """The committed FlashAlert, WRAL and Sinclair registry files."""
    files = {}
    for name in ("flashalert", "wral", "sinclair"):
        data = yaml.safe_load((CONFIG / f"{name}.yaml").read_text(encoding="utf-8"))
        files[name] = PlatformFile.model_validate_json(json.dumps(data, default=_iso))
    return Registry(files)


def _iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


@pytest.fixture(scope="module")
def registry() -> Registry:
    return _registry()


def test_flashalert_participants_keep_their_categories() -> None:
    found = rosters.parse_flashalert((FIXTURES / "flashalert-seattle.xml").read_bytes())
    categories = [category for category, _name, _org in found]
    assert categories.count("King Co. School Districts") == 3
    assert ("Colleges & Universities", "Bates Technical College", "4205") in found
    schools = [f for f in found if rosters.flashalert_school_category(f[0])]
    assert {category for category, _n, _o in schools} == {
        "King Co. School Districts",
        "Seattle-area Privates, Charters, Childcares",
    }


@pytest.mark.parametrize(
    ("category", "school"),
    [
        ("Multnomah Co. Schools", True),
        ("King Co. School Districts", True),
        ("Private & Charter Schools - Portland area", True),
        ("Seattle-area Privates, Charters, Childcares", True),
        ("Colleges & Universities - Private", False),
        ("Head Start/Early Childhood Centers", False),
        ("Churches/Synagogues", False),
        ("Businesses", False),
    ],
)
def test_flashalert_school_categories(category: str, *, school: bool) -> None:
    assert rosters.flashalert_school_category(category) is school


def test_flashalert_refuses_other_bodies() -> None:
    with pytest.raises(rosters.RosterFormatError, match="not XML"):
        rosters.parse_flashalert(b"<flashnews>")
    with pytest.raises(rosters.RosterFormatError, match="root element"):
        rosters.parse_flashalert(b"<other/>")
    with pytest.raises(rosters.RosterFormatError, match="no participants"):
        rosters.parse_flashalert(b"<flashnews/>")
    with pytest.raises(rosters.RosterFormatError, match="entities"):
        rosters.parse_flashalert(b'<!ENTITY a "b"><flashnews/>')


def test_flashalert_regions_come_from_the_registry(registry: Registry) -> None:
    regions = rosters.flashalert_regions(registry)
    assert regions["flashalert-portland"] == 1
    assert regions["flashalert-seattle"] == 12
    assert rosters.flashalert_url(12).endswith("flashnews_xml2.php?RegionID=12")


def test_wral_organizations() -> None:
    page = rosters.parse_wral((FIXTURES / "wral-organizations.json").read_bytes())
    assert page.total == len(page.organizations) == 10
    assert ("10005", "Wake Christian Academy", "P", "Wake") in page.organizations
    nameless = [org for org in page.organizations if not org[1]]
    assert len(nameless) == 1
    with pytest.raises(rosters.RosterFormatError, match="not JSON"):
        rosters.parse_wral(b"{")
    with pytest.raises(rosters.RosterFormatError, match="total"):
        rosters.parse_wral(b"{}")
    with pytest.raises(rosters.RosterFormatError, match="organizations"):
        rosters.parse_wral(b'{"total":1,"page":1,"pageSize":1}')
    with pytest.raises(rosters.RosterFormatError, match="orgCode"):
        rosters.parse_wral(b'{"total":1,"page":1,"pageSize":1,"organizations":[{"name":"x"}]}')


def test_cbs6_index_and_county_pages() -> None:
    counties = rosters.parse_cbs6_index((FIXTURES / "cbs6-index.html").read_bytes())
    assert [(c.key, c.county, c.state) for c in counties] == [
        ("AlbanyNY", "Albany", "NY"),
        ("BenningtonVT", "Bennington", "VT"),
        ("FairfieldCT", "Fairfield", "CT"),
    ]
    albany = rosters.parse_cbs6_county((FIXTURES / "cbs6-albanyny.html").read_bytes(), counties[0])
    assert albany[:3] == [
        "4 Seasons Auto Driving School",
        "AAA Hudson Valley (Driving Classes)",
        "Abounding Grace Christian Church",
    ]
    assert "Academy of the Holy Names" in albany
    fairfield = (FIXTURES / "cbs6-fairfieldct.html").read_bytes()
    assert rosters.parse_cbs6_county(fairfield, counties[2]) == []
    with pytest.raises(rosters.RosterFormatError, match="Fairfield"):
        rosters.parse_cbs6_county(fairfield, counties[0])
    with pytest.raises(rosters.RosterFormatError, match="no participating list"):
        rosters.parse_cbs6_county(b"<html>closed today</html>", counties[0])
    with pytest.raises(rosters.RosterFormatError, match="links no county"):
        rosters.parse_cbs6_index(b"<html></html>")


def test_cbs6_pages_are_matched_in_their_own_state() -> None:
    counties = rosters.parse_cbs6_index((FIXTURES / "cbs6-index.html").read_bytes())
    # SYNTHETIC county lookup: Albany and Bennington place, Connecticut's county does not.
    contexts = rosters.cbs6_contexts(
        counties, {("NY", "albany"): "36001", ("VT", "bennington"): "50003"}
    )
    assert contexts["NY"] == Context("sinclair-wrgb", ("NY",), ("36001",))
    assert contexts["VT"] == Context("sinclair-wrgb", ("VT",), ("50003",))
    assert contexts["CT"] == Context("sinclair-wrgb", ("CT",), None)


def _transport() -> httpx.MockTransport:
    """A SYNTHETIC server answering with the real roster slices."""
    bodies = {
        "wral": (FIXTURES / "wral-organizations.json").read_bytes(),
        "flashnews": (FIXTURES / "flashalert-seattle.xml").read_bytes(),
        "Default.asp": (FIXTURES / "cbs6-index.html").read_bytes(),
        "AlbanyNY": (FIXTURES / "cbs6-albanyny.html").read_bytes(),
        "BenningtonVT": (FIXTURES / "cbs6-benningtonvt.html").read_bytes(),
        "FairfieldCT": (FIXTURES / "cbs6-fairfieldct.html").read_bytes(),
    }

    def answer(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(404)
        for key in ("AlbanyNY", "BenningtonVT", "FairfieldCT", "wral", "flashnews", "Default.asp"):
            if key in url:
                return httpx.Response(200, content=bodies[key])
        return httpx.Response(404)

    return httpx.MockTransport(answer)


def _client(store: Path) -> PoliteClient:
    return PoliteClient(
        httpx.Client(transport=_transport()),
        ConditionalStore(store),
        host_interval=0.0,
        timing=Timing(sleep=lambda _seconds: None),
    )


def test_fetch_keeps_every_body_and_reads_the_entries(tmp_path: Path, registry: Registry) -> None:
    cache = tmp_path / "rosters"
    reads = rosters.fetch_rosters(_client(tmp_path / "http"), registry, cache)
    flash = [r for r in reads if r.station_id.startswith("flashalert-")]
    assert len(flash) == len(rosters.flashalert_regions(registry))
    assert [r.part for r in reads if r.station_id == rosters.WRAL_STATION] == ["page=1"]
    assert [r.part for r in reads if r.station_id == rosters.CBS6_STATION] == [
        "index",
        "AlbanyNY",
        "BenningtonVT",
        "FairfieldCT",
    ]
    assert all(read.robots and read.robots[0]["state"] == "unavailable" for read in reads)
    assert rosters.cached_reads_intact(reads, cache)
    written = tmp_path / "rosters.json"
    rosters.write_rosters(written, reads, "snowlight-pipeline/test")
    again = rosters.load_rosters(written)
    assert again == reads
    places = {("NY", "albany"): "36001", ("VT", "bennington"): "50003"}
    entries = rosters.read_entries(again, cache, registry, places)
    wral = [e for e in entries if e.station_id == rosters.WRAL_STATION]
    assert {e.category for e in wral} == {"S", "P"}
    assert all(e.name for e in wral)
    assert "Wake Christian Academy" in {e.name for e in wral}
    seattle = [e for e in entries if e.station_id == "flashalert-seattle"]
    assert len(seattle) == 6
    assert seattle[0].context.states == ("WA",)
    cbs6 = [e for e in entries if e.station_id == rosters.CBS6_STATION]
    assert "Arlington SD" in {e.name for e in cbs6}
    assert {e.context.states for e in cbs6} == {("NY",), ("VT",)}
    assert {e.roster for e in cbs6} == {"sinclair-wrgb/roster"}


def test_an_altered_body_is_refused(tmp_path: Path, registry: Registry) -> None:
    cache = tmp_path / "rosters"
    reads = rosters.fetch_rosters(_client(tmp_path / "http"), registry, cache)
    path = rosters.body_path(cache, reads[0].sha256)
    path.write_bytes(path.read_bytes() + b" ")
    assert not rosters.cached_reads_intact(reads, cache)
    with pytest.raises(rosters.RosterFormatError, match="SHA-256"):
        rosters.read_entries(reads, cache, registry, {})


def test_rosters_json_must_hold_reads(tmp_path: Path) -> None:
    path = tmp_path / "rosters.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(rosters.RosterFormatError, match="no reads"):
        rosters.load_rosters(path)
    with pytest.raises(rosters.RosterFormatError, match="robots or size"):
        rosters.RosterRead.from_json({"roster": "x"})
    with pytest.raises(rosters.RosterFormatError, match="'part'"):
        rosters.RosterRead.from_json({"roster": "x", "station_id": "y", "robots": [], "bytes": 1})

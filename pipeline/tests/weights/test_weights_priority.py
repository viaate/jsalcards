"""Scraper families, their markets and the greedy ranking.

Records come from ``fixtures/research/`` (whole records of the first-hand checks
and the ``sources.json`` stations they link to), markets from the real slice of
the DMA crosswalk, counties from the real slice of the 2025 Gazetteer (see
``fixtures/provenance.json``).
"""

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from snowlight.weights import build, notes, priority, registered

if TYPE_CHECKING:
    from pathlib import Path

    from weights.conftest import Kit


def _sources(kit: "Kit") -> dict[str, priority.Source]:
    return {s.name: s for s in priority.read_firsthand(kit.path("research/firsthand"))}


def _markets(kit: "Kit") -> build.Markets:
    pinned = hashlib.sha256(kit.bytes("usa-tvdma-county.csv")).hexdigest()
    return build.load_markets(kit.cache(), pinned)


def _classified(kit: "Kit") -> priority.Classification:
    markets = _markets(kit)
    anchors = priority.read_anchors(kit.path("research/sources.json"))
    resolver = priority.MarketResolver(markets.crosswalk.by_dma, anchors)
    return priority.classify(
        list(_sources(kit).values()),
        resolver,
        markets.crosswalk,
        markets.county_ids,
        markets.state_counties,
    )


def test_read_firsthand(kit: "Kit") -> None:
    sources = _sources(kit)
    assert len(sources) == 19
    wpri = sources["WPRI"]
    assert wpri.variant == "nexstar-wp-closings"
    assert wpri.states == ("RI", "MA")
    assert wpri.link == "wpri"
    assert wpri.file == "nexstar-tegna-scripps.json"
    assert not wpri.robots_blocked
    assert sources["WVEIS"].robots_blocked
    # An unreadable robots.txt is not a disallowing one.
    assert not sources["WVAH"].robots_blocked
    assert sources["RIBA"].link == "riba"


def test_read_firsthand_rejects_bad_files(tmp_path: "Path") -> None:
    """Synthetic files: a record without its fields, and a file that is not a list."""
    for name in priority.FIRSTHAND_FILES:
        (tmp_path / name).write_text("[]", encoding="utf-8")
    (tmp_path / "others.json").write_text('[{"source_id": "X"}]', encoding="utf-8")
    with pytest.raises(priority.PriorityError, match="lacks a documented field"):
        priority.read_firsthand(tmp_path)
    (tmp_path / "others.json").write_text("{}", encoding="utf-8")
    with pytest.raises(priority.PriorityError, match="not a list"):
        priority.read_firsthand(tmp_path)
    record: dict[str, object] = {
        "source_id": "X",
        "variant": "none-found",
        "group": "g",
        "market": "m",
    }
    (tmp_path / "others.json").write_text(json.dumps([record]), encoding="utf-8")
    with pytest.raises(priority.PriorityError, match="no state list"):
        priority.read_firsthand(tmp_path)
    record["states"] = ["RI"]
    (tmp_path / "others.json").write_text(json.dumps([record, record]), encoding="utf-8")
    with pytest.raises(priority.PriorityError, match="share a name"):
        priority.read_firsthand(tmp_path)


def test_family_of(kit: "Kit") -> None:
    sources = _sources(kit)
    family = {name: priority.family_of(source)[0] for name, source in sources.items()}
    assert family["WPRI"] == family["WTNH"] == family["KELO"] == "nexstar-wp"
    assert family["WPIX"] is None  # no closings page found
    assert family["WBBM"] == family["ECC"] == "ecc"  # the Emergency Closing Center's list
    assert family["KCNC"] == "cbs-feeds"  # CBS-owned, a NewsTicker export
    assert family["WBFF"] == "newsticker"  # Sinclair's external NewsTicker file
    assert family["WJAR"] == family["RIBA"] == family["WVEIS"] == "state-systems"
    assert family["KABC"] == "abc-owned"
    assert family["News 12 CT"] == "news12"
    assert family["NJ 101.5"] == "nj1015"
    assert family["Sonoma COE school closures"] == "rest"
    assert family["KBAK"] == "rest"  # frames the Kern County AlertLine
    assert family["KFXL"] is None  # its embed is broken
    assert family["WVAH"] is None  # nothing is known of a list
    _, why = priority.family_of(sources["WVEIS"])
    assert "robots.txt disallows" in why


def test_unknown_variant_is_an_error(kit: "Kit") -> None:
    source = replace(_sources(kit)["WPRI"], variant="something-new")
    with pytest.raises(priority.PriorityError, match="not classified"):
        priority.family_of(source)


def test_parse_label() -> None:
    assert priority.parse_label("Sioux Falls (Mitchell), SD - IA - MN - NE DMA") == (
        ["SIOUXFALLS", "MITCHELL"],
        ["SD", "IA", "MN", "NE"],
    )
    assert priority.parse_label("Hartford & New Haven, CT DMA") == (
        ["HARTFORD", "NEWHAVEN"],
        ["CT"],
    )
    assert priority.parse_label("Utica, NY DMA*")[0] == ["UTICA"]


def test_markets_are_found(kit: "Kit") -> None:
    classified = _classified(kit)
    assert classified.unresolved == []
    found = {item.source.name: item for item in classified.resolved}
    assert found["WPRI"].market.dmas == ("Providence, RI - New Bedford, MA DMA",)
    assert found["WPRI"].market.how == "market text"
    # "Hartford-New Haven" is read from the text; KELO names two markets.
    assert found["WTNH"].market.dmas == ("Hartford & New Haven, CT DMA",)
    assert found["KELO"].market.dmas == (
        "Rapid City, SD - MT - NE - WY DMA",
        "Sioux Falls (Mitchell), SD - IA - MN - NE DMA",
    )
    assert found["WJTV"].market.dmas == ("Jackson, MS DMA",)
    # Statewide and county systems.
    assert len(found["NJ 101.5"].counties) == 21
    assert found["Sonoma COE school closures"].counties == frozenset({"06097"})
    # News 12 Connecticut: the New York market's Connecticut counties only.
    assert all(fips.startswith("09") for fips in found["News 12 CT"].counties)
    # RIBA keeps the Providence market's Rhode Island and Massachusetts counties.
    assert found["RIBA"].counties == found["WPRI"].counties
    assert {item.source.name for item in classified.resolved}.isdisjoint({"WPIX", "KFXL"})
    left_out = {source.name: reason for source, reason in classified.left_out}
    assert left_out["WPIX"] == "no closings page found"


def test_market_from_anchors() -> None:
    """Synthetic labels and anchors, in the crosswalk's and sources.json's forms."""
    resolver = priority.MarketResolver(
        ["Harrisburg - Lancaster - Lebanon - York, PA DMA", "Portland, OR - WA DMA"],
        {"whp": [("Harrisburg", "PA")], "lost": [("Nowhere", "PA")]},
    )
    assert resolver.from_anchors("whp") == ["Harrisburg - Lancaster - Lebanon - York, PA DMA"]
    assert resolver.from_anchors("lost") == []
    assert resolver.from_text("Portland, OR", ["OR"]) == ["Portland, OR - WA DMA"]
    assert resolver.from_text("Portland", ["ME"]) == []


def test_market_counties_errors(kit: "Kit") -> None:
    markets = _markets(kit)
    source = _sources(kit)["WPRI"]
    for match, message in (
        (priority.MarketMatch(("Nowhere DMA",), "dma", "x"), "not in the crosswalk"),
        (priority.MarketMatch(("ZZ",), "statewide", "x"), "no counties for state"),
        (priority.MarketMatch(("RI|Atlantis",), "county", "x"), "not in the Gazetteer"),
    ):
        with pytest.raises(priority.PriorityError, match=message):
            priority.market_counties(
                match, source, markets.crosswalk, markets.county_ids, markets.state_counties
            )


def test_greedy_order() -> None:
    """Synthetic counties and weights: the order follows new weighted schools."""
    table = priority.SchoolWeights(
        schools={"a": 10, "b": 10, "c": 40, "d": 5},
        weighted={"a": 30.0, "b": 25.0, "c": 8.0, "d": 1.0},
    )
    families = {
        "snowy": frozenset({"a", "b"}),
        "big": frozenset({"c", "b"}),
        "covered": frozenset({"d"}),
    }
    steps = priority.greedy_order(families, frozenset({"d"}), table)
    assert [step.family for step in steps] == ["snowy", "big", "covered"]
    assert (steps[0].new_schools, steps[0].new_weighted) == (20, 55.0)
    assert (steps[1].new_counties, steps[1].new_weighted) == (1, 8.0)
    assert steps[2].new_counties == 0
    assert steps[-1].cumulative_schools == 65
    plain = {county: float(n) for county, n in table.schools.items()}
    by_schools = priority.SchoolWeights(table.schools, plain)
    assert priority.greedy_order(families, frozenset(), by_schools)[0].family == "big"


def test_baseline_counties(kit: "Kit") -> None:
    coverage = json.loads(kit.text("coverage.json"))
    working, listed = priority.baseline_counties(coverage)
    assert working == frozenset({"09110", "12045"})
    assert listed == working
    with pytest.raises(priority.PriorityError, match="no county table"):
        priority.baseline_counties({})
    assert priority.station_group("gray-wsfa") == "gray"


def test_baseline_is_gray_and_hearst_only(kit: "Kit") -> None:
    """The real coverage slice plus a synthetic working Nexstar source in Providence County."""
    coverage = json.loads(kit.text("coverage.json"))
    coverage["counties"]["44007"]["working"] = ["nexstar-wpri"]
    coverage["counties"]["44003"]["not_working"] = ["hearst-wcvb", 7]
    coverage["stations"] = {
        "nexstar-wpri": {"state": "working"},
        "gray-wsfa": {"state": "working"},
        "gray-wtva": {"state": "stale"},
        "odd": "not a record",
    }
    working, listed = priority.baseline_counties(coverage)
    assert working == frozenset({"09110", "12045"})
    assert listed == working | {"44003"}
    every, _ = priority.baseline_counties(coverage, groups=None)
    assert every == working | {"44007"}
    assert priority.working_stations(coverage) == {"gray": 1, "nexstar": 1}
    assert priority.working_stations({}) == {}


def test_last_updated() -> None:
    assert priority.last_updated("Last updated: 01/05/2021 3:00 PM") == "2021-01-05"
    assert priority.last_updated("no stamp") is None


def test_gray_cover(kit: "Kit") -> None:
    """Real records renamed as Gray-covered records (synthetic names and variants), looked up
    in the real registry slice (``fixtures/registry/``)."""
    sources = _sources(kit)
    moved = replace(sources["WPRI"], name="WTVA", variant="moved-to-gray")
    framed = replace(
        sources["WJTV"],
        name="KMSB",
        variant="gray-fusion-count",
        data_url="https://s3.amazonaws.com/grayfilestore-kold/closingsData/closings_KOLD.json",
    )
    twice = replace(sources["KELO"], name="KKTV", variant="gray-fusion-count")
    elsewhere = replace(sources["KBAK"], name="WJTV", variant="moved-to-gray")
    lost = replace(sources["WTNH"], name="WFFT", variant="moved-to-gray")
    stations = registered.by_call_sign(registered.read_registry(kit.path("registry")))
    left_out = [
        (moved, "now Gray"),
        (framed, "Gray page"),
        (twice, "Gray page"),
        (elsewhere, "now Gray"),
        (lost, "now Gray"),
        (sources["WPIX"], "x"),
    ]
    checked = [c for c in priority.gray_cover(left_out, stations) if isinstance(c, dict)]
    assert [
        (c["name"], c["registry_station"], c["registry_platform"], c["found_by"]) for c in checked
    ] == [
        ("WTVA", "gray-wtva", "gray", "call sign"),
        ("KMSB", "gray-kold", "gray", "its Gray data file"),
        # KKTV is registered under Gray and Scripps: Gray's entry is the one checked.
        ("KKTV", "gray-kktv", "gray", "call sign"),
        # No Gray entry: the other platform's entry is reported as such.
        ("WJTV", "nexstar-wjtv", "nexstar", "call sign"),
        ("WFFT", None, None, None),
    ]
    wtva = checked[0]
    assert wtva["registry_status"] == "active"
    assert wtva["registry_counties"] == 19
    # gray-kold is registered without an endpoint; WJTV is not Gray's; WFFT is missing.
    assert checked[1]["registry_status"] == "no_endpoint"
    gaps = notes._gray_gap_lines(checked)
    assert gaps[1].startswith(
        "3 of these 5 have no active Gray entry in the registry (KMSB, WJTV, WFFT)"
    )
    assert notes._gray_gap_lines(checked[:1]) == []

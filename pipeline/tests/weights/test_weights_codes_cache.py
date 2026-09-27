"""The closure-type codes, the download cache layout and reuse of other builds' copies."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from snowlight.weights import archive, build, codes, zones
from snowlight.weights.cache import CacheLayoutError, WeightsCache, cache_path

if TYPE_CHECKING:
    from pathlib import Path

    from weights.conftest import Kit


def test_codes_and_weights() -> None:
    assert codes.weight_of("WS.W") == 1.0
    assert codes.weight_of("WW.Y") == 0.25
    assert codes.weight_of("FF.W") == 0.1
    assert codes.weight_of("EC.W") == codes.weight_of("WC.W") == 0.5
    assert codes.weight_of("HU.W") == 1.0
    assert codes.weight_of("TR.W") == 0.5
    with pytest.raises(KeyError):
        codes.weight_of("TO.W")
    # The instructions' list, and the three codes added to it.
    listed = {"WS.W", "BZ.W", "IS.W", "EC.W", "WC.W", "HU.W", "TR.W", "WW.Y", "FF.W"}
    assert listed == codes.LISTED_CODES
    assert {"LE.W", "LE.Y", "ZR.Y"} == codes.ADDED_CODES
    assert codes.SUBSETS["cold"] == {"EC.W", "WC.W"}
    assert codes.SUBSETS["listed_winter"] == {"WS.W", "BZ.W", "IS.W", "WW.Y"}
    assert codes.group_codes("tropical") == {"HU.W", "TR.W"}
    assert ("W", "S") not in codes.code_pairs()
    assert codes.code_pairs()[0] == ("BZ", "W")
    ws = codes.BY_CODE["WS.W"]
    assert (ws.phenomena, ws.significance) == ("WS", "W")


def test_cache_layout(tmp_path: "Path") -> None:
    url = "https://www.weather.gov/source/gis/Shapefiles/County/bp16ap26.dbx?x=1"
    assert cache_path(tmp_path, url) == (
        tmp_path / "www.weather.gov" / "source" / "gis" / "Shapefiles" / "County" / "bp16ap26.dbx"
    )
    assert cache_path(tmp_path, url, suffix=".v2").name == "bp16ap26.dbx.v2"
    for bad in ("https://example.org/", "file:///etc/passwd", "https://a.org/x/../y"):
        with pytest.raises(CacheLayoutError):
            cache_path(tmp_path, bad)


def test_copy_in_a_sibling_cache_is_adopted(kit: "Kit", tmp_path: "Path") -> None:
    sibling = tmp_path / "weather-cache"
    url = zones.release_url("bp16ap26")
    first = WeightsCache(kit.http(), sibling, siblings=())
    first.fetch(url, cache_path(sibling, url))
    assert kit.server.hits[url] == 1
    own = tmp_path / "weights-cache"
    cache = WeightsCache(kit.http(), own, siblings=(sibling, own))
    assert cache.siblings == (sibling,)
    got = cache.fetch(url, cache_path(own, url))
    assert kit.server.hits[url] == 1  # not downloaded again
    assert cache.adopted == [url]
    assert got.path.read_bytes() == kit.bytes("bp16ap26.dbx")
    assert got.provenance.url == url
    # A copy whose bytes no longer match its recorded checksum is not adopted.
    other = zones.release_url("bp02ap19")
    WeightsCache(kit.http(), sibling, siblings=()).fetch(other, cache_path(sibling, other))
    cache_path(sibling, other).write_bytes(b"changed")
    fresh = WeightsCache(kit.http(), tmp_path / "third", siblings=(sibling,))
    fresh.fetch(other, cache_path(tmp_path / "third", other))
    assert fresh.adopted == []
    assert kit.server.hits[other] == 2


def test_provisional_school_year_stops_the_build(kit: "Kit", tmp_path: "Path") -> None:
    """A clock set inside the 2024-25 window: its file is still provisional."""
    kit.now = datetime(2025, 6, 20, tzinfo=UTC)
    paths = build.Paths(
        cache_dir=kit.cache_dir,
        out_dir=tmp_path / "out",
        directory=kit.path("schools.parquet"),
        coverage=kit.path("coverage.json"),
        research=kit.path("research"),
        siblings=(),
    )
    scope = build.Scope(
        years=(2024,), releases=kit.releases, county_release=kit.county_release(), day_windows=()
    )
    with pytest.raises(build.WeightsBuildError, match="provisional"):
        build.build(paths, scope=scope, clock=kit.clock, cache=kit.http())
    assert archive.load_year(kit.cache(), 2024).final is False

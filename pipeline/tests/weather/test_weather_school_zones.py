"""The directory build's school time zones, from the NWS boundary files served offline."""

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from snowlight.directory import zones as zones_module
from snowlight.directory.zones import ZoneError, nws_zone_lookup
from snowlight.sources.nws.boundaries import BoundaryCatalog
from snowlight.sources.nws.http import HttpCache
from weather.conftest import fixture_releases

if TYPE_CHECKING:
    from weather.conftest import Kit


@pytest.fixture
def served(kit: "Kit", monkeypatch: pytest.MonkeyPatch) -> "Kit":
    """The zone lookup reads the fixture server, with the fixture files' checksums."""

    def catalog(cache: HttpCache, cache_dir: Path) -> BoundaryCatalog:
        return BoundaryCatalog(cache, cache_dir, fixture_releases())

    monkeypatch.setattr(zones_module, "make_client", kit.server.client)
    monkeypatch.setattr(zones_module, "BoundaryCatalog", catalog)
    return kit


def test_the_lookup_reads_the_releases_in_effect_on_the_build_day(served: "Kit") -> None:
    kit = served
    lookup, releases = nws_zone_lookup(kit.cache_dir, date(2026, 9, 25))
    assert lookup.zones_for("35009", None, None) == ("America/Denver",)
    assert lookup.zones_for("09003", None, None) == ("America/New_York",)
    assert {kind: release["valid_from"] for kind, release in releases.items()} == {
        "county": "2026-04-16",
        "zone": "2026-04-16",
    }
    _lookup, older = nws_zone_lookup(kit.cache_dir, date(2025, 12, 1))
    assert older["county"]["valid_from"] == "2025-03-18"


def test_no_release_or_no_file_is_a_zone_error(kit: "Kit", monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(zones_module, "make_client", kit.server.client)
    with pytest.raises(ZoneError, match="no NWS county and zone boundary release"):
        nws_zone_lookup(kit.cache_dir, date(2020, 1, 1))
    for url in list(kit.server.files):
        if url.endswith("c_16ap26.zip"):
            del kit.server.files[url]
    with pytest.raises(ZoneError, match="NWS boundary files"):
        nws_zone_lookup(kit.cache_dir / "empty", date(2026, 9, 25))

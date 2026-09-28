"""WUSA's county list: the Washington market plus the District, placed by the second DMA list.

This check needs TEGNA's registry file (``pipeline/config/sources/tegna.yaml``), so it
ships with the TEGNA adapter's part rather than with the framework's; the framework's
own test of the same rule runs on a synthetic registry
(``test_dma_supplement.py``).
"""

from snowlight.sources.stations import dma
from snowlight.sources.stations.cli import county_mismatches
from snowlight.sources.stations.registry import DEFAULT_REGISTRY_DIR, load_registry

WASHINGTON = "Washington, DC - MD - PA - VA - WV DMA"


def test_wusa_county_list_matches_with_the_placed_district() -> None:
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    wusa = registry.stations["tegna-wusa"]
    assert wusa.counties is not None
    assert "11001" in wusa.counties.fips
    assert "DC" in wusa.states
    assert "BritCrit/dma_county_zip" in wusa.counties.source
    market = tuple(fips for fips in wusa.counties.fips if fips != "11001")
    first = dma.DmaCounties(by_dma={WASHINGTON: market}, unmatched=())
    filled = dma.DmaCounties(
        by_dma={WASHINGTON: wusa.counties.fips},
        unmatched=(),
        supplemented=(("11001", WASHINGTON),),
    )
    # The first list alone: WUSA (and every other station) differs by the District.
    alone = [line for line in county_mismatches(registry, first) if "tegna-wusa" in line]
    assert alone == ["tegna-wusa: 41 listed, 40 in market"]
    # With the placed county allowed, WUSA's list matches.
    assert not [line for line in county_mismatches(registry, first, filled) if "wusa" in line]

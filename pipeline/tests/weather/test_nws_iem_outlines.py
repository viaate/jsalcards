"""Evidence, on real rows, for how far IEM's simplified outlines can be from the true boundary.

``iem-2025-01-21.zip`` holds rows as the archive reader requests them
(``simple=1``); ``iem-full-2025-01-21.zip`` holds the same rows from the same
request with ``simple=0`` (IEM's full-resolution boundaries). See
:data:`snowlight.sources.nws.iem.SIMPLIFIED_TOLERANCE`.
"""

import math
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry.base import BaseGeometry

from snowlight.sources.nws.iem import (
    SIMPLIFIED_GRID,
    SIMPLIFIED_TOLERANCE,
    ArchiveRow,
    on_simplified_grid,
    read_day_file,
)
from snowlight.sources.nws.shapefile import Polygonal, polygonal, read_zip

FIXTURES = Path(__file__).parent / "fixtures"
HALF_DIAGONAL = SIMPLIFIED_GRID * math.sqrt(2) / 2
UGCS = ("LAZ077", "LAZ078", "TXZ231", "TXZ313")


def _key(row: ArchiveRow) -> tuple[object, ...]:
    return (row.event_key, row.ugc, row.status, row.issued, row.expired, row.product_id)


def _pairs() -> list[tuple[str, Polygonal, Polygonal]]:
    """(UGC, IEM's simplified outline, IEM's full-resolution boundary) for each fixture row."""
    simple = {_key(row): row for row in read_day_file(FIXTURES / "iem-2025-01-21.zip")}
    pairs = []
    for row in read_day_file(FIXTURES / "iem-full-2025-01-21.zip"):
        outline = simple[_key(row)].geometry
        assert outline is not None
        assert row.geometry is not None
        pairs.append((row.ugc or "", outline, row.geometry))
    return sorted(pairs, key=lambda pair: pair[0])


def _nws_zones() -> dict[str, Polygonal]:
    """The z_18mr25 zones of the fixture slice, as the boundary reader merges them."""
    parts: dict[str, list[Polygonal]] = {}
    for record in read_zip(FIXTURES / "z_18mr25.zip"):
        assert record.geometry is not None
        ugc = f"{record.attributes['STATE']}Z{record.attributes['ZONE']}"
        parts.setdefault(ugc, []).append(record.geometry)
    merged = {ugc: polygonal(shapely.union_all(pieces)) for ugc, pieces in parts.items()}
    return {ugc: geometry for ugc, geometry in merged.items() if geometry is not None}


def _farthest(points_of: Polygonal, target: Polygonal) -> float:
    """The largest distance from a point of ``points_of``'s boundary to ``target``'s boundary."""
    edge = shapely.segmentize(points_of.boundary, 0.0005)
    points = shapely.points(shapely.get_coordinates(edge))
    return float(np.max(shapely.distance(points, target.boundary)))


def _beyond_band(outline: Polygonal, full: Polygonal) -> BaseGeometry:
    """Where outline and boundary disagree, farther than the tolerance from the outline."""
    band = outline.boundary.buffer(SIMPLIFIED_TOLERANCE, quad_segs=64)
    return full.symmetric_difference(outline).difference(band)


def test_the_slices_pair_up() -> None:
    assert [ugc for ugc, _outline, _full in _pairs()] == list(UGCS)


@pytest.mark.parametrize(("ugc", "outline", "full"), _pairs(), ids=UGCS)
def test_every_outline_point_is_within_half_a_grid_diagonal_of_the_boundary(
    ugc: str, outline: Polygonal, full: Polygonal
) -> None:
    assert on_simplified_grid(outline), ugc
    assert not on_simplified_grid(full), ugc
    assert _farthest(outline, full) <= HALF_DIAGONAL + 1e-9


def test_parts_and_holes_narrower_than_the_grid_can_vanish() -> None:
    """The other direction does not hold: the outline drops parts and holes."""
    beyond = {ugc: _beyond_band(outline, full) for ugc, outline, full in _pairs()}
    outlines = {ugc: outline for ugc, outline, _full in _pairs()}
    # TXZ231 and LAZ077 lose slivers of the zone; LAZ078 loses a hole in it.
    assert beyond["TXZ231"].difference(outlines["TXZ231"]).area > 1e-5
    assert beyond["LAZ077"].difference(outlines["LAZ077"]).area > 1e-5
    assert beyond["LAZ078"].intersection(outlines["LAZ078"]).area > 1e-5
    assert all(_farthest(full, outline) > SIMPLIFIED_TOLERANCE for _u, outline, full in _pairs())


def test_the_nws_hint_settles_what_the_outline_dropped_where_the_zone_is_unchanged() -> None:
    zones = _nws_zones()
    for ugc, outline, full in _pairs():
        if ugc == "TXZ313":
            continue  # redrawn between that day's boundary and z_18mr25: see below
        hint = zones[ugc]
        wrong = _beyond_band(outline, full).intersection(full.symmetric_difference(hint))
        assert shapely.hausdorff_distance(full, hint) < 1e-3, ugc
        assert wrong.area < 1e-12, ugc


def test_a_zone_redrawn_between_releases_is_the_known_limit() -> None:
    """IEM's 2025-01-21 TXZ313 leaves out a thin strip that z_18mr25 includes.

    The strip is narrower than the grid, so the outline cannot show it, and the
    later NWS release has it inside the zone: a point there would be reported
    covered although that day's boundary excluded it. No school in the directory
    lies in it (every school was checked against IEM's full-resolution rows for
    that day).
    """
    zones = _nws_zones()
    [(outline, full)] = [(o, f) for ugc, o, f in _pairs() if ugc == "TXZ313"]
    hint = zones["TXZ313"]
    assert shapely.hausdorff_distance(full, hint) > 0.01
    wrong = _beyond_band(outline, full).intersection(full.symmetric_difference(hint))
    assert 5e-5 < wrong.area < 1e-4
    spot = wrong.representative_point()
    assert (round(spot.y, 2), round(spot.x, 2)) == (29.74, -95.10)
    assert outline.covers(spot)
    assert hint.covers(spot)
    assert not full.covers(spot)


def test_on_simplified_grid_needs_most_vertices_on_the_grid() -> None:
    square = shapely.box(0, 0, 0.02, 0.02)
    assert on_simplified_grid(square)
    assert not on_simplified_grid(shapely.box(0.001, 0, 0.02, 0.02))
    assert on_simplified_grid(shapely.box(0.001, 0, 0.02, 0.02), share=0.5)
    assert not on_simplified_grid(shapely.Polygon())

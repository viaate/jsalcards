"""The map renderer: projection, fill, bitmap text and the PNG encoder.

The squares and arrays drawn here are synthetic test shapes; the county map at the
end is drawn from the real county slice (``fixtures/c_16ap26.zip``).
"""

import struct
import zlib
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Polygon, box

from snowlight.weights import render, zones

FIXTURES = Path(__file__).parent / "fixtures"


def _chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    found, offset = [], 8
    while offset < len(data):
        (length,) = struct.unpack_from(">I", data, offset)
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        (crc,) = struct.unpack_from(">I", data, offset + 8 + length)
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF
        found.append((kind, body))
        offset += 12 + length
    return found


def _decode(data: bytes) -> np.ndarray:
    chunks = dict(_chunks(data))
    width, height, depth, color, _, _, _ = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    assert (depth, color) == (8, 2)
    raw = np.frombuffer(zlib.decompress(chunks[b"IDAT"]), dtype=np.uint8)
    rows = raw.reshape(height, 1 + width * 3)
    assert not rows[:, 0].any()  # every row unfiltered
    return rows[:, 1:].reshape(height, width, 3)


def test_albers_origin_and_symmetry() -> None:
    x, y = render.albers(np.array([-96.0, -86.0, -106.0]), np.array([37.5, 40.0, 40.0]))
    assert x[0] == pytest.approx(0.0, abs=1e-12)
    assert y[0] == pytest.approx(0.0, abs=1e-12)
    assert x[1] == pytest.approx(-x[2])
    assert y[1] == pytest.approx(y[2])
    assert y[1] > 0
    # Equal area: two one-degree cells at one latitude have the same projected area.
    east = render.project(box(-80, 40, -79, 41)).area
    west = render.project(box(-120, 40, -119, 41)).area
    assert east == pytest.approx(west, rel=1e-9)


def test_rasterize_fills_pixel_centres() -> None:
    shapes = {"a": box(0, 0, 10, 10), "b": box(10, 0, 20, 10)}
    image = render.rasterize(shapes, {"a": (255, 0, 0)}, width=60, background=(1, 2, 3))
    margin = render.MARGIN
    assert image.shape == (10 + 2 * margin, 60, 3)
    assert tuple(image[margin + 5, margin + 5]) == (255, 0, 0)
    assert tuple(image[margin + 5, margin + 15]) == render.NO_DATA
    assert tuple(image[0, 0]) == (1, 2, 3)
    red = (image == np.array([255, 0, 0], dtype=np.uint8)).all(axis=2)
    assert red.sum() == 100
    empty = render.rasterize({"a": box(0, 0, 10, 10), "z": Polygon()}, {}, width=60)
    assert empty.shape[1] == 60


def test_rasterize_errors() -> None:
    with pytest.raises(ValueError, match="nothing to draw"):
        render.rasterize({}, {})
    with pytest.raises(ValueError, match="nothing to draw"):
        render.rasterize({"a": Polygon()}, {})
    with pytest.raises(ValueError, match="no width"):
        render.rasterize({"a": box(1, 0, 1, 5)}, {})


def test_glyphs_are_five_by_seven() -> None:
    for char, glyph in render.GLYPHS.items():
        assert len(glyph) == render.GLYPH_ROWS, char
        for row in glyph:
            assert len(row) == render.GLYPH_COLUMNS, char
            assert set(row) <= {".", "#"}, char
    needed = "CLOSURE WEIGHT BY COUNTY, SCHOOL YEARS 2015-16 TO 2025-26 NATIONAL MEAN 0.25"
    assert set(needed) <= set(render.GLYPHS)


def test_draw_text() -> None:
    image = np.zeros((20, 40, 3), dtype=np.uint8)
    render.draw_text(image, "i", (1, 1), (9, 9, 9), scale=1)
    lit = np.argwhere(image[:, :, 0] == 9)
    expected = [
        (row + 1, column + 1)
        for row, cells in enumerate(render.GLYPHS["I"])
        for column, cell in enumerate(cells)
        if cell == "#"
    ]
    assert sorted(map(tuple, lit.tolist())) == sorted(expected)
    unknown = np.zeros((20, 40, 3), dtype=np.uint8)
    render.draw_text(unknown, "☃", (0, 0), (5, 5, 5), scale=1)
    assert unknown[:, :, 0].sum() == 5 * 20  # a hollow 5x7 box: 20 cells
    clipped = np.zeros((4, 4, 3), dtype=np.uint8)
    render.draw_text(clipped, "WW", (2, 2), (7, 7, 7))
    assert clipped.any()


def test_encode_png_round_trip() -> None:
    rng = np.random.default_rng(7)
    image = rng.integers(0, 256, size=(9, 13, 3), dtype=np.uint8)
    data = render.encode_png(image)
    assert [kind for kind, _ in _chunks(data)] == [b"IHDR", b"IDAT", b"IEND"]
    assert np.array_equal(_decode(data), image)
    with pytest.raises(ValueError, match="RGB uint8"):
        render.encode_png(np.zeros((2, 2), dtype=np.uint8))
    with pytest.raises(ValueError, match="RGB uint8"):
        render.encode_png(np.zeros((2, 2, 3), dtype=np.float64))
    with pytest.raises(ValueError, match="RGB uint8"):
        render.encode_png(np.zeros((2, 2, 4), dtype=np.uint8))


def test_color_bins() -> None:
    assert render.color_for(0.0) == render.BINS[0][1]
    assert render.color_for(0.24) == render.BINS[0][1]
    assert render.color_for(1.0) == render.BINS[4][1]
    assert render.color_for(9.0) == render.BINS[-1][1]


def test_render_weights_draws_the_county_slice() -> None:
    counties = zones.read_counties(FIXTURES / "c_16ap26.zip")
    weights = dict.fromkeys(counties.counties, 5.0)
    first = sorted(counties.counties)[0]
    del weights[first]
    image = _decode(render.render_weights(counties, weights, "TEST MAP"))
    assert image.shape[1] == render.WIDTH
    colors = {tuple(pixel) for pixel in image.reshape(-1, 3).tolist()}
    assert render.BINS[-1][1] in colors
    assert render.NO_DATA in colors
    assert render.TITLE in colors

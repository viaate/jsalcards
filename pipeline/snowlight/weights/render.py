"""The internal map of county closure weights (``closure-weights.png``), for a visual check.

The map is internal (a check for people working on the pipeline) and never
published. It is drawn here with nothing but numpy, shapely and the standard
library, so the package does not depend on another part of the pipeline:

* counties (NWS county outlines, lon/lat degrees) are projected with the USGS
  Albers equal-area conic for the conterminous United States (standard parallels
  29.5 and 45.5 N, origin 37.5 N 96 W, on the unit sphere): :func:`albers`;
* each county is filled by testing the centre of every pixel in its bounding box
  against its outline (:func:`shapely.contains_xy`), coloured by weight in the
  bins of :data:`BINS`, from near-black (no closure-type school day) to white:
  :func:`rasterize`;
* a title, a subtitle and the legend are drawn in a 5x7 bitmap font
  (:data:`GLYPHS`): :func:`draw_text`;
* the image is written as an 8-bit RGB PNG (no filtering, zlib level 9):
  :func:`encode_png`.
"""

import struct
import zlib
from collections.abc import Mapping

import numpy as np
import numpy.typing as npt
import shapely
from shapely.geometry.base import BaseGeometry

from snowlight.weights.zones import CountyList

type Rgb = tuple[int, int, int]
type Image = npt.NDArray[np.uint8]
type Floats = npt.NDArray[np.float64]

BACKGROUND: Rgb = (6, 7, 10)
NO_DATA: Rgb = (40, 40, 44)
TITLE: Rgb = (230, 230, 230)
SUBTITLE: Rgb = (180, 180, 180)
LEGEND_TEXT: Rgb = (200, 200, 200)
WIDTH = 1600
MARGIN = 20
HEADER_ROWS = 72
LEGEND_STEP = 22
BINS: tuple[tuple[float, Rgb], ...] = (
    (0.0, (18, 20, 28)),
    (0.25, (45, 38, 74)),
    (0.5, (88, 46, 110)),
    (0.75, (140, 54, 110)),
    (1.0, (196, 76, 86)),
    (1.5, (234, 118, 58)),
    (2.0, (250, 170, 60)),
    (3.0, (252, 222, 120)),
    (4.0, (255, 250, 220)),
)
"""(lower bound of the weight, colour): a county takes the last bin it reaches."""

STANDARD_PARALLELS = (29.5, 45.5)
ORIGIN = (-96.0, 37.5)
"""The projection's origin, (longitude, latitude)."""

GLYPH_ROWS = 7
GLYPH_COLUMNS = 5
_UNKNOWN = ("#####", "#...#", "#...#", "#...#", "#...#", "#...#", "#####")
GLYPHS: dict[str, tuple[str, ...]] = {
    " ": (".....",) * 7,
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": (".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
    ".": (".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    ",": (".....", ".....", ".....", ".....", ".##..", "..#..", ".#..."),
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    ":": (".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."),
    "/": (".....", "....#", "...#.", "..#..", ".#...", "#....", "....."),
    "%": ("##...", "##..#", "...#.", "..#..", ".#...", "#..##", "...##"),
    "(": ("...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."),
    ")": (".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."),
}
"""A 5x7 bitmap font: each glyph is seven rows of five cells, ``#`` drawn.

A character the font lacks is drawn as a hollow box, so a missing glyph shows."""


def albers(lon: Floats, lat: Floats) -> tuple[Floats, Floats]:
    """Project longitude/latitude degrees to Albers equal-area x, y on the unit sphere."""
    phi1, phi2 = np.radians(STANDARD_PARALLELS[0]), np.radians(STANDARD_PARALLELS[1])
    phi0, lam0 = np.radians(ORIGIN[1]), np.radians(ORIGIN[0])
    n = (np.sin(phi1) + np.sin(phi2)) / 2
    c = np.cos(phi1) ** 2 + 2 * n * np.sin(phi1)
    rho0 = np.sqrt(c - 2 * n * np.sin(phi0)) / n
    rho = np.sqrt(c - 2 * n * np.sin(np.radians(lat))) / n
    theta = n * (np.radians(lon) - lam0)
    return rho * np.sin(theta), rho0 - rho * np.cos(theta)


def project(geometry: BaseGeometry) -> BaseGeometry:
    """Return ``geometry`` (lon/lat degrees) in Albers coordinates."""

    def transform(coords: Floats) -> Floats:
        x, y = albers(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geometry, transform)


def rasterize(
    shapes: Mapping[str, BaseGeometry],
    colors: Mapping[str, Rgb],
    *,
    width: int = WIDTH,
    background: Rgb = BACKGROUND,
    default: Rgb = NO_DATA,
) -> Image:
    """Fill projected ``shapes`` (key to geometry) with ``colors`` (``default`` if absent).

    The drawing is scaled to ``width`` less a :data:`MARGIN` on each side; north is
    up. A pixel is a shape's when its centre lies inside it.

    Empty geometries are skipped.

    Raises:
        ValueError: nothing to draw, or the shapes have no width.
    """
    drawn = {key: geometry for key, geometry in shapes.items() if not geometry.is_empty}
    if not drawn:
        raise ValueError("nothing to draw")
    margin = MARGIN
    bounds = np.array([geometry.bounds for geometry in drawn.values()], dtype=np.float64)
    min_x, min_y = float(bounds[:, 0].min()), float(bounds[:, 1].min())
    max_x, max_y = float(bounds[:, 2].max()), float(bounds[:, 3].max())
    if max_x <= min_x:
        raise ValueError("the shapes have no width")
    scale = (width - 2 * margin) / (max_x - min_x)
    height = int(np.ceil((max_y - min_y) * scale)) + 2 * margin
    image: Image = np.full((height, width, 3), background, dtype=np.uint8)
    for key, geometry in drawn.items():
        left, bottom, right, top = geometry.bounds
        col0 = max(int((left - min_x) * scale) + margin - 1, 0)
        col1 = min(int((right - min_x) * scale) + margin + 2, width)
        row0 = max(int((max_y - top) * scale) + margin - 1, 0)
        row1 = min(int((max_y - bottom) * scale) + margin + 2, height)
        if col1 <= col0 or row1 <= row0:
            continue
        xs = min_x + (np.arange(col0, col1) + 0.5 - margin) / scale
        ys = max_y - (np.arange(row0, row1) + 0.5 - margin) / scale
        grid_x, grid_y = np.meshgrid(xs, ys)
        inside = shapely.contains_xy(geometry, grid_x, grid_y)
        image[row0:row1, col0:col1][inside] = colors.get(key, default)
    return image


def draw_text(image: Image, text: str, at: tuple[int, int], color: Rgb, scale: int = 2) -> None:
    """Draw ``text`` (upper-cased) with its top left corner at ``at`` (x, y).

    Each glyph cell is ``scale`` pixels square, and glyphs advance six cells.
    Pixels outside the image are clipped.
    """
    x, y = at
    height, width = image.shape[:2]
    for index, char in enumerate(text.upper()):
        glyph = GLYPHS.get(char, _UNKNOWN)
        left0 = x + index * (GLYPH_COLUMNS + 1) * scale
        for row, cells in enumerate(glyph):
            for column, cell in enumerate(cells):
                if cell != "#":
                    continue
                top, left = y + row * scale, left0 + column * scale
                if 0 <= top < height and 0 <= left < width:
                    image[top : top + scale, left : left + scale] = color


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def encode_png(image: Image) -> bytes:
    """Encode an RGB ``uint8`` image (rows, columns, 3) as PNG bytes.

    Raises:
        ValueError: the array is not an RGB ``uint8`` image.
    """
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:  # noqa: PLR2004
        raise ValueError("expected an RGB uint8 image")
    height, width = image.shape[:2]
    rows = np.zeros((height, 1 + width * 3), dtype=np.uint8)  # filter byte 0: none
    rows[:, 1:] = image.reshape(height, width * 3)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(rows.tobytes(), 9))
        + _chunk(b"IEND", b"")
    )


def color_for(weight: float) -> Rgb:
    """Return the bin colour for ``weight`` (0 gets the first bin)."""
    chosen = BINS[0][1]
    for lower, color in BINS:
        if weight >= lower:
            chosen = color
    return chosen


def _label(index: int) -> str:
    lower = BINS[index][0]
    if index + 1 < len(BINS):
        return f"{lower:g} TO {BINS[index + 1][0]:g}"
    return f"{lower:g} OR MORE"


def render_weights(counties: CountyList, weights: Mapping[str, float], title: str) -> bytes:
    """Return the PNG of county ``weights`` over the NWS county outlines."""
    shapes = {fips: project(county.geometry) for fips, county in counties.counties.items()}
    colors = {fips: color_for(weight) for fips, weight in weights.items()}
    drawn = rasterize(shapes, colors)
    header: Image = np.full((HEADER_ROWS, drawn.shape[1], 3), BACKGROUND, dtype=np.uint8)
    image: Image = np.vstack([header, drawn])
    draw_text(image, title, (24, 20), TITLE)
    draw_text(image, "SCHOOL-WEIGHTED NATIONAL MEAN WEIGHT IS 1", (24, 44), SUBTITLE)
    top = image.shape[0] - len(BINS) * LEGEND_STEP - 16
    for offset, (_, color) in enumerate(BINS):
        row = top + offset * LEGEND_STEP
        image[row : row + 14, 24:38] = color
        draw_text(image, _label(offset), (48, row), LEGEND_TEXT)
    return encode_png(image)

"""A small, dependency-free county map renderer for the internal coverage image.

Counties are projected with the USGS Albers equal-area conic for the
conterminous United States (standard parallels 29.5 and 45.5 N, origin 37.5 N
96 W), rasterized by testing pixel centres against each county polygon inside
its bounding box (:func:`shapely.contains_xy`), and written as an 8-bit RGB PNG
with the standard library's zlib. The image is internal (a progress view for
people working on the pipeline); it is never published.
"""

import struct
import zlib
from collections.abc import Mapping

import numpy as np
import numpy.typing as npt
import shapely
from shapely.geometry.base import BaseGeometry

type Rgb = tuple[int, int, int]

MARGIN = 20

_LAT1, _LAT2, _LAT0, _LON0 = 29.5, 45.5, 37.5, -96.0


def albers(
    lon: npt.NDArray[np.float64], lat: npt.NDArray[np.float64]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Project degrees to Albers equal-area conic x, y (unit sphere)."""
    phi1, phi2, phi0 = np.radians([_LAT1, _LAT2, _LAT0])
    n = (np.sin(phi1) + np.sin(phi2)) / 2
    c = np.cos(phi1) ** 2 + 2 * n * np.sin(phi1)
    rho0 = np.sqrt(c - 2 * n * np.sin(phi0)) / n
    theta = n * np.radians(lon - _LON0)
    rho = np.sqrt(c - 2 * n * np.sin(np.radians(lat))) / n
    return rho * np.sin(theta), rho0 - rho * np.cos(theta)


def project(geometry: BaseGeometry) -> BaseGeometry:
    """Return ``geometry`` (lon/lat degrees) in Albers coordinates."""

    def transform(coords: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        x, y = albers(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geometry, transform)


def render(
    shapes: Mapping[str, BaseGeometry],
    colors: Mapping[str, Rgb],
    *,
    width: int = 1600,
    background: Rgb = (0, 0, 0),
    default: Rgb = (40, 40, 44),
) -> npt.NDArray[np.uint8]:
    """Rasterize projected ``shapes`` (key to geometry) filled with ``colors``."""
    if not shapes:
        raise ValueError("nothing to draw")
    margin = MARGIN
    bounds = np.array([geometry.bounds for geometry in shapes.values()])
    minx, miny = bounds[:, 0].min(), bounds[:, 1].min()
    maxx, maxy = bounds[:, 2].max(), bounds[:, 3].max()
    scale = (width - 2 * margin) / (maxx - minx)
    height = int(np.ceil((maxy - miny) * scale)) + 2 * margin
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[:, :] = background
    for key, geometry in shapes.items():
        gx0, gy0, gx1, gy1 = geometry.bounds
        col0 = max(int((gx0 - minx) * scale) + margin - 1, 0)
        col1 = min(int((gx1 - minx) * scale) + margin + 2, width)
        row0 = max(int((maxy - gy1) * scale) + margin - 1, 0)
        row1 = min(int((maxy - gy0) * scale) + margin + 2, height)
        if col1 <= col0 or row1 <= row0:
            continue
        cols = np.arange(col0, col1)
        rows = np.arange(row0, row1)
        xs = minx + (cols + 0.5 - margin) / scale
        ys = maxy - (rows + 0.5 - margin) / scale
        grid_x, grid_y = np.meshgrid(xs, ys)
        inside = shapely.contains_xy(geometry, grid_x, grid_y)
        if inside.any():
            block = image[row0:row1, col0:col1]
            block[inside] = colors.get(key, default)
    return image


def png_bytes(image: npt.NDArray[np.uint8]) -> bytes:
    """Encode an RGB image as PNG bytes."""
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:  # noqa: PLR2004
        raise ValueError("expected an RGB uint8 image")
    height, width, _ = image.shape
    raw = b"".join(b"\x00" + image[row].tobytes() for row in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


# A 5x7 bitmap font for the image's caption: each glyph is seven rows of five bits.
_FONT: dict[str, tuple[int, ...]] = {
    " ": (0, 0, 0, 0, 0, 0, 0),
    "A": (14, 17, 17, 31, 17, 17, 17),
    "B": (30, 17, 17, 30, 17, 17, 30),
    "C": (14, 17, 16, 16, 16, 17, 14),
    "D": (30, 17, 17, 17, 17, 17, 30),
    "E": (31, 16, 16, 30, 16, 16, 31),
    "F": (31, 16, 16, 30, 16, 16, 16),
    "G": (14, 17, 16, 23, 17, 17, 15),
    "H": (17, 17, 17, 31, 17, 17, 17),
    "I": (14, 4, 4, 4, 4, 4, 14),
    "J": (7, 2, 2, 2, 2, 18, 12),
    "K": (17, 18, 20, 24, 20, 18, 17),
    "L": (16, 16, 16, 16, 16, 16, 31),
    "M": (17, 27, 21, 21, 17, 17, 17),
    "N": (17, 17, 25, 21, 19, 17, 17),
    "O": (14, 17, 17, 17, 17, 17, 14),
    "P": (30, 17, 17, 30, 16, 16, 16),
    "Q": (14, 17, 17, 17, 21, 18, 13),
    "R": (30, 17, 17, 30, 20, 18, 17),
    "S": (15, 16, 16, 14, 1, 1, 30),
    "T": (31, 4, 4, 4, 4, 4, 4),
    "U": (17, 17, 17, 17, 17, 17, 14),
    "V": (17, 17, 17, 17, 17, 10, 4),
    "W": (17, 17, 17, 21, 21, 21, 10),
    "X": (17, 17, 10, 4, 10, 17, 17),
    "Y": (17, 17, 17, 10, 4, 4, 4),
    "Z": (31, 1, 2, 4, 8, 16, 31),
    "0": (14, 17, 19, 21, 25, 17, 14),
    "1": (4, 12, 4, 4, 4, 4, 14),
    "2": (14, 17, 1, 2, 4, 8, 31),
    "3": (31, 2, 4, 2, 1, 17, 14),
    "4": (2, 6, 10, 18, 31, 2, 2),
    "5": (31, 16, 30, 1, 1, 17, 14),
    "6": (6, 8, 16, 30, 17, 17, 14),
    "7": (31, 1, 2, 4, 8, 8, 8),
    "8": (14, 17, 17, 14, 17, 17, 14),
    "9": (14, 17, 17, 15, 1, 2, 12),
    ".": (0, 0, 0, 0, 0, 12, 12),
    ",": (0, 0, 0, 0, 12, 4, 8),
    ":": (0, 12, 12, 0, 12, 12, 0),
    "-": (0, 0, 0, 31, 0, 0, 0),
    "%": (24, 25, 2, 4, 8, 19, 3),
    "(": (2, 4, 8, 8, 8, 4, 2),
    ")": (8, 4, 2, 2, 2, 4, 8),
    "/": (0, 1, 2, 4, 8, 16, 0),
}


def draw_text(
    image: npt.NDArray[np.uint8], text: str, at: tuple[int, int], color: Rgb, scale: int = 2
) -> None:
    """Draw upper-case ``text`` with its top left at ``at`` (x, y) in the 5x7 font.

    Characters the font lacks are drawn as spaces.
    """
    x, y = at
    cursor = x
    for char in text.upper():
        glyph = _FONT.get(char, _FONT[" "])
        for row, bits in enumerate(glyph):
            for col in range(5):
                if bits & (1 << (4 - col)):
                    top, left = y + row * scale, cursor + col * scale
                    image[top : top + scale, left : left + scale] = color
        cursor += 6 * scale

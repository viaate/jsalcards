"""Heights from Terrarium terrain tiles (Mapzen's Terrain Tiles, on AWS Open Data).

A tile is a 256 by 256 PNG of web-mercator pixels whose red, green and blue bytes hold the
height in meters: ``R * 256 + G + B / 256 - 32768``. A point's height is read bilinearly
from the four pixel centers around it, inside its own tile (at the tile's edge the nearest
pixels are taken: one pixel is about 60 m at zoom 11).

The PNG reader here reads only what these tiles are (8-bit RGB or RGBA, not interlaced) with
the standard library and NumPy, and refuses anything else.
"""

import math
import struct
import zlib
from typing import Final

import numpy as np
import numpy.typing as npt

TILE: Final = 256
FEET_PER_METER: Final = 1 / 0.3048
_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_COLOR_CHANNELS: Final = {2: 3, 6: 4}
_PAETH: Final = 4


class TileError(ValueError):
    """The bytes are not a terrain tile this reader reads."""


def tile_of(lon: float, lat: float, zoom: int) -> tuple[int, int, float, float]:
    """The tile ``(x, y)`` holding a point at ``zoom``, and the point's pixel position in it
    (``0`` to ``256``, pixel centers at ``i + 0.5``)."""
    n = 2**zoom
    fx = (lon + 180.0) / 360.0 * n
    phi = math.radians(lat)
    fy = (1.0 - math.log(math.tan(phi) + 1.0 / math.cos(phi)) / math.pi) / 2.0 * n
    x = min(max(math.floor(fx), 0), n - 1)
    y = min(max(math.floor(fy), 0), n - 1)
    return x, y, (fx - x) * TILE, (fy - y) * TILE


def _chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    if not data.startswith(_SIGNATURE):
        raise TileError("not a PNG")
    found: list[tuple[bytes, bytes]] = []
    at = len(_SIGNATURE)
    while at + 8 <= len(data):
        (length,) = struct.unpack(">I", data[at : at + 4])
        kind = data[at + 4 : at + 8]
        body = data[at + 8 : at + 8 + length]
        if len(body) != length or at + 12 + length > len(data):
            raise TileError("a PNG chunk is cut short")
        (crc,) = struct.unpack(">I", data[at + 8 + length : at + 12 + length])
        if zlib.crc32(kind + body) != crc:
            raise TileError("a PNG chunk fails its CRC")
        found.append((kind, body))
        at += 12 + length
        if kind == b"IEND":
            return found
    raise TileError("a PNG with no end")


def _paeth_row(line: bytes, above: bytearray, bpp: int) -> bytearray:
    """One Paeth-filtered row, in plain integers (the hot loop of a tile)."""
    current = bytearray(line)
    for i in range(bpp):
        current[i] = (current[i] + above[i]) & 0xFF
    for i in range(bpp, len(current)):
        left = current[i - bpp]
        up = above[i]
        corner = above[i - bpp]
        pa = up - corner if up >= corner else corner - up
        pb = left - corner if left >= corner else corner - left
        total = left + up - corner - corner
        pc = total if total >= 0 else -total
        if pa <= pb and pa <= pc:
            guess = left
        elif pb <= pc:
            guess = up
        else:
            guess = corner
        current[i] = (current[i] + guess) & 0xFF
    return current


def _unfilter(raw: bytes, rows: int, stride: int, bpp: int) -> bytearray:
    """Undo the PNG row filters (none, sub, up, average, Paeth)."""
    out = bytearray()
    above = bytearray(stride)
    for r in range(rows):
        at = r * (stride + 1)
        kind = raw[at]
        line = raw[at + 1 : at + 1 + stride]
        if kind == 0:
            current = bytearray(line)
        elif kind == 1:
            current = bytearray(line)
            for i in range(bpp, stride):
                current[i] = (current[i] + current[i - bpp]) & 0xFF
        elif kind == 2:  # noqa: PLR2004 - up
            current = bytearray((a + b) & 0xFF for a, b in zip(line, above, strict=True))
        elif kind == 3:  # noqa: PLR2004 - average
            current = bytearray(line)
            for i in range(stride):
                left = current[i - bpp] if i >= bpp else 0
                current[i] = (current[i] + ((left + above[i]) >> 1)) & 0xFF
        elif kind == _PAETH:
            current = _paeth_row(line, above, bpp)
        else:
            raise TileError(f"an unknown PNG row filter {kind}")
        out += current
        above = current
    return out


def decode(data: bytes) -> npt.NDArray[np.float64]:
    """A terrain tile's heights in meters, (256, 256), row 0 at the north.

    Raises:
        TileError: the bytes are not an 8-bit, non-interlaced RGB(A) PNG of 256 by 256.
    """
    chunks = _chunks(data)
    if not chunks or chunks[0][0] != b"IHDR":
        raise TileError("a PNG with no header first")
    width, height, depth, color, _compression, _filter, interlace = struct.unpack(
        ">IIBBBBB", chunks[0][1]
    )
    channels = _COLOR_CHANNELS.get(color)
    if (width, height) != (TILE, TILE) or depth != 8 or channels is None or interlace:  # noqa: PLR2004
        raise TileError(f"not a terrain tile: {width}x{height}, depth {depth}, color {color}")
    try:
        raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    except zlib.error as error:
        raise TileError(f"the PNG data cannot be read: {error}") from error
    stride = width * channels
    if len(raw) != height * (stride + 1):
        raise TileError("the PNG data is not one tile")
    pixels = np.frombuffer(bytes(_unfilter(raw, height, stride, channels)), dtype=np.uint8)
    rgb = pixels.reshape(height, width, channels)[:, :, :3].astype(np.float64)
    return rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0 - 32768.0


def sample(meters: npt.NDArray[np.float64], px: float, py: float) -> float:
    """The height at pixel position ``(px, py)`` of a tile, read bilinearly between the four
    pixel centers around it (clamped to the tile)."""
    x = min(max(px - 0.5, 0.0), TILE - 1.0)
    y = min(max(py - 0.5, 0.0), TILE - 1.0)
    x0, y0 = min(int(x), TILE - 2), min(int(y), TILE - 2)
    dx, dy = x - x0, y - y0
    top = meters[y0, x0] * (1 - dx) + meters[y0, x0 + 1] * dx
    bottom = meters[y0 + 1, x0] * (1 - dx) + meters[y0 + 1, x0 + 1] * dx
    return float(top * (1 - dy) + bottom * dy)

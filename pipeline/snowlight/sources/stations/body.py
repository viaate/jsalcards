"""Undo a content encoding an archived body still carries.

A Wayback ``id_`` capture is replayed with the station's original
``Content-Encoding``, so a client that does not decode (the archive workflow reads
raw bytes, to checksum exactly what was sent) gets gzip or zlib data. Live
responses arrive already decoded by httpx. Adapters call :func:`decode` first,
so both kinds of body parse the same way.

Brotli is not in the standard library. Of the 17,575 archived bodies downloaded by
2026-10-05, the only brotli ones are a server's empty answer sent brotli-encoded, a
stream of one to three bytes (seven Finalsite ``page-pops`` answers captured in
2025 and 2026, ``3`` and ``c\\x00\\x03``, for a homepage with no page pop up);
none holds data. Live on 2026-10-05, Palm Beach's and Teton County's page pops
answered ``Content-Encoding: br`` with the one byte ``;``, the same empty stream.
:func:`empty_brotli` recognizes such a stream, so the reader of that answer can
read it as the empty answer it is.
"""

import gzip
import zlib

from snowlight.sources.stations.model import ShapeError

_GZIP = b"\x1f\x8b"


def decode(body: bytes) -> bytes:
    """Return ``body`` with a gzip (or zlib) wrapper removed, or unchanged."""
    if body[:2] == _GZIP:
        try:
            return gzip.decompress(body)
        except (OSError, EOFError) as error:
            raise ShapeError(f"gzip body does not decompress: {error}") from error
    if body[:1] == b"\x78" and len(body) > 2 and (body[0] * 256 + body[1]) % 31 == 0:  # noqa: PLR2004
        try:
            return zlib.decompress(body)
        except zlib.error:
            return body
    return body


_MAX_EMPTY_BROTLI = 16


class _Bits:
    """The bits of a byte string, least significant first (RFC 7932, section 2)."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.at = 0

    def read(self, count: int) -> int:
        value = 0
        for shift in range(count):
            byte, bit = divmod(self.at, 8)
            if byte >= len(self.data):
                raise EOFError
            value |= ((self.data[byte] >> bit) & 1) << shift
            self.at += 1
        return value

    def to_byte(self) -> int:
        """Skip to the next byte boundary; return the bits skipped."""
        return self.read(-self.at % 8)

    def left(self) -> int:
        """The whole bytes not yet read."""
        return len(self.data) - (self.at + 7) // 8


def _window(bits: _Bits) -> bool:
    """Read the stream's window size; False for one the format reserves."""
    return not (bits.read(1) and not bits.read(3) and bits.read(3) == 1)


def _metadata(bits: _Bits) -> bool:
    """Read a meta-block that holds no data (a metadata block); False for any other."""
    if bits.read(2) != 3 or bits.read(1):  # noqa: PLR2004
        return False  # a meta-block with data, or the reserved bit set
    skip_bytes = bits.read(2)
    skip = bits.read(8 * skip_bytes) + 1 if skip_bytes else 0
    if bits.to_byte() or bits.left() < skip:
        return False
    bits.at += 8 * skip
    return True


def empty_brotli(body: bytes) -> bool:
    """Whether ``body`` is a whole brotli stream that decodes to nothing (RFC 7932).

    Such a stream is a window size, then only metadata meta-blocks (which hold no
    data) and a last meta-block marked empty, with no bit left over. Only a body of
    at most 16 bytes is considered: a longer one is not an empty answer.
    """
    if not body or len(body) > _MAX_EMPTY_BROTLI:
        return False
    bits = _Bits(body)
    try:
        if not _window(bits):
            return False
        while True:
            last = bits.read(1)
            if last and bits.read(1):
                break  # ISLASTEMPTY: the stream ends here
            if not _metadata(bits):
                return False
            if last:
                break
        return not bits.to_byte() and not bits.left()
    except EOFError:
        return False

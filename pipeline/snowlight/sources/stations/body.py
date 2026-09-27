"""Undo a content encoding an archived body still carries.

A Wayback ``id_`` capture is replayed with the station's original
``Content-Encoding``, so a client that does not decode (the archive workflow reads
raw bytes, to checksum exactly what was sent) gets gzip or zlib data. Live
responses arrive already decoded by httpx. Adapters call :func:`decode` first,
so both kinds of body parse the same way.
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

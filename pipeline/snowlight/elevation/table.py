"""The school elevation table: every school's height in feet, by NCES id and point.

One gzip file (written with no time stamp, so the same table is the same bytes) holding one
JSON object:

* ``schema``: 1;
* ``source``: the terrain tiles read (``url`` template with ``{z}/{x}/{y}``, ``zoom``) and
  ``tiles_sha256``, the SHA-256 of every tile read (its ``z/x/y`` and its bytes' SHA-256, one
  line each, sorted), so a rebuild from other tile bytes is seen;
* ``schools`` and ``unknown``: how many rows, and how many with no height;
* ``rows``: ``[id, lon_e6, lat_e6, feet]`` sorted by id, ``feet`` a whole number or ``null``
  (its tile could not be read).

A row says the height of the school at that point only: a reader takes a school whose
deployed point differs as not known (:func:`heights_for`).
"""

import gzip
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

from snowlight.directory.points import Points

SCHEMA: Final = 1
_MAX_FEET: Final = 20_000
_MIN_FEET: Final = -1_000
_ROW: Final = 4


class TableError(ValueError):
    """The bytes are not an elevation table."""


@dataclass(frozen=True, slots=True)
class Row:
    """One school's height."""

    school: str
    lon_e6: int
    lat_e6: int
    feet: int | None


@dataclass(frozen=True, slots=True)
class Table:
    """An elevation table (see the module docstring)."""

    url: str
    zoom: int
    tiles_sha256: str
    rows: tuple[Row, ...]

    @property
    def unknown(self) -> int:
        """Rows with no height."""
        return sum(1 for row in self.rows if row.feet is None)

    def to_bytes(self) -> bytes:
        """The table's file: the same table is always the same bytes."""
        value = {
            "schema": SCHEMA,
            "source": {"url": self.url, "zoom": self.zoom, "tiles_sha256": self.tiles_sha256},
            "schools": len(self.rows),
            "unknown": self.unknown,
            "rows": [[row.school, row.lon_e6, row.lat_e6, row.feet] for row in self.rows],
        }
        text = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return gzip.compress(text, compresslevel=9, mtime=0)

    @classmethod
    def from_bytes(cls, data: bytes) -> "Table":
        """Read a table's file.

        Raises:
            TableError: it is not one, or its counts or rows do not agree.
        """
        try:
            value = json.loads(gzip.decompress(data))
        except (OSError, EOFError, ValueError) as error:
            raise TableError(f"not an elevation table: {type(error).__name__}") from error
        if not isinstance(value, dict) or value.get("schema") != SCHEMA:
            raise TableError("not an elevation table of schema 1")
        source = value.get("source")
        rows = value.get("rows")
        if not isinstance(source, dict) or not isinstance(rows, list):
            raise TableError("an elevation table needs its source and rows")
        url, zoom, tiles = source.get("url"), source.get("zoom"), source.get("tiles_sha256")
        if not isinstance(url, str) or not isinstance(zoom, int) or not isinstance(tiles, str):
            raise TableError("an elevation table's source is its url, zoom and tiles_sha256")
        made = tuple(_row(item) for item in rows)
        ids = [row.school for row in made]
        if ids != sorted(set(ids)):
            raise TableError("an elevation table's rows are sorted by id, one per school")
        table = cls(url, zoom, tiles, made)
        if value.get("schools") != len(made) or value.get("unknown") != table.unknown:
            raise TableError("an elevation table's counts disagree with its rows")
        return table


def _row(item: object) -> Row:
    if not isinstance(item, list) or len(item) != _ROW:
        raise TableError(f"an elevation row is [id, lon_e6, lat_e6, feet], not {item!r}")
    school, lon, lat, feet = item
    whole = (int,)
    if (
        not isinstance(school, str)
        or not school
        or not isinstance(lon, whole)
        or not isinstance(lat, whole)
        or isinstance(lon, bool)
        or isinstance(lat, bool)
        or not (feet is None or (isinstance(feet, int) and not isinstance(feet, bool)))
    ):
        raise TableError(f"an elevation row is [id, lon_e6, lat_e6, feet], not {item!r}")
    if feet is not None and not _MIN_FEET <= feet <= _MAX_FEET:
        raise TableError(f"an elevation of {feet} feet is out of range")
    return Row(school, lon, lat, feet)


def heights_for(
    table: Table, school_ids: Sequence[str] | None, points: Points
) -> npt.NDArray[np.float64]:
    """Feet per school position of a directory (NaN where not known): a school's row counts
    only at the very point the directory has for it."""
    found = np.full(len(points), np.nan, dtype=np.float64)
    if school_ids is None:
        return found
    by_id = {row.school: row for row in table.rows}
    lon = points.lon_e6.tolist()
    lat = points.lat_e6.tolist()
    for position, school in enumerate(school_ids):
        row = by_id.get(school)
        if (
            row is not None
            and row.feet is not None
            and row.lon_e6 == lon[position]
            and row.lat_e6 == lat[position]
        ):
            found[position] = float(row.feet)
    return found

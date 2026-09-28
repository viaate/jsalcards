"""CBS19 News (WCAV, Charlottesville; Lockwood Broadcast): the closings JSON its page reads.

The closings page (``https://www.cbs19news.com/weather/closings/``, a BLOX page)
reads ``https://wcavclosings.lockwoodbroadcast.com/data/closings.json`` with its
own script. Variant this adapter reads:

``lockwood-json``
    ``[{"record": [...], "num_closings": N, "run_date": "09-27-2026 at 01:50 am"}]``.
    The page's script (read 2026-09-27) shows each record as
    ``organization_name`` " - " ``status_name`` (and ", " ``status_name_2`` when
    present) under a ``category_name`` heading, so ``organization_name`` is the
    name and ``status_name`` (with ``status_name_2`` after ", " when present) the
    status; every other field goes in ``raw_extra`` under its own name. The
    ``run_date`` is each row's update text; ``num_closings`` is the declared count
    and must equal the records read. No records is the empty state (the page then
    says "There are no closings to report at this time.").

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

from collections.abc import Mapping

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.model import Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import extra_from, json_body, listing, row, text_field

VARIANT = "lockwood-json"
_ROW_KEYS = frozenset({"organization_name", "status_name", "status_name_2"})


def _record(item: object, updated: str | None) -> ParsedRow | None:
    if not isinstance(item, Mapping):
        raise ShapeError("a closings record is not an object")
    status = text_field(item, "status_name")
    if status is None:
        raise ShapeError(f"a closings record has no status_name (keys {sorted(item)[:12]})")
    second = text_field(item, "status_name_2")
    if second:
        status = f"{status}, {second}"
    extra = extra_from(item, _ROW_KEYS)
    if updated:
        extra["updated_scope"] = "page"
    return row(text_field(item, "organization_name") or "", status, updated, extra)


def parse(body: bytes) -> Listing:
    """Read WCAV's closings JSON."""
    data = json_body(body)
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise ShapeError("not a Lockwood closings file (one export object in a list)")
    export = data[0]
    records, count = export.get("record"), export.get("num_closings")
    if not isinstance(records, list) or isinstance(count, bool) or not isinstance(count, int):
        raise ShapeError("a Lockwood closings file without its record list and count")
    stamp = text_field(export, "run_date")
    rows: list[ParsedRow] = []
    skipped = 0
    for item in records:
        found = _record(item, stamp)
        if found is None:
            skipped += 1
        else:
            rows.append(found)
    return listing(VARIANT, rows, skipped=skipped, declared=count)


def slice_body(body: bytes) -> bytes:
    """The file is kept whole (decoded)."""
    parse(body)
    return decode(body)

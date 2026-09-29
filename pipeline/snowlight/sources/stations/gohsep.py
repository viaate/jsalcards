"""Louisiana GOHSEP: the parish school system closures layer (a state list of school systems).

The Governor's Office of Homeland Security and Emergency Preparedness keeps a
standing public ArcGIS feature layer, ``Parish_School_Closures_Public_View_Layer``
(owner ``Andy.Venuto_GOHSEP``, created 2025-05-19), that its "Parish Emergency
School Closures Dashboard" draws: one feature per parish and day, each parish's
public school system with its ``STATUS`` for that ``CLOSURE_DATE``. Before it,
GOHSEP made one layer per incident (``24_006_school_closures`` for the January
2024 winter storm, ``25_007_school_closures`` for January 2025's, and others);
this one stands between incidents. Read live on 2026-09-27: 640 features, the 64
parishes over ten date groups, 627 "Open", 11 "Closed", one "Early Dismissal" and
one "Planned Closure".

The layer is read through its query endpoint as JSON (``f=json``, every feature,
no geometry). Variant this adapter reads:

``gohsep-feature-query``
    An ArcGIS REST query answer: ``fields`` (the layer's fields, with ``STATUS``'s
    coded values) and ``features``, each with ``attributes`` ``OBJECTID``,
    ``GEOID`` (the parish's five-digit county FIPS code), ``NAME`` (the parish,
    "Acadia", "St. Tammany"), ``DATE_GROUP``, ``CLOSURE_DATE`` (epoch
    milliseconds: local midnight of the day the status is for) and ``STATUS``.

Each feature is one row: ``raw_name`` the parish ``NAME`` as written, ``raw_status``
the ``STATUS`` (blank when the feature has none), no ``raw_updated_text`` (the
answer does not say when a status was set), and ``raw_extra`` ``geoid``,
``objectid``, ``date_group``, ``closure_date_ms`` (verbatim) and ``closure_date``
(that instant as a Louisiana calendar date, ``YYYY-MM-DD``). An answer with no
features is an empty list. Anything else raises
:class:`~snowlight.sources.stations.model.ShapeError`: an ArcGIS ``error`` object,
a partial page (``exceededTransferLimit``), a feature without a parish code or
name, or a body that is not such an answer.

The list names parish school systems, not schools, so the registry entry is a
district-level source: its ``leaids`` are the 64 parish school systems' NCES
district IDs, and only their schools count as covered.
"""

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.gap_markup import make_listing, make_row
from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError

VARIANT = "gohsep-feature-query"
LOUISIANA = ZoneInfo("America/Chicago")
FIPS_LENGTH = 5
LOUISIANA_FIPS = "22"


def _answer(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(decode(body))
    except (ValueError, UnicodeDecodeError) as error:
        raise ShapeError(f"not a JSON answer: {error}") from error
    if not isinstance(data, dict):
        raise ShapeError("the answer is not a JSON object")
    if "error" in data:
        raise ShapeError(f"the layer answered an error: {str(data['error'])[:200]}")
    if data.get("exceededTransferLimit"):
        raise ShapeError("the layer answered a partial page (exceededTransferLimit)")
    if not isinstance(data.get("features"), list) or not isinstance(data.get("fields"), list):
        raise ShapeError("the answer has no fields and features: not a feature query")
    names = {field.get("name") for field in data["fields"] if isinstance(field, dict)}
    missing = {"GEOID", "NAME", "STATUS", "CLOSURE_DATE"} - names
    if missing:
        raise ShapeError(f"the layer lacks the fields {sorted(missing)}")
    return data


def _closure_date(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ShapeError(f"CLOSURE_DATE is not epoch milliseconds: {value!r}")
    return datetime.fromtimestamp(value / 1000, UTC).astimezone(LOUISIANA).date().isoformat()


def _row(attributes: dict[str, Any]) -> ParsedRow | None:
    geoid, name = attributes.get("GEOID"), attributes.get("NAME")
    if not (isinstance(geoid, str) and len(geoid) == FIPS_LENGTH and geoid.isdigit()):
        raise ShapeError(f"a feature has no parish code: {attributes!r}"[:300])
    if not geoid.startswith(LOUISIANA_FIPS):
        raise ShapeError(f"a feature's parish code {geoid} is not in Louisiana")
    if not isinstance(name, str):
        raise ShapeError(f"feature {geoid} has no parish name")
    status = attributes.get("STATUS")
    if status is not None and not isinstance(status, str):
        raise ShapeError(f"feature {geoid} has a status that is not text: {status!r}")
    moment = attributes.get("CLOSURE_DATE")
    extra: dict[str, JsonScalar] = {
        "geoid": geoid,
        "objectid": attributes.get("OBJECTID"),
        "date_group": attributes.get("DATE_GROUP"),
        "closure_date_ms": moment,
        "closure_date": _closure_date(moment),
    }
    return make_row(name, status or "", None, extra)


def parse(body: bytes) -> Listing:
    """Read one answer of the parish school closures layer's query endpoint."""
    data = _answer(body)
    rows: list[ParsedRow] = []
    skipped = 0
    for feature in data["features"]:
        attributes = feature.get("attributes") if isinstance(feature, dict) else None
        if not isinstance(attributes, dict):
            raise ShapeError("a feature has no attributes")
        row = _row(attributes)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return make_listing(VARIANT, rows, skipped=skipped)


def slice_body(body: bytes) -> bytes:
    """Keep an answer whole (a list file is never cut)."""
    return decode(body)

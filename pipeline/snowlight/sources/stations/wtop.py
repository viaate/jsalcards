"""WTOP's closings and delays (Washington, DC): a server-rendered page.

WTOP (Hubbard Broadcasting radio) publishes its Closings and Delays System at
``https://wtop.com/closings-and-delays/``. The page writes the list's data into
its own script, ``Site.closings_by_state = [...];`` beside the organization
categories (``Site.closings_categories``), and a template renders it by state.
Variant this adapter reads:

``wtop-page``
    With nothing listed ``closings_by_state`` is ``[]`` and the page says "There
    are no closings and delays to report at this time." (live on 2026-09-26 and
    2026-09-27): the empty state. With postings (storm-day captures of 2025-01-06
    and 2026-03-03) it is an object keyed by a state code ("VA", "MD", "DC", "WV";
    "FG" for the federal government; "XX" for organizations with no state), each
    ``{"name": "Virginia", "categories": {"Public Schools": [posting, ...], ...}}``.
    A posting is a WordPress post: ``status`` ("2 Hour Delay on Tuesday 3/3"),
    ``note``, ``start``, ``end``, ``dayofweek``, ``post_title`` ("<org>: 2 Hour
    Delay Tuesday"), ``post_modified_gmt`` and the organization, ``org``
    (``name``, ``city``, ``state``, ``zip``, ``category``, ...). A row's name is
    ``org.name``, its status ``status`` and its update text ``post_modified_gmt``
    (UTC, as the field says; ``raw_extra["updated_zone"]`` notes it); the state
    code and name, the category, the note, the dates, the title, the ids and the
    organization's address go in ``raw_extra``. A posting whose organization is
    WTOP's placeholder (``term_id`` "X", name "Unknown", titled "Unknown
    organization: ...") names no organization and is counted as a skipped row.

Anything else raises :class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
import re
from collections.abc import Mapping

from snowlight.sources.stations.model import JsonScalar, Listing, ParsedRow, ShapeError
from snowlight.sources.stations.regional import (
    collapse,
    document,
    html_text,
    listing,
    row,
    scalar,
    text_field,
)

VARIANT = "wtop-page"
EMPTY_SENTENCE = "There are no closings and delays to report at this time."
PLACEHOLDER_ORG = "X"
_DATA = re.compile(r"Site\.closings_by_state\s*=\s*")
_POSTING_KEPT = (
    "ID",
    "post_title",
    "note",
    "status_code",
    "start",
    "end",
    "dayofweek",
    "formated_date_start",
    "formated_date_end",
    "long_term_closing",
    "post_modified",
)
_ORG_KEPT = ("term_id", "category", "street_address", "city", "state", "zip", "website")
_ORG_READ = frozenset({"name", *_ORG_KEPT})


def _states(text: str) -> tuple[object, int]:
    found = _DATA.search(text)
    if found is None:
        raise ShapeError("not WTOP's closings page (no closings_by_state)")
    try:
        states, end = json.JSONDecoder().raw_decode(text, found.end())
    except ValueError as error:
        raise ShapeError(f"closings_by_state is not JSON: {error}") from error
    return states, end


def _posting(code: str, state: str, category: str, posting: object) -> ParsedRow | None:
    org = posting.get("org") if isinstance(posting, Mapping) else None
    if not isinstance(posting, Mapping) or not isinstance(org, Mapping):
        raise ShapeError(f"a WTOP posting in {code}/{category} has no organization")
    if "status" not in posting or "name" not in org:
        raise ShapeError(f"a WTOP posting's fields have not been seen before: {sorted(posting)}")
    if org.get("term_id") == PLACEHOLDER_ORG:
        return None
    extra: dict[str, JsonScalar] = {
        "state_code": code,
        "state_name": state,
        "category": category,
        "updated_zone": "UTC",
    }
    extra |= {key: scalar(posting[key]) for key in _POSTING_KEPT if key in posting}
    extra |= {f"org_{key}": scalar(org[key]) for key in _ORG_KEPT if key in org}
    return row(
        text_field(org, "name") or "",
        text_field(posting, "status") or "",
        text_field(posting, "post_modified_gmt"),
        extra,
    )


def _rows(states: Mapping[str, object]) -> tuple[list[ParsedRow], int]:
    rows: list[ParsedRow] = []
    skipped = 0
    for code, entry in states.items():
        groups = entry.get("categories") if isinstance(entry, Mapping) else None
        if not isinstance(entry, Mapping) or not isinstance(groups, Mapping):
            raise ShapeError(f"WTOP's state {code!r} is not a name with categories")
        state = collapse(str(entry.get("name") or ""))
        for category, postings in groups.items():
            if not isinstance(postings, list):
                raise ShapeError(f"WTOP's category {code}/{category} is not a list")
            for posting in postings:
                found = _posting(code, state, collapse(category), posting)
                if found is None:
                    skipped += 1
                else:
                    rows.append(found)
    return rows, skipped


def parse(body: bytes) -> Listing:
    """Read WTOP's closings page."""
    text = html_text(body)
    states, _end = _states(text)
    if isinstance(states, Mapping) and states:
        rows, skipped = _rows(states)
        if not rows and not skipped:
            raise ShapeError("WTOP's states hold no postings")
        return listing(VARIANT, rows, skipped=skipped)
    if states != []:
        raise ShapeError("closings_by_state is neither an empty list nor an object of states")
    if EMPTY_SENTENCE not in text:
        raise ShapeError("WTOP's closings page has an empty list but no no-closings sentence")
    return listing(VARIANT, [])


def _cut(posting: object) -> dict[str, object]:
    """Return a posting with only the fields the adapter reads."""
    if not isinstance(posting, Mapping) or not isinstance(posting.get("org"), Mapping):
        raise ShapeError("a WTOP posting has no organization")
    read = {"status", "post_modified_gmt", *_POSTING_KEPT}
    org: Mapping[str, object] = posting["org"]
    kept = {key: value for key, value in posting.items() if key in read}
    return kept | {"org": {key: value for key, value in org.items() if key in _ORG_READ}}


def _kept(states: Mapping[str, object]) -> dict[str, object]:
    """Return the states with each posting cut to the fields the adapter reads."""
    kept: dict[str, object] = {}
    for code, entry in states.items():
        groups = entry.get("categories") if isinstance(entry, Mapping) else None
        if not isinstance(entry, Mapping) or not isinstance(groups, Mapping):
            raise ShapeError(f"WTOP's state {code!r} is not a name with categories")
        categories = {
            category: [_cut(posting) for posting in postings]
            for category, postings in groups.items()
            if isinstance(postings, list)
        }
        kept[code] = {"name": entry.get("name"), "categories": categories}
    return kept


def slice_body(body: bytes) -> bytes:
    """Cut the page to its data line, each posting to the fields read (plus the empty sentence)."""
    found = parse(body)
    states, _end = _states(html_text(body))
    if not isinstance(states, Mapping) or not (found.rows or found.skipped_rows):
        return document(f"<p>{EMPTY_SENTENCE}</p><script>Site.closings_by_state = [];</script>")
    data = json.dumps(_kept(states), ensure_ascii=False)
    return document(f"<script>Site.closings_by_state = {data};</script>")

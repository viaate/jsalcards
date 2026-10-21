"""Where a published status came from: its source type, and one private line per status.

Every registry platform has a :class:`SourceType` (:data:`PLATFORM_TYPES`); a
platform without one fails the tests, so a new platform is classified before its
rows can light anything. The type is kept per status in the private provenance
lines and never published (spec D11).

A board platform (a state or county status board) can keep a stale layer up for
days, so a board row lights a day only when its own date field says that day
(:data:`BOARD_ROW_DATES`), or, on a board with no row date, when it carries a row
stamp from the last 18 hours (:mod:`snowlight.live.resolve`, guard G5).
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from snowlight.output import JSONValue


class SourceType(StrEnum):
    """What kind of list a source is."""

    BROADCASTER_LIST = "broadcaster_list"
    AGGREGATOR_LIST = "aggregator_list"
    STATE_BOARD = "state_board"
    COUNTY_OFFICE = "county_office"
    DISTRICT_SITE = "district_site"
    """Reserved: a district's own site or banner; its rows are not read in S8."""
    ADMIN = "admin"
    """The site's admin, by hand (accounts spec C): no registry platform has it."""


_BROADCASTERS: Final = (
    "abc-owned",
    "allen",
    "blox",
    "cbs-owned",
    "cowles",
    "cox",
    "fox-owned",
    "graham",
    "gray",
    "hearst",
    "heritage",
    "hubbard",
    "lockwood",
    "nbc-owned",
    "ncpr",
    "news12",
    "nexstar",
    "nexstar-typed",
    "npg",
    "npg-articles",
    "radio",
    "scripps",
    "scripps-typed",
    "sinclair",
    "spectrum",
    "tegna",
    "townsquare",
    "whdh",
    "wral",
    "wtop",
)
_AGGREGATORS: Final = ("ecc", "eventdelay", "flashalert", "riba", "weatherthreat")
_STATE_BOARDS: Final = ("alsde", "delaware", "gohsep", "wveis")
_COUNTY_OFFICES: Final = ("coesheet", "flathead", "hcoe", "santacruzcoe")
_DISTRICT_SITES: Final = (
    "apptegy",
    "apptegy-feed",
    "dadeschools",
    "district-homepage",
    "district-pages",
    "edlio",
    "finalsite",
    "nisd",
    "pasco",
    "schoolblocks",
    "sharpschool",
    "smartsites",
)

PLATFORM_TYPES: Final[Mapping[str, SourceType]] = {
    **dict.fromkeys(_BROADCASTERS, SourceType.BROADCASTER_LIST),
    **dict.fromkeys(_AGGREGATORS, SourceType.AGGREGATOR_LIST),
    **dict.fromkeys(_STATE_BOARDS, SourceType.STATE_BOARD),
    **dict.fromkeys(_COUNTY_OFFICES, SourceType.COUNTY_OFFICE),
    **dict.fromkeys(_DISTRICT_SITES, SourceType.DISTRICT_SITE),
}
"""Each registry platform's source type."""

BOARD_TYPES: Final = frozenset({SourceType.STATE_BOARD, SourceType.COUNTY_OFFICE})
"""The source types held to the board-date rule (G5)."""

BOARD_ROW_DATES: Final[Mapping[str, str]] = {"gohsep": "closure_date", "wveis": "day"}
"""For each board platform with one, the row field that holds the day the row is for."""


def source_type(platform: str) -> SourceType:
    """The source type of a registry platform.

    Raises:
        KeyError: the platform has not been classified.
    """
    return PLATFORM_TYPES[platform]


PROVENANCE_KEYS: Final = (
    "nces_id",
    "school",
    "day",
    "status",
    "reason",
    "source_type",
    "source_id",
    "row_key",
    "lo",
    "hi",
    "row_stamp",
    "f5_confidence",
    "f5_notes",
    "match_reason",
    "match_level",
    "target_level",
    "match_confidence",
    "derived_version",
    "generated_at",
    "present",
    "contributing",
    "announced_by",
)
"""The fields of one provenance line (spec 6.1): codes, ids and times, never raw text.

``match_level`` is the matcher's level for the row and ``target_level`` whether the
school is reached as itself (``school``) or through its district (``district``).
``derived_version`` is the version the winning row was derived under; ``present``
whether that row was still on its source's list; ``contributing`` every row that
said the same at the latest time, as ``[source_id, source_type, row_key]``; and
``announced_by`` the key of the row whose time shows as "Posted", if any."""


def provenance_line(fields: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """One provenance line, with exactly :data:`PROVENANCE_KEYS` (plus ``sources``).

    Raises:
        ValueError: a field is missing or not one of the keys.
    """
    allowed = {*PROVENANCE_KEYS, "sources"}
    missing = [key for key in PROVENANCE_KEYS if key not in fields]
    extra = sorted(set(fields) - allowed)
    if missing or extra:
        raise ValueError(f"provenance fields: missing {missing}, unknown {extra}")
    return dict(fields)

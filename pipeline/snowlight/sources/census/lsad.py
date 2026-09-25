"""The Census Bureau's Legal/Statistical Area Description (LSAD) code list.

The list is published as an HTML table at :data:`LSAD_URL` with the columns
"LSAD", "LSAD Description" and "Associated Geographic Entity". A description
such as ``city (suffix)`` means a place with that code has the word "city"
appended to its name in the Gazetteer ("Abbeville city"); code ``00`` has an
empty description and adds nothing. :func:`name_suffixes` turns the list into
the suffix to remove for each code, so search shows "Abbeville". The table's
"Associated Geographic Entity" column is not used to filter codes: it omits
"Incorporated Place" for some codes places do carry (``21`` borough, ``CG``),
and every trimmed name is checked to actually end with its suffix.
"""

from dataclasses import dataclass
from html.parser import HTMLParser

from snowlight.sources.census import CensusFormatError

LSAD_URL = "https://www.census.gov/library/reference/code-lists/legal-status-codes.html"
_HEADER = ["LSAD", "LSAD Description", "Associated Geographic Entity"]
_SUFFIX_MARK = " (suffix)"


@dataclass(frozen=True, slots=True)
class LsadCode:
    """One row of the LSAD code list."""

    code: str
    description: str
    entities: frozenset[str]


class _TableCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_lsad_codes(html: str) -> list[LsadCode]:
    """Parse the LSAD table on the code-list page.

    Raises:
        CensusFormatError: if the page has no table with the expected header.
    """
    collector = _TableCollector()
    collector.feed(html)
    collector.close()
    try:
        start = collector.rows.index(_HEADER) + 1
    except ValueError as exc:
        raise CensusFormatError("LSAD page: no table with the expected header") from exc
    codes: list[LsadCode] = []
    for row in collector.rows[start:]:
        if len(row) != len(_HEADER):
            break
        code, description, entities = row
        codes.append(
            LsadCode(
                code=code,
                description=description,
                entities=frozenset(e.strip() for e in entities.split(",") if e.strip()),
            )
        )
    if not codes:
        raise CensusFormatError("LSAD page: the code table is empty")
    return codes


def _suffix_of(description: str) -> str | None:
    if description == "":
        return ""
    if description.endswith(_SUFFIX_MARK):
        return description.removesuffix(_SUFFIX_MARK)
    return None


def name_suffixes(codes: list[LsadCode]) -> dict[str, str]:
    """Map each LSAD code to the suffix names with that code carry.

    A code is kept only when every row listing it describes the same suffix
    (or none, as for ``00``). Codes described as a prefix, as literal text or
    by conflicting rows are left out, so names carrying them are kept whole
    rather than trimmed by guesswork.
    """
    by_code: dict[str, set[str | None]] = {}
    for entry in codes:
        by_code.setdefault(entry.code, set()).add(_suffix_of(entry.description))
    return {
        code: suffix
        for code, found in by_code.items()
        if len(found) == 1 and (suffix := next(iter(found))) is not None
    }


def base_name(full_name: str, suffix: str) -> str | None:
    """Return ``full_name`` without its LSAD ``suffix``, or ``None`` if it lacks it.

    An empty suffix returns the name unchanged.
    """
    if suffix == "":
        return full_name
    tail = " " + suffix
    if full_name.endswith(tail) and len(full_name) > len(tail):
        return full_name[: -len(tail)]
    return None

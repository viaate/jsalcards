"""The school levels a school's grades make it, for a name that does not say its level.

NCES often leaves a school's level out of its name: Massachusetts's ``"Lincoln"``
is a K-5 school, Illinois's ``"Devonshire School"`` another, and a Catholic
parish's ``"ST JOSEPH SCHOOL"`` one of PK-8. A closings list names them
``"Lincoln Elementary"``, ``"Devonshire Elementary"``, ``"St. Joseph
Elementary"``. So the level word a listing says tells nothing against a record
whose name leaves it out; the record's grades (NCES's ``grade_low`` and
``grade_high``, or its ``level`` when they are missing) say whether it is of
that level.

Each level word has *core* grades, one of which a school of that level teaches,
and a *range* its grades stay within (:data:`LEVEL_GRADES`): an elementary
school teaches a grade from K to 4 and none past 8, so a PK-8 parish school is
one, a 6-8 school is not, and a K-12 school teaches the grades but more besides.
:func:`fit` reads a record's span against every level a listing says.
"""

from enum import Enum
from functools import lru_cache
from typing import Final

type Span = tuple[int, int]
"""A school's lowest and highest grade: prekindergarten ``-1``, kindergarten ``0``,
first grade ``1`` ... twelfth ``12``, and CCD's grade 13 ``13``."""

GRADE_CODES: Final[dict[str, int | None]] = {
    "PK": -1,
    "KG": 0,
    "TK": 0,
    "T1": 1,
    **{f"{grade:02d}": grade for grade in range(1, 14)},
    "UG": None,
    "AE": None,
}
"""NCES grade codes (CCD ``GSLO``/``GSHI``, PSS recoded) and the grade each is.

Transitional kindergarten (``TK``) is kindergarten and transitional first grade
(``T1``) first grade. Ungraded (``UG``) and adult education (``AE``) are no grade:
a span that ends in one is unknown."""

LEVEL_SPANS: Final[dict[str, Span]] = {
    "Elementary": (0, 5),
    "Primary": (0, 5),
    "Middle": (6, 8),
    "High": (9, 12),
    "Secondary": (9, 12),
    "Combined elementary and secondary": (0, 12),
}
"""The span of a school whose grades NCES does not give, by its NCES level.

CCD's ``Elementary`` (or ``Primary``), ``Middle`` and ``High``, and PSS's
``Elementary``, ``Secondary`` and ``Combined elementary and secondary``, each as a
typical school of the level teaches. CCD's ``Other`` and ``Not applicable`` say
nothing of the grades."""

LEVEL_GRADES: Final[dict[str, tuple[Span, Span]]] = {
    "prekindergarten": ((-1, -1), (-1, 1)),
    "kindergarten": ((0, 0), (-1, 1)),
    "primary": ((0, 2), (-1, 5)),
    "elementary": ((0, 4), (-1, 8)),
    "intermediate": ((4, 6), (2, 9)),
    "middle": ((6, 8), (4, 9)),
    "juniorhigh": ((7, 8), (5, 12)),
    "high": ((9, 12), (6, 13)),
}
"""Each level word's core grades and the range a school of that level stays within.

A school of the level teaches one of the core grades and none outside the range:
an elementary school a grade from K to 4 and none past 8 (K-5, PK-8, 3-5; NCES's
elementary schools begin by grade 3, and a 5-8 school is a middle school), a middle
school one from 6 to 8 and none under 4 or past 9 (6-8, 5-8, 7-9), a high school
one from 9 to 12 and none under 6 (9-12, 7-12, 6-12, a ninth-grade center).
``juniorhigh`` is also the junior-senior high school (``"Jr./Sr. High"``, 7-12).
The words are those of :data:`~snowlight.match.lexicon.LEVELS`."""


class Fit(Enum):
    """How a school's grades fit the levels a listing says (:func:`fit`)."""

    FITS = "fits"
    """Its grades are of every level said: a K-5 or PK-8 school for ``Elementary``."""
    SPANS = "spans"
    """It teaches grades of every level said, and grades well past them: a K-12
    school for ``Elementary`` or ``High``. The listing may mean it, but not surely."""
    PART = "part"
    """It teaches grades of some of the levels said, not all: a K-5 school for
    ``"Elementary and Middle"``."""
    APART = "apart"
    """It teaches no grade of any level said: a 6-8 school for ``Elementary``."""
    UNKNOWN = "unknown"
    """Its grades are not known."""


def grade(code: str | None) -> int | None:
    """The grade an NCES grade code is (:data:`GRADE_CODES`), or ``None`` for none or unknown."""
    if code is None:
        return None
    return GRADE_CODES.get(code.strip().upper())


def span_of(low: str | None, high: str | None, level: str | None = None) -> Span | None:
    """A school's span from its NCES grade codes, or failing them its NCES level.

    ``None`` when neither says: ungraded, a code this module does not know, a
    lowest grade above the highest, or a level such as ``Other``.
    """
    first, last = grade(low), grade(high)
    if first is not None and last is not None and first <= last:
        return (first, last)
    if level is None:
        return None
    return LEVEL_SPANS.get(level.strip())


@lru_cache(maxsize=4096)
def fit(levels: frozenset[str], span: Span | None) -> Fit:
    """How a school of grades ``span`` fits a listing that says the level words ``levels``.

    It fits when it teaches a core grade of every level said and none outside
    the range they cover together (:data:`LEVEL_GRADES`): a K-8 school fits
    ``"Elementary and Middle"``. A word this module does not know is taught by no
    span. Any school fits a listing that says no level.
    """
    if not levels:
        return Fit.FITS
    if span is None:
        return Fit.UNKNOWN
    low, high = span
    known = [LEVEL_GRADES[level] for level in levels if level in LEVEL_GRADES]
    touched = [low <= core_high and core_low <= high for (core_low, core_high), _range in known]
    if not any(touched):
        return Fit.APART
    if len(touched) < len(levels) or not all(touched):
        return Fit.PART
    lowest = min(bounds[0] for _core, bounds in known)
    highest = max(bounds[1] for _core, bounds in known)
    return Fit.FITS if lowest <= low and high <= highest else Fit.SPANS

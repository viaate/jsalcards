"""The elevations an NWS alert names for where it applies ("above 8,000 feet").

A winter alert for a mountain zone often applies only to part of it: "Winter Weather Advisory
in effect above 8,000 feet", "WHERE...Above 8,000 feet in the Sierra Nevada". The zone's
polygon reaches the valley towns under it as well, so the predict pass reads these lines and
counts a school as reached only within the band they name (:mod:`snowlight.predict.serve`).

A band phrase is ``above N feet`` (``elevations above N``, ``N feet and above``, ``N feet and
higher``), ``below N feet`` (``N feet and below``) or ``between N and M feet`` (``from N to M
feet``, ``N to M feet``); N may carry a thousands comma and ``ft`` stands for feet. Only the
numbers are kept, never the text.

Most band phrases in an alert do not say where it applies: they qualify an amount ("3 to 5
feet above 7000 feet", "higher amounts of 10 to 16 inches above 9,000 feet", "except 1 to 2
feet above 7000 feet"), a wind ("ridge gusts above 9000 feet"), or one of several areas
("Grand and Summit Counties below 9000 feet, South Park, Byers, and Limon"). So a band is
taken only from a statement of where the alert applies, and each is one band and nothing
else:

* an ``NWSheadline`` (or the ``headline``) that is the product's own line ("... IN EFFECT",
  "... REMAINS IN EFFECT", "... WILL EXPIRE") naming one band, as "... IN EFFECT UNTIL 5 PM
  ABOVE 8000 FEET", "... FOR ELEVATIONS ABOVE 7000 FEET" or "... ABOVE 4000 FT IN THE HIGH
  CASCADES": no area listed before the band beside another, nothing after it but when or the
  one area it lies in ("... ABOVE 5000 FEET IN JOSEPHINE COUNTY AND FOR SOUTH CENTRAL OREGON"
  ties the band to the first area alone, so it is no statement);
* a ``WHERE`` paragraph that is one band ("Elevations above 5000 feet"), one band over the
  areas it names ("Above 8,000 feet in the Sierra Nevada") or one area and its band ("Mono
  County above 7500 feet").

The ``WHAT`` paragraph is no statement: its weather and band ("Snow above 7000 feet. A rain
and snow mix around 6000 feet.") speak of the weather, not of where the alert applies.

No statement may carry an amount, a wind or a hedge ("inches", "accumulations", "gusts",
"heaviest", "locally", "mainly", "except", "as well as", ...). An alert has no elevation
limit when none of its statements names a band; when any part of its headlines or
description speaks of the lower ground in words ("lower elevations", "all elevations", "all
of", "valleys", "foothills", "lake level", "snow levels", "down to", "as low as", "lowering
to"); when any height they name outside a band phrase lies outside the stated bands ("around
6000 feet" beside "above 7000 feet"; "5 kft" always); or when any band phrase anywhere in
them reaches outside the bands its statements name ("4 to 8 inches between 3000 and 5000
feet" beside "above 5000 feet"). Several bands are one limit: a school is reached when it
lies in any of them. So a limit takes away only ground the alert says, in a statement of
where it applies, that it does not cover, and an alert worded any other way counts its whole
zone, as it did before heights were read. Amounts named for towns ("4 to 8 inches in
Truckee") are not judged: the statement of where the alert applies already names the band
those towns lie in or not.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

_MAX_FEET: Final = 20_000
"""No school in the states lies higher (and no band means one above it)."""


@dataclass(frozen=True, slots=True)
class Band:
    """Feet from ``low`` (``None``: from any height) up to ``high`` (``None``: to any)."""

    low: int | None
    high: int | None


@dataclass(frozen=True, slots=True)
class ElevationLimit:
    """Where an alert applies, by height: a school is reached when it lies in any band."""

    bands: tuple[Band, ...]

    def reaches(self, feet: npt.NDArray[np.float64], margin: float) -> npt.NDArray[np.bool_]:
        """Which of the schools at ``feet`` (NaN: not known) the alert reaches, with
        ``margin`` feet to spare on each side of every band. A school of unknown height is
        reached."""
        found = np.isnan(feet)
        known = ~found
        for band in self.bands:
            inside = known.copy()
            if band.low is not None:
                inside &= feet >= band.low - margin
            if band.high is not None:
                inside &= feet <= band.high + margin
            found |= inside
        return found

    def as_json(self) -> list[list[int | None]]:
        """The bands as ``[low, high]`` pairs, for the pass's state."""
        return [[band.low, band.high] for band in self.bands]

    @classmethod
    def from_json(cls, value: object) -> "ElevationLimit | None":
        """The limit :meth:`as_json` wrote (``None`` and an empty list: no limit).

        Raises:
            ValueError: the value is not a list of ``[low, high]`` pairs of whole feet.
        """
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError(f"an elevation limit is a list of bands, not {value!r}")
        bands: list[Band] = []
        for pair in value:
            if not isinstance(pair, list) or len(pair) != 2:  # noqa: PLR2004 - low and high
                raise ValueError(f"an elevation band is [low, high], not {pair!r}")
            low, high = pair
            for side in (low, high):
                if side is not None and (not isinstance(side, int) or isinstance(side, bool)):
                    raise ValueError(f"an elevation band's sides are whole feet, not {pair!r}")
            bands.append(Band(low, high))
        return cls(tuple(bands)) if bands else None


_NUMBER: Final = r"(\d{1,2},\d{3}|\d{3,5})"
_FEET: Final = r"(?:feet|foot|ft)\b"
_BAND_PATTERNS: Final = (
    # (pattern, which groups give the low and high side)
    (
        re.compile(rf"\bbetween\s+{_NUMBER}(?:\s*{_FEET})?\s+and\s+{_NUMBER}\s*{_FEET}", re.I),
        (1, 2),
    ),
    (
        re.compile(
            rf"\b(?:from\s+)?{_NUMBER}(?:\s*{_FEET})?\s*(?:to|-)\s*{_NUMBER}\s*{_FEET}", re.I
        ),
        (1, 2),
    ),
    (re.compile(rf"\b{_NUMBER}\s*{_FEET}\s+and\s+(?:above|higher|up)\b", re.I), (1, None)),
    (re.compile(rf"\b{_NUMBER}\s*{_FEET}\s+and\s+(?:below|lower|down)\b", re.I), (None, 1)),
    (re.compile(rf"\babove\s+{_NUMBER}\s*{_FEET}", re.I), (1, None)),
    (
        re.compile(rf"\belevations?\s+above\s+{_NUMBER}\b(?!\s*(?:inch|mph|percent|%))", re.I),
        (1, None),
    ),
    (re.compile(rf"\bbelow\s+{_NUMBER}\s*{_FEET}", re.I), (None, 1)),
)
"""Every band phrase, most specific first: a later pattern reads only text an earlier one
left."""
_LOWER_GROUND: Final = re.compile(
    r"\b(?:lower|all|valley|low|lowest)\s+elevations?\b|\bvalley\s+floors?\b|\bvalleys\b"
    r"|\bsnow\s+levels?\b|\bdown\s+to\b|\bthousand\s+feet\b|\ball\s+of\b"
    r"|\bas\s+low\s+as\b(?!\s+(?:-|minus\s+|negative\s+)?(?:\d|zero\b|single\b|the\s+teens\b))"
    r"|\blower(?:s|ed|ing)?\s+to\b|\bfoothills?\b|\blake\s+levels?\b",
    re.I,
)
"""Words that speak of the lower ground: an alert that holds any reaches its whole zone. "As
low as" a number is a height (read as one, below) or a wind chill ("wind chills as low as 10
above zero"), not words for the lower ground."""
_HEIGHT: Final = re.compile(
    rf"\b{_NUMBER}\s*-?\s*{_FEET}|\b{_NUMBER}\s*(?:'|\u2019)|\b\d{{1,2}}(?:\.\d)?\s*kft\b", re.I
)
"""A height named in any form. One outside a band phrase ("at 5950 ft", "around 6000 feet")
must lie in a stated band, or the alert names ground no band was read for."""
_PRODUCT_LINE: Final = re.compile(
    r"\b(?:warning|advisory|watch)\b.*\b(?:in\s+effect|remains|will\s+expire|expires)\b"
    r"|\b(?:in\s+effect|remains|will\s+expire|expires)\b.*\b(?:warning|advisory|watch)\b",
    re.I,
)
"""A headline that is the product's own line: it names the product and that it is in effect."""
_SECOND_AREA: Final = re.compile(
    r"(?:[,;&]|\band\b)\s*(?:and\s+)?(?:in|for|of|across|over|within|along|on|throughout|at"
    r"|outside|elsewhere)\b|\b(?:but|while|with|except|also)\b|\.\s+\S",
    re.I,
)
"""What, after a band, starts another area (or clause) that the band may not reach."""
_HEDGE: Final = re.compile(
    r"\b(?:inch(?:es)?|accumulations?|amounts?|totals?|gust\w*|mph|winds?|heaviest|highest"
    r"|greatest|higher\s+amounts|locally|except|mainly|mostly|primarily|generally|especially"
    r"|particularly|including|also|plus|ice|glaze|chance|percent|near|or)\b|%|\bas\s+well\s+as\b"
    r"|\balong\s+with\b|\bin\s+addition\b",
    re.I,
)
"""Words that make a band qualify an amount, a wind or part of the ground, not say where an
alert applies."""
_LISTS: Final = re.compile(r"\band\b|[,&;]|\.\s+\S", re.I)
"""What lists more than one area (or another sentence) before a band."""
_JOINS: Final = frozenset({"with", "of", "to", "from", "and", "or", "but", "while", "except"})
"""Words that, just before a band, tie it to something else than the alert's ground."""
_WHERE_AFTER: Final = re.compile(
    r"^(?:(?:in|of|across|over|for|within|along|on|throughout|at)\b[^.]*)?$", re.I
)
"""What may follow a band in a ``WHERE`` paragraph: nothing, or the areas it lies in."""
_HEADLINE_AFTER: Final = re.compile(
    r"^(?:(?:in|of|across|over|for|within|along|on|throughout|at|remains|will|until|from"
    r"|through|now|is|expires?)\b.*)?$",
    re.I,
)
"""What may follow a band in a headline: nothing, the areas it lies in, or when."""
_TRIM: Final = " .,;:-"
_PARAGRAPH: Final = re.compile(
    r"^\s*\*?\s*(WHAT|WHERE)\.\.\.(.*?)(?=^\s*\*?\s*[A-Z][A-Z ]*\.\.\.|\n\s*\n|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _feet(text: str) -> int:
    return int(text.replace(",", ""))


def _band(low: int | None, high: int | None) -> Band | None:
    if low is not None and high is not None and low > high:
        low, high = high, low
    if any(side is not None and not 0 < side <= _MAX_FEET for side in (low, high)):
        return None
    return Band(low, high)


@dataclass(frozen=True, slots=True)
class _Found:
    """One band phrase in a text: the band (``None``: out of range) and where it lies."""

    band: Band | None
    start: int
    end: int


def _bands(text: str) -> list[_Found]:
    """Every band phrase in ``text``, in order."""
    found: list[_Found] = []
    taken = [False] * len(text)
    for pattern, (low_group, high_group) in _BAND_PATTERNS:
        for match in pattern.finditer(text):
            if any(taken[match.start() : match.end()]):
                continue
            low = _feet(match.group(low_group)) if low_group is not None else None
            high = _feet(match.group(high_group)) if high_group is not None else None
            found.append(_Found(_band(low, high), match.start(), match.end()))
            taken[match.start() : match.end()] = [True] * (match.end() - match.start())
    return sorted(found, key=lambda item: item.start)


def _one(text: str) -> tuple[_Found, str, str] | None:
    """The one band of a statement with its text before and after, or ``None`` when it holds
    none, several, one out of range, or a hedge."""
    found = _bands(text)
    if len(found) != 1 or found[0].band is None or _HEDGE.search(text):
        return None
    only = found[0]
    return only, text[: only.start].strip(_TRIM + " "), text[only.end :].strip(_TRIM)


def _single(before: str) -> bool:
    """Whether the text before a band names at most one area (or the alert alone), and does
    not tie the band to something else."""
    words = before.split()
    return not _LISTS.search(before) and not (words and words[-1].lower() in _JOINS)


def headline_band(line: str) -> Band | None:
    """The band a headline says the alert applies within, or ``None`` (module docstring)."""
    if not _PRODUCT_LINE.search(line):
        return None
    found = _one(line)
    if found is None:
        return None
    band, before, after = found
    if not _single(before) or not _HEADLINE_AFTER.match(after) or _SECOND_AREA.search(after):
        return None
    return band.band


def where_band(paragraph: str) -> Band | None:
    """The band a ``WHERE`` paragraph says the alert applies within, or ``None``."""
    found = _one(paragraph)
    if found is None:
        return None
    band, before, after = found
    if before and (not _single(before) or after):
        return None
    if not _WHERE_AFTER.match(after) or _SECOND_AREA.search(after):
        return None
    return band.band


def paragraphs(description: str, name: str | None = None) -> list[str]:
    """The ``WHAT`` and ``WHERE`` paragraphs of an alert's description (only ``name``'s when
    given), in order."""
    return [
        match.group(2)
        for match in _PARAGRAPH.finditer(description.replace("\r", ""))
        if name is None or match.group(1) == name
    ]


def _plain(text: str) -> str:
    return " ".join(text.split())


def parse_alert_text(
    headlines: Sequence[str], headline: str | None, description: str | None
) -> ElevationLimit | None:
    """The elevation limit of one alert, from its ``NWSheadline`` lines, its ``headline`` and
    its ``description`` (see the module docstring), or ``None``: its whole zone."""
    lines = [_plain(line) for line in (*headlines, *([headline] if headline else []))]
    body = _plain(description.replace("\r", "")) if description else ""
    if _LOWER_GROUND.search(" ".join([*lines, body])):
        return None
    stated = [headline_band(line) for line in lines]
    if description:
        wheres = [_plain(item) for item in paragraphs(description, "WHERE")]
        stated += [where_band(item) for item in wheres]
    bands = {band for band in stated if band is not None}
    if not bands:
        return None
    for text in (*lines, body):
        found = _bands(text)
        for item in found:
            if item.band is None or not any(_within(item.band, band) for band in bands):
                return None
        for height in _HEIGHT.finditer(text):
            if any(item.start <= height.start() and height.end() <= item.end for item in found):
                continue
            point = _point(height)
            if point is None or not any(_within(point, band) for band in bands):
                return None
    ordered = sorted(bands, key=lambda band: (band.low or 0, band.high or _MAX_FEET + 1))
    return ElevationLimit(tuple(ordered))


def _point(height: re.Match[str]) -> Band | None:
    """A height named outside a band phrase as a band of that one height, or ``None`` when it
    is out of range or written in thousands of feet ("5 kft")."""
    if height.group(1) is not None:
        return _band(_feet(height.group(1)), _feet(height.group(1)))
    if height.group(2) is not None:
        return _band(_feet(height.group(2)), _feet(height.group(2)))
    return None


def _within(inner: Band, outer: Band) -> bool:
    """Whether every height of ``inner`` lies in ``outer``."""
    low_ok = outer.low is None or (inner.low is not None and inner.low >= outer.low)
    high_ok = outer.high is None or (inner.high is not None and inner.high <= outer.high)
    return low_ok and high_ok

"""The closure-type VTEC codes the weights count, and the weight each carries.

A school day counts for a county when at least one of these events covered it
(see :mod:`snowlight.weights.count`). The day's value is the largest weight among
the codes that covered it, so a day under a Winter Storm Warning and a Winter
Weather Advisory at once counts once, at 1.0.

The weights are the project's judgment, not a measurement: no official source
states how often each kind of warning closes schools. They encode the owner's
instruction to favor the places whose weather closes schools (2026-09-26: "favor
states that get more school closings on average, like Rhode Island, versus
something like Mississippi that will rarely ever get school off"):

* 1.0: warnings for weather that makes the morning trip dangerous across a whole
  area and is the classic cause of a snow day or a storm closure: Winter Storm
  (WS.W), Blizzard (BZ.W), Ice Storm (IS.W), Lake Effect Snow (LE.W) and
  Hurricane (HU.W) Warnings.
* 0.5: warnings that close schools in some districts but not most: Extreme Cold
  and Wind Chill Warnings (EC.W, WC.W; many districts close only past a set wind
  chill) and Tropical Storm Warnings (TR.W).
* 0.25: the Winter Weather Advisory (WW.Y): lighter snow or ice, more often a
  two-hour delay than a closure.
* 0.1: the Flash Flood Warning (FF.W): storm-based, usually hours long and
  covering part of a county, and rarely the reason for a closure.

Codes the NWS folded into these during the period are counted with the code
that absorbed them, so that a place is not measured differently before and
after the change:

* Wind Chill Warning (WC.W) was replaced by the Extreme Cold Warning (EC.W) in
  the 2024-25 season: the archive has WC.W rows through 2023-24 and none after,
  EC.W rows by the thousand from 2024-25 (a handful before), and the NWS event
  list (https://api.weather.gov/alerts/types) names "Extreme Cold Warning" and no
  longer "Wind Chill Warning". Both are counted, at the same weight.
* Freezing Rain Advisory (ZR.Y) and Lake Effect Snow Advisory (LE.Y) were folded
  into the Winter Weather Advisory (their last rows are in 2017-18 and 2016-17;
  the event list names neither); they are counted at WW.Y's weight.

The build checks these statements against the rows and the event list each time
it runs (``code_changes`` in ``manifest.json``, and the method note).

The Lake Effect Snow Warning (LE.W) is an addition to the list the owner's
instructions name. The NWS issues it instead of a Winter Storm Warning when the
snow is lake-effect, so leaving it out would miss the storms that close schools
around Buffalo, Erie, the Tug Hill and western Michigan. The method note reports
how much it changes each state.
"""

from dataclasses import dataclass
from typing import Literal

type Group = Literal["winter", "cold", "tropical", "flood"]


@dataclass(frozen=True, slots=True)
class ClosureCode:
    """One VTEC phenomena/significance pair and how it is weighed."""

    code: str
    """``PP.S``, e.g. ``WS.W``."""
    name: str
    group: Group
    weight: float
    note: str

    @property
    def phenomena(self) -> str:
        """The two-letter VTEC phenomena code."""
        return self.code[:2]

    @property
    def significance(self) -> str:
        """The one-letter VTEC significance code."""
        return self.code[3]


CODES: tuple[ClosureCode, ...] = (
    ClosureCode("WS.W", "Winter Storm Warning", "winter", 1.0, "listed; heavy snow or ice"),
    ClosureCode("BZ.W", "Blizzard Warning", "winter", 1.0, "listed; snow with high wind"),
    ClosureCode("IS.W", "Ice Storm Warning", "winter", 1.0, "listed; damaging ice accretion"),
    ClosureCode(
        "LE.W",
        "Lake Effect Snow Warning",
        "winter",
        1.0,
        "added: issued instead of WS.W for lake-effect snow",
    ),
    ClosureCode("WW.Y", "Winter Weather Advisory", "winter", 0.25, "listed; lower weight"),
    ClosureCode(
        "ZR.Y", "Freezing Rain Advisory", "winter", 0.25, "folded into WW.Y; WW.Y's weight"
    ),
    ClosureCode(
        "LE.Y", "Lake Effect Snow Advisory", "winter", 0.25, "folded into WW.Y; WW.Y's weight"
    ),
    ClosureCode("EC.W", "Extreme Cold Warning", "cold", 0.5, "listed; replaced WC.W in 2024-25"),
    ClosureCode("WC.W", "Wind Chill Warning", "cold", 0.5, "listed; retired in 2024-25"),
    ClosureCode("HU.W", "Hurricane Warning", "tropical", 1.0, "listed"),
    ClosureCode("TR.W", "Tropical Storm Warning", "tropical", 0.5, "listed"),
    ClosureCode("FF.W", "Flash Flood Warning", "flood", 0.1, "listed; lower weight"),
)

BY_CODE: dict[str, ClosureCode] = {code.code: code for code in CODES}
WINTER_CODES: frozenset[str] = frozenset(code.code for code in CODES if code.group == "winter")
LISTED_WINTER_CODES: frozenset[str] = frozenset({"WS.W", "BZ.W", "IS.W", "WW.Y"})
"""The winter codes the owner's instructions name (without the additions)."""
ADDED_CODES: frozenset[str] = frozenset({"LE.W", "LE.Y", "ZR.Y"})
"""Codes counted beyond the instructions' list (see the module docstring)."""
LISTED_CODES: frozenset[str] = frozenset(code.code for code in CODES) - ADDED_CODES
"""The codes the owner's instructions name (with WC.W, which EC.W replaced)."""


def group_codes(group: Group) -> frozenset[str]:
    """Return the codes of one hazard group."""
    return frozenset(code.code for code in CODES if code.group == group)


SUBSETS: dict[str, frozenset[str]] = {
    "winter": WINTER_CODES,
    "listed_winter": LISTED_WINTER_CODES,
    "listed": LISTED_CODES,
    "cold": group_codes("cold"),
    "tropical": group_codes("tropical"),
    "flood": group_codes("flood"),
}
"""Named code subsets whose weighted days are kept alongside the metric."""


def code_pairs() -> list[tuple[str, str]]:
    """Return the ``(phenomena, significance)`` pairs, sorted."""
    return sorted((code.phenomena, code.significance) for code in CODES)


def weight_of(code: str) -> float:
    """Return the weight of ``code`` (``PP.S``).

    Raises:
        KeyError: ``code`` is not a closure-type code.
    """
    return BY_CODE[code].weight

"""The explicit allowlist of NWS alert types that bear on school closures.

Everything not listed here is dropped: civil and law-enforcement messages, child
abduction and blue alerts, air quality and smoke, fire weather, marine, surf and
rip current products, frost and freeze, fog, dust, wind advisories, and every
"statement" (Special Weather Statement, Flood Statement, Severe Weather
Statement, Coastal Flood Statement, Tropical Cyclone Local Statement and the
like), which either repeat a warning that is listed or carry no hazard area of
their own.

Each entry pairs the NWS event name (as the api.weather.gov ``event`` field and
https://api.weather.gov/alerts/types spell it) with its VTEC phenomena and
significance codes (NWS Directive 10-1703), so the live feed and the VTEC
warning archive are filtered by one list. Types marked ``retired`` no longer
appear in https://api.weather.gov/alerts/types (the NWS replaced Wind Chill
products with Extreme Cold and Cold Weather ones, renamed Excessive Heat to
Extreme Heat, and folded Blizzard Watch, Freezing Rain Advisory and the Lake
Effect Snow Watch and Advisory into Winter Storm and Winter Weather products);
they stay listed so that past dates in the warning archive are covered.

Watches and advisories of the listed hazards are kept with their warnings (a
Winter Weather Advisory or a Flood Watch is often what closes or delays
schools). Two types go slightly beyond the plain names of those hazards and are
kept on purpose: Lakeshore Flood products (the Great Lakes counterpart of
Coastal Flood products) and the Extreme Wind Warning (issued for a hurricane's
eyewall winds).

``hazard`` groups the types for display (``winter``, ``cold``, ``flood``,
``tropical``, ``heat``, ``wind``, ``severe``) and ``level`` is ``warning``,
``watch`` or ``advisory``, from the VTEC significance (W, A, Y).
"""

from dataclasses import dataclass
from typing import Literal

type Hazard = Literal["winter", "cold", "flood", "tropical", "heat", "wind", "severe"]
type Level = Literal["warning", "watch", "advisory"]

_LEVELS: dict[str, Level] = {"W": "warning", "A": "watch", "Y": "advisory"}


@dataclass(frozen=True, slots=True)
class AlertType:
    """One allowlisted alert type."""

    event: str
    hazard: Hazard
    codes: tuple[tuple[str, str], ...]
    retired: bool = False

    @property
    def level(self) -> Level:
        """``warning``, ``watch`` or ``advisory``, from the VTEC significance."""
        return _LEVELS[self.codes[0][1]]


def _t(event: str, hazard: Hazard, *codes: str, retired: bool = False) -> AlertType:
    pairs = tuple((code[:2], code[3]) for code in codes)
    return AlertType(event, hazard, pairs, retired)


ALERT_TYPES: tuple[AlertType, ...] = (
    # Winter storms
    _t("Winter Storm Warning", "winter", "WS.W"),
    _t("Winter Storm Watch", "winter", "WS.A"),
    _t("Winter Weather Advisory", "winter", "WW.Y"),
    _t("Blizzard Warning", "winter", "BZ.W"),
    _t("Blizzard Watch", "winter", "BZ.A", retired=True),
    _t("Ice Storm Warning", "winter", "IS.W"),
    _t("Freezing Rain Advisory", "winter", "ZR.Y", retired=True),
    _t("Lake Effect Snow Warning", "winter", "LE.W"),
    _t("Lake Effect Snow Watch", "winter", "LE.A", retired=True),
    _t("Lake Effect Snow Advisory", "winter", "LE.Y", retired=True),
    # Cold
    _t("Extreme Cold Warning", "cold", "EC.W"),
    _t("Extreme Cold Watch", "cold", "EC.A"),
    _t("Cold Weather Advisory", "cold", "CW.Y"),
    _t("Wind Chill Warning", "cold", "WC.W", retired=True),
    _t("Wind Chill Watch", "cold", "WC.A", retired=True),
    _t("Wind Chill Advisory", "cold", "WC.Y", retired=True),
    # Floods (areal FA and river FL products share the Flood names)
    _t("Flood Warning", "flood", "FA.W", "FL.W"),
    _t("Flood Watch", "flood", "FA.A", "FL.A"),
    _t("Flood Advisory", "flood", "FA.Y", "FL.Y"),
    _t("Flash Flood Warning", "flood", "FF.W"),
    _t("Flash Flood Watch", "flood", "FF.A"),
    _t("Coastal Flood Warning", "flood", "CF.W"),
    _t("Coastal Flood Watch", "flood", "CF.A"),
    _t("Coastal Flood Advisory", "flood", "CF.Y"),
    _t("Lakeshore Flood Warning", "flood", "LS.W"),
    _t("Lakeshore Flood Watch", "flood", "LS.A"),
    _t("Lakeshore Flood Advisory", "flood", "LS.Y"),
    # Tropical cyclones
    _t("Hurricane Warning", "tropical", "HU.W"),
    _t("Hurricane Watch", "tropical", "HU.A"),
    _t("Tropical Storm Warning", "tropical", "TR.W"),
    _t("Tropical Storm Watch", "tropical", "TR.A"),
    _t("Storm Surge Warning", "tropical", "SS.W"),
    _t("Storm Surge Watch", "tropical", "SS.A"),
    _t("Extreme Wind Warning", "tropical", "EW.W"),
    # Heat
    _t("Extreme Heat Warning", "heat", "XH.W"),
    _t("Extreme Heat Watch", "heat", "XH.A"),
    _t("Excessive Heat Warning", "heat", "EH.W", retired=True),
    _t("Excessive Heat Watch", "heat", "EH.A", retired=True),
    _t("Heat Advisory", "heat", "HT.Y"),
    # Wind
    _t("High Wind Warning", "wind", "HW.W"),
    _t("High Wind Watch", "wind", "HW.A"),
    # Severe storms
    _t("Severe Thunderstorm Warning", "severe", "SV.W"),
    _t("Severe Thunderstorm Watch", "severe", "SV.A"),
    _t("Tornado Warning", "severe", "TO.W"),
    _t("Tornado Watch", "severe", "TO.A"),
)

BY_EVENT: dict[str, AlertType] = {kind.event: kind for kind in ALERT_TYPES}
BY_CODE: dict[tuple[str, str], AlertType] = {
    code: kind for kind in ALERT_TYPES for code in kind.codes
}

# The 48 contiguous states and the District of Columbia, by USPS code.
_CONUS_CODES = (
    "AL AZ AR CA CO CT DE DC FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY"
)
CONUS_STATES: frozenset[str] = frozenset(_CONUS_CODES.split())


def alert_type_for_event(event: str) -> AlertType | None:
    """Return the allowlisted type named ``event`` exactly, or ``None``."""
    return BY_EVENT.get(event)


def alert_type_for_code(phenomena: str, significance: str) -> AlertType | None:
    """Return the allowlisted type for a VTEC code such as ``("WS", "W")``, or ``None``."""
    return BY_CODE.get((phenomena, significance))

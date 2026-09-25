"""Valid Time Event Code (VTEC) strings, as defined in NWS Directive 10-1703.

A P-VTEC string looks like ``/O.NEW.KABQ.FF.W.0185.260924T2342Z-260925T0245Z/``:
product class, action, issuing office, phenomena, significance, event tracking
number, and the event's begin and end times in UTC. ``000000T0000Z`` means the
time is not given (an event already in effect, or one "until further notice").
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

_PVTEC = re.compile(
    r"^/(?P<cls>[OTEX])\.(?P<action>[A-Z]{3})\.(?P<office>[A-Z0-9]{4})\."
    r"(?P<phen>[A-Z0-9]{2})\.(?P<sig>[A-Z])\.(?P<etn>\d{4})\."
    r"(?P<begin>\d{6}T\d{4}Z)-(?P<end>\d{6}T\d{4}Z)/$"
)
_UNSET = "000000T0000Z"


class VtecError(ValueError):
    """A string is not a P-VTEC string."""


@dataclass(frozen=True, slots=True)
class Vtec:
    """One parsed P-VTEC string."""

    product_class: str
    action: str
    office: str
    phenomena: str
    significance: str
    etn: int
    begin: datetime | None
    end: datetime | None

    @property
    def code(self) -> tuple[str, str]:
        """The ``(phenomena, significance)`` pair, e.g. ``("WS", "W")``."""
        return self.phenomena, self.significance


def _time(text: str) -> datetime | None:
    if text == _UNSET:
        return None
    return datetime.strptime(text, "%y%m%dT%H%MZ").replace(tzinfo=UTC)


def parse_vtec(text: str) -> Vtec:
    """Parse one P-VTEC string.

    Raises:
        VtecError: ``text`` is not a P-VTEC string.
    """
    match = _PVTEC.match(text.strip())
    if match is None:
        raise VtecError(f"not a P-VTEC string: {text!r}")
    try:
        begin, end = _time(match["begin"]), _time(match["end"])
    except ValueError as error:
        raise VtecError(f"bad time in {text!r}") from error
    return Vtec(
        product_class=match["cls"],
        action=match["action"],
        office=match["office"],
        phenomena=match["phen"],
        significance=match["sig"],
        etn=int(match["etn"]),
        begin=begin,
        end=end,
    )

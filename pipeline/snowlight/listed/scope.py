"""Which sources' rows count, and where the matcher looks for each source's names.

A row counts toward SEEN only when it is an entry on a closings list: a station's,
a closing center's, or a state's or county's status board. Some registered
sources are not lists of organizations, and their rows are left out
(:data:`EXCLUDED_PLATFORMS`): a school district's own website alert channel
(Apptegy, Finalsite, Smart Sites, Pasco's and Miami-Dade's banners) carries
whatever the district posts, under the district's own name or a notice's title,
so the district "appears" there whether or not it ever reports to a list; and a
county office's news posts (Humboldt) are titled sentences, not names.

The matcher's context for a source is its registry entry, exactly as
:meth:`snowlight.match.Matcher.match` takes it: the entry's states, its county
FIPS codes (``None`` for a statewide source without them), and its id as the
alias market.
"""

from dataclasses import dataclass
from typing import Final

from snowlight.sources.stations.registry import Station

EXCLUDED_PLATFORMS: Final[dict[str, str]] = {
    "apptegy": "a district's own website alert banner: its rows carry the district's own name",
    "dadeschools": "a district's own alerts file: its rows are alert titles",
    "finalsite": "a district's own website page pops: its rows are notice titles",
    "pasco": "a district's own website emergency banner: its rows carry the district's name",
    "smartsites": "a district's own website pop-up alerts: its rows are notice titles",
    "hcoe": "a county office's news posts: its rows are post titles, not organization names",
}
"""Platforms whose rows are not entries on a closings list, with the reason."""


@dataclass(frozen=True, slots=True, order=True)
class Context:
    """Where the matcher looks for a name: the arguments :meth:`Matcher.match` takes."""

    market: str
    states: tuple[str, ...]
    counties: tuple[str, ...] | None


def station_context(station: Station) -> Context:
    """The matcher context of a station's list: its registry states, counties and id."""
    counties = station.counties.fips if station.counties is not None else None
    return Context(market=station.id, states=tuple(station.states), counties=counties)


def excluded_reason(station: Station) -> str | None:
    """Why a station's rows do not count, or ``None`` when they do."""
    return EXCLUDED_PLATFORMS.get(station.platform)

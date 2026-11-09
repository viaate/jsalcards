"""The closed vocabularies of the published files.

:class:`Status` and :class:`Reason` travel as small integer codes inside compact
rows. A code, once published, keeps its meaning forever: new members are added at
the end with the next free number, and a retired member's number is never reused.
``tests/schemas/test_schema_vocab.py`` pins every code so a renumbering fails the build.

Display text for every code lives in the site's ``src/copy.ts``; the files carry
only codes and the TypeScript types carry only the code names.
"""

from enum import IntEnum
from typing import Annotated, Literal

from pydantic import Field


class Status(IntEnum):
    """What a school is doing on a day because of weather.

    0 closed, 1 delayed start, 2 remote or e-learning, 3 early dismissal.
    """

    CLOSED = 0
    DELAYED = 1
    REMOTE = 2
    EARLY_DISMISSAL = 3


class Reason(IntEnum):
    """The weather named for a status or a forecast.

    0 winter storm, 1 ice, 2 extreme cold, 3 flooding, 4 hurricane,
    5 severe storms, 6 heat, 7 power outage.
    """

    WINTER_STORM = 0
    ICE = 1
    EXTREME_COLD = 2
    FLOODING = 3
    HURRICANE = 4
    SEVERE_STORMS = 5
    HEAT = 6
    POWER_OUTAGE = 7


class Detail(IntEnum):
    """A plain detail a listing states beside its status (:mod:`snowlight.live.details`).

    The site says each in its own words (``src/copy-details.ts``), never the listing's.
    In the order the panel says them: who (0-2), buses (3-7), meals (8-11), pre-K
    (12-14), after school (15-19) and offices (20-21).
    """

    STUDENTS_AND_STAFF = 0
    STAFF_REPORT = 1
    STAFF_LATE = 2
    BUSES_SNOW_ROUTES = 3
    BUSES_EMERGENCY_ROUTES = 4
    BUSES_PAVED_ROADS = 5
    BUSES_LIMITED = 6
    NO_BUSES = 7
    NO_BREAKFAST = 8
    NO_LUNCH = 9
    NO_HOT_LUNCH = 10
    GRAB_AND_GO = 11
    NO_AM_PREK = 12
    NO_PM_PREK = 13
    NO_PREK = 14
    ACTIVITIES_CANCELLED = 15
    AFTER_SCHOOL_CANCELLED = 16
    EVENING_CANCELLED = 17
    CHILDCARE_CLOSED = 18
    CHILDCARE_OPEN = 19
    OFFICES_CLOSED = 20
    OFFICES_OPEN = 21


# The codes a live derivation stores for each detail (snowlight.live.details).
DETAIL_BY_CODE: dict[str, Detail] = {detail.name.lower(): detail for detail in Detail}


# The labels the listing parser (snowlight.classify) reports, mapped to their codes.
REASON_BY_LABEL: dict[str, Reason] = {
    "Winter storm": Reason.WINTER_STORM,
    "Ice": Reason.ICE,
    "Extreme cold": Reason.EXTREME_COLD,
    "Flooding": Reason.FLOODING,
    "Hurricane": Reason.HURRICANE,
    "Severe storms": Reason.SEVERE_STORMS,
    "Heat": Reason.HEAT,
    "Power outage": Reason.POWER_OUTAGE,
}

# The listing parser's status kinds, mapped to their codes.
STATUS_BY_KIND: dict[str, Status] = {
    "closed": Status.CLOSED,
    "delayed": Status.DELAYED,
    "remote": Status.REMOTE,
    "early_dismissal": Status.EARLY_DISMISSAL,
}

# Statuses where no in-person school happens that day.
NO_SCHOOL: frozenset[Status] = frozenset({Status.CLOSED, Status.REMOTE})
# Statuses that shift the school day (a late start or an early end).
SHIFTED: frozenset[Status] = frozenset({Status.DELAYED, Status.EARLY_DISMISSAL})

type Hazard = Annotated[
    Literal["winter", "cold", "flood", "tropical", "heat", "wind", "severe"],
    Field(description="The kind of weather an alert is about."),
]
type AlertLevel = Annotated[
    Literal["warning", "watch", "advisory"],
    Field(description="warning: happening or about to; watch: possible; advisory: less severe."),
]
type Severity = Annotated[
    Literal["Extreme", "Severe", "Moderate", "Minor", "Unknown"],
    Field(description="The alert's own severity rating."),
]

"""A SYNTHETIC world for the live tests: stations, a directory, a matcher and a stub reader.

Every name and status here is made up. The stub reader follows the real status
reader's rules for the forms the tests use (``snowlight.classify.parse_status``):
a bare status posted overnight or in the morning is for that day, at midday it is
undated (``other`` at 0.3), in the evening it is for the next day; "tomorrow" is the day
after the posting day; a weekday one or two days past is unsure (0.3); "Open", "School is
open", "Schools will be open" and "Normal schedule" say open at 0.9. ``[conf=0.7]`` in a
text sets the confidence.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from snowlight.listed.located import Places
from snowlight.listed.matching import Outcome
from snowlight.live.guards import Rules
from snowlight.live.ledger import Ledger, SeenRow
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.merge import Merged, merge
from snowlight.live.provenance import PLATFORM_TYPES
from snowlight.live.resolve import (
    LiveDirectory,
    LiveSchool,
    Resolved,
    Resolver,
    StatusReader,
)
from snowlight.replays.build import School
from snowlight.sources.stations.registry import Station

CHICAGO = "America/Chicago"
DENVER = "America/Denver"
LOS_ANGELES = "America/Los_Angeles"
NEW_YORK = "America/New_York"
VERSION = "synthetic-f5|synthetic-f6|s8c"


def at(text: str) -> datetime:
    """A UTC instant from ``YYYY-MM-DD HH:MM``."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def station(
    station_id: str = "gray-synthetic",
    *,
    states: Sequence[str] = ("CA", "FL", "KS", "MO", "MT"),
    leaids: Sequence[str] = (),
) -> Station:
    """A SYNTHETIC station."""
    basis = "district" if leaids else "dma"
    body: dict[str, Any] = {
        "id": station_id,
        "platform": station_id.rsplit("-", 1)[0],
        "call_sign": "SYNT",
        "name": "SYNTHETIC station",
        "market": "SYNTHETIC market",
        "dma": None,
        "states": list(states),
        "counties": {"basis": basis, "source": "SYNTHETIC", "fips": ["20091"]},
        "page_url": "https://example.invalid/closings",
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": "active",
        "evidence": "SYNTHETIC",
    }
    if leaids:
        body["leaids"] = list(leaids)
    return Station.model_validate_json(json.dumps(body))


def _school(  # noqa: PLR0913 - the fields a test sets
    sid: str,
    index: int,
    *,
    zones: Sequence[str] = (CHICAGO,),
    state: str = "KS",
    district: str = "2000001",
    charter: bool = False,
    virtual: str | None = None,
    name: str = "SYNTHETIC School",
    level: str = "Elementary",
) -> LiveSchool:
    record = School(
        id=sid,
        state=state,
        public=True,
        status="Open",
        county_fips="20091",
        lat=None,
        lon=None,
        virtual=virtual,
        name=name,
        district_id=district,
        level=level,
        school_type="Regular School",
        enrollment=300,
        grade_low="KG",
        grade_high="05",
    )
    return LiveSchool(record=record, index=index, charter=charter, zones=tuple(zones))


ALPHA = ("200000100001", "200000100002")
"""The SYNTHETIC Alpha district's two regular schools (indexes 0 and 1)."""
ALPHA_CHARTER = "200000100003"
ALPHA_VIRTUAL = "200000100004"
ESCAMBIA_CHARTER = "120051000815"
ESCAMBIA_VIRTUAL = "120051007541"
ESCAMBIA_REGULAR = "120051000001"
PACIFIC = "060000000001"
SPLIT = "300000000001"
NOWHERE = "400000000001"
EASTERN = "360000000001"


def directory(extra: Sequence[LiveSchool] = ()) -> LiveDirectory:
    """The SYNTHETIC directory."""
    schools = [
        _school(ALPHA[0], 0, name="SYNTHETIC Alpha Elementary"),
        _school(ALPHA[1], 1, name="SYNTHETIC Alpha High", level="High"),
        _school(ALPHA_CHARTER, 2, charter=True, name="SYNTHETIC Alpha Charter"),
        _school(ALPHA_VIRTUAL, 3, virtual="FULLVIRTUAL", name="SYNTHETIC Alpha Online"),
        _school(ESCAMBIA_CHARTER, 4, state="FL", district="1200510", charter=True),
        _school(ESCAMBIA_VIRTUAL, 5, state="FL", district="1200510", virtual="FULLVIRTUAL"),
        _school(ESCAMBIA_REGULAR, 6, state="FL", district="1200510"),
        _school(PACIFIC, 7, zones=(LOS_ANGELES,), state="CA", district="0600000"),
        _school(SPLIT, 8, zones=(CHICAGO, DENVER), state="MT", district="3000000"),
        _school(NOWHERE, 9, zones=(), state="MO", district="4000000"),
        _school(EASTERN, 10, zones=(NEW_YORK,), state="MO", district="3600000"),
        *extra,
    ]
    sizes: dict[str, int] = {}
    for school in schools:
        district = school.record.district_id or ""
        sizes[district] = sizes.get(district, 0) + 1
    return LiveDirectory(
        schools={school.record.id: school for school in schools},
        district_sizes=sizes,
        edition="synthetic-edition",
    )


def accepted(
    *, direct: Sequence[str] = (), via: Sequence[str] = (), reason: str = "alias", conf: float = 1.0
) -> Outcome:
    return Outcome(
        accepted=True,
        reason=reason,
        level="district" if via else "school",
        confidence=conf,
        targets=tuple(direct) or ("2000001",),
        direct=tuple(direct),
        via_district=tuple(via),
        best_id="x",
        best_name="SYNTHETIC",
        best_score=1.0,
        detail="",
    )


def refused(reason: str = "no_candidate", best: str | None = None) -> Outcome:
    return Outcome(
        accepted=False,
        reason=reason,
        level="none",
        confidence=0.0,
        targets=(),
        direct=(),
        via_district=(),
        best_id=best,
        best_name=None,
        best_score=None,
        detail="",
    )


ALPHA_DISTRICT = "SYNTHETIC Alpha District"
ALPHA_SCHOOL = "SYNTHETIC Alpha Elementary"


@dataclass
class StubMatcher:
    """Matches names from a table; anything else is unmatched."""

    table: dict[str, Outcome] = field(default_factory=dict)
    calls: int = 0

    def __call__(self, station: Station, row: SeenRow) -> Outcome:  # noqa: ARG002 - the protocol
        self.calls += 1
        return self.table.get(row.name, refused())


def default_matcher() -> StubMatcher:
    return StubMatcher(
        {
            ALPHA_DISTRICT: accepted(via=(*ALPHA, ALPHA_CHARTER, ALPHA_VIRTUAL)),
            ALPHA_SCHOOL: accepted(direct=(ALPHA[0],)),
            "SYNTHETIC Escambia County Public Schools": accepted(
                via=(ESCAMBIA_CHARTER, ESCAMBIA_VIRTUAL, ESCAMBIA_REGULAR)
            ),
            "SYNTHETIC Escambia Charter Academy": accepted(direct=(ESCAMBIA_CHARTER,)),
            "SYNTHETIC Pacific School": accepted(direct=(PACIFIC,)),
            "SYNTHETIC Split School": accepted(direct=(SPLIT,)),
            "SYNTHETIC Nowhere School": accepted(direct=(NOWHERE,)),
            "SYNTHETIC Eastern School": accepted(direct=(EASTERN,)),
        }
    )


# --- the stub status reader -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SynEntry:
    kind: str
    dates: tuple[date, ...]
    delay_minutes: int | None = None
    opens_at: time | None = None
    dismissal_time: time | None = None
    dismissal_early_minutes: int | None = None
    dates_stated: bool = False
    until_further_notice: bool = False


@dataclass(frozen=True, slots=True)
class SynParsed:
    kind: str
    schedule: tuple[SynEntry, ...] = ()
    names_weather: bool = False
    reason: str | None = None
    other_causes: tuple[str, ...] = ()
    confidence: float = 0.1
    says_open: bool = False
    notes: tuple[str, ...] = ()


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = {"oct": 10, "nov": 11, "dec": 12, "jan": 1}
_MONTH_DAY = re.compile(r"\b(oct|nov|dec|jan)[a-z]*\.?\s+(\d{1,2})\b")
_CONF = re.compile(r"\[conf=([0-9.]+)\]")
_OPEN = re.compile(r"^(?:schools? (?:is|are|will be) open|normal schedule)\b")


def _kind(text: str) -> str | None:
    if "delay" in text:
        return "delayed"
    if "remote" in text:
        return "remote"
    if "early dismissal" in text:
        return "early_dismissal"
    if "closed" in text or "closing" in text:
        return "closed"
    return None


def stub_reader(text: str, *, posted_at: datetime, tz: str) -> SynParsed:  # noqa: PLR0911, PLR0912
    """The SYNTHETIC status reader (see the module)."""
    local = posted_at.astimezone(ZoneInfo(tz))
    today = local.date()
    hours = local.hour + local.minute / 60
    words = text.casefold()
    found = _CONF.search(words)
    if "possible" in words:
        return SynParsed("other", confidence=0.3, notes=("hedged",))
    if "activities cancelled" in words:
        return SynParsed("other", confidence=0.9, notes=("activities_cancelled",))
    if "rescinded" in words:
        return SynParsed("other", confidence=0.9, notes=("revoked",))
    if words.startswith("open") or _OPEN.search(words):
        return SynParsed("other", confidence=0.9, says_open=True)
    kind = _kind(words)
    if kind is None:
        return SynParsed("other", confidence=0.1, notes=("unrecognized",))
    causes = ("Water service",) if "water main" in words else ()
    weather = "snow" in words
    reason = "Winter storm" if weather else None
    ufn = "until further notice" in words
    extra: dict[str, Any] = {}
    if kind == "delayed":
        extra = {"delay_minutes": 120, "opens_at": time(10)}
    elif kind == "early_dismissal":
        extra = {"dismissal_time": time(13)}
    stated: date | None = None
    month_day = _MONTH_DAY.search(words)
    if month_day:
        stated = date(today.year, _MONTHS[month_day.group(1)], int(month_day.group(2)))
    if "tomorrow" in words:
        stated = today + timedelta(days=1)
    for number, name in enumerate(_WEEKDAYS):
        if name in words:
            ahead = (number - today.weekday()) % 7
            if ahead in {5, 6}:
                return SynParsed("other", confidence=0.3, notes=("unreadable_date",))
            stated = today + timedelta(days=ahead)
    if stated is not None:
        day, dated, confidence = stated, True, 0.95
    elif hours < 12:
        day, dated, confidence = today, False, 0.9
    elif hours < 16:
        return SynParsed("other", confidence=0.3, notes=("undated",), other_causes=causes)
    else:
        day, dated, confidence = today + timedelta(days=1), False, 0.9
    if found:
        confidence = float(found.group(1))
    entry = SynEntry(kind, (day,), dates_stated=dated, until_further_notice=ufn, **extra)
    return SynParsed(
        kind,
        (entry,),
        names_weather=weather,
        reason=reason,
        other_causes=causes,
        confidence=confidence,
    )


def district_schools(district: str, count: int, first_index: int) -> list[LiveSchool]:
    """``count`` SYNTHETIC schools of one district, from ``first_index`` on."""
    return [
        _school(f"{district}{number:05d}", first_index + number, district=district)
        for number in range(count)
    ]


def row(  # noqa: PLR0913 - the fields a test sets
    name: str,
    text: str = "Closed",
    *,
    section: str | None = None,
    places: Places = (),
    row_stamp: datetime | None = None,
    row_date: str = "",
) -> SeenRow:
    """A SYNTHETIC row of a read."""
    return SeenRow(
        name=name,
        text=text,
        section=section,
        places=places,
        row_stamp=row_stamp,
        row_date=row_date,
    )


@dataclass
class World:
    """A ledger, a resolver and the stations, for one test."""

    reader: StatusReader = stub_reader
    rules: Rules = field(default_factory=Rules)
    matcher: StubMatcher = field(default_factory=default_matcher)
    stations: dict[str, Station] = field(default_factory=lambda: {"gray-synthetic": station()})
    dir: LiveDirectory = field(default_factory=directory)
    version: str = VERSION
    ledger: Ledger = field(default_factory=lambda: Ledger(":memory:"))
    last: dict[str, list[SeenRow]] = field(default_factory=dict)
    pollable: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(PLATFORM_TYPES, True))

    def read(
        self,
        when: datetime,
        rows: Sequence[SeenRow],
        *,
        source: str = "gray-synthetic",
        outcome: ReadOutcome = ReadOutcome.OK,
    ) -> ReadOutcome:
        observed = self.ledger.observe(source, outcome, when, rows)
        confirmed = outcome is ReadOutcome.NOT_MODIFIED and not rows
        if not confirmed and observed.outcome in {
            ReadOutcome.OK,
            ReadOutcome.NOT_MODIFIED,
            ReadOutcome.EMPTY,
        }:
            self.last[source] = list(rows)
        return observed.outcome

    def resolver(self) -> Resolver:
        return Resolver(
            reader=self.reader,
            match=self.matcher,
            directory=self.dir,
            ledger=self.ledger,
            version=self.version,
            pollable=self.pollable,
            rules=self.rules,
        )

    def resolve(self) -> list[Resolved]:
        resolver = self.resolver()
        return [resolver.resolve(self.stations[source], rows) for source, rows in self.last.items()]

    def publish(self, now: datetime, *, held: Mapping[str, bool] | None = None) -> Merged:
        resolved = self.resolve()
        return merge(
            resolved,
            held=held if held is not None else {r.source_id: True for r in resolved},
            directory=self.dir,
            generated_at=now,
            rules=self.rules,
        )


def lit(merged: Merged) -> dict[tuple[int, str], str]:
    """Each published (school, ISO day) and its status name."""
    return {
        (closing.school, closing.day.isoformat()): closing.status.name
        for closing in merged.closings
    }


def withheld_of(resolved: Sequence[Resolved]) -> dict[str, str | None]:
    """Each row key's hex and its withheld reason."""
    return {
        result.row.key.hex(): None if result.derived.withheld is None else result.derived.withheld
        for source in resolved
        for result in source.rows
    }


def reasons(resolved: Sequence[Resolved]) -> list[str | None]:
    return [
        None if result.derived.withheld is None else result.derived.withheld.value
        for source in resolved
        for result in source.rows
    ]

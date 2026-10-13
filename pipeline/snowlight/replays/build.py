"""Build one replay day: match, expand, read, settle, and hold the day to its bar.

The steps for day ``D`` (spec section 4.3):

1. **Match.** Every row of an allowed source (:func:`~snowlight.replays.gates.source_drop`)
   in the archive is matched once per distinct listing with the committed
   matcher (:func:`snowlight.listed.build.row_query`,
   :func:`snowlight.listed.matching.match_all`), and the place guard takes away
   the matches a row's own list places elsewhere
   (:func:`snowlight.listed.build.guard`). This is done once per run over the
   whole archive (:func:`match_archive`), so the guard and each station's median
   match share are the same whichever day is built.
2. **Expand.** An accepted listing reaches the schools it names (``school``) and
   the schools of the districts it names (``district``). Left out: a school
   outside its station's states; a public school under a section that says
   private (or the reverse); one the directory lists as new after the storm's
   school year (or, through its district, as moved to another agency); through
   its host district, a virtual or online school (by its flag or its name) and a
   school in a detention center, a hospital or a treatment program; and every
   school of a district whose row names one school, campus, site or program. A
   public school a listing names by its name alone, with no place, level word or
   district of its own behind the match, is marked unanchored.
3. **Zone and read.** Each school's zone comes from the NWS boundaries
   (:class:`ZoneLookup`). The row's whole status (its status and its comments,
   :func:`~snowlight.replays.rows.reader_text`) is read once per zone of its
   schools; readings that disagree on the day drop the row. A row whose list
   gives its posted time must say the same when read at that time. Each reading
   also says what the row says for the day, counted or not (:func:`vote_of`):
   a status, open, or disputed.
4. **Read gates.** A read that looks broken (too many unread rows) or matches far
   under its station's median drops whole.
5. **Settle.** Per station, over every list variant, the captures in the
   school's window are read in time order and the latest one decides
   (superseding). Within one capture every row that says something for the day
   must agree, a school row and its district's row alike, and an unanchored
   school row lights only beside its district's agreeing row. Across stations,
   every station's latest reading of the school must agree (open and disputed
   readings included), and a station that withdrew the school stops another's
   claim.
6. **Status.** The reader's kind and reason map to the published codes.

The day's bar (A1-A6 here, A7 by building twice) decides whether a seed is kept.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence, Set
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Final, Literal, Protocol
from zoneinfo import ZoneInfo

import polars as pl

from snowlight.listed.build import GUARD_REASON, guard, row_query
from snowlight.listed.evidence import ListRow, LoadedRows, Read
from snowlight.listed.located import Gazetteer, Verdict
from snowlight.listed.matching import MatcherSpec, Outcome, Query, match_all
from snowlight.match import Matcher
from snowlight.replays.control import ControlResult, control_day
from snowlight.replays.gates import (
    ALLOWED_NOTES,
    MIN_CONFIDENCE,
    REPLAY_PLATFORMS,
    UNREAD_CONFIDENCE,
    Drop,
    Entry,
    Parsed,
    ParseFn,
    capture_window,
    claim_for_day,
    day_ok,
    directory_year,
    dissents,
    in_window,
    low_match,
    rejected_notes,
    says_open,
    school_year_of,
    source_drop,
    speaks_for,
    station_median,
    unread_share,
    unreadable,
)
from snowlight.replays.rows import (
    NO_EXTRA,
    RowExtra,
    day_rows,
    instant,
    posted_stamp,
    reader_text,
    rows_by_read,
    widest_window,
    window_reads,
)
from snowlight.replays.seed import RULES, SCHEMA_VERSION, SOURCE_TYPE, Built, Quality, ReplaySeed
from snowlight.schemas.vocab import REASON_BY_LABEL, STATUS_BY_KIND, Reason, Status
from snowlight.sources.stations.registry import Registry, Station

NEW_STATUSES: Final = frozenset({"New", "Added", "Reopened"})
"""Directory statuses of a public school that may not have existed in an earlier year."""
MOVED_STATUSES: Final = frozenset({"Changed Boundary/Agency"})
"""Directory statuses of a public school that may have been in another district a year before."""
VIRTUAL_FLAGS: Final = frozenset({"FULLVIRTUAL", "FACEVIRTUAL"})
"""The directory's ``virtual`` values for a school taught mainly online, with no building of its
own to close (``SUPPVIRTUAL`` is a school with a building that also teaches online)."""
VIRTUAL_NAME: Final = re.compile(
    r"\b(?:virtual|online|cyber|e-?school|e-?academy|ecademy|digital\s+academy|"
    r"connections\s+academy|distance\s+learning|e-?learning|independent\s+study|"
    r"(?<!group\s)home\s*school|home\s*link|parent\s+partnership|flex\s+academy|digital\s+learning|"
    r"insight\s+school|hybrid)\b",
    re.IGNORECASE,
)
"""A school's name that says it is taught online or at home, whatever the directory's flag."""
FACILITY_NAME: Final = re.compile(
    r"\b(?:detention|detent|juvenile|juv|jail|correction(?:al|s)?|corr\s+(?:center|ctr)|"
    r"incarcerat\w*|hospitals?|homebound|residential|resident\s+student|residence|treatment|"
    r"trmnt|trtmt|tr?eatmt|"
    r"youth\s+(?:development|dev|services?|detention|correctional|center|centre|ctr|campus|"
    r"facility|recovery|academy|ranch|village|home|shelter|challenge|court|multi-?service)|"
    r"(?:regional|reg\.?|county|co\.?|state|illinois|il)\s+youth|(?:center|ctr)\s+for\s+youth|"
    r"(?:boys|girls)\s+ranch|sheriff'?s?|adjudicated|djj|jjaep|j\s+j\s+a\s+e\s+p|jdc|"
    r"juvenile\s+justice|justice\s+(?:center|ctr|facility)|county\s+court|court\s+school|"
    r"(?:staff[\s-])?secure|forensic|reception\s+and\s+diag\w*|diagnostic\s+(?:center|ctr)|"
    r"department\s+of\s+(?:corrections|juvenile|youth|human)|"
    r"children'?s?\s+(?:home|hospital|medical|center|centre|ctr|village|psychiatric)|childrens\s+\w+\s+unit|"
    r"(?:behavioral|mental)\s+health|psychiatric|crisis|\w*rehab\w*|addiction|healing\s+center|"
    r"(?:youth|crisis)\s+shelter|shelter\s+care|group\s+home|ronald\s+mcdonald\s+house|"
    r"institution|care\s+and\s+treatment|state\s+care|reformatory|penitentiary|prisons?|"
    r"inmates?|offenders?|probation|(?:forestry|boot|work)\s+camp|"
    r"behaviou?r(?:al)?\s+(?:health|services?|center|ctr|hospital|continuum)|ami\s*kids|"
    r"youth\s+(?:care|villages?|corr\w*|educational\s+support)|hosp|home\s*(?:&|and)\s*hosp\w*|"
    r"corr\.?\s+(?:centr?e?|cent|ctr|facil\w*)|his\s+house|boys\s+republic|boys\s*town|"
    r"(?:boys|girls)\s+school|kemmerer\s+village|challenge\s+academy|job\s+corps|prairie\s+care|"
    r"inner\s+harbou?r|jvnl|juve|juvenil+e?|det\.?\s+(?:centre|center|cntr|ctr)|r?ydc|devereux|"
    r"state\s+school|regional\s+inst\w*|children'?s\s+services|health\s+(?:center|ctr)|c\s*&\s*t|"
    r"contract\w*|(?<!advanced\s)placements?|tuition|out[\s-]+of[\s-]+(?:district|county|state))s?\b|"
    r"\bcamp\s*(?:#\s*)?\d*\s*$",
    re.IGNORECASE,
)
"""A school's name that says it is a program in a detention center, a jail or prison, a youth
services or development center, a hospital, a psychiatric, crisis or treatment center, a group or
children's home, or a homebound program: such a school does not close for its district's snow
day. Measured on the directory's public names (Alternative and Special Education schools above
all): "Woodsbend Youth Development Center", "Ingham County Youth Center", "ADJUDICATED YOUTH
FACILITY", "SUFFOLK COUNTY SHERIFFS OFFICE", "TARRANT YOUTH RECOVERY", "CHILDREN'S MEDICAL CTR",
"Goshen Secure Center", "Santa Clara County Court", "Afflerbaugh-Paige Camp", "BRAZOS COUNTY
JJAEP", "AmiKiDs Caddo", "Youth Villages at Inner Harbour", "PALMSHORES BEHAVIOR HEALTH CENTER",
"Home & Hosp/Transition Support", "Pine Hills Youth Corr Facil", "Wyoming Girls School",
"Devereux Ackerman Academy" and "SAN ANGELO STATE SCHOOL" (both typed Regular). Every form
reads in the plural too ("Whaley Children Centers", a treatment campus typed Regular), and a
contract, placement or tuition roster is held with them ("CONTRACT", "Vancouver Contracted
Programs", "Exceptional Children Special Placements", "VO. TECH. TUITION"; not "Advanced
Placement")."""
FACILITY_TYPES: Final = frozenset({"Alternative School", "Special Education School"})
"""The directory's school types that may be a program in a facility, whatever their name says:
state-agency, detention, children's-home and psychiatric programs go by plain school names
("Breathitt Regional School", "Dessie Scott School", "Gateway Children's Services", "Peace
Academy", "RTC SCHOOL"). Every such school is held to its own row (:func:`facility`)."""


ROSTER_LOW: Final = frozenset({"PK", "KG"})
"""The lowest grades of a roster that spans every grade (with :data:`ROSTER_HIGH`)."""
ROSTER_HIGH: Final = "12"


def roster(school: "School") -> bool:
    """Whether a school is a roster or a program, not a building: a Regular school that spans
    every grade (PK or KG through 12) with no students enrolled. Measured on the directory's
    public schools: 121 such schools, all online programs, placement and contract rosters,
    treatment campuses ("Whaley Children Centers"), shared-time, summer, adult and alternative
    programs ("Shared Time", "Outside School Day Program", "Shelby County Summer School")."""
    return (
        school.school_type == "Regular School"
        and school.enrollment == 0
        and school.grade_low in ROSTER_LOW
        and school.grade_high == ROSTER_HIGH
    )


def facility(school: "School") -> bool:
    """Whether a school may be a facility program that does not close for its district's snow
    day: an alternative or special education school (:data:`FACILITY_TYPES`), a school of
    another type whose name says so (:data:`FACILITY_NAME`), or a roster (:func:`roster`). It
    lights only through its own row, never through its district's."""
    return (
        school.school_type in FACILITY_TYPES
        or bool(FACILITY_NAME.search(school.name))
        or roster(school)
    )


PRIVATE_SECTION: Final = re.compile(
    r"\b(?:private|parochial|catholic|religious|christian|montessori|independent|non-?public)\b",
    re.IGNORECASE,
)
PUBLIC_SECTION: Final = re.compile(r"(?<!\bnon-)(?<!\bnon\s)\bpublic\b", re.IGNORECASE)
"""Section words that say which kind of school a list files a row under ("Non-Public" is
private)."""
PART_WORDS: Final = re.compile(
    r"(?<!\ball\s)(?<!\bevery\s)(?<!\beach\s)\b(?:campus|building|elementary|elem|middle|"
    r"high\s+school|jr|jhs|ms|hs|upper\s+school|lower\s+school|academy|center|site|location|"
    r"annex|preschool|pre-?k|early\s+childhood|except|(?:pk|tk|k)\s*-\s*\d{1,2}|grades?\s+(?:pk|k|\d)|"
    r"(?:at|for)\s+(?!(?:all|every|each|our|the|public|district|area)\b)"
    r"(?-i:[A-Z])[\w.'-]*(?:\s+(?-i:[A-Z])[\w.'-]*)*\s+school)\b",
    re.IGNORECASE,
)
"""Words that name one part of a district ("Kibbleworth campus", "Lincoln Elementary", "the
north site", "except the high school", "Lincoln Elem only", "K-8 closed", "Closed at Lincoln
School"): such a row does not speak for all its schools. "All
campuses" and "every elementary" speak for every one."""
NAME_ONLY: Final = frozenset({"name"})
"""The matcher's reasons that rest on a listing's name alone (``snowlight.match.Reason.NAME``)."""
LISTING_LEVELS: Final = (
    ("elementary", re.compile(r"\b(?:elementary|elem|es|primary|grade\s+school)\b", re.I)),
    ("intermediate", re.compile(r"\bintermediate\b", re.I)),
    ("middle", re.compile(r"\b(?:middle|ms|junior|jr)\b", re.I)),
    ("high", re.compile(r"\b(?:high|hs|senior)\b", re.I)),
)
"""The level words a listing can carry, by level."""
RECORD_LEVELS: Final[Mapping[str, frozenset[str]]] = {
    "Elementary": frozenset({"elementary", "intermediate"}),
    "Middle": frozenset({"middle", "intermediate"}),
    "High": frozenset({"high"}),
    "Secondary": frozenset({"middle", "high"}),
    "Combined elementary and secondary": frozenset(
        {"elementary", "intermediate", "middle", "high"}
    ),
}
"""The listing level words that agree with each directory ``level``."""
FALLBACK_ZONE: Final = "America/Chicago"
"""The zone a read's rows are read in for the unreadable gate when its station's is unknown.
Whether the reader recognizes anything in a text does not depend on the zone."""
MIN_LIT: Final = 250
MIN_SOURCES: Final = 2
MIN_MARKETS: Final = 2
MAX_CONFLICT_SHARE: Final = 0.02
MIN_KEEP_SHARE: Final = 0.98

type Level = Literal["school", "district"]


class BuildError(ValueError):
    """The inputs do not agree, or an invariant of the day does not hold."""


class ZoneLookup(Protocol):
    """Finds a place's IANA zone (:class:`snowlight.weather.timezones.TimeZoneLookup`)."""

    def zone_for(
        self, county_fips: str | None, lat: float | None, lon: float | None, /
    ) -> str | None:
        """The zone the place is in, or ``None`` when it is not settled."""
        ...


@dataclass(frozen=True, slots=True)
class School:
    """The directory fields a replay reads for one school."""

    id: str
    state: str
    public: bool
    status: str | None
    county_fips: str | None
    lat: float | None
    lon: float | None
    virtual: str | None = None
    """The directory's ``virtual`` value (``FULLVIRTUAL`` for a school with no building)."""
    name: str = ""
    district_id: str | None = None
    level: str | None = None
    """The directory's ``level`` (Elementary, Middle, High, ...)."""
    school_type: str | None = None
    """The directory's ``school_type`` (Regular, Alternative, Special Education, ...)."""
    enrollment: int | None = None
    """The directory's ``enrollment`` (``None`` when it reports none)."""
    grade_low: str | None = None
    """The directory's lowest grade as an NCES code (``PK``, ``KG``, ``01`` ... ``12``)."""
    grade_high: str | None = None
    """The directory's highest grade as an NCES code."""


@dataclass(frozen=True, slots=True)
class Directory:
    """The directory's schools by NCES id, and its public school year."""

    schools: Mapping[str, School]
    public_year: int
    """The first year of the public (CCD) school year, 2024 for 2024-2025."""
    district_sizes: Mapping[str, int] = field(default_factory=dict)
    """How many schools each district holds."""

    @classmethod
    def from_frame(cls, frame: pl.DataFrame) -> "Directory":
        """Read ``schools.parquet`` (id, kind, state, status, county_fips, lat, lon, school_year,
        and ``virtual``, ``name``, ``district_id``, ``level``, ``school_type``, ``enrollment``,
        ``grade_low`` and ``grade_high`` when it has them).

        Raises:
            ValueError: no public school names a school year.
        """
        columns = ["id", "kind", "state", "status", "county_fips", "lat", "lon", "school_year"]
        optional = [
            (frame[name] if name in frame.columns else pl.Series([None] * frame.height)).to_list()
            for name in (
                "virtual",
                "name",
                "district_id",
                "level",
                "school_type",
                "enrollment",
                "grade_low",
                "grade_high",
            )
        ]
        schools: dict[str, School] = {}
        public_years: list[str] = []
        sizes: Counter[str] = Counter()
        rows = zip(frame.select(columns).iter_rows(), *optional, strict=True)
        for (
            sid,
            kind,
            state,
            status,
            fips,
            lat,
            lon,
            year,
        ), mode, name, district, level, kind_of, enrolled, low, high in rows:
            public = kind == "public"
            if district is not None:
                sizes[str(district)] += 1
            schools[str(sid)] = School(
                id=str(sid),
                state=str(state),
                public=public,
                status=None if status is None else str(status),
                county_fips=None if fips is None else str(fips),
                lat=None if lat is None else float(lat),
                lon=None if lon is None else float(lon),
                virtual=None if mode is None else str(mode),
                name="" if name is None else str(name),
                district_id=None if district is None else str(district),
                level=None if level is None else str(level),
                school_type=None if kind_of is None else str(kind_of),
                enrollment=None if enrolled is None else int(enrolled),
                grade_low=None if low is None else str(low),
                grade_high=None if high is None else str(high),
            )
            if public and year:
                public_years.append(str(year))
        return cls(
            schools=schools,
            public_year=directory_year(public_years),
            district_sizes=dict(sorted(sizes.items())),
        )


# --- step 1: matching, once per run -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatchBook:
    """The matcher's answer for every listing of the allowed sources, and the read shares."""

    outcomes: Mapping[Query, Outcome]
    shares: Mapping[tuple[str, str], float]
    """Each tied read's accepted-match share, by (source id, read time)."""
    medians: Mapping[str, float | None]
    """Each station's median share over its populated reads (``None`` under 3 reads)."""
    placed: frozenset[Query] = frozenset()
    """The listings one of whose rows names a place that agrees with the matched records."""


def match_archive(  # noqa: PLR0913 - the rows, the matcher and how to run it
    loaded: LoadedRows,
    registry: Registry,
    matcher: Matcher,
    *,
    gazetteer: Gazetteer,
    spec: MatcherSpec | None = None,
    workers: int = 1,
) -> MatchBook:
    """Match every row of an allowed source once, guard by place, and measure each read.

    A listing one of whose rows names a place that agrees with its records is
    ``placed`` (an anchor for a match by name alone, see :meth:`_Day.anchored`),
    even when another of its rows places it elsewhere and the guard takes the
    match away: such a name is two organizations on that list.
    """
    rows = allowed_rows(loaded, registry)
    queries = [row_query(row, registry) for row in rows]
    matched = dict(match_all(matcher, queries, workers=workers, spec=spec))
    pairs = [(query, row.places) for query, row in zip(queries, rows, strict=True)]
    placed: set[Query] = set()
    for query, places in pairs:
        outcome = matched[query]
        if outcome.accepted and places and query not in placed:
            verdict = gazetteer.verdict(places, outcome.targets, query.context.states)
            if verdict is Verdict.AGREES:
                placed.add(query)
    outcomes = {**matched, **guard(gazetteer, pairs, matched)}
    return book_from(rows, registry, outcomes, frozenset(placed))


def allowed_rows(loaded: LoadedRows, registry: Registry) -> list[ListRow]:
    """The rows of the sources a replay may read (:func:`~snowlight.replays.gates.source_drop`)."""
    return [row for row in loaded.rows if source_drop(registry.stations.get(row.source_id)) is None]


_NAME_WORDS: Final = re.compile(r"[a-z0-9]+")


def listing_key(name: str) -> str:
    """A listing's name with case, punctuation and a leading "The" set aside."""
    words = _NAME_WORDS.findall(name.casefold())
    return " ".join(words[1:] if words[:1] == ["the"] else words)


def same_market(one: Station, two: Station) -> bool:
    """Whether two stations serve one market: the same DMA or market, or a county in common."""
    if (one.dma and one.dma == two.dma) or one.market == two.market:
        return True
    first = set(one.counties.fips) if one.counties is not None else set()
    second = set(two.counties.fips) if two.counties is not None else set()
    return bool(first & second)


def carry_place_guard(
    rows: Sequence[ListRow],
    registry: Registry,
    outcomes: Mapping[Query, Outcome],
    placed: Set[Query] = frozenset(),
) -> dict[Query, Outcome]:
    """Take away a match that a station's list in the same market places elsewhere.

    When one station's row places a listing away from the records the matcher
    named (:data:`~snowlight.listed.build.GUARD_REASON`), the same listing name
    at that station (under another section, say) or at another station of that
    market names the same organization: its match to
    any of those records is not accepted either. Two organizations can share a
    name in one market ("Watertown Public Schools" in two states), so nothing is
    carried from a listing whose own rows also place it by the record, and a
    listing whose own list places it by the record keeps its match (``placed``).
    Returns the changed outcomes.
    """
    away: dict[str, set[tuple[str, frozenset[str]]]] = defaultdict(set)
    for row in rows:
        query = row_query(row, registry)
        outcome = outcomes[query]
        if outcome.reason == GUARD_REASON and outcome.targets and query not in placed:
            away[listing_key(row.name)].add((row.source_id, frozenset(outcome.targets)))
    changed: dict[Query, Outcome] = {}
    for row in rows:
        query = row_query(row, registry)
        outcome = outcomes[query]
        if not outcome.accepted or query in changed or query in placed:
            continue
        station = registry.stations[row.source_id]
        for source, targets in sorted(away.get(listing_key(row.name), ()), key=str):
            if not targets & set(outcome.targets):
                continue
            if same_market(registry.stations[source], station):
                changed[query] = replace(
                    outcome,
                    accepted=False,
                    reason=GUARD_REASON,
                    direct=(),
                    via_district=(),
                    detail=f"{outcome.detail}; {source}'s list places it away from the record",
                )
                break
    return changed


def book_from(
    rows: Sequence[ListRow],
    registry: Registry,
    outcomes: Mapping[Query, Outcome],
    placed: frozenset[Query] = frozenset(),
) -> MatchBook:
    """A :class:`MatchBook` from the matcher's (guarded) answers for ``rows``.

    The place guard's verdicts are carried to the same listing name at the other
    stations of a market first (:func:`carry_place_guard`).
    """
    outcomes = {**outcomes, **carry_place_guard(rows, registry, outcomes, placed)}
    accepted: Counter[tuple[str, str]] = Counter()
    total: Counter[tuple[str, str]] = Counter()
    for row in rows:
        key = (row.source_id, row.fetched_at)
        total[key] += 1
        accepted[key] += outcomes[row_query(row, registry)].accepted
    shares = {key: accepted[key] / count for key, count in sorted(total.items())}
    by_station: dict[str, list[float]] = defaultdict(list)
    for (station, _at), share in shares.items():
        by_station[station].append(share)
    medians = {station: station_median(values) for station, values in sorted(by_station.items())}
    return MatchBook(outcomes=dict(outcomes), shares=shares, medians=medians, placed=placed)


# --- the day's inputs and results ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DayInputs:
    """Everything a day is built from."""

    loaded: LoadedRows
    registry: Registry
    book: MatchBook
    directory: Directory
    lookup: ZoneLookup
    parse: ParseFn
    extras: Mapping[tuple[str, str], tuple[RowExtra, ...]] = field(default_factory=dict)
    """Each read's rows' comments and posted times, in row order (:func:`rows.row_extras`)."""


@dataclass(frozen=True, slots=True)
class Claim:
    """A counted status for one school from one row (or one capture)."""

    kind: str
    status: Status
    reason: Reason | None
    dated: bool
    notes: tuple[str, ...]


OPEN_VOTE: Final = "open"
"""A reading that says the school is open (the reader's ``says_open``, or :func:`says_open`)."""
DISPUTED_VOTE: Final = "disputed"
"""A reading that says the school's weather status is not what another row says: the reader
finds two statuses that disagree (note ``conflict``, or confidence at :data:`CONFLICTING`), or
the reading takes a status back, denies it, narrows it, is unsure of it, or gives the day another
cause or a learning mode (:func:`snowlight.replays.gates.dissents`)."""
CONFLICTING: Final = 0.25
"""The reader's level for a text whose statuses disagree (``classify.model.CONFLICTING``)."""
CONFLICT_NOTE: Final = "conflict"


def vote_of(  # noqa: PLR0913 - one reading and the row's words
    parsed: Parsed,
    entry: Entry | None,
    day: date,
    *,
    text: str,
    name: str = "",
    detail: str = "",
    posted: date | None = None,
) -> str | None:
    """What a reading says about the school for ``day``, counted or not, or ``None``.

    Open (:data:`OPEN_VOTE`) before anything else; then a disputed reading
    (:data:`DISPUTED_VOTE`); then the entry's status kind. A reading with none of
    these (nothing recognized, another day's status) says nothing about the day.

    The votes, by what the claim gates make of the reading:

    * counted, or uncounted only for its window (``OUTSIDE_WINDOW``): its kind;
    * ``SAYS_OPEN``: open;
    * ``OTHER_CAUSE``, ``NON_WEATHER_WORDS`` or ``DETAIL_MODE`` for the day:
      disputed;
    * a note in :data:`snowlight.replays.gates.DISSENT_NOTES` (revoked,
      negated, superseded, ambiguous, partial_program, conflict): disputed when
      the reading gives the day a status, states none, or names the day in its
      words (:func:`snowlight.replays.gates.dissents`);
    * the note ``conflict`` or confidence at :data:`CONFLICTING`: disputed for
      every day, whatever it names. The reader finds two statuses that disagree
      and may have dated either one wrongly, so this vote takes no day rule (it
      only ever costs light);
    * ``LOW_CONFIDENCE``, ``STALE_POST``, ``OPEN_ENDED``, ``DATE_OUT_OF_RANGE``
      or another note (hedged, activities_cancelled, ...): its kind. Such a
      reading names the status a counted claim of the same kind names, so it
      neither confirms nor denies it; a different kind still makes a conflict.
      It never adds light: only counted claims light or corroborate.

    ``text`` is the reader's text (the status and the comments, which carry any
    learning word); ``detail`` is the comments alone, read for an open comment;
    ``posted`` is the capture's local date, for "today" and "tomorrow".
    """
    if parsed.says_open or says_open(text, detail):
        return OPEN_VOTE
    if (
        CONFLICT_NOTE in parsed.notes
        or UNREAD_CONFIDENCE < parsed.confidence <= CONFLICTING
        or dissents(parsed, day, text=text, name=name, posted=posted)
    ):
        return DISPUTED_VOTE
    if entry is not None and entry.kind in STATUS_BY_KIND:
        return entry.kind
    return None


@dataclass(frozen=True, slots=True)
class Reading:
    """What one row says about one school it reaches."""

    row: ListRow
    level: Level
    kind: str | None
    """The reader's kind for the target day, counted or not (``None``: no entry)."""
    claim: Claim | None
    drop: Drop | None
    vote: str | None = None
    """What the reading says about the school for the day (:func:`vote_of`)."""
    anchored: bool = True
    """Whether the match rests on more than the listing's name (:meth:`_Day.anchored`)."""


@dataclass(frozen=True, slots=True)
class CaptureClaim:
    """A station's counted status for a school, and the readings it rests on."""

    claim: Claim
    evidence: tuple[Reading, ...]


@dataclass(frozen=True, slots=True)
class Lit:
    """A school the day lights."""

    school: str
    status: Status
    reason: Reason | None
    stations: tuple[str, ...]
    evidence: tuple[Reading, ...]
    school_type: str | None = None
    """The directory's ``school_type`` (the report lists alternative and special education
    schools lit through districts only, for the audit)."""

    @property
    def corroborated(self) -> bool:
        """Whether two or more stations give this status."""
        return len(self.stations) > 1

    @property
    def matched_apart(self) -> bool:
        """Whether the stations reach the school through listings of different names.

        Two stations that give one listing the same name share one matcher
        decision: they corroborate the status, not the match.
        """
        names = {" ".join(reading.row.name.casefold().split()) for reading in self.evidence}
        return self.corroborated and len(names) > 1


@dataclass(frozen=True, slots=True)
class ReadCheck:
    """The read gates' numbers for one read."""

    source_id: str
    fetched_at: str
    variant: str
    sha256: str
    rows: int
    unread_share: float
    match_share: float
    station_median: float | None
    drop: Drop | None


@dataclass(frozen=True, slots=True)
class Settled:
    """The outcome of the day's steps for one target day."""

    target: date
    rows_in: int
    lit: Mapping[str, Lit]
    conflicts: tuple[str, ...]
    row_drops: Mapping[str, int]
    """Rows dropped, by the first gate they failed."""
    target_drops: Mapping[str, int]
    """(row, school) pairs dropped in expansion."""
    school_drops: Mapping[str, int]
    """(station, school) pairs dropped in settling, and schools dropped across stations."""
    note_drops: Mapping[str, int]
    """Rows dropped for a note, by each note not allowed."""
    reads: tuple[ReadCheck, ...]
    dropped: tuple[tuple[ListRow, Drop], ...]
    entries: int
    """Rows the reader gave an entry for the target day, before the claim gates (a district row
    that names part of the district counts, though it lights none of its schools)."""
    untied: tuple[tuple[str, str, int], ...] = ()
    """Populated reads in the window whose rows did not tie to them (source, time, rows)."""
    untied_voids: int = 0
    """(station, school) claims voided by a later read whose rows did not tie."""


# --- steps 2-4: rows to readings ----------------------------------------------------------------


@dataclass
class _Day:
    inputs: DayInputs
    target: date
    window_day: date
    check_range: bool = True
    readings: dict[tuple[str, str, str], list[Reading]] = field(
        default_factory=lambda: defaultdict(list)
    )
    touched: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    row_drops: Counter[str] = field(default_factory=Counter)
    target_drops: Counter[str] = field(default_factory=Counter)
    note_drops: Counter[str] = field(default_factory=Counter)
    dropped: list[tuple[ListRow, Drop]] = field(default_factory=list)
    zones: dict[str, str | None] = field(default_factory=dict)
    station_zones: dict[str, str] = field(default_factory=dict)
    checked_zones: set[str] = field(default_factory=set)
    entries: int = 0

    def drop_row(self, row: ListRow, reason: Drop) -> None:
        self.row_drops[reason.value] += 1
        self.dropped.append((row, reason))

    def zone(self, school: School) -> str | None:
        if school.id not in self.zones:
            self.zones[school.id] = self.inputs.lookup.zone_for(
                school.county_fips, school.lat, school.lon
            )
        return self.zones[school.id]

    def check_zone(self, zone: str) -> None:
        """Every capture a school in ``zone`` may count from lies in the widest window.

        Raises:
            BuildError: the zone's window reaches outside :func:`rows.widest_window`.
        """
        if zone in self.checked_zones:
            return
        start, end = capture_window(self.window_day, zone, dated=True)
        low, high = widest_window(self.window_day)
        if start < low or end > high:
            raise BuildError(f"{zone}'s window for {self.window_day} is outside the widest window")
        self.checked_zones.add(zone)

    def station_zone(self, station: Station) -> str:
        """The zone most of a station's counties are in (for the unreadable gate only)."""
        if station.id not in self.station_zones:
            fips = station.counties.fips if station.counties is not None else ()
            found = Counter(
                zone for code in fips if (zone := self.inputs.lookup.zone_for(code, None, None))
            )
            ranked = sorted(found.items(), key=lambda item: (-item[1], item[0]))
            self.station_zones[station.id] = ranked[0][0] if ranked else FALLBACK_ZONE
        return self.station_zones[station.id]

    def check_read(
        self,
        station: Station,
        rows: Sequence[ListRow],
        read: Read,
        extras: Sequence[RowExtra],
    ) -> ReadCheck:
        """The read gates for one read, each row read as its claim is (status and comments)."""
        captured = instant(read.fetched_at)
        zone = self.station_zone(station)
        confidences = [
            self.inputs.parse(
                reader_text(row.status, extra.detail), posted_at=captured, tz=zone
            ).confidence
            for row, extra in zip(rows, extras, strict=True)
        ]
        key = (read.source_id, read.fetched_at)
        share = self.inputs.book.shares.get(key, 0.0)
        median = self.inputs.book.medians.get(station.id)
        drop: Drop | None = None
        if unreadable(confidences):
            drop = Drop.READ_UNREADABLE
        elif low_match(share, median):
            drop = Drop.READ_LOW_MATCH
        return ReadCheck(
            source_id=read.source_id,
            fetched_at=read.fetched_at,
            variant=read.variant,
            sha256=read.sha256,
            rows=len(rows),
            unread_share=round(unread_share(confidences), 4),
            match_share=round(share, 4),
            station_median=None if median is None else round(median, 4),
            drop=drop,
        )

    def target_drop(  # noqa: PLR0911 - one return per guard
        self, school: School, level: Level, row: ListRow, text: str
    ) -> Drop | None:
        """Why a school a listing reaches is left out, or ``None`` when it is kept."""
        station = self.inputs.registry.stations[row.source_id]
        before = school_year_of(self.target) < self.inputs.directory.public_year
        section = row.section or ""
        if school.state not in station.states:
            return Drop.OUT_OF_STATE
        if (school.public and PRIVATE_SECTION.search(section)) or (
            not school.public and PUBLIC_SECTION.search(section)
        ):
            return Drop.SECTION
        if before and school.public and school.status in NEW_STATUSES:
            return Drop.SCHOOL_YEAR
        if level == "district" and before and school.public and school.status in MOVED_STATUSES:
            return Drop.SCHOOL_YEAR
        if level == "district" and (
            school.virtual in VIRTUAL_FLAGS or VIRTUAL_NAME.search(school.name)
        ):
            return Drop.VIRTUAL
        if level == "district" and facility(school):
            return Drop.FACILITY
        if level == "district" and PART_WORDS.search(text):
            return Drop.PART_OF_DISTRICT
        return None

    def anchored(self, school: School, level: Level, row: ListRow, outcome: Outcome) -> bool:
        """Whether a row's match to a school rests on more than the listing's name.

        A district's row, a private school's row and a match the matcher made by
        alias, context, nearness or campus are anchored. A public school matched by
        its name alone (``"Kestrel Hill School"``) is anchored only when the row's
        list places it by the record (:attr:`MatchBook.placed`), the listing
        carries the school's level word ("Elementary", "High"), or the school is its
        district's only one. Otherwise the row may be a private namesake: it lights
        the school only beside its own district's agreeing row
        (:func:`capture_state`).
        """
        if level == "district" or not school.public or outcome.reason not in NAME_ONLY:
            return True
        if row_query(row, self.inputs.registry) in self.inputs.book.placed:
            return True
        if school.district_id is not None and (
            self.inputs.directory.district_sizes.get(school.district_id) == 1
        ):
            return True
        record = RECORD_LEVELS.get(school.level or "", frozenset())
        return any(word in record and found.search(row.name) for word, found in LISTING_LEVELS)

    def targets(
        self, outcome: Outcome, row: ListRow, text: str
    ) -> tuple[list[tuple[School, Level, bool]], list[School], Drop]:
        """The schools a listing reaches that pass the expansion guards (and whether each is
        anchored), the schools of a district row that names part of the district
        (``PART_OF_DISTRICT``: they vote but never light), and the first drop."""
        reached: list[tuple[str, Level]] = [(sid, "school") for sid in outcome.direct]
        reached += [(sid, "district") for sid in outcome.via_district]
        kept: list[tuple[School, Level, bool]] = []
        parts: list[School] = []
        first: Drop | None = None
        for sid, level in reached:
            school = self.inputs.directory.schools.get(sid)
            if school is None:
                raise BuildError(f"the matcher names {sid}, which the directory does not hold")
            reason = self.target_drop(school, level, row, text)
            if reason is None:
                kept.append((school, level, self.anchored(school, level, row, outcome)))
                continue
            if reason is Drop.PART_OF_DISTRICT:
                parts.append(school)
            first = first or reason
            self.target_drops[reason.value] += 1
        return kept, parts, first or Drop.NOT_MATCHED

    def gate(  # noqa: PLR0913 - one row, one zone
        self,
        parsed: Parsed,
        row: ListRow,
        *,
        captured: datetime,
        zone: str,
        text: str,
        extra: RowExtra,
    ) -> Entry | Drop:
        """The claim gates for one reading, and the posted-time check (``STALE_POST``).

        A row whose list gives its posted time must say the same for the day read
        at that time. A page's stamp only bounds the row's age: it never lifts the
        "tomorrow" guard (:func:`~snowlight.replays.gates.relative_tomorrow`). A
        stamp that names a date only ("2025-01-07") is known to the day: an undated
        row posted before the day drops, and a dated row is read again at noon of
        the stamp's date.
        """
        posted = posted_stamp(extra.posted, captured, zone, extra.posted_zone)
        gate = claim_for_day(
            parsed,
            self.target,
            captured,
            zone,
            text=text,
            name=row.name,
            detail=extra.detail,
            window_day=self.window_day,
            check_range=self.check_range,
            posted_on=None if posted is None or extra.page_stamp else posted.day,
        )
        if isinstance(gate, Drop) or posted is None:
            return gate
        if posted.date_only and not gate.dates_stated and posted.day < self.window_day:
            return Drop.STALE_POST
        if posted.at < captured:
            then = self.inputs.parse(text, posted_at=posted.at, tz=zone).on(self.target)
            if then is None or then.kind != gate.kind:
                return Drop.STALE_POST
        return gate

    def read_row(self, row: ListRow, captured: datetime, extra: RowExtra) -> None:
        """Read one row for every school it reaches, once per zone of those schools.

        The row's claim (or its drop) is one for all its schools; when the zones'
        readings disagree, the row drops (``ZONE_SPLIT``). Each school keeps its own
        zone's kind and vote. A school the row may light whose zone is unknown drops
        the row (``ZONE_UNKNOWN``); a school of a row that names part of its district
        whose zone is unknown casts no vote, and the row's other schools still vote.
        """
        station = self.inputs.registry.stations[row.source_id]
        outcome = self.inputs.book.outcomes[row_query(row, self.inputs.registry)]
        if not outcome.accepted:
            self.drop_row(
                row, Drop.PLACE_GUARD if outcome.reason == GUARD_REASON else Drop.NOT_MATCHED
            )
            return
        text = reader_text(row.status, extra.detail)
        kept, parts, first = self.targets(outcome, row, text)
        if not kept and not parts:
            self.drop_row(row, first)
            return
        zones = {self.zone(school) for school, _level, _anchored in kept}
        voters = [school for school in parts if self.zone(school) is not None]
        zones |= {self.zone(school) for school in voters}
        known = sorted(zone for zone in zones if zone is not None)
        if len(known) != len(zones) or not known:
            self.drop_row(row, Drop.ZONE_UNKNOWN)
            return
        results: dict[str, tuple[Parsed, Entry | Drop]] = {}
        for zone in known:
            self.check_zone(zone)
            parsed = self.inputs.parse(text, posted_at=captured, tz=zone)
            gate = self.gate(parsed, row, captured=captured, zone=zone, text=text, extra=extra)
            results[zone] = (parsed, gate)
        if any(parsed.on(self.target) is not None for parsed, _gate in results.values()):
            self.entries += 1
        claim, drop = self.row_claim(results, known[0], claims=bool(kept))
        if drop is not None:
            self.drop_row(row, drop)
        for school, level, anchored in kept:
            zone = self.zones[school.id] or known[0]
            mine, _gate = results[zone]
            entry = mine.on(self.target)
            kind = None if drop is Drop.ZONE_SPLIT or entry is None else entry.kind
            vote = vote_of(
                mine,
                entry,
                self.target,
                text=text,
                name=row.name,
                detail=extra.detail,
                posted=captured.astimezone(ZoneInfo(zone)).date(),
            )
            if drop is Drop.ZONE_SPLIT and vote != OPEN_VOTE:
                vote = DISPUTED_VOTE
            self.readings[(station.id, row.fetched_at, school.id)].append(
                Reading(
                    row=row,
                    level=level,
                    kind=kind,
                    claim=claim,
                    drop=drop,
                    vote=vote,
                    anchored=anchored,
                )
            )
            self.touched[station.id].add(school.id)
        readings = {zone: parsed for zone, (parsed, _gate) in results.items()}
        self.vote_parts(row, voters, readings, text=text, detail=extra.detail, captured=captured)

    def row_claim(
        self, results: Mapping[str, tuple[Parsed, Entry | Drop]], first: str, *, claims: bool
    ) -> tuple[Claim | None, Drop | None]:
        """A row's one claim for all its schools, or its drop: ``ZONE_SPLIT`` when its zones'
        readings disagree, ``PART_OF_DISTRICT`` when it reaches no school it may light."""
        parsed, gate = results[first]
        if len({_signature(p, g, self.target) for p, g in results.values()}) > 1:
            return None, Drop.ZONE_SPLIT
        if not claims:
            return None, Drop.PART_OF_DISTRICT
        if isinstance(gate, Drop):
            if gate is Drop.NOTE:
                self.note_drops.update(rejected_notes(parsed))
            return None, gate
        claim = Claim(
            kind=gate.kind,
            status=STATUS_BY_KIND[gate.kind],
            reason=REASON_BY_LABEL.get(parsed.reason) if parsed.reason else None,
            dated=gate.dates_stated,
            notes=tuple(sorted(set(parsed.notes))),
        )
        return claim, None

    def vote_parts(  # noqa: PLR0913 - one row, its part schools and its words
        self,
        row: ListRow,
        parts: Sequence[School],
        readings: Mapping[str, Parsed],
        *,
        text: str,
        detail: str,
        captured: datetime,
    ) -> None:
        """Record what a district row that names part of the district says of each of its
        schools (:func:`part_vote`): it never lights them, but it stands against any claim."""
        station_id = self.inputs.registry.stations[row.source_id].id
        first = min(readings)
        for school in parts:
            zone = self.zones[school.id] or first
            mine = readings[zone]
            entry = mine.on(self.target)
            self.readings[(station_id, row.fetched_at, school.id)].append(
                Reading(
                    row=row,
                    level="district",
                    kind=None if entry is None else entry.kind,
                    claim=None,
                    drop=Drop.PART_OF_DISTRICT,
                    vote=part_vote(
                        mine,
                        entry,
                        self.target,
                        text=text,
                        name=row.name,
                        detail=detail,
                        posted=captured.astimezone(ZoneInfo(zone)).date(),
                    ),
                )
            )
            self.touched[station_id].add(school.id)


def part_vote(  # noqa: PLR0913 - one reading and the row's words
    parsed: Parsed,
    entry: Entry | None,
    day: date,
    *,
    text: str,
    name: str,
    detail: str = "",
    posted: date | None = None,
) -> str | None:
    """What a district row that names part of the district says about each of its schools.

    Open when it says so ("Open; no AM preschool", "Open - north campus closed");
    otherwise disputed when it says anything for ``day`` ("2 hr delay - JHS",
    "K-8 closed") or may be about it (:func:`~snowlight.replays.gates.speaks_for`):
    the district's status is narrowed to some of its schools, so no other row or
    list may speak for the rest. A row about other days only says nothing of the
    day.
    """
    vote = vote_of(parsed, entry, day, text=text, name=name, detail=detail, posted=posted)
    if vote == OPEN_VOTE:
        return OPEN_VOTE
    if vote is not None or speaks_for(parsed, entry, day, text, posted):
        return DISPUTED_VOTE
    return None


def _signature(parsed: Parsed, gate: Entry | Drop, day: date) -> tuple[str, ...]:
    """What a zone's reading of a row comes to: its claim, or its drop and the day's kind."""
    if isinstance(gate, Drop):
        entry = parsed.on(day)
        return ("drop", gate.value, entry.kind if entry is not None else "")
    return ("claim", gate.kind, parsed.reason or "")


# --- step 5: settle -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaptureState:
    """What one capture of a station says about one school."""

    listed: bool
    """Whether any row of the capture reaches the school."""
    claim: CaptureClaim | None = None
    """The counted claim, when every row that speaks for the day agrees on it."""
    votes: frozenset[str] = frozenset()
    """What the rows say for the day, counted or not (:func:`vote_of`)."""
    keeps: str | None = None
    """The one kind, when every row is that kind and uncounted only for its window."""
    conflict: bool = False
    """The rows disagree (a school row and its district's row alike)."""
    unanchored: bool = False
    """The only counted rows name the school by a name alone (:meth:`_Day.anchored`)."""


OMITTED: Final = CaptureState(listed=False)


def capture_state(readings: Sequence[Reading]) -> CaptureState:
    """What one capture says about one school (see :class:`CaptureState`).

    Every row that reaches the school counts the same, whether it names the
    school or its district: a row naming the school does not override its
    district's row, since the school row may be a wrong match (a private school
    of the same name). A counted claim stands only when every other row that
    says something for the day (:func:`vote_of`) is the same kind, uncounted only
    for its window; a row about another day, or one the reader recognizes nothing
    in, does not stand in its way. A claim whose only rows name the school by a
    name alone stands only beside an anchored row (its district's) that agrees.
    """
    if not readings:
        return OMITTED
    votes = frozenset(reading.vote for reading in readings if reading.vote is not None)
    claims = [reading.claim for reading in readings if reading.claim is not None]
    if not claims:
        found = {reading.kind for reading in readings}
        kind = next(iter(found)) if len(found) == 1 else None
        windowed = all(reading.drop is Drop.OUTSIDE_WINDOW for reading in readings)
        return CaptureState(listed=True, votes=votes, keeps=kind if windowed else None)
    first = claims[0]
    if len({claim.status for claim in claims}) > 1 or any(
        reading.claim is None
        and reading.vote is not None
        and not (reading.drop is Drop.OUTSIDE_WINDOW and reading.kind == first.kind)
        for reading in readings
    ):
        return CaptureState(listed=True, votes=votes, conflict=True)
    evidence = tuple(reading for reading in readings if reading.claim is not None)
    if not any(reading.anchored for reading in evidence):
        return CaptureState(listed=True, votes=votes, unanchored=True)
    reasons = {claim.reason for claim in claims}
    merged = Claim(
        kind=first.kind,
        status=first.status,
        reason=first.reason if len(reasons) == 1 else None,
        dated=all(claim.dated for claim in claims),
        notes=tuple(sorted({note for claim in claims for note in claim.notes})),
    )
    return CaptureState(listed=True, claim=CaptureClaim(merged, evidence), votes=votes)


def supersede(states: Iterable[CaptureState]) -> CaptureClaim | Drop | None:
    """Fold one station's captures of a school, oldest first, over all its list variants.

    A capture with a counted claim sets it. A capture that lists the school
    uncounted with the claim's own kind keeps it. Anything else (an omission,
    another reading, a conflict, a claim by a name alone) voids it. Returns the
    claim that stands, or why none does (``None`` when there never was one).
    """
    current: CaptureClaim | None = None
    last: Drop | None = None
    for state in states:
        if state.claim is not None:
            current, last = state.claim, None
        elif current is not None and state.keeps == current.claim.kind:
            continue
        else:
            if current is not None:
                last = Drop.SUPERSEDED
            elif state.unanchored and last is None:
                last = Drop.UNANCHORED
            if state.conflict:
                last = Drop.CONFLICT_IN_LIST
            current = None
    return current if current is not None else last


@dataclass(frozen=True, slots=True)
class StationView:
    """One station's settled word on a school."""

    result: CaptureClaim | Drop | None
    """Its standing claim, why its claim fell (superseded, conflict in its list), or nothing."""
    vote: frozenset[str]
    """What its latest capture that lists the school says for the day (:func:`vote_of`)."""
    untied_void: bool = False
    """Its claim fell to a later read whose rows did not tie to it."""


def station_view(
    day: "_Day", station_id: str, sid: str, reads: Sequence[Read], tied: Set[tuple[str, str]]
) -> StationView:
    """One station's view of a school over all its list variants (see :func:`supersede`)."""
    zone = day.zones[sid]
    if zone is None:  # pragma: no cover - a reading is kept only for a known zone
        return StationView(None, frozenset())
    window = [
        read
        for read in reads
        if in_window(instant(read.fetched_at), day.window_day, zone, dated=True)
    ]
    states = [
        capture_state(day.readings.get((station_id, read.fetched_at, sid), ())) for read in window
    ]
    result = supersede(states)
    listed = [state for state in states if state.listed]
    vote = listed[-1].votes if listed else frozenset()
    untied_void = False
    if result is Drop.SUPERSEDED:
        claimed = max(i for i, state in enumerate(states) if state.claim is not None)
        standing = states[claimed].claim
        kind = standing.claim.kind if standing is not None else None
        voider = next(i for i in range(claimed + 1, len(states)) if states[i].keeps != kind)
        read = window[voider]
        untied_void = (read.source_id, read.fetched_at) not in tied
    return StationView(result, vote, untied_void)


def _settle(day: _Day) -> tuple[dict[str, Lit], list[str], Counter[str], int]:
    inputs = day.inputs
    captures = window_reads(inputs.loaded, day.window_day)
    tied = {(row.source_id, row.fetched_at) for row in inputs.loaded.rows}
    school_drops: Counter[str] = Counter()
    untied_voids = 0
    views: dict[str, list[tuple[str, StationView]]] = defaultdict(list)
    for station_id in sorted(day.touched):
        reads = captures.get(station_id, ())
        for sid in sorted(day.touched[station_id]):
            view = station_view(day, station_id, sid, reads, tied)
            views[sid].append((station_id, view))
            if isinstance(view.result, Drop):
                school_drops[view.result.value] += 1
                untied_voids += view.untied_void
    lit: dict[str, Lit] = {}
    conflicts: list[str] = []
    for sid, by_station in sorted(views.items()):
        claims = [
            (station, view.result)
            for station, view in by_station
            if isinstance(view.result, CaptureClaim)
        ]
        if not claims:
            continue
        if len(frozenset().union(*(view.vote for _station, view in by_station))) > 1:
            conflicts.append(sid)
            school_drops[Drop.CONFLICT.value] += 1
            continue
        if any(
            isinstance(view.result, Drop) and view.result is not Drop.UNANCHORED
            for _station, view in by_station
        ):
            school_drops[Drop.WITHDRAWN.value] += 1
            continue
        reasons_named = {item.claim.reason for _station, item in claims}
        first = claims[0][1].claim
        lit[sid] = Lit(
            school=sid,
            status=first.status,
            reason=first.reason if len(reasons_named) == 1 else None,
            stations=tuple(sorted(station for station, _item in claims)),
            evidence=tuple(r for _station, item in claims for r in item.evidence),
            school_type=inputs.directory.schools[sid].school_type,
        )
    _check_invariants(lit, inputs)
    return lit, conflicts, school_drops, untied_voids


def _check_invariants(lit: Mapping[str, Lit], inputs: DayInputs) -> None:
    """A4: no lit school outside its stations' states; no light from an off-list source.

    Raises:
        BuildError: either invariant fails.
    """
    for item in lit.values():
        school = inputs.directory.schools[item.school]
        for station_id in item.stations:
            station = inputs.registry.stations[station_id]
            if station.platform not in REPLAY_PLATFORMS or station.leaids:
                raise BuildError(f"{item.school} is lit from {station_id}, an excluded source")
            if school.state not in station.states:
                raise BuildError(f"{item.school} ({school.state}) is lit from {station_id}")


def _extras(inputs: DayInputs, key: tuple[str, str], rows: Sequence[ListRow]) -> Sequence[RowExtra]:
    """The read's rows' extras, row for row (none when the run has no extras).

    Raises:
        BuildError: the extras hold another number of rows than the read.
    """
    found = inputs.extras.get(key)
    if found is None:
        return [NO_EXTRA] * len(rows)
    if len(found) != len(rows):
        raise BuildError(f"{key[0]} at {key[1]}: {len(found)} extras for {len(rows)} rows")
    return found


def _untied(inputs: DayInputs, window_day: date) -> tuple[tuple[str, str, int], ...]:
    tied = {(row.source_id, row.fetched_at) for row in inputs.loaded.rows}
    return tuple(
        (read.source_id, read.fetched_at, read.rows)
        for reads in window_reads(inputs.loaded, window_day).values()
        for read in reads
        if (read.source_id, read.fetched_at) not in tied
    )


def settle_day(
    inputs: DayInputs, target: date, window_day: date | None = None, *, check_range: bool = True
) -> Settled:
    """Run steps 2-6 for ``target`` over the captures in ``window_day``'s window.

    ``check_range=False`` leaves out the date-range gate (the D+7 control).
    """
    day = _Day(
        inputs=inputs, target=target, window_day=window_day or target, check_range=check_range
    )
    rows = day_rows(inputs.loaded, day.window_day)
    reads = {(read.source_id, read.fetched_at): read for read in inputs.loaded.reads if read.rows}
    checks: list[ReadCheck] = []
    for (source, fetched_at), read_rows in sorted(rows_by_read(rows).items()):
        station = inputs.registry.stations.get(source)
        drop = source_drop(station)
        if drop is not None or station is None:
            for row in read_rows:
                day.drop_row(row, drop or Drop.UNKNOWN_SOURCE)
            continue
        extras = _extras(inputs, (source, fetched_at), read_rows)
        check = day.check_read(station, read_rows, reads[(source, fetched_at)], extras)
        checks.append(check)
        if check.drop is not None:
            for row in read_rows:
                day.drop_row(row, check.drop)
            continue
        captured = instant(fetched_at)
        for row, extra in zip(read_rows, extras, strict=True):
            day.read_row(row, captured, extra)
    lit, conflicts, school_drops, untied_voids = _settle(day)
    return Settled(
        target=target,
        rows_in=len(rows),
        lit=lit,
        conflicts=tuple(conflicts),
        row_drops=dict(sorted(day.row_drops.items())),
        target_drops=dict(sorted(day.target_drops.items())),
        school_drops=dict(sorted(school_drops.items())),
        note_drops=dict(sorted(day.note_drops.items())),
        reads=tuple(checks),
        dropped=tuple(day.dropped),
        entries=day.entries,
        untied=_untied(inputs, day.window_day),
        untied_voids=untied_voids,
    )


# --- the bar and the seed -----------------------------------------------------------------------


def market_of(station: Station) -> str:
    """A station's market for the bar: its DMA label, else the market the research recorded."""
    return station.dma or station.market


def quality_of(settled: Settled, registry: Registry) -> Quality:
    """The day's headline numbers."""
    stations = sorted({station for item in settled.lit.values() for station in item.stations})
    return Quality(
        lit=len(settled.lit),
        sources=len(stations),
        markets=len({market_of(registry.stations[station]) for station in stations}),
        corroborated=sum(1 for item in settled.lit.values() if item.corroborated),
        conflicts=len(settled.conflicts),
    )


def keep_share(ids: Iterable[str], directory_ids: Set[str]) -> float:
    """The share of ``ids`` a directory still holds (1.0 for none)."""
    wanted = list(ids)
    if not wanted:
        return 1.0
    return sum(1 for sid in wanted if sid in directory_ids) / len(wanted)


def day_bar(
    day: date,
    public_year: int,
    quality: Quality,
    control: ControlResult,
    kept: float,
) -> tuple[str, ...]:
    """The automatic bar's failures, A1-A6 (A4 raises in :func:`settle_day`; A7 is the CLI's)."""
    failures: list[str] = []
    gate = day_ok(day, public_year)
    if gate is not None:
        failures.append(f"A1: {gate.value}")
    if quality.lit < MIN_LIT or quality.sources < MIN_SOURCES or quality.markets < MIN_MARKETS:
        failures.append(
            f"A2: {quality.lit} lit from {quality.sources} sources in {quality.markets} markets "
            f"(at least {MIN_LIT}, {MIN_SOURCES}, {MIN_MARKETS})"
        )
    seen = quality.lit + quality.conflicts
    if seen and quality.conflicts / seen > MAX_CONFLICT_SHARE:
        failures.append(f"A3: {quality.conflicts} conflicts of {seen}")
    if not control.passed:
        failures.append(f"A5: the D+7 control lights {control.lit}")
    if kept < MIN_KEEP_SHARE:
        failures.append(f"A6: a publish keeps {kept:.2%} of ids")
    return tuple(failures)


def seed_statuses(lit: Mapping[str, Lit]) -> tuple[tuple[str, int, int | None, str], ...]:
    """The seed's ``[nces_id, status, reason, source_type]`` rows, sorted by id."""
    return tuple(
        (sid, int(item.status), None if item.reason is None else int(item.reason), SOURCE_TYPE)
        for sid, item in sorted(lit.items())
    )


def built_for(  # noqa: PLR0913 - one hash per input
    *,
    rules_sha256: str,
    reader_sha256: str,
    matcher_sha256: str,
    registry_sha256: str,
    archive_sha256: str,
    zones_sha256: str,
    directory_generated_on: str,
) -> Built:
    """The ``built`` block: these rules, with the given input hashes."""
    return Built(
        rules=RULES,
        rules_sha256=rules_sha256,
        min_confidence=MIN_CONFIDENCE,
        allowed_notes=tuple(sorted(ALLOWED_NOTES)),
        reader_sha256=reader_sha256,
        matcher_sha256=matcher_sha256,
        registry_sha256=registry_sha256,
        archive_sha256=archive_sha256,
        zones_sha256=zones_sha256,
        directory_generated_on=directory_generated_on,
    )


@dataclass(frozen=True, slots=True)
class DayBuild:
    """One built day: its seed, the parts of its report, and its bar."""

    day: date
    seed: ReplaySeed
    settled: Settled
    control: ControlResult
    passed: bool
    failures: tuple[str, ...]
    public_year: int = 0
    """The directory's public school year (its first year)."""


def control_lighter(inputs: DayInputs, day: date) -> Callable[[date], tuple[int, int]]:
    """The D+7 control's run: day's captures, a later target, no date-range gate."""

    def light(target: date) -> tuple[int, int]:
        settled = settle_day(inputs, target, window_day=day, check_range=False)
        return len(settled.lit), settled.entries

    return light


def build_day(
    day: date, inputs: DayInputs, *, built: Built, publish_ids: Set[str] | None = None
) -> DayBuild:
    """Build ``day``: settle it, run the D+7 control, and hold it to the bar.

    ``publish_ids`` are the ids of the directory a publish would map the seed
    to (A6); by default the build's own directory.

    Raises:
        BuildError: an invariant fails (A4) or the inputs disagree.
    """
    settled = settle_day(inputs, day)
    control = control_day(day, control_lighter(inputs, day))
    quality = quality_of(settled, inputs.registry)
    statuses = seed_statuses(settled.lit)
    seed = ReplaySeed.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "id": day.isoformat(),
            "day": day.isoformat(),
            "built": built,
            "quality": quality,
            "statuses": statuses,
        },
        strict=False,
    )
    ids = publish_ids if publish_ids is not None else set(inputs.directory.schools)
    failures = day_bar(
        day,
        inputs.directory.public_year,
        quality,
        control,
        keep_share((status[0] for status in statuses), ids),
    )
    return DayBuild(
        day=day,
        seed=seed,
        settled=settled,
        control=control,
        passed=not failures,
        failures=failures,
        public_year=inputs.directory.public_year,
    )

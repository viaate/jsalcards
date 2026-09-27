"""Cross-checks of the bulk school-year files against the pipeline's other readers.

Day files
=========

The weather check reads IEM's archive one UTC day at a time through
:class:`snowlight.sources.nws.iem.IemArchive` (zipped shapefiles). The weights
read whole school years as CSV (:mod:`snowlight.weights.archive`). For each
window in :data:`WINDOWS`, :func:`compare_days` fetches the existing client's day
files (for the closure-type codes, into this build's cache), and compares:

* rows: every county/zone row beginning in the window, keyed by event, UGC,
  begin and end, must appear in both;
* county days: for each county in :data:`CHECK_COUNTIES` (chosen across the
  country before the check was run) and each school day of the window, the codes
  that count under the 6 AM rule, computed from each source with the same zone
  mapping. Day-file rows get their product time from the head of their product
  id (``YYYYMMDDHHMM-...``), as the CSV's ``utc_prodissue`` is.

A window's rows are read from the day files of the week before it too, so that
an event already in effect when the window starts is seen by both.

Zone names before the first correlation release
===============================================

Products issued before 2 April 2019 are read in the earliest correlation release
(:mod:`snowlight.weights.zones`). :func:`compare_zone_names` compares, for each
zone so read, its name in that release with the name IEM's UGC database gave it
in the middle of each school year concerned
(``https://mesonet.agron.iastate.edu/api/1/nws/ugcs.json?valid=YYYY-01-15T12:00Z``).
The names agree (:func:`names_agree`) when they are the same once case and
punctuation are dropped, when one holds the other (``Chester`` and ``Western
Chester``; the long forms IEM gives California's mountain zones), when they
differ by spelling only (similarity of at least :data:`SPELLING` in
:func:`rapidfuzz.fuzz.ratio`, e.g. ``Uncompahgre Plateu`` and ``Plateau``, or of
:data:`PARTIAL_SPELLING` in :func:`rapidfuzz.fuzz.partial_ratio`, a misspelt
shorter form: ``North Central Cascdes`` and ``North Central Cascades and
Passes``), or when
IEM's name still names every county the release gives the zone (``Inland Pasco``
and ``Coastal Pasco``, both Pasco County). Otherwise the zone's code may have
meant another area then, and the build leaves the zone out for that school year,
unless IEM's archived outline of the zone at that time covers the counties the
release lists (:mod:`snowlight.weights.outlines`; ``NameCheck.kept_by_outline``).
"""

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from rapidfuzz import fuzz

from snowlight.output import JSONValue
from snowlight.sources.nws.iem import ArchiveRow, IemArchive
from snowlight.weather.hazards import CONUS_STATES
from snowlight.weights.archive import (
    EventRow,
    ReadStats,
    SchoolYearFile,
    close_open_tropical,
)
from snowlight.weights.cache import WeightsCache
from snowlight.weights.codes import BY_CODE, code_pairs
from snowlight.weights.count import counted_days, school_days, school_year_of
from snowlight.weights.zones import CountyList, ZoneCountyCatalog, ZoneRelease

WINDOWS: tuple[tuple[date, date], ...] = (
    (date(2025, 2, 3), date(2025, 2, 14)),
    (date(2024, 9, 23), date(2024, 9, 27)),
)
"""School-day windows compared (inclusive): a stormy fortnight of winter 2025 and
the week Hurricane Helene came ashore."""
LOOKBACK = timedelta(days=7)
CHECK_COUNTIES: tuple[str, ...] = (
    "44007",  # Providence, RI
    "25025",  # Suffolk, MA
    "36029",  # Erie, NY
    "36061",  # New York, NY
    "26163",  # Wayne, MI
    "26081",  # Kent, MI
    "27053",  # Hennepin, MN
    "42003",  # Allegheny, PA
    "42101",  # Philadelphia, PA
    "17031",  # Cook, IL
    "39049",  # Franklin, OH
    "55079",  # Milwaukee, WI
    "19153",  # Polk, IA
    "38017",  # Cass, ND
    "08031",  # Denver, CO
    "49035",  # Salt Lake, UT
    "53033",  # King, WA
    "06037",  # Los Angeles, CA
    "48113",  # Dallas, TX
    "13121",  # Fulton, GA
    "37119",  # Mecklenburg, NC
    "37021",  # Buncombe, NC
    "47037",  # Davidson, TN
    "28049",  # Hinds, MS
    "22071",  # Orleans, LA
    "12086",  # Miami-Dade, FL
    "12073",  # Leon, FL
    "51059",  # Fairfax, VA
    "21111",  # Jefferson, KY
    "30111",  # Yellowstone, MT
)
UGCS_URL = "https://mesonet.agron.iastate.edu/api/1/nws/ugcs.json"
SPELLING = 90.0
PARTIAL_SPELLING = 95.0
_COUNTY_WORDS = re.compile(r"\b(county|parish|city of|city)\b")
_PRODUCT_TIME = re.compile(r"^(\d{12})-")

type RowKey = tuple[str, str, datetime, datetime]


def _product_time(product_id: str) -> datetime | None:
    found = _PRODUCT_TIME.match(product_id)
    if found is None:
        return None
    return datetime.strptime(found[1], "%Y%m%d%H%M").replace(tzinfo=UTC)


def event_rows_from_day_files(rows: Iterable[ArchiveRow]) -> tuple[list[EventRow], int]:
    """Turn day-file rows into :class:`EventRow` (county/zone rows of the contiguous states).

    Returns the rows and the number of county/zone rows left out because a time
    or the product time was missing.
    """
    kept: list[EventRow] = []
    missing = 0
    for row in rows:
        code = f"{row.phenomena}.{row.significance}"
        if row.gtype != "C" or row.ugc is None or code not in BY_CODE:
            continue
        if row.ugc[:2] not in CONUS_STATES:
            continue
        issued = _product_time(row.product_id)
        if row.issued is None or row.expired is None or issued is None:
            missing += 1
            continue
        kept.append(
            EventRow(
                wfo=row.wfo,
                code=code,
                etn=row.etn,
                vtec_year=row.vtec_year,
                status=row.status,
                ugc=row.ugc,
                begin=row.issued,
                end=row.expired,
                product_issued=issued,
                product_id=row.product_id,
            )
        )
    return kept, missing


def _key(row: EventRow) -> RowKey:
    return (row.event_key, row.ugc, row.begin, row.end)


@dataclass(frozen=True, slots=True)
class CountyMapper:
    """What turns a row into counties and their time zones."""

    catalog: ZoneCountyCatalog
    counties: CountyList


def county_codes_by_day(
    rows: Iterable[EventRow],
    days: Sequence[date],
    fips_codes: Iterable[str],
    mapper: CountyMapper,
) -> dict[tuple[str, date], frozenset[str]]:
    """Return, for each (county, day), the codes that count under the 6 AM rule."""
    wanted = set(fips_codes)
    window = set(days)
    found: dict[tuple[str, date], set[str]] = defaultdict(set)
    for row in rows:
        for fips in mapper.catalog.counties(row.ugc, row.product_issued.date()) & wanted:
            county = mapper.counties.counties.get(fips)
            if county is None:
                continue
            hits = counted_days(row.begin, row.end, row.product_issued, county.time_zones)
            for day in hits & window:
                found[(fips, day)].add(row.code)
    return {
        (fips, day): frozenset(found.get((fips, day), ()))
        for fips in sorted(wanted)
        for day in days
    }


@dataclass(slots=True)
class WindowCheck:
    """The comparison for one window."""

    first: date
    last: date
    day_files: int = 0
    day_rows_without_times: int = 0
    rows_csv: int = 0
    rows_day_files: int = 0
    rows_matched: int = 0
    only_csv: list[str] = field(default_factory=list)
    only_day_files: list[str] = field(default_factory=list)
    county_days: int = 0
    county_days_agree: int = 0
    county_days_with_events: int = 0
    disagreements: list[str] = field(default_factory=list)
    counties: Mapping[str, dict[str, int]] = field(default_factory=dict)

    def as_json(self) -> dict[str, JSONValue]:
        """Return the JSON-ready record kept in the internal report."""
        return {
            "first_day": self.first.isoformat(),
            "last_day": self.last.isoformat(),
            "day_files": self.day_files,
            "day_rows_without_times": self.day_rows_without_times,
            "rows_csv": self.rows_csv,
            "rows_day_files": self.rows_day_files,
            "rows_matched": self.rows_matched,
            "rows_only_csv": list(self.only_csv[:50]),
            "rows_only_day_files": list(self.only_day_files[:50]),
            "county_days": self.county_days,
            "county_days_agree": self.county_days_agree,
            "county_days_with_events": self.county_days_with_events,
            "disagreements": list(self.disagreements[:50]),
            "counties": {fips: dict(counts) for fips, counts in self.counties.items()},
        }


def _describe(key: RowKey) -> str:
    event, ugc, begin, end = key
    return f"{event} {ugc} {begin:%Y-%m-%dT%H:%MZ}..{end:%Y-%m-%dT%H:%MZ}"


def compare_window(
    window: tuple[date, date],
    csv_rows: Sequence[EventRow],
    day_rows: Sequence[EventRow],
    mapper: CountyMapper,
    fips_codes: Sequence[str] = CHECK_COUNTIES,
) -> WindowCheck:
    """Compare the two sources over the school days ``window`` (inclusive).

    Rows are compared when they begin in the UTC days the day files cover: from
    :data:`LOOKBACK` before the window to the day after it.
    """
    first, last = window
    check = WindowCheck(first, last)
    start = datetime.combine(first - LOOKBACK, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(last + timedelta(days=2), datetime.min.time(), tzinfo=UTC)
    csv_keys = {_key(row) for row in csv_rows if start <= row.begin < end}
    day_keys = {_key(row) for row in day_rows if start <= row.begin < end}
    check.rows_csv, check.rows_day_files = len(csv_keys), len(day_keys)
    check.rows_matched = len(csv_keys & day_keys)
    check.only_csv = [_describe(key) for key in sorted(csv_keys - day_keys)]
    check.only_day_files = [_describe(key) for key in sorted(day_keys - csv_keys)]
    days = [day for day in school_days(school_year_of(first)) if first <= day <= last]
    from_csv = county_codes_by_day(csv_rows, days, fips_codes, mapper)
    from_days = county_codes_by_day(day_rows, days, fips_codes, mapper)
    per_county: dict[str, dict[str, int]] = {}
    for (fips, day), codes in sorted(from_csv.items()):
        other = from_days[(fips, day)]
        counts = per_county.setdefault(fips, {"days": 0, "agree": 0, "with_events": 0})
        counts["days"] += 1
        check.county_days += 1
        if codes or other:
            counts["with_events"] += 1
            check.county_days_with_events += 1
        if codes == other:
            counts["agree"] += 1
            check.county_days_agree += 1
        else:
            check.disagreements.append(
                f"{fips} {day}: csv {sorted(codes)} day files {sorted(other)}"
            )
    check.counties = per_county
    return check


def compare_days(
    archive: IemArchive,
    files: Sequence[SchoolYearFile],
    mapper: CountyMapper,
    windows: Sequence[tuple[date, date]] = WINDOWS,
) -> list[WindowCheck]:
    """Run :func:`compare_window` for each window, fetching the day files it needs."""
    by_year = {file.year: file for file in files}
    checks = []
    for first, last in windows:
        source = by_year.get(school_year_of(first))
        if source is None:
            raise ValueError(f"no school-year file holds {first}")
        day = first - LOOKBACK
        raw: list[ArchiveRow] = []
        count = 0
        while day <= last + timedelta(days=1):
            raw.extend(archive.day(day).rows)
            count += 1
            day += timedelta(days=1)
        converted, missing = event_rows_from_day_files(raw)
        day_rows = close_open_tropical(converted, ReadStats())
        lookback = datetime.combine(first - LOOKBACK, datetime.min.time(), tzinfo=UTC)
        csv_rows = [row for row in source.rows if row.begin >= lookback]
        check = compare_window((first, last), csv_rows, day_rows, mapper)
        check.day_files = count
        check.day_rows_without_times = missing
        checks.append(check)
    return checks


def make_day_archive(cache: WeightsCache) -> IemArchive:
    """Return the existing day-file client, for the closure-type codes, on this cache."""
    return IemArchive(cache.cache, cache.root, code_pairs(), CONUS_STATES)


def ugcs_url(valid: datetime) -> str:
    """Return the IEM UGC database request for the codes valid at ``valid``."""
    return f"{UGCS_URL}?valid={valid.astimezone(UTC):%Y-%m-%dT%H:%M}Z"


def read_ugc_names(text: str) -> dict[str, str]:
    """Return UGC code to name from a ``ugcs.json`` answer.

    Raises:
        ValueError: the answer is not the documented table.
    """
    document = json.loads(text)
    rows = document.get("data") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise ValueError("ugcs.json: no data table")
    names: dict[str, str] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("ugc"), str):
            names[str(row["ugc"])] = str(row.get("name") or "")
    return names


def _normal(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _words(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def names_agree(ours: str, theirs: str, county_names: Iterable[str]) -> str | None:
    """Return why two names of one zone code agree, or ``None`` when they do not."""
    a, b = _normal(ours), _normal(theirs)
    if a == b:
        return "same name"
    if (
        a
        and b
        and (a in b or b in a or _words(ours) <= _words(theirs) or _words(theirs) <= _words(ours))
    ):
        return "one name holds the other"
    if fuzz.ratio(a, b) >= SPELLING or fuzz.partial_ratio(a, b) >= PARTIAL_SPELLING:
        return "spelling"
    counties = [_normal(_COUNTY_WORDS.sub(" ", name.lower())) for name in county_names]
    if counties and all(county and county in b for county in counties):
        return "names the same counties"
    return None


@dataclass(slots=True)
class NameCheck:
    """Zone names in the earliest release against IEM's, for one school year."""

    year: int
    valid: str
    zones: int = 0
    same: int = 0
    agreeing: list[str] = field(default_factory=list)
    """Zones whose names differ but agree (with the reason)."""
    left_out: list[str] = field(default_factory=list)
    """Zones whose names disagree: left out for the school year."""
    missing_in_iem: list[str] = field(default_factory=list)
    kept_by_outline: list[str] = field(default_factory=list)
    """Zones whose names disagree but whose outline then covered the release's counties."""

    def as_json(self) -> dict[str, JSONValue]:
        """Return the JSON-ready record kept in the internal report."""
        return {
            "school_year_start": self.year,
            "iem_valid": self.valid,
            "zones": self.zones,
            "same_name": self.same,
            "different_but_agreeing": list(self.agreeing),
            "left_out": list(self.left_out),
            "kept_by_outline": list(self.kept_by_outline),
            "missing_in_iem": list(self.missing_in_iem),
        }

    @property
    def left_out_zones(self) -> list[str]:
        """The zone codes left out."""
        return [entry.split(":", 1)[0] for entry in self.left_out]


def compare_zone_names(
    cache: WeightsCache,
    zones_by_year: Mapping[int, set[str]],
    release: ZoneRelease,
) -> list[NameCheck]:
    """Compare the release's names of ``zones_by_year`` with IEM's for each school year."""
    checks = []
    for year in sorted(zones_by_year):
        valid = datetime(year + 1, 1, 15, 12, tzinfo=UTC)
        url = ugcs_url(valid)
        dest = cache.root / "mesonet.agron.iastate.edu" / "api-ugcs" / f"{valid:%Y-%m-%d}.json"
        file = cache.fetch(url, dest)
        iem = read_ugc_names(file.path.read_text(encoding="utf-8"))
        check = NameCheck(year, f"{valid:%Y-%m-%dT%H:%MZ}")
        for ugc in sorted(zones_by_year[year]):
            check.zones += 1
            theirs = iem.get(ugc)
            ours = release.names.get(ugc, "")
            if theirs is None:
                check.missing_in_iem.append(ugc)
                continue
            reason = names_agree(ours, theirs, release.county_names.get(ugc, ()))
            if reason == "same name":
                check.same += 1
            elif reason is not None:
                check.agreeing.append(f"{ugc}: release {ours!r}, IEM {theirs!r} ({reason})")
            else:
                counties = ", ".join(sorted(release.county_names.get(ugc, ())))
                check.left_out.append(f"{ugc}: release {ours!r} ({counties}), IEM {theirs!r}")
        checks.append(check)
    return checks

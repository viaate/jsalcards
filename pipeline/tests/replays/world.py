"""SYNTHETIC worlds for the replay tests. None of it describes a real school, station or list.

* :func:`stub_parse` is a stand-in for the status reader (f5) that reads a tiny
  made-up grammar, so the tests do not need the real reader:
  ``"closed"`` (no date: the posting day before noon local, else the next day),
  ``"remote;on=2024-01-16"`` (a stated date), and options after ``;``:
  ``conf=0.5``, ``note=hedged``, ``cause=holiday``, ``open``, ``ufn``,
  ``reason=Ice``, ``also=2024-01-06`` (another stated date); words after a note's
  value are the row's own (``note=revoked Friday 1/19``), and :data:`NOTE_CODES`
  stand for notes that take a status back. ``"nothing"`` is a
  text it recognizes nothing in (confidence 0.1). ``"open"`` is read as the real
  reader reads "Open" or "On time" (kind ``other``, no schedule, ``says_open``),
  and ``"conflict"`` as it reads "Closed. 2 hour delay" (kind ``other`` at 0.25,
  note ``conflict``). ``"revoked"``, ``"negated"`` and ``"partial"`` are read as
  it reads "Closing rescinded", "No delay" and "Closed. Lincoln Elementary open."
  (kind ``other`` at 0.9, no schedule, note ``revoked``, ``negated`` or
  ``partial_program``), and ``"ambiguous"`` as "Closed - CANCELED" (kind ``other``
  at 0.3, note ``ambiguous``). Like the real reader, a status
  with no date of its own carries no note. Words after ``". "`` are the row's
  comments (:func:`snowlight.replays.rows.reader_text`): one that says
  ``learning`` makes the reading remote, as the real reader does with "AMI Day".
* :class:`World` builds a registry of invented stations, reads and rows, the
  matcher's answers for them, and a directory of invented schools (ids ``99...``).
"""

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
import shapely

from snowlight.listed.build import row_query
from snowlight.listed.evidence import ListRow, LoadedRows, Read
from snowlight.listed.matching import Outcome, Query
from snowlight.replays.build import (
    DayInputs,
    Directory,
    MatchBook,
    School,
    allowed_rows,
    book_from,
)
from snowlight.replays.gates import ParseFn
from snowlight.replays.rows import RowExtra, detail_of
from snowlight.sources.stations.registry import PlatformFile, Registry
from snowlight.weights.zones import County, CountyList

DAY = date(2024, 1, 16)  # a Tuesday
CHICAGO = "America/Chicago"
DENVER = "America/Denver"
ZONES: Mapping[str, str | None] = {
    "20091": CHICAGO,
    "08001": DENVER,
    "29095": CHICAGO,
    "60050": "Pacific/Pago_Pago",
}
"""County FIPS to zone for :class:`StubZones`; any other county has none."""


@dataclass(frozen=True)
class FakeEntry:
    """A SYNTHETIC dated status, shaped like the reader's ``DatedStatus``."""

    kind: str
    dates: tuple[date, ...]
    dates_stated: bool = True
    until_further_notice: bool = False


@dataclass(frozen=True)
class FakeParsed:
    """A SYNTHETIC reading, shaped like the reader's ``ParsedStatus``."""

    kind: str
    schedule: tuple[FakeEntry, ...]
    reason: str | None = None
    other_causes: tuple[str, ...] = ()
    confidence: float = 0.95
    says_open: bool = False
    notes: tuple[str, ...] = ()

    def on(self, day: date, /) -> FakeEntry | None:
        for entry in self.schedule:
            if day in entry.dates:
                return entry
        return None


KINDS = {"closed": "closed", "delayed": "delayed", "remote": "remote", "early": "early_dismissal"}
TAKEN_BACK = {"revoked": "revoked", "negated": "negated", "partial": "partial_program"}
"""The SYNTHETIC heads for readings that take a status back, deny it or narrow it."""
NOTE_CODES = {"rv": "revoked", "ng": "negated", "ss": "superseded"}
"""Short SYNTHETIC codes for the notes that take a status back, as heads (``"rv"``) or note
values (``note=ss``): unlike ``"revoked"``, they are no retraction word, so only the row's own
words decide where its retraction stands (:func:`snowlight.replays.gates.retracts`)."""


def stub_parse(text: str, *, posted_at: datetime, tz: str) -> FakeParsed:
    """Read the SYNTHETIC grammar of the module docstring."""
    status, _, detail = text.partition(". ")
    head, *options = [part.strip() for part in status.split(";")]
    if head == "open":
        return FakeParsed(kind="other", schedule=(), confidence=0.9, says_open=True)
    if head == "conflict":
        return FakeParsed(kind="other", schedule=(), confidence=0.25, notes=("conflict",))
    if head in TAKEN_BACK or head in NOTE_CODES:
        note = TAKEN_BACK.get(head) or NOTE_CODES[head]
        return FakeParsed(kind="other", schedule=(), confidence=0.9, notes=(note,))
    if head == "ambiguous":
        return FakeParsed(kind="other", schedule=(), confidence=0.3, notes=("ambiguous",))
    if head not in KINDS:
        return FakeParsed(kind="other", schedule=(), confidence=0.1)
    local = posted_at.astimezone(ZoneInfo(tz))
    stated = [date.fromisoformat(o[3:]) for o in options if o.startswith("on=")]
    also = [date.fromisoformat(o[5:]) for o in options if o.startswith("also=")]
    if stated:
        dates, dated = tuple(stated), True
    else:
        first = local.date() if local.time() < time(12) else local.date() + timedelta(days=1)
        dates, dated = (first,), False
    notes = [o[5:].split()[0] for o in options if o.startswith("note=")]
    notes = [NOTE_CODES.get(note, note) for note in notes]
    kind = "remote" if "learning" in detail.casefold() else KINDS[head]
    entry = FakeEntry(
        kind=kind, dates=dates, dates_stated=dated, until_further_notice="ufn" in options
    )
    schedule = (entry, *(FakeEntry(kind=kind, dates=(when,)) for when in also))
    confidence = next((float(o[5:]) for o in options if o.startswith("conf=")), 0.95)
    reason = next((o[7:] for o in options if o.startswith("reason=")), "Winter storm")
    return FakeParsed(
        kind=kind,
        schedule=schedule,
        reason=reason,
        other_causes=tuple(o[6:] for o in options if o.startswith("cause=")),
        confidence=confidence,
        says_open="open" in options,
        notes=tuple(sorted(set(notes))),
    )


class StubZones:
    """A SYNTHETIC zone lookup by county (see :data:`ZONES`)."""

    def zone_for(
        self, county_fips: str | None, lat: float | None, lon: float | None, /
    ) -> str | None:
        del lat, lon
        return ZONES.get(county_fips or "")


def _sha(source: str, at: str) -> str:
    return hashlib.sha256(f"{source} {at}".encode()).hexdigest()


def utc(local: str, zone: str = CHICAGO) -> str:
    """A local ``YYYY-MM-DD HH:MM`` as a read time in UTC."""
    moment = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(zone))
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def platform_file(platform: str, stations: Sequence[dict[str, Any]]) -> PlatformFile:
    """A SYNTHETIC platform file."""
    return PlatformFile.model_validate_json(
        json.dumps(
            {
                "platform": {
                    "id": platform,
                    "name": "SYNTHETIC platform",
                    "operator": "SYNTHETIC",
                    "adapter": platform.replace("-", "_"),
                    "poll_minutes": 10,
                    "terms": {"automated_access": "unread", "summary": "SYNTHETIC", "evidence": []},
                    "notes": "SYNTHETIC",
                    "shared_paths": [],
                },
                "stations": list(stations),
            }
        )
    )


def station(
    station_id: str,
    *,
    states: Sequence[str] = ("KS", "MO"),
    market: str = "SYNTHETIC market one",
    leaids: Sequence[str] = (),
    fips: Sequence[str] = ("20091", "29095"),
) -> dict[str, Any]:
    """A SYNTHETIC station entry."""
    counties: dict[str, Any] = {"basis": "dma", "source": "SYNTHETIC", "fips": list(fips)}
    if leaids:
        counties = {"basis": "district", "source": "SYNTHETIC", "fips": list(fips)}
    body: dict[str, Any] = {
        "id": station_id,
        "platform": station_id.rsplit("-", 1)[0],
        "call_sign": "SYNT",
        "name": "SYNTHETIC station",
        "market": market,
        "dma": None,
        "states": list(states),
        "counties": counties,
        "page_url": "https://example.invalid/closings",
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": "active",
        "evidence": "SYNTHETIC",
    }
    if leaids:
        body["leaids"] = list(leaids)
    return body


def registry(*stations: dict[str, Any]) -> Registry:
    """A SYNTHETIC registry holding ``stations`` under their platforms."""
    by_platform: dict[str, list[dict[str, Any]]] = {}
    for item in stations:
        by_platform.setdefault(str(item["platform"]), []).append(item)
    return Registry({name: platform_file(name, items) for name, items in by_platform.items()})


def school(  # noqa: PLR0913 - the fields of a school
    sid: str,
    *,
    state: str = "MO",
    fips: str = "29095",
    public: bool = True,
    status: str | None = "Open",
    virtual: str | None = None,
    name: str = "SYNTHETIC school",
    district: str | None = None,
    level: str | None = None,
    school_type: str | None = None,
    enrollment: int | None = None,
    grades: tuple[str, str] | None = None,
) -> School:
    """A SYNTHETIC directory school."""
    return School(
        id=sid,
        state=state,
        public=public,
        status=status,
        county_fips=fips,
        lat=None,
        lon=None,
        virtual=virtual,
        name=name,
        district_id=district,
        level=level,
        school_type=school_type,
        enrollment=enrollment,
        grade_low=None if grades is None else grades[0],
        grade_high=None if grades is None else grades[1],
    )


def ids(prefix: str, count: int) -> list[str]:
    """``count`` SYNTHETIC public school ids (12 digits, starting ``99``)."""
    return [f"99{prefix:0>4}{n:06d}" for n in range(count)]


@dataclass
class World:
    """SYNTHETIC rows, reads, matcher answers and schools for one test."""

    stations: list[dict[str, Any]] = field(default_factory=list)
    schools: dict[str, School] = field(default_factory=dict)
    public_year: int = 2023
    rows: list[ListRow] = field(default_factory=list)
    answers: dict[tuple[str, str], Outcome] = field(default_factory=dict)
    extra_reads: list[Read] = field(default_factory=list)
    variants: dict[tuple[str, str], str] = field(default_factory=dict)
    extras: dict[tuple[str, str], list[RowExtra]] = field(default_factory=dict)
    placed: set[tuple[str, str]] = field(default_factory=set)
    """(source, listing name) pairs whose list places the listing by its record."""

    def add_schools(self, *items: School) -> None:
        for item in items:
            self.schools[item.id] = item

    def row(  # noqa: PLR0913 - a row and the matcher's answer for it
        self,
        source: str,
        at: str,
        status: str,
        *,
        name: str = "SYNTHETIC listing",
        direct: Iterable[str] = (),
        district: Iterable[str] = (),
        accepted: bool | None = None,
        reason: str = "accepted",
        variant: str = "syn-list",
        comment: str = "",
        posted: str | None = None,
        section: str | None = None,
        placed: bool = False,
        targets: Iterable[str] | None = None,
    ) -> ListRow:
        """Add a row (and its read) and what the matcher answers for its listing.

        ``comment`` is the row's comment field and ``posted`` its list's posted
        text, as :func:`snowlight.replays.rows.row_extras` reads them. ``reason``
        is the matcher's (``"name"`` for a match by name alone); ``placed`` says
        the row's list places it by its record; ``targets`` are the records a
        rejected answer still names (the place guard keeps them).
        """
        if placed:
            self.placed.add((source, name))
        direct, district = tuple(direct), tuple(district)
        self.variants[(source, at)] = variant
        self.extras.setdefault((source, at), []).append(
            RowExtra(detail=detail_of(name, status, {"comment": comment}), posted=posted)
        )
        row = ListRow(
            source_id=source,
            mode="archive",
            fetched_at=at,
            read_sha256=_sha(source, at),
            variant=variant,
            name=name,
            status=status,
            section=section,
        )
        self.rows.append(row)
        took = accepted if accepted is not None else bool(direct or district)
        self.answers[(source, name)] = Outcome(
            accepted=took,
            reason=reason if took or reason != "accepted" else "no_match",
            level="school" if direct else "district",
            confidence=1.0 if took else 0.0,
            targets=(*direct, *district) if took else tuple(targets or ()),
            direct=direct if took else (),
            via_district=district if took else (),
            best_id=None,
            best_name=None,
            best_score=None,
            detail="SYNTHETIC",
        )
        return row

    def empty_read(self, source: str, at: str, *, rows: int = 0, variant: str = "syn-list") -> None:
        """A read that holds no tied rows (empty, deferred, or untied when ``rows`` > 0)."""
        self.extra_reads.append(
            Read(
                source_id=source,
                mode="archive",
                fetched_at=at,
                retrieved_at="2026-09-01T00:00:00Z",
                sha256="0" * 64,
                variant=variant,
                rows=rows,
            )
        )

    def loaded(self) -> LoadedRows:
        counts: dict[tuple[str, str], int] = {}
        for row in self.rows:
            counts[(row.source_id, row.fetched_at)] = (
                counts.get((row.source_id, row.fetched_at), 0) + 1
            )
        reads = [
            Read(
                source_id=source,
                mode="archive",
                fetched_at=at,
                retrieved_at="2026-09-01T00:00:00Z",
                sha256=_sha(source, at),
                variant=self.variants[(source, at)],
                rows=count,
            )
            for (source, at), count in counts.items()
        ]
        return LoadedRows(rows=tuple(self.rows), reads=(*reads, *self.extra_reads), dropped={})

    def registry(self) -> Registry:
        return registry(*self.stations)

    def book(self) -> MatchBook:
        reg = self.registry()
        outcomes: dict[Query, Outcome] = {}
        placed: set[Query] = set()
        for row in self.rows:
            if row.source_id in reg.stations:
                query = row_query(row, reg)
                outcomes[query] = self.answers[(row.source_id, row.name)]
                if (row.source_id, row.name) in self.placed:
                    placed.add(query)
        return book_from(allowed_rows(self.loaded(), reg), reg, outcomes, frozenset(placed))

    def inputs(self, parse: ParseFn = stub_parse) -> DayInputs:
        return DayInputs(
            loaded=self.loaded(),
            registry=self.registry(),
            book=self.book(),
            directory=Directory(
                schools=dict(self.schools),
                public_year=self.public_year,
                district_sizes=dict(
                    Counter(item.district_id for item in self.schools.values() if item.district_id)
                ),
            ),
            lookup=StubZones(),
            parse=parse,
            extras={key: tuple(items) for key, items in self.extras.items()},
        )


# --- a SYNTHETIC world on disk, for the real matcher and the CLI --------------------------------

QUILL, MARROW, TANSY = "9900001", "9900002", "9900003"
"""SYNTHETIC districts: Quillfeather R-7 and Marrowbrook R-2 (MO), Tansyridge USD 900 (KS)."""


def disk_districts() -> pl.DataFrame:
    """The SYNTHETIC districts."""
    return pl.DataFrame(
        {
            "district_id": [QUILL, MARROW, TANSY],
            "name": ["Quillfeather R-7", "Marrowbrook R-2", "Tansyridge USD 900"],
            "state": ["MO", "MO", "KS"],
            "state_fips": ["29", "29", "20"],
            "county_fips": ["29095", "29095", "20091"],
            "county_name": ["Jackson County", "Jackson County", "Johnson County"],
            "city": ["Quillfeather", "Marrowbrook", "Tansyridge"],
            "lat": [39.00, 39.10, 38.90],
            "lon": [-94.40, -94.50, -94.80],
        }
    )


def disk_schools(per_district: int) -> pl.DataFrame:
    """SYNTHETIC schools: ``per_district`` each in Quillfeather and Tansyridge, and two more."""
    rows: list[dict[str, Any]] = []

    quill = (QUILL, "MO", "29095", "Quillfeather")
    tansy = (TANSY, "KS", "20091", "Tansyridge")
    marrow = (MARROW, "MO", "29095", "Marrowbrook")

    def add(sid: str, name: str, place: tuple[str, str, str, str], status: str = "Open") -> None:
        district, state, fips, city = place
        rows.append(
            {
                "id": sid,
                "kind": "public",
                "name": name,
                "district_id": district,
                "state": state,
                "state_fips": "29" if state == "MO" else "20",
                "county_fips": fips,
                "county_name": "Jackson County" if state == "MO" else "Johnson County",
                "city": city,
                "lat": 39.0 if state == "MO" else 38.9,
                "lon": -94.4 if state == "MO" else -94.8,
                "grade_low": "KG",
                "grade_high": "05",
                "level": "Elementary",
                "status": status,
                "school_year": "2024-2025",
            }
        )

    for n in range(per_district):
        add(f"9900001{n:05d}", f"Quillfeather Learning Center {n}", quill)
        add(f"9900003{n:05d}", f"Tansyridge Learning Center {n}", tansy)
    add("990000200001", "Marrowbrook Elementary", marrow)
    add("990000200002", "Marrowbrook Middle", marrow, status="New")
    frame = pl.DataFrame(rows)
    return frame.with_columns(pl.int_range(pl.len(), dtype=pl.UInt32).alias("index"))


def disk_counties() -> CountyList:
    """Two SYNTHETIC square counties around the synthetic schools."""
    return CountyList(
        counties={
            "29095": County(
                "29095", "MO", "Jackson", (CHICAGO,), shapely.box(-94.7, 38.8, -94.2, 39.3)
            ),
            "20091": County(
                "20091", "KS", "Johnson", (CHICAGO,), shapely.box(-95.1, 38.6, -94.7, 39.1)
            ),
        },
        state_fips={"MO": "29", "KS": "20"},
        records=2,
    )


def write_disk_world(root: Path, *, per_district: int, rows: Sequence[dict[str, Any]]) -> None:
    """Write a SYNTHETIC directory, registry, archive, aliases and meta.json under ``root``.

    ``rows`` are raw archive rows (``source_id``, ``fetched_at``, ``raw_name``,
    ``raw_status``, ``raw_extra``); each read is made from them.
    """
    directory = root / "directory"
    directory.mkdir(parents=True)
    disk_districts().write_parquet(directory / "districts.parquet")
    disk_schools(per_district).write_parquet(directory / "schools.parquet")
    sources = root / "sources"
    sources.mkdir()
    stations = [
        station("hearst-a", states=("MO",), fips=("29095",)),
        station("hearst-b", states=("KS",), market="SYNTHETIC market two", fips=("20091",)),
    ]
    file = platform_file("hearst", stations)
    (sources / "hearst.yaml").write_text(file.model_dump_json(), encoding="utf-8")
    archive = root / "archive"
    archive.mkdir()
    counts = Counter((str(r["source_id"]), str(r["fetched_at"])) for r in rows)
    reads = [
        {
            "source_id": source,
            "mode": "archive",
            "url": "https://example.invalid/closings",
            "fetched_at": at,
            "retrieved_at": "2026-09-01T00:00:00Z",
            "sha256": _sha(source, at),
            "bytes": 1,
            "variant": "hearst-rows",
            "state": "populated",
            "rows": count,
        }
        for (source, at), count in sorted(counts.items())
    ]
    for name, items in (("reads.jsonl", reads), ("rows.jsonl", rows)):
        text = "".join(json.dumps(item) + "\n" for item in items)
        (archive / name).write_text(text, encoding="utf-8")
    (root / "aliases.yaml").write_text("schema_version: 1\nmarkets: {}\n", encoding="utf-8")
    schools = disk_schools(per_district).sort("index")
    meta = {"generated_on": "2026-09-24", "count": schools.height, "ids": schools["id"].to_list()}
    (root / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def raw_row(  # noqa: PLR0913 - the fields of a raw row
    source: str,
    at: str,
    name: str,
    status: str,
    location: str = "",
    *,
    comment: str | None = None,
    updated: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """A SYNTHETIC raw archive row of the ``hearst-rows`` variant."""
    extra: dict[str, Any] = {"location": location}
    if comment is not None:
        extra["comments_line1"] = comment
    if scope is not None:
        extra["updated_scope"] = scope
    return {
        "source_id": source,
        "fetched_at": at,
        "raw_name": name,
        "raw_status": status,
        "raw_updated_text": updated,
        "raw_extra": extra,
    }

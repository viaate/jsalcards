"""The training run's inputs from disk: the directory, the weather history and the archive.

Everything here reads files the other builds made (the directory, the IEM season
files and zone polygons the weights build cached, the station archive) and writes
only under ``out/internal/predict`` (gitignored): the per-day weather classes
(``weather.parquet``) and the labels (``labels.parquet``), with their report and the
audit sample. The model itself is fit from those by :mod:`snowlight.predict.pool`.
"""

import bisect
import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from snowlight.predict import pool
from snowlight.predict.alerts_history import (
    Reach,
    district_day_classes,
    read_season,
    school_day_classes,
)
from snowlight.predict.artifact import (
    SITUATION_KEYS,
    DistrictModel,
    ModelArtifact,
    RecordDay,
    Settings,
    Training,
)
from snowlight.predict.calendar import school_days, season_label
from snowlight.predict.config import PIPELINE_ROOT, LabelSettings, PredictConfig
from snowlight.predict.geography import REGION_OF, majority, neighbors
from snowlight.predict.labels import (
    DayLit,
    LabelInputs,
    LitStatus,
    Outcome,
    ReadRecord,
    audiences,
    carries,
    district_markets,
    label_days,
    parse_reads,
    station_stats,
    storm_absences,
)
from snowlight.predict.situations import WeatherClass, Window

INTERNAL: Final = PIPELINE_ROOT / "out" / "internal"
DEFAULT_OUT: Final = INTERNAL / "predict"
PRIVATE_FLAG: Final = 0x01
CHARTER_FLAG: Final = 0x02
VIRTUAL_FLAG: Final = 0x04
STAMP: Final = "%Y-%m-%dT%H:%M:%SZ"
QUIET_DROPS: Final = frozenset(
    {
        "not_for_day",
        "date_out_of_range",
        "outside_window",
        "weekend",
        "says_open",
        "unknown_source",
        "platform",
        "district_source",
    }
)
"""Row drops that leave a district absent from the day's list in effect: the row is about
another day, says school is open, or comes from a source replays never read. (A row the step
read as naming one school is not here: the audit found whole-district rows read that way.)"""


@dataclass(frozen=True, slots=True)
class TrainPaths:
    """Where the training run reads and writes."""

    archive: Path = INTERNAL / "stations" / "archive"
    registry: Path = PIPELINE_ROOT / "config" / "sources"
    directory: Path = INTERNAL / "directory"
    meta: Path = PIPELINE_ROOT / "out" / "site-data" / "schools" / "meta.json"
    aliases: Path = PIPELINE_ROOT / "config" / "aliases.yaml"
    weather_cache: Path = PIPELINE_ROOT / ".cache" / "weather"
    weights_cache: Path = PIPELINE_ROOT / ".cache" / "weights"
    out: Path = DEFAULT_OUT


def eligible_schools(schools: pl.DataFrame) -> pl.DataFrame:
    """The schools whose status labels a district: public, with a district, not a charter
    and not fully virtual (``kind_flags`` as ``points.bin`` gives them)."""
    flags = pl.col("kind_flags").cast(pl.Int32)
    return schools.filter(
        (pl.col("kind") == "public")
        & pl.col("district_id").is_not_null()
        & ((flags & (PRIVATE_FLAG | CHARTER_FLAG | VIRTUAL_FLAG)) == 0)
    )


def district_table(schools: pl.DataFrame, zone_of_school: Mapping[int, str]) -> pl.DataFrame:
    """Per district (LEAID) with a school in the directory: its state, its schools' most
    common county and zone, and its eligible school count. ``zone_of_school`` maps a
    directory index to its IANA zone."""
    eligible = eligible_schools(schools).group_by("district_id").agg(pl.len().alias("eligible"))
    grouped = (
        schools.filter(pl.col("district_id").is_not_null())
        .group_by("district_id")
        .agg(pl.col("state").first(), pl.col("county_fips"), pl.col("index"))
        .join(eligible, on="district_id", how="left")
    )
    rows: list[dict[str, object]] = []
    for record in grouped.sort("district_id").iter_rows(named=True):
        zones = [zone_of_school.get(int(str(index))) for index in record["index"]]
        rows.append(
            {
                "district": record["district_id"],
                "state": record["state"],
                "county": majority(list(record["county_fips"])),
                "time_zone": majority(zones),
                "eligible": record["eligible"] or 0,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "district": pl.String,
            "state": pl.String,
            "county": pl.String,
            "time_zone": pl.String,
            "eligible": pl.Int64,
        },
    )


# --- the weather history ----------------------------------------------------------------------


@dataclass(slots=True)
class HistoryPlaces:
    """Which schools each zone version reaches, and each school's time zone."""

    reach: Reach
    zone_of_school: dict[int, str] = field(default_factory=dict)
    files: dict[int, Path] = field(default_factory=dict)
    """Season to its cached IEM file."""


def history_places(
    paths: TrainPaths, schools: pl.DataFrame, seasons: Sequence[int]
) -> HistoryPlaces:  # pragma: no cover - reads the cached NWS and IEM files
    """Place every school in its zone versions, season by season, as the weights build does."""
    from snowlight.sources.nws.http import HttpCache, make_client  # noqa: PLC0415
    from snowlight.weights import archive, schoolzones, zonepolys, zones  # noqa: PLC0415
    from snowlight.weights import schools as weight_schools  # noqa: PLC0415
    from snowlight.weights.cache import WeightsCache  # noqa: PLC0415

    with HttpCache(make_client()) as http:
        cache = WeightsCache(http, root=paths.weights_cache, siblings=())
        counties = zones.load_counties(cache)
        files = [archive.load_year(cache, season) for season in seasons]
        frame = schools.select(weight_schools.SCHOOL_COLUMNS)
        placement = weight_schools.place_schools(frame, counties)
        sets = zonepolys.load_zone_sets(cache)
        book = zonepolys.build_book(cache, [row for file in files for row in file.rows], sets)
        zoned = schoolzones.place_in_zones(frame, placement, book.reference, counties)
        members = schoolzones.memberships(book.polygons, frame, placement, zoned)
        versions = schoolzones.year_versions(files, book)
        by_year = schoolzones.place_by_year(
            book.polygons,
            versions,
            zoned,
            members,
            coordinates=schoolzones.school_coordinates(frame, placement),
        )
    index_of = np.array([school.index for school in placement.schools], dtype=np.int64)
    reach = Reach(
        members={key: index_of[positions] for key, positions in members.items()},
        extra={
            pair: index_of[np.asarray(positions, dtype=np.int64)]
            for pair, positions in by_year.extra.items()
        },
        key_of={
            (version.ugc, version.area_km2): resolved.key
            for version, resolved in book.resolved.items()
        },
    )
    zone_of_school = {
        int(index_of[position]): school.time_zones[0]
        for position, school in enumerate(zoned.schools)
        if school.time_zones
    }
    return HistoryPlaces(reach, zone_of_school, {file.year: file.file.path for file in files})


def weather_history(
    places: HistoryPlaces, schools: pl.DataFrame, config: PredictConfig
) -> tuple[pl.DataFrame, dict[str, object]]:
    """Each (district, day) whose class is above ``none``, and the counts behind it."""
    weather = config.weather
    window = Window(weather.window_from, weather.window_until, weather.snapshot_hour)
    table = district_table(schools, places.zone_of_school)
    zone_of_district = dict(zip(table["district"], table["time_zone"], strict=True))
    eligible = eligible_schools(schools)
    district_of_school = eligible.select(
        pl.col("index").cast(pl.Int64).alias("school"), pl.col("district_id").alias("district")
    )
    zone_by_index: list[str | None] = [None] * (
        schools.height and int(schools["index"].to_numpy().max()) + 1
    )
    for index, district in zip(
        district_of_school["school"].to_list(),
        district_of_school["district"].to_list(),
        strict=True,
    ):
        zone_by_index[index] = zone_of_district.get(district)
    rows = [
        row
        for season, path in sorted(places.files.items())
        for row in read_season(path.read_text(encoding="utf-8"), season)
    ]
    classes = school_day_classes(rows, places.reach, zone_by_index, window)
    found = district_day_classes(classes.frame, district_of_school, weather.covered_share)
    stats: dict[str, object] = {
        "rows": classes.rows,
        "rows_unresolved": classes.rows_unresolved,
        "rows_by_code": classes.by_code,
        "school_days_above_none": classes.frame.height,
        "district_days_by_class": {
            WeatherClass(int(value)).label: int(count)
            for value, count in found.group_by("weather").len().sort("weather").iter_rows()
        },
    }
    return found, stats


# --- the archive --------------------------------------------------------------------------------


@dataclass(slots=True)
class DayIndex:
    """The archive's rows and reads in time order, to hand each day only its own."""

    loaded: object
    """The :class:`~snowlight.listed.evidence.LoadedRows` of the whole archive."""
    row_times: list[str]
    read_times: list[str]

    def near(self, day: date) -> tuple[slice, slice]:
        """The rows and reads fetched from three days before ``day`` to noon the day after
        (UTC): a superset of every window that can light ``day``."""
        start = (datetime.combine(day - timedelta(days=3), time(0), tzinfo=UTC)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        end = (datetime.combine(day + timedelta(days=1), time(12), tzinfo=UTC)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        rows = slice(
            bisect.bisect_left(self.row_times, start), bisect.bisect_left(self.row_times, end)
        )
        reads = slice(
            bisect.bisect_left(self.read_times, start), bisect.bisect_left(self.read_times, end)
        )
        return rows, reads


@dataclass(slots=True)
class ArchiveRun:  # pragma: no cover - the real archive
    """The archive matched once, ready to settle any day."""

    inputs: object
    """The replay builder's :class:`~snowlight.replays.build.DayInputs` for the whole archive."""
    index: DayIndex
    listings: list[tuple[str, str, date]]
    market_of: dict[str, str]
    reads: list[ReadRecord]
    markets: dict[str, str] = field(default_factory=dict)
    """District to its market (:func:`district_markets`), once labeled."""
    eligible: frozenset[str] = frozenset()
    """The eligible schools' NCES ids (set before labeling): only their rows hold a label."""

    def settle(self, day: date) -> object:
        """The replay step's :class:`~snowlight.replays.build.Settled` for ``day``."""
        from dataclasses import replace  # noqa: PLC0415

        from snowlight.listed.evidence import LoadedRows  # noqa: PLC0415
        from snowlight.replays.build import DayInputs, settle_day  # noqa: PLC0415

        inputs = self.inputs
        assert isinstance(inputs, DayInputs)  # noqa: S101
        loaded = inputs.loaded
        rows, reads = self.index.near(day)
        subset = LoadedRows(rows=loaded.rows[rows], reads=loaded.reads[reads], dropped={})
        return settle_day(replace(inputs, loaded=subset), day)

    def lit_for(self, day: date) -> DayLit:
        """The settled statuses of ``day``, and the populated reads the replay step kept (a
        read it dropped, unreadable or matched too little, never shows a district open)."""
        from snowlight.replays.build import Settled  # noqa: PLC0415

        settled = self.settle(day)
        assert isinstance(settled, Settled)  # noqa: S101
        kept = frozenset(
            (check.source_id, datetime.strptime(check.fetched_at, STAMP).replace(tzinfo=UTC))
            for check in settled.reads
            if check.drop is None
        )
        return DayLit(
            {sid: LitStatus(item.status, item.reason) for sid, item in settled.lit.items()},
            kept,
            self.listed_unlit(day, settled),
        )

    def listed_unlit(self, day: date, settled: object) -> frozenset[str]:
        """The districts a row of ``day``'s window names (through an eligible school or the
        district row) that the replay step did not light any eligible school of, unless it
        dropped the row as being about another day or saying school is open
        (:data:`QUIET_DROPS`)."""
        from snowlight.listed.build import row_query  # noqa: PLC0415
        from snowlight.replays.build import DayInputs, Settled  # noqa: PLC0415

        inputs = self.inputs
        assert isinstance(inputs, DayInputs)  # noqa: S101
        assert isinstance(settled, Settled)  # noqa: S101
        quiet = {
            (row.source_id, row.fetched_at, row.name, row.status)
            for row, drop in settled.dropped
            if drop.value in QUIET_DROPS
        }
        lit_districts: set[str] = set()
        named: set[str] = set()
        directory = inputs.directory
        for school in settled.lit:
            found = directory.schools.get(school)
            if found is not None and found.district_id and school in self.eligible:
                lit_districts.add(found.district_id)
        rows, _reads = self.index.near(day)
        start, end = widest(day)
        for row in inputs.loaded.rows[rows]:
            if not start <= row.fetched_at < end:
                continue
            if (row.source_id, row.fetched_at, row.name, row.status) in quiet:
                continue
            outcome = inputs.book.outcomes.get(row_query(row, inputs.registry))
            if outcome is None or not outcome.accepted:
                continue
            for school in (*outcome.direct, *outcome.via_district):
                found = directory.schools.get(school)
                if found is not None and found.district_id and school in self.eligible:
                    named.add(found.district_id)
        return frozenset(named - lit_districts)

    def audit(  # noqa: PLR0913, PLR0917 - one label and what it was read from
        self,
        district: str,
        day: date,
        zone: str,
        eligible: Sequence[str],
        audience: Mapping[str, Mapping[str, date]],
        settings: LabelSettings,
    ) -> dict[str, object]:
        """The evidence of one label, for the audit by eye (internal: it holds list rows):
        the morning reads of the district's audience stations (time, rows, kept or the
        replay step's drop), every row in the day's window matched to the district, and the
        settled statuses of its eligible schools."""
        from collections import Counter  # noqa: PLC0415

        from snowlight.listed.build import row_query  # noqa: PLC0415
        from snowlight.replays.build import DayInputs, Settled  # noqa: PLC0415

        inputs = self.inputs
        assert isinstance(inputs, DayInputs)  # noqa: S101
        settled = self.settle(day)
        assert isinstance(settled, Settled)  # noqa: S101
        tz = ZoneInfo(zone)
        checks = {(c.source_id, c.fetched_at): c for c in settled.reads}
        stations = sorted(s for s in audience if district in carries(audience, s, day))
        morning: list[str] = []
        for read in self.reads:
            if read.source_id not in stations or read.state not in {"populated", "empty"}:
                continue
            local = read.fetched_at.astimezone(tz)
            if local.date() != day or not settings.read_from <= local.time() < settings.read_until:
                continue
            check = checks.get((read.source_id, read.fetched_at.strftime(STAMP)))
            gate = (
                "-"
                if read.state == "empty"
                else (
                    "not checked"
                    if check is None
                    else ("kept" if check.drop is None else check.drop.value)
                )
            )
            morning.append(
                f"{read.source_id} {local:%H:%M} {read.state} {read.rows} rows ({gate}); "
                f"market {self.market_of.get(read.source_id, '?')}"
            )
        rows, _reads = self.index.near(day)
        start, end = widest(day)
        matched: list[str] = []
        directory = inputs.directory
        for row in inputs.loaded.rows[rows]:
            if not start <= row.fetched_at < end:
                continue
            outcome = inputs.book.outcomes.get(row_query(row, inputs.registry))
            if outcome is None or not outcome.accepted:
                continue
            schools = (*outcome.direct, *outcome.via_district)
            districts = {
                found.district_id
                for school in schools
                if (found := directory.schools.get(school)) is not None
            }
            if district in districts:
                at = datetime.strptime(row.fetched_at, STAMP).replace(tzinfo=UTC).astimezone(tz)
                matched.append(f"{row.source_id} {at:%m-%d %H:%M}: {row.name} | {row.status}")
        lit = Counter(
            f"{shown.status.value}/{shown.reason.value if shown.reason else '-'}"
            for school in eligible
            if (shown := settled.lit.get(school)) is not None
        )
        return {
            "district": district,
            "day": day.isoformat(),
            "stations": stations,
            "morning_reads": morning,
            "matched_rows": sorted(set(matched)),
            "lit": dict(sorted(lit.items())),
            "eligible": len(eligible),
        }


def widest(day: date) -> tuple[str, str]:
    """The replay step's widest window for ``day``, as capture stamps."""
    from snowlight.replays.rows import widest_window  # noqa: PLC0415

    low, high = widest_window(day)
    return low.strftime(STAMP), high.strftime(STAMP)


def prepare_archive(
    paths: TrainPaths, zone_of_district: Mapping[str, str], workers: int
) -> ArchiveRun:  # pragma: no cover - the real archive, the reader and the matcher
    """Match the whole archive once with the landed matcher and status reader."""
    from snowlight.listed.build import row_query  # noqa: PLC0415
    from snowlight.listed.cli import nws_counties  # noqa: PLC0415
    from snowlight.listed.evidence import LoadedRows, load_rows  # noqa: PLC0415
    from snowlight.listed.located import Gazetteer  # noqa: PLC0415
    from snowlight.listed.matching import MatcherSpec  # noqa: PLC0415
    from snowlight.replays.build import (  # noqa: PLC0415
        DayInputs,
        Directory,
        allowed_rows,
        market_of,
        match_archive,
    )
    from snowlight.replays.cli import load_reader, nws_lookup  # noqa: PLC0415
    from snowlight.replays.rows import row_extras  # noqa: PLC0415
    from snowlight.sources.stations.registry import load_registry  # noqa: PLC0415

    parse, _root = load_reader()
    loaded = load_rows(paths.archive / "reads.jsonl", paths.archive / "rows.jsonl")
    extras = row_extras(paths.archive / "rows.jsonl")
    registry = load_registry(paths.registry)
    spec = MatcherSpec(paths.directory, paths.aliases)
    matcher = spec.build()
    schools = pl.read_parquet(paths.directory / "schools.parquet")
    districts = pl.read_parquet(paths.directory / "districts.parquet")
    gazetteer = Gazetteer.build(schools, districts, nws_counties())
    book = match_archive(loaded, registry, matcher, gazetteer=gazetteer, spec=spec, workers=workers)
    directory = Directory.from_frame(schools)
    rows = sorted(loaded.rows, key=lambda row: row.fetched_at)
    reads = sorted(loaded.reads, key=lambda read: read.fetched_at)
    ordered = LoadedRows(rows=tuple(rows), reads=tuple(reads), dropped=loaded.dropped)
    lookup = nws_lookup(paths.weather_cache, date.today()).lookup
    inputs = DayInputs(
        loaded=ordered,
        registry=registry,
        book=book,
        directory=directory,
        lookup=lookup,
        parse=parse,
        extras=extras,
    )
    listings: list[tuple[str, str, date]] = []
    for row in allowed_rows(ordered, registry):
        outcome = book.outcomes.get(row_query(row, registry))
        if outcome is None or not outcome.accepted:
            continue
        moment = datetime.strptime(row.fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        for district in sorted(
            {
                found.district_id
                for school in (*outcome.direct, *outcome.via_district)
                if (found := directory.schools.get(school)) is not None and found.district_id
            }
        ):
            zone = zone_of_district.get(district)
            if zone is not None:
                listings.append((row.source_id, district, _local_day(moment, zone)))
    markets = {sid: market_of(station) for sid, station in registry.stations.items()}
    with (paths.archive / "reads.jsonl").open(encoding="utf-8") as handle:
        records = sorted(parse_reads(handle), key=lambda read: read.fetched_at)
    index = DayIndex(ordered, [row.fetched_at for row in rows], [read.fetched_at for read in reads])
    return ArchiveRun(inputs, index, listings, markets, records)


def _local_day(moment: datetime, zone: str) -> date:
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    return moment.astimezone(ZoneInfo(zone)).date()


def run_labels(  # noqa: PLR0913, PLR0917 - the archive, the directory and the settings
    run: ArchiveRun,
    schools: pl.DataFrame,
    table: pl.DataFrame,
    weather: pl.DataFrame,
    config: PredictConfig,
    days: Sequence[date] | None = None,
) -> pl.DataFrame:  # pragma: no cover - the real archive
    """Label every school day of the archive's span (or ``days``)."""
    eligible = eligible_schools(schools)
    by_district: dict[str, list[str]] = {}
    for district, school in zip(
        eligible["district_id"].to_list(), eligible["id"].to_list(), strict=True
    ):
        by_district.setdefault(district, []).append(school)
    zone_of = {
        district: zone
        for district, zone in zip(table["district"], table["time_zone"], strict=True)
        if zone is not None
    }
    run.eligible = frozenset(eligible["id"].to_list())
    captures, median_rows = station_stats(run.reads)
    inputs = LabelInputs(
        eligible={district: tuple(ids) for district, ids in by_district.items()},
        zone_of=zone_of,
        audience=audiences(run.listings, config.labels.audience_days),
        reads=run.reads,
        market_of=run.market_of,
        weather={
            (district, day): WeatherClass(int(value))
            for district, day, value in weather.iter_rows()
        },
        district_of={school: district for district, ids in by_district.items() for school in ids},
        captures=captures,
        median_rows=median_rows,
    )
    if days is None:
        first = run.reads[0].fetched_at.date()
        last = run.reads[-1].fetched_at.date()
        days = list(school_days(max(first, date(config.labels.first_season, 8, 15)), last))
    labels = label_days(days, inputs, run.lit_for, config.labels)
    markets = district_markets(run.listings, run.market_of)
    run.markets = markets
    states = dict(zip(table["district"], table["state"], strict=True))
    clustered = labels.with_columns(
        pl.col("district")
        .map_elements(
            lambda d: markets.get(d) or f"state {states.get(d, '?')}", return_dtype=pl.String
        )
        .alias("cluster")
    )
    return storm_absences(clustered, config.labels.storm_absence_share)


def labels_report(labels: pl.DataFrame, states: Mapping[str, str]) -> str:
    """The internal labels report: counts by season, state and outcome."""
    lines = ["# Labels (internal)", ""]
    lines.append(f"Labeled district-days: {labels.height:,}")
    counts = Counter(labels["outcome"].to_list())
    lines.append(
        "By outcome: "
        + ", ".join(f"{outcome.value} {counts.get(outcome.value, 0):,}" for outcome in Outcome)
    )
    if "unknown_why" in labels.columns:
        why = Counter(labels["unknown_why"].drop_nulls().to_list())
        lines.append(
            "Unknown, by why: "
            + ", ".join(f"{key} {value:,}" for key, value in sorted(why.items()))
        )
    lines.extend(
        [
            "",
            "Why a row is unknown (each district an audience station read that day gets a row):",
            "- partly_lit: read, more than the open share lit, under the closing and delay shares",
            "- dropped_read: its stations' only morning reads were dropped by the replay step",
            "- thin_station: its stations have too few populated captures in the archive",
            "- small_capture: storm day, its stations' morning lists were far below their median",
            "- voided_empty: an empty list while a market peer held many rows",
            "- empty_uncorroborated: storm day, only an empty list and no market peer read",
            "- listed_unread: a list named it that day in a row the replay step did not light",
            "- absent_in_storm: storm day, absent from the lists while most of its market closed",
            "- break: a likely break day (Thanksgiving week, Dec 18 to Jan 3, MLK, Presidents')",
        ]
    )
    lines.extend(["", "| season | no_school | delayed | open | unknown |", "|---|---|---|---|---|"])
    for season in sorted(set(labels["season"].to_list())):
        part = Counter(labels.filter(pl.col("season") == season)["outcome"].to_list())
        lines.append(
            f"| {season_label(season)} | "
            + " | ".join(f"{part.get(outcome.value, 0):,}" for outcome in Outcome)
            + " |"
        )
    lines.extend(["", "| state | no_school | delayed | open | unknown |", "|---|---|---|---|---|"])
    by_state: dict[str, Counter[str]] = {}
    for district, outcome in zip(labels["district"], labels["outcome"], strict=True):
        by_state.setdefault(states.get(district, "?"), Counter())[outcome] += 1
    for state in sorted(by_state):
        part = by_state[state]
        lines.append(
            f"| {state} | " + " | ".join(f"{part.get(o.value, 0):,}" for o in Outcome) + " |"
        )
    return "\n".join(lines) + "\n"


def audit_markdown(items: Sequence[Mapping[str, object]]) -> str:
    """The audit sample for reading by eye: each label, its reads and its matched rows."""
    lines = ["# Labels audit (internal: holds list rows)", ""]
    for number, item in enumerate(items, 1):
        lines.append(
            f"## {number}. {item['district']} {item['day']}: {item['outcome']} "
            f"(weather {item['weather']}, lit {item['lit_share']}, of {item['eligible']} schools)"
        )
        lines.append(f"- audience stations: {', '.join(map(str, item['stations'])) or 'none'}")  # type: ignore[call-overload]
        for read in item["morning_reads"]:  # type: ignore[attr-defined]
            lines.append(f"- read {read}")
        lines.append(f"- lit: {item['lit']}")
        for row in item["matched_rows"]:  # type: ignore[attr-defined]
            lines.append(f"  - row {row}")
        lines.append("")
    return "\n".join(lines) + "\n"


def sample_rows(labels: pl.DataFrame, outcome: Outcome, count: int, seed: int = 7) -> pl.DataFrame:
    """A fixed random sample of ``count`` labels with ``outcome``, for the audit by eye."""
    part = labels.filter(pl.col("outcome") == outcome.value)
    if part.height <= count:
        return part
    return part.sample(n=count, seed=seed, shuffle=True).sort("district", "day")


def write_json_lines(path: Path, items: Iterator[dict[str, object]]) -> None:
    """Write one JSON object a line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, sort_keys=True, default=str) + "\n")


# --- the model ------------------------------------------------------------------------------


def training_places(table: pl.DataFrame, schools: pl.DataFrame, miles: float) -> pool.Places:
    """The chain's places of the training directory's districts (``table`` from
    :func:`district_table`), with neighbors from its schools' points."""
    districts = table["district"].to_list()
    position = {district: i for i, district in enumerate(districts)}
    located = schools.filter(pl.col("district_id").is_not_null())
    owner = np.array([position.get(d, -1) for d in located["district_id"].to_list()], np.int64)
    near = neighbors(
        located["lon"].to_numpy().astype(np.float64),
        located["lat"].to_numpy().astype(np.float64),
        owner,
        miles,
    )
    states = table["state"].to_list()
    return pool.make_places(
        districts,
        region=[REGION_OF.get(state) if state else None for state in states],
        state=states,
        county=table["county"].to_list(),
        neighbors={districts[d]: [districts[e] for e in es] for d, es in near.items()},
    )


def _record(labels: pl.DataFrame, keep: int) -> dict[str, dict[str, tuple[RecordDay, ...]]]:
    found: dict[str, dict[str, tuple[RecordDay, ...]]] = {}
    usable = labels.filter(pl.col("did").is_not_null()).sort("district", "day")
    keys = [
        pool.situation_of(int(w), bool(a)).key
        for w, a in zip(usable["weather"].to_list(), usable["after"].to_list(), strict=True)
    ]
    grouped: dict[tuple[str, str], list[RecordDay]] = {}
    for district, day, did, key in zip(
        usable["district"].to_list(),
        usable["day"].to_list(),
        usable["did"].to_list(),
        keys,
        strict=True,
    ):
        grouped.setdefault((district, key), []).append(RecordDay(day=day, did=did))
    for (district, key), days in grouped.items():
        found.setdefault(district, {})[key] = tuple(days[-keep:])
    return found


def fit_artifact(
    labels: pl.DataFrame,
    table: pl.DataFrame,
    places: pool.Places,
    config: PredictConfig,
    directory_generated_on: date,
) -> tuple[ModelArtifact, pool.Tuned, pool.Tuned]:
    """Fit the strengths on every labeled season and keep every district's counts."""
    settings = config.model
    usable = pool.usable_labels(labels, places)
    rows = pool.rows_from_labels(usable, places, "no_school")
    delay_rows = pool.rows_from_labels(usable, places, "delay")
    seasons = sorted(set(rows.season.tolist()))
    tables = pool.tables_from_rows(rows, places, seasons)
    tables_delay = pool.tables_from_rows(delay_rows, places, seasons)
    rules = pool.rules_of(settings)
    tuned = pool.tune(rows, places, tables, seasons, settings.m_grid, rules=rules)
    tuned_delay = pool.tune(
        delay_rows, places, tables_delay, seasons, settings.m_grid, rules=pool.delay_rules(rules)
    )
    y, n = tables.total()
    yd, nd = tables_delay.total()
    records = _record(usable, settings.record_days)
    districts: dict[str, DistrictModel] = {}
    for i, record in enumerate(table.iter_rows(named=True)):
        leaid = record["district"]
        assert places.districts[i] == leaid  # noqa: S101 - same order by construction
        labeled = n[i].sum() > 0
        districts[leaid] = DistrictModel(
            state=record["state"],
            county=record["county"],
            time_zone=record["time_zone"],
            y=tuple(int(v) for v in y[i]) if labeled else None,
            n=tuple(int(v) for v in n[i]) if labeled else None,
            yd=tuple(int(v) for v in yd[i]) if labeled else None,
            nd=tuple(int(v) for v in nd[i]) if labeled else None,
            record=records.get(leaid, {}),
        )
    artifact = ModelArtifact(
        schema_version=2,
        situations=SITUATION_KEYS,
        training=Training(
            seasons=tuple(seasons),
            labeled_days=len(rows),
            directory_generated_on=directory_generated_on,
        ),
        settings=Settings(
            own_min_days=settings.own_min_days,
            level_min_days=settings.level_min_days,
            nation_min_days=settings.nation_min_days,
            almost_share=settings.almost_share,
            fallback=dict(sorted(settings.fallback.items())),
            floor=settings.floor,
            ceiling=settings.ceiling,
        ),
        strengths={
            "no_school": tuned.strengths.as_json(),
            "delay": tuned_delay.strengths.as_json(),
        },
        districts=districts,
    )
    return artifact, tuned, tuned_delay

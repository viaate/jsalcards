"""The live job (D10): one pass reads the newest inputs and writes ``flights/live/<stamp>.json``
and ``flights/latest.json`` (:mod:`snowlight.schemas.flights`).

A pass reads the two newest 00Z forecast bulletins it can, the FAA status, the NWS alerts and
the weather reports, each on its own: one that fails is published as not read (its time
``None``), never as "nothing in effect" (D7). A block whose end has passed, or that no run
covers, has no value.

Only rows of the kind the held-out test scored are ever used: 00Z runs, blocks the run covers
whole, of lead class 1 to 3 (:func:`snowlight.flights.features.block_features`, the same rule as
the history). For each airport day the chances come from the newest such run (its ``runs``
entry names it); a newer run that covers a block only in part, or was issued on the block's own
day, never replaces it. Where an airport's chance did not pass the held-out test
(:mod:`snowlight.flights.model`), the value is its usual rate with its ``usual`` bit set.

The model knows only the weather: during a known non-weather event (an airline's computer
outage, flight cuts the FAA orders) its chances say what the weather alone would do; the FAA
programs at each airport are the only live sign of such an event (docs/flights.md).
"""

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
from pydantic import ValidationError

from snowlight.flights import inputs
from snowlight.flights import model as fm
from snowlight.flights.airports import Airport
from snowlight.flights.artifact import Artifact
from snowlight.flights.blocks import BLOCKS, STARTS, Block
from snowlight.flights.features import block_features, with_hubs
from snowlight.flights.nbs import StationRun
from snowlight.flights.obs import OBSERVED_COLUMNS, with_observed
from snowlight.flights.train import day_features, observed_stations, zones
from snowlight.schemas.base import screen_text
from snowlight.schemas.flights import (
    FlightsAirportLive,
    FlightsAlert,
    FlightsArchive,
    FlightsArchiveForecast,
    FlightsArchiveProgram,
    FlightsArchiveReport,
    FlightsBlockRow,
    FlightsDayRows,
    FlightsLatest,
    FlightsLive,
    FlightsProgramNow,
    FlightsUsualTomorrow,
    FlightsWeatherNow,
    FlightsWhy,
)

DAYS: Final = 3
BLOCK_TARGETS: Final = fm.BLOCK_TARGETS
_HOURS: Final = {
    Block.EARLY: 4,
    Block.MORNING: 3,
    Block.AFTERNOON: 5,
    Block.EVENING: 4,
    Block.NIGHT: 8,
}


def stamp_of(moment: datetime) -> str:
    """A live file's stamp: its UTC minute."""
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%MZ")


def slot_of(moment: datetime) -> str:
    """The live file a pass at ``moment`` writes: the 20-minute passes take three slots in turn."""
    return f"slot-{int(moment.timestamp()) // 1200 % 3}"


def next_slot(latest_bytes: bytes | None, now: datetime) -> str:
    """The slot after the one the host's ``latest.json`` names, so two passes in a row never
    share a slot (a reader holding the older copy would see the stamps disagree); by the clock
    (:func:`slot_of`) when there is no readable ``latest.json``."""
    if latest_bytes is not None:
        try:
            named = FlightsLatest.from_json_bytes(latest_bytes).slot
        except ValueError:
            return slot_of(now)
        return f"slot-{(int(named.removeprefix('slot-')) + 1) % 3}"
    return slot_of(now)


def rows_of(runs: Sequence[StationRun]) -> pl.DataFrame:
    """NBS rows (as the history keeps them) of parsed station runs."""
    from snowlight.flights.nbs import ELEMENTS  # noqa: PLC0415

    records = [
        {
            "station": run.station,
            "run": run.run,
            "valid": valid,
            **{name: run.get(name)[index] for name in ELEMENTS},
        }
        for run in runs
        for index, valid in enumerate(run.valid)
    ]
    schema: dict[str, pl.DataType] = {
        "station": pl.String(),
        "run": pl.Datetime("us", "UTC"),
        "valid": pl.Datetime("us", "UTC"),
    }
    schema.update({name: pl.Int16() for name in ELEMENTS})
    return pl.DataFrame(records, schema=schema)


@dataclass(slots=True)
class Inputs:
    """What a pass read; ``None`` where a source could not be read."""

    runs: list[StationRun] = field(default_factory=list)
    faa: tuple[datetime, list[inputs.Program]] | None = None
    alerts: tuple[datetime, dict[str, list[FlightsAlert]]] | None = None
    weather: dict[str, inputs.Report] | None = None
    weather_at: datetime | None = None
    observed: pl.DataFrame | None = None
    """The hourly report flags of the hours before the runs read (the observed-before inputs,
    :func:`snowlight.flights.obs.before_runs`); ``None`` when not read, and then every chance
    is the usual rate, marked so: a chance never misses a storm that already came."""


def _block_span(day: date, block: Block, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, STARTS[block], tzinfo=zone).astimezone(UTC)
    return start, start + timedelta(hours=_HOURS[block])


def _why_rules() -> tuple[tuple[FlightsWhy, Callable[[Mapping[str, float]], bool]], ...]:
    return (
        (FlightsWhy.ICE, lambda r: r["ice"] >= 0.01 or r["p_zr"] >= 0.2),  # noqa: PLR2004
        (FlightsWhy.SNOW, lambda r: r["snow"] >= 0.5 or r["p_snow"] >= 0.5),  # noqa: PLR2004
        (FlightsWhy.THUNDER, lambda r: r["thunder"] >= 0.3),  # noqa: PLR2004
        (FlightsWhy.WIND, lambda r: r["gust"] >= 35),  # noqa: PLR2004
        (FlightsWhy.FOG, lambda r: r["vis"] < 1 or r["cig"] < 5),  # noqa: PLR2004
        (FlightsWhy.COLD, lambda r: r["tmp"] <= 0),
        (
            FlightsWhy.BEFORE,
            lambda r: (
                r["snow_before"] >= 1
                or r["ice_before"] >= 0.05  # noqa: PLR2004
                or r["pre_snow"] >= 1
                or r["pre_ice"] >= 0.05  # noqa: PLR2004
                or fm.after_storm(r["obs_snow"], r["obs_snow_old"], r["obs_frz"])
            ),
        ),
        (FlightsWhy.HUBS, lambda r: r["hub_snow"] >= 1 or r["hub_storm"] >= 0.4),  # noqa: PLR2004
    )


WHY_RULES: Final = _why_rules()
"""The plain reasons, in the order they are named, each with the forecast that names it."""

WHY_INPUTS: Final = (
    "ice",
    "p_zr",
    "snow",
    "p_snow",
    "thunder",
    "gust",
    "vis",
    "cig",
    "tmp",
    "snow_before",
    "ice_before",
    "pre_snow",
    "pre_ice",
    "obs_snow",
    "obs_snow_old",
    "obs_frz",
    "hub_snow",
    "hub_storm",
)


def why_of(day: Mapping[str, object]) -> tuple[FlightsWhy, ...]:
    """The reasons a day's forecast names (``day``: the day's worst values)."""
    values = {}
    for name in WHY_INPUTS:
        value = day.get(name)
        values[name] = float(value) if isinstance(value, int | float) else 0.0
    if not isinstance(day.get("vis"), int | float):
        values["vis"] = 10.0
    if not isinstance(day.get("cig"), int | float):
        values["cig"] = 999.0
    if not isinstance(day.get("tmp"), int | float):
        values["tmp"] = 50.0
    return tuple(why for why, rule in WHY_RULES if rule(values))


def per_mille(p: float) -> int:
    """A chance in tenths of a percent (0 to 1000), as the files give it."""
    return int(min(1000, max(0, round(p * 1000))))


@dataclass(slots=True)
class Pass:
    """One live pass's inputs, model and clock."""

    artifact: Artifact
    airports: Sequence[Airport]
    now: datetime
    read: Inputs
    slot: str | None = None
    """The slot this pass writes (:func:`next_slot`); by the clock when not given."""
    fresh: frozenset[str] = field(default=frozenset(), init=False)
    """The report stations whose observed reports reach the newest run
    (:func:`snowlight.flights.inputs.fresh_stations`): any other airport shows the usual rate."""

    def block_table(self) -> pl.DataFrame:
        """Per airport, run, day and block: the features of every whole block of lead class 1
        to 3 in the 00Z runs read (empty without one)."""
        runs = [run for run in self.read.runs if run.run.hour == 0]
        if not runs:
            return pl.DataFrame()
        z = zones(self.airports)
        features = block_features(rows_of(runs).lazy(), z.select("station", "apt", "tz")).collect()
        if features.is_empty():
            return features
        hubs = with_hubs(features, fm.HUBS).join(z.select("apt", "lat"), on="apt")
        flags = self.read.observed
        found = with_observed(
            hubs.lazy(),
            flags.lazy() if flags is not None else None,
            observed_stations(self.airports),
        )
        return found.collect()

    def build(self) -> FlightsLive:
        """The live file of this pass."""
        table = self.block_table()
        runs = [run.run for run in self.read.runs if run.run.hour == 0]
        flags = self.read.observed
        self.fresh = (
            inputs.fresh_stations(flags, max(runs)) if flags is not None and runs else frozenset()
        )
        newest_hour = flags.get_column("hour").max() if flags is not None and len(flags) else None
        by_block: dict[tuple[str, date, int], Mapping[str, object]] = {}
        by_day: dict[tuple[str, date], Mapping[str, object]] = {}
        day_run: dict[tuple[str, date], datetime] = {}
        if len(table):
            # Each airport day takes the newest run with a whole block of it, every block from
            # that one run: a newer run never mixes into an older one's day.
            newest = table.group_by("apt", "day").agg(pl.col("run").max())
            chosen = table.join(newest, on=["apt", "day", "run"])
            for row in chosen.iter_rows(named=True):
                by_block[(row["apt"], row["day"], int(row["block"]))] = row
                day_run[(row["apt"], row["day"])] = row["run"]
            for row in day_features(chosen).iter_rows(named=True):
                by_day[(row["apt"], row["day"])] = row
        faa = self.read.faa
        alerts = self.read.alerts
        programs: dict[str, list[inputs.Program]] | None = None
        if faa:
            programs = {}
            for program in faa[1]:
                programs.setdefault(program.code, []).append(program)
        alerted = alerts[1] if alerts else None
        entries: list[FlightsAirportLive] = []
        for airport in self.airports:
            entry = self._entry(
                airport,
                partial(self._airport, airport, by_block, by_day, day_run, programs, alerted),
                programs,
                alerted,
            )
            if entry is not None:
                entries.append(entry)
        header: dict[str, datetime | None] = {
            "run": max(runs) if runs else None,
            "programs_at": self._not_after(faa[0]) if faa else None,
            "alerts_at": self._not_after(alerts[0]) if alerts else None,
            "weather_at": (
                self._not_after(self.read.weather_at)
                if self.read.weather is not None and self.read.weather_at is not None
                else None
            ),
            "observed_at": (
                self._not_after(newest_hour) if isinstance(newest_hour, datetime) else None
            ),
        }
        # Each source's time is checked on its own: one that does not fit leaves that source as
        # not read (and its part of every airport with it), never the others (LR-F3).
        for name in list(header):
            if header[name] is not None and not self._fits(name, header[name]):
                sys.stderr.write(f"flights: the pass's {name} does not fit; that source not read\n")
                header[name] = None
                entries = [_unread(entry, name) for entry in entries]
        if (header["run"] is None and runs) or (
            header["observed_at"] is None and isinstance(newest_hour, datetime)
        ):
            # Chances made from a run or reports whose time cannot be written are never shown.
            return self.usual_only()
        try:
            document = FlightsLive(
                schema_version=1,
                generated_at=self.now.replace(microsecond=0),
                slot=self.slot or slot_of(self.now),
                stamp=stamp_of(self.now),
                airports=tuple(entries),
                **header,
            )
            document.to_json_bytes()  # as the file is written and read back
        except Exception as error:
            sys.stderr.write(
                f"flights: the pass's file does not fit ({type(error).__name__}); every airport "
                "shows its usual rate and every source as not read\n"
            )
            return self.usual_only()
        return document

    def _not_after(self, moment: datetime) -> datetime:
        """A source's time as published: never after the pass (a source clock a few minutes
        ahead, within :data:`snowlight.flights.inputs.CLOCK_AHEAD`, reads as the pass's time)."""
        return min(moment, self.now.replace(microsecond=0))

    def _fits(self, name: str, moment: datetime | None) -> bool:
        """Whether one source time fits the file on its own, as written and read back."""
        times = dict.fromkeys(_HEADER_TIMES)
        times[name] = moment
        try:
            FlightsLive.from_json_bytes(
                FlightsLive(
                    schema_version=1,
                    generated_at=self.now.replace(microsecond=0),
                    slot=self.slot or slot_of(self.now),
                    stamp=stamp_of(self.now),
                    airports=(),
                    **times,
                ).to_json_bytes()
            )
        except Exception:
            return False
        return True

    def usual_only(self) -> FlightsLive:
        """The pass's file with every source as not read and every airport at its marked usual
        rate (the fallback when the file made from the sources does not fit)."""
        entries = [
            entry
            for airport in self.airports
            if (entry := self._entry(airport, partial(self._usual_entry, airport))) is not None
        ]
        return FlightsLive(
            schema_version=1,
            generated_at=self.now.replace(microsecond=0),
            slot=self.slot or slot_of(self.now),
            stamp=stamp_of(self.now),
            run=None,
            programs_at=None,
            alerts_at=None,
            weather_at=None,
            observed_at=None,
            airports=tuple(entries),
        )

    def _entry(
        self,
        airport: Airport,
        make: Callable[[], FlightsAirportLive],
        programs: Mapping[str, list[inputs.Program]] | None = None,
        alerts: Mapping[str, list[FlightsAlert]] | None = None,
    ) -> FlightsAirportLive | None:
        """``make``'s entry when it fits the file as written and read back, else the airport's
        marked usual rate (LR-F3) with each part read of the sources that still fits on its own
        (its FAA programs, its alerts, its report), and each that does not marked not read;
        ``None`` only when even that does not fit."""
        try:
            entry = make()
            entry.to_json_bytes()
        except Exception as error:
            sys.stderr.write(
                f"flights: {airport.code} shows its usual rate this pass ({type(error).__name__})\n"
            )
        else:
            return entry
        try:
            entry = self._usual_entry(airport, *self._read_parts(airport, programs, alerts))
            entry.to_json_bytes()
        except Exception as error:
            sys.stderr.write(
                f"flights: {airport.code} left out of this pass ({type(error).__name__})\n"
            )
            return None
        return entry

    def _read_parts(
        self,
        airport: Airport,
        programs: Mapping[str, list[inputs.Program]] | None,
        alerts: Mapping[str, list[FlightsAlert]] | None,
    ) -> tuple[
        tuple[FlightsProgramNow, ...] | None,
        tuple[FlightsAlert, ...] | None,
        FlightsWeatherNow | None,
    ]:
        """The airport's FAA programs, alerts and report as read this pass, each on its own
        guard: one that does not fit the file is ``None`` (not read), never empty."""
        kept_programs: tuple[FlightsProgramNow, ...] | None = None
        kept_alerts: tuple[FlightsAlert, ...] | None = None
        report: FlightsWeatherNow | None = None
        try:
            if programs is not None:
                made = tuple(program_now(p) for p in programs.get(airport.code, []))
                for program in made:
                    FlightsProgramNow.from_json_bytes(program.to_json_bytes())
                kept_programs = made
        except Exception as error:
            sys.stderr.write(
                f"flights: {airport.code} programs not read ({type(error).__name__})\n"
            )
        try:
            if alerts is not None:
                kept_alerts = tuple(FlightsAlert(int(a)) for a in alerts.get(airport.code, []))
        except Exception as error:
            sys.stderr.write(f"flights: {airport.code} alerts not read ({type(error).__name__})\n")
        try:
            if self.read.weather is not None:
                report = weather_now(self.read.weather.get(airport.code), self.now)
                if report is not None:
                    FlightsWeatherNow.from_json_bytes(report.to_json_bytes())
        except Exception as error:
            sys.stderr.write(f"flights: {airport.code} report not read ({type(error).__name__})\n")
            report = None
        return kept_programs, kept_alerts, report

    def _usual_entry(
        self,
        airport: Airport,
        programs: tuple[FlightsProgramNow, ...] | None = None,
        alerts: tuple[FlightsAlert, ...] | None = None,
        report: FlightsWeatherNow | None = None,
    ) -> FlightsAirportLive:
        """The airport's marked usual rates: every block still to come and every day at its
        usual rate, marked so, with only the parts of the sources given (else not read)."""
        zone = ZoneInfo(airport.tz)
        today = (self.now.astimezone(zone) - timedelta(hours=5)).date()
        values: dict[str, list[list[int | None]]] = {t: [] for t in BLOCK_TARGETS}
        usual: dict[str, list[int]] = {t: [] for t in BLOCK_TARGETS}
        rough: list[int | None] = []
        for offset in range(DAYS):
            day = today + timedelta(days=offset)
            for target in BLOCK_TARGETS:
                table, kind = target.split("_")
                row: list[int | None] = []
                mask = 0
                for block in BLOCKS:
                    _, end = _block_span(day, block, zone)
                    if end <= self.now:
                        row.append(None)
                        continue
                    base = self.artifact.usual(table, kind, airport.code, int(block), day.month)
                    row.append(per_mille(base))
                    mask |= 1 << int(block)
                values[target].append(row)
                usual[target].append(mask)
            rough.append(per_mille(self.artifact.usual_rough(airport.code, day.month)))
        return FlightsAirportLive(
            code=airport.code,
            today=today,
            dep_canc=_rows(values["dep_canc"]),
            dep_late=_rows(values["dep_late"]),
            arr_canc=_rows(values["arr_canc"]),
            arr_late=_rows(values["arr_late"]),
            rough=(rough[0], rough[1], rough[2]),
            runs=(None, None, None),
            usual=tuple(_masks(usual[t]) for t in BLOCK_TARGETS),  # type: ignore[arg-type]
            rough_usual=(1 << DAYS) - 1,
            why=((), (), ()),
            programs=programs,
            alerts=alerts,
            now=report,
        )

    def _chance(
        self, airport: Airport, target: str, row: Mapping[str, object], base: float
    ) -> tuple[int, bool]:
        lead = int(str(row["lead_class"]))
        storm = fm.after_storm(*(_hours(row.get(name)) for name in OBSERVED_COLUMNS))
        if airport.wx not in self.fresh or not self.artifact.model.shows(
            airport.code, target, lead, stormy=storm
        ):
            return per_mille(base), True
        frame = pl.DataFrame([{**row, "base": base}])
        p = float(self.artifact.model.chance(target, lead, fm.design(frame))[0])
        return per_mille(p), False

    def _airport(  # noqa: PLR0913, PLR0917 - an airport and the pass's tables
        self,
        airport: Airport,
        by_block: Mapping[tuple[str, date, int], Mapping[str, object]],
        by_day: Mapping[tuple[str, date], Mapping[str, object]],
        day_run: Mapping[tuple[str, date], datetime],
        programs: Mapping[str, list[inputs.Program]] | None,
        alerts: Mapping[str, list[FlightsAlert]] | None,
    ) -> FlightsAirportLive:
        zone = ZoneInfo(airport.tz)
        local_now = self.now.astimezone(zone)
        today = (local_now - timedelta(hours=5)).date()
        values: dict[str, list[list[int | None]]] = {t: [] for t in BLOCK_TARGETS}
        usual: dict[str, list[int]] = {t: [] for t in BLOCK_TARGETS}
        rough: list[int | None] = []
        rough_usual = 0
        whys: list[tuple[FlightsWhy, ...]] = []
        runs: list[datetime | None] = []
        for offset in range(DAYS):
            day = today + timedelta(days=offset)
            runs.append(day_run.get((airport.code, day)))
            month = day.month
            masks = dict.fromkeys(BLOCK_TARGETS, 0)
            for target in BLOCK_TARGETS:
                values[target].append([])
            for block in BLOCKS:
                _, end = _block_span(day, block, zone)
                row = by_block.get((airport.code, day, int(block)))
                for target in BLOCK_TARGETS:
                    if end <= self.now or row is None:
                        values[target][-1].append(None)
                        continue
                    table, kind = target.split("_")
                    base = self.artifact.usual(table, kind, airport.code, int(block), month)
                    value, is_usual = self._chance(airport, target, row, base)
                    values[target][-1].append(value)
                    if is_usual:
                        masks[target] |= 1 << int(block)
            for target in BLOCK_TARGETS:
                usual[target].append(masks[target])
            whole = by_day.get((airport.code, day))
            if whole is None:
                rough.append(None)
            else:
                base = self.artifact.usual_rough(airport.code, month)
                value, is_usual = self._chance(airport, "rough", whole, base)
                rough.append(value)
                if is_usual:
                    rough_usual |= 1 << offset
            whys.append(why_of(whole) if whole is not None else ())
        report = self.read.weather.get(airport.code) if self.read.weather else None
        return FlightsAirportLive(
            code=airport.code,
            today=today,
            dep_canc=_rows(values["dep_canc"]),
            dep_late=_rows(values["dep_late"]),
            arr_canc=_rows(values["arr_canc"]),
            arr_late=_rows(values["arr_late"]),
            rough=(rough[0], rough[1], rough[2]),
            runs=(runs[0], runs[1], runs[2]),
            usual=tuple(_masks(usual[t]) for t in BLOCK_TARGETS),  # type: ignore[arg-type]
            rough_usual=rough_usual,
            why=(whys[0], whys[1], whys[2]),
            programs=(
                tuple(program_now(p) for p in programs.get(airport.code, []))
                if programs is not None
                else None
            ),
            alerts=tuple(alerts.get(airport.code, [])) if alerts is not None else None,
            now=weather_now(report, self.now),
        )


_HEADER_TIMES: Final = ("run", "programs_at", "alerts_at", "weather_at", "observed_at")
"""The file's source times, each checked on its own."""
_UNREAD: Final = {"programs_at": "programs", "alerts_at": "alerts", "weather_at": "now"}
"""The airport part each source time stands for."""


def _unread(entry: FlightsAirportLive, name: str) -> FlightsAirportLive:
    """``entry`` with the part the source time ``name`` stands for marked not read."""
    part = _UNREAD.get(name)
    return entry.model_copy(update={part: None}) if part is not None else entry


def program_now(program: inputs.Program) -> FlightsProgramNow:
    """A program as published; its minutes left out when they do not fit the file."""
    try:
        return FlightsProgramNow(
            program=program.program, minutes=program.minutes, until=program.until, why=program.kind
        )
    except ValidationError:
        return FlightsProgramNow(
            program=program.program, minutes=None, until=program.until, why=program.kind
        )


def weather_now(report: inputs.Report | None, now: datetime) -> FlightsWeatherNow | None:
    """A report as published, its time never after the pass ``now`` (a station clock a few
    minutes ahead reads as the pass's time); each number that does not fit the file left out,
    and the report itself when its time or kinds do not."""
    if report is None:
        return None
    for visibility, gust in (
        (report.visibility, report.gust),
        (None, None),
    ):
        try:
            return FlightsWeatherNow(
                at=min(report.at.replace(microsecond=0), now.replace(microsecond=0)),
                kinds=report.kinds,
                visibility=visibility,
                gust=gust,
            )
        except ValidationError:
            continue
    return None


def _hours(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def _row(day: list[int | None]) -> FlightsBlockRow:
    return (day[0], day[1], day[2], day[3], day[4])


def _rows(days: list[list[int | None]]) -> FlightsDayRows:
    return (_row(days[0]), _row(days[1]), _row(days[2]))


def _masks(days: list[int]) -> tuple[int, int, int]:
    return (days[0], days[1], days[2])


def latest(live: FlightsLive) -> FlightsLatest:
    """The pointer to a live file."""
    return FlightsLatest(
        schema_version=1, generated_at=live.generated_at, slot=live.slot, stamp=live.stamp
    )


def files(live: FlightsLive) -> dict[str, bytes]:
    """The pass's files by published path (under ``flights/``)."""
    return {
        f"flights/live/{live.slot}.json": live.to_json_bytes(),
        "flights/latest.json": latest(live).to_json_bytes(),
    }


ARCHIVE_DAYS: Final = 30
"""The host keeps this many days, one snapshot a day, each day's file rewritten
:data:`ARCHIVE_DAYS` days later (the lead's ruling LR-F7: the published tree holds the current
files and at most 30 days of history). The host cannot delete files and is the site's own tree,
so the archive stays bounded (:data:`ARCHIVE_BUDGET`). BTS posts a month about 50 days after it
ends, so the monthly job copies each day's snapshot into its history cache while the host still
holds it (:func:`snowlight.flights.monthly.keep_archive`) and scores from that copy."""
ARCHIVE_BUDGET: Final = 150_000_000
"""The most bytes the whole archive may take on the host."""
LIVE_BUDGET: Final = 1_500_000
"""The most bytes the three live slots and ``latest.json`` may take."""
HOST_BUDGET: Final = 200_000_000
"""The most bytes every Flights file may take on the host together: the archive, the live files
and the monthly build (:data:`snowlight.flights.monthly.BUILD_BUDGET`). The host's tree is the
site's, uploaded whole by every Schools deploy, so it stays bounded."""
ARCHIVE_BY_HOUR: Final = 6
"""A day's snapshot is taken by the first pass that has that day's 00Z run, before 06Z (still
the evening before across the US)."""
TAF_LENGTH: Final = 1200


def archive_path(day: date) -> str:
    """Where the snapshot of ``day`` (the UTC date of its 00Z run) is kept: the ring slot of
    that day, rewritten :data:`ARCHIVE_DAYS` days later."""
    return f"flights/archive/{archive_slot(day)}.json"


def archive_day(live: FlightsLive, now: datetime) -> date | None:
    """The day this pass may keep a snapshot of: today (UTC) when the pass has today's 00Z run
    and it is not yet :data:`ARCHIVE_BY_HOUR`; else ``None``."""
    today = now.astimezone(UTC).date()
    run = live.run
    if run is None or now.astimezone(UTC).hour >= ARCHIVE_BY_HOUR:
        return None
    if run.astimezone(UTC).date() != today or run.hour != 0:
        return None
    return today


def kept_day(data: bytes | None) -> date | None:
    """The day a kept snapshot is of (``None``: none kept, or not a valid snapshot)."""
    if data is None:
        return None
    try:
        return FlightsArchive.from_json_bytes(data).day
    except ValueError:
        return None


def archive_slot(day: date) -> str:
    """The ring slot of ``day``'s snapshot (:func:`archive_path`)."""
    return f"{day.toordinal() % ARCHIVE_DAYS:03d}"


def _screened(text: str) -> str | None:
    try:
        return screen_text(text)
    except ValueError:
        return None


def archive_document(
    live: FlightsLive, read: Inputs, artifact: Artifact, tafs: Mapping[str, str], day: date
) -> FlightsArchive:
    """The archive snapshot of ``day`` (D9): the published file, the usual rates behind it (in
    tenths of a percent, rounded as the published chances are, so scoring holds both to the
    same rounding), and the FAA programs (with the FAA's own reasons), weather reports and TAFs
    as read, for scoring and later fits. A reason or TAF the text screen refuses is left out."""
    usual = []
    for entry in live.airports:
        tomorrow = entry.today + timedelta(days=1)
        row = [
            per_mille(artifact.usual("dep", "canc", entry.code, int(block), tomorrow.month))
            for block in BLOCKS
        ]
        usual.append(
            FlightsUsualTomorrow(
                code=entry.code,
                dep_canc=(row[0], row[1], row[2], row[3], row[4]),
                rough=per_mille(artifact.usual_rough(entry.code, tomorrow.month)),
            )
        )
    programs = []
    for p in read.faa[1] if read.faa else []:
        why = _screened(p.why[:80])
        programs.append(
            FlightsArchiveProgram(
                code=p.code,
                program=p.program,
                minutes=program_now(p).minutes,
                why=why if why else "",
            )
        )
    forecasts = []
    for code, text in sorted(tafs.items()):
        screened = _screened(text[:TAF_LENGTH])
        if screened:
            forecasts.append(FlightsArchiveForecast(code=code, text=screened))
    return FlightsArchive(
        schema_version=1,
        slot=archive_slot(day),
        day=day,
        live=live,
        usual_tomorrow=tuple(usual),
        programs=tuple(programs),
        reports=tuple(
            FlightsArchiveReport(code=code, report=now)
            for code, report in sorted((read.weather or {}).items())
            if (now := weather_now(report, live.generated_at)) is not None
        ),
        forecasts=tuple(forecasts),
    )


def archive_bytes(
    live: FlightsLive, read: Inputs, artifact: Artifact, tafs: Mapping[str, str], day: date
) -> bytes:
    """The archive snapshot of ``day`` as published (:func:`archive_document`), validated."""
    return archive_document(live, read, artifact, tafs, day).to_json_bytes()


def chance_array(values: Sequence[float]) -> np.ndarray:
    """Chances as an array (for tests and the monthly scoring)."""
    return np.asarray(values, dtype=np.float64)


Reader = Callable[[], bytes | None]

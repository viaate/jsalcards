"""The model learning on its own from live-read days (S7-L), over the synthetic world.

Every timeline, read, label and storm here is made up for the tests (SYNTHETIC); nothing
comes from a real list.
"""

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from predict import world
from predict.test_publish import NOW, MemoryHost, feed, make_pass
from predict.test_serve import index, storm
from snowlight.live.history import BY, BY_HOLD, ChangeLog, Event, Shown
from snowlight.live.history import Change as LogChange
from snowlight.live.morning import ANY_KIND, MorningLog, Slot, slot_start
from snowlight.live.state import pack
from snowlight.predict import cli, learn
from snowlight.predict import serve as serve_module
from snowlight.predict.artifact import SITUATION_KEYS, Learned, ModelArtifact
from snowlight.predict.config import PredictConfig
from snowlight.predict.labels import LitStatus
from snowlight.predict.learn import (
    Decision,
    LearnStore,
    Score,
    decide,
    learned_from,
    no_worse,
    score,
)
from snowlight.predict.live_labels import (
    Lit,
    Morning,
    NoLiveSource,
    StateSource,
    StationStats,
    day_ready,
    finish_labels,
    label_live_day,
    lit_of,
    record_snapshots,
    snapshot_classes,
)
from snowlight.predict.opens import SaidOpen
from snowlight.predict.serve import ServeError, ServeModel, build_model, district_classes
from snowlight.predict.serve import forecast_file as made_file
from snowlight.predict.situations import WeatherClass, Window
from snowlight.schemas.live import DayIndex, DayTimeline
from snowlight.schemas.predictions import MAX_OUTLOOKS, AlertBase, Forecast, PredictionsFile
from snowlight.schemas.vocab import Reason, Status

CFG = world.CONFIG.model_copy(
    update={
        "learn": world.CONFIG.learn.model_copy(
            update={
                "anchor_min_days": 40,
                "holdout_min_storm_rows": 20,
                "holdout_min_situation_rows": 10,
                "holdout_bin_min_rows": 5,
            }
        )
    }
)
"""The shipped rules with thresholds a five-district world can reach."""
SHA = "c" * 64
SNOW = SITUATION_KEYS.index("snow_warning")
WINDOW = Window(CFG.weather.window_from, CFG.weather.window_until, CFG.weather.snapshot_hour)
SLACK = timedelta(minutes=CFG.learn.snapshot_slack_minutes)
DAY = date(2026, 1, 6)  # a Tuesday: the synthetic world's timeline day
MO = ("2900001", "2900002", "2900003")


def built(learned: Learned | None = None, config: PredictConfig = CFG) -> ServeModel:
    return build_model(world.directory(), world.model(), config, lambda _lon, _lat: None, learned)


def weekdays(start: date, count: int) -> list[date]:
    found: list[date] = []
    day = start
    while len(found) < count:
        if day.weekday() < 5:
            found.append(day)
        day += timedelta(days=1)
    return found


def store_of(
    outcomes: Sequence[Mapping[str, str]],
    start: date = date(2025, 10, 6),
    key: str = "snow_warning",
) -> LearnStore:
    """SYNTHETIC: one labeled live day per mapping (LEAID to what it did)."""
    store = LearnStore.empty()
    for day, by in zip(weekdays(start, len(outcomes)), outcomes, strict=True):
        labels: dict[str, dict[str, list[str]]] = {}
        for leaid, did in by.items():
            labels.setdefault(key, {}).setdefault(did, []).append(leaid)
        store = store.with_day(day, labels, 0)
    return store


def honest(j: int) -> dict[str, str]:
    """SYNTHETIC: each district closes on one storm day in five."""
    return {d: "closed" if (j + i) % 5 == 0 else "open" for i, d in enumerate(world.DISTRICTS)}


MISREAD = dict.fromkeys(world.DISTRICTS, "closed")
"""SYNTHETIC: a day a broken reader showed every district closed."""


def run_decide(
    store: LearnStore, current: Learned | None = None, config: PredictConfig = CFG
) -> Decision:
    return decide(
        store,
        current,
        lambda learned: built(learned, config),
        SHA,
        config,
        world.utc("2026-01-07T09:00:00"),
    )


# --- labels ---------------------------------------------------------------------------------------


def classes_all(weather: WeatherClass) -> list[WeatherClass | None]:
    return [weather] * len(world.DISTRICTS)


def labels_by_district(rows: Sequence[Mapping[str, object]]) -> dict[str, tuple[object, object]]:
    frame = finish_labels(rows, CFG.labels.storm_absence_share)
    return {r["district"]: (r["outcome"], r["unknown_why"]) for r in frame.iter_rows(named=True)}


KC_CARRIED = ("2000004", "2900001", "2900002")
CARRIED = {"tv": dict.fromkeys(KC_CARRIED, date(2025, 12, 1))}
"""SYNTHETIC: the TV list lit schools of these districts on earlier days: it carries them."""
WINDOW_SLOTS = tuple(f"{h:02d}:{m:02d}" for h in range(12, 17) for m in (0, 30))[1:]
"""UTC slots 12:30-16:30: 06:30-09:30 Central (12:30-15:30Z) and Mountain (13:30-16:30Z)."""
WHOLE = (10, 10, 0)
"""SYNTHETIC: a whole populated read of ten rows, all placed, all read."""
EMPTY = (0, 0, 0)


def stats(**captures: int) -> StationStats:
    found = {"tv": 10, "radio": 10, **captures}
    return StationStats(
        captures=found,
        median_rows=dict.fromkeys(found, 10.0),
        placed=dict.fromkeys(found, 1.0),
    )


def morning_of(  # noqa: PLR0913 - every part a test sets
    reads: Mapping[str, Sequence[tuple[int, int, int]]],
    *,
    audience: Mapping[str, Mapping[str, date]] = CARRIED,
    shown: Sequence[str] = ("v1",),
    unknown: Sequence[str] = (),
    named: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    named_before: Mapping[str, Sequence[str]] | None = None,
    station_stats: StationStats | None = None,
    held: bool = False,
    day: date = DAY,
) -> Morning:
    """SYNTHETIC: one day's record: every window slot shown under ``shown``, the sources'
    ``reads`` in the 13:00Z slot (07:00 Central), ``named`` in the 13:30Z slot."""
    slots = {
        slot_start(day, key): Slot(shown=set(shown), unknown=set(unknown)) for key in WINDOW_SLOTS
    }
    first = slots[slot_start(day, "13:00")]
    first.reads = {source: set(found) for source, found in reads.items()}
    if named:
        slots[slot_start(day, "13:30")].named = {
            leaid: {d: set(kinds) for d, kinds in days.items()} for leaid, days in named.items()
        }
    return Morning(
        day=day,
        slots=slots,
        audience=audience,
        market_of={"tv": "KC", "radio": "KC"},
        stats=station_stats or stats(),
        prefix="v1",
        named_before={k: frozenset(v) for k, v in (named_before or {}).items()},
        held=held,
    )


def label(
    found: Morning,
    weather: WeatherClass = WeatherClass.SNOW_WARNING,
    lit: Lit | None = None,
) -> dict[str, tuple[object, object]]:
    return labels_by_district(
        label_live_day(
            found.day,
            lit=lit_of(world.timeline()) if lit is None else lit,
            morning=found,
            classes=classes_all(weather),
            directory=learn.directory_of(built()),
            settings=CFG.labels,
        )
    )


DARK = Lit({}, frozenset())


def test_only_districts_read_whole_are_labeled_and_absence_in_a_storm_is_unknown() -> None:
    found = label(morning_of({"tv": [WHOLE]}))
    # 2900003 showed a closing but no list that carries it was read: no label at all.
    assert set(found) == set(KC_CARRIED)
    assert found["2900001"] == ("no_school", None)
    # Read, dark, on a storm day when half the market closed: unknown, never open.
    assert found["2900002"] == ("unknown", "absent_in_storm")
    assert found["2000004"] == ("unknown", "absent_in_storm")
    # On a quiet day a dark district whose list was read whole is open.
    quiet = label(morning_of({"tv": [WHOLE]}), WeatherClass.NONE, DARK)
    assert quiet == dict.fromkeys(KC_CARRIED, ("open", None))


def test_the_archive_read_gates_hold_for_live_reads() -> None:
    # B1: on a storm morning an empty list alone is not a read (empty_uncorroborated) ...
    alone = label(morning_of({"tv": [EMPTY]}), lit=DARK)
    assert alone == dict.fromkeys(KC_CARRIED, ("unknown", "empty_uncorroborated"))
    # ... unless another list of the market read too; on a quiet day it is.
    both = label(morning_of({"tv": [EMPTY], "radio": [EMPTY]}), lit=DARK)
    assert both == dict.fromkeys(KC_CARRIED, ("open", None))
    assert label(morning_of({"tv": [EMPTY]}), WeatherClass.NONE, DARK) == both
    # An empty list while a market peer holds five rows or more: void (voided_empty).
    busy = label(morning_of({"tv": [EMPTY], "radio": [(6, 6, 0)]}), WeatherClass.NONE, DARK)
    assert busy == dict.fromkeys(KC_CARRIED, ("unknown", "voided_empty"))
    # A storm-day list under half its usual rows is partial (small_capture).
    small = label(morning_of({"tv": [(3, 3, 0)]}), lit=DARK)
    assert small == dict.fromkeys(KC_CARRIED, ("unknown", "small_capture"))
    assert label(morning_of({"tv": [(3, 3, 0)]}), WeatherClass.NONE, DARK) == both
    # A list with too few reads to tell whole from partial (thin_station).
    thin = label(morning_of({"tv": [WHOLE]}, station_stats=stats(tv=2)), WeatherClass.NONE, DARK)
    assert thin == dict.fromkeys(KC_CARRIED, ("unknown", "thin_station"))
    # A read the reader could not read, or the matcher placed too little of (dropped_read).
    for broken in ((10, 10, 5), (10, 2, 0)):
        dropped = label(morning_of({"tv": [broken]}), WeatherClass.NONE, DARK)
        assert dropped == dict.fromkeys(KC_CARRIED, ("unknown", "dropped_read"))


def test_a_district_a_list_named_without_the_map_lighting_it_is_never_open() -> None:
    # B1/B2: a row named 2900002 for the day (a breaker, a conflict, a weak reading, a
    # refused publish: the map stayed dark), or for every day (withheld, undated).
    for days in ({DAY.isoformat(): ["closed"]}, {"*": [ANY_KIND]}):
        found = label(morning_of({"tv": [WHOLE]}, named={"2900002": days}), WeatherClass.NONE, DARK)
        assert found["2900002"] == ("unknown", "listed_unread")
        assert found["2900001"] == ("open", None)
    # Named the evening before for the day: the same.
    before = label(morning_of({"tv": [WHOLE]}, named_before={"2900002": ["closed"]}),
                   WeatherClass.NONE, DARK)  # fmt: skip
    assert before["2900002"] == ("unknown", "listed_unread")
    # A row about another day says nothing of this one.
    other = label(morning_of({"tv": [WHOLE]}, named={"2900002": {"2026-01-07": ["closed"]}}),
                  WeatherClass.NONE, DARK)  # fmt: skip
    assert other["2900002"] == ("open", None)
    # A district the map lit closed is labeled by what it showed.
    lit = label(morning_of({"tv": [WHOLE]}, named={"2900001": {"*": [ANY_KIND]}}))
    assert lit["2900001"] == ("no_school", None)


def delayed_lit(*leaids: str, dismissed: Sequence[str] = ()) -> Lit:
    """SYNTHETIC: every eligible school of ``leaids`` lit delayed for snow, and the first
    school of each of ``dismissed`` lit dismissed early instead."""
    directory = learn.directory_of(built())
    statuses: dict[int, LitStatus] = {}
    for leaid in leaids:
        for school in directory.eligible[directory.districts.index(leaid)].tolist():
            statuses[int(school)] = LitStatus(Status.DELAYED, Reason.WINTER_STORM)
    for leaid in dismissed:
        school = int(directory.eligible[directory.districts.index(leaid)][0])
        statuses[school] = LitStatus(Status.EARLY_DISMISSAL, Reason.WINTER_STORM)
    return Lit(statuses, frozenset())


def test_a_district_the_map_lit_delayed_is_delayed() -> None:
    # B1 (round 2), SYNTHETIC: the KC districts lit delayed on a whole read, each named only by
    # its own lit delay rows: delayed, never unknown.
    lit = delayed_lit(*KC_CARRIED)
    own = {leaid: {DAY.isoformat(): ["delayed"]} for leaid in KC_CARRIED}
    found = label(morning_of({"tv": [WHOLE]}, named=own), lit=lit)
    assert found == dict.fromkeys(KC_CARRIED, ("delayed", None))
    # A row also named 2900002 closed (or remote, or an early dismissal) and the map never
    # showed it: what it did is not known.
    for kind in ("closed", "remote", "early_dismissal"):
        named = {**own, "2900002": {DAY.isoformat(): ["delayed", kind]}}
        found = label(morning_of({"tv": [WHOLE]}, named=named), lit=lit)
        assert found["2900002"] == ("unknown", "listed_unread")
        assert found["2900001"] == ("delayed", None)
    # A dissenting, unsure or unread row named it, that day or every day: the same.
    for days in ({DAY.isoformat(): [ANY_KIND]}, {"*": [ANY_KIND]}):
        found = label(morning_of({"tv": [WHOLE]}, named={**own, "2900002": days}), lit=lit)
        assert found["2900002"] == ("unknown", "listed_unread")
    before = label(morning_of({"tv": [WHOLE]}, named=own, named_before={"2900002": ["closed"]}),
                   lit=lit)  # fmt: skip
    assert before["2900002"] == ("unknown", "listed_unread")
    # A status the map did show on one of its schools accounts for that naming: 2900001
    # (two schools) showed one delayed and one dismissed early.
    shown = delayed_lit(*KC_CARRIED, dismissed=["2900001"])
    named = {**own, "2900001": {DAY.isoformat(): ["delayed", "early_dismissal"]}}
    found = label(morning_of({"tv": [WHOLE]}, named=named), lit=shown)
    assert found["2900001"] == ("delayed", None)
    hidden = {**own, "2900001": {DAY.isoformat(): ["delayed", "early_dismissal", "closed"]}}
    found = label(morning_of({"tv": [WHOLE]}, named=hidden), lit=shown)
    assert found["2900001"] == ("unknown", "listed_unread")


def test_a_dark_map_is_never_read_as_an_open_list() -> None:
    reads = {"tv": [WHOLE]}
    # B2: every pass of the window withheld Missouri whole (a source whose say was unknown).
    withheld = label(morning_of(reads, unknown=["MO"]), WeatherClass.NONE, DARK)
    assert withheld["2900001"] == withheld["2900002"] == ("unknown", "not_read")
    assert withheld["2000004"] == ("open", None)  # Kansas was shown
    # The gate refused every pass (nothing shown), or showed it only under another prefix.
    for shown in ((), ("v1-shadow",)):
        dark = label(morning_of(reads, shown=shown), WeatherClass.NONE, DARK)
        assert dark == dict.fromkeys(KC_CARRIED, ("unknown", "not_read"))
    # A read outside the settled window (10:00 Central) is not a read of the morning.
    late = morning_of({})
    late.slots[slot_start(DAY, "16:00")].reads = {"tv": {WHOLE}}
    assert label(late, WeatherClass.NONE, DARK) == dict.fromkeys(
        KC_CARRIED, ("unknown", "not_read")
    )


def test_a_record_that_stops_inside_the_window_reads_nothing() -> None:
    # S1, SYNTHETIC: the passes stopped after 07:00 Central (an ingest outage, passes failing
    # before they were recorded): the early whole read does not make the districts open.
    whole = morning_of({"tv": [WHOLE]})
    stopped = replace(whole, slots={at: slot for at, slot in whole.slots.items() if at <= world.utc(
        "2026-01-06T13:00:00")})  # fmt: skip
    assert label(stopped, WeatherClass.NONE, DARK) == dict.fromkeys(
        KC_CARRIED, ("unknown", "not_read")
    )
    # Passes in the window's last slot (15:00Z, 09:00 Central) after a gap: the read counts.
    resumed = replace(whole, slots={at: slot for at, slot in whole.slots.items() if at <= world.utc(
        "2026-01-06T13:00:00") or at in (world.utc("2026-01-06T15:00:00"), world.utc(
        "2026-01-06T16:00:00"))})  # fmt: skip
    assert label(resumed, WeatherClass.NONE, DARK) == dict.fromkeys(KC_CARRIED, ("open", None))


def test_a_held_break_unclassed_or_retracted_day_stays_unknown() -> None:
    directory = learn.directory_of(built())
    common: dict[str, Any] = {"directory": directory, "settings": CFG.labels}
    lit = lit_of(world.timeline())
    snow = classes_all(WeatherClass.SNOW_WARNING)
    held = morning_of({"tv": [WHOLE]}, held=True)
    assert label_live_day(DAY, lit=lit, morning=held, classes=snow, **common) == []
    holiday = date(2025, 12, 22)
    found = morning_of({"tv": [WHOLE]}, day=holiday)
    rows = label_live_day(holiday, lit=lit, morning=found, classes=snow, **common)
    assert {r["unknown_why"] for r in rows} == {"break"}
    unclassed = [None] * len(world.DISTRICTS)
    rows = label_live_day(DAY, lit=lit, morning=morning_of({"tv": [WHOLE]}), classes=unclassed,
                          **common)  # fmt: skip
    assert {r["unknown_why"] for r in rows} == {"no_weather"}
    # School 2 (district 2900002) was lit closed, then the status was taken back.
    taken_back = world.timeline().model_copy(
        update={"gaps": (2,), "counts": (2,), "minutes": (300, 360),
                "statuses": (Status.CLOSED, None), "reasons": (Reason.WINTER_STORM, None)}
    )  # fmt: skip
    rows = label_live_day(DAY, lit=lit_of(taken_back), morning=morning_of({"tv": [WHOLE]}),
                          classes=snow, **common)  # fmt: skip
    assert {r["district"]: r["unknown_why"] for r in rows}["2900002"] == "retracted"


def listing(day: date, nces: str, source: str) -> LogChange:
    at = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)
    shown = Shown(int(Status.CLOSED), int(Reason.WINTER_STORM), None, None)
    return LogChange(at, day, nces, Event.LIT, shown, {"source_id": source})


def state_source(folder: Path) -> StateSource:
    return StateSource(
        folder=folder,
        market_of={"tv": "KC"},
        zone_of=dict(world.ZONES),
        settings=CFG.labels,
        prefix="v1",
        read_file=lambda _path: None,
    )


def test_the_state_folder_gives_the_morning_once_its_record_is_whole(tmp_path: Path) -> None:
    folder = tmp_path / "state"
    log = MorningLog(folder / "morning")
    # 07:00 Central is 13:00Z.
    log.record(world.utc("2026-01-06T13:00:00"), shown="v1", reads={"tv": WHOLE}, unknown=(),
               named={"2900002": {"*": {ANY_KIND}}})  # fmt: skip
    log.record(world.utc("2026-01-05T23:00:00"), shown="v1", reads={}, unknown=(),
               named={"2900003": {DAY.isoformat(): {"closed"}},
                      "2000004": {"2026-01-05": {"closed"}}})  # fmt: skip
    changes = ChangeLog(folder / "changes")
    # The TV list lit a school of 2900002 on two earlier days: it carries that district; it
    # lit 2900003 once only: not its audience.
    changes.commit(
        [
            listing(date(2026, 1, 2), "290000200003", "tv"),
            listing(date(2026, 1, 5), "290000200003", "tv"),
            listing(date(2026, 1, 5), "290000300004", "tv"),
        ]
    )
    source = state_source(folder)
    # S4: the record stops at 13:00Z, before the read windows closed (16:30Z in Mountain).
    assert source.morning(DAY) == "the live state was saved before its read windows closed"
    log.record(world.utc("2026-01-06T17:00:00"), shown="v1", reads={}, unknown=(), named={})
    found = state_source(folder).morning(DAY)
    assert isinstance(found, Morning)
    assert found.audience == {"tv": {"2900002": date(2026, 1, 2)}}
    assert found.slots[world.utc("2026-01-06T13:00:00")].reads == {"tv": {WHOLE}}
    assert found.named_before == {"2900003": frozenset({"closed"})}
    assert not found.held
    assert found.stats.captures == {"tv": 1}
    # The emergency stop held the map dark on the day: nothing is labeled.
    changes.commit([LogChange(world.utc("2026-01-06T14:00:00"), DAY, "290000100001", Event.DARK,
                              None, {BY: BY_HOLD})])  # fmt: skip
    held = state_source(folder).morning(DAY)
    assert isinstance(held, Morning)
    assert held.held
    # No record of the day, or one that does not read.
    assert state_source(folder).morning(date(2026, 1, 7)) == "no record of the live reads"
    log.path(DAY).write_text("{")
    assert state_source(folder).morning(DAY) == "its record of the live reads does not read"
    assert state_source(tmp_path / "none").morning(DAY) == "no record of the live reads"


def test_a_listed_day_with_no_timeline_that_reads_waits() -> None:
    # S3: the host's index lists the day, but its timeline does not read: not ready.
    entry = {"day": DAY.isoformat(), "schools": 3, "final": True}
    index = DayIndex.from_json_bytes(
        json.dumps(
            {"schema_version": 1, "generated_at": "2026-01-08T12:00:00Z", "days": [entry]}
        ).encode()
    )
    assert (
        day_ready(DAY, None, index) == "the live host lists its timeline but holds none that reads"
    )
    empty = index.model_copy(update={"days": ()})
    assert day_ready(DAY, None, empty) is None
    early = empty.model_copy(update={"generated_at": world.utc("2026-01-07T05:00:00")})
    assert day_ready(DAY, None, early) == "its timeline is not final yet"
    assert day_ready(DAY, world.timeline(), None) is None


def test_a_class_taken_too_early_or_for_another_directory_is_unknown() -> None:
    model = built()
    zones = model.time_zone
    content = learn.content_key(model.directory)
    snow = np.full((len(zones), 1), int(WeatherClass.SNOW_WARNING), dtype=np.int64)
    record = record_snapshots(
        {}, content=content, zones=zones, classes=snow, days=[DAY], now=world.utc(
            "2026-01-06T02:30:00"), window=WINDOW
    )  # fmt: skip
    found = snapshot_classes(record, DAY, content=content, zones=zones, window=WINDOW, slack=SLACK)
    # 20:30 Central is within the hour before 21:00; 19:30 Mountain is not.
    for leaid, value in zip(world.DISTRICTS, found, strict=True):
        assert value == (None if leaid == "4900005" else WeatherClass.SNOW_WARNING)
    later = record_snapshots(
        record, content=content, zones=zones, classes=np.zeros_like(snow), days=[DAY],
        now=world.utc("2026-01-06T03:30:00"), window=WINDOW,
    )  # fmt: skip
    found = snapshot_classes(later, DAY, content=content, zones=zones, window=WINDOW, slack=SLACK)
    # Central's snapshot had passed: its class is kept; Mountain's is now taken in time.
    assert found == [WeatherClass.SNOW_WARNING] * 4 + [WeatherClass.NONE]
    other = snapshot_classes(later, DAY, content="x", zones=zones, window=WINDOW, slack=SLACK)
    assert other == [None] * len(zones)


# --- labeling the new days ------------------------------------------------------------------------


class Source:
    """SYNTHETIC live days: reads on every day but ``unread``, the given timelines."""

    def __init__(self, timelines: Mapping[date, DayTimeline], unread: Sequence[date] = ()) -> None:
        self.timelines = timelines
        self.unread = set(unread)

    def index(self) -> DayIndex | None:
        return None

    def timeline(self, day: date) -> DayTimeline | None:
        return self.timelines.get(day)

    def morning(self, day: date) -> Morning | str:
        if day in self.unread:
            return "no record of the live reads"
        return morning_of({"tv": [WHOLE]}, day=day)


def snapshots_for(
    day: date, weather: WeatherClass = WeatherClass.SNOW_WARNING
) -> dict[str, object]:
    model = built()
    content = learn.content_key(model.directory)
    snow = np.full((len(model.time_zone), 1), int(weather), dtype=np.int64)
    record: Mapping[str, object] = {}
    eve = datetime.combine(day - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    for hour in (26.5, 27.5):  # 02:30Z and 03:30Z the next morning (UTC)
        record = record_snapshots(
            record, content=content, zones=model.time_zone, classes=snow, days=[day],
            now=eve + timedelta(hours=hour), window=WINDOW,
        )  # fmt: skip
    return dict(record)


SHORT = CFG.model_copy(update={"learn": CFG.learn.model_copy(update={"morning_reads_days": 3})})
"""Labels the 5th to the 7th of January 2026 on the 8th."""
MONDAY = date(2026, 1, 5)


def test_unready_days_wait_a_labeled_day_is_frozen_and_reruns_change_nothing() -> None:
    directory = learn.directory_of(built())
    shown_monday = world.timeline().model_copy(update={"day": MONDAY})
    unfinished = shown_monday.model_copy(update={"final": False})
    source = Source({DAY: world.timeline(), MONDAY: unfinished})
    snapshots = {**snapshots_for(DAY), **snapshots_for(MONDAY)}
    # 06:00Z on 8 January: the 7th is not over in Hawaii yet.
    now = world.utc("2026-01-08T06:00:00")
    done = learn.label_new_days(LearnStore.empty(), source, directory, snapshots, SHORT, now)
    # The 5th's timeline is not final, and the 6th waits for it (S2: which districts the 6th
    # follows a closing of is told from the 5th); the 7th is not over everywhere.
    assert done.added == []
    assert done.skipped == {
        "its timeline is not final yet": 1,
        "its previous school day is not labeled yet": 1,
        "not over everywhere yet": 1,
    }
    final = Source({DAY: world.timeline(), MONDAY: shown_monday})
    done = learn.label_new_days(LearnStore.empty(), final, directory, snapshots, SHORT, now)
    assert done.added == [MONDAY, DAY]
    rows = done.store.rows().filter(pl.col("day") == DAY)
    assert rows["district"].to_list() == ["2900001"]
    assert rows["did"].to_list() == ["closed"]
    # The two dark districts of a storm market are unknown.
    assert done.store.days[1].unknown == 2
    again = learn.label_new_days(done.store, final, directory, snapshots, SHORT, now)
    assert again.added == []
    assert again.store.to_bytes() == done.store.to_bytes()
    # A day with no record of the morning's reads is never labeled, and the day after it
    # need not wait for it.
    unread = Source({DAY: world.timeline(), MONDAY: shown_monday}, unread=[DAY])
    blind = learn.label_new_days(LearnStore.empty(), unread, directory, snapshots, SHORT, now)
    assert blind.added == [MONDAY]
    assert blind.skipped["no record of the live reads"] == 1
    no_monday = Source({DAY: world.timeline()}, unread=[MONDAY])
    after = learn.label_new_days(LearnStore.empty(), no_monday, directory, snapshots, SHORT, now)
    assert after.added == [DAY]


def test_a_day_after_a_closing_is_told_from_the_previous_school_day() -> None:
    # S2, SYNTHETIC: an advisory on both days; 2900001 closed on the 5th. Labeled in one run
    # or the 5th first, the 6th's 2900001 is the day after a closing.
    directory = learn.directory_of(built())
    snapshots = {**snapshots_for(DAY, WeatherClass.ADVISORY),
                 **snapshots_for(MONDAY, WeatherClass.ADVISORY)}  # fmt: skip
    shown_monday = world.timeline().model_copy(update={"day": MONDAY})
    now = world.utc("2026-01-08T06:00:00")
    source = Source({DAY: world.timeline(), MONDAY: shown_monday})
    done = learn.label_new_days(LearnStore.empty(), source, directory, snapshots, SHORT, now)
    rows = done.store.rows().filter((pl.col("day") == DAY) & (pl.col("district") == "2900001"))
    assert [SITUATION_KEYS[k] for k in rows["situation"].to_list()] == ["advisory_after"]


# --- the check and the swap -----------------------------------------------------------------------


def test_honest_live_days_re_anchor_the_storm_level_and_swap_in() -> None:
    store = store_of([honest(j) for j in range(30)])
    decision = run_decide(store)
    assert decision.kind == "swap", decision.why
    learned = decision.learned
    assert learned is not None
    assert learned.anchored == ("snow_warning",)
    held_out = 4 * len(world.DISTRICTS)
    assert learned.check["held_out_rows"] == held_out
    assert learned.check["refit_brier"] < learned.check["served_brier"]
    assert learned.labeled_days == 26 * len(world.DISTRICTS)
    # The held-out days are never in what is swapped in.
    record_days = [item.day for by in learned.records.values() for r in by.values() for item in r]
    assert record_days
    assert max(record_days) <= learned.through
    # Serving it: the storm situation counts the live days, and its sentence says so.
    model = built(learned)
    assert model.anchored[SNOW]
    assert not model.anchored[SITUATION_KEYS.index("none")]
    assert built(None).p[1, SNOW] > model.p[1, SNOW]
    now = world.utc("2026-01-07T02:00:00")
    days = (date(2026, 1, 6), date(2026, 1, 7))
    classes = district_classes(model, storm(), index(), days, now, WINDOW, 0.5)
    made = made_file(model, classes, days, now, closed_on=lambda _day: None, last=None)
    own = made.districts[1].days[1]
    assert isinstance(own, Forecast)
    assert isinstance(own.why.base, AlertBase)
    assert own.why.base.live
    archive = made_file(built(None), classes, days, now, closed_on=lambda _day: None, last=None)
    before = archive.districts[1].days[1]
    assert isinstance(before, Forecast)
    assert isinstance(before.why.base, AlertBase)
    assert not before.why.base.live


LATEST = "v1/predictions/latest.json"


def chances(data: bytes) -> list[object]:
    """Every district's and private school's chances and whys in a file, in order."""
    made = PredictionsFile.from_json_bytes(data)
    days = [day for entry in made.districts for day in entry.days]
    days += [day for entry in made.schools for day in made.outlook_of(entry)]
    return [
        (day.p_no_school, day.p_delay, day.reasons, day.why) if isinstance(day, Forecast) else day
        for day in days
    ]


def test_a_pass_over_the_size_budget_steps_down_the_fit_ladder(capsys: Any) -> None:  # noqa: PLR0915 - each step in order
    # B1 (S7-2 round 2): a learned file may give every district an own base with 8 live days,
    # which the size budget does not hold under a storm over the whole country. Over the
    # budget, the pass publishes every chance and why without the record days, then without
    # private schools' previous chances, then without any previous chance, then (round 4)
    # the districts alone, and goes dark only when even that is over.
    learned = run_decide(store_of([honest(j) for j in range(30)])).learned
    assert learned is not None
    before = MemoryHost()
    calm = make_pass(before, alerts=feed(alerts=0), directory=world.directory(), config=CFG,
                     now=NOW - timedelta(minutes=30))  # fmt: skip
    calm.learned = learned
    assert cli.one_pass(calm) == 0

    def storm_pass(budget: int | None = None) -> tuple[int, MemoryHost]:
        host = MemoryHost()
        host.files.update(before.files)
        serve = CFG.serve.model_copy(update={"budget_raw_bytes": budget or 16_500_000})
        run = make_pass(host, directory=world.directory(), config=CFG.model_copy(
            update={"serve": serve}))  # fmt: skip
        run.learned = learned
        return cli.one_pass(run), host

    def days_of(data: bytes) -> tuple[list[Forecast], list[Forecast]]:
        made = PredictionsFile.from_json_bytes(data)
        districts = [d for e in made.districts for d in e.days if isinstance(d, Forecast)]
        return districts, [d for d in made.outlooks if isinstance(d, Forecast)]

    capsys.readouterr()
    found, host = storm_pass()
    assert found == 0
    whole = host.files[LATEST]
    districts, schools = days_of(whole)
    own = [d for d in districts if d.record is not None]
    assert own
    assert all(isinstance(d.why.base, AlertBase) and d.why.base.live for d in own)
    assert any(d.previous is not None for d in districts)
    assert any(d.previous is not None for d in schools)
    assert "warning" not in capsys.readouterr().err

    found, host = storm_pass(len(whole) - 1)
    assert found == 0
    bare = host.files[LATEST]
    assert chances(bare) == chances(whole)
    districts, schools = days_of(bare)
    assert all(d.record is None for d in districts + schools)
    assert any(d.previous is not None for d in schools)
    assert f"({len(whole):,} bytes raw); published it with no record days\n" in (
        capsys.readouterr().err
    )

    found, host = storm_pass(len(bare) - 1)
    assert found == 0
    mine = host.files[LATEST]
    assert chances(mine) == chances(whole)
    districts, schools = days_of(mine)
    assert all(d.record is None for d in districts + schools)
    assert any(d.previous is not None for d in districts)
    assert all(d.previous is None for d in schools)
    assert "published it with no record days or private schools' previous chances\n" in (
        capsys.readouterr().err
    )

    found, host = storm_pass(len(mine) - 1)
    assert found == 0
    least = host.files[LATEST]
    assert chances(least) == chances(whole)
    districts, schools = days_of(least)
    assert all(d.record is None and d.previous is None for d in districts + schools)
    assert "published it with no record days or previous chances\n" in capsys.readouterr().err

    # The districts alone, with their previous chances and no record days, are shorter than
    # the least file with private schools here: the pass publishes them rather than go dark.
    alone = PredictionsFile.from_json_bytes(whole)
    found, host = storm_pass(len(least) - 1)
    assert found == 0
    districts_only = PredictionsFile.from_json_bytes(host.files[LATEST])
    assert not districts_only.schools
    assert not districts_only.outlooks
    assert not districts_only.zones
    assert [e.days for e in districts_only.districts] == [
        tuple(d.model_copy(update={"record": None}) if isinstance(d, Forecast) else d
              for d in e.days) for e in alone.districts
    ]  # fmt: skip
    assert "published it with no private schools or record days\n" in capsys.readouterr().err

    found, host = storm_pass(len(host.files[LATEST]) - 1)
    assert found == cli.EXIT_DARK
    assert host.files == before.files
    assert "dark (size: " in capsys.readouterr().err


def counted_over_districts() -> ModelArtifact:
    """SYNTHETIC: the world's model with no private school's counts, so the private chain holds
    no situation and every private school is counted over the districts around it."""
    return world.model().model_copy(
        update={"private": world.private_models(with_counts=False), "private_labeled_days": 0}
    )


def test_a_private_outlook_table_too_long_steps_down_and_never_darkens(  # noqa: PLR0915 - each step
    capsys: Any, monkeypatch: Any
) -> None:
    # B1 (S7-2 round 4): once a learned file re-anchors a situation the private schools are
    # counted over the districts around them in, each school's nearby rates are its own, and
    # previous chances multiply the (chance, previous) pairs past the shared table. The pass
    # leaves out the private schools' previous chances, then publishes the districts alone;
    # it never darkens the districts, and the schema's index check is never what stops it.
    learned = run_decide(store_of([honest(j) for j in range(30)])).learned
    assert learned is not None
    anchored = build_model(world.directory(), counted_over_districts(), CFG,
                           lambda _lon, _lat: None, learned)  # fmt: skip
    assert anchored.private is not None
    assert not any(anchored.private.of_private)
    assert anchored.private.live[SNOW]
    before = MemoryHost()
    calm = make_pass(before, alerts=feed(alerts=0), directory=world.directory(), config=CFG,
                     now=NOW - timedelta(minutes=30))  # fmt: skip
    calm.learned, calm.model = learned, counted_over_districts
    assert cli.one_pass(calm) == 0
    # SYNTHETIC: the last file gave the second Kansas City school another chance today, so
    # it and its neighbor share today's outlook but not its previous chance.
    last = PredictionsFile.from_json_bytes(before.files[LATEST])
    shared = last.outlooks[last.schools[0].days[0]]
    assert isinstance(shared, Forecast)
    assert last.schools[1].days[0] == last.schools[0].days[0]
    other = shared.model_copy(update={
        "p_no_school": 0.05, "why": shared.why.model_copy(update={
            "base": shared.why.base.model_copy(update={"points": 5})})})  # fmt: skip
    schools = list(last.schools)
    schools[1] = schools[1].model_copy(update={"days": (len(last.outlooks), schools[1].days[1])})
    before.files[LATEST] = last.model_copy(
        update={"outlooks": (*last.outlooks, other), "schools": tuple(schools)}
    ).to_json_bytes()

    def storm_pass() -> tuple[int, bytes]:
        host = MemoryHost()
        host.files.update(before.files)
        run = make_pass(host, directory=world.directory(), config=CFG)
        run.learned, run.model = learned, counted_over_districts
        found = cli.one_pass(run)
        return found, host.files[LATEST]

    capsys.readouterr()
    found, whole = storm_pass()
    assert found == 0
    made = PredictionsFile.from_json_bytes(whole)
    live = [d for d in made.outlooks if isinstance(d, Forecast) and d.why.base.live]
    assert live
    assert all(getattr(d.why.base, "of", None) == "districts" for d in live)
    plain = {d.model_copy(update={"previous": None}) for d in made.outlooks}
    assert len(plain) < len(made.outlooks)
    assert "warning" not in capsys.readouterr().err

    monkeypatch.setattr(serve_module, "MAX_OUTLOOKS", len(plain))
    found, mine = storm_pass()
    assert found == 0
    assert chances(mine) == chances(whole)
    kept = PredictionsFile.from_json_bytes(mine)
    assert set(kept.outlooks) == plain
    assert any(isinstance(d, Forecast) and d.previous is not None
               for e in kept.districts for d in e.days)  # fmt: skip
    assert (
        f"the private schools name over {len(plain):,} distinct outlooks; published it with no "
        "record days or private schools' previous chances\n"
    ) in capsys.readouterr().err

    monkeypatch.setattr(serve_module, "MAX_OUTLOOKS", len(plain) - 1)
    found, alone = storm_pass()
    assert found == 0
    districts = PredictionsFile.from_json_bytes(alone)
    assert not districts.schools
    assert not districts.outlooks
    assert not districts.zones
    assert districts.districts == made.districts
    assert "; published it with no private schools\n" in capsys.readouterr().err


def test_a_pass_with_no_private_previous_chances_names_only_the_possible_outlooks() -> None:
    # B1 (S7-2 round 4): with no previous chance for private schools, every outlook a pass can
    # give them is one of serve.possible_outlooks (each school in every situation, scope and
    # said-open form), counted before any pass; the table holds that many, here with the
    # private schools counted over the districts around them under a learned anchor, and in
    # every situation for every school, the day after or not, said open or not, and mixed.
    # Also with the weather flag (addendum e, E2) differing between schools that share every
    # other part of a cell (r2 critic, S4): those are distinct outlooks, counted there too.
    learned = run_decide(store_of([honest(j) for j in range(30)])).learned
    assert learned is not None
    built = build_model(world.directory(), _with_advisory_days(counted_over_districts()), CFG,
                        lambda _lon, _lat: None, learned)  # fmt: skip
    assert built.private is not None
    assert SITUATION_KEYS[built.private.effective[ADVISORY]] == "advisory"
    assert built.private.whole[:, ADVISORY].all()
    mixed = built.private.whole.copy()
    mixed[::2] = ~mixed[::2]
    days = (date(2026, 1, 7), date(2026, 1, 8))
    sizes = []
    weathers: set[object] = set()
    for flags in (built.private.whole, mixed):
        model = replace(built, private=replace(built.private, whole=flags))
        private = model.private
        assert private is not None
        possible = serve_module.possible_outlooks(private, days)
        assert len(possible) <= MAX_OUTLOOKS
        sizes.append(len(possible))
        named = _named_outlooks(model, days)
        assert named <= possible
        assert any(isinstance(d, Forecast) and d.why.base.live for d in named)
        assert any(
            isinstance(d, Forecast) and d.why.reasons and d.why.reasons[0].kind == "said_open"
            for d in named
        )
        weathers |= {getattr(d.why.base, "weather", None) for d in named if isinstance(d, Forecast)}
    # The flag mixed: more distinct outlooks, at most twice as many, both kinds named.
    assert sizes[0] < sizes[1] <= 2 * sizes[0]
    assert {None, "advisory"} <= weathers


ADVISORY = SITUATION_KEYS.index("advisory")


def _with_advisory_days(model: ModelArtifact) -> ModelArtifact:
    """SYNTHETIC: ``model`` with 30 of 40 advisory days for every district it counts, so the
    advisory situation is modeled (not borrowed) and its bases name the weather."""
    districts = dict(model.districts)
    for leaid, entry in districts.items():
        if entry.y is None or entry.n is None or entry.nd is None:
            continue
        y, n, nd = list(entry.y), list(entry.n), list(entry.nd)
        y[ADVISORY], n[ADVISORY], nd[ADVISORY] = 30, 40, 10
        districts[leaid] = entry.model_copy(update={"y": tuple(y), "n": tuple(n), "nd": tuple(nd)})
    return model.model_copy(update={"districts": districts})


def _named_outlooks(model: ServeModel, days: tuple[date, date]) -> set[object]:
    """Every outlook passes with no private previous chance give the private schools of
    ``model``: in every situation for every school, the day after or not, said open or not,
    and mixed (SYNTHETIC classes)."""
    private = model.private
    assert private is not None
    now = datetime(2026, 1, 7, 2, tzinfo=UTC)
    every = frozenset(private.positions.tolist())
    classes = np.zeros((len(model.directory.district_ids), 2), dtype=np.int64)
    last: PredictionsFile | None = None
    rng = np.random.default_rng(7)
    forms = [
        (np.full((len(private), 2), int(w)), after, said)
        for w in WeatherClass
        for after in (False, True)
        for said in (False, True)
    ]
    forms += [(rng.integers(0, len(WeatherClass), size=(len(private), 2)), bool(after), False)
              for after in rng.integers(0, 2, size=8)]  # fmt: skip
    named: set[object] = set()
    for n, (weather, after, said) in enumerate(forms):
        found = made_file(
            model,
            classes,
            days,
            now + timedelta(minutes=n),
            closed_on=lambda _day: None,
            last=last,
            private_classes=weather.astype(np.int64),
            closed_schools=(lambda _day: every) if after else (lambda _day: None),
            said=SaidOpen(schools=dict.fromkeys(days, every)) if said else SaidOpen(),
            fit=serve_module.Fit.NO_PRIVATE_PREVIOUS,
        )
        named |= set(found.outlooks)
        last = found
    return named


def with_delays(j: int) -> dict[str, str]:
    """SYNTHETIC: each district closes on one storm day in five and delays on another."""
    return {
        d: "closed" if (j + i) % 5 == 0 else "delayed" if (j + i) % 5 == 1 else "open"
        for i, d in enumerate(world.DISTRICTS)
    }


def delays_read_open(j: int) -> dict[str, str]:
    """SYNTHETIC: a broken reader read every open district delayed."""
    return {d: "delayed" if did == "open" else did for d, did in honest(j).items()}


def test_a_re_anchored_delay_chance_counts_the_live_delays() -> None:
    # B1 (round 2): live days with delays re-anchor the delay chance to their level.
    decision = run_decide(store_of([with_delays(j) for j in range(30)]))
    assert decision.kind == "swap", decision.why
    assert decision.learned is not None
    refit, served = built(decision.learned), built(None)
    assert refit.q[:, SNOW].min() >= 0.1
    assert refit.q[:, SNOW].mean() > served.q[:, SNOW].mean()
    assert decision.learned.check["refit_delay_brier"] <= decision.learned.check[
        "served_delay_brier"]  # fmt: skip


def test_a_delay_misread_is_never_swapped_in() -> None:
    # B2, SYNTHETIC: open read as delayed on the fit days (the held-out days honest), or on
    # the held-out days only: the no-school chance is the same, the delay chance is not.
    for store in (
        store_of([delays_read_open(j) if 2 <= j < 24 else honest(j) for j in range(30)]),
        store_of([delays_read_open(j) if j >= 26 else honest(j) for j in range(30)]),
    ):
        decision = run_decide(store)
        assert decision.kind == "keep", decision.why
        assert decision.learned is None
        assert "delay Brier" in decision.why


def test_a_misread_stretch_is_never_swapped_in() -> None:
    # Twenty misread days among the fit days: the refit learns a level the newer days refute.
    fit_bad = store_of([MISREAD if 2 <= j < 22 else honest(j) for j in range(30)])
    decision = run_decide(fit_bad)
    assert decision.kind == "keep", decision.why
    assert decision.learned is None
    assert "the refit is worse" in decision.why
    # The newest days misread: they are only ever held out, and the honest refit is not
    # swapped in on them either.
    newest_bad = store_of([MISREAD if j >= 26 else honest(j) for j in range(30)])
    assert run_decide(newest_bad).kind == "keep"


def test_the_re_anchor_threshold() -> None:
    store = store_of([honest(j) for j in range(30)])
    rows = store.rows()
    through = sorted(set(rows["day"].to_list()))[25]
    fit = rows.filter(rows["day"] <= through).height
    at = CFG.model_copy(update={"learn": CFG.learn.model_copy(update={"anchor_min_days": fit})})
    over = CFG.model_copy(
        update={"learn": CFG.learn.model_copy(update={"anchor_min_days": fit + 1})}
    )
    made = datetime(2026, 1, 7, tzinfo=UTC)
    assert learned_from(rows, through, SHA, at, {}, made).anchored == ("snow_warning",)
    assert learned_from(rows, through, SHA, over, {}, made).anchored == ()
    # Below the shipped minimum (200 live storm district-days nationally) nothing changes and
    # every chance keeps the recorded days.
    decision = run_decide(store, config=world.CONFIG.model_copy(
        update={"learn": world.CONFIG.learn.model_copy(update={"holdout_min_storm_rows": 20})}
    ))  # fmt: skip
    assert decision.kind == "unchanged"
    assert decision.why == (
        f"nothing to learn yet: no storm situation has 200 live-read district-days through "
        f"{through} and 30 held out (the most: {fit} snow_warning); every chance keeps the "
        "recorded days; the model is unchanged"
    )
    assert world.CONFIG.learn.anchor_min_days == 200


def test_misread_clear_days_are_never_re_anchored_or_swapped_in() -> None:
    # B3, SYNTHETIC: honest storm days between clear days on which every district read closed.
    store = LearnStore.empty()
    for j, day in enumerate(weekdays(date(2025, 10, 6), 60)):
        key, outcomes = ("snow_warning", honest(j)) if j % 2 else ("none", MISREAD)
        labels: dict[str, dict[str, list[str]]] = {}
        for leaid, did in outcomes.items():
            labels.setdefault(key, {}).setdefault(did, []).append(leaid)
        store = store.with_day(day, labels, 0)
    decision = run_decide(store)
    assert decision.kind == "swap", decision.why
    assert decision.learned is not None
    assert decision.learned.anchored == ("snow_warning",)
    none = SITUATION_KEYS.index("none")
    assert np.array_equal(built(decision.learned).p[:, none], built(None).p[:, none])
    assert decision.learned.check["snow_warning_rows"] > 0


def test_a_situation_is_anchored_only_with_held_out_rows_to_check_it_on() -> None:
    rows = store_of([honest(j) for j in range(30)]).rows()
    through = sorted(set(rows["day"].to_list()))[25]
    made = datetime(2026, 1, 7, tzinfo=UTC)
    held = rows.filter(rows["day"] > through).height
    enough = CFG.model_copy(update={"learn": CFG.learn.model_copy(
        update={"holdout_min_situation_rows": held})})  # fmt: skip
    short = CFG.model_copy(update={"learn": CFG.learn.model_copy(
        update={"holdout_min_situation_rows": held + 1})})  # fmt: skip
    assert learned_from(rows, through, SHA, enough, {}, made).anchored == ("snow_warning",)
    assert learned_from(rows, through, SHA, short, {}, made).anchored == ()


def test_the_no_worse_guard_checks_every_re_anchored_situation() -> None:
    per = {"snow_warning": (50, 0.2, 0.1), "ice_warning": (50, 0.2, 0.1)}
    current = Score(100, 0.2, 0.1, 0.05, 1, per)
    keys = ("snow_warning", "ice_warning")
    assert no_worse(current, current, 0.01, keys) is None
    # Pooled better, one re-anchored situation worse: kept.
    mixed = Score(100, 0.15, 0.1, 0.05, 1,
                  {"snow_warning": (50, 0.1, 0.1), "ice_warning": (50, 0.21, 0.1)})  # fmt: skip
    assert "its ice_warning Brier 0.21000 is worse" in str(no_worse(mixed, current, 0.01, keys))
    # B2: its delay chance worse in one re-anchored situation: kept.
    delay = Score(100, 0.15, 0.1, 0.05, 1,
                  {"snow_warning": (50, 0.1, 0.1), "ice_warning": (50, 0.2, 0.11)})  # fmt: skip
    assert "its ice_warning delay Brier 0.11000 is worse" in str(
        no_worse(delay, current, 0.01, keys)
    )
    unseen = Score(100, 0.15, 0.1, 0.05, 1,
                   {"snow_warning": (50, 0.1, 0.1), "ice_warning": (0, 0.0, 0.0)})  # fmt: skip
    assert "no held-out district-day checks ice_warning" in str(
        no_worse(unseen, current, 0.01, keys)
    )
    # S3: a score that is not a number is worse, wherever it is.
    nan = float("nan")
    for broken in (
        Score(100, nan, 0.1, 0.05, 1, per),
        Score(100, 0.2, nan, 0.05, 1, per),
        Score(100, 0.2, 0.1, nan, 1, per),
        Score(100, 0.2, 0.1, 0.05, 1, {**per, "ice_warning": (50, nan, 0.1)}),
        Score(100, 0.2, 0.1, 0.05, 1, {**per, "snow_warning": (50, 0.2, nan)}),
    ):
        assert "is not a number" in str(no_worse(broken, current, 0.01, keys))


def test_held_out_reliability_bins_are_checked_at_held_out_sizes() -> None:
    # S1: twenty held-out storm rows of one district, all closed, against the archive's chance.
    rows = store_of([{"2900001": "closed"} for _ in range(20)]).rows()
    model = built(None)
    assert score(model, rows, CFG).out_of_bound == 1
    large = CFG.model_copy(update={"learn": CFG.learn.model_copy(
        update={"holdout_bin_min_rows": 21})})  # fmt: skip
    assert score(model, rows, large).out_of_bound == 0
    assert world.CONFIG.learn.holdout_bin_min_rows == 20
    assert world.CONFIG.learn.holdout_bin_min_rows < world.CONFIG.learn.holdout_min_storm_rows


def test_one_storm_or_one_state_held_out_decides_nothing() -> None:
    # S2: the newest days hold their storm rows on two days only, or in one state only.
    two_days = [honest(j) for j in range(30)]
    store = LearnStore.empty()
    for j, (day, by) in enumerate(zip(weekdays(date(2025, 10, 6), 30), two_days, strict=True)):
        key = "none" if j >= 26 and j not in (27, 29) else "snow_warning"
        labels: dict[str, dict[str, list[str]]] = {}
        for leaid, did in by.items():
            labels.setdefault(key, {}).setdefault(did, []).append(leaid)
        store = store.with_day(day, labels, 0)
    few = CFG.model_copy(update={"learn": CFG.learn.model_copy(update={"holdout_max_share": 0.1})})
    decision = run_decide(store, config=few)
    assert decision.kind == "unchanged"
    assert "over 3 storm days and 2 states" in decision.why
    missouri = store_of([{d: honest(j)[d] for d in MO} for j in range(30)])
    assert run_decide(missouri).kind == "unchanged"


def test_an_excluded_day_is_never_learned_and_a_file_that_counted_it_is_replaced() -> None:
    store = store_of([honest(j) for j in range(30)])
    first = run_decide(store)
    assert first.learned is not None
    bad = sorted(store.labeled())[3]
    excluded = CFG.model_copy(update={"learn": CFG.learn.model_copy(
        update={"excluded_days": (bad,)})})  # fmt: skip
    # The refit without it passes the check against the committed model: it is swapped in.
    again = run_decide(store, first.learned, excluded)
    assert again.kind == "swap", again.why
    assert again.learned is not None
    assert again.learned.labeled_days == first.learned.labeled_days - len(world.DISTRICTS)
    assert f"it replaces a file that counted {bad}" in again.why
    # With nothing left to anchor, a file that re-anchors nothing replaces it.
    strict = excluded.model_copy(update={"learn": excluded.learn.model_copy(
        update={"anchor_min_days": 10_000})})  # fmt: skip
    reset = run_decide(store, first.learned, strict)
    assert reset.kind == "reset"
    assert reset.learned is not None
    assert reset.learned.anchored == ()
    assert not any(built(reset.learned).anchored)
    # S5: the store of labels lost or reset, the served file's own days still name the day.
    assert first.learned.days[3] == bad
    lost = decide(LearnStore.empty(), first.learned, built, SHA, strict,
                  world.utc("2026-01-07T09:00:00"))  # fmt: skip
    assert lost.kind == "reset"
    assert lost.learned is not None
    assert lost.learned.days == ()
    # The day is never labeled.
    source = Source({bad: world.timeline().model_copy(update={"day": bad})})
    done = learn.label_new_days(
        LearnStore.empty(), source, learn.directory_of(built()), {}, excluded,
        datetime.combine(bad + timedelta(days=2), datetime.min.time(), tzinfo=UTC),
    )  # fmt: skip
    assert done.added == []
    assert done.skipped["excluded from learning (learn.excluded_days)"] == 1


def test_the_no_worse_guard() -> None:
    current = Score(rows=100, brier=0.2, delay_brier=0.1, ece=0.05, out_of_bound=1)
    assert no_worse(current, current, 0.01) is None
    better = Score(rows=100, brier=0.19, delay_brier=0.1, ece=0.055, out_of_bound=1)
    assert no_worse(better, current, 0.01) is None
    assert "storm Brier" in str(no_worse(Score(100, 0.2001, 0.1, 0.05, 1), current, 0.01))
    assert "storm delay Brier" in str(no_worse(Score(100, 0.1, 0.1001, 0.05, 1), current, 0.01))
    assert "reliability bins" in str(no_worse(Score(100, 0.1, 0.1, 0.05, 2), current, 0.01))
    assert "ECE" in str(no_worse(Score(100, 0.1, 0.1, 0.0601, 1), current, 0.01))
    assert "no held-out" in str(no_worse(Score(0, 0.0, 0.0, 0.0, 0), current, 0.01))


def test_too_few_held_out_storm_days_decide_nothing() -> None:
    decision = run_decide(store_of([honest(j) for j in range(6)]))
    assert decision.kind == "unchanged"
    assert "too few to hold out 20" in decision.why
    assert run_decide(LearnStore.empty()).why == (
        "nothing to learn: no live-read district-days labeled yet; the model is unchanged"
    )


# --- one run --------------------------------------------------------------------------------------


class Host:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.writes = 0

    def read(self, key: str) -> bytes | None:
        return self.files.get(key)

    def write(self, files: Mapping[str, bytes]) -> None:
        self.writes += 1
        self.files.update(files)


def learn_run(host: Host, source: Any, now: datetime, config: PredictConfig = CFG) -> cli.LearnRun:
    return cli.LearnRun(
        config=config,
        host=host,
        prefix="v1",
        source=source,
        model=built(None, config),
        archive_sha256=SHA,
        snapshots={},
        build=lambda learned: built(learned, config),
        now=now,
    )


def test_with_no_live_day_read_yet_the_run_leaves_the_model_unchanged(capsys: Any) -> None:
    host = Host()
    now = world.utc("2026-10-20T15:00:00")
    assert cli.learn_once(learn_run(host, NoLiveSource(), now, world.CONFIG)) == 0
    assert host.writes == 0
    assert host.files == {}
    out = capsys.readouterr().out
    # S4: the log says what is true here: no live state reached the run (not that no live
    # day was read anywhere).
    assert out.startswith("predict learn: 6 school days not labeled: no live ingest state "
                          "reached this run\n")  # fmt: skip
    assert out.endswith(
        "predict learn: nothing to learn: no live-read district-days labeled yet; the model is "
        "unchanged\n"
    )


def test_a_rerun_writes_nothing_and_a_kept_refit_exits_four(capsys: Any) -> None:
    host = Host()
    host.files["v1/predictions/learn.json"] = store_of([honest(j) for j in range(30)]).to_bytes()
    now = world.utc("2026-01-07T09:00:00")
    assert cli.learn_once(learn_run(host, NoLiveSource(), now)) == 0
    assert host.writes == 1
    learned = Learned.from_bytes(host.files["v1/predictions/learned.json"])
    assert learned.anchored == ("snow_warning",)
    assert "swapped in the refit" in capsys.readouterr().out
    assert cli.learn_once(learn_run(host, NoLiveSource(), now)) == 0
    assert host.writes == 1
    assert "nothing newer to check yet" in capsys.readouterr().out
    bad = Host()
    bad.files["v1/predictions/learn.json"] = store_of(
        [MISREAD if 2 <= j < 22 else honest(j) for j in range(30)]
    ).to_bytes()
    assert cli.learn_once(learn_run(bad, NoLiveSource(), now)) == learn.EXIT_KEPT
    assert "v1/predictions/learned.json" not in bad.files
    assert "kept the model served" in capsys.readouterr().out
    broken = Host()
    broken.files["v1/predictions/learn.json"] = b"{"
    assert cli.learn_once(learn_run(broken, NoLiveSource(), now)) == 1
    assert broken.writes == 0


def test_a_learned_file_never_darkens_serving(monkeypatch: Any) -> None:
    learned = run_decide(store_of([honest(j) for j in range(30)])).learned
    assert learned is not None
    data = learned.to_bytes()
    assert learn.read_learned(data, SHA) == (learned, None)
    assert learn.read_learned(data, "d" * 64)[0] is None
    assert (
        learn.read_learned(b"{}", SHA)[1] == "the learned file does not validate (ValidationError)"
    )
    assert learn.read_learned(None, SHA) == (None, None)
    real = build_model

    def refuse(*args: Any, **kwargs: Any) -> ServeModel:
        if len(args) > 4 or kwargs:
            raise ServeError("a sentence would be false")
        return real(*args)

    monkeypatch.setattr("snowlight.predict.learn.build_model", refuse)
    model, why = learn.serving_model(
        world.directory(), world.model(), learned, CFG, lambda _lon, _lat: None
    )
    assert why is not None
    assert "serving the committed model" in why
    assert not any(model.anchored)


def write_ledger(path: Path, reads: Sequence[tuple[str, str]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE good_reads (source_id TEXT NOT NULL, at TEXT NOT NULL)")
    connection.executemany("INSERT INTO good_reads VALUES (?, ?)", reads)
    connection.commit()
    connection.close()


def test_the_learning_step_reads_the_packed_state_of_the_cache_store(tmp_path: Path) -> None:
    state, store, scratch = tmp_path / "state", tmp_path / "store", tmp_path / "scratch"
    assert cli.live_state_folder(state, store, scratch) is None
    packed = tmp_path / "packed"
    packed.mkdir()
    write_ledger(packed / "ledger.sqlite", [])
    store.mkdir()
    (store / "live-state.tar.gz").write_bytes(pack(packed))
    assert cli.live_state_folder(state, store, scratch) == scratch
    assert (scratch / "ledger.sqlite").is_file()
    state.mkdir()
    write_ledger(state / "ledger.sqlite", [])
    assert cli.live_state_folder(state, store, tmp_path / "other") == state

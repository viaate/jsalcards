"""``snowlight predict read-labels`` and ``snowlight predict read-sources`` (advisory-sane L1).

``read-labels`` runs in the predict workflow right after ``predict learn``, as its own step
(it never changes what ``learn`` does or writes): it labels the new live school mornings by
the outcome-blind read rule (:mod:`snowlight.predict.live_read`) into the private record
(``out/internal/predict/reads``, kept in the workflow's own Actions cache and, by
``predict evidence``, for good in the evidence databases), and publishes the public audit,
``predictions/read-audit.json`` on the live host, whenever a day is added. It labels nothing
(and freezes nothing) while either coverage file is absent: a day labeled without them
would be frozen with every district ``not_covered``. A day the published audit holds is
never labeled again, and the audit never drops or rewrites one, even when the Actions cache
lost the record (the evidence store keeps it). Each run rewrites the private report,
``reads/summary.json`` (:class:`snowlight.predict.live_read.ReadReport`: the list
sensitivities with their 90% intervals, dates and lists, G1's tier B check, rows by region,
and G1's hand audit), and logs its counts. A run labels at most
:data:`~snowlight.predict.live_read.DAYS_PER_RUN` days and sets ``added`` as each is
written, so a run cut off by the step's time limit still saves what it wrote.

``read-sources`` builds the rule's coverage files (codes and counts only) from the
stations' area coverage (``coverage.json``, ``proven.counties``), a match of the whole
archive and the archive's weather classes (``weather.parquet``): each source's populated
archive captures, the rows of its closing-size captures
(:func:`snowlight.predict.live_read.closing_captures`), and the archive audiences (each
source's districts, no dates).
"""

import argparse
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from snowlight.live.publishers import PublishError
from snowlight.output import write_bytes_atomic
from snowlight.predict import live_read
from snowlight.predict.config import PIPELINE_ROOT, PredictConfig
from snowlight.predict.live_labels import Directory
from snowlight.predict.publish import Host
from snowlight.schemas.base import check_published_bytes
from snowlight.schemas.stats import ReadAudit

STARTED: Final = time.monotonic()
"""When this module was first imported: the CLI imports it to register its commands, so this
is about the start of the step's process (the call time counts line's limit counts from it)."""
INTERNAL: Final = PIPELINE_ROOT / "out" / "internal"
COVERAGE: Final = INTERNAL / "stations" / "coverage.json"


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def _err(line: str) -> None:
    sys.stderr.write(line + "\n")


def register(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register ``read-labels`` and ``read-sources``."""
    from snowlight.predict import train  # noqa: PLC0415
    from snowlight.predict.cli import LIVE_INTERNAL, _serve_inputs  # noqa: PLC0415

    labels = actions.add_parser(
        "read-labels", help="the outcome-blind live labels and their public audit (nightly)"
    )
    _serve_inputs(labels)
    labels.add_argument("--live-state", type=Path, default=LIVE_INTERNAL / "state")
    labels.add_argument("--live-store", type=Path, default=LIVE_INTERNAL / "store")
    labels.add_argument("--registry", type=Path, default=train.TrainPaths().registry)
    labels.add_argument("--reads", type=Path, default=live_read.READS_DIR)
    labels.add_argument("--read-sources", type=Path, default=live_read.READ_SOURCES_PATH)
    labels.add_argument("--audiences", type=Path, default=live_read.AUDIENCES_PATH)
    labels.set_defaults(handler=run_read_labels)

    build = actions.add_parser(
        "read-sources", help="the read rule's coverage files (codes only) from the archive"
    )
    build.add_argument("--coverage", type=Path, default=COVERAGE, help="coverage.json")
    build.add_argument("--archive", type=Path, default=train.TrainPaths().archive)
    build.add_argument("--out", type=Path, default=live_read.READ_SOURCES_PATH.parent)
    build.add_argument(
        "--weather",
        type=Path,
        default=train.DEFAULT_OUT / "weather.parquet",
        help="the archive's weather classes predict labels wrote (closing-size captures)",
    )
    build.add_argument("--registry", type=Path, default=train.TrainPaths().registry)
    build.add_argument("--directory", type=Path, default=train.TrainPaths().directory)
    build.add_argument("--aliases", type=Path, default=train.TrainPaths().aliases)
    build.add_argument("--weather-cache", type=Path, default=train.TrainPaths().weather_cache)
    build.add_argument(
        "--districts",
        type=Path,
        default=train.DEFAULT_OUT / "districts.parquet",
        help="the district table predict labels wrote (each district's zone)",
    )
    build.add_argument("--workers", type=int, default=4)
    build.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=datetime.now(UTC).date(),
        help="the build's day: audiences keep pairs listed from the previous season's Aug 1",
    )
    build.set_defaults(handler=run_read_sources)


# --- read-labels --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReadLabelsRun:
    """Everything one ``read-labels`` run needs, as values (tests replace them)."""

    config: PredictConfig
    host: Host
    prefix: str
    source: Any
    """The live days (:class:`snowlight.predict.live_read.ReadSource`)."""
    directory: Directory
    coverage: live_read.Coverage
    snapshots: Mapping[str, object]
    folder: Path
    now: datetime
    missing: tuple[str, ...] = ()
    """The coverage files absent: nothing is labeled while any is."""
    outputs: Path | None = None
    """The step's ``GITHUB_OUTPUT``: ``added=true`` when a day was added (the cache is saved
    only then)."""
    frozen: Path | None = None
    """The frozen record's folder (:data:`snowlight.predict.frozen.FOLDER`), for the call time
    counts line's served rows; ``None``: not read (none counted served)."""
    started: float | None = None
    """When the step's process began (``time.monotonic``; the CLI's :data:`STARTED`), which the
    call time counts line's limit counts from; ``None``: when :func:`read_once` began."""
    model_sha256: str | None = None
    """The committed model artifact's sha256, half of each live switch term's key
    (:mod:`snowlight.predict.live_switch`); ``None``: the switch writes nothing."""
    switch: bool = True
    """Whether the live switch runs at the end of the step (predict-next TIMING-AUTO)."""
    clock: Callable[[], float] | None = None
    """The step's clock for the live switch's limits (``time.monotonic`` when ``None``)."""


COVERAGE_ABSENT: Final = "the coverage files are absent ({}): nothing is labeled or frozen"
PUBLISHED_MARK: Final = "published.json"
"""Kept in the record once the audit is published: a host that then answers with no audit
(a wrong prefix, a listing glitch) is an error, never a first run, so the days it published
are never labeled again nor dropped from a rewritten audit."""


def read_once(run: ReadLabelsRun) -> int:
    """One run: label the new days, then publish the audit when a day was added (or the host
    holds none). 0 done, 1 an error (the record and the host as they were; days already
    written stay, frozen). A host audit that does not read is an error: nothing is labeled
    until it is mended, since the days it published could not be told apart. So is a host
    with no audit once this record has published one (:data:`PUBLISHED_MARK`)."""
    began = time.monotonic()
    if run.missing:
        _out("predict read-labels: " + COVERAGE_ABSENT.format(", ".join(run.missing)))
        return 0
    key = f"{run.prefix}/{live_read.AUDIT_PATH}"
    marked: list[bool] = []
    coverage = run.coverage
    season = coverage.audience_season
    if season is not None and not live_read.audiences_current(
        season, run.now.astimezone(UTC).date()
    ):
        _out(
            f"::warning::predict read-labels: {live_read.AUDIENCES_PATH.name} was built in the "
            f"{season} season and holds pairs of that season and the one before: none is read "
            "as tier A until it is rebuilt (predict read-sources --as-of, each Aug 1)"
        )
        coverage = replace(coverage, archive={})

    def added(_day: date) -> None:
        # As each day is written: a step cut off by its time limit still saves what it wrote.
        if run.outputs is not None and not marked:
            with run.outputs.open("a", encoding="utf-8") as handle:
                handle.write("added=true\n")
            marked.append(True)

    mark = run.folder / PUBLISHED_MARK
    try:
        held = _held(run.host.read(key), mark)
    except _RefusedError as error:
        _err(f"predict read-labels: error: {error}")
        return 1
    except PublishError as error:
        _err(f"predict read-labels: error: {type(error).__name__}: nothing is labeled")
        return 1
    try:
        done = live_read.read_new_days(
            run.folder,
            run.source,
            directory=run.directory,
            coverage=coverage,
            snapshots=run.snapshots,
            config=run.config,
            now=run.now,
            published=[item.day for item in held.days] if held is not None else (),
            on_added=added,
        )
        audit = live_read.audit_of(run.folder, run.now, held)
    except (PublishError, sqlite3.Error, ValueError, OSError) as error:
        _err(f"predict read-labels: error: {type(error).__name__}: nothing more is labeled")
        return 1
    for reason, count in sorted(done.skipped.items()):
        _out(f"predict read-labels: {count} school days not labeled: {reason}")
    lost = sorted({item.day for item in audit.days} - set(live_read.labeled_days(run.folder)))
    if lost:
        _out(
            f"::warning::predict read-labels: the record lacks {len(lost)} days the public "
            f"audit holds ({lost[0].isoformat()} to {lost[-1].isoformat()}): the Actions cache "
            "lost them; the evidence store keeps them, and they are never labeled again"
        )
    if done.added:
        _out("predict read-labels: labeled " + ", ".join(d.isoformat() for d in done.added))
    lists_now: int | None = None
    if done.counted is not None:
        least = run.config.labels.station_min_captures
        lists_now = live_read.tier_b_lists(coverage, done.closing)
        recent = done.recent.days if done.recent is not None else {}
        _out(
            f"predict read-labels: counted live days through {done.added[-1].isoformat()}: "
            f"{sum(done.counted.days.values())} days of {len(done.counted.days)} lists; "
            f"{sum(n >= least for n in done.closing.values())} lists with {least} closing-size "
            f"values, archive and live (lead ruling C2), {lists_now} of them tier B; "
            f"{len(recent)} lists with a counted day in the "
            f"{live_read.ReadRule.of(run.config).recent_days} days before (they read with no "
            "second list: condition 4)"
        )
    # The private report comes after the public audit, so a run the step's time limit cuts
    # off in the report has still published the days it labeled.
    if not _publish(run, key, held, audit) or (report := _report(run, audit, lists_now)) is None:
        return 1
    for line in summary(audit, run.folder, report):
        _out(f"predict read-labels: {line}")
    step = began if run.started is None else min(run.started, began)
    # The live switch decides what this run's passes serve, so it runs before the call time
    # counts lines (its own limits: it starts before 45 s, starts no date past 55 s and writes
    # before 65 s unless a date it counted ran late).
    if run.switch:
        switch_lines(run, step)
    call_time_lines(run, done, step, coverage)
    _out(f"predict read-labels: {time.monotonic() - began:.1f} s")
    return 0


CALL_TIME_SECONDS: Final = 90.0
"""The call time counts lines stop once the step has run this long (its limit is 2 minutes):
the clock is checked before each day, before each timeline read, before the morning record is
parsed and between districts, so at most one host read (20 s a phase) runs past it."""
SKIPPED: Final = "call time (off): skipped past {:.0f} s of the step"
GAP_MINUTES: Final = 60
"""A morning call is lit after a reader gap when the list that lit it had no whole read in the
record in this many minutes before the lighting pass's slot."""


def call_time_lines(
    run: ReadLabelsRun,
    done: live_read.ReadRun,
    began: float,
    coverage: live_read.Coverage | None = None,
    *,
    clock: Callable[[], float] | None = None,
) -> None:
    """One counts-only line per day added (predict-next CALL-TIME, the term off:
    :func:`snowlight.predict.call_time.day_counts`), on ``coverage``, the one L1 read the day
    with (``None``: the run's). Past :data:`CALL_TIME_SECONDS` from ``began`` (on ``clock``,
    ``time.monotonic`` when ``None``) the day's work stops wherever it is and one skip line
    is printed instead; any error is one warning: it never changes a label, the audit,
    ``added`` or the exit."""
    now = clock or time.monotonic

    def late() -> bool:
        return now() - began > CALL_TIME_SECONDS

    try:
        calls: dict[date, list[Any]] = {}
        for day in done.added:
            if late():
                raise TimeoutError
            line = _call_time_line(
                run, done, day, calls, coverage=coverage or run.coverage, late=late
            )
            if line is not None:
                _out(f"predict read-labels: {line}")
    except TimeoutError:
        _out("predict read-labels: " + SKIPPED.format(CALL_TIME_SECONDS))
    except Exception as error:  # a counts line never changes what the step did
        _out(f"::warning::predict read-labels: call time counts: {type(error).__name__}")


def switch_lines(run: ReadLabelsRun, began: float) -> None:
    """The live switch's step (:func:`snowlight.predict.live_switch.run`): its counts,
    evaluation and switch lines; any failure is one warning and writes nothing, and it never
    changes a label, the audit, ``added`` or the exit."""
    from snowlight.predict import live_switch  # noqa: PLC0415

    try:
        live_switch.run(
            live_switch.StepInputs(
                config=run.config,
                host=run.host,
                prefix=run.prefix,
                reads=run.folder,
                frozen=run.frozen,
                model_sha256=run.model_sha256,
                now=run.now,
                started=began,
                clock=run.clock or time.monotonic,
            ),
            _out,
        )
    except Exception as error:  # the switch never changes what the step did
        _out(f"::warning::predict read-labels: switch: {type(error).__name__}: nothing written")


def _outcomes(source: Any) -> Mapping[str, str] | None:
    """Each source's last outcome in the live state's ledger, or ``None`` when the host holds
    none: no ledger, or the state export's schema-only one (what the predict job reads), so a
    dark list's cause is never guessed."""
    from snowlight.live.ledger import last_outcomes  # noqa: PLC0415

    folder = getattr(getattr(source, "state", None), "folder", None)
    if not isinstance(folder, Path) or not (folder / "ledger.sqlite").is_file():
        return None
    return last_outcomes(folder / "ledger.sqlite") or None


def _call_time_line(  # noqa: PLR0913 - the run, its day, the calls read and the limit
    run: ReadLabelsRun,
    done: live_read.ReadRun,
    day: date,
    known: dict[date, list[Any]],
    *,
    coverage: live_read.Coverage,
    late: Callable[[], bool],
) -> str | None:
    """One day's counts line; ``known``: each final timeline's calls, read once a run. Only
    a final day whose class snapshot the predict state still holds with a district of a
    term's class is read from the host (any other day gives no call), and ``late()`` is
    asked before each read.

    Raises:
        TimeoutError: ``late()`` turned true.
    """
    from snowlight.live.morning import EVERY_DAY  # noqa: PLC0415
    from snowlight.predict import call_time  # noqa: PLC0415
    from snowlight.predict.live_labels import Morning, snapshot_classes  # noqa: PLC0415
    from snowlight.predict.situations import Window  # noqa: PLC0415

    config = run.config
    settings = call_time.CallSettings.of(config)
    rule = live_read.ReadRule.of(config)
    source = run.source
    morning = source.morning(day)
    found = live_read.read_day(run.folder, day)
    if not isinstance(morning, Morning) or found is None:
        return f"call time (off) {day.isoformat()}: no record"
    weather = config.weather
    window = Window(weather.window_from, weather.window_until, weather.snapshot_hour)
    slack = timedelta(minutes=config.learn.snapshot_slack_minutes)
    directory = run.directory

    def classes_of(when: date) -> list[Any]:
        return snapshot_classes(
            run.snapshots, when, content=directory.content, zones=directory.zones,
            window=window, slack=slack,
        )  # fmt: skip

    classes = classes_of(day)
    closing = done.closing_rule
    least = config.labels.station_min_captures
    live = source.captures(day, live_read.CAPTURE_DAYS, closing)
    stats = live_read.ListStats.of(coverage, live, least)
    recent = source.captures(day, rule.recent_days, closing).days
    index = source.index()
    calls: list[call_time.Call] = []
    for entry in index.days if index is not None else ():
        if entry.day > day or not entry.final:
            continue
        if entry.day not in known:
            # u reaches back only as far as the class snapshots kept (about 45 days): a day
            # with no district of a term's class gives no call, so its timeline is not read
            them = classes_of(entry.day)
            if not any(call_time.serves(k, settings) for k in them):
                known[entry.day] = []
            else:
                if late():
                    raise TimeoutError
                known[entry.day] = list(
                    call_time.called_minutes(
                        source.timeline(entry.day), directory, them, settings, rule
                    ).values()
                )
        calls.extend(known[entry.day])
    if late():
        raise TimeoutError
    days = _record_days(source, morning, day - timedelta(days=settings.required_days))
    record = call_time.whole_reads(days, morning.prefix)
    every_before = frozenset(
        leaid
        for slot in days.get(day - timedelta(days=1), {}).values()
        for leaid, named in slot.named.items()
        if EVERY_DAY in named
    )
    read = {r.district for r in found.rows if r.label is not live_read.Label.NOT_READ}
    unknown = {r.district for r in found.rows if r.label is live_read.Label.UNKNOWN}
    outcomes = _outcomes(source)
    calls_today = [c for c in calls if c.day == day]
    lit_by = source.lit_by(day) or {}
    gapped = {
        c.leaid
        for c in calls_today
        if c.kind is call_time.CallKind.MORNING
        and _after_gap(lit_by.get(c.leaid, {}), days.get(day, {}))
    }
    counts = call_time.day_counts(
        call_time.DayInputs(
            day=day, morning=morning, directory=directory, coverage=coverage, stats=stats,
            classes=classes, read=read, unknown=unknown, calls=calls, record=record,
            recent=recent, every_before=every_before, served=_served(run.frozen, day),
            outcomes=outcomes, gapped=gapped,
        ),
        settings,
        rule,
        late=late,
    )  # fmt: skip
    if run.frozen is None:
        counts["no frozen record read"] = 1
    return call_time.counts_line(day, counts)


def _record_days(source: Any, morning: Any, first: date) -> dict[date, Mapping[datetime, Any]]:
    """The morning record's slots of each UTC day from ``first`` to the morning's: from the live
    state's folder when the source reads one (each day parsed once), else from the source."""
    from snowlight.live.morning import MorningLog, slot_start  # noqa: PLC0415
    from snowlight.predict.live_labels import Morning  # noqa: PLC0415

    day = morning.day
    days: dict[date, Mapping[datetime, Any]] = {}
    folder = getattr(getattr(source, "state", None), "folder", None)
    if isinstance(folder, Path):
        log = MorningLog(folder / "morning")
        for when in log.days():
            if first <= when <= day and (kept := log.day(when)) is not None:
                days[when] = {slot_start(when, k): v for k, v in kept.slots.items()}
        return days
    when = first
    while when <= day:
        other = morning if when == day else source.morning(when)
        if isinstance(other, Morning):
            days[when] = other.slots
        when += timedelta(days=1)
    return days


def _after_gap(lit: Mapping[str, datetime], slots: Mapping[datetime, Any]) -> bool:
    """Whether the list that first lit a district lit it after a reader gap: no whole read of
    it in the record in :data:`GAP_MINUTES` before the lighting pass's slot."""
    if not lit:
        return False
    source, at = min(lit.items(), key=lambda item: (item[1], item[0]))
    moment = at.astimezone(UTC)
    start = moment.replace(minute=moment.minute // 30 * 30, second=0, microsecond=0)
    begin = start - timedelta(minutes=GAP_MINUTES)
    return not any(begin <= when < start and source in slot.reads for when, slot in slots.items())


def _served(folder: Path | None, day: date) -> frozenset[str]:
    """The districts with a served ``d0_0630`` frozen row the decline applies to (``s`` 1,
    ``pr`` known, no ``sa``), from the frozen record's folder."""
    if folder is None:
        return frozenset()
    from snowlight.predict import frozen  # noqa: PLC0415

    found = frozen.rows(day, day, folder).get(day)
    if found is None:
        return frozenset()
    return frozenset(
        row.leaid
        for row in found.rows
        if row.freeze == "d0_0630" and row.served and row.p_raw is not None and not row.said_open
    )


def _publish(run: ReadLabelsRun, key: str, held: ReadAudit | None, audit: ReadAudit) -> bool:
    """Publish the audit when it differs from the host's, and mark the record once it has
    published one (``False``: an error, logged)."""
    mark = run.folder / PUBLISHED_MARK
    try:
        if held is None or held.days != audit.days:
            data = audit.to_json_bytes()
            check_published_bytes(data)
            run.host.write({key: data})
            if run.host.read(key) != data:
                raise PublishError("the audit read back is not the one written")
            _out(f"predict read-labels: published {live_read.AUDIT_PATH} ({len(audit.days)} days)")
        if audit.days and not mark.is_file():
            write_bytes_atomic(mark, f'{{"days": {len(audit.days)}}}\n'.encode())
    except (PublishError, ValueError, OSError) as error:
        _err(f"predict read-labels: error: the audit: {type(error).__name__}")
        return False
    return True


def _report(
    run: ReadLabelsRun, audit: ReadAudit, lists_now: int | None = None
) -> live_read.ReadReport | None:
    """The private report of the season, written to ``reads/summary.json`` (``None``: it
    could not be made, logged). ``lists_now``: the lists tier B as of a run that labeled a
    day; a run that labeled none keeps the last report's count (0 before the first)."""
    try:
        report = live_read.report_of(
            run.folder,
            audit,
            live_read.ReadRule.of(run.config),
            live_read.season_of(run.now.astimezone(UTC).date()),
            lists_now if lists_now is not None else _lists_before(run.folder),
        )
        write_bytes_atomic(
            run.folder / live_read.SUMMARY, report.model_dump_json(indent=1).encode()
        )
    except (ValueError, OSError) as error:
        _err(f"predict read-labels: error: the private report: {type(error).__name__}")
        return None
    return report


def _lists_before(folder: Path) -> int:
    """The last report's tier B lists as of its run (0 when there is none, or it does not
    read as this schema)."""
    path = folder / live_read.SUMMARY
    try:
        return live_read.ReadReport.model_validate_json(path.read_bytes()).tier_b_lists_now
    except (OSError, ValueError):
        return 0


class _RefusedError(Exception):
    """The host's audit cannot be trusted: nothing is labeled."""


def _held(held: bytes | None, mark: Path) -> ReadAudit | None:
    """The host's audit (:func:`_held_audit`), ``None`` on the first run only.

    Raises:
        _RefusedError: it does not read, or the host holds none though this record published one
            (``mark``): the days it published could not be told and would be labeled again,
            or dropped from a rewritten audit.
    """
    try:
        found = _held_audit(held)
    except ValueError as error:
        raise _RefusedError(
            f"the published {live_read.AUDIT_PATH} does not read ({type(error).__name__}): "
            "nothing is labeled, so no day it published is labeled again"
        ) from error
    if found is None and mark.is_file():
        raise _RefusedError(
            f"the host holds no {live_read.AUDIT_PATH}, though this record published one: "
            "nothing is labeled, so no day it published is labeled again or dropped"
        )
    return found


def _held_audit(held: bytes | None) -> ReadAudit | None:
    """The host's audit, ``None`` when it holds none (the first run).

    Raises:
        ValueError: it holds one that does not read (after a schema change or a broken
            write): nothing is labeled then, since the days it published could not be told
            and would be labeled again.
    """
    if held is None:
        return None
    return ReadAudit.from_json_bytes(held)


def _g1_status(report: live_read.ReadReport) -> str:
    """G1 tier B's word (lead ruling C5: the by-date mean flags a check met by trials only,
    and gates it once the trials come from :data:`~snowlight.predict.live_read.BY_DATE_LISTS`
    lists)."""
    if report.tier_b_g1:
        return "met by trials, not by date" if report.tier_b_not_by_date else "met"
    return "not met: by date" if report.tier_b_not_by_date else "not met"


def summary(
    audit: ReadAudit, folder: Path, report: live_read.ReadReport | None = None
) -> list[str]:
    """Counts for the log (no chance, no level, no district): rows per class and label over
    the record, the co-listing trials per tier with the list sensitivities and G1's tier B
    check, read rows per region, and the record's size."""
    labels: Counter[str] = Counter()
    for item in audit.days:
        for counts in item.classes:
            if counts.weather in ("none", "unclassed"):
                continue
            labels[f"{counts.weather} read"] += counts.read_a + counts.read_b
            labels[f"{counts.weather} unnamed"] += counts.unnamed
            labels[f"{counts.weather} closed"] += counts.lit_no_school
            labels[f"{counts.weather} unnamed with unplaced rows"] += counts.unnamed_unplaced
            labels[f"{counts.weather} not read, state withheld"] += counts.withheld_state
    found = ", ".join(f"{key} {value}" for key, value in sorted(labels.items()))
    lines = [
        f"{len(audit.days)} days labeled, all seasons; " + (found or "no alerted district read yet")
    ]
    totals = live_read.trial_totals(audit)
    lines.append(
        "co-listing trials, all seasons: "
        + ", ".join(f"tier {t.value} {n} ({h} named)" for t, (n, h) in sorted(totals.items()))
    )
    if report is not None:
        tier_b = report.sensitivity[1]
        lines.append(
            "list sensitivity, this season: "
            + "; ".join(
                f"s_{item.tier.value} {item.mean:.3f} (90% {item.low:.3f} to {item.high:.3f};"
                f" by date {item.day_low:.3f} to {item.day_high:.3f}; {item.trials} trials"
                f" from {item.dates} dates and {item.lists} lists)"
                for item in report.sensitivity
            )
            + f"; G1 tier B (s_B at least {report.tier_b_min} over at least "
            + f"{report.tier_b_min_trials} closed trials from at least "
            + f"{report.tier_b_min_dates} dates): "
            + _g1_status(report)
            + f" ({tier_b.dates} dates, {tier_b.lists} lists); by-date mean "
            + f"{tier_b.day_mean:.3f} (90% {tier_b.day_low:.3f} to {tier_b.day_high:.3f}): "
            + ("at least " if tier_b.day_mean >= report.tier_b_min else "under ")
            + f"{report.tier_b_min} ("
            + ("part of G1" if report.tier_b_by_date_gates else "diagnostic")
            + f", tier B trials from {report.tier_b_lists} lists, {report.tier_b_lists_now} "
            + f"lists tier B now, of {live_read.BY_DATE_LISTS})"
            + (
                f"; record incomplete: {report.incomplete} days of the season the audit holds "
                "and the record lost (their dates, lists and hand-audit rows are not counted)"
                if report.incomplete
                else ""
            )
        )
        lines.append(
            "named anywhere in the day (the unnamed rows' correction): "
            + "; ".join(
                f"s_{item.tier.value} {item.in_day_mean:.3f} (90% {item.in_day_low:.3f} to "
                f"{item.in_day_high:.3f}; {item.in_day_hits} of {item.in_day_trials})"
                for item in report.sensitivity
            )
        )
        audit_ = report.hand_audit
        rate = "no rate yet" if audit_.rate is None else (
            f"false-open rate {audit_.rate:.3f} (90% {audit_.low:.3f} to {audit_.high:.3f})"
        )  # fmt: skip
        lines.append(
            f"hand audit: {audit_.unnamed} unnamed rows, {audit_.drawn} drawn over "
            f"{audit_.weeks} weeks, {audit_.audited} audited, {audit_.false_opens} not open, "
            f"{rate}; G1 (at least {audit_.min_rows} audited, at most {audit_.max_share} "
            f"false opens): {'met' if audit_.g1 else 'not met'}"
        )
        read = {
            region: sum(
                n for found in classes.values() for k, n in found.items() if k != "not_read"
            )
            for region, classes in report.rows.items()
        }
        lines.append(
            "read alerted rows by region: "
            + (", ".join(f"{r} {n}" for r, n in sorted(read.items())) or "none")
        )
    size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else 0
    lines.append(f"read record: {size} B")
    return lines


def run_read_labels(args: argparse.Namespace) -> int:  # pragma: no cover - the real world
    """Run ``predict read-labels``."""
    with tempfile.TemporaryDirectory() as scratch:
        return _run_read_labels(args, Path(scratch))


def _run_read_labels(args: argparse.Namespace, scratch: Path) -> int:  # pragma: no cover
    import os  # noqa: PLC0415

    from snowlight.live.publishers import DirPublisher  # noqa: PLC0415
    from snowlight.live.state import StateError  # noqa: PLC0415
    from snowlight.predict import frozen, learn  # noqa: PLC0415
    from snowlight.predict.cli import (  # noqa: PLC0415
        NO_STATE_WHERE,
        live_state_folder,
        make_pass,
    )
    from snowlight.predict.live_labels import (  # noqa: PLC0415
        NO_STATE,
        NoLiveSource,
        StateSource,
        markets_of,
    )
    from snowlight.predict.serve import ServeError, build_model  # noqa: PLC0415
    from snowlight.sources.stations.registry import load_registry  # noqa: PLC0415

    env = dict(os.environ)
    (args.reads / "rows").mkdir(parents=True, exist_ok=True)  # the cache step saves the folder
    try:
        run = make_pass(args, env, serving=False)  # the switch's state: read by its step
        directory = run.directory()
        committed = run.model()
        model = build_model(directory, committed, run.config, run.zone_fallback)
        host: Any
        if run.host is not None and run.mode.key is not None:
            host, prefix = run.host, run.mode.key.split("/", 1)[0]
        else:
            host, prefix = DirPublisher(INTERNAL / "predict" / "learn"), "v1"
            _out("predict read-labels: publishing is off: the audit stays in out/internal")
        stations = list(load_registry(args.registry).stations.values())
        missing = tuple(p.name for p in (args.read_sources, args.audiences) if not p.is_file())
        proven = live_read.load_read_sources(args.read_sources)
        coverage = live_read.Coverage(
            county_sources=proven.counties,
            archive=live_read.load_audiences(args.audiences),
            audience_season=live_read.load_audience_season(args.audiences),
            county_of={k: v.county for k, v in committed.districts.items() if v.county},
            district_sites=frozenset(s.id for s in stations if s.leaids),
            captures=proven.captures,
            min_captures=live_read.ReadRule.of(run.config).min_captures,
            rows=proven.rows,
        )
        _out(
            f"predict read-labels: {len(coverage.county_sources)} counties with proven lists, "
            f"{len(coverage.archive)} archive audiences"
        )
        source: Any = NoLiveSource()
        folder = live_state_folder(args.live_state, args.live_store, scratch)
        if folder is not None:
            source = live_read.StateReadSource(
                StateSource(
                    folder=folder,
                    market_of=markets_of((s.id, s.market) for s in stations),
                    zone_of=dict(zip(directory.district_ids, model.time_zone, strict=True)),
                    settings=run.config.labels,
                    prefix=prefix,
                    read_file=lambda path: host.read(f"{prefix}/{path}"),
                )
            )
        else:
            _out(f"predict read-labels: {NO_STATE}: {NO_STATE_WHERE}")
            return 0
    except (ValueError, OSError, ServeError, PublishError, StateError) as error:
        _err(f"predict read-labels: error: {type(error).__name__}: nothing is labeled")
        return 1
    return read_once(
        ReadLabelsRun(
            config=run.config,
            host=host,
            prefix=prefix,
            source=source,
            directory=learn.directory_of(model),
            coverage=coverage,
            snapshots=run.state.snapshots,
            folder=args.reads,
            now=datetime.now(UTC),
            missing=missing,
            outputs=Path(env["GITHUB_OUTPUT"]) if env.get("GITHUB_OUTPUT") else None,
            frozen=frozen.FOLDER,
            started=STARTED,
            model_sha256=run.model_sha256,
        )
    )


# --- read-sources -------------------------------------------------------------------------------


def read_sources_of(
    coverage: Mapping[str, object],
    reads: Path,
    min_captures: int,
    closing: Mapping[live_read.Capture, date],
) -> bytes:
    """``read-sources.json.gz``: ``coverage.json``'s proven counties with their sources, every
    source's populated archive captures of any day (``captures``: the ``thin_station``
    gate), and the rows of its **closing-size** captures only, the largest of each
    closing-size day (``closing_rows``, :func:`~snowlight.predict.live_read.closing_rows` of
    :func:`~snowlight.predict.live_read.closing_captures`: the size gate's reference and
    tier B's captures; the rule asks ``min_captures`` of them, archive and live record
    together, at run time). Codes and counts only: no dates, no text (lead ruling C3: row
    counts are numbers, not text).

    Raises:
        ValueError: ``coverage`` has no proven county table.
    """
    proven = coverage.get("proven")
    counties = proven.get("counties") if isinstance(proven, dict) else None
    if not isinstance(counties, dict):
        raise ValueError("coverage.json has no proven.counties")
    with reads.open(encoding="utf-8") as handle:
        every = live_read.populated_captures(handle)
    with reads.open(encoding="utf-8") as handle:
        rows = live_read.closing_rows(handle, closing)
    return live_read.gzip_json(
        {
            "schema_version": live_read.FILES_VERSION,
            "min_captures": min_captures,
            "closing_lit": live_read.CLOSING_LIT,
            "counties": live_read.county_sources_of(counties),
            "captures": every,
            "closing_rows": rows,
        }
    )


@dataclass(frozen=True, slots=True)
class Audiences:
    """``audiences.json.gz``'s bytes and what lead ruling C4 dropped from it."""

    data: bytes
    kept: int
    """(source, district) pairs kept."""
    dropped: int
    """Pairs the archive's audience rule gives whose last listing is before ``since``."""
    dropped_districts: int
    """Districts no kept pair carries that a dropped one did."""


def audiences_of(listings: list[tuple[str, str, date]], min_days: int, since: date) -> Audiences:
    """``audiences.json.gz``: each source's districts (7-digit LEAIDs only, sorted, no dates),
    by the archive's audience rule (listed on ``min_days`` local days), keeping only the pairs
    listed on or after ``since`` (lead ruling C4: the start of the previous season, so a list
    carries a district only when it listed it in the current or previous season; older pairs
    are dropped here, so the file holds no dates)."""
    from snowlight.predict.labels import audiences  # noqa: PLC0415

    found = audiences(
        [(s, d, day) for s, d, day in listings if len(d) == 7 and d.isdigit()],  # noqa: PLR2004
        min_days,
    )
    last: dict[tuple[str, str], date] = {}
    for source, district, day in listings:
        key = (source, district)
        if day > last.get(key, date.min):
            last[key] = day
    kept: dict[str, list[str]] = {}
    dropped: set[tuple[str, str]] = set()
    for source, districts in found.items():
        recent = sorted(d for d in districts if last[(source, d)] >= since)
        dropped.update((source, d) for d in districts if last[(source, d)] < since)
        if recent:
            kept[source] = recent
    carried = {d for districts in kept.values() for d in districts}
    data = live_read.gzip_json(
        {
            "schema_version": live_read.FILES_VERSION,
            "audience_days": min_days,
            "audience_seasons": AUDIENCE_SEASONS,
            "audiences": kept,
            "season": since.year + AUDIENCE_SEASONS - 1,
        }
    )
    return Audiences(
        data=data,
        kept=sum(len(d) for d in kept.values()),
        dropped=len(dropped),
        dropped_districts=len({d for _s, d in dropped} - carried),
    )


AUDIENCE_SEASONS: Final = 2
"""Lead ruling C4: the archive audiences keep pairs listed in the current or previous
season."""


def audience_since(today: date) -> date:
    """The first day of the season before ``today``'s (seasons begin Aug 1,
    :data:`~snowlight.predict.live_read.SEASON_START`)."""
    start = live_read.season_of(today)
    return start.replace(year=start.year - (AUDIENCE_SEASONS - 1))


def run_read_sources(args: argparse.Namespace) -> int:  # pragma: no cover - the real archive
    """Run ``predict read-sources``: match the whole archive (minutes, 4 workers), then write
    both coverage files."""
    import json  # noqa: PLC0415

    import polars as pl  # noqa: PLC0415

    from snowlight.predict import train  # noqa: PLC0415
    from snowlight.predict.situations import WeatherClass  # noqa: PLC0415

    config = PredictConfig.load(args.config)
    rule = live_read.ReadRule.of(config)
    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    table = pl.read_parquet(args.districts)
    zone_of = {
        d: z for d, z in zip(table["district"], table["time_zone"], strict=True) if z is not None
    }
    paths = train.TrainPaths(
        archive=args.archive,
        registry=args.registry,
        directory=args.directory,
        aliases=args.aliases,
        weather_cache=args.weather_cache,
    )
    run = train.prepare_archive(paths, zone_of, args.workers)
    table = pl.read_parquet(args.weather).select("district", "day", "weather")
    weather = {(str(d), day): WeatherClass(int(value)) for d, day, value in table.iter_rows()}
    closing = live_read.closing_captures(run.captured, weather)
    data = read_sources_of(coverage, args.archive / "reads.jsonl", rule.min_captures, closing)
    write_bytes_atomic(args.out / live_read.READ_SOURCES_PATH.name, data)
    proven = live_read.load_read_sources(args.out / live_read.READ_SOURCES_PATH.name)
    ready = {s for s, n in proven.rows.items() if len(n) >= rule.min_captures}
    sources = {s for found in proven.counties.values() for s in found}
    _out(
        f"read-sources: {len(proven.counties):,} counties, {len(sources):,} proven lists "
        f"({len(ready & sources):,} with {rule.min_captures} closing-size archive captures), "
        f"{len(proven.captures):,} lists with captures ({sum(proven.captures.values()):,}; "
        f"{len(closing):,} closing-size), {len(data):,} B"
    )
    since = audience_since(args.as_of)
    built = audiences_of(run.listings, config.labels.audience_days, since)
    write_bytes_atomic(args.out / live_read.AUDIENCES_PATH.name, built.data)
    found = live_read.load_audiences(args.out / live_read.AUDIENCES_PATH.name)
    districts = {d for districts in found.values() for d in districts}
    _out(
        f"audiences: {len(found):,} sources, {built.kept:,} pairs, {len(districts):,} districts, "
        f"{len(built.data):,} B; dropped {built.dropped:,} pairs last listed before "
        f"{since.isoformat()} ({built.dropped_districts:,} districts no kept pair carries)"
    )
    return 0

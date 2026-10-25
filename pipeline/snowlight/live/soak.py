"""``snowlight live soak --since T --until T``: the shadow soak's report (S8-E E2, E3), local and
read only, from public records:

* the reader's commits to ``v1-shadow/live/closings.json`` on the live host (each message is
  ``live <prefix> pass <start> run <id> sweep <s> due <n> good <n> lit <n> state <bytes>``);
* every commit under ``v1/live/`` (closings, opens, days, alerts, hold): one the reader made
  (a ``live v1 pass`` or ``live v1 alerts`` message, or any message naming a live-read run's
  id, which every write of a live-read process does) must not exist in shadow; the others are
  the overrides job's, whose served delay has its bar like predict's commits to
  ``v1/predictions/latest.json``;
* every commit of the live host in the window (their order) and its Pages deployments: a
  commit is served when the first successful deployment of it or of a later commit is (a
  commit whose own deployment was superseded is served by the one that replaced it);
* the live-read and live-ingest runs and their jobs, live-read's annotations (``live-read
  exit N``, the summary notice with the D1 rows of the day, the live host's size and the
  ``GITHUB_TOKEN`` count, the loop's ``first pass`` and ``end`` notices, the restored caches)
  and the token notices of live-ingest's ``reader`` job;
* githubstatus.com incidents (a gap is set apart only if it overlaps an Actions or Pages
  incident from 60 minutes before its start to 30 minutes after its end);
* for the drills (E4, E5, E6, E8): live-drill's runs and their ``live-drill <drill> <event>
  <time>`` notices, live-ingest's ``watch`` job annotations (``live watch: the served
  v1-shadow file is stale``) and the commits of ``v1-shadow/live/alerts.json`` (``live
  v1-shadow alerts open|close <kind> <time>``).

The report gives the publish gap on commits and on served time (p95, max; incident gaps and
stale minutes per day), the sweeps, every boundary between runs with its type and gap and the
cold starts (job start to first pass), live-read's exits, live-ingest's regularity and its
jobs, the packed state and D1 writes, the runner-hours, the cache restores and the live host's
growth a day, and the ``GITHUB_TOKEN`` hourly peak. It holds counts, times and run ids only.
"""

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any, Final

import httpx

from snowlight.output import JSONValue

PASS: Final = re.compile(
    r"^live (?P<prefix>[a-z0-9-]+) pass (?P<start>\S+) run (?P<run>\S+) sweep (?P<sweep>\d+)"
    r" due (?P<due>\d+) good (?P<good>\d+) lit (?P<lit>\d+) state (?P<state>\d+)"
)
SUMMARY: Final = re.compile(
    r"live-read summary: exit (?P<exit>\S+); state bytes (?P<bytes>\S+);"
    r".*d1 rows today (?P<rows>[^;\s]+)"
)
EXIT: Final = re.compile(r"live-read exit (?P<exit>-?\d+)")
FIRST: Final = re.compile(r"live-read first pass (?P<at>\S+)")
"""The loop's notice of its first pass's start (the cold start ends there)."""
END: Final = re.compile(r"live-read end (?P<cause>[a-z_]+)")
"""The loop's notice of why it ended (``until``, ``edition``, ``overrides``, ``passes``, ...)."""
TOKEN: Final = re.compile(r"github token used (?P<used>\d+) of (?P<limit>\d+) reset (?P<reset>\d+)")
"""``X-RateLimit-Used``, ``-Limit`` and ``-Reset`` of the repository's ``GITHUB_TOKEN``."""
HOST_SIZE: Final = re.compile(r"live host size (?P<kb>\d+) KB")
CACHES: Final = re.compile(r"live-read caches restored (?P<bytes>\d+) bytes")
READER_V1: Final = re.compile(r"^live v1 (?:pass|alerts) ")
"""A message only the reader writes under ``v1/`` (the overrides job's commits carry the
default message, or ``run -`` on a blank)."""
RUN_ID: Final = re.compile(r"\brun (?P<id>\d+)\b")
ALERT_CHANGE: Final = re.compile(
    r"^live (?P<prefix>[a-z0-9-]+) alerts (?P<what>open|close) (?P<kind>[a-z_]+) (?P<at>\S+)"
)
"""The commit message of each change of ``alerts.json``."""
DRILL: Final = re.compile(
    r"live-drill (?P<drill>stall|gate|switch) (?P<event>[a-z]+(?: [a-z]+)?) (?P<at>\d{4}-\S+Z)"
)
"""A drill's notice of one of its moments (``stall disabled``, ``stall enabled``, ``stall
reader started``, ``gate blank``, ``gate release``, ``switch started|passed|failed``)."""
BLANK_SERVED: Final = re.compile(r"drill gate: the blank .*: (?P<seconds>-?\d+) s, (?:within|over)")
NOT_FRESH: Final = re.compile(r"live watch: the served v1-shadow file is (?:stale|missing|ahead)")
HOLD_COMMIT: Final = "live-blank v1-shadow blank "
STALE: Final = timedelta(minutes=15)
SET_APART_FROM: Final = timedelta(minutes=6)
"""Only a gap longer than the p95 bar can be set apart for an incident."""
BEFORE: Final = timedelta(minutes=60)
AFTER: Final = timedelta(minutes=30)
INGEST_EVERY: Final = timedelta(minutes=5)
INGEST_SLACK: Final = timedelta(seconds=30)
SUCCESSOR_WITHIN: Final = timedelta(minutes=10)
SHADOW_CLOSINGS: Final = "v1-shadow/live/closings.json"
SHADOW_ALERTS: Final = "v1-shadow/live/alerts.json"
V1_LIVE: Final = "v1/live"
"""Every live file under ``v1/`` (closings, opens, days, alerts, hold)."""
PREDICTIONS: Final = "v1/predictions/latest.json"
HOST: Final = "viaate/snowlight-live"
SITE: Final = "viaate/jsalcards"
BARS: Final = {
    "gap_p95_minutes": 6.0,
    "gap_max_minutes": 15.0,
    "sweep_due_p95_seconds": 150.0,
    "sweep_full_max_seconds": 300.0,
    "successor_gap_max_minutes": 7.0,
    "successor_gap_p50_minutes": 6.0,
    "other_gap_max_minutes": 15.0,
    "cold_start_p95_seconds": 120.0,
    "served_p95_seconds": 60.0,
    "served_max_seconds": 90.0,
    "state_max_bytes": 12 * 1024 * 1024,
    "d1_rows_day_max": 30_000,
    "token_hourly_peak_max": 600,
}
DRILL_BARS: Final = {
    "stale_within_minutes": 30.0,
    "reader_within_minutes": 5.0,
    "stale_cleared_within_minutes": 10.0,
    "gate_open_within_minutes": 15.0,
    "gate_cleared_within_minutes": 10.0,
    "blank_served_within_seconds": 60.0,
}


@dataclass(frozen=True, slots=True)
class Commit:
    sha: str
    at: datetime
    message: str
    path: str = SHADOW_CLOSINGS

    @property
    def parsed(self) -> dict[str, str] | None:
        found = PASS.match(self.message)
        return None if found is None else found.groupdict()


@dataclass(frozen=True, slots=True)
class Run:
    id: int
    workflow: str
    created: datetime
    started: datetime | None = None
    ended: datetime | None = None
    conclusion: str | None = None
    jobs: Mapping[str, str] = field(default_factory=dict)
    """Each job's conclusion by name."""
    annotations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Incident:
    start: datetime
    end: datetime
    components: tuple[str, ...]


@dataclass(slots=True)
class History:
    since: datetime
    until: datetime
    commits: list[Commit] = field(default_factory=list)
    """The reader's commits to the shadow closings file."""
    v1_commits: list[Commit] = field(default_factory=list)
    """Every commit under ``v1/live/``."""
    served: dict[str, datetime] = field(default_factory=dict)
    """When each deployment of the live host succeeded, by its commit's sha."""
    order: list[str] = field(default_factory=list)
    """Every live-host commit of the window, oldest first (empty: each commit is served by
    its own deployment only)."""
    other_commits: list[Commit] = field(default_factory=list)
    """Predict's commits (their served time has its own bar); the overrides job's are the
    ``v1_commits`` that are not the reader's."""
    runs: list[Run] = field(default_factory=list)
    incidents: list[Incident] = field(default_factory=list)
    alert_commits: list[Commit] = field(default_factory=list)
    """The commits of the shadow ``alerts.json`` (one per alert change)."""


def percentile(values: Sequence[float], share: float) -> float | None:
    """The nearest-rank percentile (``None`` with no values)."""
    if not values:
        return None
    ranked = sorted(values)
    return ranked[max(0, min(len(ranked) - 1, math.ceil(share * len(ranked)) - 1))]


def _minutes(delta: timedelta) -> float:
    return round(delta.total_seconds() / 60, 2)


def _incident_for(start: datetime, end: datetime, incidents: Iterable[Incident]) -> bool:
    """Whether a gap from ``start`` to ``end`` overlaps an Actions or Pages incident widened
    by 60 minutes before and 30 after."""
    return any(
        start < incident.end + AFTER
        and end > incident.start - BEFORE
        and any(name in {"Actions", "Pages"} for name in incident.components)
        for incident in incidents
    )


def gaps(
    times: Sequence[datetime],
    incidents: Sequence[Incident],
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, JSONValue]:
    """The gaps between consecutive times: p95, max (a gap over 6 minutes that overlaps an
    incident is set apart, and listed), and the stale minutes per day. With the window
    (``since`` and ``until``), its edges count as gaps too: from ``since`` to the first time
    and from the last time to ``until`` (the whole window when there is none), so a reader
    dark at the start or the end of the soak is not missed; ``edges`` gives both in
    minutes."""
    ordered = sorted(times)
    kept: list[float] = []
    apart: list[dict[str, JSONValue]] = []
    stale: Counter[str] = Counter()
    bounds = list(ordered)
    edges: dict[str, JSONValue] = {}
    if since is not None and until is not None:
        bounds = [since, *(moment for moment in ordered if since <= moment <= until), until]
        edges = {
            "start_minutes": _minutes(bounds[1] - since),
            "end_minutes": _minutes(until - bounds[-2]),
        }
    for before, after in pairwise(bounds):
        gap = after - before
        if gap > STALE:
            stale[before.date().isoformat()] += int((gap - STALE).total_seconds() // 60)
        if gap > SET_APART_FROM and _incident_for(before, after, incidents):
            apart.append({"from": before.isoformat(), "minutes": _minutes(gap)})
        else:
            kept.append(gap.total_seconds() / 60)
    return {
        "count": len(kept),
        "p95_minutes": None if not kept else round(percentile(kept, 0.95) or 0.0, 2),
        "max_minutes": None if not kept else round(max(kept), 2),
        "set_apart": list[JSONValue](apart),
        "stale_minutes_by_day": dict(sorted(stale.items())),
        **({"edges": edges} if edges else {}),
    }


def served_times(order: Sequence[str], own: Mapping[str, datetime]) -> dict[str, datetime]:
    """When each commit was served: the first success among the deployments of it and of
    every later commit (Pages folds a superseded deployment into a later one, so the commit
    is served when that one is). Without the order, each commit's own deployment only."""
    if not order:
        return dict(own)
    found: dict[str, datetime] = {}
    soonest: datetime | None = None
    for sha in reversed(order):
        moment = own.get(sha)
        if moment is not None and (soonest is None or moment < soonest):
            soonest = moment
        if soonest is not None:
            found[sha] = soonest
    return found


def _moment(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _first(run: Run, pattern: re.Pattern[str]) -> re.Match[str] | None:
    return next((found for line in run.annotations if (found := pattern.search(line))), None)


def reader_commit(commit: Commit, read_ids: frozenset[str]) -> bool:
    """Whether a commit under ``v1/`` is the reader's: a message only the reader writes there,
    or one that names a live-read run (every write of a live-read process names its run)."""
    if READER_V1.match(commit.message):
        return True
    return any(found["id"] in read_ids for found in RUN_ID.finditer(commit.message))


def boundary_kind(previous: Run | None, following: Run | None) -> str:
    """A boundary's type from the old run's end: ``mode change`` (it was cancelled: the
    reader job cancels a run in the old mode), ``restart after a kill`` (exit 124),
    ``restart after exit 1``, ``edition stop`` (its loop ended for a deployed directory
    change), ``successor`` (the new run's job started within 10 minutes of the old one's
    end), else ``restart`` (the chain broke: the reader job or the schedule restarted it)."""
    if previous is None:
        return "restart"
    code = _first(previous, EXIT)
    end = _first(previous, END)
    kinds = (
        (previous.conclusion == "cancelled", "mode change"),
        (code is not None and code["exit"] == "124", "restart after a kill"),
        (code is not None and code["exit"] == "1", "restart after exit 1"),
        (end is not None and end["cause"] == "edition", "edition stop"),
        (
            following is not None
            and previous.ended is not None
            and following.started is not None
            and timedelta(0) <= following.started - previous.ended <= SUCCESSOR_WITHIN,
            "successor",
        ),
    )
    return next((kind for found, kind in kinds if found), "restart")


def handoffs(commits: Sequence[Commit], runs: Mapping[str, Run]) -> dict[str, JSONValue]:
    """Each boundary between two runs' commits, with its type (:func:`boundary_kind`) and
    gap, and the cold starts (:func:`cold_starts`)."""
    found: list[dict[str, JSONValue]] = []
    successors: list[float] = []
    others: list[float] = []
    by_kind: Counter[str] = Counter()
    parsed = [(commit, commit.parsed) for commit in sorted(commits, key=lambda item: item.at)]
    for (before, old), (after, new) in pairwise(parsed):
        if old is None or new is None or old["run"] == new["run"]:
            continue
        gap = _minutes(after.at - before.at)
        kind = boundary_kind(runs.get(old["run"]), runs.get(new["run"]))
        by_kind[kind] += 1
        (successors if kind == "successor" else others).append(gap)
        found.append({"at": after.at.isoformat(), "kind": kind, "gap_minutes": gap})
    colds = cold_starts(commits, runs.values())
    return {
        "boundaries": list[JSONValue](found),
        "by_kind": dict(sorted(by_kind.items())),
        "successor_p50_minutes": percentile(successors, 0.5),
        "successor_max_minutes": max(successors, default=None),
        "other_max_minutes": max(others, default=None),
        "cold_starts": len(colds),
        "cold_start_p95_seconds": percentile(colds, 0.95),
        "cold_start_max_seconds": max(colds, default=None),
    }


def cold_starts(commits: Sequence[Commit], runs: Iterable[Run]) -> list[float]:
    """Each live-read run's cold start: its job's start to its first pass's start, from the
    loop's ``first pass`` notice (a successor's first pass may skip an unchanged upload, so
    its first commit can be the next grid pass); from its first commit only when the notice
    is missing."""
    first_commit: dict[str, datetime] = {}
    for commit in sorted(commits, key=lambda item: item.at):
        found = commit.parsed
        if found is not None and found["run"] not in first_commit:
            start = _moment(found["start"])
            if start is not None:
                first_commit[found["run"]] = start
    colds: list[float] = []
    for run in runs:
        if run.workflow != "live-read" or run.started is None:
            continue
        notice = _first(run, FIRST)
        first = _moment(notice["at"]) if notice is not None else first_commit.get(str(run.id))
        if first is not None and first >= run.started:
            colds.append((first - run.started).total_seconds())
    return colds


def token_peaks(runs: Iterable[Run]) -> dict[str, int]:
    """The ``GITHUB_TOKEN`` peak of each rate-limit hour (by its reset hour, UTC): the most
    any notice saw used in that window."""
    peaks: dict[str, int] = {}
    for run in runs:
        for line in run.annotations:
            if (found := TOKEN.search(line)) is None:
                continue
            reset = datetime.fromtimestamp(int(found["reset"]), UTC)
            hour = reset.replace(minute=0, second=0, microsecond=0).isoformat()
            peaks[hour] = max(peaks.get(hour, 0), int(found["used"]))
    return dict(sorted(peaks.items()))


def host_growth(runs: Iterable[Run]) -> dict[str, JSONValue]:
    """The live host's size at the first and last live-read run end, and its growth a day."""
    sizes = sorted(
        (run.ended, int(found["kb"]))
        for run in runs
        if run.workflow == "live-read"
        and run.ended is not None
        and (found := _first(run, HOST_SIZE)) is not None
    )
    if len(sizes) < 2:  # noqa: PLR2004 - a growth needs two sizes
        return {"first_kb": None, "last_kb": None, "kb_per_day": None}
    (first_at, first_kb), (last_at, last_kb) = sizes[0], sizes[-1]
    days = (last_at - first_at).total_seconds() / 86_400
    return {
        "first_kb": first_kb,
        "last_kb": last_kb,
        "kb_per_day": None if days <= 0 else round((last_kb - first_kb) / days, 1),
    }


def cache_restores(runs: Iterable[Run]) -> dict[str, float]:
    """The GB of caches live-read restored each day (by its job's start)."""
    days: defaultdict[str, int] = defaultdict(int)
    for run in runs:
        if run.workflow != "live-read" or run.started is None:
            continue
        if (found := _first(run, CACHES)) is not None:
            days[run.started.date().isoformat()] += int(found["bytes"])
    return {day: round(total / 1e9, 3) for day, total in sorted(days.items())}


def report(history: History) -> dict[str, JSONValue]:
    """The soak report (see the module): numbers, and each bar's verdict."""

    def inside(commit: Commit) -> bool:
        return history.since <= commit.at <= history.until

    commits = [commit for commit in history.commits if inside(commit)]
    parsed = [found for commit in commits if (found := commit.parsed) is not None]
    sweeps = [float(found["sweep"]) for found in parsed]
    due_sweeps = [float(found["sweep"]) for found in parsed if int(found["due"]) > 0]
    states = [int(found["state"]) for found in parsed]
    served_at = served_times(history.order, history.served)
    served = [served_at[commit.sha] for commit in commits if commit.sha in served_at]
    reads = [run for run in history.runs if run.workflow == "live-read"]
    read_ids = frozenset(str(run.id) for run in reads)
    v1 = [commit for commit in history.v1_commits if inside(commit)]
    readers_v1 = [commit for commit in v1 if reader_commit(commit, read_ids)]
    others = [
        *(commit for commit in history.other_commits if inside(commit)),
        *(commit for commit in v1 if not reader_commit(commit, read_ids)),
    ]
    other_delays = [
        (served_at[commit.sha] - commit.at).total_seconds()
        for commit in others
        if commit.sha in served_at
    ]
    runs = {str(run.id): run for run in history.runs}
    ingests = sorted(
        (run for run in history.runs if run.workflow == "live-ingest"), key=lambda run: run.created
    )
    exits: Counter[str] = Counter()
    rows_by_day: dict[str, int] = {}
    for run in reads:
        for line in run.annotations:
            if (code := EXIT.search(line)) is not None:
                exits[code["exit"]] += 1
            if (
                (summary := SUMMARY.search(line)) is not None
                and summary["rows"].isdigit()
                and run.ended
            ):
                day = run.ended.date().isoformat()
                rows_by_day[day] = max(rows_by_day.get(day, 0), int(summary["rows"]))
    steps = [b.created - a.created for a, b in pairwise(ingests)]
    regular = [
        step
        for step, (a, b) in zip(steps, pairwise(ingests), strict=True)
        if not _incident_for(a.created, b.created, history.incidents)
    ]
    on_time = sum(1 for step in regular if abs(step - INGEST_EVERY) <= INGEST_SLACK)
    jobs: Counter[str] = Counter()
    for run in ingests:
        for name in ("reader", "watch"):
            jobs[f"{name}:{run.jobs.get(name, 'missing')}"] += 1
    hours: defaultdict[str, float] = defaultdict(float)
    for run in reads:
        if run.started and run.ended:
            hours[run.started.date().isoformat()] += (
                run.ended - run.started
            ).total_seconds() / 3600
    peaks = token_peaks(history.runs)
    numbers: dict[str, JSONValue] = {
        "since": history.since.isoformat(),
        "until": history.until.isoformat(),
        "commits": len(commits),
        "gap_on_commits": gaps(
            [commit.at for commit in commits], history.incidents, history.since, history.until
        ),
        "gap_on_served_time": gaps(served, history.incidents, history.since, history.until),
        "sweep_due_p95_seconds": percentile(due_sweeps, 0.95),
        "sweep_full_max_seconds": max(sweeps, default=None),
        "reader_commits_under_v1": len(readers_v1),
        "reader_commits_under_v1_shas": [commit.sha for commit in readers_v1],
        "live_read_exits": dict(sorted(exits.items())),
        "live_ingest_runs": len(ingests),
        "live_ingest_on_time": on_time,
        "live_ingest_steps_outside_incidents": len(regular),
        "live_ingest_jobs": dict(sorted(jobs.items())),
        "served_delay_commits": len(other_delays),
        "served_delay_p95_seconds": percentile(other_delays, 0.95),
        "served_delay_max_seconds": max(other_delays, default=None),
        "state_max_bytes": max(states, default=None),
        "d1_rows_by_day": dict(sorted(rows_by_day.items())),
        "runner_hours_by_day": {day: round(value, 2) for day, value in sorted(hours.items())},
        "cache_restores_gb_by_day": dict(cache_restores(history.runs)),
        "live_host_growth": host_growth(history.runs),
        "github_token_peak_by_hour": dict(peaks),
        "github_token_hourly_peak": max(peaks.values(), default=None),
        "handoffs": handoffs(commits, runs),
        "incidents": len(history.incidents),
        "drills": list[JSONValue](drills(history)),
    }
    numbers["bars"] = bars(numbers)
    return numbers


def _drill_moments(runs: Iterable[Run]) -> list[tuple[str, str, datetime, Run]]:
    """Every drill notice ``(drill, event, time, run)``, oldest first."""
    found = []
    for run in runs:
        if run.workflow != "live-drill":
            continue
        for line in run.annotations:
            if (match := DRILL.search(line)) is not None and (
                moment := _moment(match["at"])
            ) is not None:
                found.append((match["drill"], match["event"], moment, run))
    return sorted(found, key=lambda item: item[2])


def _delay(start: datetime | None, end: datetime | None) -> float | None:
    return None if start is None or end is None else _minutes(end - start)


def _within(
    value: float | None, bar: float, start: datetime | None = None, until: datetime | None = None
) -> bool | None:
    """``value`` (minutes, or seconds for a seconds bar) at most ``bar``; with no value, a
    miss when the window ran past ``start`` + ``bar`` (it never came), else not measured."""
    if value is not None:
        return value <= bar
    if start is not None and until is not None and start + timedelta(minutes=bar) <= until:
        return False
    return None


def _stall(history: History, disabled: datetime, enabled: datetime) -> dict[str, JSONValue]:
    """E4 from the records: ``stale`` within 30 minutes of the last shadow commit, the reader
    running within 5 minutes of the enable, ``stale`` cleared within 10 minutes of the first
    fresh commit, every live-ingest run of the drill green."""
    passes = sorted(
        (commit for commit in history.commits if commit.parsed is not None),
        key=lambda commit: commit.at,
    )
    last = next((c.at for c in reversed(passes) if c.at <= enabled), None)
    fresh = next((c.at for c in passes if c.at > enabled), None)
    watches = sorted(
        (run for run in history.runs if run.workflow == "live-ingest"),
        key=lambda run: run.started or run.created,
    )

    def when(run: Run) -> datetime:
        return run.started or run.created

    def stale(run: Run) -> bool:
        return any(NOT_FRESH.search(line) for line in run.annotations)

    first_stale = next(
        (when(run) for run in watches if last is not None and when(run) >= last and stale(run)),
        None,
    )
    cleared = next(
        (
            when(run)
            for run in watches
            if fresh is not None
            and when(run) >= fresh
            and not stale(run)
            and run.jobs.get("watch") == "success"
        ),
        None,
    )
    reader = next(
        (
            run.started
            for run in sorted(
                (r for r in history.runs if r.workflow == "live-read" and r.started),
                key=lambda r: r.started or r.created,
            )
            if run.started is not None and run.started >= enabled
        ),
        None,
    )
    end = cleared or fresh or enabled
    during = [run for run in watches if disabled <= run.created <= end]
    stale_after = _delay(last, first_stale)
    reader_after = _delay(enabled, reader)
    cleared_after = _delay(fresh, cleared)
    return {
        "drill": "stall",
        "disabled": disabled.isoformat(),
        "enabled": enabled.isoformat(),
        "last_shadow_commit": None if last is None else last.isoformat(),
        "stale_after_minutes": stale_after,
        "reader_after_enable_minutes": reader_after,
        "first_fresh_commit": None if fresh is None else fresh.isoformat(),
        "stale_cleared_after_minutes": cleared_after,
        "live_ingest_runs": len(during),
        "bars": {
            "stale_within_30": _within(
                stale_after, DRILL_BARS["stale_within_minutes"], last, history.until
            ),
            "reader_within_5": _within(
                reader_after, DRILL_BARS["reader_within_minutes"], enabled, history.until
            ),
            "stale_cleared_within_10": _within(
                cleared_after, DRILL_BARS["stale_cleared_within_minutes"], fresh, history.until
            ),
            "live_ingest_green": all(run.conclusion == "success" for run in during)
            if during
            else None,
        },
    }


def _gate(
    history: History, blank: datetime, release: datetime | None, run: Run
) -> dict[str, JSONValue]:
    """E5 and E6 from the records: ``gate`` opened in ``alerts.json`` within 15 minutes of
    the hold commit and cleared within 10 minutes of the release, the blank served within
    60 s of its commit (the drill's own notice), nothing under ``v1/`` from the reader."""
    held = next(
        (
            commit.at
            for commit in sorted(history.commits, key=lambda item: item.at)
            if commit.at >= blank and commit.message.startswith(HOLD_COMMIT)
        ),
        None,
    )
    changes = [
        (commit.at, found)
        for commit in sorted(history.alert_commits, key=lambda item: item.at)
        if (found := ALERT_CHANGE.match(commit.message)) is not None and found["kind"] == "gate"
    ]
    opened = next(
        (at for at, found in changes if held and at >= held and found["what"] == "open"), None
    )
    closed = next(
        (at for at, found in changes if release and at >= release and found["what"] == "close"),
        None,
    )
    served = next(
        (int(found["seconds"]) for line in run.annotations if (found := BLANK_SERVED.search(line))),
        None,
    )
    read_ids = frozenset(str(item.id) for item in history.runs if item.workflow == "live-read")
    until = (release or blank) + timedelta(minutes=15)
    under_v1 = [
        commit
        for commit in history.v1_commits
        if blank <= commit.at <= until and reader_commit(commit, read_ids)
    ]
    open_after = _delay(held, opened)
    close_after = _delay(release, closed)
    return {
        "drill": "gate",
        "blank": blank.isoformat(),
        "hold_commit": None if held is None else held.isoformat(),
        "release": None if release is None else release.isoformat(),
        "gate_open_after_minutes": open_after,
        "gate_cleared_after_minutes": close_after,
        "blank_served_seconds": served,
        "reader_commits_under_v1": len(under_v1),
        "bars": {
            "gate_open_within_15": _within(
                open_after, DRILL_BARS["gate_open_within_minutes"], held, history.until
            ),
            "gate_cleared_within_10": _within(
                close_after, DRILL_BARS["gate_cleared_within_minutes"], release, history.until
            ),
            "blank_served_within_60_s": _within(
                None if served is None else float(served),
                DRILL_BARS["blank_served_within_seconds"],
            ),
            "no_v1_commits": not under_v1,
        },
    }


def drills(history: History) -> list[dict[str, JSONValue]]:
    """Each drill of the window with its E4, E5, E6 or E8 measures and bars (see
    :func:`_stall` and :func:`_gate`; a switch rehearsal's own verdict)."""
    found: list[dict[str, JSONValue]] = []
    moments = _drill_moments(history.runs)
    for drill, event, moment, run in moments:
        later = [(e, m) for d, e, m, r in moments if r.id == run.id and d == drill]
        if drill == "stall" and event == "disabled":
            enabled = next((m for e, m in later if e == "enabled"), None)
            if enabled is not None:
                found.append(_stall(history, moment, enabled))
        elif drill == "gate" and event == "blank":
            release = next((m for e, m in later if e == "release"), None)
            found.append(_gate(history, moment, release, run))
        elif drill == "switch" and event in {"passed", "failed"}:
            found.append(
                {"drill": "switch", "at": moment.isoformat(), "bars": {"served": event == "passed"}}
            )
    return found


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def bars(numbers: Mapping[str, Any]) -> dict[str, JSONValue]:
    """Each E2/E3 bar: met, missed, or not measured (``None``)."""

    def at_most(value: object, bar: float) -> bool | None:
        found = _number(value)
        return None if found is None else found <= bar

    commits, served, hand = (
        numbers["gap_on_commits"],
        numbers["gap_on_served_time"],
        numbers["handoffs"],
    )
    exits = numbers["live_read_exits"]
    rows = numbers["d1_rows_by_day"]
    return {
        "gap_p95": at_most(commits["p95_minutes"], BARS["gap_p95_minutes"]),
        "gap_max": at_most(commits["max_minutes"], BARS["gap_max_minutes"]),
        "served_gap_p95": at_most(served["p95_minutes"], BARS["gap_p95_minutes"]),
        "served_gap_max": at_most(served["max_minutes"], BARS["gap_max_minutes"]),
        "sweep_due_p95": at_most(numbers["sweep_due_p95_seconds"], BARS["sweep_due_p95_seconds"]),
        "sweep_full_max": at_most(
            numbers["sweep_full_max_seconds"], BARS["sweep_full_max_seconds"]
        ),
        "no_v1_commits": numbers["reader_commits_under_v1"] == 0,
        "no_exit_1": not any(code in exits for code in ("1", "124")),
        "successor_gap_max": at_most(
            hand["successor_max_minutes"], BARS["successor_gap_max_minutes"]
        ),
        "successor_gap_p50": at_most(
            hand["successor_p50_minutes"], BARS["successor_gap_p50_minutes"]
        ),
        "other_gap_max": at_most(hand["other_max_minutes"], BARS["other_gap_max_minutes"]),
        "cold_start_p95": at_most(hand["cold_start_p95_seconds"], BARS["cold_start_p95_seconds"]),
        "served_p95": at_most(numbers["served_delay_p95_seconds"], BARS["served_p95_seconds"]),
        "served_max": at_most(numbers["served_delay_max_seconds"], BARS["served_max_seconds"]),
        "state_size": at_most(numbers["state_max_bytes"], BARS["state_max_bytes"]),
        "d1_rows": None if not rows else max(rows.values()) <= BARS["d1_rows_day_max"],
        "token_hourly_peak": at_most(
            numbers["github_token_hourly_peak"], BARS["token_hourly_peak_max"]
        ),
        "ingest_jobs_green": all(key.endswith(":success") for key in numbers["live_ingest_jobs"])
        if numbers["live_ingest_jobs"]
        else None,
        "ingest_on_time": None
        if not numbers["live_ingest_steps_outside_incidents"]
        else numbers["live_ingest_on_time"] == numbers["live_ingest_steps_outside_incidents"],
    }


# Reading the public records (the network) ---------------------------------------------------


def _when(text: object) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@dataclass(slots=True)
class Public:
    """The public API, read only (a token raises the rate limit; none is needed)."""

    client: httpx.Client
    token: str = ""

    def get(self, url: str, params: Mapping[str, str] | None = None) -> Any:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = self.client.get(url, params=params, headers=headers, timeout=30.0)
        response.raise_for_status()
        return response.json()

    def pages(self, url: str, params: Mapping[str, str], key: str | None = None) -> list[Any]:
        found: list[Any] = []
        for page in range(1, 50):
            body = self.get(url, {**params, "per_page": "100", "page": str(page)})
            items = body.get(key, []) if key else body
            if not items:
                break
            found.extend(items)
        return found


def commits_of(
    public: Public, repository: str, path: str | None, since: datetime, until: datetime
) -> list[Commit]:
    """The commits of ``repository`` touching ``path`` (every commit when ``None``), oldest
    first."""
    params = {"since": since.isoformat(), "until": until.isoformat()}
    if path is not None:
        params["path"] = path
    items = public.pages(f"https://api.github.com/repos/{repository}/commits", params)
    found = []
    for item in items:
        at = _when(item.get("commit", {}).get("committer", {}).get("date"))
        if at is not None:
            found.append(Commit(str(item["sha"]), at, str(item["commit"]["message"]), path or ""))
    return sorted(found, key=lambda commit: commit.at)


COMMIT_PATHS: Final = (SHADOW_CLOSINGS, V1_LIVE, PREDICTIONS, SHADOW_ALERTS)
"""The live-host paths the report lists commits of."""


def fetch_history(
    client: httpx.Client, since: datetime, until: datetime, token: str = ""
) -> History:
    """Every public record the report reads (see the module)."""
    public = Public(client, token)
    history = History(since, until)
    wide_since, wide_until = since - timedelta(hours=1), until + timedelta(hours=1)
    history.commits = commits_of(public, HOST, SHADOW_CLOSINGS, since, until)
    history.v1_commits = commits_of(public, HOST, V1_LIVE, since, until)
    history.other_commits = commits_of(public, HOST, PREDICTIONS, since, until)
    history.alert_commits = commits_of(public, HOST, SHADOW_ALERTS, since, until)
    history.order = [
        commit.sha for commit in commits_of(public, HOST, None, wide_since, wide_until)
    ]
    for deployment in public.pages(
        f"https://api.github.com/repos/{HOST}/deployments", {"environment": "github-pages"}
    ):
        created = _when(deployment.get("created_at"))
        if created is None or created < wide_since or created > wide_until:
            continue
        statuses = public.get(str(deployment["statuses_url"]))
        done = [
            _when(status.get("created_at"))
            for status in statuses
            if status.get("state") == "success"
        ]
        moments = [moment for moment in done if moment is not None]
        if moments:
            history.served[str(deployment["sha"])] = min(moments)
    window = f"{since.date().isoformat()}..{until.date().isoformat()}"
    for workflow in ("live-read", "live-ingest", "live-drill"):
        runs = public.pages(
            f"https://api.github.com/repos/{SITE}/actions/workflows/{workflow}.yml/runs",
            {"created": window},
            "workflow_runs",
        )
        for run in runs:
            history.runs.append(_run(public, workflow, run, since))
    incidents = public.get("https://www.githubstatus.com/api/v2/incidents.json").get(
        "incidents", []
    )
    for incident in incidents:
        start, end = _when(incident.get("created_at")), _when(incident.get("resolved_at")) or until
        if start is None or end < since or start > until:
            continue
        names = tuple(str(item.get("name", "")) for item in incident.get("components", []))
        history.incidents.append(Incident(start, end, names))
    return history


def _run(public: Public, workflow: str, run: Mapping[str, Any], since: datetime) -> Run:
    """One run with its jobs, and the annotations of live-read's and live-drill's jobs and
    of live-ingest's ``reader`` job (its token notice) and ``watch`` job (a stale file)."""
    jobs = public.get(str(run["jobs_url"])).get("jobs", [])
    annotations: list[str] = []
    for job in jobs:
        if workflow in {"live-read", "live-drill"} or job.get("name") in {"reader", "watch"}:
            found = public.get(
                f"https://api.github.com/repos/{SITE}/check-runs/{job['id']}/annotations"
            )
            annotations.extend(str(item.get("message", "")) for item in found)
    started = [moment for job in jobs if (moment := _when(job.get("started_at")))]
    ended = [moment for job in jobs if (moment := _when(job.get("completed_at")))]
    return Run(
        id=int(run["id"]),
        workflow=workflow,
        created=_when(run["created_at"]) or since,
        started=min(started, default=None),
        ended=max(ended, default=None),
        conclusion=run.get("conclusion"),
        jobs={str(job["name"]): str(job.get("conclusion")) for job in jobs},
        annotations=tuple(annotations),
    )


def render(found: Mapping[str, JSONValue]) -> str:
    """The report as indented JSON (counts, times and run ids only)."""
    return json.dumps(found, indent=2, sort_keys=True, default=str)


def parse_moment(text: str, clock: Callable[[], datetime] | None = None) -> datetime:
    """``2026-10-31T18:00Z`` or ``now``."""
    if text == "now":
        return (clock or (lambda: datetime.now(UTC)))()
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)

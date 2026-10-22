"""``snowlight live sweep``: one pool pass over every active source, measured (S8-B).

It reads every source the ingest polls (or the ids given) once through the live pool,
exactly as a pass does, but resolves and publishes nothing. It appends every request to
the request log (the pace key, its floor and when it held the key) and writes a report:
how long the sweep took, when each source finished, the outcomes, the requests the HTTP
client sent against those the pacer granted, each place the pacing was broken
(:func:`~snowlight.live.pool.violations`), and the robots.txt requests per origin, every
attempt counted, from the request log (:func:`~snowlight.live.pool.robots_requests`), with
the reads they make up (:func:`~snowlight.live.pool.robots_reads`; a read's retries and
redirect hops listed apart). Both hold ids, hosts, codes and times only, never page
text. Bodies go to the conditional-request cache only (the next sweep's 304s).
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import httpx

from snowlight.live.ledger import Outcome
from snowlight.live.pool import (
    WORKERS,
    PassResult,
    RequestLog,
    pace_key,
    percentile,
    robots_reads,
    robots_requests,
    violations,
)
from snowlight.live.reads import due_sources, live_pool
from snowlight.output import write_bytes_atomic
from snowlight.sources.stations.fetch import RunResult, read_station
from snowlight.sources.stations.http import PoliteClient, make_client
from snowlight.sources.stations.registry import Registry, Station, load_registry

SLOWEST: Final = 15


def report(
    result: PassResult,
    log: RequestLog,
    sent: Counter[str],
    *,
    label: str,
) -> dict[str, object]:
    """The sweep's report (see the module)."""
    requests = robots_requests(log.entries)
    reads = robots_reads(log.entries)
    finished = [item.finished for item in result.sources]
    lanes: dict[str, list[float]] = {}
    for entry in log.entries:
        lanes.setdefault(entry.key, []).append(entry.end)
    origin = min((entry.start for entry in log.entries), default=0.0)
    slowest = sorted(
        ((key, len(ends), round(max(ends) - origin, 1)) for key, ends in lanes.items()),
        key=lambda item: -item[2],
    )[:SLOWEST]
    broken = violations(log.entries)
    paced = Counter(entry.key for entry in log.entries)
    by_outcome: dict[str, list[str]] = {}
    for item in result.sources:
        if item.outcome not in {Outcome.OK, Outcome.NOT_MODIFIED, Outcome.EMPTY}:
            status = item.http_status if item.http_status is not None else "none"
            by_outcome.setdefault(item.outcome.value, []).append(f"{item.source_id}:{status}")
    return {
        "label": label,
        "started": result.started.astimezone(UTC).isoformat(),
        "seconds": round(result.seconds, 1),
        "sources": len(result.sources),
        "lanes": result.lanes,
        "outcomes": result.counts(),
        "finished_p50": round(percentile(finished, 0.50), 1),
        "finished_p95": round(percentile(finished, 0.95), 1),
        "finished_max": round(max(finished, default=0.0), 1),
        "requests_paced": len(log.entries),
        "requests_sent": sum(sent.values()),
        "unpaced_keys": sorted(key for key in set(sent) | set(paced) if sent[key] != paced[key]),
        "violations": len(broken),
        "violation_lines": broken[:50],
        "robots_requests": sum(requests.values()),
        "robots_reads": sum(reads.values()),
        "robots_reads_max_per_origin": max(reads.values(), default=0),
        "robots_origins": dict(sorted(requests.items())),
        "robots_follow_ups": {
            origin: count - reads[origin]
            for origin, count in sorted(requests.items())
            if count > reads[origin]
        },
        "slowest_keys": [list(item) for item in slowest],
        "not_good": {key: sorted(value) for key, value in sorted(by_outcome.items())},
    }


def run_sweep(args: argparse.Namespace) -> int:  # pragma: no cover - reads the live network
    """Run ``snowlight live sweep``."""
    registry: Registry = load_registry(args.registry)
    ids = sorted(set(args.only) if args.only else due_sources(registry))
    due: list[Station] = [registry.stations[sid] for sid in ids if sid in registry.stations]
    sent: Counter[str] = Counter()

    def count(request: httpx.Request) -> None:
        sent[pace_key(str(request.url))] += 1

    http = make_client()
    http.event_hooks["request"] = [count]
    log = RequestLog()
    args.state.mkdir(parents=True, exist_ok=True)
    pool = live_pool(args.cache_dir, args.state, workers=args.workers, log=log, http=http)
    now = datetime.now(UTC).replace(microsecond=0)

    def read(station: Station, client: PoliteClient) -> RunResult:
        return read_station(registry, station, client, now)

    origin = time.monotonic()
    try:
        result = pool.run_pass(due, read)
    finally:
        http.close()
    log.write(args.log, origin=origin, sweep=args.label)
    found = report(result, log, sent, label=str(args.label))
    text = json.dumps(found, indent=2, sort_keys=True) + "\n"
    write_bytes_atomic(args.report, text.encode("utf-8"))
    sys.stdout.write(
        f"sweep {args.label}: {len(due)} sources in {found['seconds']} s, "
        f"p95 finish {found['finished_p95']} s, {found['requests_paced']} requests, "
        f"{found['violations']} pacing violations, {found['robots_reads']} robots reads "
        f"({found['robots_requests']} requests), "
        f"outcomes {found['outcomes']}\n"
    )
    return 0 if found["violations"] == 0 and not found["unpaced_keys"] else 1


def add_parser(
    actions: "argparse._SubParsersAction[argparse.ArgumentParser]", registry: Path
) -> None:
    """Register ``live sweep``."""
    sweep = actions.add_parser("sweep", help="one measured pool pass over every active source")
    sweep.add_argument("--registry", type=Path, default=registry)
    sweep.add_argument("--cache-dir", type=Path, required=True, help="conditional bodies")
    sweep.add_argument("--state", type=Path, required=True, help="robots.json folder")
    sweep.add_argument("--log", type=Path, required=True, help="request log (JSON lines)")
    sweep.add_argument("--report", type=Path, required=True, help="the sweep's report")
    sweep.add_argument("--label", type=int, default=1, help="the sweep's number in the log")
    sweep.add_argument("--workers", type=int, default=WORKERS)
    sweep.add_argument("--only", nargs="*", default=(), help="sweep only these source ids")
    sweep.set_defaults(handler=run_sweep)

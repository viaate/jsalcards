"""The live reader's alerts (S8-E section 4): where each goes depends on the mode.

**Kinds** (:class:`Kind`): ``gate`` (2 refused passes in a row; clears when a pass
publishes), ``health`` (healthy share under 60% for 3 passes in a row; clears after 2 passes
at 60% or more),
``source`` (a daily digest of the sources erroring 3 hours or more inside their windows that
were not erroring in the 24 hours before), ``breaker`` (the breaker or the spike hold fired;
clears after 2 clean passes), ``edition`` (a mismatch, a blank, an unreadable deployment, or
code ahead of the deploy for 15 minutes; clears when the handshake is good), ``cold`` (at
least 20 candidate rows and over 25% ``unknown_start`` in a morning window; clears when the
window ends), ``state`` (pull or push failed, the swap lost, overrides-only, the write cap,
packed state over 12 MB), ``chain`` (2 runs in a row exited 1, or a successor dispatch failed
3 times; raised by a workflow step), ``timer`` (no live-ingest run created in 15 minutes), and
``stale`` (the watch job in live-ingest.yml).

**Where they go.**

* ``shadow`` (:class:`ShadowSink`): **no issue is ever opened**, so the owner gets no email.
  Each open and close is recorded in ``v1-shadow/live/alerts.json`` (one commit per change:
  kinds, UTC times, codes, counts, registry ids) and printed as one ``::warning::`` annotation
  (at most :data:`ANNOTATIONS` per process, under the 10-per-step cap; later ones are plain
  lines).
* ``on`` and ``off`` (:class:`IssueSink`): one open issue per kind and prefix, labelled
  ``live-alert`` (created if missing) and found by its body marker
  ``<!-- live-alert:<kind>:<prefix> -->``; at most one comment an hour; closed with
  "recovered at HH:MMZ". While ``state`` or ``stale`` is open, ``gate``, ``health``,
  ``source``, ``cold`` and ``chain`` add one comment to it instead of opening their own
  (root cause first). ``alerts.json`` is kept under the prefix the reader writes.

Bodies, titles, comments, annotations and ``alerts.json`` carry kinds, UTC times, counts,
codes, registry ids and the run link with a docs/live.md anchor; **never** listing text, a
school, district or person name, an email, a token, a URL other than the run's, or a
response body (:func:`clean`). An answer's body is never logged.
"""

import json
import logging
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol
from zoneinfo import ZoneInfo

import httpx

from snowlight.live.publishers import Publisher, PublishError
from snowlight.output import JSONValue, dumps_json

LOG: Final = logging.getLogger(__name__)

ALERTS: Final = "live/alerts.json"
LABEL: Final = "live-alert"
ANNOTATIONS: Final = 8
COMMENT_EVERY: Final = timedelta(hours=1)
ROOT_CAUSES: Final = ("state", "stale")
FOLLOWERS: Final = frozenset({"gate", "health", "source", "cold", "chain"})
DOCS: Final = "docs/live.md#alerts"
HISTORY: Final = 50
"""Closed alerts kept in ``alerts.json`` (the newest)."""
_SAFE: Final = re.compile(r"[A-Za-z0-9_.:+\-]{0,120}")
"""What a detail key must be (a code)."""
_SOURCE: Final = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")
"""A registry id (``gray-kwch``): lowercase words joined by hyphens, never one word."""
_EXITS: Final = re.compile(r"-?\d{1,3}(?:--?\d{1,3}){0,4}")
_ENUMS: Final = {
    "edition": frozenset(
        {"equal", "kept", "different", "none_deployed", "unreadable", "ahead", "blank"}
    ),
    "why": frozenset(
        {
            "lost",
            "write_cap",
            "push",
            "end_push",
            "overrides_only",
            "size",
            "plan",
            "unreadable",
            "cold",
        }
    ),
}
"""The detail keys whose value is one of a fixed set of codes."""
_COUNTS: Final = frozenset({"healthy_permille", "candidates", "unknown_start", "count"})
_PATTERNS: Final = {"exits": _EXITS}
_LISTS: Final = {"sources": _SOURCE}
"""The detail keys whose value is a list, each item matching its pattern."""


class Kind(StrEnum):
    GATE = "gate"
    HEALTH = "health"
    SOURCE = "source"
    BREAKER = "breaker"
    EDITION = "edition"
    COLD = "cold"
    STATE = "state"
    CHAIN = "chain"
    TIMER = "timer"
    STALE = "stale"


type Detail = Mapping[str, int | str | Sequence[str]]


def clean(detail: Detail) -> dict[str, JSONValue]:
    """``detail`` with only the keys an alert may carry, each value checked against its own
    rule: a count (an integer), one of a fixed set of codes, the exits pattern, or a list of
    registry ids. Any other key or value is dropped, so no listing text, name (one word or
    several), URL or body can reach an alert, whatever a caller passes.

    Raises:
        ValueError: a key is not a code.
    """
    found: dict[str, JSONValue] = {}
    for key, value in detail.items():
        if not _SAFE.fullmatch(key):
            raise ValueError("an alert detail key is not a code")
        if key in _COUNTS:
            if isinstance(value, int) and not isinstance(value, bool):
                found[key] = int(value)
        elif key in _ENUMS:
            if isinstance(value, str) and value in _ENUMS[key]:
                found[key] = value
        elif key in _PATTERNS:
            if isinstance(value, str) and _PATTERNS[key].fullmatch(value):
                found[key] = value
        elif key in _LISTS and not isinstance(value, (str, int)):
            found[key] = [str(item) for item in value if _LISTS[key].fullmatch(str(item))]
    return found


def _when(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(slots=True)
class Open:
    """An alert open now."""

    kind: str
    opened: datetime
    detail: dict[str, JSONValue]
    commented: datetime | None = None


class Sink(Protocol):
    """Where alert changes go."""

    def opened(self, alert: Open, book: "AlertBook") -> None: ...

    def updated(self, alert: Open, book: "AlertBook") -> None: ...

    def closed(self, alert: Open, at: datetime, book: "AlertBook") -> None: ...


@dataclass(slots=True)
class AlertBook:
    """The open alerts of one process and the history it records (see the module)."""

    sink: Sink
    prefix: str
    run_url: str = ""
    open: dict[str, Open] = field(default_factory=dict)
    history: list[dict[str, JSONValue]] = field(default_factory=list)

    def set(
        self, kind: Kind | str, active: bool, now: datetime, detail: Detail | None = None
    ) -> None:
        """Open ``kind`` (or keep it open, updating its detail) when ``active``, else close
        it when open. A failing sink is logged by the error's type; the book keeps its
        state, so the next change is tried again."""
        name = str(Kind(kind))
        found = self.open.get(name)
        try:
            if active and found is None:
                alert = Open(name, now, clean(detail or {}))
                self.open[name] = alert
                self.sink.opened(alert, self)
            elif active and found is not None:
                fresh = clean(detail or {})
                if fresh != found.detail:
                    found.detail = fresh
                    self.sink.updated(found, self)
            elif not active and found is not None:
                del self.open[name]
                self.history.append(
                    {
                        "kind": name,
                        "opened": _when(found.opened),
                        "closed": _when(now),
                        **found.detail,
                    }
                )
                self.history = self.history[-HISTORY:]
                self.sink.closed(found, now, self)
        except Exception as error:
            LOG.error("alert %s: %s", name, type(error).__name__)

    def document(self, now: datetime) -> dict[str, JSONValue]:
        """``alerts.json``: the open alerts and the recent closed ones (codes only)."""
        return {
            "schema_version": 1,
            "generated_at": _when(now),
            "prefix": self.prefix,
            "open": [
                {"kind": alert.kind, "opened": _when(alert.opened), **alert.detail}
                for alert in sorted(self.open.values(), key=lambda item: item.kind)
            ],
            "closed": list(self.history),
        }


def annotate(level: str, text: str) -> None:
    """One workflow annotation line (stdout), flushed at once: a pipe buffers stdout, so a
    reader the watcher or a cancel ends would otherwise take its notices with it."""
    sys.stdout.write(f"::{level}::{text}\n")
    sys.stdout.flush()


@dataclass(slots=True)
class ShadowSink:
    """Shadow: ``alerts.json`` under the reader's prefix and one annotation per change, never
    an issue."""

    host: Publisher | None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    printed: int = 0
    write: bool = True

    def _say(self, text: str) -> None:
        if self.printed < ANNOTATIONS:
            annotate("warning", text)
        else:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
        self.printed += 1

    def record_change(self, book: AlertBook, what: str) -> None:
        if self.host is None or not self.write:
            return
        now = self.clock()
        if hasattr(self.host, "message"):
            self.host.message = f"live {book.prefix} alerts {what} {_when(now)}"
        try:
            self.host.write({f"{book.prefix}/{ALERTS}": dumps_json(book.document(now))})
        except PublishError as error:
            LOG.error("alerts.json: %s", error)

    def opened(self, alert: Open, book: AlertBook) -> None:
        self._say(f"live alert {alert.kind} opened at {_when(alert.opened)} ({book.prefix})")
        self.record_change(book, f"open {alert.kind}")

    def updated(self, alert: Open, book: AlertBook) -> None:
        del alert
        del book

    def closed(self, alert: Open, at: datetime, book: AlertBook) -> None:
        self._say(f"live alert {alert.kind} closed at {_when(at)} ({book.prefix})")
        self.record_change(book, f"close {alert.kind}")


def marker(kind: str, prefix: str) -> str:
    return f"<!-- live-alert:{kind}:{prefix} -->"


class IssueError(RuntimeError):
    """The issues API answered badly (its status only)."""


@dataclass(slots=True)
class Issues:
    """The repository's issues over ``GITHUB_TOKEN`` (``issues: write``)."""

    client: httpx.Client
    repository: str
    token: str = field(repr=False)
    api: str = "https://api.github.com"

    def _call(self, method: str, path: str, body: object = None) -> httpx.Response:
        try:
            response = self.client.request(
                method,
                f"{self.api}/repos/{self.repository}/{path}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=body,
                timeout=30.0,
            )
        except httpx.HTTPError as error:
            raise IssueError(
                f"{method} {path.split('?', maxsplit=1)[0]}: {type(error).__name__}"
            ) from error
        if response.status_code >= 400:  # noqa: PLR2004 - an HTTP error
            raise IssueError(
                f"{method} {path.split('?', maxsplit=1)[0]}: HTTP {response.status_code}"
            )
        return response

    def open_issues(self) -> list[dict[str, object]]:
        found = self._call("GET", f"issues?state=open&labels={LABEL}&per_page=100").json()
        return [item for item in found if isinstance(item, dict)] if isinstance(found, list) else []

    def ensure_label(self) -> None:
        try:
            self._call("GET", f"labels/{LABEL}")
        except IssueError:
            self._call("POST", "labels", {"name": LABEL, "color": "b60205"})

    def create(self, title: str, body: str) -> int:
        made = self._call(
            "POST", "issues", {"title": title, "body": body, "labels": [LABEL]}
        ).json()
        number = made.get("number") if isinstance(made, dict) else None
        if not isinstance(number, int):
            raise IssueError("POST issues: no number")
        return number

    def comment(self, number: int, body: str) -> None:
        self._call("POST", f"issues/{number}/comments", {"body": body})

    def close(self, number: int, body: str) -> None:
        self.comment(number, body)
        self._call("PATCH", f"issues/{number}", {"state": "closed", "state_reason": "completed"})


class IssueApi(Protocol):
    def open_issues(self) -> list[dict[str, object]]: ...

    def ensure_label(self) -> None: ...

    def create(self, title: str, body: str) -> int: ...

    def comment(self, number: int, body: str) -> None: ...

    def close(self, number: int, body: str) -> None: ...


@dataclass(slots=True)
class IssueSink:
    """``on`` and ``off``: issues (see the module), plus ``alerts.json`` when a host is given."""

    api: IssueApi
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    record: ShadowSink | None = None

    def _number(self, kind: str, prefix: str) -> int | None:
        tag = marker(kind, prefix)
        for issue in self.api.open_issues():
            body = issue.get("body")
            number = issue.get("number")
            if isinstance(body, str) and tag in body and isinstance(number, int):
                return number
        return None

    def _body(self, alert: Open, book: AlertBook) -> str:
        lines = [f"{marker(alert.kind, book.prefix)}", f"live alert `{alert.kind}` ({book.prefix})"]
        lines.append(f"opened at {_when(alert.opened)}")
        lines.extend(f"- {key}: {value}" for key, value in sorted(alert.detail.items()))
        if book.run_url:
            lines.append(f"run: {book.run_url}")
        lines.append(f"see {DOCS}")
        return "\n".join(lines)

    def _root(self, book: AlertBook) -> int | None:
        for kind in ROOT_CAUSES:
            if kind in book.open:
                number = self._number(kind, book.prefix)
                if number is not None:
                    return number
        return None

    def opened(self, alert: Open, book: AlertBook) -> None:
        if self.record is not None:
            self.record.write = True
            self.record.record_change(book, f"open {alert.kind}")
        root = self._root(book) if alert.kind in FOLLOWERS else None
        if root is not None:
            self.api.comment(root, f"also `{alert.kind}` since {_when(alert.opened)} (see {DOCS})")
            alert.commented = self.clock()
            return
        if self._number(alert.kind, book.prefix) is not None:
            return
        self.api.ensure_label()
        self.api.create(f"Live alert: {alert.kind} ({book.prefix})", self._body(alert, book))

    def updated(self, alert: Open, book: AlertBook) -> None:
        now = self.clock()
        if alert.commented is not None and now - alert.commented < COMMENT_EVERY:
            return
        number = self._number(alert.kind, book.prefix)
        if number is None:
            return
        details = ", ".join(f"{key} {value}" for key, value in sorted(alert.detail.items()))
        self.api.comment(number, f"still open at {_when(now)}: {details or 'no counts'}")
        alert.commented = now

    def closed(self, alert: Open, at: datetime, book: AlertBook) -> None:
        if self.record is not None:
            self.record.record_change(book, f"close {alert.kind}")
        number = self._number(alert.kind, book.prefix)
        if number is not None:
            self.api.close(number, f"recovered at {at.astimezone(UTC).strftime('%H:%MZ')}")


# The reader's conditions --------------------------------------------------------------------

MORNING_ZONES: Final = (
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
)
COLD_MIN_ROWS: Final = 20
COLD_SHARE: Final = 0.25
HEALTH_MIN: Final = 0.6
CLEAN_PASSES: Final = 2
HEALTH_PASSES: Final = 3
"""Passes in a row under :data:`HEALTH_MIN` before ``health`` opens. The share dips for a single
pass when a half-hour's sources come due together (31 such dips in the 48-hour soak, each over
by the next pass), which is no reading problem; a real one lasts."""
AHEAD_ALERT: Final = timedelta(minutes=15)
SOURCE_HOURS: Final = timedelta(hours=3)
SOURCE_BASELINE: Final = timedelta(hours=24)
DIGEST_HOUR: Final = 15
"""The UTC hour from which the day's source digest is made (after the morning windows)."""
TIMER_LATE: Final = timedelta(minutes=15)


def morning(now: datetime) -> bool:
    """Whether ``now`` is inside the 04:00-09:00 window of any of the four main zones."""
    return any(4 <= now.astimezone(ZoneInfo(zone)).hour < 9 for zone in MORNING_ZONES)  # noqa: PLR2004


@dataclass(slots=True)
class SourceErrors:
    """Each source's error spell (for the ``source`` digest): when it began, how long of it
    fell inside the source's windows, and when the source last erred before it."""

    spells: dict[str, tuple[datetime, float, datetime | None]] = field(default_factory=dict)
    last_error_end: dict[str, datetime] = field(default_factory=dict)

    def note(
        self, source_id: str, *, error: bool, boosted: bool, now: datetime, step: timedelta
    ) -> None:
        spell = self.spells.get(source_id)
        if error:
            if spell is None:
                self.spells[source_id] = (now, 0.0, self.last_error_end.get(source_id))
            else:
                began, windowed, before = spell
                self.spells[source_id] = (
                    began,
                    windowed + (step.total_seconds() if boosted else 0.0),
                    before,
                )
        elif spell is not None:
            del self.spells[source_id]
            self.last_error_end[source_id] = now

    def digest(self) -> list[str]:
        """The sources erring 3 hours or more inside their windows that had not erred in the
        24 hours before their spell began."""
        return sorted(
            source_id
            for source_id, (began, windowed, before) in self.spells.items()
            if windowed >= SOURCE_HOURS.total_seconds()
            and (before is None or began - before >= SOURCE_BASELINE)
        )


@dataclass(slots=True)
class ReaderAlerts:
    """Turns each pass of the reader into alert changes (see the module)."""

    book: AlertBook
    good_health: int = 0
    bad_health: int = 0
    clean: int = 0
    ahead_since: datetime | None = None
    errors: SourceErrors = field(default_factory=SourceErrors)
    digest_day: str | None = None

    def after_pass(  # noqa: PLR0913 - one pass's parts
        self,
        now: datetime,
        *,
        published: bool,
        refused_alert: bool,
        share: float | None,
        breaker: bool,
        edition: str,
        ahead: bool,
        resolve_counts: Mapping[str, int],
    ) -> None:
        book = self.book
        book.set(Kind.GATE, refused_alert and not published, now, {"edition": edition})
        if share is not None:
            if share < HEALTH_MIN:
                self.good_health = 0
                self.bad_health += 1
                if self.bad_health >= HEALTH_PASSES:
                    book.set(Kind.HEALTH, True, now, {"healthy_permille": round(share * 1000)})
            else:
                self.bad_health = 0
                self.good_health += 1
                if self.good_health >= CLEAN_PASSES:
                    book.set(Kind.HEALTH, False, now)
        if breaker:
            self.clean = 0
            book.set(Kind.BREAKER, True, now)
        else:
            self.clean += 1
            if self.clean >= CLEAN_PASSES:
                book.set(Kind.BREAKER, False, now)
        self.edition(now, edition, ahead=ahead)
        kept = int(resolve_counts.get("kept", 0))
        unknown = int(resolve_counts.get("withheld:unknown_start", 0))
        candidates = kept + unknown
        cold = morning(now) and candidates >= COLD_MIN_ROWS and unknown > COLD_SHARE * candidates
        if cold or not morning(now):
            book.set(Kind.COLD, cold, now, {"candidates": candidates, "unknown_start": unknown})

    def edition(self, now: datetime, state: str, *, ahead: bool, blank: bool = False) -> None:
        """The handshake's verdict (each pass and each 60-s check)."""
        if ahead:
            self.ahead_since = self.ahead_since or now
            if now - self.ahead_since >= AHEAD_ALERT:
                self.book.set(Kind.EDITION, True, now, {"edition": "ahead"})
            return
        self.ahead_since = None
        if state in {"equal", "kept"} and not blank:
            self.book.set(Kind.EDITION, False, now)
        elif state in {"different", "unreadable", "none_deployed"} or blank:
            self.book.set(Kind.EDITION, True, now, {"edition": state})

    def sources(
        self, now: datetime, outcomes: Mapping[str, tuple[bool, bool]], step: timedelta
    ) -> None:
        """Each source read this pass: ``(erred, in a window or alert)``; once a day after
        :data:`DIGEST_HOUR` UTC the digest opens or closes ``source``."""
        for source_id, (erred, boosted) in outcomes.items():
            self.errors.note(source_id, error=erred, boosted=boosted, now=now, step=step)
        day = now.astimezone(UTC).date().isoformat()
        if now.astimezone(UTC).hour >= DIGEST_HOUR and self.digest_day != day:
            self.digest_day = day
            found = self.errors.digest()
            self.book.set(Kind.SOURCE, bool(found), now, {"sources": found, "count": len(found)})


def timer_late(latest: datetime | None, now: datetime) -> bool:
    """Whether the owner's timer is late: no live-ingest run created in 15 minutes."""
    return latest is None or now - latest > TIMER_LATE


def latest_ingest_run(
    client: httpx.Client, repository: str, token: str
) -> datetime | None:  # pragma: no cover - GitHub's API
    """When the newest live-ingest run was created (``None`` when it cannot be read)."""
    try:
        response = client.get(
            f"https://api.github.com/repos/{repository}/actions/workflows/live-ingest.yml/runs",
            params={"per_page": "1"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=20.0,
        )
        runs = (
            response.json().get("workflow_runs") if response.status_code == httpx.codes.OK else None
        )
        created = runs[0].get("created_at") if isinstance(runs, list) and runs else None
        return (
            None
            if not isinstance(created, str)
            else datetime.fromisoformat(created.replace("Z", "+00:00"))
        )
    except (httpx.HTTPError, ValueError, AttributeError):
        return None


def book_for(  # noqa: PLR0913 - the mode's parts
    mode: str,
    prefix: str,
    *,
    host: Publisher | None,
    issues: IssueApi | None,
    run_url: str = "",
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AlertBook:
    """The alert book of a mode: shadow writes ``alerts.json`` and annotations only; on and off
    open issues (when an issues API is given) and keep ``alerts.json`` under ``prefix``."""
    record = ShadowSink(host, clock)
    if mode == "shadow" or issues is None:
        return AlertBook(record, prefix, run_url)
    return AlertBook(IssueSink(issues, clock, record), prefix, run_url)


def load_book(book: AlertBook, data: bytes | None) -> None:
    """Take the open alerts and history from a published ``alerts.json`` (a successor goes on
    with them: an alert open when the last run ended stays one alert)."""
    if data is None:
        return
    try:
        document = json.loads(data)
        for entry in document.get("open", []):
            kind = str(entry["kind"])
            opened = datetime.fromisoformat(str(entry["opened"]).replace("Z", "+00:00"))
            detail = {key: value for key, value in entry.items() if key not in {"kind", "opened"}}
            book.open[str(Kind(kind))] = Open(kind, opened, clean(detail))
        book.history = [entry for entry in document.get("closed", []) if isinstance(entry, dict)][
            -HISTORY:
        ]
    except (ValueError, KeyError, TypeError, AttributeError):
        LOG.warning("alerts.json does not read; starting with no open alert")

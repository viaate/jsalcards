"""The live reader's alerts (S8-E section 4). SYNTHETIC hosts, issues and names.

* shadow: ``alerts.json`` and one annotation per change, never an issue;
* on and off: one issue per kind and prefix found by its marker, at most one comment an
  hour, closed with "recovered at", and root cause first while ``state`` or ``stale`` is open;
* T15a: synthetic names put through every path reach no title, body, comment,
  ``alerts.json``, annotation or commit message;
* the reader's conditions: gate, health, breaker, edition (code ahead for 15 minutes), cold,
  the source digest, the timer.
"""

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from snowlight.live.alerts import (
    ALERTS,
    ANNOTATIONS,
    AlertBook,
    IssueSink,
    Kind,
    ReaderAlerts,
    ShadowSink,
    book_for,
    clean,
    load_book,
    marker,
    timer_late,
)
from snowlight.live.publishers import DirPublisher

NOW = datetime(2026, 11, 17, 12, 5, tzinfo=UTC)  # 06:05 Central: a morning window
SYNTHETIC_NAMES = (
    "SYNTHETIC Alpha School",
    "Closed due to snow",
    "person@example.com",
    "Zyxwopple",  # a one-word name, as a school or a person may have
)


@dataclass
class Host:
    root: Path
    message: str = ""
    messages: list[str] = field(default_factory=list)

    def read(self, key: str) -> bytes | None:
        return DirPublisher(self.root).read(key)

    def write(self, files: Mapping[str, bytes]) -> None:
        self.messages.append(self.message)
        DirPublisher(self.root).write(files)


@dataclass
class FakeIssues:
    issues: dict[int, dict[str, object]] = field(default_factory=dict)
    comments: list[tuple[int, str]] = field(default_factory=list)
    labels: int = 0

    def open_issues(self) -> list[dict[str, object]]:
        return [issue for issue in self.issues.values() if issue["state"] == "open"]

    def ensure_label(self) -> None:
        self.labels += 1

    def create(self, title: str, body: str) -> int:
        number = len(self.issues) + 1
        self.issues[number] = {"number": number, "title": title, "body": body, "state": "open"}
        return number

    def comment(self, number: int, body: str) -> None:
        self.comments.append((number, body))

    def close(self, number: int, body: str) -> None:
        self.comment(number, body)
        self.issues[number]["state"] = "closed"


@dataclass
class Clock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


def test_shadow_writes_alerts_json_and_annotations_never_an_issue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = Host(tmp_path)
    issues = FakeIssues()
    book = book_for("shadow", "v1-shadow", host=host, issues=issues)
    book.set(Kind.GATE, True, NOW, {"edition": "equal"})
    book.set(Kind.GATE, True, NOW + timedelta(minutes=5), {"edition": "equal"})  # unchanged
    book.set(Kind.GATE, False, NOW + timedelta(minutes=10))
    assert issues.issues == {}
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "::warning::live alert gate opened at 2026-11-17T12:05:00Z (v1-shadow)",
        "::warning::live alert gate closed at 2026-11-17T12:15:00Z (v1-shadow)",
    ]
    document = json.loads((tmp_path / "v1-shadow" / ALERTS).read_bytes())
    assert document["open"] == []
    assert document["closed"] == [
        {
            "kind": "gate",
            "opened": "2026-11-17T12:05:00Z",
            "closed": "2026-11-17T12:15:00Z",
            "edition": "equal",
        }
    ]
    assert len(host.messages) == 2  # one commit per change
    assert host.messages[0].startswith("live v1-shadow alerts open gate ")


def test_annotations_stay_under_the_step_cap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    book = book_for("shadow", "v1-shadow", host=Host(tmp_path), issues=None)
    for step in range(12):
        book.set(Kind.HEALTH, step % 2 == 0, NOW + timedelta(minutes=step))
    lines = capsys.readouterr().out.splitlines()
    assert sum(line.startswith("::warning::") for line in lines) == ANNOTATIONS
    assert len(lines) == 12


def test_on_opens_one_issue_per_kind_throttles_comments_and_closes(tmp_path: Path) -> None:
    clock = Clock()
    issues = FakeIssues()
    book = AlertBook(
        IssueSink(issues, clock, ShadowSink(Host(tmp_path), clock)),
        "v1",
        "https://github.com/synthetic/run/1",
    )
    book.set(Kind.HEALTH, True, NOW, {"healthy_permille": 410})
    assert len(issues.issues) == 1
    issue = issues.issues[1]
    assert marker("health", "v1") in str(issue["body"])
    assert "docs/live.md#alerts" in str(issue["body"])
    # a changed count comments at most once an hour
    for minutes, permille in ((5, 400), (10, 390), (65, 380)):
        clock.now = NOW + timedelta(minutes=minutes)
        book.set(Kind.HEALTH, True, clock.now, {"healthy_permille": permille})
    assert [number for number, _ in issues.comments] == [1, 1]
    # a new process finds the open issue by its marker and opens no second one
    again = AlertBook(IssueSink(issues, clock), "v1")
    again.set(Kind.HEALTH, True, clock.now)
    assert len(issues.issues) == 1
    clock.now = NOW + timedelta(hours=2)
    book.set(Kind.HEALTH, False, clock.now)
    assert issues.issues[1]["state"] == "closed"
    assert issues.comments[-1] == (1, "recovered at 14:05Z")
    assert (tmp_path / "v1" / ALERTS).is_file()  # kept under the prefix the reader writes


def test_root_cause_first(tmp_path: Path) -> None:
    del tmp_path
    issues = FakeIssues()
    book = AlertBook(IssueSink(issues, Clock()), "v1")
    book.set(Kind.STATE, True, NOW, {"why": "pull"})
    book.set(Kind.GATE, True, NOW)
    book.set(Kind.EDITION, True, NOW, {"edition": "different"})  # not a follower: its own issue
    assert [issue["title"] for issue in issues.issues.values()] == [
        "Live alert: state (v1)",
        "Live alert: edition (v1)",
    ]
    assert issues.comments == [
        (1, "also `gate` since 2026-11-17T12:05:00Z (see docs/live.md#alerts)")
    ]


def test_no_synthetic_name_reaches_any_alert_surface(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = Host(tmp_path)
    issues = FakeIssues()
    for mode in ("shadow", "on"):
        book = book_for(mode, "v1-shadow" if mode == "shadow" else "v1", host=host, issues=issues)
        for kind in Kind:
            book.set(
                kind,
                True,
                NOW,
                {
                    "note": SYNTHETIC_NAMES[0],
                    "sources": list(SYNTHETIC_NAMES),
                    "count": 3,
                    **dict.fromkeys(("edition", "why", "exits"), SYNTHETIC_NAMES[3]),
                },
            )
            book.set(kind, True, NOW + timedelta(hours=2), {"note": SYNTHETIC_NAMES[1]})
            book.set(kind, False, NOW + timedelta(hours=3))
    surfaces = [capsys.readouterr().out, *host.messages]
    surfaces += [str(issue["title"]) + str(issue["body"]) for issue in issues.issues.values()]
    surfaces += [body for _, body in issues.comments]
    surfaces += [path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json")]
    text = "\n".join(surfaces)
    assert "count" in text
    for name in SYNTHETIC_NAMES:
        assert name not in text
    assert "SYNTHETIC" not in text


def test_clean_keeps_codes_and_counts_only() -> None:
    assert clean(
        {"edition": "different", "count": 4, "sources": ["gray-synthetic", "two words"]}
    ) == {
        "edition": "different",
        "count": 4,
        "sources": ["gray-synthetic"],
    }
    # a one-word name passes no rule: not an enum code, not a registry id, not a count
    assert clean({"edition": "Zyxwopple", "why": "Zyxwopple", "exits": "Zyxwopple"}) == {}
    assert clean({"sources": ["Zyxwopple", "zyxwopple", "gray-synthetic"]}) == {
        "sources": ["gray-synthetic"]
    }
    assert clean({"note": "Zyxwopple", "count": "Zyxwopple", "candidates": True}) == {}
    assert clean({"exits": "1-124", "why": "end_push"}) == {"exits": "1-124", "why": "end_push"}
    assert clean({"note": "SYNTHETIC Alpha School"}) == {}
    assert clean({"url": "https://example.com/a?b"}) == {}
    with pytest.raises(ValueError, match="not a code"):
        clean({"a key": 1})


def _reader(tmp_path: Path) -> tuple[ReaderAlerts, AlertBook]:
    book = book_for("shadow", "v1-shadow", host=Host(tmp_path), issues=None)
    return ReaderAlerts(book), book


def _pass(alerts: ReaderAlerts, now: datetime, **overrides: object) -> None:
    values: dict[str, object] = {
        "published": True,
        "refused_alert": False,
        "share": 1.0,
        "breaker": False,
        "edition": "equal",
        "ahead": False,
        "resolve_counts": {},
    }
    values.update(overrides)
    alerts.after_pass(now, **values)  # type: ignore[arg-type]


def test_the_reader_conditions(tmp_path: Path) -> None:
    alerts, book = _reader(tmp_path)
    _pass(alerts, NOW, published=False, refused_alert=True, share=0.4)
    assert set(book.open) == {"gate", "health"}
    _pass(alerts, NOW + timedelta(minutes=5), share=0.7)
    assert set(book.open) == {"health"}  # a pass that publishes clears gate; health needs 2
    _pass(alerts, NOW + timedelta(minutes=10), share=0.7)
    assert set(book.open) == set()
    _pass(alerts, NOW + timedelta(minutes=15), breaker=True)
    _pass(alerts, NOW + timedelta(minutes=20))
    assert "breaker" in book.open
    _pass(alerts, NOW + timedelta(minutes=25))
    assert "breaker" not in book.open


def test_code_ahead_alerts_after_15_minutes_and_clears_when_the_deploy_matches(
    tmp_path: Path,
) -> None:
    alerts, book = _reader(tmp_path)
    for minutes in (0, 5, 10):
        alerts.edition(NOW + timedelta(minutes=minutes), "different", ahead=True)
    assert "edition" not in book.open
    alerts.edition(NOW + timedelta(minutes=15), "different", ahead=True)
    assert book.open["edition"].detail == {"edition": "ahead"}
    alerts.edition(NOW + timedelta(minutes=16), "equal", ahead=False)
    assert "edition" not in book.open
    alerts.edition(NOW + timedelta(minutes=17), "different", ahead=False)
    assert "edition" in book.open


def test_cold_opens_in_a_morning_window_and_clears_when_it_ends(tmp_path: Path) -> None:
    alerts, book = _reader(tmp_path)
    _pass(alerts, NOW, resolve_counts={"kept": 5, "withheld:unknown_start": 12})  # under 20 rows
    assert "cold" not in book.open
    _pass(alerts, NOW, resolve_counts={"kept": 10, "withheld:unknown_start": 12})
    assert "cold" in book.open
    # it stays open through the window
    _pass(
        alerts, NOW + timedelta(minutes=5), resolve_counts={"kept": 20, "withheld:unknown_start": 1}
    )
    assert "cold" in book.open
    afternoon = datetime(2026, 11, 17, 19, tzinfo=UTC)  # 13:00 Central, 11:00 Pacific
    _pass(alerts, afternoon, resolve_counts={"kept": 10, "withheld:unknown_start": 12})
    assert "cold" not in book.open


def test_the_source_digest(tmp_path: Path) -> None:
    alerts, book = _reader(tmp_path)
    step = timedelta(minutes=5)
    start = datetime(2026, 11, 17, 9, tzinfo=UTC)
    moment = start
    while moment < start + timedelta(hours=4):  # 4 hours erring, inside the windows
        alerts.sources(moment, {"gray-synthetic": (True, True), "gray-fine": (False, True)}, step)
        moment += step
    alerts.sources(datetime(2026, 11, 17, 15, tzinfo=UTC), {"gray-synthetic": (True, True)}, step)
    assert book.open["source"].detail == {"sources": ["gray-synthetic"], "count": 1}
    # the next day's digest has none: closed
    alerts.sources(datetime(2026, 11, 17, 16, tzinfo=UTC), {"gray-synthetic": (False, True)}, step)
    alerts.sources(datetime(2026, 11, 18, 15, tzinfo=UTC), {}, step)
    assert "source" not in book.open


def test_a_source_that_erred_the_day_before_is_not_new(tmp_path: Path) -> None:
    alerts, book = _reader(tmp_path)
    step = timedelta(minutes=5)
    start = datetime(2026, 11, 17, 3, tzinfo=UTC)
    alerts.sources(start, {"gray-synthetic": (True, True)}, step)
    alerts.sources(start + step, {"gray-synthetic": (False, True)}, step)
    moment = start + timedelta(hours=1)
    while moment < start + timedelta(hours=6):
        alerts.sources(moment, {"gray-synthetic": (True, True)}, step)
        moment += step
    alerts.sources(datetime(2026, 11, 17, 15, tzinfo=UTC), {}, step)
    assert "source" not in book.open


def test_the_timer_and_a_successor_keep_the_open_alerts(tmp_path: Path) -> None:
    assert timer_late(None, NOW)
    assert timer_late(NOW - timedelta(minutes=16), NOW)
    assert not timer_late(NOW - timedelta(minutes=14), NOW)
    host = Host(tmp_path)
    book = book_for("shadow", "v1-shadow", host=host, issues=None)
    book.set(Kind.TIMER, True, NOW, {"minutes": 16})
    successor = book_for("shadow", "v1-shadow", host=host, issues=None)
    load_book(successor, host.read(f"v1-shadow/{ALERTS}"))
    assert set(successor.open) == {"timer"}
    successor.set(Kind.TIMER, True, NOW + timedelta(minutes=5), {"minutes": 16})
    assert len(host.messages) == 1  # still one alert, no new commit
    load_book(successor, b"{not json")


def test_a_notice_reaches_the_log_when_the_reader_is_killed() -> None:
    """stdout is a pipe on a runner, so it is block-buffered: an annotation or a status line
    printed before the watcher's or a cancel's kill must already be in the log."""
    code = (
        "import os, signal\n"
        "from snowlight.live.alerts import annotate, ShadowSink\n"
        "from snowlight.live.cli import _say\n"
        "annotate('notice', 'live-read first pass 2026-10-25T06:27:53Z')\n"
        "ShadowSink(host=None)._say('live v1-shadow alerts open gate')\n"
        "_say('pulse kept')\n"
        "os.kill(os.getpid(), signal.SIGKILL)\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    ran = subprocess.run(  # noqa: S603 - this interpreter, a fixed program
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    assert ran.returncode == -9
    assert ran.stdout.splitlines() == [
        "::notice::live-read first pass 2026-10-25T06:27:53Z",
        "::warning::live v1-shadow alerts open gate",
        "pulse kept",
    ]

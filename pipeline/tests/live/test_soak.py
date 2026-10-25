"""The soak report (S8-E E2, E3) on a SYNTHETIC history: commits every 5 minutes with a handoff,
a gap inside a GitHub incident (set apart) and one outside it, served times, live-read and
live-ingest runs with their annotations."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from snowlight.live.soak import Commit, History, Incident, Run, gaps, percentile, render, report

T0 = datetime(2026, 10, 31, 18, 0, tzinfo=UTC)


def _commit(
    at: datetime, run: int, *, sweep: int = 70, due: int = 40, state: int = 4_000_000
) -> Commit:
    start = (at - timedelta(seconds=sweep + 20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    message = (
        f"live v1-shadow pass {start} run {run} sweep {sweep} due {due} good {due} lit 0"
        f" state {state}"
    )
    return Commit(sha=f"{run}-{at.timestamp():.0f}", at=at, message=message)


def _noted(run: Run, *lines: str) -> Run:
    return replace(run, annotations=(*run.annotations, *lines))


def _history() -> History:
    history = History(T0, T0 + timedelta(hours=12))
    moment = T0 + timedelta(minutes=1, seconds=30)
    run = 101
    for index in range(140):
        if index == 60:
            run = 102  # the successor: one grid slot without a commit
            moment += timedelta(minutes=5)
        if index == 100:
            moment += timedelta(minutes=20)  # inside the incident below: set apart
        history.commits.append(_commit(moment, run))
        history.served[history.commits[-1].sha] = moment + timedelta(seconds=25)
        moment += timedelta(minutes=5)
    history.incidents.append(
        Incident(T0 + timedelta(hours=8, minutes=40), T0 + timedelta(hours=9), ("Actions",))
    )
    first_end = history.commits[59].at + timedelta(minutes=1)
    second_start = first_end + timedelta(minutes=1, seconds=40)
    summary = "live-read summary: exit {}; state bytes 4000000; d1 pushes 10; d1 rows today {}"
    history.runs = [
        Run(101, "live-read", T0, T0, first_end, "success", {"read": "success"},
            ("live-read exit 0: every pass published", summary.format(0, 1200))),
        Run(102, "live-read", second_start, second_start, T0 + timedelta(hours=12), "success",
            {"read": "success"}, ("live-read exit 3: a refused pass", summary.format(3, 2600))),
    ]  # fmt: skip
    for index in range(144):
        created = T0 + timedelta(minutes=5 * index, seconds=40 + (index % 3))
        history.runs.append(
            Run(
                9000 + index, "live-ingest", created, jobs={"reader": "success", "watch": "success"}
            )
        )
    history.other_commits = [Commit("p1", T0 + timedelta(hours=1), "predict pass")]
    history.served["p1"] = T0 + timedelta(hours=1, seconds=40)
    return history


def test_the_report_on_a_synthetic_history() -> None:
    found = report(_history())
    commits = found["gap_on_commits"]
    assert isinstance(commits, dict)
    assert commits["max_minutes"] == 10.0  # the handoff's missing slot
    assert commits["p95_minutes"] == 5.0
    assert commits["set_apart"] == [{"from": "2026-11-01T02:21:30+00:00", "minutes": 25.0}]
    assert commits["stale_minutes_by_day"] == {"2026-11-01": 10}
    served = found["gap_on_served_time"]
    assert isinstance(served, dict)
    assert served["max_minutes"] == 10.0
    assert found["sweep_due_p95_seconds"] == 70.0
    assert found["reader_commits_under_v1"] == 0
    assert found["live_read_exits"] == {"0": 1, "3": 1}
    assert found["d1_rows_by_day"] == {"2026-10-31": 1200, "2026-11-01": 2600}
    assert found["state_max_bytes"] == 4_000_000
    hand = found["handoffs"]
    assert isinstance(hand, dict)
    assert hand["boundaries"] == [
        {"at": _history().commits[60].at.isoformat(), "kind": "successor", "gap_minutes": 10.0}
    ]
    assert found["live_ingest_on_time"] == found["live_ingest_steps_outside_incidents"]
    assert found["served_delay_max_seconds"] == 40.0
    bars = found["bars"]
    assert isinstance(bars, dict)
    assert bars["gap_p95"] is True
    assert bars["gap_max"] is True
    assert bars["no_v1_commits"] is True
    assert bars["no_exit_1"] is True
    assert bars["successor_gap_max"] is False  # 10 minutes: over the 7-minute bar
    assert bars["ingest_jobs_green"] is True
    assert "SYNTHETIC" not in render(found)


def test_a_reader_commit_under_v1_and_an_exit_1_miss_their_bars() -> None:
    history = _history()
    history.v1_commits.append(_commit(T0 + timedelta(hours=2), 101))
    history.v1_commits.append(Commit("o1", T0 + timedelta(hours=2), "Publish the live files"))
    history.runs[0] = Run(
        101,
        "live-read",
        T0,
        T0,
        T0 + timedelta(hours=5),
        "success",
        {},
        ("live-read exit 1: a persistent failure",),
    )
    found = report(history)
    assert found["reader_commits_under_v1"] == 1  # the overrides job's own commit is not one
    bars = found["bars"]
    assert isinstance(bars, dict)
    assert bars["no_v1_commits"] is False
    assert bars["no_exit_1"] is False


def test_gaps_and_percentiles() -> None:
    assert percentile([], 0.95) is None
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    times = [T0, T0 + timedelta(minutes=5), T0 + timedelta(minutes=30)]
    pages = Incident(T0 + timedelta(minutes=40), T0 + timedelta(minutes=50), ("Pages",))
    other = Incident(T0 + timedelta(minutes=40), T0 + timedelta(minutes=50), ("Issues",))
    assert gaps(times, [pages])["max_minutes"] == 5.0  # the 25-minute gap is set apart
    assert gaps(times, [other])["max_minutes"] == 25.0  # an Issues incident does not count


def test_a_reader_dark_at_either_edge_of_the_window_counts_as_a_gap() -> None:
    times = [T0 + timedelta(minutes=minute) for minute in (20, 25, 30)]
    found = gaps(times, [], T0, T0 + timedelta(minutes=70))
    assert found["edges"] == {"start_minutes": 20.0, "end_minutes": 40.0}
    assert found["max_minutes"] == 40.0  # dark for the window's last 40 minutes
    assert found["count"] == 4
    dark = gaps([], [], T0, T0 + timedelta(hours=2))
    assert dark["max_minutes"] == 120.0  # no commit at all: the whole window is one gap
    outside = [T0 - timedelta(minutes=5), *times]  # a time outside the window is left out
    assert gaps(outside, [], T0, T0 + timedelta(minutes=70))["edges"] == found["edges"]


def test_cold_start_comes_from_the_first_pass_notice_when_the_first_upload_is_skipped() -> None:
    """A successor's first pass (about G+3.9) skips an unchanged upload by design, so its
    first commit is the G+5 grid pass: the cold start is read from the loop's notice."""
    history = _history()
    new = history.runs[1]
    assert new.started is not None
    notice = f"live-read first pass {(new.started + timedelta(seconds=95)).isoformat()}"
    history.runs[1] = _noted(new, notice)
    hand = report(history)["handoffs"]
    assert isinstance(hand, dict)
    assert hand["cold_start_max_seconds"] == 95.0
    # without the notice, the first commit's pass start is all there is (and it is later)
    fallback = report(_history())["handoffs"]
    assert isinstance(fallback, dict)
    assert isinstance(fallback["cold_start_max_seconds"], float)
    assert fallback["cold_start_max_seconds"] > 95.0


def test_reader_commits_under_v1_are_found_by_message_and_run_id() -> None:
    history = _history()
    stamp = "2026-10-31T20:00:00Z"
    history.v1_commits += [
        Commit("b1", T0 + timedelta(hours=2), f"live v1 blank {stamp} run 101", "v1/live"),
        Commit("a1", T0 + timedelta(hours=2), f"live v1 alerts open {stamp}", "v1/live"),
        Commit("d1", T0 + timedelta(hours=3), "Publish the live files (live-read run 102)"),
        Commit("o1", T0 + timedelta(hours=3), "Publish the live files"),
        Commit("o2", T0 + timedelta(hours=4), f"live v1 blank {stamp} run -"),
        Commit("o3", T0 + timedelta(hours=4), "Publish the live files (live-ingest run 9001)"),
    ]
    found = report(history)
    assert found["reader_commits_under_v1"] == 3
    assert found["reader_commits_under_v1_shas"] == ["b1", "a1", "d1"]
    bars = found["bars"]
    assert isinstance(bars, dict)
    assert bars["no_v1_commits"] is False


def test_a_superseded_deployment_is_served_by_the_next_one() -> None:
    from snowlight.live.soak import served_times  # noqa: PLC0415

    at = T0 + timedelta(minutes=1)
    own = {"c2": at + timedelta(seconds=70), "c4": at + timedelta(seconds=30)}
    served = served_times(["c1", "c2", "c3", "c4", "c5"], own)
    assert served == {"c1": own["c4"], "c2": own["c4"], "c3": own["c4"], "c4": own["c4"]}
    assert served_times([], own) == own


def test_boundaries_carry_their_type() -> None:
    from snowlight.live.soak import boundary_kind  # noqa: PLC0415

    end = T0 + timedelta(hours=5)
    after = Run(2, "live-read", end, end + timedelta(minutes=2))
    late = Run(3, "live-read", end, end + timedelta(minutes=20))

    def old(conclusion: str = "success", *lines: str) -> Run:
        return Run(1, "live-read", T0, T0, end, conclusion, {}, lines)

    assert boundary_kind(None, after) == "restart"
    assert boundary_kind(old("cancelled"), after) == "mode change"
    assert boundary_kind(old("failure", "live-read exit 124: killed"), after) == (
        "restart after a kill"
    )
    assert boundary_kind(old("success", "live-read exit 1: x"), after) == "restart after exit 1"
    assert boundary_kind(old("success", "live-read end edition"), after) == "edition stop"
    assert boundary_kind(old("success", "live-read end until"), after) == "successor"
    assert boundary_kind(old("success", "live-read end until"), late) == "restart"


def test_token_peak_cache_restores_and_host_growth() -> None:
    history = _history()
    reset = int((T0 + timedelta(hours=1)).timestamp())
    history.runs[2] = _noted(history.runs[2], f"github token used 410 of 1000 reset {reset}")
    history.runs[3] = _noted(history.runs[3], f"github token used 640 of 1000 reset {reset}")
    history.runs[0] = _noted(
        history.runs[0], "live host size 42000 KB", "live-read caches restored 300000000 bytes"
    )
    history.runs[1] = _noted(
        history.runs[1], "live host size 46000 KB", "live-read caches restored 200000000 bytes"
    )
    found = report(history)
    assert found["github_token_hourly_peak"] == 640
    bars = found["bars"]
    assert isinstance(bars, dict)
    assert bars["token_hourly_peak"] is False
    assert found["cache_restores_gb_by_day"] == {"2026-10-31": 0.5}
    growth = found["live_host_growth"]
    assert isinstance(growth, dict)
    assert growth["first_kb"] == 42000
    assert growth["last_kb"] == 46000
    assert isinstance(growth["kb_per_day"], float)
    assert growth["kb_per_day"] > 0


def test_fetch_history_reads_the_paths_the_report_needs() -> None:
    """The commits of the shadow file, every live file under v1/ and predict's file, the whole
    host's commit order and its deployments, on a stub of the public API."""
    import httpx  # noqa: PLC0415

    from snowlight.live.soak import COMMIT_PATHS, fetch_history  # noqa: PLC0415

    asked: list[str | None] = []
    at = "2026-10-31T19:00:00Z"

    def commit(sha: str, message: str) -> dict[str, object]:
        return {"sha": sha, "commit": {"message": message, "committer": {"date": at}}}

    by_path = {
        "v1-shadow/live/closings.json": [commit("s1", "live v1-shadow pass x")],
        "v1/live": [commit("o1", "Publish the live files")],
        "v1/predictions/latest.json": [commit("p1", "Publish the predictions")],
        "v1-shadow/live/alerts.json": [
            commit("a1", "live v1-shadow alerts open gate 2026-10-31T19:00:00Z")
        ],
        None: [commit("p1", "a"), commit("o1", "b"), commit("s1", "c")],
    }
    jobs_asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:  # noqa: PLR0911 - one stub API
        url = request.url
        page = url.params.get("page", "1")
        if url.path.endswith("/commits"):
            path = url.params.get("path")
            if page == "1":
                asked.append(path)
            return httpx.Response(200, json=by_path[path] if page == "1" else [])
        if url.path.endswith("/deployments"):
            body = [{"sha": "s1", "created_at": at, "statuses_url": "https://api.github.com/s"}]
            return httpx.Response(200, json=body if page == "1" else [])
        if url.path == "/s":
            return httpx.Response(
                200, json=[{"state": "success", "created_at": "2026-10-31T19:00:40Z"}]
            )
        if url.path.endswith("/runs"):
            name = url.path.split("/")[-2].removesuffix(".yml")
            if name == "live-read" or page != "1":
                return httpx.Response(200, json={"workflow_runs": []})
            jobs_url = f"https://api.github.com/jobs/{name}"
            run = {
                "id": 5 if name == "live-ingest" else 6,
                "created_at": at,
                "conclusion": "success",
                "jobs_url": jobs_url,
            }
            return httpx.Response(200, json={"workflow_runs": [run]})
        if url.path.startswith("/jobs/"):
            names = ("reader", "watch", "check") if url.path.endswith("ingest") else ("drill",)
            jobs = [{"id": index, "name": name, "started_at": at, "conclusion": "success"}
                    for index, name in enumerate(names)]  # fmt: skip
            return httpx.Response(200, json={"jobs": jobs})
        if url.path.endswith("/annotations"):
            jobs_asked.append(url.path.split("/")[-2])
            return httpx.Response(200, json=[{"message": "live watch: x"}])
        return httpx.Response(200, json={"incidents": []})

    with httpx.Client(transport=httpx.MockTransport(answer)) as client:
        history = fetch_history(client, T0, T0 + timedelta(hours=2))
    assert asked == [*COMMIT_PATHS, None]
    assert "v1/predictions/latest.json" in COMMIT_PATHS
    assert [commit.sha for commit in history.other_commits] == ["p1"]
    assert [commit.sha for commit in history.alert_commits] == ["a1"]
    # the reader's and the watch job's annotations, and the drill's; never check's
    assert sorted(jobs_asked) == ["0", "0", "1"]
    assert {run.workflow for run in history.runs} == {"live-ingest", "live-drill"}
    assert history.order == ["p1", "o1", "s1"]
    found = report(history)
    # predict's and the overrides job's commits are served by the later shadow deployment
    assert found["served_delay_commits"] == 2
    assert found["served_delay_max_seconds"] == 40.0


def _drill_history() -> History:
    """A SYNTHETIC stall drill and gate drill: shadow commits every 5 minutes but while the
    reader is stopped, the watch job's annotations, the alerts.json changes, the drill's
    notices."""
    history = History(T0, T0 + timedelta(hours=3))
    disabled = T0 + timedelta(minutes=20)
    enabled = disabled + timedelta(minutes=36)
    moment = T0 + timedelta(minutes=1, seconds=30)
    while moment < history.until:
        if not disabled <= moment <= enabled + timedelta(minutes=3):
            history.commits.append(_commit(moment, 101 if moment < disabled else 102))
        moment += timedelta(minutes=5)
    for index in range(36):
        created = T0 + timedelta(minutes=5 * index, seconds=40)
        stale = disabled + timedelta(minutes=17) <= created <= enabled + timedelta(minutes=6)
        notes = ("live watch: the served v1-shadow file is stale (1100 s old)",) if stale else ()
        history.runs.append(
            Run(9000 + index, "live-ingest", created, created + timedelta(seconds=5), None,
                "success", {"reader": "success", "watch": "success"}, notes)
        )  # fmt: skip
    history.runs.append(
        Run(102, "live-read", enabled + timedelta(seconds=95), enabled + timedelta(seconds=100))
    )
    blank = T0 + timedelta(hours=2)
    release = blank + timedelta(minutes=14)
    stamp = "%Y-%m-%dT%H:%M:%SZ"
    history.runs.append(
        Run(7001, "live-drill", disabled, annotations=(
            f"live-drill stall disabled {disabled.strftime(stamp)}",
            f"live-drill stall enabled {enabled.strftime(stamp)}",
        ))
    )  # fmt: skip
    history.runs.append(
        Run(7002, "live-drill", blank, annotations=(
            f"live-drill gate blank {blank.strftime(stamp)}",
            "drill gate: the blank (generated_at x) committed at y (abc), served at z: 41 s,"
            " within the 60-s bar",
            f"live-drill gate release {release.strftime(stamp)}",
        ))
    )  # fmt: skip
    held = blank + timedelta(seconds=50)
    history.commits.append(Commit("h1", held, f"live-blank v1-shadow blank {held.strftime(stamp)}"))
    history.alert_commits = [
        Commit("a1", held + timedelta(minutes=11), "live v1-shadow alerts open gate x"),
        Commit("a2", release + timedelta(minutes=6), "live v1-shadow alerts close gate x"),
    ]
    return history


def _drills(history: History) -> list[dict[str, Any]]:
    found = report(history)["drills"]
    assert isinstance(found, list)
    return [cast("dict[str, Any]", item) for item in found]


def test_the_drills_are_measured_against_their_bars() -> None:
    stall, gate = _drills(_drill_history())
    assert stall["drill"] == "stall"
    assert stall["bars"] == {
        "stale_within_30": True,
        "reader_within_5": True,
        "stale_cleared_within_10": True,
        "live_ingest_green": True,
    }
    assert stall["reader_after_enable_minutes"] == 1.67
    assert gate["drill"] == "gate"
    assert gate["gate_open_after_minutes"] == 11.0
    assert gate["gate_cleared_after_minutes"] == 6.0
    assert gate["blank_served_seconds"] == 41
    assert all(gate["bars"].values())


def test_a_late_stale_a_slow_restart_and_a_red_run_miss_their_drill_bars() -> None:
    history = _drill_history()
    history.runs = [
        replace(run, conclusion="failure") if run.id == 9010 else run for run in history.runs
    ]
    history.runs = [
        replace(run, started=run.started + timedelta(minutes=6))
        if run.workflow == "live-read" and run.started
        else run
        for run in history.runs
    ]
    history.alert_commits = history.alert_commits[:1]
    stall, gate = _drills(history)
    assert stall["bars"]["reader_within_5"] is False
    assert stall["bars"]["live_ingest_green"] is False
    assert gate["bars"]["gate_cleared_within_10"] is False  # never cleared in the window
    history.until = T0 + timedelta(hours=2, minutes=20)
    _, gate = _drills(history)
    assert gate["bars"]["gate_cleared_within_10"] is None  # the window ends too soon to tell

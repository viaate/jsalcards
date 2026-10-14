"""The coverage gate's closure window, refused replays and the window's calibration.

A source's closure window is its closure days (storm days and the days a proven
whole-county list sharing one of its counties held a row) and the
:data:`~snowlight.sources.stations.gate.NEAR_DAYS` either side of each. Captures
made in the window are due; ``window_seen`` counts the distinct ones whose read
saw the list. A capture the archive answers 429 in several hours is the replay of
the site's refusal and counts as read (``refused``). :func:`gate.calibration`
measures, on the proven sources' own archived reads, how often a source in use
showed it in its window.

Everything here is synthetic (every URL is under .test).
"""

import json
from datetime import date
from pathlib import Path

import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.output import JSONValue
from snowlight.sources.stations import gate
from snowlight.sources.stations.archive import Capture, SnapshotRecord
from snowlight.sources.stations.model import ListingRead
from snowlight.sources.stations.registry import Registry, load_registry
from snowlight.sources.stations.storms import StormDays

U = "https://synthetic-u.test/closings"
U_KEY = "synthetic-u.test/closings"
TERMS = {
    "automated_access": "permitted",
    "summary": "synthetic",
    "evidence": [
        {
            "url": "https://x.test/t",
            "read_at": "2026-09-25T00:00:00Z",
            "sha256": None,
            "excerpt": ["ok"],
        }
    ],
}


def _station(sid: str, fips: list[str], **fields: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": sid,
        "platform": "synthetic",
        "call_sign": sid.split("-")[1].upper() + "XX",
        "name": sid,
        "market": "Kansas City",
        "dma": None,
        "states": ["MO"],
        "counties": {"basis": "dma", "source": "synthetic", "fips": fips},
        "page_url": f"https://{sid}.test/closings",
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": "active",
        "evidence": "synthetic",
    }
    entry.update(fields)
    return entry


def _registry(tmp_path: Path) -> Registry:
    """P and U: whole-county lists sharing 29095; Q: a district there; V: elsewhere."""
    folder = tmp_path / "sources"
    folder.mkdir()
    district = _station(
        "synthetic-q",
        ["29095"],
        counties={"basis": "district", "source": "synthetic", "fips": ["29095"]},
        leaids=["2900001"],
    )
    content = {
        "platform": {
            "id": "synthetic",
            "name": "synthetic",
            "operator": "synthetic",
            "adapter": "gray",
            "poll_minutes": 10,
            "terms": TERMS,
            "notes": "synthetic",
        },
        "stations": [
            _station("synthetic-p", ["29047", "29095"]),
            district,
            _station("synthetic-u", ["29095"]),
            _station("synthetic-v", ["20091"]),
        ],
    }
    (folder / "synthetic.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    return load_registry(folder)


def _storms(registry: Registry) -> StormDays:
    days = {"winter": {"29095": {date(2025, 1, 8): 1.0, date(2022, 1, 10): 0.25}}}
    return StormDays.build(registry, gate.hazard_days(days, ["winter"]))


def _report(open_ids: list[str]) -> dict[str, JSONValue]:
    return {
        "states": {"MO": {"meets_target": False, "open": list(open_ids)}},
        "stations": {sid: {"gain": {"weighted": 1.0}} for sid in open_ids},
    }


STORM = date(2025, 1, 8)
OLD_STORM = date(2022, 1, 10)
LISTED = date(2025, 2, 3)


def _around(day: date) -> set[date]:
    return {date.fromordinal(day.toordinal() + step) for step in (-2, -1, 1, 2)}


def test_near_days_are_the_two_days_either_side_of_each_closure_day(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    storms = _storms(registry)
    near = gate.near_days("synthetic-u", storms, {LISTED})
    assert near == _around(STORM) | _around(OLD_STORM) | _around(LISTED)
    assert STORM not in near
    assert LISTED not in near
    # A closure day next to another is a closure day, not a near one.
    assert date(2025, 1, 9) not in gate.near_days("synthetic-u", storms, {date(2025, 1, 9)})
    # No storm days: only the proven-list days count; none of either: no window.
    assert gate.near_days("synthetic-u", None, {LISTED}) == frozenset(_around(LISTED))
    assert gate.near_days("synthetic-v", storms, set()) == frozenset()


def _capture(stamp: str, digest: str) -> Capture:
    return Capture(stamp, U, "200", "text/html", 1000, digest)


def test_the_census_counts_near_day_captures_and_the_window_reads(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    storms = _storms(registry)
    captures = [
        _capture("20250107150000", "NEAR"),  # the day before the storm: near, unread
        _capture("20250108150000", "STORM"),  # the storm day: read empty
        _capture("20250108160000", "STORM"),  # the same bytes: one distinct capture
        _capture("20250109150000", "AFTER"),  # the day after: read empty
        _capture("20250110150000", "SHELL"),  # two days after: a page shell
        _capture("20250301150000", "FAIR"),  # fair weather: unread, not due
    ]
    census = gate.Census(
        listings={U_KEY: captures},
        listing_names=set(),
        read={
            ("20250108150000", U_KEY): "empty",
            ("20250109150000", U_KEY): "empty",
            ("20250110150000", U_KEY): "deferred",
            ("20250106150000", U_KEY): "count_only",  # read, though no listing holds it
        },
    )
    near = gate.near_days("synthetic-u", storms, set())
    found = gate.key_census(census, "synthetic-u", U_KEY, storms, near=near)
    assert (found.unread, found.unread_storm, found.unread_near, found.unread_due) == (2, 0, 1, 1)
    # STORM (once, by digest), AFTER, and the unlisted read of the 6th; not the shell.
    assert found.window_seen == 3
    assert found.as_json()["window_seen"] == 3
    assert found.as_json()["unread_near"] == 1
    # Without the near days the capture before the storm is not due.
    core = gate.key_census(census, "synthetic-u", U_KEY, storms)
    assert (core.unread_near, core.unread_due) == (0, 0)
    assert core.window_seen == 1  # only the storm day itself
    plan = gate.plan_due(
        registry, _report(["synthetic-u"]), census, set(), storms=storms, closure={}
    )
    assert [item.timestamp for item in plan.snapshots] == ["20250107150000"]
    assert plan.snapshots[0].why == "2025-01-07: within 2 days of one of its closure days"


def _record(stamp: str, retrieved: str, **fields: object) -> SnapshotRecord:
    base: dict[str, object] = {
        "timestamp": stamp,
        "url": U,
        "requested": f"https://web.archive.org/web/{stamp}id_/{U}",
        "retrieved_at": retrieved,
        "error": "HTTP 429",
    }
    base.update(fields)
    return SnapshotRecord.model_validate_json(json.dumps(base))


def test_a_capture_answered_429_in_three_hours_is_a_refusal_replayed() -> None:
    records = [
        *(_record("20250212075851", f"2026-10-04T{hour:02d}:50:28Z") for hour in (6, 13, 15)),
        _record("20250212075851", "2026-10-04T15:59:01Z"),  # again in the same hour
        # In two hours only: the archive's own rate limit is not ruled out.
        *(_record("20250213000000", f"2026-10-04T1{hour}:00:00Z") for hour in (1, 2)),
        *(_record("20250213000000", f"2026-10-04T12:{minute}:00Z") for minute in (10, 40)),
        # Answered 429 on three days, but served once: not a replay.
        *(_record("20250214000000", f"2026-10-0{day}T12:00:00Z") for day in (1, 2, 3)),
        _record(
            "20250214000000",
            "2026-10-04T12:00:00Z",
            error=None,
            file="snapshots/x.body",
            sha256="d" * 64,
        ),
        # Reached through a redirect: the 429 answers another capture.
        *(
            _record(
                "20250215000000",
                f"2026-10-0{day}T12:00:00Z",
                hops=[{"location": "x", "status": 302}],
            )
            for day in (1, 2, 3)
        ),
        # Another error on three days is not a refusal.
        *(
            _record("20250216000000", f"2026-10-0{day}T12:00:00Z", error="HTTP 503")
            for day in (1, 2, 3)
        ),
    ]
    assert gate.refused_captures(records) == {("20250212075851", U_KEY): "refused"}
    # It held no page of the list: a list read only so is not "all-read".
    assert "refused" in gate.BLIND_STATES


def _read(sid: str, when: str, rows: int, sha: str) -> ListingRead:
    return ListingRead.model_validate_json(
        json.dumps(
            {
                "source_id": sid,
                "mode": "archive",
                "url": f"https://{sid}.test/closings",
                "fetched_at": when,
                "retrieved_at": "2026-10-04T01:00:00Z",
                "sha256": sha * 64,
                "bytes": 10,
                "variant": "synthetic",
                "state": "populated" if rows else "empty",
                "rows": rows,
                "declared_count": None,
                "skipped_rows": 0,
            }
        )
    )


def test_the_calibration_measures_the_window_on_proven_sources(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    storms = _storms(registry)
    reads = [
        # P, a list: a row on the storm day.
        _read("synthetic-p", "2025-01-08T15:00:00Z", 4, "a"),
        _read("synthetic-p", "2025-03-01T15:00:00Z", 0, "b"),
        # U, a list: empty on the storm day, a row two days later (near, not a closure day).
        _read("synthetic-u", "2025-01-08T14:00:00Z", 0, "c"),
        _read("synthetic-u", "2025-01-10T15:00:00Z", 2, "d"),
        # Q, a district channel: a notice of no closing on the storm day, a kept
        # closing notice the day after.
        _read("synthetic-q", "2025-01-08T13:00:00Z", 1, "e"),
        _read("synthetic-q", "2025-01-09T15:00:00Z", 1, "f"),
        # V, a status board (rows every day): left out.
        _read("synthetic-v", "2025-01-08T15:00:00Z", 9, "0"),
    ]
    result: dict[str, JSONValue] = {
        "district_notice_gate": {
            "synthetic-q": {
                "kind": "channel",
                "kept_proofs": [{"mode": "archive", "captured_at": "2025-01-09T15:00:00Z"}],
            },
            "synthetic-v": {"kind": "board", "kept_proofs": []},
        }
    }
    proven = {"synthetic-p", "synthetic-q", "synthetic-u", "synthetic-v"}
    found = gate.calibration(registry, reads, proven, storms, result)
    assert found["near_days"] == gate.NEAR_DAYS

    def cells(kind: str, name: str) -> dict[str, tuple[int, int]]:
        block = found[kind]
        assert isinstance(block, dict)
        rows = block[name]
        assert isinstance(rows, list)
        found_cells: dict[str, tuple[int, int]] = {}
        for row in rows:
            assert isinstance(row, dict)
            sources, none = row["sources"], row["none_showed"]
            assert isinstance(sources, int)
            assert isinstance(none, int)
            if sources:
                found_cells[str(row["reads"])] = (sources, none)
        return found_cells

    # Closure days alone: U's one read there was empty, though U is in use.
    assert cells("lists", "closure_days") == {"1": (2, 1)}
    lists = found["lists"]
    assert isinstance(lists, dict)
    assert lists["closure_days_missed"] == [{"id": "synthetic-u", "window_reads": 1}]
    # With the days either side, U's row two days after the storm is in its window.
    assert cells("lists", "window") == {"1": (1, 0), "2": (1, 0)}
    assert lists["window_missed"] == []
    assert cells("channels", "closure_days") == {"1": (1, 1)}
    assert cells("channels", "window") == {"2": (1, 0)}
    # Left out: a live read, a source the registry lacks, a district channel the
    # notice gate never judged, and a proven list never seen with a row.
    others = [
        *reads,
        _read("synthetic-p", "2025-01-08T16:00:00Z", 0, "1").model_copy(update={"mode": "live"}),
        _read("synthetic-z", "2025-01-08T15:00:00Z", 3, "2"),
        _read("synthetic-v", "2025-01-08T15:00:00Z", 0, "3"),
    ]
    again = gate.calibration(registry, others, {*proven, "synthetic-z"}, storms, {})
    assert again["channels"] == gate.calibration(registry, [], proven, storms, {})["channels"]
    lists_again = again["lists"]
    assert isinstance(lists_again, dict)
    assert lists_again["window_missed"] == []
    # A source never seen in use (no row, no kept notice) is not measured.
    quiet = gate.calibration(registry, reads[1:2], {"synthetic-p"}, storms, {})
    assert quiet["lists"] == quiet["channels"]
    assert quiet["channels"] == {
        "closure_days": [
            {"reads": label, "sources": 0, "none_showed": 0} for *_, label in gate.CALIBRATION_BINS
        ],
        "closure_days_missed": [],
        "window": [
            {"reads": label, "sources": 0, "none_showed": 0} for *_, label in gate.CALIBRATION_BINS
        ],
        "window_missed": [],
    }

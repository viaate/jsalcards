"""The coverage gate's closure days, the ``storm-read`` verdict and the due-capture plan.

A source stays open while a capture of its list made in its closure window is
unread: its storm days (an NWS winter, cold or tropical code over one of its
counties), the days a proven whole-county list sharing one of its counties was
seen with a row, and the two days either side of each. Once every such capture is
read with no row, and a read there saw the list itself, its verdict is
``storm-read`` (``no-storm-capture`` when no read there saw it): no archived
capture left could reasonably prove it, though its fair-weather captures may be
unread.

Everything here is synthetic (every URL is under .test).
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.cli import main
from snowlight.output import JSONValue
from snowlight.sources.stations import gate
from snowlight.sources.stations.archive import Capture
from snowlight.sources.stations.model import ListingRead
from snowlight.sources.stations.registry import Registry, StationStatus, load_registry
from snowlight.sources.stations.storms import StormDays

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
SHA = "c" * 64
U = "https://synthetic-u.test/closings"
U_KEY = "synthetic-u.test/closings"


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
            _station("synthetic-v", ["20091"], archive_urls=["https://old-v.test/list"]),
        ],
    }
    (folder / "synthetic.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    return load_registry(folder)


def _read(sid: str, when: str, rows: int, mode: str = "archive") -> ListingRead:
    return ListingRead.model_validate_json(
        json.dumps(
            {
                "source_id": sid,
                "mode": mode,
                "url": f"https://{sid}.test/closings",
                "fetched_at": when,
                "retrieved_at": "2026-10-04T01:00:00Z",
                "sha256": SHA,
                "bytes": 10,
                "variant": "synthetic",
                "state": "populated" if rows else "empty",
                "rows": rows,
                "declared_count": None,
                "skipped_rows": 0,
            }
        )
    )


def _storms(registry: Registry) -> StormDays:
    days = {"winter": {"29095": {date(2025, 1, 8): 1.0, date(2022, 1, 10): 0.25}}}
    return StormDays.build(registry, gate.hazard_days(days, ["winter"]))


def _capture(stamp: str, digest: str, status: str = "200", length: int = 1000) -> Capture:
    return Capture(stamp, U, status, "text/html", length, digest)


def _census(read: dict[tuple[str, str], str] | None = None) -> gate.Census:
    captures = [
        _capture("20220110150000", "OLDSTORM"),  # a storm day before the readable form
        _capture("20220301120000", "REFUSED"),  # read: refused (the old form)
        _capture("20250106120000", "EMPTY1"),  # read: empty
        _capture("20250108130000", "STORM1", length=900),  # storm day: due
        _capture("20250108050000", "STORM2", length=1200),  # the same day, larger: due
        _capture("20250203150000", "LISTED"),  # a proven list's day: due
        _capture("20250301120000", "FAIR"),  # fair weather: unread, not due
        _capture("20250108100000", "STORM1", status="-"),  # a revisit of STORM1
    ]
    found = {
        ("20220301120000", U_KEY): "error",
        ("20250106120000", U_KEY): "empty",
        **(read or {}),
    }
    return gate.Census(
        listings={U_KEY: sorted(captures, key=lambda c: c.timestamp)},
        listing_names={"synthetic_u_test_closings___20170101-20260930.json"},
        read=found,
    )


def test_closure_days_come_from_proven_whole_county_lists(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    reads = [
        _read("synthetic-p", "2025-02-03T15:00:00Z", 4),  # proven, archived, populated
        _read("synthetic-p", "2025-02-05T15:00:00Z", 0),  # empty: no closure day
        _read("synthetic-p", "2026-10-01T15:00:00Z", 2, mode="live"),  # live: not a capture
        _read("synthetic-q", "2025-02-04T15:00:00Z", 1),  # a district's notice
        _read("synthetic-u", "2025-02-06T15:00:00Z", 3),  # not proven
        _read("synthetic-z", "2025-02-07T15:00:00Z", 3),  # not registered
    ]
    proven = {"synthetic-p", "synthetic-q", "synthetic-z"}
    days = gate.closure_days(registry, reads, proven)
    one = frozenset({date(2025, 2, 3)})
    assert days == {"synthetic-p": one, "synthetic-q": one, "synthetic-u": one}
    assert "synthetic-v" not in days  # no county in common


def test_the_census_counts_due_captures(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    census = _census()
    since = gate.readable_since(census, [U_KEY])
    assert since == "20220301120000"
    found = gate.key_census(
        census,
        "synthetic-u",
        U_KEY,
        _storms(registry),
        closure={date(2025, 2, 3)},
        since=since,
    )
    # Unread: the old storm day, two storm captures, the revisit, the listed day, fair.
    assert found.unread == 6
    assert found.unread_storm == 4
    assert found.unread_closure == 1
    assert found.unread_due == 4  # not the storm day before the readable form
    assert found.as_json()["unread_due"] == 4
    assert found.as_json()["unread_closure"] == 1
    # Without storm days or closure days nothing is due.
    plain = gate.key_census(census, "synthetic-u", U_KEY, None)
    assert (plain.unread, plain.unread_storm, plain.unread_due) == (6, 0, 0)


def _keys(**fields: object) -> list[gate.KeyCensus]:
    base: dict[str, object] = {
        "key": "k",
        "listed": 5,
        "listing_asked": True,
        "winter": 3,
        "digests": 5,
        "read": {"empty": 2},
        "read_captures": 2,
        "unread": 3,
        "unread_storm": 0,
    }
    base.update(fields)
    return [gate.KeyCensus(**base)]  # type: ignore[arg-type]


def test_storm_read_needs_every_due_capture_read_and_the_list_seen() -> None:
    active = StationStatus.ACTIVE
    due = _keys(unread_storm=2, unread_due=2)
    assert gate.verdict("working", False, due, active, storm_days=True) == "unread"
    fair = _keys(window_seen=1)
    assert gate.verdict("working", False, fair, active, storm_days=True) == "storm-read"
    # Without storm days nothing is known to be due: still unread.
    assert gate.verdict("working", False, fair, active) == "unread"
    # The list was seen, but on no capture in its closure window: none made there is left.
    outside = _keys()
    assert gate.verdict("working", False, outside, active, storm_days=True) == "no-storm-capture"
    # A page shell or a refusal never saw the list: more of its captures are asked for
    # until three are read, and then it is a form no read can see the list in.
    shell = _keys(read={"deferred": 1, "error": 1})
    assert gate.verdict("working", False, shell, active, storm_days=True) == "unread"
    shells = _keys(read={"deferred": 2, "error": 1}, read_captures=3)
    assert gate.verdict("working", False, shells, active, storm_days=True) == "unreadable"
    counted = _keys(read={"count_only": 1}, window_seen=1)
    assert gate.verdict("working", False, counted, active, storm_days=True) == "storm-read"
    # A district's notice that announced no closing saw its list.
    notice = _keys(read={"populated": 1, "deferred": 4}, window_seen=1)
    assert gate.verdict("working", False, notice, active, storm_days=True) == "storm-read"
    # An address of its list never listed comes first; fair captures of an older one do not.
    unlisted = [*fair, *_keys(key="k2", listed=0, listing_asked=False, unread=0, read={})]
    assert gate.verdict("working", False, unlisted, active, storm_days=True) == "not-listed"
    older = [*_keys(unread=0), *_keys(key="old", current=False, unread_due=3)]
    assert gate.verdict("working", False, older, active, storm_days=True) == "older-unread"
    assert gate.verdict("working", True, due, active, storm_days=True) == "proven"
    assert {"storm-read", "no-storm-capture"} <= gate.TERMINAL
    assert "unread" not in gate.TERMINAL


def _report(open_ids: list[str]) -> dict[str, JSONValue]:
    return {
        "states": {
            "MO": {"meets_target": False, "open": list(open_ids)},
            "KS": {"meets_target": True, "open": []},
        },
        "stations": {
            "synthetic-u": {"gain": {"weighted": 2.0}},
            "synthetic-v": {"gain": {"weighted": 5.0}},
        },
    }


def test_open_sources_are_ordered_by_weighted_gain() -> None:
    assert gate.open_sources(_report(["synthetic-u", "synthetic-v"])) == [
        "synthetic-v",
        "synthetic-u",
    ]
    with pytest.raises(gate.GateError, match="no state or station table"):
        gate.open_sources({})


def test_the_due_plan_asks_for_every_due_capture(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    storms = _storms(registry)
    closure = {"synthetic-u": frozenset({date(2025, 2, 3)})}
    census = _census()
    plan = gate.plan_due(
        registry,
        _report(["synthetic-u", "synthetic-v"]),
        census,
        set(),
        storms=storms,
        closure=closure,
        options=gate.DueOptions(first=1),
    )
    stamps = [item.timestamp for item in plan.snapshots]
    # The strongest storm day first (the larger capture), then the rest; the revisit
    # of STORM1 is asked for by STORM1's own time, once; the old form's day is not due.
    assert stamps == ["20250108050000", "20250108130000", "20250203150000"]
    assert plan.snapshots[0].why == "storm day 2025-01-08 (market score 1.00)"
    assert (
        plan.snapshots[2].why == "2025-02-03: a day a proven list sharing its counties held a row"
    )
    # V's page was never listed: it is listed, and no capture of it is known.
    assert plan.listings == [
        {
            "url": "synthetic-v.test/closings",
            "from": "20170101",
            "to": "20260930",
            "filter": ["statuscode:200"],
            "collapse": "timestamp:10",
            "station": "synthetic-v",
            "why": "never listed: an address of the source's list, so no verdict but "
            "not-listed could be given; listed to learn what the archive holds of it",
        }
    ]
    request = plan.as_json()
    assert isinstance(request["snapshots"], list)
    assert len(request["snapshots"]) == 3
    assert "cdx" in request
    # Captures already downloaded or asked for by a pending run are not asked again.
    skip = frozenset({("20250108050000", U_KEY)})
    done = {("20250203150000", U_KEY)}
    again = gate.plan_due(
        registry,
        _report(["synthetic-u"]),
        census,
        done,
        storms=storms,
        closure=closure,
        options=gate.DueOptions(skip=skip, only=frozenset({"synthetic-u"})),
    )
    assert [item.timestamp for item in again.snapshots] == ["20250108130000"]
    assert again.as_json() == {"snapshots": [again.snapshots[0].as_json()]}
    limited = gate.plan_due(
        registry,
        _report(["synthetic-u"]),
        census,
        set(),
        storms=storms,
        closure=closure,
        options=gate.DueOptions(limit=1),
    )
    assert len(limited.snapshots) == 1
    # A source named by ``only`` is planned though it keeps no state open (its proof
    # would add no school): it can be settled all the same.
    settled = gate.plan_due(
        registry,
        _report([]),
        census,
        set(),
        storms=storms,
        closure=closure,
        options=gate.DueOptions(only=frozenset({"synthetic-u"})),
    )
    assert [item.timestamp for item in settled.snapshots] == stamps
    assert gate.plan_due(registry, _report([]), census, set(), storms=storms, closure=closure) == (
        gate.DuePlan([], [])
    )
    with pytest.raises(gate.GateError, match="registry lacks"):
        gate.plan_due(registry, _report(["synthetic-z"]), census, set(), storms=storms, closure={})


def test_a_source_whose_list_was_never_seen_gets_its_largest_captures(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    captures = [
        Capture("20250301120000", U, "200", "text/html", 800, "A"),
        Capture("20250302120000", U, "200", "text/html", 3000, "B"),
        Capture("20250303120000", U, "200", "text/html", 2000, "C"),
    ]
    census = gate.Census(
        listings={U_KEY: captures},
        listing_names=set(),
        read={("20250304120000", U_KEY): "deferred"},
    )
    plan = gate.plan_due(
        registry,
        _report(["synthetic-u"]),
        census,
        set(),
        storms=_storms(registry),
        closure={},
    )
    # One capture was read (a page shell): two more, the largest, make three.
    assert [item.timestamp for item in plan.snapshots] == ["20250302120000", "20250303120000"]
    assert plan.snapshots[0].why.endswith("as no read has seen its list yet")
    # Three shells read: no more fair-weather captures are asked for (unreadable).
    shells = gate.Census(
        listings={U_KEY: captures},
        listing_names=set(),
        read={(f"2025030{n}120000", U_KEY): "deferred" for n in (4, 5, 6)},
    )
    assert (
        gate.plan_due(
            registry,
            _report(["synthetic-u"]),
            shells,
            set(),
            storms=_storms(registry),
            closure={},
        ).snapshots
        == []
    )
    # Once a read saw the list, fair-weather captures are not asked for.
    census.read[("20250305120000", U_KEY)] = "empty"
    again = gate.plan_due(
        registry,
        _report(["synthetic-u"]),
        census,
        set(),
        storms=_storms(registry),
        closure={},
    )
    assert again.snapshots == []


def test_the_report_marks_settled_states() -> None:
    stations: dict[str, JSONValue] = {
        "a": {"verdict": "storm-read", "gain": {"by_state": {"MO": [3, 1.0]}}},
        "b": {"verdict": "unread", "gain": {"by_state": {"MO": [0, 0.0]}}},
        "c": {"verdict": "unread", "gain": {"by_state": {"KS": [2, 1.0]}}},
        "d": {"verdict": "not-listed", "gain": {"by_state": {"MO": [1, 0.2]}}},
        "e": {"verdict": "proven", "gain": None},
        "f": "not a table",
    }
    ids = ["a", "b", "c", "d", "e", "f", "g"]
    assert gate._open_sources("MO", ids, stations) == ["d"]
    stations["d"] = {"verdict": "no-capture", "gain": {"by_state": {"MO": [1, 0.2]}}}
    assert gate._open_sources("MO", ids, stations) == []


def test_the_plan_command_writes_the_due_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    report_path = tmp_path / "gate.json"
    report_path.write_text(json.dumps({**_report(["synthetic-u"]), "ranking": []}), "utf-8")
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(
        json.dumps({"stations": {"synthetic-p": {"state": "working", "proof": {"proves": True}}}}),
        encoding="utf-8",
    )
    reads = tmp_path / "reads.jsonl"
    reads.write_text(
        _read("synthetic-p", "2025-02-03T15:00:00Z", 4).model_dump_json() + "\n", encoding="utf-8"
    )
    artifacts = tmp_path / "artifacts"
    listing = artifacts / "cdx-1"
    listing.mkdir(parents=True)
    header = ["timestamp", "original", "statuscode", "mimetype", "length", "digest"]
    rows = [
        ["20250106120000", U, "200", "text/html", "1000", "EMPTY1"],
        ["20250203150000", U, "200", "text/html", "1000", "LISTED"],
        ["20250301120000", U, "200", "text/html", "1000", "FAIR"],
    ]
    (listing / "synthetic_u_test_closings___20170101-20260930.json").write_text(
        json.dumps([header, *rows]), encoding="utf-8"
    )
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps({"snapshots": [{"timestamp": "1", "url": U}]}), "utf-8")
    monkeypatch.setattr(
        "snowlight.sources.stations.gate_cli._storms",
        lambda *_args, **_kwargs: _storms(registry),
    )
    common = [
        "stations",
        "--registry",
        str(tmp_path / "sources"),
        "gate",
        "plan",
        "--report",
        str(report_path),
        "--artifacts",
        str(artifacts),
        "--archive-reads",
        str(reads),
        "--archive-health",
        str(tmp_path / "none.json"),
    ]
    code = main([*common, "--due", "--coverage", str(coverage_path), "--pending", str(pending)])
    assert code == 0
    request = json.loads(capsys.readouterr().out)
    # The proven list's day is due, then the capture two days before the storm of
    # 2025-01-08 (near it); the fair-weather capture is not (the list was never seen,
    # but due captures are left to read first).
    assert [item["timestamp"] for item in request["snapshots"]] == [
        "20250203150000",
        "20250106120000",
    ]
    assert main([*common, "--due", "--no-storms"]) == 1
    assert "needs the storm days" in capsys.readouterr().err
    assert main([*common, "--due", "--coverage", str(tmp_path / "missing.json")]) == 1
    assert "gate plan:" in capsys.readouterr().err


def test_the_closure_days_reach_the_report_verdicts(tmp_path: Path) -> None:
    """A capture on a proven list's day keeps a source open until it is read."""
    registry = _registry(tmp_path)
    census = _census(
        {
            ("20250108130000", U_KEY): "empty",
            ("20250108050000", U_KEY): "empty",
            ("20220110150000", U_KEY): "error",
        }
    )
    storms = _storms(registry)
    days = {"synthetic-u": frozenset({date(2025, 2, 3)})}
    keys = [
        gate.key_census(
            census,
            "synthetic-u",
            U_KEY,
            storms,
            closure=days["synthetic-u"],
            since=gate.readable_since(census, [U_KEY]),
        )
    ]
    active = StationStatus.ACTIVE
    assert gate.verdict("working", False, keys, active, storm_days=True) == "unread"
    census.read[("20250203150000", U_KEY)] = "empty"
    keys = [
        gate.key_census(
            census,
            "synthetic-u",
            U_KEY,
            storms,
            closure=days["synthetic-u"],
            since=gate.readable_since(census, [U_KEY]),
        )
    ]
    assert keys[0].unread == 1  # the fair-weather capture
    # The storm-day capture of 2022 was refused (the old form): misread, so not settled.
    assert gate.verdict("working", False, keys, active, storm_days=True) == "misread"
    # Once a reader reads that form (empty), every window capture is read: settled.
    census.read[("20220110150000", U_KEY)] = "empty"
    keys = [
        gate.key_census(
            census,
            "synthetic-u",
            U_KEY,
            storms,
            closure=days["synthetic-u"],
            since=gate.readable_since(census, [U_KEY]),
        )
    ]
    assert gate.verdict("working", False, keys, active, storm_days=True) == "storm-read"
    assert datetime(2025, 2, 3, 15, tzinfo=UTC).date() in days["synthetic-u"]


def test_blind_since_marks_the_page_form_that_loads_its_list_by_script() -> None:
    def census(reads: dict[str, str]) -> gate.Census:
        return gate.Census(
            listings={}, listing_names=set(), read={(k, U_KEY): v for k, v in reads.items()}
        )

    # A homepage that carried its notices (2023) and then loaded them by script.
    moved = census(
        {
            "20230105120000": "empty",
            "20230210120000": "populated",
            "20240105120000": "deferred",
            "20240301120000": "deferred",
            "20250105120000": "deferred",
        }
    )
    assert gate.blind_since(moved, [U_KEY]) == "20240105120000"
    # Fewer than three reads after the last that saw the list: nothing is presumed.
    few = census({"20230105120000": "empty", "20240105120000": "deferred"})
    assert gate.blind_since(few, [U_KEY]) is None
    # A read that saw the list after the shells: the page carries it again.
    back = census(
        {
            **dict.fromkeys(["20240105120000", "20240106120000"], "deferred"),
            "20240107120000": "error",
            "20250105120000": "empty",
        }
    )
    assert gate.blind_since(back, [U_KEY]) is None
    # Never seen: from the first read on, every capture is presumed a shell.
    never = census(dict.fromkeys(["20240105120000", "20240106120000", "20240107120000"], "error"))
    assert gate.blind_since(never, [U_KEY]) == "20240105120000"
    # Another key's reads do not count.
    assert gate.blind_since(moved, ["other.test/"]) is None


def test_captures_after_the_page_went_blind_are_not_due(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    storms = _storms(registry)
    census = _census(
        {
            ("20250107120000", U_KEY): "deferred",
            ("20250107130000", U_KEY): "deferred",
            ("20250107140000", U_KEY): "deferred",
        }
    )
    until = gate.blind_since(census, [U_KEY])
    assert until == "20250107120000"
    found = gate.key_census(
        census,
        "synthetic-u",
        U_KEY,
        storms,
        closure={date(2025, 2, 3)},
        since=gate.readable_since(census, [U_KEY]),
        until=until,
    )
    assert found.unread_due == 0
    assert found.unread == 6
    plan = gate.plan_due(
        registry, _report(["synthetic-u"]), census, set(), storms=storms, closure={}
    )
    assert plan.snapshots == []


def test_an_older_unread_source_gets_its_other_addresses_read(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    page, old = "https://synthetic-v.test/closings", "https://old-v.test/list"
    census = gate.Census(
        listings={
            "synthetic-v.test/closings": [Capture("20250105120000", page, "200", "t", 9, "P")],
            "old-v.test/list": [
                Capture("20190105120000", old, "200", "t", 9, "OLD"),
                Capture("20190106120000", old, "-", "warc/revisit", 9, "OLD"),
                Capture("20190107120000", old, "200", "t", 9, "READ"),
            ],
        },
        listing_names=set(),
        read={
            ("20250105120000", "synthetic-v.test/closings"): "empty",
            ("20190107120000", "old-v.test/list"): "empty",
        },
    )
    plan = gate.plan_due(
        registry,
        _report(["synthetic-v"]),
        census,
        set(),
        storms=_storms(registry),
        closure={},
    )
    # The revisit replays the 2019-01-05 capture: one capture asked for.
    assert [(item.timestamp, item.url) for item in plan.snapshots] == [("20190105120000", old)]
    assert plan.snapshots[0].why.startswith("2019-01-05: an unread capture of an earlier address")


def test_a_list_whose_captures_are_all_404s_or_redirects_has_no_capture() -> None:
    active = StationStatus.ACTIVE
    gone = _keys(read={"gone": 1, "redirect": 2}, read_captures=3, unread=0)
    assert gate.verdict("working", False, gone, active, storm_days=True) == "no-capture"
    refused = _keys(read={"gone": 1, "error": 2}, read_captures=3, unread=0)
    assert gate.verdict("working", False, refused, active, storm_days=True) == "unreadable"
    shells = _keys(read={"gone": 1, "deferred": 2}, read_captures=3, unread=0)
    assert gate.verdict("working", False, shells, active, storm_days=True) == "all-read"

"""A station's own former address of its list proves it, like its current address.

Decided for the coverage gate (2026-10-04): the proven share asks whether an
outlet's closings channel is used at all, and a station that moved its own list
(KPAX's Scripps closings module from ``/weather/school-closings-delays`` to
``/school-closings-delays``; Alachua's homepage from sbac.edu to
alachuaschools.net) still runs the same channel. The registry names each such
address in ``former_urls`` with the evidence of the move; any other older address
(another vendor's file a page once framed) still proves nothing. The archive
census also counts a capture the archive answered with a redirect to another
address (an old address after a move) as read: it holds no list of its own.

Everything here is synthetic (every URL is under .test).
"""

import json
from pathlib import Path

import polars as pl
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.output import JSONValue
from snowlight.sources.stations import coverage, gate, proof
from snowlight.sources.stations.archive import Capture, SnapshotRecord
from snowlight.sources.stations.model import HealthStatus, SourceHealth
from snowlight.sources.stations.registry import (
    PlatformFile,
    RegistryError,
    StationStatus,
    dump_platform_file,
    load_registry,
)

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
SCHOOLS = pl.DataFrame(
    {
        "state": ["MT", "MT", "MT"],
        "county_fips": ["30063", "30063", "30031"],
        "county_name": ["Missoula", "Missoula", "Gallatin"],
    }
)
SHA = "c" * 64
MOVED = "https://moved.test/weather/school-closings-delays"
FRAMED = "https://vendor.test/moved/closings.html"


def _station(sid: str, fips: list[str], **fields: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": sid,
        "platform": "synthetic",
        "call_sign": sid.split("-")[1].upper() + "XX",
        "name": sid,
        "market": "Missoula",
        "dma": None,
        "states": ["MT"],
        "counties": {"basis": "dma", "source": "synthetic", "fips": fips},
        "page_url": f"https://{sid}.test/school-closings-delays",
        "data_url": None,
        "archive_urls": [],
        "poll_minutes": None,
        "status": "active",
        "evidence": "synthetic",
    }
    entry.update(fields)
    return entry


def _write(folder: Path, stations: list[dict[str, object]]) -> Path:
    folder.mkdir(exist_ok=True)
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
        "stations": stations,
    }
    (folder / "synthetic.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    return folder


def _former(url: str) -> dict[str, str]:
    return {"url": url, "evidence": "synthetic: the same module on the same site"}


def _registry_folder(tmp_path: Path) -> Path:
    moved = _station(
        "synthetic-moved",
        ["30063"],
        archive_urls=[MOVED, FRAMED],
        former_urls=[_former(MOVED)],
    )
    framed = _station(
        "synthetic-framed",
        ["30031"],
        page_url="https://synthetic-framed.test/closings",
        archive_urls=[FRAMED.replace("moved", "framed")],
    )
    return _write(tmp_path / "sources", [moved, framed])


def _read(sid: str, url: str, when: str, rows: int) -> dict[str, object]:
    return {
        "source_id": sid,
        "mode": "archive",
        "url": url,
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


def _evidence(tmp_path: Path, reads: list[dict[str, object]]) -> proof.Evidence:
    path = tmp_path / "archive-reads.jsonl"
    path.write_text("".join(json.dumps(item) + "\n" for item in reads), encoding="utf-8")
    return proof.gather(live_reads=None, archive_reads=path, archive_health=None, fixtures=None)


def _dig(value: JSONValue, *keys: str) -> JSONValue:
    for key in keys:
        assert isinstance(value, dict)
        value = value[key]
    return value


def test_a_former_address_is_an_archive_url_and_not_a_current_one(tmp_path: Path) -> None:
    folder = tmp_path / "bad"
    _write(folder, [_station("synthetic-moved", ["30063"], former_urls=[_former(MOVED)])])
    with pytest.raises(RegistryError, match="former addresses are archive URLs too"):
        load_registry(folder)
    page = "https://synthetic-moved.test/school-closings-delays"
    _write(
        folder,
        [_station("synthetic-moved", ["30063"], archive_urls=[page], former_urls=[_former(page)])],
    )
    with pytest.raises(RegistryError, match="is not current"):
        load_registry(folder)


def test_the_registry_writes_former_addresses_only_where_there_are_some(tmp_path: Path) -> None:
    registry = load_registry(_registry_folder(tmp_path))
    text = dump_platform_file(registry.files["synthetic"]).decode("utf-8")
    assert text.count("former_urls:") == 1
    again = PlatformFile.model_validate_json(json.dumps(yaml.safe_load(text.split("\n", 3)[3])))
    assert again.stations[0].former_urls[0].url == MOVED


def test_a_read_of_a_former_address_proves_the_station(tmp_path: Path) -> None:
    registry = load_registry(_registry_folder(tmp_path))
    moved = registry.stations["synthetic-moved"]
    framed = registry.stations["synthetic-framed"]
    evidence = _evidence(
        tmp_path,
        [
            _read("synthetic-moved", MOVED, "2020-01-07T13:00:00Z", 12),
            _read("synthetic-moved", moved.page_url or "", "2025-01-07T13:00:00Z", 0),
            # Another vendor's file the framed station's page once loaded: kept, proves nothing.
            _read("synthetic-framed", FRAMED.replace("moved", "framed"), "2019-01-07T13:00:00Z", 5),
        ],
    )
    best = evidence.best(moved)
    assert best is not None
    assert (best.current(moved), best.former(moved), best.proves(moved)) == (False, True, True)
    assert best.as_json(moved)["address"] == "former"
    other = evidence.best(framed)
    assert other is not None
    assert (other.address(framed), other.proves(framed)) == ("earlier", False)
    states = coverage.station_states(
        registry,
        {
            sid: SourceHealth.model_validate(
                {
                    "source_id": sid,
                    "url": f"https://{sid}.test/x",
                    "checked_at": "2026-10-04T01:00:00Z",
                    "status": HealthStatus.EMPTY,
                    "rows": 0,
                    "reason": None,
                }
            )
            for sid in registry.stations
        },
    )
    result = coverage.measure(registry, SCHOOLS, states, None)
    proof.add_proven(result, registry, SCHOOLS, states, evidence)
    assert _dig(result, "proven", "stations") == {
        "working": 2,
        "proven": 1,
        "unproven": 1,
        "shared": 0,
    }
    assert _dig(result, "proven", "national", "covered") == 2
    assert _dig(result, "stations", "synthetic-moved", "proof", "proves") is True
    assert _dig(result, "stations", "synthetic-framed", "proof", "address") == "earlier"
    working, proven = gate.proven_and_working(result)
    assert (working, proven) == ({"synthetic-moved", "synthetic-framed"}, {"synthetic-moved"})


def test_a_current_read_is_preferred_to_a_former_one(tmp_path: Path) -> None:
    registry = load_registry(_registry_folder(tmp_path))
    moved = registry.stations["synthetic-moved"]
    evidence = _evidence(
        tmp_path,
        [
            _read("synthetic-moved", MOVED, "2020-01-07T13:00:00Z", 40),
            _read("synthetic-moved", moved.page_url or "", "2025-01-07T13:00:00Z", 2),
        ],
    )
    best = evidence.best(moved)
    assert best is not None
    assert (best.address(moved), best.rows) == ("current", 2)


def _capture(stamp: str, url: str, digest: str, length: int) -> Capture:
    return Capture(
        timestamp=stamp,
        original=url,
        status="200",
        mimetype="text/html",
        length=length,
        digest=digest,
    )


def test_the_census_and_the_plan_count_former_addresses_as_proving(tmp_path: Path) -> None:
    registry = load_registry(_registry_folder(tmp_path))
    moved = registry.stations["synthetic-moved"]
    assert gate.former_keys(moved) == ["moved.test/weather/school-closings-delays"]
    assert gate.proving_keys(moved) == [
        "moved.test/weather/school-closings-delays",
        "synthetic-moved.test/school-closings-delays",
    ]
    key = "moved.test/weather/school-closings-delays"
    census = gate.Census(
        listings={
            key: [
                _capture("20200107130000", MOVED, "A", 1000),
                _capture("20200108130000", MOVED, "B", 2000),
            ]
        },
        listing_names={"moved_test_weather_school_closings_delays.json"},
        read={("20200107130000", key): "empty"},
    )
    found = gate.key_census(census, moved.id, key, None, current=False, former=True)
    assert (found.unread, found.proving) == (1, True)
    assert found.as_json()["former"] is True
    framed_key = gate.KeyCensus("vendor.test/x", 2, True, 2, 2, {}, 0, 2, 0, current=False)
    assert gate.verdict("working", False, [found], StationStatus.ACTIVE) == "unread"
    assert gate.verdict("working", False, [framed_key], StationStatus.ACTIVE) == "older-unread"
    ranking: list[dict[str, JSONValue]] = [{"id": moved.id, "schools": 2, "weighted": 9.0}]
    plan = gate.plan_captures(
        registry, ranking, census, set(), storms=None, options=gate.PlanOptions(min_weighted=1)
    )
    assert [(item.timestamp, item.url) for item in plan] == [("20200108130000", MOVED)]


def test_a_capture_answered_by_a_redirect_to_another_address_counts_as_read() -> None:
    old = "https://moved.test/weather/school-closings-delays"
    new = "https://moved.test/school-closings-delays"
    records = [
        # Asked for at a guessed time: the archive moved to the nearest capture of the
        # same address (20220110...), which redirected to the new address.
        SnapshotRecord(
            timestamp="20220115120000",
            url=old,
            requested=f"https://web.archive.org/web/20220115120000id_/{old}",
            hops=(
                {"location": f"https://web.archive.org/web/20220110080000id_/{old}", "status": 302},
                {"location": f"https://web.archive.org/web/20220110080000id_/{new}", "status": 301},
            ),
            final_original=new,
            final_timestamp="20220110080001",
        ),
        # Moved only to the nearest capture of the same address: not a redirect.
        SnapshotRecord(
            timestamp="20230115120000",
            url=old,
            requested=f"https://web.archive.org/web/20230115120000id_/{old}",
            hops=(
                {
                    "location": f"https://web.archive.org/web/20230110080000id_/{old}/",
                    "status": 302,
                },
            ),
            final_original=f"{old}/",
            final_timestamp="20230110080000",
        ),
    ]
    assert gate.redirected_captures(records) == {
        ("20220110080000", "moved.test/weather/school-closings-delays"): "redirect"
    }


def test_revisits_of_a_404_page_are_not_captures_of_a_list(tmp_path: Path) -> None:
    folder = tmp_path / "artifacts" / "cdx-1"
    folder.mkdir(parents=True)
    old = "https://moved.test/weather/school-closings-delays"
    header = ["timestamp", "original", "statuscode", "mimetype", "length", "digest"]
    rows = [
        ["20170316090541", old, "200", "text/html", "8560", "PAGE"],
        ["20170401090541", old, "-", "warc/revisit", "600", "PAGE"],
        ["20190330142937", old, "404", "text/html", "9437", "GONE"],
        ["20190401134652", old, "-", "warc/revisit", "632", "GONE"],
        ["20200401134652", old, "-", "warc/revisit", "632", "GONE"],
        # A revisit whose original the listing does not hold is kept (it may be a page).
        ["20210401134652", old, "-", "warc/revisit", "632", "ELSEWHERE"],
    ]
    (folder / "moved_test_weather_school_closings_delays.json").write_text(
        json.dumps([header, *rows]), encoding="utf-8"
    )
    listings, _ = gate.load_listings(tmp_path / "artifacts")
    kept = [capture.timestamp for capture in listings["moved.test/weather/school-closings-delays"]]
    assert kept == ["20170316090541", "20170401090541", "20210401134652"]


def test_a_list_whose_address_was_never_listed_is_not_all_read() -> None:
    read = gate.KeyCensus("page.test/", 0, False, 0, 0, {"empty": 1}, 1, 0, 0)
    assert gate.verdict("working", False, [read], StationStatus.ACTIVE) == "not-listed"
    listed = gate.KeyCensus("page.test/", 1, True, 1, 1, {"empty": 1}, 1, 0, 0)
    assert gate.verdict("working", False, [listed], StationStatus.ACTIVE) == "all-read"
    # An older address never listed does not hold the verdict back: it cannot prove the list.
    older = gate.KeyCensus("vendor.test/x", 0, False, 0, 0, {}, 0, 0, 0, current=False)
    assert gate.verdict("working", False, [listed, older], StationStatus.ACTIVE) == "all-read"


def test_a_capture_the_archive_replays_as_404_counts_as_read(tmp_path: Path) -> None:
    """A revisit of a 404 page the listing files under another form of the URL."""
    old = "https://moved.test/weather/school-closings-delays"
    records = [
        SnapshotRecord(
            timestamp="20200414135325",
            url=old,
            requested=f"https://web.archive.org/web/20200414135325id_/{old}",
            error="HTTP 404",
        ),
        # Moved to the nearest capture first, then 404: both times count.
        SnapshotRecord(
            timestamp="20210101000000",
            url=old,
            requested=f"https://web.archive.org/web/20210101000000id_/{old}",
            final_timestamp="20201231235959",
            final_original=old,
            error="HTTP 410",
        ),
        # The site refused the archive's crawler: never asked for again.
        SnapshotRecord(
            timestamp="20240101000000",
            url=old,
            requested=f"https://web.archive.org/web/20240101000000id_/{old}",
            error="HTTP 403",
        ),
        # Any other failure was not a read.
        SnapshotRecord(
            timestamp="20220101000000",
            url=old,
            requested=f"https://web.archive.org/web/20220101000000id_/{old}",
            error="URLError: timed out",
        ),
        # A body was kept: its read says what it held.
        SnapshotRecord(
            timestamp="20230101000000",
            url=old,
            requested=f"https://web.archive.org/web/20230101000000id_/{old}",
            file="snapshots/x.body",
            error="HTTP 404",
        ),
    ]
    key = "moved.test/weather/school-closings-delays"
    assert gate.missing_captures(records) == {
        ("20200414135325", key): "gone",
        ("20210101000000", key): "gone",
        ("20201231235959", key): "gone",
        ("20240101000000", key): "gone",
    }
    folder = tmp_path / "artifacts" / "snapshots-1" / "snapshots"
    folder.mkdir(parents=True)
    (folder / "manifest.jsonl").write_text(
        "".join(record.model_dump_json() + "\n" for record in records), encoding="utf-8"
    )
    census = gate.census_from_files(tmp_path / "artifacts", [], [])
    assert census.read[("20200414135325", key)] == "gone"
    assert ("20220101000000", key) not in census.read


def test_a_capture_the_archive_answers_with_another_counts_as_read() -> None:
    """Real shape: Missoula's homepage asked for at 20250120112116, served as 20250119233653."""
    page = "https://www.page.test/"
    records = [
        SnapshotRecord(
            timestamp="20250120112116",
            url=page,
            requested=f"https://web.archive.org/web/20250120112116id_/{page}",
            hops=(
                {
                    "location": f"https://web.archive.org/web/20250119233653id_/{page}",
                    "status": 302,
                },
            ),
            final_original=page,
            final_timestamp="20250119233653",
            file="snapshots/a.body",
        ),
        # Served as asked: its own read says what it held.
        SnapshotRecord(
            timestamp="20250121000000",
            url=page,
            requested=f"https://web.archive.org/web/20250121000000id_/{page}",
            final_original=page,
            final_timestamp="20250121000000",
            file="snapshots/b.body",
        ),
        # Moved to another address: a redirect, not a substitute.
        SnapshotRecord(
            timestamp="20250122000000",
            url=page,
            requested=f"https://web.archive.org/web/20250122000000id_/{page}",
            final_original="https://other.test/",
            final_timestamp="20250122000001",
            file="snapshots/c.body",
        ),
        # Not downloaded: nothing was read.
        SnapshotRecord(
            timestamp="20250123000000",
            url=page,
            requested=f"https://web.archive.org/web/20250123000000id_/{page}",
            final_timestamp="20250123000001",
            error="URLError: timed out",
        ),
    ]
    assert gate.replaced_captures(records) == {("20250120112116", "page.test/"): "replaced"}
    # A substitute neither sees the list nor makes the page blind.
    census = gate.Census(
        listings={},
        listing_names=set(),
        read={
            ("20250120112116", "page.test/"): "replaced",
            **{(f"2025013{n}000000", "page.test/"): "deferred" for n in range(3)},
        },
    )
    assert gate.blind_since(census, ["page.test/"]) == "20250130000000"
    assert gate.readable_since(census, ["page.test/"]) is None

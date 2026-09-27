"""Archived captures: CDX listings, snapshot plans, and parsing a downloaded artifact.

The capture bodies are real fixtures (fixtures/hearst/); the manifests and CDX
rows that point at them are synthetic, laid out the way the archive workflow
writes them.
"""

import gzip
import hashlib
import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.cli import main
from snowlight.sources.stations import archive
from snowlight.sources.stations.model import HealthStatus, ReadMode
from snowlight.sources.stations.registry import load_registry

FIXTURES = Path(__file__).parent / "fixtures" / "hearst"
CDX_HEADER = ["timestamp", "original", "statuscode", "mimetype", "length", "digest"]


def _registry(tmp_path: Path) -> Path:
    folder = tmp_path / "sources"
    folder.mkdir()
    platform = {
        "id": "demo",
        "name": "Demo (synthetic)",
        "operator": "Nobody",
        "adapter": "hearst",
        "poll_minutes": 10,
        "terms": {"automated_access": "unread", "summary": "synthetic", "evidence": []},
        "notes": "synthetic",
    }
    station = {
        "id": "demo-kmbc",
        "platform": "demo",
        "call_sign": "KMBC",
        "name": "synthetic",
        "market": "Kansas City",
        "dma": None,
        "states": ["MO"],
        "counties": {"basis": "observed", "source": "synthetic", "fips": ["29095"]},
        "page_url": "https://www.kmbc.com/weather/closings",
        "data_url": None,
        "archive_urls": ["https://www.kmbc.com/weather/closings"],
        "poll_minutes": None,
        "status": "active",
        "evidence": "synthetic",
    }
    content = {"platform": platform, "stations": [station]}
    (folder / "demo.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    return folder


def _artifact(tmp_path: Path) -> Path:
    root = tmp_path / "artifact"
    snaps = root / "snapshots"
    snaps.mkdir(parents=True)
    body = gzip.compress((FIXTURES / "kmbc-20240117203333.html").read_bytes())
    (snaps / "a.body").write_bytes(body)
    records = [
        {
            "timestamp": "20240108050323",
            "url": "https://www.kmbc.com/weather/closings",
            "requested": "https://web.archive.org/web/20240108050323id_/https://www.kmbc.com/weather/closings",
            "hops": [
                {"status": 302, "location": "https://web.archive.org/web/20240117203333id_/x"}
            ],
            "retrieved_at": "2026-09-25T04:05:22Z",
            "final_url": "https://web.archive.org/web/20240117203333id_/https://www.kmbc.com/weather/closings",
            "final_timestamp": "20240117203333",
            "final_original": "https://www.kmbc.com/weather/closings",
            "http_status": 200,
            "file": "snapshots/a.body",
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        },
        {
            "timestamp": "20240202000000",
            "url": "https://www.kmbc.com/weather/closings",
            "requested": "https://web.archive.org/web/20240202000000id_/https://www.kmbc.com/weather/closings",
            "error": "HTTP 503",
        },
        {
            "timestamp": "20240303000000",
            "url": "https://www.example.org/closings",
            "requested": "https://web.archive.org/web/20240303000000id_/https://www.example.org/closings",
            "file": "snapshots/a.body",
            "sha256": "0" * 64,
        },
    ]
    lines = "".join(json.dumps(record) + "\n" for record in records)
    (snaps / "manifest.jsonl").write_text(lines, encoding="utf-8")
    return root


def test_parse_snapshots_uses_the_capture_time_and_reports_failures(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    result = archive.parse_snapshots(registry, _artifact(tmp_path))
    statuses = [(entry.source_id, entry.status) for entry in result.health]
    assert statuses == [
        ("demo-kmbc", HealthStatus.OK),
        ("demo-kmbc", HealthStatus.ERROR),
        ("unregistered", HealthStatus.ERROR),
    ]
    captured = datetime(2024, 1, 17, 20, 33, 33, tzinfo=UTC)
    assert {row.fetched_at for row in result.rows} == {captured}
    assert len(result.rows) == 4
    (read,) = result.reads
    assert read.mode is ReadMode.ARCHIVE
    assert read.fetched_at == captured
    assert read.retrieved_at == datetime(2026, 9, 25, 4, 5, 22, tzinfo=UTC)
    assert "HTTP 503" in (result.health[1].reason or "")
    assert [snap.error for snap in result.snapshots] == [None, "HTTP 503"]


def test_cli_archive_parse_writes_outputs(tmp_path: Path) -> None:
    folder = _registry(tmp_path)
    out = tmp_path / "out"
    code = main(
        [
            "stations",
            "--registry",
            str(folder),
            "archive",
            "parse",
            str(_artifact(tmp_path)),
            "--out-dir",
            str(out),
        ]
    )
    # One capture was not served and one belongs to no station: both are reported in
    # health.json, but neither means an adapter needs attention.
    assert code == 0
    assert len((out / "rows.jsonl").read_text().splitlines()) == 4


def test_cli_archive_parse_fails_on_an_unknown_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _artifact(tmp_path)
    body = b"<html><body>Closings moved</body></html>"  # synthetic
    (root / "snapshots" / "a.body").write_bytes(body)
    manifest = root / "snapshots" / "manifest.jsonl"
    first = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])
    first.update(sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
    manifest.write_text(json.dumps(first) + "\n", encoding="utf-8")
    folder = _registry(tmp_path)
    args = ["stations", "--registry", str(folder), "archive", "parse", str(root)]
    code = main([*args, "--out-dir", str(tmp_path / "out")])
    assert code == 1
    assert "unrecognized shape" in capsys.readouterr().err


def test_read_cdx_and_plan_storm_days(tmp_path: Path) -> None:
    rows = [
        CDX_HEADER,
        [
            "20240108050323",
            "https://www.kmbc.com/weather/closings",
            "200",
            "text/html",
            "26600",
            "A",
        ],
        [
            "20240117203333",
            "https://www.kmbc.com/weather/closings",
            "200",
            "text/html",
            "32644",
            "B",
        ],
        [
            "20240122073606",
            "https://www.kmbc.com/weather/closings",
            "200",
            "text/html",
            "26445",
            "C",
        ],
        [
            "20240704070803",
            "https://www.kmbc.com/weather/closings",
            "200",
            "text/html",
            "27294",
            "D",
        ],
        ["20250114142134", "https://www.kmbc.com/weather/closings", "451", "text/html", "829", "E"],
        [
            "20250218141821",
            "https://www.kmbc.com/weather/closings",
            "200",
            "text/html",
            "49136",
            "F",
        ],
        ["20250219165518", "https://www.kmbc.com/weather/closings", "-", "warc/revisit", "-", "G"],
    ]
    path = tmp_path / "kmbc.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    captures = archive.read_cdx(path)
    assert len(captures) == 7
    assert captures[6].length is None
    plan = archive.plan_snapshots({"demo-kmbc": captures})
    assert plan == [
        {"timestamp": "20240117203333", "url": "https://www.kmbc.com/weather/closings"},
        {"timestamp": "20250218141821", "url": "https://www.kmbc.com/weather/closings"},
    ]
    only_2024 = archive.PlanOptions(seasons=frozenset({2024}))
    assert archive.plan_snapshots({"demo-kmbc": captures}, only_2024) == plan[1:]


def test_cli_archive_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = _registry(tmp_path)
    cdx = tmp_path / "cdx"
    cdx.mkdir()
    rows = [
        CDX_HEADER,
        [
            "20240117203333",
            "https://www.kmbc.com/weather/closings",
            "200",
            "text/html",
            "32644",
            "B",
        ],
    ]
    (cdx / "www_kmbc_com.json").write_text(json.dumps(rows), encoding="utf-8")
    args = ["stations", "--registry", str(folder), "archive", "plan", str(cdx), "--by-size"]
    assert main(args) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan == {
        "snapshots": [
            {"timestamp": "20240117203333", "url": "https://www.kmbc.com/weather/closings"}
        ]
    }


@pytest.mark.parametrize(
    "content",
    [
        "{}",
        '[["time"]]',
        '[["timestamp","original","statuscode","mimetype","length","digest"],[1]]',
        "no",
    ],
)
def test_bad_cdx_files_are_errors(tmp_path: Path, content: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(archive.ArchiveError):
        archive.read_cdx(path)


def test_empty_cdx_listing(tmp_path: Path) -> None:
    path = tmp_path / "none.json"
    path.write_text("[]", encoding="utf-8")
    assert archive.read_cdx(path) == []


def test_url_keys_ignore_scheme_www_slash_and_query() -> None:
    assert (
        archive.url_key("http://www.KMBC.com/weather/closings/?x=1") == "kmbc.com/weather/closings"
    )
    assert archive.url_key("kmbc.com/weather/closings") == "kmbc.com/weather/closings"


def test_capture_time_rejects_short_stamps() -> None:
    assert archive.capture_time("20240117203333") == datetime(2024, 1, 17, 20, 33, 33, tzinfo=UTC)
    with pytest.raises(archive.ArchiveError):
        archive.capture_time("202401")


def test_winter_season() -> None:
    assert archive.winter_season(datetime(2024, 11, 2, tzinfo=UTC)) == 2024
    assert archive.winter_season(datetime(2025, 3, 30, tzinfo=UTC)) == 2024
    assert archive.winter_season(datetime(2025, 7, 1, tzinfo=UTC)) is None


def test_bad_manifest_line_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "manifest.jsonl"
    path.write_text('{"timestamp": "2024"}\n', encoding="utf-8")
    with pytest.raises(archive.ArchiveError):
        archive.read_manifest(path)


def test_fixture_add_from_an_artifact(tmp_path: Path) -> None:
    folder = _registry(tmp_path)
    fixtures = tmp_path / "fixtures"
    code = main(
        [
            "stations",
            "--registry",
            str(folder),
            "fixture",
            "add",
            str(_artifact(tmp_path)),
            "--timestamp",
            "20240108050323",
            "--url",
            "https://www.kmbc.com/weather/closings",
            "--file",
            "demo/kmbc.html",
            "--slice",
            "hearst-page-v1",
            "--fixtures",
            str(fixtures),
        ]
    )
    assert code == 0
    provenance = json.loads((fixtures / "PROVENANCE.json").read_text(encoding="utf-8"))
    (entry,) = provenance
    assert entry["captured_at"] == "2024-01-17T20:33:33Z"
    assert entry["expected"]["rows"] == 4
    real = (FIXTURES / "kmbc-20240117203333.html").read_bytes()
    assert (fixtures / "demo" / "kmbc.html").read_bytes() == real
    assert "kmbc.html" in (fixtures / "README.md").read_text(encoding="utf-8")
    shutil.rmtree(fixtures)


def test_count_only_and_missing_captures_are_reported_but_not_failures(tmp_path: Path) -> None:
    folder = tmp_path / "sources"
    folder.mkdir()
    platform = {
        "id": "graydemo",
        "name": "Demo (synthetic)",
        "operator": "Nobody",
        "adapter": "gray",
        "poll_minutes": 10,
        "terms": {"automated_access": "unread", "summary": "synthetic", "evidence": []},
        "notes": "synthetic",
    }
    station = {
        "id": "graydemo-wkyt",
        "platform": "graydemo",
        "call_sign": "WKYT",
        "name": "synthetic",
        "market": "Lexington",
        "dma": None,
        "states": ["KY"],
        "counties": {"basis": "observed", "source": "synthetic", "fips": ["21067"]},
        "page_url": "https://www.wkyt.com/weather/closings/",
        "data_url": None,
        "archive_urls": ["https://www.wkyt.com/weather/closings/"],
        "poll_minutes": None,
        "status": "active",
        "evidence": "synthetic",
    }
    content = {"platform": platform, "stations": [station]}
    (folder / "graydemo.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    root = tmp_path / "artifact"
    snaps = root / "snapshots"
    snaps.mkdir(parents=True)
    body = (FIXTURES.parent / "gray" / "wkyt-20260127004608.html").read_bytes()
    (snaps / "w.body").write_bytes(body)
    url = "https://www.wkyt.com/weather/closings/"
    records = [
        {
            "timestamp": "20260127004608",
            "url": url,
            "requested": f"https://web.archive.org/web/20260127004608id_/{url}",
            "retrieved_at": "2026-09-25T06:00:00Z",
            "final_timestamp": "20260127004608",
            "final_original": url,
            "http_status": 200,
            "file": "snapshots/w.body",
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        },
        {
            "timestamp": "20250122120000",
            "url": "https://www.wjcl.com/weather/closings",
            "requested": "https://web.archive.org/web/20250122120000id_/https://www.wjcl.com/weather/closings",
            "error": "HTTP 404",
        },
    ]
    lines = "".join(json.dumps(record) + "\n" for record in records)
    (snaps / "manifest.jsonl").write_text(lines, encoding="utf-8")
    result = archive.parse_snapshots(load_registry(folder), root)
    assert result.failures == []
    first, second = result.health
    assert first.status is HealthStatus.ERROR
    assert "only a count (318 listed)" in (first.reason or "")
    assert [read.state.value for read in result.reads] == ["count_only"]
    assert second.source_id == "unregistered"
    assert "capture not downloaded: HTTP 404" in (second.reason or "")
    code = main(
        [
            "stations",
            "--registry",
            str(folder),
            "archive",
            "parse",
            str(root),
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 0


def test_a_body_that_differs_from_its_manifest_is_a_failure(tmp_path: Path) -> None:
    root = _artifact(tmp_path)
    manifest = root / "snapshots" / "manifest.jsonl"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["sha256"] = "0" * 64
    manifest.write_text(json.dumps(first) + "\n", encoding="utf-8")
    result = archive.parse_snapshots(load_registry(_registry(tmp_path)), root)
    assert result.rows == []
    (failure,) = result.failures
    assert "SHA-256" in failure


def test_a_capture_in_two_artifacts_is_read_once(tmp_path: Path) -> None:
    first = _artifact(tmp_path / "one")
    second = tmp_path / "two"
    shutil.copytree(first, second / "artifact")
    registry = load_registry(_registry(tmp_path))
    result = archive.parse_snapshots(registry, tmp_path)
    assert len(result.rows) == 4
    assert len(result.reads) == 1


def test_a_request_a_later_run_downloaded_is_not_reported_as_missing(tmp_path: Path) -> None:
    served = _artifact(tmp_path / "later")
    earlier = tmp_path / "earlier" / "artifact" / "snapshots"
    earlier.mkdir(parents=True)
    records = [
        {
            "timestamp": "20240108050323",
            "url": "https://www.kmbc.com/weather/closings",
            "requested": "https://web.archive.org/web/20240108050323id_/https://www.kmbc.com/weather/closings",
            "error": "not attempted: the run's time budget was spent",
        },
        {
            "timestamp": "20240202000000",
            "url": "https://www.kmbc.com/weather/closings",
            "requested": "https://web.archive.org/web/20240202000000id_/https://www.kmbc.com/weather/closings",
            "error": "HTTP 503",
        },
    ]
    lines = "".join(json.dumps(record) + "\n" for record in records)
    (earlier / "manifest.jsonl").write_text(lines, encoding="utf-8")
    assert served.is_dir()
    result = archive.parse_snapshots(load_registry(_registry(tmp_path)), tmp_path)
    reasons = [health.reason or "" for health in result.health]
    # The first request was downloaded by the later run: read once, never "missing".
    assert not any("not attempted" in reason for reason in reasons)
    # The second was not served in either run: reported once.
    assert sum("HTTP 503" in reason for reason in reasons) == 1
    assert len(result.reads) == 1


def test_fixture_add_refuses_a_body_that_differs_from_its_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _artifact(tmp_path)
    manifest = root / "snapshots" / "manifest.jsonl"
    first = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])
    first["sha256"] = "0" * 64
    manifest.write_text(json.dumps(first) + "\n", encoding="utf-8")
    code = main(
        [
            "stations",
            "--registry",
            str(_registry(tmp_path)),
            "fixture",
            "add",
            str(root),
            "--timestamp",
            "20240108050323",
            "--url",
            "https://www.kmbc.com/weather/closings",
            "--file",
            "demo/kmbc.html",
            "--fixtures",
            str(tmp_path / "fixtures"),
        ]
    )
    assert code == 1
    assert "SHA-256" in capsys.readouterr().err


def test_plan_skips_read_seasons_and_samples_older_years() -> None:
    def capture(stamp: str, length: int) -> archive.Capture:
        return archive.Capture(
            stamp, "https://www.kmbc.com/weather/closings", "200", "text/html", length, "D"
        )

    captures = [
        capture("20150110120000", 900),
        capture("20150601120000", 950),
        capture("20160201120000", 800),
        capture("20240117203333", 32644),
        capture("20240122073606", 26445),
        capture("20250218141821", 49136),
    ]
    skip = {("20240117203333", "kmbc.com/weather/closings")}
    options = archive.PlanOptions(skip=frozenset(skip), eras_before=2023, since=date(2023, 11, 1))
    plan = archive.plan_snapshots({"demo-kmbc": captures}, options)
    assert [item["timestamp"] for item in plan] == [
        "20250218141821",  # the 2023-24 season was already read
        "20150110120000",  # a winter capture of 2015 before a larger summer one
        "20160201120000",
    ]


def test_downloaded_lists_captures_read(tmp_path: Path) -> None:
    root = _artifact(tmp_path)
    assert ("20240117203333", "kmbc.com/weather/closings") in archive.downloaded(root)

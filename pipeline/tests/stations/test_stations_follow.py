"""Following a page that holds no list to the file it loads: archived and live.

The page and export bodies are real fixtures (fixtures/gray/, see its README for
each capture): WBTV's count-only closings page captured 2026-01-27 22:19:50 UTC and
the S3 export it loaded, captured two seconds later. Manifests, registries and
servers around them are synthetic; a body built from a real fixture and then
edited is named ``synthetic_*``.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.cli import main
from snowlight.sources.stations import archive, fetch
from snowlight.sources.stations.http import ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import HealthStatus, ListingState
from snowlight.sources.stations.registry import load_registry

FIXTURES = Path(__file__).parent / "fixtures" / "gray"
PAGE_URL = "https://www.wbtv.com/weather/closings/"
EXPORT = "https://s3.amazonaws.com/grayfilestore-wbtv/closingsData/closings_WBTV.json"
EXPORT_CAPTURED = EXPORT + "?rnd=409036&arc-site=wbtv"
PAGE_STAMP, EXPORT_STAMP = "20260127221950", "20260127221952"


def _page() -> bytes:
    return (FIXTURES / "wbtv-20260127221950.html").read_bytes()


def _export() -> bytes:
    return (FIXTURES / "wbtv-export-20260127221952.json").read_bytes()


def _registry(tmp_path: Path, *, access: str = "unread", data_url: str | None = EXPORT) -> Path:
    folder = tmp_path / "sources"
    folder.mkdir(exist_ok=True)
    evidence = [
        {
            "url": "https://demo.test/terms",
            "read_at": "2026-09-25T00:00:00Z",
            "sha256": None,
            "excerpt": ["synthetic"],
        }
    ]
    platform = {
        "id": "graydemo",
        "name": "Demo (synthetic)",
        "operator": "Nobody",
        "adapter": "gray",
        "poll_minutes": 10,
        "terms": {
            "automated_access": access,
            "summary": "synthetic",
            "evidence": evidence if access != "unread" else [],
        },
        "notes": "synthetic",
    }
    station = {
        "id": "graydemo-wbtv",
        "platform": "graydemo",
        "call_sign": "WBTV",
        "name": "synthetic",
        "market": "Charlotte",
        "dma": None,
        "states": ["NC"],
        "counties": {"basis": "observed", "source": "synthetic", "fips": ["37119"]},
        "page_url": PAGE_URL,
        "data_url": data_url,
        "archive_urls": [PAGE_URL, EXPORT],
        "poll_minutes": None,
        "status": "active",
        "evidence": "synthetic",
    }
    content = {"platform": platform, "stations": [station]}
    (folder / "graydemo.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    return folder


def _artifact(tmp_path: Path, captures: Sequence[tuple[str, str, bytes]]) -> Path:
    """Lay out (timestamp, URL, body) captures the way the archive workflow writes them."""
    root = tmp_path / "artifact"
    snaps = root / "snapshots"
    snaps.mkdir(parents=True)
    records: list[Mapping[str, object]] = []
    for number, (stamp, url, body) in enumerate(captures):
        name = f"snapshots/{number}.body"
        (root / name).write_bytes(body)
        records.append(
            {
                "timestamp": stamp,
                "url": url,
                "requested": f"https://web.archive.org/web/{stamp}id_/{url}",
                "retrieved_at": "2026-09-25T08:13:02Z",
                "final_timestamp": stamp,
                "final_original": url,
                "http_status": 200,
                "file": name,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    lines = "".join(json.dumps(record) + "\n" for record in records)
    (snaps / "manifest.jsonl").write_text(lines, encoding="utf-8")
    return root


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%d%H%M%S")


def test_a_count_only_page_is_read_through_the_export_captured_with_it(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    root = _artifact(
        tmp_path,
        [(PAGE_STAMP, PAGE_URL, _page()), (EXPORT_STAMP, EXPORT_CAPTURED, _export())],
    )
    result = archive.parse_snapshots(registry, root)
    assert result.failures == []
    (read,) = result.reads
    assert read.url == EXPORT_CAPTURED
    assert read.variant == "gray-s3-json"
    assert read.rows == 55
    assert read.fetched_at == datetime(2026, 1, 27, 22, 19, 52, tzinfo=UTC)
    (hop,) = read.via
    assert hop.url == PAGE_URL
    assert hop.variant == "gray-fusion-count"
    assert hop.state is ListingState.COUNT_ONLY
    assert hop.declared_count == 55
    assert hop.count_matches is True
    assert hop.follows == EXPORT
    assert hop.gap_seconds == 2
    assert hop.fetched_at == datetime(2026, 1, 27, 22, 19, 50, tzinfo=UTC)
    (health,) = result.health
    assert (health.status, health.rows, health.via_url) == (HealthStatus.OK, 55, PAGE_URL)
    assert len(result.rows) == 55
    assert {row.fetched_at for row in result.rows} == {read.fetched_at}
    assert (result.rows[0].raw_name, result.rows[-1].raw_name) == (
        "Alleghany County Schools",
        "Kellex",
    )
    assert len(result.snapshots) == 2
    assert archive.follow_summary(result.reads) == {
        "followed": 1,
        "followed_with_rows": 1,
        "counts_checked": 1,
        "counts_matching": 1,
    }


def test_the_page_says_when_its_count_was_made(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    root = _artifact(
        tmp_path,
        [(PAGE_STAMP, PAGE_URL, _page()), (EXPORT_STAMP, EXPORT_CAPTURED, _export())],
    )
    (hop,) = archive.parse_snapshots(registry, root).reads[0].via
    # "lastModified":1769552197878 in the page's gsync-closings cache entry.
    assert hop.count_at == datetime(2026, 1, 27, 22, 16, 37, tzinfo=UTC)


def test_synthetic_count_that_differs_from_a_list_captured_as_it_was_made_is_a_failure(
    tmp_path: Path,
) -> None:
    # The count is edited, and so is its time: one second before the export capture.
    made = int(datetime(2026, 1, 27, 22, 19, 51, tzinfo=UTC).timestamp()) * 1000
    synthetic_page = (
        _page()
        .replace(b'"totalResults":55', b'"totalResults":54')
        .replace(b'"lastModified":1769552197878', f'"lastModified":{made}'.encode())
    )
    assert synthetic_page != _page()
    registry = load_registry(_registry(tmp_path))
    root = _artifact(
        tmp_path,
        [(PAGE_STAMP, PAGE_URL, synthetic_page), (EXPORT_STAMP, EXPORT_CAPTURED, _export())],
    )
    result = archive.parse_snapshots(registry, root)
    (hop,) = result.reads[0].via
    assert hop.count_matches is False
    (failure,) = result.failures
    assert "counts 54 (as of 2026-01-27T22:19:51Z)" in failure
    assert "lists 55" in failure


def test_synthetic_count_made_minutes_before_the_list_is_recorded_not_failed(
    tmp_path: Path,
) -> None:
    # The real count was made at 22:16:37, 195 s before the export was captured: a
    # list can change in that time (on storm mornings it does), so a difference is
    # reported, not failed.
    synthetic_page = _page().replace(b'"totalResults":55', b'"totalResults":54')
    registry = load_registry(_registry(tmp_path))
    root = _artifact(
        tmp_path,
        [(PAGE_STAMP, PAGE_URL, synthetic_page), (EXPORT_STAMP, EXPORT_CAPTURED, _export())],
    )
    result = archive.parse_snapshots(registry, root)
    assert result.failures == []
    assert archive.count_differences(result.reads) == [
        "graydemo-wbtv 2026-01-27T22:19:50Z: the page counts 54 as of 2026-01-27T22:16:37Z; "
        "the list captured 195 s later (2026-01-27T22:19:52Z) holds 55"
    ]


def test_a_count_that_differs_from_a_later_export_is_recorded_not_failed(tmp_path: Path) -> None:
    later = datetime(2026, 1, 27, 22, 19, 52, tzinfo=UTC) + timedelta(hours=5)
    synthetic_page = _page().replace(b'"totalResults":55', b'"totalResults":54')
    registry = load_registry(_registry(tmp_path))
    root = _artifact(
        tmp_path,
        [(PAGE_STAMP, PAGE_URL, synthetic_page), (_stamp(later), EXPORT_CAPTURED, _export())],
    )
    result = archive.parse_snapshots(registry, root)
    assert result.failures == []
    (hop,) = result.reads[0].via
    assert (hop.count_matches, hop.gap_seconds) == (False, 5 * 3600 + 2)


def test_an_export_captured_beyond_the_window_is_read_on_its_own(tmp_path: Path) -> None:
    later = datetime(2026, 1, 27, 22, 19, 50, tzinfo=UTC) + archive.FOLLOW_WINDOW
    registry = load_registry(_registry(tmp_path))
    root = _artifact(
        tmp_path,
        [
            (PAGE_STAMP, PAGE_URL, _page()),
            (_stamp(later + timedelta(seconds=1)), EXPORT_CAPTURED, _export()),
        ],
    )
    result = archive.parse_snapshots(registry, root)
    page, export = result.health
    assert page.status is HealthStatus.ERROR
    assert "only a count (55 listed)" in (page.reason or "")
    assert "+6.0 h away" in (page.reason or "")
    assert "no CDX listing in the artifacts names a capture of it" in (page.reason or "")
    assert (export.status, export.rows, export.via_url) == (HealthStatus.OK, 55, None)
    assert [read.via for read in result.reads] == [(), ()]


def _listing(root: Path, rows: Sequence[tuple[str, str, str]]) -> None:
    """Write a CDX listing (timestamp, original, status) as the workflow's cdx artifact does."""
    folder = root / "cdx-1"
    folder.mkdir()
    table = [list(archive.CDX_FIELDS)] + [
        [stamp, url, status, "application/json", "900", "SYNTHETICDIGEST"]
        for stamp, url, status in rows
    ]
    (folder / "listing.json").write_text(json.dumps(table), encoding="utf-8")


def test_a_page_says_when_the_archive_holds_no_list_file_near_it(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    root = _artifact(tmp_path, [(PAGE_STAMP, PAGE_URL, _page())])
    _listing(
        root,
        [
            ("20251213100723", EXPORT + "?rnd=1&arc-site=wbtv", "200"),
            ("20260128081755", EXPORT + "?rnd=2&arc-site=wbtv", "404"),
            ("20260203050920", EXPORT + "?rnd=3&arc-site=wbtv", "-"),
        ],
    )
    result = archive.parse_snapshots(registry, root)
    (page,) = result.health
    reason = page.reason or ""
    assert f"no capture of {EXPORT} was downloaded" in reason
    assert "the archive lists 2 captures of it, none within 6 h of this page" in reason
    assert "(nearest +150.8 h, 2026-02-03T05:09:20Z)" in reason
    assert archive.unread_summary(result.health) == {
        "count only, list file not in the archive near it": 1
    }


def test_a_page_says_when_a_list_file_near_it_is_listed_but_not_downloaded(
    tmp_path: Path,
) -> None:
    registry = load_registry(_registry(tmp_path))
    root = _artifact(tmp_path, [(PAGE_STAMP, PAGE_URL, _page())])
    _listing(root, [(EXPORT_STAMP, EXPORT_CAPTURED, "200")])
    result = archive.parse_snapshots(registry, root)
    (page,) = result.health
    assert "lists a capture of it +0.0 h away (2026-01-27T22:19:52Z), within 6 h" in (
        page.reason or ""
    )
    assert archive.unread_summary(result.health) == {
        "count only, list file listed near it but not downloaded": 1
    }


def test_a_page_whose_station_names_no_export_says_so(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path, data_url=None))
    result = archive.parse_snapshots(
        registry, _artifact(tmp_path, [(PAGE_STAMP, PAGE_URL, _page())])
    )
    (page,) = result.health
    assert "names no file to follow" in (page.reason or "")


def test_a_page_with_no_capture_of_its_export_says_so(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    result = archive.parse_snapshots(
        registry, _artifact(tmp_path, [(PAGE_STAMP, PAGE_URL, _page())])
    )
    (page,) = result.health
    assert f"no capture of {EXPORT} was downloaded" in (page.reason or "")


def test_each_export_capture_pairs_with_one_page_closest_first(tmp_path: Path) -> None:
    page_time = datetime(2026, 1, 27, 22, 19, 50, tzinfo=UTC)
    second_page = _stamp(page_time + timedelta(minutes=30))
    registry = load_registry(_registry(tmp_path))
    root = _artifact(
        tmp_path,
        [
            (second_page, PAGE_URL, _page()),
            (PAGE_STAMP, PAGE_URL, _page()),
            (EXPORT_STAMP, EXPORT_CAPTURED, _export()),
        ],
    )
    result = archive.parse_snapshots(registry, root)
    followed = [read for read in result.reads if read.via]
    (read,) = followed
    assert read.via[0].fetched_at == page_time
    alone = [entry for entry in result.health if entry.status is HealthStatus.ERROR]
    assert [entry.checked_at for entry in alone] == [page_time + timedelta(minutes=30)]
    assert len(result.rows) == 55


def test_plan_follow_picks_the_listed_file_nearest_an_unpaired_page(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    root = _artifact(tmp_path, [(PAGE_STAMP, PAGE_URL, _page())])
    _listing(
        root,
        [
            ("20260127080000", EXPORT + "?rnd=1&arc-site=wbtv", "200"),
            (EXPORT_STAMP, EXPORT_CAPTURED, "200"),
            ("20260127221951", EXPORT + "?rnd=3&arc-site=wbtv", "404"),
            (PAGE_STAMP, PAGE_URL, "200"),
        ],
    )
    plan = archive.plan_follow(registry, root)
    # First the export nearest the downloaded page; then, as the station has no
    # populated read yet, its largest winter export captures (the 404 is not
    # replayable, and the downloaded page itself is not asked for again).
    assert plan == [
        {"timestamp": EXPORT_STAMP, "url": EXPORT_CAPTURED},
        {"timestamp": "20260127080000", "url": EXPORT + "?rnd=1&arc-site=wbtv"},
    ]
    assert archive.plan_follow(registry, root, limit=1) == plan[:1]


def test_plan_follow_pairs_winter_files_with_pages_captured_near_them(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path))
    root = _artifact(tmp_path, [])
    _listing(
        root,
        [
            ("20250110120000", EXPORT + "?rnd=1&arc-site=wbtv", "200"),
            ("20250110120001", PAGE_URL, "200"),
            ("20250111120000", EXPORT + "?rnd=2&arc-site=wbtv", "200"),
            ("20250111121000", PAGE_URL, "200"),
            ("20250710120000", EXPORT + "?rnd=4&arc-site=wbtv", "200"),
            ("20250710120001", PAGE_URL, "200"),
        ],
    )
    plan = archive.plan_follow(registry, root)
    # The station has no populated read: first its winter export captures, then each
    # with the page nearest it (within two minutes, else within six hours). July is
    # not winter.
    assert plan == [
        {"timestamp": "20250110120000", "url": EXPORT + "?rnd=1&arc-site=wbtv"},
        {"timestamp": "20250111120000", "url": EXPORT + "?rnd=2&arc-site=wbtv"},
        {"timestamp": "20250110120001", "url": PAGE_URL},
        {"timestamp": "20250111121000", "url": PAGE_URL},
    ]


def test_plan_follow_retries_transient_failures_first_and_unattempted_last(
    tmp_path: Path,
) -> None:
    registry = load_registry(_registry(tmp_path))
    root = _artifact(tmp_path, [])
    base = {"requested": "https://web.archive.org/web/x", "hops": []}
    records = [
        {**base, "timestamp": "20250110120000", "url": PAGE_URL, "error": "HTTP 404"},
        {
            **base,
            "timestamp": "20250110130000",
            "url": PAGE_URL,
            "error": "URLError: <urlopen error _ssl.c:983: The handshake operation timed out>",
        },
        {**base, "timestamp": "20250110140000", "url": PAGE_URL, "error": "HTTP 503"},
        {
            **base,
            "timestamp": "20250110150000",
            "url": PAGE_URL,
            "error": "not attempted: the run's time budget was spent",
        },
    ]
    (root / "snapshots" / "manifest.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    assert archive.retry_requests(root) == [
        ("20250110130000", PAGE_URL),
        ("20250110140000", PAGE_URL),
    ]
    assert archive.plan_follow(registry, root) == [
        {"timestamp": "20250110130000", "url": PAGE_URL},
        {"timestamp": "20250110140000", "url": PAGE_URL},
        {"timestamp": "20250110150000", "url": PAGE_URL},
    ]


def test_cli_archive_plan_follow_prints_requests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _registry(tmp_path)
    root = _artifact(tmp_path, [(PAGE_STAMP, PAGE_URL, _page())])
    _listing(root, [(EXPORT_STAMP, EXPORT_CAPTURED, "200")])
    args = ["stations", "--registry", str(folder), "archive", "plan-follow", str(root), "--by-size"]
    assert main(args) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == {"snapshots": [{"timestamp": EXPORT_STAMP, "url": EXPORT_CAPTURED}]}


def test_cli_archive_parse_reports_followed_pages(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _registry(tmp_path)
    root = _artifact(
        tmp_path,
        [(PAGE_STAMP, PAGE_URL, _page()), (EXPORT_STAMP, EXPORT_CAPTURED, _export())],
    )
    out = tmp_path / "out"
    args = ["stations", "--registry", str(folder), "archive", "parse", str(root)]
    assert main([*args, "--out-dir", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "1 pages read through the file they load (1 with rows)" in printed
    assert "1 of 1 page counts match" in printed
    (line,) = (out / "reads.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["via"][0]["count_matches"] is True


# Live ---------------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 27, 22, 19, 50, tzinfo=UTC)
        self.mono = 0.0

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


def _client(tmp_path: Path, handler: httpx.MockTransport) -> PoliteClient:
    ticker = _Clock()
    timing = Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep)
    return PoliteClient(
        httpx.Client(transport=handler), ConditionalStore(tmp_path / "cache"), timing=timing
    )


def _live(export: bytes | None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "www.wbtv.com":
            return httpx.Response(200, content=_page())
        if export is not None and request.url.path.endswith("closings_WBTV.json"):
            return httpx.Response(200, content=export)
        return httpx.Response(503)

    return httpx.MockTransport(handler)


def test_live_count_only_page_with_no_data_url_is_an_error_that_says_so(tmp_path: Path) -> None:
    registry = load_registry(_registry(tmp_path, access="permitted", data_url=None))
    station = registry.stations["graydemo-wbtv"]
    client = _client(tmp_path, _live(_export()))
    result = fetch.read_station(registry, station, client, datetime(2026, 1, 27, tzinfo=UTC))
    (health,) = result.health
    assert health.status is HealthStatus.ERROR
    assert "only a count (55 listed)" in (health.reason or "")
    assert [str(snap.url) for snap in result.snapshots] == [PAGE_URL]


def test_real_frame_page_is_read_through_the_grid_it_framed(tmp_path: Path) -> None:
    # WJRT's abc12.com closings page captured 2022-02-03 03:53:16 framed
    # ftp2.wjrt.com's grid, captured three seconds later (both real fixtures).
    page_url = "https://www.abc12.com/weather/closings/"
    grid_url = "https://ftp2.wjrt.com/school_closings/wjrtclosings.html"
    root = _artifact(
        tmp_path,
        [
            ("20220203035316", page_url, (FIXTURES / "wjrt-20220203035316.html").read_bytes()),
            ("20220203035319", grid_url, (FIXTURES / "wjrt-file-20220203035319.html").read_bytes()),
        ],
    )
    result = archive.parse_snapshots(load_registry(), root)
    assert result.failures == []
    (read,) = result.reads
    assert (read.source_id, read.url, read.variant, read.rows) == (
        "gray-wjrt",
        grid_url,
        "gray-file-grid",
        216,
    )
    (hop,) = read.via
    assert (hop.url, hop.variant, hop.follows, hop.gap_seconds) == (
        page_url,
        "gray-frame",
        grid_url,
        3,
    )
    assert hop.count_matches is None
    (health,) = result.health
    assert (health.status, health.rows, health.via_url) == (HealthStatus.OK, 216, page_url)
    assert {row.fetched_at for row in result.rows} == {datetime(2022, 2, 3, 3, 53, 19, tzinfo=UTC)}
    assert result.rows[0].raw_name == "Akron/Fairgrove Schools"


def test_shared_application_captures_are_set_aside(tmp_path: Path) -> None:
    shell = "https://webpubcontent.raycommedia.com/raycom/gsync/"
    root = _artifact(tmp_path, [("20191116212553", shell, b"<title>GSync Web Embeds</title>")])
    result = archive.parse_snapshots(load_registry(), root)
    assert result.set_aside == [f"20191116212553 {shell}"]
    assert (result.health, result.reads, result.failures) == ([], [], [])


FRAMED = "https://ftp2.wbtv.test/closings.html"
"""A synthetic list file for the planner tests (never downloaded)."""


def _with_list_file(folder: Path) -> Path:
    """Give the synthetic station a framed list file as well as its export."""
    path = folder / "graydemo.yaml"
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    station = content["stations"][0]
    station["archive_urls"] = [*station["archive_urls"], FRAMED]
    station["list_files"] = [{"url": FRAMED, "loaded_by": "frame", "seen": "synthetic"}]
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
    return folder


def test_plan_follow_orders_list_file_pairs_before_export_pairs(tmp_path: Path) -> None:
    registry = load_registry(_with_list_file(_registry(tmp_path)))
    root = _artifact(tmp_path, [])
    _listing(
        root,
        [
            ("20200110120000", FRAMED, "200"),
            ("20200110150000", PAGE_URL, "200"),  # the list file's page, 3 h later
            ("20200710120000", FRAMED, "200"),  # not winter
            ("20210110120000", EXPORT + "?rnd=1", "200"),
            ("20210110120030", PAGE_URL, "200"),
        ],
    )
    plan = archive.plan_follow(registry, root)
    assert plan == [
        # 3: the framed file and the page nearest it
        {"timestamp": "20200110120000", "url": FRAMED},
        {"timestamp": "20200110150000", "url": PAGE_URL},
        # 4: the station has no populated read: its other winter list file capture
        {"timestamp": "20210110120000", "url": EXPORT + "?rnd=1"},
        # 5: the export with the page captured 30 s after it
        {"timestamp": "20210110120030", "url": PAGE_URL},
    ]


def test_plan_follow_asks_populated_stations_only_for_older_export_pairs(
    tmp_path: Path,
) -> None:
    registry = load_registry(_registry(tmp_path))
    # The WBTV export (55 rows) is downloaded, so the station has a populated read.
    root = _artifact(tmp_path, [(EXPORT_STAMP, EXPORT_CAPTURED, _export())])
    _listing(
        root,
        [
            ("20210110120000", EXPORT + "?rnd=1", "200"),
            ("20210110120030", PAGE_URL, "200"),
            ("20250110120000", EXPORT + "?rnd=2", "200"),
            ("20250110120030", PAGE_URL, "200"),
        ],
    )
    assert archive.plan_follow(registry, root) == [
        {"timestamp": "20210110120000", "url": EXPORT + "?rnd=1"},
        {"timestamp": "20210110120030", "url": PAGE_URL},
    ]

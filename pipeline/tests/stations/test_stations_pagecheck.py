"""Page checks: choosing each station's data_url from what its page loaded.

The page records here are synthetic (the shape pagecheck.cjs writes, with made-up
times and texts); the registry is the real one, copied to a temporary folder.
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from snowlight.cli import main
from snowlight.sources.stations import pagecheck
from snowlight.sources.stations.http import USER_AGENT
from snowlight.sources.stations.registry import DEFAULT_REGISTRY_DIR, load_registry

EXPORT = "https://s3.amazonaws.com/grayfilestore-wfsb/closingsData/closings_WFSB.json"
FRAME = "https://webpubcontent.gray.tv/wfsb/xml/WFSBclosings.html"


def _synthetic_record(station_id: str, url: str, responses: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": station_id,
        "url": url,
        "final_url": url,
        "started": "2026-09-26T22:48:50.123Z",
        "error": None,
        "responses": responses,
        "frames": [
            {"url": url, "text": "Closings Types All States All No closings are listed."},
            {"url": FRAME + "?app_data=x", "text": "UPDATED SATURDAY\nSynthetic Church: Closed"},
        ],
    }


def _response(url: str, kind: str, status: int = 200) -> dict[str, Any]:
    return {"url": url, "status": status, "type": kind, "last_modified": None}


def test_a_framed_file_wins_over_an_export_the_page_also_fetched() -> None:
    station = load_registry().stations["gray-wfsb"]
    record = _synthetic_record(
        station.id,
        "https://www.wfsb.com/weather/closings/",
        [
            _response(EXPORT + "?rnd=1&arc-site=wfsb", "xhr"),
            _response(FRAME + "?app_data=x", "document"),
            _response("https://webpubcontent.gray.tv/gray/arc-fusion-assets/a.html", "document"),
        ],
    )
    decision = pagecheck.decide(station, [record])
    assert decision.data_url == FRAME
    assert decision.loaded_by == "frame"
    assert decision.loads == (EXPORT, FRAME)
    assert decision.check is not None
    assert decision.check.shows == "The framed list: UPDATED SATURDAY Synthetic Church: Closed"
    assert decision.check.checked_at.isoformat() == "2026-09-26T22:48:50+00:00"


def test_an_export_alone_is_the_list_and_failed_loads_do_not_count() -> None:
    station = load_registry().stations["gray-kctv"]
    kctv = "https://s3.amazonaws.com/grayfilestore-kctv/closingsData/closings_KCTV.json"
    record = _synthetic_record(
        station.id,
        "https://www.kctv5.com/weather/closings/",
        [_response(FRAME, "document", status=403), _response(kctv + "?rnd=2", "xhr")],
    )
    decision = pagecheck.decide(station, [record])
    assert (decision.data_url, decision.loaded_by, decision.loads) == (kctv, "script", (kctv,))


def test_a_page_that_loads_nothing_or_cannot_be_opened_is_left_for_review() -> None:
    station = load_registry().stations["gray-kctv"]
    empty = _synthetic_record(station.id, "https://www.kctv5.com/weather/closings/", [])
    decision = pagecheck.decide(station, [empty])
    assert (decision.data_url, decision.note) == (None, "the page loaded no list file")
    assert decision.check is not None
    assert decision.check.shows == "The page's closings area: No closings are listed."
    broken = {**empty, "error": "TimeoutError"}
    assert pagecheck.decide(station, [broken]).note == "no closings page could be opened"


def test_apply_writes_the_data_url_page_check_and_list_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "sources"
    folder.mkdir()
    for name in ("gray.yaml", "hearst.yaml"):
        shutil.copy(DEFAULT_REGISTRY_DIR / name, folder / name)
    check_dir = tmp_path / "check"
    (check_dir / "pages").mkdir(parents=True)
    kctv = "https://s3.amazonaws.com/grayfilestore-kctv/closingsData/closings_KCTV.json"
    other = "https://webpubcontent.gray.tv/kctv/xml/KCTVclosings.html"  # synthetic
    record = _synthetic_record(
        "gray-kctv",
        "https://www.kctv5.com/weather/closings/",
        [_response(kctv, "xhr"), _response(other, "document")],
    )
    (check_dir / "pages" / "gray-kctv.json").write_text(json.dumps([record]), encoding="utf-8")
    args = ["stations", "--registry", str(folder), "pagecheck", "apply", str(check_dir)]
    assert main([*args, "--write"]) == 0
    assert f"gray-kctv: loads {other}" in capsys.readouterr().out
    station = load_registry(folder).stations["gray-kctv"]
    assert station.data_url == other
    assert station.export == kctv
    assert station.page_check is not None
    assert station.page_check.loads == (kctv, other)
    assert other in station.archive_urls
    assert [f.loaded_by for f in station.list_files if f.url == other] == ["frame"]


def test_targets_name_every_active_gray_page_with_the_projects_user_agent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["stations", "pagecheck", "targets"]) == 0
    targets = json.loads(capsys.readouterr().out)
    registry = load_registry()
    assert len(targets) == sum(1 for s in registry.active() if s.platform == "gray")
    assert {t["user_agent"] for t in targets} == {USER_AGENT}
    assert "jsalcards" in USER_AGENT

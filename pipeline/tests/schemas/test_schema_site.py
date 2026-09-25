"""validate_site: the pre-publish check of a whole site-data folder."""

import json
import shutil
from pathlib import Path
from typing import Annotated, Any

import pytest
from pydantic import StringConstraints

from schemas.helpers import example, example_path
from snowlight.schemas.base import PublishedModel
from snowlight.schemas.export import main
from snowlight.schemas.registry import PUBLISHED_FILES
from snowlight.schemas.site import SiteReport, _load, validate_site


def _site(tmp_path: Path) -> Path:
    """A site-data folder holding every synthetic example at its published path."""
    root = tmp_path / "site-data"
    for entry in PUBLISHED_FILES:
        path = entry.path.replace("{id}", example("replay")["id"])
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(example_path(entry.name), target)
    return root


def _write(root: Path, path: str, value: Any) -> None:
    (root / path).write_text(json.dumps(value), encoding="utf-8")


def test_a_consistent_site_passes(tmp_path: Path) -> None:
    report = validate_site(_site(tmp_path))
    assert report.problems == []
    assert sorted(report.checked) == sorted(
        entry.path.replace("{id}", "2026-12-18") for entry in PUBLISHED_FILES
    )
    assert report.published() == sorted(report.checked)
    assert (report.scanned, report.unchecked, report.skipped) == ([], [], [])


def test_an_empty_site_has_nothing_to_check(tmp_path: Path) -> None:
    report = validate_site(tmp_path)
    assert (report.checked, report.problems) == ([], [])
    assert validate_site(tmp_path / "missing") == SiteReport()


class _TwoWords(PublishedModel):
    """A model whose pattern is looser than the byte scan: two lowercase words."""

    label: Annotated[str, StringConstraints(pattern=r"^[a-z]+ [a-z]+$")]


def test_the_byte_scan_backs_up_a_loose_model(tmp_path: Path) -> None:
    path = tmp_path / "label.json"
    path.write_text('{"label":"census bureau"}', encoding="utf-8")
    report = SiteReport()
    assert _load(_TwoWords, path, "label.json", report) is None
    assert report.problems == [
        "label.json: published file names a source or address: 'census bureau'"
    ]
    path.write_text('{"label":"snow day"}', encoding="utf-8")
    assert _load(_TwoWords, path, "label.json", report) == _TwoWords(label="snow day")
    assert report.checked == ["label.json"]


def test_an_invalid_file_is_reported_with_its_first_problem(tmp_path: Path) -> None:
    root = _site(tmp_path)
    value = example("closings")
    value["days"][0]["statuses"][0] = 9
    _write(root, "live/closings.json", value)
    report = validate_site(root)
    assert report.problems == [
        "live/closings.json: 1 problem(s); first at days.0.statuses.0: Input should be 0, 1, 2 or 3"
    ]


def test_a_repeated_key_is_reported(tmp_path: Path) -> None:
    root = _site(tmp_path)
    text = (root / "live" / "covered.json").read_text(encoding="utf-8")
    (root / "live" / "covered.json").write_text(
        text.replace('"ranges"', '"ranges": [], "ranges"', 1), encoding="utf-8"
    )
    assert validate_site(root).problems == [
        'live/covered.json: 1 problem(s); first: an object repeats the key "ranges"'
    ]


def test_every_file_in_the_folder_is_accounted_for(tmp_path: Path) -> None:
    root = _site(tmp_path)
    (root / "schools" / "points.bin").write_bytes(bytes(range(256)))
    (root / "search").mkdir()
    (root / "search" / "cities.jsonl").write_text(
        '{"name":"Synthetic City","state":"IA"}\n', encoding="utf-8"
    )
    (root / "schools" / "manifest.internal.json").write_text(
        '{"url":"https://example.com/directory.zip"}', encoding="utf-8"
    )
    report = validate_site(root)
    assert report.problems == []
    assert report.scanned == ["search/cities.jsonl"]
    assert report.unchecked == ["schools/points.bin"]
    assert report.skipped == ["schools/manifest.internal.json"]
    assert "schools/manifest.internal.json" not in report.published()
    assert "schools/points.bin" in report.published()


@pytest.mark.parametrize(
    "path",
    [
        "schools/manifest.json",
        "live/closings.json.bak",
        "replays/2026-12-18/frames.json",
        ".DS_Store",
        "search/extra.jsonl",
    ],
)
def test_a_file_nothing_reads_is_reported(tmp_path: Path, path: str) -> None:
    root = _site(tmp_path)
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text('{"source":"https://example.com"}', encoding="utf-8")
    (problem,) = validate_site(root).problems
    assert problem.startswith(f"{path}: not a published file")


def test_other_published_text_is_scanned(tmp_path: Path) -> None:
    root = _site(tmp_path)
    (root / "search").mkdir()
    (root / "search" / "zips.jsonl").write_text(
        '{"zcta":"00000","note":"see www.example.org"}\n', encoding="utf-8"
    )
    (root / "search" / "cities.jsonl").write_bytes(b"\xff\xfe")
    problems = validate_site(root).problems
    assert len(problems) == 2
    assert problems[0].startswith("search/cities.jsonl: ")
    assert problems[1].startswith("search/zips.jsonl: published file names a source")


def test_a_source_in_a_name_is_reported(tmp_path: Path) -> None:
    root = _site(tmp_path)
    value = example("school-directory")
    value["names"][0] = "Synthetic School (www.example.org)"
    _write(root, "schools/meta.json", value)
    (problem,) = validate_site(root).problems
    assert problem.startswith("schools/meta.json: 1 problem(s); first at names.0")
    assert "names a source or address" in problem


def test_indexes_must_point_into_the_published_directory(tmp_path: Path) -> None:
    root = _site(tmp_path)
    value = example("predictions")
    value["directory"]["generated_on"] = "2026-09-01"
    _write(root, "predictions/latest.json", value)
    (problem,) = validate_site(root).problems
    assert problem.startswith("predictions: indexes directory")
    (root / "schools" / "meta.json").unlink()
    assert validate_site(root).problems == [
        "schools/meta.json is missing, so no index can be checked"
    ]


def test_live_files_are_published_together(tmp_path: Path) -> None:
    root = _site(tmp_path)
    _write(root, "live/covered.json", example("covered") | {"generated_at": "2027-01-12T13:06:00Z"})
    assert validate_site(root).problems == [
        "closings.json and covered.json have different generated_at"
    ]
    (root / "live" / "covered.json").unlink()
    assert validate_site(root).problems == [
        "live/closings.json and live/covered.json are published together"
    ]


def test_replays_and_their_index_agree(tmp_path: Path) -> None:
    root = _site(tmp_path)
    replays = root / "replays"
    shutil.copy(replays / "2026-12-18.json", replays / "2026-12-19.json")
    problems = validate_site(root).problems
    assert "replays/2026-12-19.json: holds replay 2026-12-18" in problems
    assert "replays/2026-12-19.json is not in replays/index.json" in problems
    (replays / "2026-12-19.json").write_text("{}", encoding="utf-8")
    (problem,) = validate_site(root).problems
    assert problem.startswith("replays/2026-12-19.json: 8 problem(s); first at schema_version")
    (replays / "2026-12-19.json").unlink()
    (replays / "2026-12-18.json").unlink()
    assert validate_site(root).problems == [
        "replays/index.json lists 2026-12-18, which has no file"
    ]


def test_a_summary_that_disagrees_with_its_replay_is_reported(tmp_path: Path) -> None:
    root = _site(tmp_path)
    index = example("replay-index")
    index["replays"][0]["schools"] = 5
    _write(root, "replays/index.json", index)
    assert validate_site(root).problems == ["replay 2026-12-18: the summary's schools disagree"]
    (root / "replays" / "index.json").unlink()
    assert validate_site(root).problems == ["replay files are published without replays/index.json"]


def test_cli_validate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _site(tmp_path)
    (root / "schools" / "points.bin").write_bytes(b"\x00")
    (root / "schools" / "manifest.internal.json").write_text("{}", encoding="utf-8")
    (root / "search").mkdir()
    (root / "search" / "cities.jsonl").write_text("{}\n", encoding="utf-8")
    assert main(["--validate", str(root)]) == 0
    out = capsys.readouterr().out
    assert "ok: live/closings.json" in out
    assert "ok, text scanned: search/cities.jsonl" in out
    assert "published, checked by its builder: schools/points.bin" in out
    assert "skipped, never published: schools/manifest.internal.json" in out
    (root / "live" / "covered.json").unlink()
    assert main(["--validate", str(root)]) == 1
    assert "published together" in capsys.readouterr().err
    assert main(["--validate", str(tmp_path / "missing")]) == 1
    assert "is not a folder" in capsys.readouterr().err

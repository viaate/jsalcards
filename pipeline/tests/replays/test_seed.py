"""The derived seed: its shape, its bytes, its provenance, and that no list text reaches it."""

import ast
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import shapely
from pydantic import ValidationError

from replays.world import DAY, World, disk_counties, ids, school, station, utc
from snowlight.output import JSONValue
from snowlight.replays.build import build_day, built_for
from snowlight.replays.seed import (
    MATCHER_FILES,
    RULES_FILES,
    ReplaySeed,
    archive_sha256,
    counties_sha256,
    files_sha256,
    matcher_sha256,
    read_seed,
    reader_sha256,
    registry_sha256,
    rules_sha256,
    unsafe_strings,
    write_seed,
    zones_sha256,
)

PIPELINE = Path(__file__).resolve().parents[2]
MORN = utc("2024-01-16 05:26")
NAMES = ("SYNTHETIC Quillfeather Elementary", "SYNTHETIC Marrowbrook Academy")
BUILT = built_for(
    rules_sha256="e" * 64,
    reader_sha256="a" * 64,
    matcher_sha256="b" * 64,
    registry_sha256="c" * 64,
    archive_sha256="d" * 64,
    zones_sha256="f" * 64,
    directory_generated_on="2026-09-24",
)


def _seed() -> ReplaySeed:
    a, b = ids("0020", 2)
    private = "A9900001"
    world = World(stations=[station("gray-a"), station("gray-b", market="SYNTHETIC two")])
    world.add_schools(school(a), school(b), school(private, public=False, status=None))
    world.row("gray-a", MORN, "closed;on=2024-01-16", name=NAMES[0], direct=[a, private])
    world.row("gray-b", MORN, "remote;on=2024-01-16;reason=Ice", name=NAMES[1], direct=[b])
    return build_day(DAY, world.inputs(), built=BUILT).seed


def test_the_seed_shape() -> None:
    seed = _seed().as_json()
    assert isinstance(seed, dict)
    assert set(seed) == {"schema_version", "id", "day", "built", "quality", "statuses"}
    built = seed["built"]
    assert isinstance(built, dict)
    assert set(built) == {
        "rules",
        "rules_sha256",
        "min_confidence",
        "allowed_notes",
        "reader_sha256",
        "matcher_sha256",
        "registry_sha256",
        "archive_sha256",
        "zones_sha256",
        "directory_generated_on",
    }
    assert built["rules"] == "replay-1"
    assert built["min_confidence"] == 0.8
    assert built["allowed_notes"] == ["undated", "unread_words"]
    assert seed["quality"] == {
        "lit": 3,
        "sources": 2,
        "markets": 2,
        "corroborated": 0,
        "conflicts": 0,
    }
    a, b = ids("0020", 2)
    assert seed["statuses"] == [
        [a, 0, 0, "station_list"],
        [b, 2, 1, "station_list"],
        ["A9900001", 0, 0, "station_list"],
    ]


def test_no_list_text_station_or_time_reaches_the_seed() -> None:
    seed = _seed().as_json()
    assert unsafe_strings(seed) == []
    text = json.dumps(seed)
    for word in (*NAMES, "gray-a", "gray-b", "SYNTHETIC", MORN, "closed", "remote"):
        assert word not in text


def test_the_raw_text_scan_flags_text() -> None:
    seed = _seed().as_json()
    assert isinstance(seed, dict)
    statuses = seed["statuses"]
    assert isinstance(statuses, list)
    statuses.append(["Closed Tuesday", 0, None, "station_list"])
    values: list[JSONValue] = ["gray-kctv", "2024-01-16T11:26:00Z", "ok", {"k": ["Closed"]}]
    assert unsafe_strings(seed) == ["Closed Tuesday"]
    assert unsafe_strings(values) == ["gray-kctv", "2024-01-16T11:26:00Z", "ok", "Closed"]


@pytest.mark.parametrize(
    "text",
    [
        "CLOSEDXX",
        "SNOWDAYS",
        "CANCELED",
        "2024-01-16\n",
        "990020000001\n",
        "undated\n",
        "AB1234567",
        "20240116",  # a compact date: not a private-school id
        "12345678",
        "1A123456",
    ],
)
def test_the_raw_text_scan_takes_each_string_whole(text: str) -> None:
    """Eight capitals are not a private-school id, and a trailing newline is not part of a form."""
    assert unsafe_strings([text]) == [text]


@pytest.mark.parametrize(
    "sid", ["990020000001", "A9900001", "AB990001", "00000033", "01990001", "99000001"]
)
def test_the_scan_takes_each_id_form_the_directory_holds(sid: str) -> None:
    assert unsafe_strings([sid]) == []


def test_seed_writes_are_byte_identical(tmp_path: Path) -> None:
    seed = _seed()
    write_seed(tmp_path / "one.json", seed)
    write_seed(tmp_path / "two.json", _seed())
    assert (tmp_path / "one.json").read_bytes() == (tmp_path / "two.json").read_bytes()
    assert read_seed(tmp_path / "one.json") == seed
    assert (tmp_path / "one.json").read_bytes().startswith(b'{"built":{"allowed_notes"')


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"id": "2024-01-17"}, "id is its day"),
        ({"statuses": [["990020000001", 0, None, "station_list"]] * 2}, "sorted by NCES id"),
        ({"statuses": [["99002000001", 0, None, "station_list"]]}, "pattern"),
        ({"statuses": [["990020000001", 4, None, "station_list"]]}, "less than or equal to 3"),
    ],
)
def test_the_seed_validates(change: dict[str, object], message: str) -> None:
    body = _seed().as_json()
    assert isinstance(body, dict)
    body.update(change)  # type: ignore[arg-type]
    if "statuses" in change:
        body["quality"]["lit"] = len(change["statuses"])  # type: ignore[arg-type, call-overload, index]
    with pytest.raises(ValidationError, match=message):
        ReplaySeed.model_validate_json(json.dumps(body))


def test_the_lit_count_must_match() -> None:
    body = _seed().as_json()
    assert isinstance(body, dict)
    body["quality"]["lit"] = 2  # type: ignore[call-overload, index]
    with pytest.raises(ValidationError, match="counts the statuses"):
        ReplaySeed.model_validate_json(json.dumps(body))


def test_files_hash_by_relative_path_and_bytes(tmp_path: Path) -> None:
    one = tmp_path / "one"
    (one / "snowlight" / "classify").mkdir(parents=True)
    (one / "snowlight" / "classify" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (one / "snowlight" / "classify" / "b.py").write_text("B = 2\n", encoding="utf-8")
    two = tmp_path / "elsewhere" / "two"
    shutil.copytree(one, two)
    assert reader_sha256(one) == reader_sha256(two)
    (two / "snowlight" / "classify" / "b.py").write_text("B = 3\n", encoding="utf-8")
    assert reader_sha256(one) != reader_sha256(two)
    (two / "snowlight" / "classify" / "b.py").rename(two / "snowlight" / "classify" / "c.py")
    assert reader_sha256(two) != reader_sha256(one)
    with pytest.raises(FileNotFoundError):
        files_sha256(tmp_path, ("nothing/*.py",))


def test_the_input_hashes_of_this_tree(tmp_path: Path) -> None:
    assert len(MATCHER_FILES) == 6
    assert "snowlight/listed/located.py" in MATCHER_FILES
    aliases = PIPELINE / "config" / "aliases.yaml"
    assert len(matcher_sha256(PIPELINE, aliases)) == 64
    other = tmp_path / "aliases.yaml"
    other.write_text("schema_version: 1\nmarkets: {}\n", encoding="utf-8")
    assert matcher_sha256(PIPELINE, other) != matcher_sha256(PIPELINE, aliases)
    copy = tmp_path / "copy.yaml"
    shutil.copyfile(aliases, copy)
    assert matcher_sha256(PIPELINE, copy) == matcher_sha256(PIPELINE, aliases)
    assert len(rules_sha256(PIPELINE)) == 64
    assert "snowlight/schemas/vocab.py" in RULES_FILES
    assert "snowlight/weights/zones.py" in RULES_FILES
    assert "snowlight/sources/stations/registry.py" in RULES_FILES
    assert zones_sha256(["b", "a"]) == zones_sha256(["a", "b"]) != zones_sha256(["a"])
    assert len(registry_sha256(PIPELINE / "config" / "sources")) == 64
    (tmp_path / "reads.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "rows.jsonl").write_text("{}\n", encoding="utf-8")
    first = archive_sha256(tmp_path)
    (tmp_path / "rows.jsonl").write_text("{}\n{}\n", encoding="utf-8")
    assert archive_sha256(tmp_path) != first


def test_the_counties_the_place_guard_read_are_pinned_by_content() -> None:
    counties = disk_counties()
    same = counties_sha256(disk_counties())
    assert counties_sha256(counties) == same
    moved = dict(counties.counties)
    first = moved["29095"]
    moved["29095"] = replace(first, geometry=shapely.box(-94.7, 38.8, -94.2, 39.4))
    assert counties_sha256(replace(counties, counties=moved)) != same
    renamed = {**counties.counties, "29095": replace(first, name="SYNTHETIC other")}
    assert counties_sha256(replace(counties, counties=renamed)) != same
    assert counties_sha256(None) != same
    aliases = PIPELINE / "config" / "aliases.yaml"
    pinned = matcher_sha256(PIPELINE, aliases, same)
    assert pinned != matcher_sha256(PIPELINE, aliases)
    assert pinned != matcher_sha256(PIPELINE, aliases, counties_sha256(None))


def test_the_rules_hash_covers_every_county_reader_the_boundaries_module_uses() -> None:
    """The county and zone readers decide which zone a school's day is read in; only the HTTP
    cache, which fetches the files the zones hash already pins, is left out."""
    tree = ast.parse((PIPELINE / "snowlight/sources/nws/boundaries.py").read_text("utf-8"))
    modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    used = {module for module in modules if module and module.startswith("snowlight.sources.")}
    fetch = {"snowlight/sources/nws/http.py"}
    files = {module.replace(".", "/") + ".py" for module in used} - fetch
    assert files
    assert files <= set(RULES_FILES)

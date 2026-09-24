"""Tests for the deterministic, atomic output writers."""

import json
import math
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from snowlight.output import JSONValue, dumps_json, write_bytes_atomic, write_json

json_values: st.SearchStrategy[JSONValue] = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda children: st.lists(children) | st.dictionaries(st.text(), children),
    max_leaves=25,
)


@given(json_values)
def test_dumps_json_round_trips(value: JSONValue) -> None:
    assert json.loads(dumps_json(value).decode("utf-8")) == value


@given(st.dictionaries(st.text(), st.integers()))
def test_dumps_json_ignores_insertion_order(mapping: dict[str, int]) -> None:
    reordered = dict(reversed(list(mapping.items())))
    assert dumps_json(dict(mapping)) == dumps_json(dict(reordered))


def test_dumps_json_is_compact_utf8() -> None:
    assert dumps_json({"b": 1, "a": ["Ñandú", None]}) == '{"a":["Ñandú",null],"b":1}'.encode()


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_dumps_json_refuses_non_finite_floats(bad: float) -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        dumps_json({"value": bad})


def test_write_json_creates_parents_and_writes(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "schools.json"
    write_json(target, {"count": 3})
    assert target.read_bytes() == b'{"count":3}'
    assert target.stat().st_mode & 0o777 == 0o644


def test_write_json_failure_keeps_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "status.json"
    write_json(target, {"ok": True})
    with pytest.raises(ValueError, match="JSON compliant"):
        write_json(target, {"ok": math.nan})
    assert target.read_bytes() == b'{"ok":true}'
    assert sorted(p.name for p in tmp_path.iterdir()) == ["status.json"]


def test_write_bytes_atomic_replaces_and_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "points.bin"
    write_bytes_atomic(target, b"\x00\x01")
    write_bytes_atomic(target, b"\x02")
    assert target.read_bytes() == b"\x02"
    assert [p.name for p in tmp_path.iterdir()] == ["points.bin"]


def test_write_bytes_atomic_cleans_up_when_rename_fails(tmp_path: Path) -> None:
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "child").write_text("keeps the directory non-empty")
    with pytest.raises(OSError, match="occupied"):
        write_bytes_atomic(target, b"data")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["occupied"]

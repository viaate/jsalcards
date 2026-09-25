"""Round trips: every synthetic example parses strictly and serializes back unchanged."""

import json

import pytest
from pydantic import ValidationError

from schemas.helpers import EXAMPLES, example, example_path
from snowlight.output import dumps_json
from snowlight.schemas.registry import PUBLISHED_FILES, PublishedFile


def test_every_published_file_has_exactly_one_example() -> None:
    names = sorted(path.stem.removeprefix("synthetic-") for path in EXAMPLES.glob("*.json"))
    assert names == sorted(entry.name for entry in PUBLISHED_FILES)
    assert all(path.name.startswith("synthetic-") for path in EXAMPLES.glob("*.json"))


def test_example_round_trips_byte_for_byte(entry: PublishedFile) -> None:
    raw = example_path(entry.name).read_bytes()
    document = entry.model.from_json_bytes(raw)
    written = document.to_json_bytes()
    assert written == dumps_json(json.loads(raw))
    assert entry.model.from_json_bytes(written) == document


def test_example_validates_as_python_value_too(entry: PublishedFile) -> None:
    document = entry.model.from_json_bytes(example_path(entry.name).read_bytes())
    assert entry.model.model_validate(document.model_dump()) == document


def test_written_bytes_are_compact_sorted_utf8(entry: PublishedFile) -> None:
    written = entry.model.from_json_bytes(example_path(entry.name).read_bytes()).to_json_bytes()
    assert b"\n" not in written
    assert b", " not in written
    assert b": " not in written
    value = json.loads(written)
    assert list(value) == sorted(value)


def test_documents_are_immutable(entry: PublishedFile) -> None:
    document = entry.model.from_json_bytes(example_path(entry.name).read_bytes())
    field = next(iter(type(document).model_fields))
    with pytest.raises(ValidationError, match="frozen"):
        setattr(document, field, None)


def test_every_field_is_required(entry: PublishedFile) -> None:
    value = example(entry.name)
    for key in list(value):
        partial = {k: v for k, v in value.items() if k != key}
        with pytest.raises(ValidationError, match="missing"):
            entry.model.from_json_bytes(json.dumps(partial))

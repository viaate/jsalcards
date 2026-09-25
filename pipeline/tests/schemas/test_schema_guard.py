"""Published models cannot carry a source name or an address, by construction and in practice.

Three layers are tested:

1. The class guard: defining a published model with a source-like field name, a
   URL type, free text that is neither screened nor patterned, a dict, ``Any``,
   a nested internal model, a code or literal named after a source, or a number
   literal that would also accept ``true`` fails at class creation.
2. The documents: adding a source-like key anywhere in any example, repeating a
   key, or putting an address or a source's name in any text value, fails
   validation.
3. The generated artifacts: no property in schemas/ or the TypeScript names a source.
"""

import copy
import dataclasses
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import Enum, IntEnum
from pathlib import Path
from typing import Annotated, Any, Literal

import pytest
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    HttpUrl,
    PlainSerializer,
    StringConstraints,
    ValidationError,
)

from schemas.helpers import example
from snowlight.schemas import internal
from snowlight.schemas.base import (
    EXACT_INT,
    SCREENED,
    InternalModel,
    PublishedContentError,
    PublishedModel,
    check_published_bytes,
    exact_int,
    forbidden_in_name,
    name_parts,
    repeated_keys,
    screen_text,
)
from snowlight.schemas.export import REPO_ROOT, SCHEMA_DIR, json_schema
from snowlight.schemas.live import Closing
from snowlight.schemas.registry import PUBLISHED_FILES, PublishedFile
from snowlight.schemas.scalars import DirectoryName, SchemaVersion
from snowlight.schemas.vocab import Reason, Status

GENERATED_TS = REPO_ROOT / "web" / "src" / "types" / "generated" / "index.ts"

# Text that must never get into a published value.
PROBES = (
    "https://example.com/closings",
    "http://example.org",
    "www.example.org/schools",
    "closings.example.com",
    "alerts@example.com",
    "National Weather Service",
    "Data from NCES",
    "Common Core of Data",
    "Iowa Environmental Mesonet",
    "Gray Media",
    "NOAA",
)

# Keys that would carry provenance if a published object accepted them.
INJECTED_KEYS = ("source", "source_url", "url", "sourceName", "provenance", "link", "feed")


def published_models() -> list[type[PublishedModel]]:
    """Every published model reachable from the registry, each once."""
    seen: dict[str, type[PublishedModel]] = {}

    def visit(model: type[BaseModel]) -> None:
        assert issubclass(model, PublishedModel), model
        if model.__qualname__ in seen:
            return
        seen[model.__qualname__] = model
        for info in model.model_fields.values():
            for nested in _models_in(info.annotation):
                visit(nested)

    for entry in PUBLISHED_FILES:
        visit(entry.model)
    return list(seen.values())


def _models_in(annotation: Any) -> Iterator[type[BaseModel]]:
    value = getattr(annotation, "__value__", None)
    if value is not None:
        yield from _models_in(value)
        return
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for arg in getattr(annotation, "__args__", ()):
        yield from _models_in(arg)


# 1. The class guard ------------------------------------------------------------------


def test_every_published_model_is_forbidding_frozen_and_strict() -> None:
    models = published_models()
    assert len(models) >= len(PUBLISHED_FILES)
    for model in models:
        config = model.model_config
        assert config.get("extra") == "forbid", model
        assert config.get("frozen") is True, model
        assert config.get("strict") is True, model


def _define(**fields: Any) -> type[PublishedModel]:
    namespace: dict[str, Any] = {"__annotations__": {}}
    for name, spec in fields.items():
        if isinstance(spec, tuple):
            namespace["__annotations__"][name] = spec[0]
            namespace[name] = spec[1]
        else:
            namespace["__annotations__"][name] = spec
    return type("Candidate", (PublishedModel,), namespace)


Pattern = Annotated[str, StringConstraints(pattern=r"^[a-z]+$")]


class Provenance(InternalModel):
    """An internal record, for the nesting test."""

    source_id: str


class Feed(IntEnum):
    """Codes named after a source, for the enum test."""

    NWS = 0


class Outlet(Enum):
    """Codes whose values are addresses, for the enum test."""

    MAIN = "https://example.com/closings"


class SourceKind(IntEnum):
    """A code whose name is a source word, for the enum test."""

    SOURCE_URL = 0


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"source_url": Pattern}, "may not be named"),
        ({"source": int}, "may not be named"),
        ({"feedLink": Pattern}, "may not be named"),
        ({"attribution": Pattern}, "may not be named"),
        ({"snapshot_at": datetime}, "may not be named"),
        ({"station": Pattern}, "may not be named"),
        ({"label": (int, Field(alias="sourceName"))}, "may not be named"),
        ({"imageURLs": Pattern}, "may not be named"),
        ({"homepage_link_text": Pattern}, "may not be named"),
        ({"hrefs": Pattern}, "may not be named"),
        ({"page": Annotated[str, StringConstraints(pattern=r"^https?://\S+$")]}, "admits"),
        ({"code": Annotated[str, StringConstraints(pattern=r"^[A-Za-z ]+$")]}, "admits"),
        ({"domainish": Annotated[str, StringConstraints(pattern=r"\.")]}, "admits"),
        ({"note": str}, "free text"),
        ({"note": Annotated[str, StringConstraints(min_length=1)]}, "free text"),
        ({"notes": tuple[str, ...]}, "free text"),
        ({"note": str | None}, "free text"),
        ({"home": HttpUrl}, "cannot appear"),
        ({"extra_info": dict[str, int]}, "cannot appear"),
        ({"anything": Any}, "cannot appear"),
        ({"items": list[int]}, "cannot appear"),
        ({"blob": bytes}, "cannot appear"),
        ({"record": Provenance}, "cannot appear"),
        ({"records": tuple[Provenance, ...]}, "cannot appear"),
        ({"version": Literal[1]}, "also matches true"),
        ({"version": Annotated[Literal[1], BeforeValidator(exact_int)]}, "also matches true"),
        ({"version": Annotated[Literal[1], EXACT_INT]}, "also matches true"),
        ({"version": Annotated[Literal[1], BeforeValidator(int), EXACT_INT]}, "also matches true"),
        ({"note": Annotated[str, SCREENED]}, "needs AfterValidator"),
        ({"note": Annotated[str, AfterValidator(str.strip), SCREENED]}, "needs AfterValidator"),
        ({"flag": Literal[True]}, "cannot appear"),
        ({"ratio": Literal[0.5]}, "cannot appear"),
        ({"kind": Literal["nws"]}, "names a source"),
        ({"kind": Literal["ok", "source_url"]}, "may not be named"),
        ({"kind": Literal["www.example.org"]}, "names a source"),
        ({"code": Feed}, "names a source"),
        ({"code": Outlet}, "may not be named"),
        ({"code": SourceKind}, "may not be named"),
        ({"codes": tuple[Feed | None, ...]}, "names a source"),
        ({"code": Annotated[str, StringConstraints(pattern=r"^[A-Z]{4}(?: \d{1,2})?$")]}, "admits"),
    ],
)
def test_guard_refuses_fields_that_could_carry_a_source(
    fields: dict[str, Any], message: str
) -> None:
    with pytest.raises(TypeError, match=message):
        _define(**fields)


def test_guard_refuses_a_model_that_allows_extra_keys() -> None:
    with pytest.raises(TypeError, match="forbid extra"):
        type(
            "Loose",
            (PublishedModel,),
            {"__annotations__": {"n": int}, "model_config": ConfigDict(extra="allow")},
        )


def test_guard_accepts_the_allowed_kinds_of_field() -> None:
    model = _define(
        count=int,
        chance=float,
        flag=bool,
        when=datetime,
        code=Pattern,
        name=DirectoryName,
        maybe=int | None,
        rows=tuple[tuple[int, Pattern], ...],
        version=SchemaVersion,
        exact=Annotated[Literal[2], BeforeValidator(exact_int), EXACT_INT],
        state=Literal["forecast", "no_threat"],
        status=Status,
    )
    assert set(model.model_fields) == {
        "count",
        "chance",
        "flag",
        "when",
        "code",
        "name",
        "maybe",
        "rows",
        "version",
        "exact",
        "state",
        "status",
    }
    assert repr(EXACT_INT) == "EXACT_INT"


@pytest.mark.parametrize(
    ("name", "parts"),
    [
        ("source_url", ["source", "url"]),
        ("sourceURL", ["source", "url"]),
        ("feedLink", ["feed", "link"]),
        ("asOf", ["as", "of"]),
        ("p_no_school", ["p", "no", "school"]),
        ("lead_days", ["lead", "days"]),
        ("imageURLs", ["image", "urls"]),
        ("schoolIDs", ["school", "ids"]),
        ("HTTPServer", ["http", "server"]),
    ],
)
def test_name_parts_splits_snake_and_camel_case(name: str, parts: list[str]) -> None:
    assert name_parts(name) == parts


def test_internal_models_do_carry_provenance() -> None:
    fields = set(internal.ClosingObservation.model_fields)
    assert {"source_id", "source_url", "snapshot_at"} <= fields
    assert {"source_id", "url", "fetched_at"} <= set(internal.SourceSnapshot.model_fields)


# 2. The documents --------------------------------------------------------------------


def _objects(value: Any, path: tuple[Any, ...] = ()) -> Iterator[tuple[Any, ...]]:
    if isinstance(value, dict):
        yield path
        for key, item in value.items():
            yield from _objects(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _objects(item, (*path, index))


def _strings(value: Any, path: tuple[Any, ...] = ()) -> Iterator[tuple[Any, ...]]:
    if isinstance(value, str):
        yield path
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, (*path, index))


def _at(value: Any, path: tuple[Any, ...]) -> Any:
    for step in path:
        value = value[step]
    return value


def test_every_object_in_every_example_refuses_a_source_key(entry: PublishedFile) -> None:
    document = example(entry.name)
    paths = list(_objects(document))
    assert paths
    for path in paths:
        for key in INJECTED_KEYS:
            tampered = copy.deepcopy(document)
            _at(tampered, path)[key] = "Synthetic Source"
            with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
                entry.model.from_json_bytes(json.dumps(tampered))


def test_every_object_in_every_example_refuses_a_repeated_key(entry: PublishedFile) -> None:
    document = example(entry.name)
    paths = list(_objects(document))
    for path in paths:
        target = _at(document, path)
        if not target:
            continue
        key = next(iter(target))
        text = json.dumps(document, separators=(",", ":"))
        # Re-serialize with the first key of this object written twice.
        marker = "\u0000repeat\u0000"
        tampered = copy.deepcopy(document)
        _at(tampered, path)[marker] = None
        raw = json.dumps(tampered, separators=(",", ":"))
        repeat = f"{json.dumps(key)}:{json.dumps(target[key], separators=(',', ':'))}"
        raw = raw.replace(f"{json.dumps(marker)}:null", repeat)
        assert json.loads(raw) == document
        assert raw != text
        with pytest.raises(ValidationError, match=f"repeats the key {re.escape(json.dumps(key))}"):
            entry.model.from_json_bytes(raw)


def test_repeated_keys_are_found_at_any_depth() -> None:
    assert repeated_keys(b'{"a":1,"b":{"c":[{"d":1,"d":2}]}}') == ["d"]
    assert repeated_keys('{"a":1,"a":1,"b":2,"b":3}') == ["a", "b"]
    assert repeated_keys(b'[{"a":1},{"a":2}]') == []


def test_every_text_value_in_every_example_refuses_addresses_and_source_names(
    entry: PublishedFile,
) -> None:
    document = example(entry.name)
    paths = list(_strings(document))
    assert paths
    for path in paths:
        for probe in PROBES:
            tampered = copy.deepcopy(document)
            _at(tampered, path[:-1])[path[-1]] = probe
            with pytest.raises(ValidationError):
                entry.model.from_json_bytes(json.dumps(tampered))


@pytest.mark.parametrize("probe", PROBES)
def test_screen_text_refuses_probes(probe: str) -> None:
    with pytest.raises(PublishedContentError):
        screen_text(probe)


@pytest.mark.parametrize(
    "name",
    [
        "Synthetic Elementary School",
        "St. Synthetic's Academy",
        "Synthetic Jr./Sr. High School",
        "Escuela Sintética Número 3",
        "Synthetic-Example Community Unit School District 300",
        "Synthetic Hearst Elementary",
        "Synthetic Newsome Middle School",
        "Synthetic School of Science & Technology",
    ],
)
def test_screen_text_accepts_names_shaped_like_school_names(name: str) -> None:
    assert screen_text(name) == name


def test_screen_text_refuses_control_characters() -> None:
    with pytest.raises(PublishedContentError, match="control"):
        screen_text("Synthetic\nSchool")


def test_check_published_bytes_scans_the_whole_document() -> None:
    check_published_bytes(b'{"names":["Synthetic School"]}')
    with pytest.raises(PublishedContentError, match=r"weather\.gov"):
        check_published_bytes(b'{"x":"see weather.gov"}')


def test_internal_observation_projects_to_a_closing_without_provenance() -> None:
    observation = internal.ClosingObservation(
        school_index=3,
        school_id="000000000004",
        status=Status.CLOSED,
        day=datetime(2027, 1, 12, tzinfo=UTC).date(),
        announced_at=datetime(2027, 1, 12, 10, 42, tzinfo=UTC),
        reason=Reason.ICE,
        shift_minutes=None,
        clock_minute=None,
        source_id="synthetic-source",
        source_url=HttpUrl("https://example.com/synthetic"),
        snapshot_at=datetime(2027, 1, 12, 11, 0, tzinfo=UTC),
        listing_text="Synthetic Academy D: Closed",
    )
    closing = observation.closing()
    assert isinstance(closing, Closing)
    fields = {field.name for field in dataclasses.fields(closing)}
    assert not any(forbidden_in_name(name) for name in fields)
    text = json.dumps(dataclasses.asdict(closing), default=str)
    assert "example.com" not in text
    assert "synthetic-source" not in text
    assert "Closed" not in text


# 3. The generated artifacts ----------------------------------------------------------


def _property_names(schema: Any) -> Iterator[str]:
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                yield from value
            yield from _property_names(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from _property_names(item)


def _objects_in_schema(schema: Any) -> Iterator[dict[str, Any]]:
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from _objects_in_schema(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from _objects_in_schema(item)


def test_exported_schemas_close_every_object_and_name_no_source(entry: PublishedFile) -> None:
    schema = json_schema(entry)
    objects = list(_objects_in_schema(schema))
    assert objects
    for node in objects:
        assert node.get("additionalProperties") is False, node.get("title")
    for name in _property_names(schema):
        assert not forbidden_in_name(name), name


def test_schema_files_and_typescript_name_no_source_field() -> None:
    texts = [path.read_text(encoding="utf-8") for path in sorted(SCHEMA_DIR.glob("*.json"))]
    for text in texts:
        for name in _property_names(json.loads(text)):
            assert not forbidden_in_name(name), name
    declared = re.findall(r"^\s+readonly (\w+)\??:", _typescript(), flags=re.MULTILINE)
    assert declared
    for name in declared:
        assert not forbidden_in_name(name), name


def _typescript() -> str:
    path: Path = GENERATED_TS
    return path.read_text(encoding="utf-8")


def test_to_json_bytes_refuses_a_lossy_serializer() -> None:
    lossy = _define(count=Annotated[int, PlainSerializer(lambda value: value + 1, return_type=int)])
    with pytest.raises(ValueError, match="does not round-trip"):
        lossy.model_validate({"count": 1}).to_json_bytes()
    assert repr(SCREENED) == "SCREENED"

"""The two kinds of model, and the guard that keeps sources out of published files.

:class:`PublishedModel` describes a file the website downloads, or a part of one.
:class:`InternalModel` describes a record the pipeline keeps for itself, such as a
fetch of a source or one source's listing for one school; those carry source ids,
URLs and snapshot times, and nothing published may hold them.

The guard is structural. When a subclass of :class:`PublishedModel` is defined,
:func:`check_published_fields` inspects every field and raises :class:`TypeError`
before the class can be used if

* a field's name, or its JSON alias, contains a word from :data:`FORBIDDEN_NAME_PARTS`
  (``source``, ``url``, ``link``, ``provenance``, ``snapshot`` and so on) or, even
  inside a longer word, ``url``, ``href``, ``http``, ``provenance`` or ``attribution``;
* a field's type is anything but a closed set of plain types: ``int``, ``float``,
  ``bool``, ``None``, ``date``, ``datetime``, :class:`~enum.Enum` members,
  ``Literal`` values, tuples of those, other published models, and ``str`` only
  when its values pass through :func:`screen_text` (marked with :data:`SCREENED`
  and ``AfterValidator(screen_text)``, both required) or it carries a ``pattern``
  that refuses every one of :data:`PATTERN_PROBES`
  (web and email addresses, source names, broadcast call signs). URL types, dicts
  (free-form keys), ``Any``, internal models and every other type are refused;
* an enum member's name, or a ``Literal`` text value, names a source or an
  address (so ``Literal["nws"]`` fails as ``source`` does);
* a ``Literal`` holds a number without :data:`EXACT_INT` and
  ``BeforeValidator(exact_int)``. Pydantic matches ``Literal[1]`` by equality, so
  even in strict mode it would take ``true`` and ``1.0`` for ``1``;
  :func:`exact_int` refuses anything but a JSON integer.

Every published model also forbids extra keys (``extra="forbid"``), so a document
with a ``source`` key fails validation, and is frozen and strict: a file that says
``"12"`` where the contract says ``12`` is rejected, not quietly coerced.

:meth:`PublishedModel.from_json_bytes` is the one way to read a published file: it
validates strictly and also refuses an object that repeats a key (JSON parsers
keep the last copy silently, so a repeated key could hide a value from review).
:meth:`PublishedModel.to_json_bytes` is the one way to serialize one: compact,
key-sorted UTF-8 (:func:`snowlight.output.dumps_json`), then parsed back strictly
and compared, then scanned by :func:`check_published_bytes`.
"""

import json
import re
import types
from collections import Counter
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal, Self, TypeAliasType, Union, get_args, get_origin

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import InitErrorDetails, PydanticCustomError

from snowlight.output import JSONValue, dumps_json

# Words that name where data came from. A published field may not be called by any of
# them, in snake_case or camelCase ("source_id", "sourceUrl" and "feedLink" all fail).
FORBIDDEN_NAME_PARTS: frozenset[str] = frozenset(
    {
        "attribution",
        "credit",
        "credits",
        "crawl",
        "domain",
        "feed",
        "fetched",
        "host",
        "href",
        "link",
        "links",
        "origin",
        "provenance",
        "publisher",
        "referrer",
        "retrieved",
        "scraped",
        "snapshot",
        "source",
        "sources",
        "station",
        "uri",
        "url",
        "urls",
    }
)

# Text a published file must never contain. Web addresses in any form, and the names
# of the organizations and services Snowlight reads. Only names that cannot also be
# a school's or district's name are listed ("Hearst" names a broadcaster and several
# schools, so it is not here); the structural guard above is what keeps provenance
# out, this is the second line.
_URL_PATTERNS = (
    r"[a-z][a-z0-9+.-]*://",
    r"\bwww\.",
    r"\b[a-z0-9-]+\.(?:com|org|net|gov|edu|us|io|info|tv|fm|news)\b",
    r"\b[\w.+-]+@[a-z0-9-]+\.[a-z]",
)
_SOURCE_NAMES = (
    r"\bnces\b",
    r"national center for education statistics",
    r"common core of data",
    r"private school (?:universe )?survey",
    r"\bedge geocod",
    r"census bureau",
    r"national weather service",
    r"\bnoaa\b",
    r"\bnws\b",
    r"weather\.gov",
    r"environmental mesonet",
    r"\bgray media\b",
    r"\bgsync\b",
    r"\bnexstar\b",
    r"\btegna\b",
    r"\bflashalert\b",
    r"newsroom solutions",
    r"\btownnews\b",
    r"\bopenfreemap\b",
    r"\bopenstreetmap\b",
    r"\bopen-meteo\b",
)
_FORBIDDEN_TEXT = re.compile("|".join((*_URL_PATTERNS, *_SOURCE_NAMES)), re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# Words in a name: an acronym with a plural s (URLs), an acronym, a word, a number.
_NAME_WORDS = re.compile(r"[A-Z]+s(?![a-z])|[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
# Stems refused anywhere in a name, even inside a longer word.
_FORBIDDEN_STEMS = ("url", "href", "http", "provenance", "attribution")
# Values that a pattern-constrained published string must refuse.
PATTERN_PROBES: tuple[str, ...] = (
    "https://example.com/closings",
    "http://example.org",
    "www.example.org",
    "example.com",
    "someone@example.com",
    "National Weather Service",
    "NCES",
    "NOAA",
    "WGAL 8",
    "KCCI",
)
_SCALARS: tuple[type, ...] = (int, float, bool, type(None), date, datetime)


class PublishedContentError(ValueError):
    """Text in a published file names a source or carries a web address."""


class ScreenedText:
    """Marks a ``str`` type whose values pass through :func:`screen_text`.

    Pydantic ignores this marker; :func:`check_published_fields` looks for it.
    """

    def __repr__(self) -> str:
        return "SCREENED"


SCREENED = ScreenedText()


class ExactInteger:
    """Marks a numeric ``Literal`` whose values pass through :func:`exact_int`.

    Pydantic ignores this marker; :func:`check_published_fields` looks for it.
    """

    def __repr__(self) -> str:
        return "EXACT_INT"


EXACT_INT = ExactInteger()


def exact_int(value: Any) -> Any:
    """Refuse ``true``, ``1.0`` and other values that equal an integer without being one.

    Used as a ``BeforeValidator`` in front of an integer ``Literal``, together with
    :data:`EXACT_INT`.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"expected a JSON integer, not {value!r}")
    return value


def screen_text(value: str) -> str:
    """Return ``value`` if it can appear in a published file.

    Raises:
        PublishedContentError: ``value`` holds a control character, a web or email
            address, or the name of a data source.
    """
    if _CONTROL.search(value):
        raise PublishedContentError(f"text holds a control character: {value!r}")
    found = _FORBIDDEN_TEXT.search(value)
    if found:
        raise PublishedContentError(f"text names a source or address ({found.group(0)!r})")
    return value


def check_published_bytes(data: bytes) -> None:
    """Refuse a serialized published file that names a source or carries an address.

    Raises:
        PublishedContentError: if :func:`screen_text` would refuse any part of it.
    """
    found = _FORBIDDEN_TEXT.search(data.decode("utf-8"))
    if found:
        raise PublishedContentError(f"published file names a source or address: {found.group(0)!r}")


def repeated_keys(data: bytes | str) -> list[str]:
    """Return the keys that some object in the JSON text ``data`` holds twice, sorted."""
    repeated: set[str] = set()

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        counts = Counter(key for key, _ in items)
        repeated.update(key for key, count in counts.items() if count > 1)
        return dict(items)

    json.loads(data, object_pairs_hook=pairs)
    return sorted(repeated)


def name_parts(name: str) -> list[str]:
    """Split a snake_case or camelCase name into lowercase words."""
    return [word.lower() for word in _NAME_WORDS.findall(name)]


def _patterns(metadata: list[Any]) -> list[str]:
    found = [getattr(item, "pattern", None) for item in metadata]
    return [pattern for pattern in found if isinstance(pattern, str)]


def forbidden_in_name(name: str) -> list[str]:
    """The source-like words and stems in a field name, if any."""
    lowered = name.lower()
    words = FORBIDDEN_NAME_PARTS.intersection(name_parts(name))
    stems = {stem for stem in _FORBIDDEN_STEMS if stem in lowered}
    return sorted(words | stems)


def _annotated_metadata(metadata: list[Any]) -> list[Any]:
    """Flatten FieldInfo objects (from ``Field(...)`` inside ``Annotated``) into metadata."""
    flat: list[Any] = []
    for item in metadata:
        if isinstance(item, FieldInfo):
            flat.extend(item.metadata)
        else:
            flat.append(item)
    return flat


def _has_validator(metadata: list[Any], kind: type, func: Any) -> bool:
    """Whether ``metadata`` holds ``kind(func)``, such as ``AfterValidator(screen_text)``."""
    return any(isinstance(item, kind) and getattr(item, "func", None) is func for item in metadata)


def _check_word(word: str, where: str) -> None:
    """Raise TypeError if a code name or literal value names a source or an address."""
    banned = forbidden_in_name(word)
    if banned:
        raise TypeError(f"{where}: a published value may not be named {banned}")
    try:
        screen_text(word)
    except PublishedContentError as error:
        raise TypeError(f"{where}: {error}") from None


def _check_literal(values: tuple[Any, ...], where: str, metadata: list[Any]) -> None:
    """Raise TypeError unless every ``Literal`` value is safe text or an exact integer."""
    for value in values:
        if isinstance(value, str) and not isinstance(value, Enum):
            _check_word(value, where)
        elif isinstance(value, int) and not isinstance(value, (bool, Enum)):
            if EXACT_INT not in metadata or not _has_validator(
                metadata, BeforeValidator, exact_int
            ):
                raise TypeError(
                    f"{where}: Literal[{value!r}] also matches true and {value!r}.0; "
                    "add BeforeValidator(exact_int) and EXACT_INT"
                )
        else:
            raise TypeError(f"{where}: Literal[{value!r}] cannot appear in a published file")


def _check_leaf(annotation: Any, where: str, metadata: list[Any]) -> None:
    """Raise TypeError unless a type with no type arguments is allowed."""
    if annotation is str:
        if SCREENED in metadata:
            if not _has_validator(metadata, AfterValidator, screen_text):
                raise TypeError(f"{where}: SCREENED text needs AfterValidator(screen_text)")
            return
        patterns = _patterns(metadata)
        if not patterns:
            raise TypeError(f"{where}: free text must be screened or match a pattern")
        for pattern in patterns:
            admitted = [probe for probe in PATTERN_PROBES if re.search(pattern, probe)]
            if admitted:
                raise TypeError(f"{where}: pattern {pattern!r} admits {admitted[0]!r}")
        return
    if annotation in _SCALARS:
        return
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        for member in annotation:
            _check_word(member.name, f"{where}: {annotation.__name__}.{member.name}")
            if isinstance(member.value, str):
                _check_word(member.value, f"{where}: {annotation.__name__}.{member.name}")
        return
    if isinstance(annotation, type) and issubclass(annotation, PublishedModel):
        return  # checked when it was defined
    raise TypeError(f"{where}: {annotation!r} cannot appear in a published file")


def _check_type(annotation: Any, where: str, metadata: list[Any]) -> None:
    """Raise TypeError unless ``annotation`` is allowed in a published model."""
    if isinstance(annotation, TypeAliasType):
        _check_type(annotation.__value__, where, metadata)
        return
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Annotated:
        _check_type(args[0], where, [*metadata, *_annotated_metadata(list(args[1:]))])
    elif origin is Literal:
        _check_literal(args, where, metadata)
    elif origin in (Union, types.UnionType):
        for arg in args:
            _check_type(arg, where, metadata)
    elif origin is tuple:
        for arg in args:
            if arg is not Ellipsis:
                _check_type(arg, where, [])
    elif origin is None:
        _check_leaf(annotation, where, metadata)
    else:
        raise TypeError(f"{where}: {annotation!r} cannot appear in a published file")


def check_published_fields(model: type[BaseModel]) -> None:
    """Raise TypeError if any field of ``model`` could carry a source or address.

    See the module docstring for the rules.
    """
    config = model.model_config
    if config.get("extra") != "forbid":
        raise TypeError(f"{model.__name__}: published models must forbid extra keys")
    for name, info in model.model_fields.items():
        where = f"{model.__name__}.{name}"
        for label in {name, info.alias or name, info.serialization_alias or name}:
            banned = forbidden_in_name(label)
            if banned:
                raise TypeError(f"{where}: a published field may not be named {banned}")
        _check_type(info.annotation, where, list(info.metadata))


class PublishedModel(BaseModel):
    """A file the website downloads, or part of one. See the module docstring."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
        serialize_by_alias=True,
    )

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Run the structural guard on every published model as it is defined."""
        super().__pydantic_init_subclass__(**kwargs)
        check_published_fields(cls)

    def to_json_value(self) -> JSONValue:
        """Return the document as plain JSON values (wire names, codes, ISO text)."""
        value: JSONValue = self.model_dump(mode="json")
        return value

    def to_json_bytes(self) -> bytes:
        """Serialize for publishing: compact, key-sorted UTF-8 that parses back to ``self``.

        Raises:
            PublishedContentError: if the bytes would name a source or hold an address.
            ValueError: if the bytes do not parse back to an equal document.
        """
        data = dumps_json(self.to_json_value())
        if type(self).from_json_bytes(data) != self:
            raise ValueError(f"{type(self).__name__} does not round-trip through JSON")
        check_published_bytes(data)
        return data

    @classmethod
    def from_json_bytes(cls, data: bytes | str) -> Self:
        """Validate a published file strictly (no type coercion) and return it.

        Raises:
            ValidationError: the file does not match the model, or an object in it
                repeats a key.
        """
        document = cls.model_validate_json(data, strict=True)
        repeated = repeated_keys(data)
        if repeated:
            detail = InitErrorDetails(
                type=PydanticCustomError(
                    "duplicate_key",
                    "an object repeats the key {key}",
                    {"key": json.dumps(repeated[0])},
                ),
                loc=(),
                input=repeated[0],
            )
            raise ValidationError.from_exception_data(cls.__name__, [detail])
        return document


class InternalModel(BaseModel):
    """A record the pipeline keeps for itself: never published, free to name sources."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

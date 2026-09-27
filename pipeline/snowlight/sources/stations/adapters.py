"""The adapter registry: one parser per platform, shared by live reads and archived copies.

An adapter is a pure function from one response body to a
:class:`~snowlight.sources.stations.model.Listing`. It sniffs which of its
platform's known formats (variants) the body is in, reads every row, and raises
:class:`~snowlight.sources.stations.model.ShapeError` for anything else, so a
changed page is an error rather than an empty list. The same function reads live
responses and Wayback ``id_`` captures, which are the bytes the station sent.

Adapters are found, not listed. Each platform file in ``pipeline/config/sources/``
names its adapter (``platform.adapter``), and the adapter named ``abc-owned`` is the
``parse`` function of the module ``snowlight.sources.stations.abc_owned`` (a dash
becomes an underscore). That function must take the body as ``bytes`` and return a
``Listing``; a module without one is not an adapter. A module is imported only when
a platform file that is present names it, and only when it is first used, so a
platform ships as its module, its YAML file, its fixtures and its tests, and no
file here changes when a platform is added or left out.
"""

import importlib
import importlib.util
import inspect
import re
import typing
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.sources.stations.model import Listing
from snowlight.sources.stations.registry import DEFAULT_REGISTRY_DIR

PACKAGE = "snowlight.sources.stations"
"""The package every adapter module lives in."""

_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_PLATFORM_DEPTH = 2  # collections open at a key of the platform block: the file, the block

type Adapter = Callable[[bytes], Listing]


def module_name(adapter: str) -> str:
    """Return the module an adapter name refers to (``abc-owned``: ``...stations.abc_owned``).

    Raises:
        KeyError: ``adapter`` is not a lowercase, dash-separated name.
    """
    if not _NAME.fullmatch(adapter):
        raise KeyError(adapter)
    return f"{PACKAGE}.{adapter.replace('-', '_')}"


def _is_adapter(function: object) -> bool:
    """Whether ``function`` takes one body as ``bytes`` and returns a ``Listing``."""
    if not inspect.isfunction(function):
        return False
    try:
        hints = typing.get_type_hints(function)
    except (NameError, TypeError):
        return False
    parameters = list(inspect.signature(function).parameters.values())
    return (
        len(parameters) == 1
        and parameters[0].kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and hints.get(parameters[0].name) is bytes
        and hints.get("return") is Listing
    )


def module_exists(adapter: str) -> bool:
    """Whether the module an adapter name refers to is installed (it is not imported)."""
    try:
        return importlib.util.find_spec(module_name(adapter)) is not None
    except KeyError:
        return False


def load_adapter(adapter: str) -> Adapter:
    """Import the module ``adapter`` names and return its ``parse`` function.

    An error raised while the module itself imports is not caught: a broken module
    is a failure, not a missing platform.

    Raises:
        KeyError: no module has that name, or its ``parse`` is not an adapter.
    """
    if not module_exists(adapter):
        raise KeyError(adapter)
    parse = getattr(importlib.import_module(module_name(adapter)), "parse", None)
    if not _is_adapter(parse):
        raise KeyError(adapter)
    return cast(Adapter, parse)


@dataclass
class _Open:
    """A collection the YAML stream is inside of."""

    mapping: bool
    expecting_key: bool = True
    key: str | None = None


def declared_adapter(path: Path) -> str | None:
    """Return the adapter a platform file names (``platform.adapter``), or None.

    The YAML is read as a stream of events, and only up to that value: a platform
    file starts with its short ``platform`` block and ends with a long list of
    stations the adapter lookup does not need. A file that is not valid YAML, or
    names no adapter, gives None (loading the registry reports why).
    """
    stack: list[_Open] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for event in yaml.parse(stream):
                if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                    stack.append(_Open(mapping=isinstance(event, yaml.MappingStartEvent)))
                    continue
                if isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                    stack.pop()
                    if len(stack) == 1 and stack[0].key == "platform":
                        return None  # the platform block ended without an adapter
                elif isinstance(event, (yaml.ScalarEvent, yaml.AliasEvent)) and stack:
                    value = getattr(event, "value", None)
                    text = value if isinstance(value, str) else None
                    top = stack[-1]
                    if top.mapping and top.expecting_key:
                        top.expecting_key, top.key = False, text
                        continue
                    in_platform = len(stack) == _PLATFORM_DEPTH and stack[0].key == "platform"
                    if in_platform and top.key == "adapter":
                        return text
                else:
                    continue
                if stack and stack[-1].mapping:
                    stack[-1].expecting_key = True  # a value (scalar or collection) was read
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    return None


class AdapterRegistry(Mapping[str, Adapter]):
    """The adapters the platform files in one folder name, imported when first needed.

    The keys are the adapter names the folder's ``*.yaml`` files give whose module
    exists and holds an adapter. A platform file naming an adapter that does not
    exist adds no key, so
    :meth:`~snowlight.sources.stations.registry.Registry.check_adapters` reports it.
    The folder is read, and the modules it names imported, the first time the
    mapping is used, not when it is made.
    """

    def __init__(self, folder: Path = DEFAULT_REGISTRY_DIR) -> None:
        self.folder = folder
        self._names: tuple[str, ...] | None = None
        self._loaded: dict[str, Adapter] = {}

    def names(self) -> tuple[str, ...]:
        """Return the adapter names the folder's platform files give that exist, in order."""
        if self._names is None:
            declared = {
                name
                for path in sorted(self.folder.glob("*.yaml"))
                if (name := declared_adapter(path)) is not None
            }
            found = []
            for name in sorted(declared):
                try:
                    self._loaded[name] = load_adapter(name)
                except KeyError:
                    continue
                found.append(name)
            self._names = tuple(found)
        return self._names

    def __getitem__(self, name: str) -> Adapter:
        if name not in self.names():
            raise KeyError(name)
        return self._loaded[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self.names())

    def __len__(self) -> int:
        return len(self.names())


ADAPTERS: Mapping[str, Adapter] = AdapterRegistry()
"""Adapter name (as a platform's ``adapter`` field gives it) to parser, for the
platform files in ``pipeline/config/sources/``."""


def adapter_for(name: str) -> Adapter:
    """Return the parser the adapter ``name`` refers to, whatever folder named it.

    Raises:
        KeyError: no adapter has that name.
    """
    return load_adapter(name)

"""The chance job's reads of the files our other chains write (predict-next ON-AIR).

The closings reader writes ``live/closings.json``, ``live/opens.json``, the day timelines
(``live/days/<day>.json``) and their index; the chance job reads all four. Their published
models forbid unknown keys, so on Nov 9 2026 a key the reader began to write darkened every
pass of the running chance job for hours. :func:`read` is how the chance job reads them:

* **strictly first**: a file that validates takes today's exact call and gives today's
  object, and nothing else runs;
* **only when every failure is an unknown key**: those keys, which pydantic's own errors
  name at every level, are dropped and what is left is validated again, exactly as strictly
  (the same validators, the model's own rules). An unknown code, an unknown
  ``schema_version``, a missing or repeated key or anything else is refused as before.

Each drop is said once per process per model and place, with counts and our own field paths
only: an unknown key's own name is never printed.

One function per file (:func:`closings`, :func:`opens`, :func:`timeline`, :func:`index`) is
the only caller of :func:`read`, and the one place where a later form of that file is taught
(docs/predict.md, "Staying on air"). Writers, published models and the web stay strict.

:class:`Refused` marks a dark pass whose cause is a file of ours this code cannot read: the
one kind of darkness newer code may cure, which lets the loop end early for a newer branch
head.
"""

import json
import os
import sys
from typing import Any

from pydantic import ValidationError

from snowlight.predict.publish import DarkError
from snowlight.schemas.base import PublishedModel, repeated_keys
from snowlight.schemas.live import ClosingsFile, DayIndex, DayTimeline, OpensFile

PARENTS_SAID = 5
"""At most this many places are named in a warning; the rest are counted."""


class Refused(DarkError):  # noqa: N818 - a marker on a dark pass, named as the docs name it
    """A file one of our other chains wrote that this code cannot read."""


_said: set[tuple[str, tuple[str, ...]]] = set()


def forget() -> None:
    """Forget which drops were said (tests)."""
    _said.clear()


def _refuse_constant(text: str) -> None:
    raise ValueError(f"not JSON: {text}")


def _pruned(data: bytes | str, error: ValidationError) -> tuple[Any, list[tuple[Any, ...]]]:
    """``data`` as a tree without the unknown keys ``error`` names, and the path of each
    key's parent.

    Raises:
        ValueError, LookupError, TypeError: an error is not an unknown key, a key repeats, or a
            path does not resolve.
    """
    errors = error.errors(include_url=False, include_context=False, include_input=False)
    if not errors or any(item["type"] != "extra_forbidden" for item in errors):
        raise ValueError("not only unknown keys")
    if repeated_keys(data):
        raise ValueError("a repeated key")
    tree = json.loads(data, parse_constant=_refuse_constant)
    parents: list[tuple[Any, ...]] = []
    for item in errors:
        *path, key = item["loc"]
        node = tree
        for part in path:
            if isinstance(part, str) and isinstance(node, dict):
                node = node[part]
            elif isinstance(part, int) and not isinstance(part, bool) and isinstance(node, list):
                if part < 0:
                    raise LookupError(part)
                node = node[part]
            else:
                raise LookupError(part)
        if not isinstance(node, dict) or not isinstance(key, str):
            raise LookupError(key)
        del node[key]
        parents.append(tuple(path))
    return tree, parents


def _place(path: tuple[Any, ...]) -> str:
    """A parent's path in our own field names: integers as ``[]``, the root ``(top)``."""
    text = ""
    for part in path:
        if isinstance(part, int):
            text += "[]"
        else:
            text += f".{part}" if text else str(part)
    return text or "(top)"


def _warn(text: str) -> None:
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") == "true" else "warning: "
    sys.stderr.write(prefix + text + "\n")


def read[M: PublishedModel](model: type[M], data: bytes | str, *, where: str) -> M:
    """``data`` as ``model``: strictly, or, when all that is wrong are unknown keys, without
    them (see the module docstring). ``where`` names the file in the warning.

    Raises:
        ValidationError: the file does not validate for any reason but unknown keys, or what
            is left without them does not.
    """
    try:
        return model.from_json_bytes(data)
    except ValidationError as error:
        try:
            tree, parents = _pruned(data, error)
            left = json.dumps(
                tree, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode()
        except Exception:
            raise error from None
    found = model.from_json_bytes(left)
    places = sorted({_place(path) for path in parents})
    key = (model.__name__, tuple(places))
    if key not in _said:
        _said.add(key)
        named = ", ".join(places[:PARENTS_SAID])
        if len(places) > PARENTS_SAID:
            named += f" and {len(places) - PARENTS_SAID} more"
        _warn(
            f"predict: {where}: {len(parents)} unknown keys dropped (in {named}); "
            "the rest validates"
        )
    return found


def closings(data: bytes | str, *, where: str) -> ClosingsFile:
    """``live/closings.json``."""
    return read(ClosingsFile, data, where=where)


def opens(data: bytes | str, *, where: str) -> OpensFile:
    """``live/opens.json``."""
    return read(OpensFile, data, where=where)


def timeline(data: bytes | str, *, where: str) -> DayTimeline:
    """A day timeline, ``live/days/<day>.json``."""
    return read(DayTimeline, data, where=where)


def index(data: bytes | str, *, where: str) -> DayIndex:
    """The day timelines' index, ``live/days/index.json``."""
    return read(DayIndex, data, where=where)

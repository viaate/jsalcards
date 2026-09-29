"""Nuxt 2's server-rendered state: the ``window.__NUXT__`` payload, read without running it.

A Nuxt 2 page (Apptegy's district sites until 2024, whose archived captures the
Apptegy adapter reads) carries its whole store as a script::

    window.__NUXT__=(function(a,b,c,...){x.menu={...};...;return {layout:...,state:{...}}}
                     (false,1,null,...));

devalue writes every repeated value once, as an argument, and refers to it by the
parameter's name. :func:`read` tokenizes the script (strings, numbers, names and
punctuation; nothing is evaluated), binds the parameters to the argument values,
and :meth:`Nuxt2State.value` reads the value written after a given key (``key:``
or ``key=``) anywhere in the function body: object and array literals, strings,
numbers, ``true``/``false``/``null``/``undefined``, ``void 0``, ``!0``/``!1``,
parameter names, ``new Date(...)`` (its argument) and ``Array(n)`` (n empty slots).
Anything else where a value is read raises
:class:`~snowlight.sources.stations.model.ShapeError`.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from snowlight.sources.stations.model import ShapeError

_START = re.compile(r"window\.__NUXT__\s*=\s*\(function\(([^)]*)\)\s*\{")
_TOKEN = re.compile(
    r"""\s*(?:
      (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
    | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
    | (?P<name>[A-Za-z_$][A-Za-z0-9_$]*)
    | (?P<punct>[{}\[\](),:;.=!\-+])
    )""",
    re.VERBOSE | re.DOTALL,
)
_END = re.compile(r"</script", re.IGNORECASE)
MAX_DEPTH = 200
MAX_ARRAY = 10_000
"""The largest ``Array(n)`` read (devalue writes one for an array of empty slots)."""
_KEY_OPEN = 3
"""Tokens from a key to the value it opens: ``key`` ``:`` ``{``."""

type Token = tuple[str, str]


def _tokens(text: str) -> list[Token]:
    out: list[Token] = []
    pos, end = 0, len(text)
    while pos < end:
        found = _TOKEN.match(text, pos)
        if found is None:
            if not text[pos:].strip():
                break
            raise ShapeError(f"the Nuxt 2 payload holds {text[pos : pos + 30]!r}")
        kind = found.lastgroup
        if kind is None:  # pragma: no cover - every alternative is a named group
            raise ShapeError("the Nuxt 2 payload could not be read")
        out.append((kind, found.group(kind)))
        pos = found.end()
    return out


def _string(raw: str) -> str:
    if raw.startswith("'"):
        inner = raw[1:-1].replace("\\'", "'").replace('"', '\\"')
        raw = f'"{inner}"'
    try:
        value = json.loads(raw)
    except ValueError as error:
        raise ShapeError(f"the Nuxt 2 payload holds a bad string: {error}") from error
    if not isinstance(value, str):  # pragma: no cover - a quoted literal is text
        raise ShapeError("the Nuxt 2 payload holds a bad string")
    return value


class _Parser:
    """A reader of JavaScript value literals over a token list."""

    def __init__(self, tokens: list[Token], env: dict[str, Any]) -> None:
        self.tokens = tokens
        self.env = env
        self.at = 0

    def peek(self, ahead: int = 0) -> Token | None:
        index = self.at + ahead
        return self.tokens[index] if index < len(self.tokens) else None

    def take(self, text: str | None = None) -> Token:
        token = self.peek()
        if token is None or (text is not None and token[1] != text):
            raise ShapeError(f"the Nuxt 2 payload has {token!r} where {text!r} was expected")
        self.at += 1
        return token

    def items(self, close: str, depth: int = 0) -> list[Any]:
        """The values up to ``close`` (an array's or an argument list's), consuming it."""
        items: list[Any] = []
        while self.peek() != ("punct", close):
            if self.peek() == ("punct", ","):  # an empty slot
                self.take(",")
                items.append(None)
                continue
            items.append(self.value(depth + 1))
            if self.peek() == ("punct", ","):
                self.take(",")
        self.take(close)
        return items

    def _object(self, depth: int) -> dict[str, Any]:
        out: dict[str, Any] = {}
        while self.peek() != ("punct", "}"):
            kind, key = self.take()
            if kind == "str":
                key = _string(key)
            elif kind not in {"name", "num"}:
                raise ShapeError(f"the Nuxt 2 payload has a bad key {key!r}")
            self.take(":")
            out[key] = self.value(depth + 1)
            if self.peek() == ("punct", ","):
                self.take(",")
        self.take("}")
        return out

    def _name(self, name: str, depth: int) -> Any:
        constants: dict[str, Any] = {"true": True, "false": False, "null": None, "undefined": None}
        if name in constants:
            return constants[name]
        if name == "void":
            self.value(depth + 1)
            return None
        if name == "new":
            constructor = self.take()[1]
            self.take("(")
            args = self.items(")", depth)
            if constructor == "Date":
                return args[0] if args else None
            raise ShapeError(f"the Nuxt 2 payload constructs a {constructor}")
        if name == "Array" and self.peek() == ("punct", "("):
            self.take("(")
            args = self.items(")", depth)
            size = args[0] if len(args) == 1 and isinstance(args[0], int) else None
            if size is None or not 0 <= size <= MAX_ARRAY:
                raise ShapeError("the Nuxt 2 payload holds an Array() of unknown size")
            return [None] * size
        if name not in self.env:
            raise ShapeError(f"the Nuxt 2 payload refers to an unknown name {name!r}")
        value = self.env[name]
        while self.peek() == ("punct", "."):
            self.take(".")
            member = self.take()[1]
            value = value.get(member) if isinstance(value, dict) else None
        return value

    def _punct(self, text: str, depth: int) -> Any:
        if text == "{":
            return self._object(depth)
        if text == "[":
            return self.items("]", depth)
        if text == "-":
            number = self.value(depth + 1)
            if not isinstance(number, int | float):
                raise ShapeError("the Nuxt 2 payload negates a value that is not a number")
            return -number
        if text == "!":
            return not self.value(depth + 1)
        raise ShapeError(f"the Nuxt 2 payload has {text!r} where a value was expected")

    def value(self, depth: int = 0) -> Any:
        """The value that starts at the current token (the tokens it spans are consumed)."""
        if depth > MAX_DEPTH:
            raise ShapeError("the Nuxt 2 payload nests too deeply")
        kind, text = self.take()
        if kind == "str":
            return _string(text)
        if kind == "num":
            return float(text) if any(c in text for c in ".eE") else int(text)
        if kind == "name":
            return self._name(text, depth)
        return self._punct(text, depth)


@dataclass(frozen=True, slots=True)
class Nuxt2State:
    """A Nuxt 2 payload's function body, with its parameters bound to their values."""

    body: list[Token]
    env: dict[str, Any]

    def value(self, key: str, *, after: tuple[str, ...] = ()) -> tuple[bool, Any]:
        """The first value written after ``key:`` (or ``key=``), and whether it was found.

        With ``after``, only a ``key`` that directly follows those keys' opening braces
        (``after[0]:{after[1]:{key:``) counts.
        """
        for index, (kind, text) in enumerate(self.body):
            if kind not in {"name", "str"} or (_string(text) if kind == "str" else text) != key:
                continue
            if not self._preceded(index, after):
                continue
            nxt = self.body[index + 1] if index + 1 < len(self.body) else None
            if nxt not in {("punct", ":"), ("punct", "=")}:
                continue
            parser = _Parser(self.body, self.env)
            parser.at = index + 2
            return True, parser.value()
        return False, None

    def _preceded(self, index: int, after: tuple[str, ...]) -> bool:
        at = index
        for key in reversed(after):
            # ... key : { <at>
            if at < _KEY_OPEN or self.body[at - 2 : at] != [("punct", ":"), ("punct", "{")]:
                return False
            kind, text = self.body[at - _KEY_OPEN]
            if kind not in {"name", "str"} or (_string(text) if kind == "str" else text) != key:
                return False
            at -= _KEY_OPEN
        return True


def read(html: str) -> Nuxt2State:
    """Read the ``window.__NUXT__`` payload of a page (raises ShapeError without one)."""
    start = _START.search(html)
    if start is None:
        raise ShapeError("no window.__NUXT__ payload: not a Nuxt 2 page")
    params = [p.strip() for p in start.group(1).split(",") if p.strip()]
    end = _END.search(html, start.end())
    script = html[start.end() - 1 : end.start() if end is not None else len(html)]
    tokens = _tokens(script)
    depth = 0
    close = None
    for index, (kind, text) in enumerate(tokens):
        if kind == "punct" and text == "{":
            depth += 1
        elif kind == "punct" and text == "}":
            depth -= 1
            if depth == 0:
                close = index
                break
    if close is None or tokens[close + 1 : close + 2] != [("punct", "(")]:
        raise ShapeError("the Nuxt 2 payload has no argument list")
    parser = _Parser(tokens, {})
    parser.at = close + 2
    args = parser.items(")")
    if len(args) > len(params):
        raise ShapeError("the Nuxt 2 payload passes more arguments than it names")
    env = {name: args[i] if i < len(args) else None for i, name in enumerate(params)}
    return Nuxt2State(body=tokens[1:close], env=env)

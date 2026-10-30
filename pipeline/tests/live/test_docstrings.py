"""Every attribute docstring of the live reader documents the name just above it: two string
statements in a row mean one of them has come loose from its constant (as HEALTH_WINDOW's did
when OWN_READS_MIN was put between them)."""

import ast
from itertools import pairwise
from pathlib import Path

import pytest

import snowlight.live

LIVE = Path(snowlight.live.__file__).parent


def is_string(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


@pytest.mark.parametrize("path", sorted(LIVE.glob("*.py")), ids=lambda path: path.name)
def test_no_docstring_follows_another(path: Path) -> None:
    loose = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        body = getattr(node, "body", None)
        if isinstance(body, list):
            loose += [b.lineno for a, b in pairwise(body) if is_string(a) and is_string(b)]
    assert loose == []

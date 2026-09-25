"""The synthetic example documents, for the schema tests."""

import json
from pathlib import Path
from typing import Any

EXAMPLES = Path(__file__).resolve().parent / "examples"


def example_path(name: str) -> Path:
    """The synthetic example for the published file called ``name``."""
    return EXAMPLES / f"synthetic-{name}.json"


def example(name: str) -> Any:
    """The synthetic example for ``name``, parsed."""
    return json.loads(example_path(name).read_text(encoding="utf-8"))

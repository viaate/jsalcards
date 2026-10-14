"""The synthetic example documents, for the schema tests."""

import json
from pathlib import Path
from typing import Any

from snowlight.directory import points

EXAMPLES = Path(__file__).resolve().parent / "examples"


def example_path(name: str) -> Path:
    """The synthetic example for the published file called ``name``."""
    return EXAMPLES / f"synthetic-{name}.json"


def example(name: str) -> Any:
    """The synthetic example for ``name``, parsed."""
    return json.loads(example_path(name).read_text(encoding="utf-8"))


def example_points() -> bytes:
    """``points.bin`` for the synthetic directory example: six schools, two districts."""
    return points.encode(
        lon_e6=[-86_100_000, -86_200_000, -86_300_000, -111_000_000, -111_100_000, -86_400_000],
        lat_e6=[34_100_000, 34_200_000, 34_300_000, 33_400_000, 33_500_000, 34_400_000],
        district=[0, 0, 1, 1, points.NO_DISTRICT, points.NO_DISTRICT],
        kind=[0, 2, 0, 4, 1, 1],
        district_count=2,
    )

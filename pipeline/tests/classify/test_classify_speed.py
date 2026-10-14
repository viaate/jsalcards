"""The throughput bar: 10,000 parses in under a second.

The benchmark runs in a fresh interpreter with coverage switched off, so the
timings are what the parser costs, not what the test harness adds. See
``bench_synthetic_listings.py`` for the (synthetic) workloads.
"""

import importlib.util
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

BENCH = Path(__file__).with_name("bench_synthetic_listings.py")
LIMIT_SECONDS = 1.0


@pytest.fixture(scope="module")
def timings() -> dict[str, float]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("COV")}
    env.pop("COVERAGE_PROCESS_START", None)
    result = subprocess.run(  # noqa: S603 - fixed argv: this interpreter and a repo file
        [sys.executable, str(BENCH)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    data: dict[str, float] = json.loads(result.stdout)
    return data


def test_ten_thousand_repeated_listings_parse_in_under_a_second(timings: dict[str, float]) -> None:
    assert timings["repeated"] < LIMIT_SECONDS


def test_ten_thousand_distinct_listings_parse_in_under_a_second(timings: dict[str, float]) -> None:
    assert timings["distinct"] < LIMIT_SECONDS


def test_ten_thousand_named_listings_parse_in_under_a_second(timings: dict[str, float]) -> None:
    # A status with a made-up school name, every word new to the parser.
    assert timings["named"] < LIMIT_SECONDS


def test_ten_thousand_dense_listings_parse_in_under_a_second(timings: dict[str, float]) -> None:
    # Every text carries a status, a date phrase, a cause and a side note: the worst case.
    assert timings["dense"] < LIMIT_SECONDS


def test_ten_thousand_listings_as_long_as_real_ones_parse_in_under_a_second(
    timings: dict[str, float],
) -> None:
    # Real listings' lengths and shapes: a side note, a day, slots, a joined phrase.
    assert timings["real_length"] < LIMIT_SECONDS


def _bench() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bench_synthetic_listings", BENCH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_real_length_workload_is_as_long_as_real_listings() -> None:
    # Real listings have a median of about 40 characters and a 90th percentile of about 107.
    texts: list[str] = _bench().real_length_listings()
    lengths = sorted(map(len, texts))
    assert len(set(texts)) == len(texts) == 10_000
    assert 36 <= statistics.median(lengths) <= 44
    assert 95 <= lengths[9_000] <= 115
    # Phrases joined by a hyphen: "No School-No Personnel Report Today".
    assert sum("-No " in text or "-NO " in text for text in texts) >= 100


@pytest.mark.parametrize("workload", ["stamped", "numbered", "prefixed", "side_noted"])
def test_ten_thousand_decorated_listings_parse_in_under_a_second(
    timings: dict[str, float], workload: str
) -> None:
    # An update stamp, a reference number, a name before, or a side note naming a place.
    assert timings[workload] < LIMIT_SECONDS


def test_every_workload_is_held_to_the_limit(timings: dict[str, float]) -> None:
    assert set(timings) == {
        "repeated", "distinct", "named", "dense", "stamped", "numbered", "prefixed", "side_noted",
        "real_length",
    }  # fmt: skip
    assert max(timings.values()) < LIMIT_SECONDS

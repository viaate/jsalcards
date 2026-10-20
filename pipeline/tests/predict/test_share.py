"""The share a base sentence says, and the test that it is true of a record."""

import json
import os
from pathlib import Path

import numpy as np
import pytest

from snowlight.predict.share import Share, points_of, say, says_true, share_of

GOLDEN = Path(__file__).parent / "golden" / "shares.json"


def shares_json() -> bytes:
    """Every percent's share, as the web's unit test reads it."""
    rows = [
        {"percent": p, "some": s.some, "of": s.of, "more": s.more}
        for p in range(1, 100)
        for s in (share_of(p),)
    ]
    return (json.dumps(rows, indent=1) + "\n").encode()


def test_the_golden_shares_are_what_the_rule_says() -> None:
    # web/src/copy.test.ts checks shareOf against this file: the two rules never drift.
    data = shares_json()
    if os.environ.get("SNOWLIGHT_WRITE_GOLDEN") == "1":
        GOLDEN.write_bytes(data)
    assert GOLDEN.read_bytes() == data


def test_share_of_matches_the_web_examples() -> None:
    assert share_of(30) == Share(3, 10, more=False)
    assert share_of(25) == Share(1, 4, more=False)
    assert share_of(33) == Share(1, 3, more=False)
    assert share_of(64) == Share(3, 5, more=True)
    assert share_of(12) == Share(1, 9, more=True)
    assert share_of(57) == Share(1, 2, more=True)
    assert share_of(2) == Share(1, 50, more=False)
    assert share_of(3) == Share(1, 33, more=False)
    with pytest.raises(ValueError, match="1 to 99"):
        share_of(0)


def test_a_sentence_is_true_only_of_a_record_it_describes() -> None:
    def true(points: int, y: int, n: int) -> bool:
        return bool(
            says_true(np.array([points]), np.array([y], float), np.array([n], float), 0.05)[0]
        )

    # The critic's cases: each sentence was false of the record it named.
    assert not true(98, 4, 4)  # "49 in 50" of 4 of 4
    assert not true(78, 3, 4)  # "more than 3 in 4" of exactly 3 of 4
    assert not true(91, 15, 17)  # "more than 9 in 10" of 15 of 17 (88%)
    assert not true(90, 77, 82)  # "9 in 10" of 77 of 82 (93.9%)
    # True ones.
    assert true(75, 3, 4)  # "3 in 4"
    assert true(88, 15, 17)  # share_of(88): more than 4 in 5, and 88% is
    assert true(99, 4, 4)  # "almost always" of every day
    assert true(1, 0, 40)  # "almost never" of none
    assert true(1, 1, 40)  # 2.5% is under 1 in 20
    assert not true(1, 2, 40)  # 5% is not under 1 in 20
    assert not true(99, 19, 20)  # 95% is not over 19 in 20
    assert not true(30, 0, 0)  # never true of no days
    # An exact share rounds half up, as the web rounds: 74.5% is 3 in 4 to the percent.
    assert true(75, 149, 200)


@pytest.mark.parametrize("points", range(101))
def test_every_sentence_is_true_of_some_record_and_false_of_others(points: int) -> None:
    n = np.full(201, 200.0)
    y = np.arange(201, dtype=float)
    found = says_true(np.full(201, points), y, n, 0.05)
    assert found.any(), say(points)
    assert not found.all(), say(points)
    for count in y[found]:
        share = count / 200
        if 1 < points < 99:
            told = share_of(points)
            if told.more:
                assert share > told.some / told.of
            else:
                assert abs(share - told.some / told.of) < 0.01


def test_points_are_the_shown_whole_percent() -> None:
    assert points_of(np.array([0.01, 0.29, 0.875, 0.99])).tolist() == [1, 29, 88, 99]

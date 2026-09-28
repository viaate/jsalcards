"""The hand audit of 200 accepted matches (``audit/review-2026-09-28.json``).

The review records each sampled listing (a real row's name on a real list, with
its captures and the SHA-256 of a read it came in), the records it was matched
to, and the verdict a person gave after reading the raw rows and the NCES
records. These tests hold the review to the precision bar, and, where the build
has run here, check that every listing judged correct is still matched to the
same records.
"""

import json
from pathlib import Path
from typing import Any

import pytest

REVIEW = Path(__file__).parent / "audit" / "review-2026-09-28.json"
MATCHES = Path(__file__).resolve().parents[2] / "out" / "internal" / "listed" / "matches.jsonl"
SIZE = 200
PRECISION = 0.99


def _review() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(REVIEW.read_text(encoding="utf-8"))
    return data


def test_the_review_meets_the_precision_bar() -> None:
    entries = _review()["entries"]
    assert len(entries) == SIZE
    correct = [e for e in entries if e["verdict"] == "correct"]
    assert len(correct) / len(entries) >= PRECISION
    for entry in entries:
        assert entry["verdict"] in {"correct", "wrong"}
        if entry["verdict"] == "wrong":
            assert entry["note"], entry
        assert entry["targets"], entry
        assert len(entry["reads"][0]) == 64
        assert entry["first"] <= entry["last"]


def test_the_sample_is_stratified_by_state_and_basis() -> None:
    entries = _review()["entries"]
    bases = {entry["stratum"][1] for entry in entries}
    assert bases == {"school", "district", "roster"}
    states = {entry["stratum"][0] for entry in entries}
    assert len(states) >= 45
    for entry in entries:
        kinds = {target["kind"] for target in entry["targets"]}
        if entry["stratum"][1] == "district":
            assert kinds == {"district"}
        elif entry["stratum"][1] == "school":
            assert "school" in kinds


def test_the_reviewed_listings_are_still_matched_the_same_way() -> None:
    if not MATCHES.exists():
        pytest.skip("the listed build has not run here")
    built: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    with MATCHES.open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            built[(item["source_id"], item["name"], item["section"])] = item
    for entry in _review()["entries"]:
        found = built.get((entry["source_id"], entry["name"], entry["section"]))
        assert found is not None, entry["name"]
        if entry["verdict"] == "correct":
            assert found["accepted"] is True, entry["name"]
            assert [t["id"] for t in found["targets"]] == [t["id"] for t in entry["targets"]]
        else:
            assert found["accepted"] is False, entry["name"]

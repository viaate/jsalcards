"""live/opens.json, live/days/<day>.json and live/days/index.json: their rules (SYNTHETIC)."""

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from schemas.helpers import example
from snowlight.schemas.live import DayIndex, DayTimeline, OpensFile


def _timeline(change: Callable[[dict[str, Any]], None]) -> DayTimeline:
    document = copy.deepcopy(example("live-day"))
    change(document)
    return DayTimeline.model_validate_json(json.dumps(document))


def test_the_example_timeline_reads_its_schools_in_order() -> None:
    timeline = _timeline(lambda _doc: None)
    assert timeline.schools() == (0, 1, 4)
    assert sum(timeline.counts) == len(timeline.minutes)


def _set(**values: Any) -> Callable[[dict[str, Any]], None]:
    def change(document: dict[str, Any]) -> None:
        document.update(values)

    return change


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_set(counts=[2, 1]), "3 schools but 2 counts"),
        (_set(minutes=[-300, 330, 351, 312, 402]), "6 changes but 5 minutes"),
        (_set(shifts=[120, 120]), "one shift and clock per delay or dismissal"),
        (_set(gaps=[0, 0, 4]), "a school is not in the directory"),
        (_set(statuses=[None, 1, 0, 1, 1, None]), "first change must show a status"),
        (_set(minutes=[330, -300, 351, 312, 402, 610]), "in time order"),
        (
            _set(statuses=[1, 1, 0, 1, 1, None], shifts=[120, 120, 120, 180], clocks=[600] * 4),
            "must change something",
        ),
        (_set(reasons=[0, 0, 1, None, 0, 2]), "taken back has no reason"),
        (_set(minutes=[-20000, 330, 351, 312, 402, 610]), "greater than or equal"),
        (_set(counts=[2, 0, 4]), "greater than or equal to 1"),
    ],
)
def test_a_timeline_that_breaks_a_rule_is_refused(
    change: Callable[[dict[str, Any]], None], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _timeline(change)


def test_a_detail_change_alone_is_a_change() -> None:
    def longer_delay(document: dict[str, Any]) -> None:
        document["statuses"] = [1, 1, 0, 1, 1, None]
        document["shifts"] = [120, 180, 120, 180]
        document["clocks"] = [600, 660, None, None]

    assert _timeline(longer_delay).statuses[:2] == (1, 1)


def _opens(change: Callable[[dict[str, Any]], None]) -> OpensFile:
    document = copy.deepcopy(example("opens"))
    change(document)
    return OpensFile.model_validate_json(json.dumps(document))


def _first_open(**values: Any) -> Callable[[dict[str, Any]], None]:
    def change(document: dict[str, Any]) -> None:
        document["opens"][0].update(values)

    return change


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_first_open(school=5, day="2027-01-13"), "sorted by day and school"),
        (_first_open(day="2027-01-10"), "is not today or tomorrow"),
        (_first_open(school=6), "is not in the directory"),
        (_first_open(at="2027-01-12T13:06:00Z"), "seen after generated_at"),
        (_first_open(kind="closed"), "Input should be 'open'"),
        (_first_open(confidence=0.905), "hundredths"),
        (_first_open(source="SYNTHETIC"), "Extra inputs are not permitted"),
    ],
)
def test_an_opens_file_that_breaks_a_rule_is_refused(
    change: Callable[[dict[str, Any]], None], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _opens(change)


def test_the_day_index_is_newest_first_and_unique() -> None:
    document = copy.deepcopy(example("live-days"))
    document["days"].reverse()
    with pytest.raises(ValidationError, match="newest first"):
        DayIndex.model_validate_json(json.dumps(document))
    document["days"] = [document["days"][1], document["days"][1]]
    with pytest.raises(ValidationError, match="unique"):
        DayIndex.model_validate_json(json.dumps(document))

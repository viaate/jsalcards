"""The night chart's contract (``schemas/predictions.py``): ``NightSnow``, ``night_at`` and every
night check, both ways."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from schemas.helpers import example
from snowlight.schemas.predictions import (
    NIGHT_MAX_AGE,
    NightSnow,
    PredictionsFile,
    check_night,
    night_hours,
)
from snowlight.schemas.scalars import format_instant

# The example file: 11:00Z on Tuesday 2027-01-12, 5 AM in Chicago, one hour to 7 AM.
GENERATED = datetime(2027, 1, 12, 11, tzinfo=UTC)
ZONE = "America/Chicago"
NIGHT: dict[str, Any] = {"least": [1.2], "low": 1.2, "high": 1.9}


def _with(night: dict[str, Any] | None = None, **top: Any) -> dict[str, Any]:
    value: dict[str, Any] = example("predictions")
    value["districts"][0]["days"][0]["night"] = NIGHT if night is None else night
    value["night_at"] = format_instant(GENERATED - timedelta(minutes=67))
    value.update(top)
    return value


def _parse(value: dict[str, Any]) -> PredictionsFile:
    return PredictionsFile.from_json_bytes(json.dumps(value))


def _refused(value: dict[str, Any], check: str) -> None:
    with pytest.raises(ValidationError, match=f"night: {check}"):
        _parse(value)


def test_a_night_reads_and_writes_back() -> None:
    assert night_hours(GENERATED, ZONE) == 1
    file = _parse(_with())
    night = file.districts[0].days[0].night  # type: ignore[union-attr]
    assert night == NightSnow(least=(1.2,), low=1.2, high=1.9)
    assert PredictionsFile.from_json_bytes(file.to_json_bytes()) == file
    assert b'"night":{"high":1.9,"least":[1.2],"low":1.2}' in file.to_json_bytes()
    assert b'"night_at":"2027-01-12T09:53:00Z"' in file.to_json_bytes()


def test_a_file_without_nights_has_no_night_keys() -> None:
    data = _parse(example("predictions")).to_json_bytes()
    assert b'"night' not in data


@pytest.mark.parametrize(
    ("night", "check"),
    [
        ({"least": [1.2, 1.1], "low": 1.1, "high": 1.9}, "least_falls"),
        ({"least": [1.2], "low": 1.3, "high": 1.9}, "range"),
        ({"least": [1.2], "low": 1.0, "high": 1.1}, "range"),
        ({"least": [0.4], "low": 0.4, "high": 0.9}, "range"),
        ({"least": [3.0], "low": 2.5, "high": 4.0}, "range"),
        ({"least": [100.0], "low": 99.0, "high": 99.0}, "least_bound"),
        ({"least": [99.9], "low": 99.0, "high": 100.0}, "range"),
        ({"least": [1.2], "low": 1.2, "high": 1.9, "heavy": [0, 1]}, "heavy"),
    ],
)
def test_each_night_check_refuses(night: dict[str, Any], check: str) -> None:
    _refused(_with(night), check)


def test_the_bars_must_be_the_window_s_hours() -> None:
    _refused(_with({"least": [0.5, 1.2], "low": 1.2, "high": 1.9}), "bars")


def test_the_window_must_be_open_and_the_day_the_night_s() -> None:
    value = _with(generated_at="2027-01-12T12:00:00Z")  # 6 AM in Chicago: closed
    _refused(value, "window")
    value = example("predictions")
    value["districts"][0]["days"][1]["night"] = NIGHT  # Jan 13: not this pass's night day
    value["night_at"] = format_instant(GENERATED - timedelta(minutes=67))
    _refused(value, "window")


def test_one_day_a_district() -> None:
    value = _with()
    value["districts"][0]["days"][1]["night"] = NIGHT
    _refused(value, "one_day")


def test_night_at_comes_with_a_night_and_only_then() -> None:
    value = _with()
    del value["night_at"]
    _refused(value, "night_at_pair")
    value = example("predictions")
    value["night_at"] = format_instant(GENERATED - timedelta(minutes=67))
    _refused(value, "night_at_pair")


@pytest.mark.parametrize("minutes", [0, 150])
def test_night_at_up_to_150_minutes_old(minutes: int) -> None:
    assert timedelta(minutes=150) == NIGHT_MAX_AGE
    _parse(_with(night_at=format_instant(GENERATED - timedelta(minutes=minutes))))


@pytest.mark.parametrize("minutes", [-1, 151])
def test_night_at_never_after_the_file_nor_over_150_minutes_old(minutes: int) -> None:
    _refused(_with(night_at=format_instant(GENERATED - timedelta(minutes=minutes))), "night_at_age")


def test_no_night_on_a_private_schools_outlook() -> None:
    value = example("predictions")
    assert value["outlooks"], "the example holds private schools' outlooks"
    value["outlooks"][0]["night"] = NIGHT
    _refused(value, "outlook")


def test_a_heavy_span_of_three_or_four_hours_inside_the_bars() -> None:
    night = NightSnow(
        least=(0.1, 0.4, 1.0, 1.8, 2.4, 2.6, 2.7, 2.7, 2.7), low=2.0, high=4.0, heavy=(2, 5)
    )
    assert night.heavy == (2, 5)
    NightSnow(least=night.least, low=2.0, high=4.0, heavy=(5, 9))
    for heavy in ((2, 4), (2, 7), (7, 10), (-1, 2)):
        with pytest.raises(ValidationError):
            NightSnow(least=night.least, low=2.0, high=4.0, heavy=heavy)


def test_check_night_is_what_the_file_checks() -> None:
    night = NightSnow(least=(1.2,), low=1.2, high=1.9)
    check_night(night, GENERATED.date(), ZONE, GENERATED)
    with pytest.raises(ValueError, match="night: bars"):
        check_night(night, GENERATED.date(), ZONE, GENERATED - timedelta(hours=3))
    with pytest.raises(ValueError, match="night: window"):
        check_night(night, GENERATED.date() + timedelta(days=1), ZONE, GENERATED)

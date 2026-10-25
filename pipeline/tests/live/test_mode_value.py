"""``LIVE_PUBLISH`` read as Actions compares strings (S8-E mode): ignoring case, no trimming;
anything else, unset included, is ``shadow``, and reading it never raises. So the reader and
the publish job's ``vars.LIVE_PUBLISH != 'on'`` always agree on who writes ``v1``."""

import logging

import pytest

from snowlight.live.cli import mode_of
from snowlight.live.publish import Mode

VALUES = (
    "on",
    "ON",
    "On",
    "oN",
    "shadow",
    "SHADOW",
    "Shadow",
    "off",
    "OFF",
    "",
    " on",
    "on ",
    "on\n",
    "yes",
    "true",
    "1",
    "loud",
    "ön",
    "он",  # Cyrillic letters that look like "on"
    "\uff4f\uff4e",  # full-width letters
)


def actions_equal(left: str, right: str) -> bool:
    """Actions' string comparison: case ignored (ordinal), nothing trimmed."""
    return left.isascii() and right.isascii() and left.lower() == right.lower()


@pytest.mark.parametrize("value", VALUES)
def test_the_reader_and_the_publish_job_agree_on_who_writes_v1(value: str) -> None:
    mode = mode_of({"LIVE_PUBLISH": value})
    assert (mode is Mode.ON) == actions_equal(value, "on")
    if mode is not Mode.ON:
        assert mode in {Mode.SHADOW, Mode.OFF}
        assert (mode is Mode.OFF) == actions_equal(value, "off")


def test_unset_is_shadow_quietly(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    assert mode_of({}) is Mode.SHADOW
    assert caplog.records == []
    assert mode_of({"LIVE_PUBLISH": "loud"}) is Mode.SHADOW
    assert [record.getMessage() for record in caplog.records] == [
        "LIVE_PUBLISH is not on, shadow or off: shadow"
    ]

"""The pipeline's one screenshot call (snowlight.social.shot) on a stand-in page: only
Chromium's capture error is tried again, at most three times in all, and the bytes are the
page's own."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from snowlight.social.shot import (
    ATTEMPTS,
    CAPTURE_ERROR,
    FRAME,
    WAIT_MS,
    capture_failed,
    screenshot,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page

PNG = b"\x89PNG\r\n\x1a\nSYNTHETIC"
CAPTURE = f"Page.screenshot: {CAPTURE_ERROR}\nCall log:\n  - taking page screenshot"


class ClosedError(PlaywrightError):
    """Stands in for any of Playwright's own subclasses of its error (a closed page, say):
    the retry takes Playwright's plain error alone."""


class FakePage:
    """Answers each screenshot with the next of ``answers`` (an error is raised) and keeps
    every call in order: each screenshot's arguments, each wait, each script evaluated.
    ``fail_wait`` is raised by the next wait."""

    def __init__(self, *answers: bytes | Exception, fail_wait: Exception | None = None) -> None:
        self.answers = list(answers)
        self.fail_wait = fail_wait
        self.calls: list[dict[str, object]] = []
        self.waits: list[float] = []
        self.order: list[str] = []

    def screenshot(self, **kwargs: object) -> bytes:
        self.calls.append(kwargs)
        self.order.append("shot")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def wait_for_timeout(self, timeout: float) -> None:
        self.order.append("wait")
        if self.fail_wait is not None:
            raise self.fail_wait
        self.waits.append(timeout)

    def evaluate(self, script: str) -> bool:
        assert script == FRAME
        self.order.append("frame")
        return True


def shoot(
    page: FakePage,
    path: Path | None = None,
    *,
    said: list[str] | None = None,
    again: Callable[[], None] | None = None,
) -> bytes:
    said = [] if said is None else said
    if again is None:
        return screenshot(cast("Page", page), path, say=said.append)
    return screenshot(cast("Page", page), path, say=said.append, again=again)


def test_a_shot_taken_first_time_is_the_plain_call() -> None:
    page = FakePage(PNG)
    said: list[str] = []
    checks: list[int] = []
    assert shoot(page, said=said, again=lambda: checks.append(1)) == PNG
    assert page.calls == [{"path": None, "type": "png", "full_page": False}]
    assert page.order == ["shot"]  # nothing waited for or evaluated before the first attempt
    assert said == []
    assert checks == []


def test_the_path_is_passed_through(tmp_path: Path) -> None:
    page = FakePage(PNG)
    assert shoot(page, tmp_path / "picture.png") == PNG
    assert page.calls == [{"path": tmp_path / "picture.png", "type": "png", "full_page": False}]


def test_one_capture_error_is_said_waited_out_checked_and_tried_again() -> None:
    page = FakePage(PlaywrightError(CAPTURE), PNG)
    said: list[str] = []
    checks: list[list[str]] = []
    assert shoot(page, said=said, again=lambda: checks.append(list(page.order))) == PNG
    assert len(page.calls) == 2
    assert page.calls[0] == page.calls[1]
    assert page.waits == [WAIT_MS]
    assert page.order == ["shot", "wait", "frame", "shot"]
    assert checks == [["shot", "wait", "frame"]]  # the check runs after the wait, before the shot
    assert said == [
        "::warning::social: the screenshot had no frame to capture (attempt 1 of 3);"
        " taking it again"
    ]


def test_two_capture_errors_wait_longer_before_the_last_attempt() -> None:
    page = FakePage(PlaywrightError(CAPTURE), PlaywrightError(CAPTURE), PNG)
    said: list[str] = []
    assert shoot(page, said=said) == PNG
    assert len(page.calls) == ATTEMPTS == 3
    assert page.waits == [WAIT_MS, 2 * WAIT_MS]
    assert page.order == ["shot", "wait", "frame", "shot", "wait", "frame", "shot"]
    assert [line.split("(")[1].split(")")[0] for line in said] == [
        "attempt 1 of 3",
        "attempt 2 of 3",
    ]


def test_three_capture_errors_raise_the_last() -> None:
    last = PlaywrightError(CAPTURE)
    page = FakePage(PlaywrightError(CAPTURE), PlaywrightError(CAPTURE), last, PNG)
    said: list[str] = []
    with pytest.raises(PlaywrightError) as raised:
        shoot(page, said=said)
    assert raised.value is last
    assert len(page.calls) == ATTEMPTS
    assert page.waits == [WAIT_MS, 2 * WAIT_MS]
    assert page.answers == [PNG]  # no fourth attempt
    assert len(said) == ATTEMPTS - 1  # the last one is raised, not said


def test_a_failed_check_before_the_retry_is_raised_and_no_shot_is_taken() -> None:
    page = FakePage(PlaywrightError(CAPTURE), PNG)

    def changed() -> None:
        raise RuntimeError("SYNTHETIC: the page changed")

    with pytest.raises(RuntimeError, match="changed"):
        shoot(page, again=changed)
    assert len(page.calls) == 1


@pytest.mark.parametrize(
    "failure",
    [ClosedError("Target page, context or browser has been closed"), PlaywrightTimeout("Timeout")],
    ids=lambda error: type(error).__name__,
)
def test_a_page_that_fails_during_the_wait_raises_the_capture_error(failure: Exception) -> None:
    capture = PlaywrightError(CAPTURE)
    page = FakePage(capture, PNG, fail_wait=failure)
    with pytest.raises(PlaywrightError) as raised:
        shoot(page)
    assert raised.value is capture
    assert raised.value.__cause__ is failure
    assert len(page.calls) == 1


@pytest.mark.parametrize(
    "error",
    [
        PlaywrightTimeout("Page.screenshot: Timeout 30000ms exceeded."),
        PlaywrightTimeout(CAPTURE),  # a timeout is never tried again, whatever it says
        ClosedError("Target page, context or browser has been closed"),
        ClosedError(CAPTURE),  # nor any other subclass of Playwright's error
        PlaywrightError("Page.screenshot: Protocol error (Page.captureScreenshot): Target crashed"),
        PlaywrightError("Page.screenshot: Protocol error (Page.navigate): Unable to capture"),
        RuntimeError(CAPTURE),  # not Playwright's own error
        OSError("No space left on device"),
    ],
    ids=lambda error: type(error).__name__,
)
def test_any_other_error_is_raised_at_once(error: Exception) -> None:
    page = FakePage(error, PNG)
    said: list[str] = []
    with pytest.raises(type(error)) as raised:
        shoot(page, said=said)
    assert raised.value is error
    assert len(page.calls) == 1
    assert page.order == ["shot"]
    assert said == []


def test_only_the_capture_error_counts() -> None:
    assert capture_failed(PlaywrightError(CAPTURE))
    assert capture_failed(PlaywrightError(CAPTURE_ERROR))
    assert not capture_failed(PlaywrightError("Unable to capture screenshot"))
    assert not capture_failed(PlaywrightTimeout(CAPTURE))
    assert not capture_failed(ClosedError(CAPTURE))
    assert not capture_failed(ValueError(CAPTURE))

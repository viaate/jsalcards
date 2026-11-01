"""Every screenshot the pipeline takes (the Render step's map picture and each card), with
one narrow retry: Chromium's ``Protocol error (Page.captureScreenshot): Unable to capture
screenshot``, which a busy machine gives when the compositor has no frame ready in time.

Only that error is tried again, at most :data:`ATTEMPTS` times in all. Each retry is said as
a ``::warning::`` line, then waits :data:`WAIT_MS` times the attempt's number and for the page
to draw two frames (:data:`FRAME`, at most :data:`FRAME_MS`), then runs the caller's check
(the map picture checks its state again), then takes the shot again; the last capture error
is raised. Any other error (a timeout, a closed page, another protocol error) is raised at
once, and a page that fails during the wait raises the capture error it was waiting after.
The first attempt is the plain call with nothing waited for before it, so a picture taken
first time is byte for byte the one the plain call takes.

Measured under six CPU burners on a 4-CPU machine (``tests/social/test_cards.py``, about 64
card shots a run): with the 250 and 500 ms waits alone, 33 shots in five runs needed a retry
and 3 of those needed the third attempt; with the frame wait as well, 52 shots in ten runs
needed a retry and none needed the third attempt. None failed.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # the browser is needed only to take a picture, not to import this
    from pathlib import Path

    from playwright.sync_api import Page

ATTEMPTS: Final = 3
"""Attempts in all, the first included."""
WAIT_MS: Final = 250
"""Milliseconds waited before the second attempt (twice that before the third)."""
FRAME_MS: Final = 1000
"""Milliseconds the frame wait (:data:`FRAME`) takes at most."""
FRAME: Final = f"""() => new Promise((done) => {{
  const late = setTimeout(() => done(false), {FRAME_MS});
  requestAnimationFrame(() => requestAnimationFrame(() => {{ clearTimeout(late); done(true); }}));
}})"""
"""Waits until the page has drawn two frames (so the compositor has one to give), or
:data:`FRAME_MS` at most; it changes nothing on the page."""
CAPTURE_ERROR: Final = "Protocol error (Page.captureScreenshot): Unable to capture screenshot"
"""The one error tried again (Chromium had no frame to capture)."""


def capture_failed(error: BaseException) -> bool:
    """Whether ``error`` is Playwright's own error for a frame Chromium could not capture
    (not a timeout, not a closed page, not any other error)."""
    from playwright.sync_api import Error  # noqa: PLC0415 - see the module

    # Its plain protocol error only: never a subclass (a timeout, a closed page).
    return type(error) is Error and CAPTURE_ERROR in error.message


def _nothing() -> None:
    """No check before a retried shot."""


def screenshot(
    page: "Page",
    path: "Path | None" = None,
    *,
    say: Callable[[str], None],
    again: Callable[[], None] = _nothing,
) -> bytes:
    """``page.screenshot(path=path, type="png", full_page=False)``: the viewport as a PNG
    (also written to ``path`` when one is given), with the capture error alone tried again
    (see the module). ``say`` gets each retry's warning; ``again`` runs before each retried
    shot and raises if the page is no longer the one checked before the first.

    Raises:
        playwright.sync_api.Error: the capture error on the last attempt (or on an attempt
            after which the page failed during the wait, chained from that failure), or any
            other error on the attempt that met it.
        Exception: whatever ``again`` raises.
    """
    from playwright.sync_api import Error  # noqa: PLC0415 - see the module

    attempt = 1
    while True:
        try:
            return page.screenshot(path=path, type="png", full_page=False)
        except Exception as error:
            if attempt >= ATTEMPTS or not capture_failed(error):
                raise
            say(
                f"::warning::social: the screenshot had no frame to capture (attempt {attempt}"
                f" of {ATTEMPTS}); taking it again"
            )
            try:
                page.wait_for_timeout(WAIT_MS * attempt)
                page.evaluate(FRAME)
            except Error as failed:
                raise error from failed
        again()
        attempt += 1

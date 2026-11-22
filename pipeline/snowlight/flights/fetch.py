"""Polite downloads for the flights history and live inputs.

One request at a time per host (callers never run two at once), a plain User-Agent with no
personal details, a few tries with growing pauses on errors, and every download written whole
to its place (``.part`` then rename), so a re-run skips what it already has.
"""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

import httpx

USER_AGENT: Final = "snowlight-flights/1.0 (public data reader)"
TRIES: Final = 4
PAUSE_SECONDS: Final = 5.0


class FetchError(RuntimeError):
    """A download failed after every try."""


def client(timeout: float = 60.0) -> httpx.Client:  # pragma: no cover - the network
    """An HTTP client with the flights User-Agent."""
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True)


def get_bytes(  # noqa: PLR0913 - the request, its tries and its clock
    http: httpx.Client,
    url: str,
    *,
    tries: int = TRIES,
    pause: float = PAUSE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> bytes | None:
    """The body at ``url``; ``None`` when the server says it is not there (404).

    ``deadline`` (on ``clock``): a time the whole request, every try and the body as it streams
    in, must end by; past it the request stops (the client's own timeout is per phase, so a
    slow body could otherwise run on).

    Raises:
        FetchError: every try failed, or the deadline passed.
    """
    last = ""
    for attempt in range(tries):
        if deadline is not None and clock() >= deadline:
            raise FetchError(f"{url}: out of time")
        try:
            with http.stream("GET", url) as response:
                if response.status_code == 404:  # noqa: PLR2004 - not there
                    return None
                if response.status_code == 200:  # noqa: PLR2004 - the body
                    chunks: list[bytes] = []
                    for chunk in response.iter_bytes():
                        if deadline is not None and clock() >= deadline:
                            raise FetchError(f"{url}: out of time while reading")
                        chunks.append(chunk)
                    return b"".join(chunks)
                last = f"HTTP {response.status_code}"
        except httpx.HTTPError as error:
            last = f"{type(error).__name__}: {error}"
        if attempt + 1 < tries:
            sleep(pause * (attempt + 1))
    raise FetchError(f"{url}: {last}")


def download(
    http: httpx.Client,
    url: str,
    path: Path,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Download ``url`` to ``path`` unless it is already there; False when the server has no
    such file."""
    if path.is_file() and path.stat().st_size > 0:
        return True
    body = get_bytes(http, url, sleep=sleep)
    if body is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    part.write_bytes(body)
    part.replace(path)
    return True

"""The alert history read that rebuilds a lost alert memory (spec addendum 2026-10-24 f: a
fresh start pages through or bounds the history and publishes). SYNTHETIC pages only."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from predict import world
from snowlight.predict.inputs import HISTORY_PAGES, AlertsHistory
from snowlight.predict.publish import Dark, DarkError

START = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
END = datetime(2026, 1, 7, 12, 0, tzinfo=UTC)
NEXT = "https://api.weather.gov/alerts?cursor="


def product(number: int, sent: str = "2026-01-06T20:00:00+00:00") -> dict[str, Any]:
    """SYNTHETIC: one winter storm warning product, numbered."""
    return world.feature(
        f"/O.NEW.KEAX.WS.W.{number:04d}.260107T0600Z-260108T0000Z/",
        ("MOZ028",),
        sent=sent,
        onset="2026-01-07T06:00:00+00:00",
        ends="2026-01-08T00:00:00+00:00",
    )


def page(features: list[dict[str, Any]], following: str | None) -> bytes:
    """One page of the history feed, with its ``next`` link (or none)."""
    body = json.loads(world.feed_bytes(features, "2026-01-07T12:00:00+00:00"))
    if following is not None:
        body["pagination"] = {"next": following}
    return json.dumps(body).encode()


def history(answer: Callable[[httpx.Request], httpx.Response]) -> tuple[AlertsHistory, list[str]]:
    """A history reader over ``answer``, and the URLs it asked for."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return answer(request)

    return AlertsHistory(httpx.Client(transport=httpx.MockTransport(handler))), asked


def test_the_history_is_read_to_its_last_page() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if "cursor=2" in str(request.url):
            return httpx.Response(200, content=page([], None))
        return httpx.Response(200, content=page([product(1), product(2)], NEXT + "2"))

    reader, asked = history(answer)
    found = reader.read(START, END)
    assert sorted(alert.id for alert in found) == [
        "urn:test:/O.NEW.KEAX.WS.W.0001.260107T0600Z-260108T0000Z/",
        "urn:test:/O.NEW.KEAX.WS.W.0002.260107T0600Z-260108T0000Z/",
    ]
    assert len(asked) == 2
    assert "start=2026-01-05T00%3A00%3A00Z" in asked[0]


def test_a_looping_cursor_ends_the_read_whole_instead_of_going_dark() -> None:
    # The feed hands back the same page and the same next link for ever: the fresh start that
    # went dark ("more than 40 pages") must publish from what it read.
    reader, asked = history(
        lambda _request: httpx.Response(200, content=page([product(1)], NEXT + "same"))
    )
    found = reader.read(START, END)
    assert [alert.id for alert in found] == [
        "urn:test:/O.NEW.KEAX.WS.W.0001.260107T0600Z-260108T0000Z/"
    ]
    assert len(asked) == 2


def test_a_new_cursor_over_products_already_read_ends_the_read() -> None:
    count = iter(range(1000))
    reader, asked = history(
        lambda _request: httpx.Response(
            200, content=page([product(1), product(2)], f"{NEXT}{next(count)}")
        )
    )
    assert len(reader.read(START, END)) == 2
    assert len(asked) == 2


def test_a_page_issued_before_the_start_ends_the_read() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if "cursor=old" in str(request.url):
            return httpx.Response(
                200, content=page([product(3, sent="2026-01-02T00:00:00+00:00")], NEXT + "older")
            )
        return httpx.Response(200, content=page([product(1)], NEXT + "old"))

    reader, asked = history(answer)
    assert len(reader.read(START, END)) == 2
    assert len(asked) == 2


def test_more_pages_of_new_products_than_allowed_go_dark_and_say_how_far() -> None:
    count = iter(range(1000))

    def answer(_request: httpx.Request) -> httpx.Response:
        number = next(count)
        return httpx.Response(200, content=page([product(number)], f"{NEXT}{number}"))

    reader, asked = history(answer)
    with pytest.raises(DarkError) as raised:
        reader.read(START, END)
    assert raised.value.reason is Dark.MEMORY
    assert f"more than {HISTORY_PAGES} pages ({HISTORY_PAGES} products" in str(raised.value)
    assert len(asked) == HISTORY_PAGES


@pytest.mark.parametrize(
    ("response", "said"),
    [
        (httpx.Response(503), "HTTP 503"),
        (httpx.Response(200, content=b"<html>"), "not an alerts page"),
    ],
)
def test_an_unreadable_page_goes_dark(response: httpx.Response, said: str) -> None:
    reader, _asked = history(lambda _request: response)
    with pytest.raises(DarkError, match=said):
        reader.read(START, END)


def test_a_failed_request_goes_dark() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    reader, _asked = history(answer)
    with pytest.raises(DarkError, match="ConnectError"):
        reader.read(START, END)

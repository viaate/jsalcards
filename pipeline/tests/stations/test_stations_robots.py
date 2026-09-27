"""robots.txt handling: RFC 9309 matching, status rules, and the real Hearst and Gray files.

The two real files are verbatim copies read on 2026-09-25 (see fixtures/README.md
and fixtures/PROVENANCE.robots.json); the short inline files are synthetic, written
for one rule each.
"""

import hashlib
import json
from pathlib import Path

import pytest

from snowlight.sources.stations.http import USER_AGENT
from snowlight.sources.stations.robots import Robots, RobotsState, parse

FIXTURES = Path(__file__).parent / "fixtures" / "robots"
UA = USER_AGENT


def _real(name: str) -> Robots:
    provenance = json.loads((FIXTURES / "PROVENANCE.robots.json").read_text(encoding="utf-8"))
    entry = provenance[name]
    body = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(body).hexdigest() == entry["sha256"]
    return Robots.from_bytes(body)


def test_hearst_robots_allows_the_closings_page_for_our_agent() -> None:
    robots = _real("www.kmbc.com.robots.txt")
    assert robots.allowed("https://www.kmbc.com/weather/closings", UA)
    assert not robots.allowed("https://www.kmbc.com/api/closings", UA)
    assert robots.crawl_delay(UA) == 10.0


def test_hearst_robots_names_ai_agents_and_the_archive_crawler() -> None:
    robots = _real("www.kmbc.com.robots.txt")
    disallowed = robots.disallowed_agents()
    for agent in ("claudebot", "anthropic-ai", "gptbot", "archive.org_bot", "ccbot"):
        assert agent in disallowed
    assert not robots.allowed("https://www.kmbc.com/weather/closings", "ClaudeBot/1.0")


def test_gray_robots_allows_weather_pages_for_our_agent() -> None:
    robots = _real("www.kctv5.com.robots.txt")
    assert robots.allowed("https://www.kctv5.com/weather/closings/", UA)
    assert not robots.allowed("https://www.kctv5.com/wires/story", UA)
    assert not robots.allowed("https://www.kctv5.com/weather/closings/", "anthropic-ai")
    assert robots.crawl_delay(UA) is None


def test_longest_match_wins_and_allow_wins_ties() -> None:
    robots = Robots.from_bytes(
        b"User-agent: *\nDisallow: /weather/\nAllow: /weather/closings\nDisallow: /a\nAllow: /a\n"
    )
    assert robots.allowed("https://x.test/weather/closings/today", UA)
    assert not robots.allowed("https://x.test/weather/radar", UA)
    assert robots.allowed("https://x.test/a", UA)


def test_wildcards_and_end_anchor() -> None:
    robots = Robots.from_bytes(b"User-agent: *\nDisallow: /*.json$\nDisallow: /*?outputType=apps\n")
    assert not robots.allowed("https://x.test/data/closings.json", UA)
    assert robots.allowed("https://x.test/data/closings.json?c=1", UA)
    assert not robots.allowed("https://x.test/story?outputType=apps", UA)
    assert robots.allowed("https://x.test/story?outputType=web", UA)


def test_named_group_replaces_the_star_group() -> None:
    robots = Robots.from_bytes(
        b"User-agent: *\nDisallow: /\n\nUser-agent: snowlight-pipeline\nAllow: /closings\n"
        b"Disallow: /\n"
    )
    assert robots.allowed("https://x.test/closings", UA)
    assert not robots.allowed("https://x.test/other", UA)
    assert not robots.allowed("https://x.test/closings", "OtherBot/2.0")


def test_consecutive_agents_share_a_group_and_empty_disallow_matches_nothing() -> None:
    groups = parse("User-agent: a\nUser-agent: b\nDisallow:\nUser-agent: c\nDisallow: /\n")
    assert [group.agents for group in groups] == [["a", "b"], ["c"]]
    robots = Robots.from_bytes(b"User-agent: *\nDisallow:\n")
    assert robots.allowed("https://x.test/anything", UA)


def test_robots_txt_itself_is_always_allowed() -> None:
    robots = Robots.from_bytes(b"User-agent: *\nDisallow: /\n")
    assert robots.allowed("https://x.test/robots.txt", UA)
    assert not robots.allowed("https://x.test/", UA)


@pytest.mark.parametrize(
    ("status", "state", "allowed"),
    [
        (404, RobotsState.UNAVAILABLE, True),
        (403, RobotsState.UNAVAILABLE, True),
        (500, RobotsState.UNREACHABLE, False),
        (503, RobotsState.UNREACHABLE, False),
    ],
)
def test_status_rules(status: int, state: RobotsState, allowed: bool) -> None:
    robots = Robots.for_status(status)
    assert robots.state is state
    assert robots.allowed("https://x.test/closings", UA) is allowed


def test_percent_encoding_is_compared_consistently() -> None:
    robots = Robots.from_bytes("User-agent: *\nDisallow: /café\n".encode())
    assert not robots.allowed("https://x.test/caf%C3%A9/menu", UA)


def test_no_matching_group_allows_everything() -> None:
    robots = Robots.from_bytes(b"User-agent: GPTBot\nDisallow: /\n")
    assert robots.allowed("https://x.test/closings", UA)
    assert robots.decide("https://x.test/closings", UA)[1] == "no rule matches"


def test_invalid_crawl_delay_is_ignored() -> None:
    robots = Robots.from_bytes(b"User-agent: *\nCrawl-delay: soon\nCrawl-delay: -1\nDisallow:\n")
    assert robots.crawl_delay(UA) is None

"""The deterministic post checks, against adversarial drafts (all SYNTHETIC), and the
repository's own facts file and first queued post."""

import json
from pathlib import Path

import pytest

from snowlight.social.content import load
from snowlight.social.rules import (
    MAX_WEIGHT,
    FactsError,
    Style,
    check,
    emoji_count,
    parse_facts,
    weight,
)
from social.fakes import FACTS

REPO = Path(__file__).resolve().parents[3]
FACT_SET = parse_facts(FACTS)
IMAGE = "the national map at night on 2026-10-20, nothing glowing"


def problems(text: str, style: Style = "dev_log", *, today: bool = True) -> list[str]:
    return check(text, style=style, facts=FACT_SET, image_description=IMAGE, image_is_today=today)


def test_a_true_plain_post_passes() -> None:
    assert (
        problems(
            "Dev log: the closings reader runs 24/7 in practice mode. Waitlist link in my bio."
        )
        == []
    )
    assert (
        problems(
            "The map is still in private testing. Join the waitlist, link in my bio.", "waitlist"
        )
        == []
    )
    assert problems("Phone alerts for your school are coming at launch #buildinpublic") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Read more at https://example.org/x", "URL or a domain"),
        ("Find it at snowlightmap.com", "URL or a domain"),
        ("Go to www.example", "URL or a domain"),
        ("Thanks @someone for the idea", "mentions an account"),
        ("Snow day map #snow #school", "more than one hashtag"),
        ("Snow ❄️ and more snow ⛄", "more than one emoji"),
        ("Big week!!", "'!!'"),
        ("Big week‼", "'!!'"),
        ("Snowlight — a map", "em dash"),
        ("The most accurate closings map", "'most accurate'"),
        ("A revolutionary way to see snow days", "'revolutionary'"),
        ("An AI-powered map", "'ai-powered'"),
        ("Closings guaranteed by 6", "'guaranteed'"),
        ("It is never wrong", "'never wrong'"),
        ("Better than any snow day calculator", "'snow day calculator'"),
        ("Unlike snowdaycalculator I show schools", "'snowdaycalculator'"),
        ("Way past SDC numbers", "'SDC'"),
        ("My secret formula", "'formula'"),
        ("A reconstruction of their model", "'reconstruction'"),
        ("I read the KXYZ closings list", "call letters"),
        ("Closings for 3,146 schools", "the number 3146"),
        ("Up 40 percent", "the number 40"),
        ("A thousand schools", "'thousand'"),
    ],
)
def test_adversarial_drafts_are_refused(text: str, expected: str) -> None:
    found = problems(text)
    assert any(expected in line for line in found), found


def test_testing_and_coming_facts_are_never_called_live() -> None:
    assert any("calls 'the map' live" in line for line in problems("The map is live now."))
    assert any(
        "calls 'alerts' live" in line for line in problems("Alerts are available for every school.")
    )
    assert any(
        "without saying it is coming" in line for line in problems("Schools glow when closed.")
    )
    assert any("without saying it is testing" in line for line in problems("Look at the map."))
    assert problems("Look at the map I am testing.") == []
    assert problems("Closings on the map are coming this winter, before launch.") == []


def test_a_waitlist_post_must_point_at_the_bio() -> None:
    assert any(
        "link in my bio" in line for line in problems("Join the waitlist today.", "waitlist")
    )


def test_numbers_must_come_from_the_facts_and_never_from_the_picture() -> None:
    assert (
        problems("118,211 schools in 18,227 districts so far. The map is in private testing.") == []
    )
    found = problems("The image is from 2026-10-20.")
    assert any("(the card shows the picture's)" in line for line in found), found
    assert any("the number 146" in line for line in problems("146 schools"))


def test_a_stale_image_is_never_presented_as_now() -> None:
    assert any("an older one" in line for line in problems("Snowlight right now", today=False))
    assert problems("Snowlight right now") == []


def test_weight_counts_as_x_does() -> None:
    assert weight("a" * 10) == 10
    assert weight("雪") == 2
    assert weight("café") == 4
    assert weight("❄️") == 4
    assert any("characters by X's count" in line for line in problems("a" * (MAX_WEIGHT + 1)))
    assert emoji_count("\U0001f468‍\U0001f469‍\U0001f467 \U0001f44d\U0001f3fd") == 2


def test_malformed_facts_are_refused() -> None:
    with pytest.raises(FactsError, match="does not parse"):
        parse_facts("- [LIVE] Bad: x")
    with pytest.raises(FactsError, match="needs its terms"):
        parse_facts("- [COMING] alerts: Phone alerts.")
    with pytest.raises(FactsError, match="repeats"):
        parse_facts("- [LIVE] a: x\n- [LIVE] a: y")
    with pytest.raises(FactsError, match="no facts"):
        parse_facts("# nothing")


def test_the_repository_facts_and_queue_pass_their_own_checks() -> None:
    content = load(REPO)
    assert len(content.images) >= 4
    assert content.queue, "the first post is queued"
    newest = content.newest()
    assert newest is not None
    for item in content.queue:
        # The strictest case: no fresh picture fits, so it goes with an older image.
        image = item.image or newest
        assert (
            check(
                item.text,
                style=item.style,
                facts=content.facts,
                image_description=image.describe(),
                image_is_today=False,
            )
            == []
        ), item.id
    first = json.loads((REPO / "social" / "queue" / "0001.json").read_text())
    assert first["text"].startswith("Snowlight dev log:")
    assert "link in my bio" in first["text"]
    for fact in content.facts.facts:
        lowered = fact.text.lower()
        for word in ("formula", "sdc", "calculator", "snow-data", "snowlight-data", "private repo"):
            assert word not in lowered, (fact.id, word)

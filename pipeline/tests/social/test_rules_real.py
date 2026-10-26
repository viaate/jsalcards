"""The deterministic checks against the repository's REAL ``social/facts.md``: drafts that
call a TESTING or COMING fact live, invent numbers or dates, hype, or call an older picture
current are refused, and true drafts pass (every draft here is SYNTHETIC)."""

from pathlib import Path

import pytest

from snowlight.social.content import load
from snowlight.social.rules import Style, check

REPO = Path(__file__).resolve().parents[3]
FACTS = load(REPO).facts
FRESH = (
    "A picture of the Snowlight map taken at 9:47 AM Central time on October 26, 2026 over"
    " the Great Lakes. Not in the picture: Snowlight's chance of no school on Monday,"
    " October 26 is at most 1% in every one of the 18227 districts with a chance."
    " (taken for this post)"
)
OLDER = (
    "A picture of the dark Snowlight map over the Great Lakes (an older picture, taken"
    " 2026-10-26, not a picture of now)"
)


def problems(text: str, *, current: bool = True, style: Style = "dev_log") -> list[str]:
    return check(
        text,
        style=style,
        facts=FACTS,
        image_description=FRESH if current else OLDER,
        image_is_today=current,
    )


@pytest.mark.parametrize(
    "text",
    [
        # Not live called live, in plain words and by negation.
        "Closings are live on Snowlight.",
        "Real time closings are live in Ohio.",
        "Closed schools now show up on Snowlight for every state.",
        "Snowlight shows closings for every state, updated every 5 minutes.",
        "You can see which schools are closed on Snowlight today.",
        "The map is no longer in testing. Go check your school.",
        "Search is done testing and works for everyone.",
        "Practice is over and the reader's finds are public now.",
        "The map is not in testing anymore.",
        "Testing is over: search by ZIP code.",
        "Get a text the second your school closes.",
        "Phone alerts ship next week.",
        "Closings glow on the map now that testing wrapped.",
        "Practice mode has been closed out, search is open.",
        "Waitlist at snowlight\u2024com",
        "Waitlist at snowlight\u00b7com",
        "Waitlist at snowlight\uff0ecom",
        "Check snowlight map dot com.",
        "Snowlight is live.",
        "Watches raise your chance now.",
        "Your school glows when it closes.",
        # Hype and comparisons.
        "Snowlight is the best snow day app out there.",
        "I built the best snow day app in America.",
        "The most precise snow day forecasts anywhere.",
        "The only map of its kind. Waitlist link in my bio.",
        "Snowlight vs the other apps.",
        "Spot on every time.",
        # Invented numbers, number words and dates.
        "Fifty schools closed in Ohio this morning.",
        "Twelve states are covered. Waitlist link in my bio.",
        "Two years of work. Waitlist link in my bio.",
        "Twenty-four people joined. Waitlist link in my bio.",
        "My first week of building. Waitlist link in my bio.",
        "24 schools closed today in Michigan.",
        "The reader reads 48 lists. Waitlist link in my bio.",
        "I'm launching tomorrow.",
        "Launching on November 1.",
        "Launching next Monday. Waitlist link in my bio.",
        "Launching in two weeks. Waitlist link in my bio.",
        # A count from the picture is the card's, never the post's (in view vs national).
        "312 schools glow in Ohio.",
        "1,204 schools closed across the US in practice mode.",
    ],
)
def test_untrue_drafts_are_refused_by_the_real_facts(text: str) -> None:
    assert problems(text), text


@pytest.mark.parametrize(
    "text",
    [
        "Snowlight today: calm skies over the Great Lakes, every school a faint speck.",
        "This is Snowlight as of this afternoon over the Great Lakes.",
        "Snowlight currently: quiet over the Great Lakes.",
        "Fresh look at Snowlight over the Great Lakes, just captured.",
        "Snowlight at 9:47 AM over the Great Lakes, quiet for now.",
        "Snowlight at 9 AM over the Great Lakes.",
        "The latest from my private test map.",
        "Quiet tonight on my private test map.",
    ],
)
def test_an_older_picture_is_never_called_current(text: str) -> None:
    found = problems(text, current=False)
    assert any("an older one" in line or "9:47" in line for line in found), found


@pytest.mark.parametrize(
    "text",
    [
        "Snowlight dev log: the live closings reader runs 24/7 in practice mode, checking school"
        " closing lists every 5 minutes in the morning and evening. Launching before the first"
        " real snow. Waitlist link in my bio.",
        "Dev log: I taught the closings reader to check closing lists every 5 minutes from 4 to"
        " 9 AM. Waitlist link in my bio.",
        "Closings on the map are coming this winter. Waitlist link in my bio.",
        "The map is still in private testing. The chance of no school is 1% almost everywhere"
        " in late October, which I am testing quietly.",
        "Snowlight's school directory holds 118,211 schools in 18,227 districts.",
        "Join the waitlist: one email when Snowlight goes live. Link in my bio.",
        "Quiet over the Great Lakes in my private test map. Launching before the first real"
        " snow. Waitlist link in my bio.",
        "No one sees the practice mode finds yet. Waitlist link in my bio.",
    ],
)
@pytest.mark.parametrize("current", [True, False])
def test_true_drafts_pass_with_a_fresh_or_an_older_picture(text: str, *, current: bool) -> None:
    style: Style = "waitlist" if "link in my bio" in text.lower() else "dev_log"
    assert problems(text, current=current, style=style) == []


def test_a_picture_day_may_be_said_as_the_picture_says_it() -> None:
    assert problems("Monday's chance in my test map is 1% almost everywhere.") == []
    assert problems("Monday I launch. Waitlist link in my bio.", style="waitlist")

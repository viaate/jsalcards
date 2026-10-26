"""The deterministic checks against the repository's REAL ``social/facts.md``: drafts that
call a TESTING or COMING fact live, invent numbers or dates, hype, or call an older picture
current are refused, and true drafts pass (every draft here is SYNTHETIC)."""

import gzip
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from snowlight.social.content import load
from snowlight.social.rules import Style, check, model_fact_for, numbers_in

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
        " closing lists every 5 minutes in the morning and evening. The chances come from a"
        " prediction model, not a guess. Waitlist link in my bio.",
        "Dev log: I taught the closings reader to check closing lists every 5 minutes from 4 to"
        " 9 AM. The chances come from a statistical model. Waitlist link in my bio.",
        "Closings on the map are coming this winter. Until then, every district gets a chance"
        " from a prediction model. Waitlist link in my bio.",
        "The map is still in private testing. The chance of no school is 1% almost everywhere"
        " in late October, and it comes from a statistical model, not a guess.",
        "Snowlight's school directory holds 118,211 schools in 18,227 districts, and each one"
        " gets a chance from the same prediction model.",
        "Join the waitlist: one email when Snowlight goes live. The chances come from a real"
        " prediction model trained on real closing records. Link in my bio.",
        "Quiet over the Great Lakes in my private test map. The model is trained on 2,388 real"
        " past school days with a known outcome. Waitlist link in my bio.",
        "No one sees the practice mode finds yet, but the prediction model runs every school"
        " day. Waitlist link in my bio.",
    ],
)
@pytest.mark.parametrize("current", [True, False])
def test_true_drafts_pass_with_a_fresh_or_an_older_picture(text: str, *, current: bool) -> None:
    style: Style = "waitlist" if "link in my bio" in text.lower() else "dev_log"
    assert problems(text, current=current, style=style) == []


def test_a_picture_day_may_be_said_as_the_picture_says_it() -> None:
    assert problems("Monday's chance in my test map is 1% almost everywhere, from the model.") == []
    assert problems("Monday I launch. Waitlist link in my bio.", style="waitlist")


# Model first (E): every post states a LIVE model fact; TESTING and COMING model work is never
# called live; numbers only as the facts give them; no accuracy, no one else.

MODEL_TRUE = [
    "Snowlight dev log: each school district's chance comes from a statistical model trained"
    " on 2,388 real past school days with known outcomes, not a guess. Waitlist link in my bio.",
    "Private schools get their own chance too, from the same kind of model, trained on 661 real"
    " past private school days with a known outcome.",
    "Where a district has few recorded days of its own, the model leans on its nearby"
    " districts, county, state, region and the whole country.",
    "The model sorts each school day by the weather service's winter alerts, and the chance"
    " moves when a winter storm warning goes up.",
    "I tested the model walk-forward on past winters it never saw.",
    "The model works out a new set of chances about every 30 minutes.",
    "The model's forecast reasons are built, and I am testing them with them switched off.",
    "Once closings are on the map this winter, the model will learn from them.",
]


@pytest.mark.parametrize("text", MODEL_TRUE)
def test_true_model_drafts_pass(text: str) -> None:
    style: Style = "waitlist" if "link in my bio" in text.lower() else "dev_log"
    assert problems(text, style=style) == []


@pytest.mark.parametrize(
    "text",
    [
        # No model fact at all.
        "Dev log: the closings reader runs 24/7 in practice mode. Waitlist link in my bio.",
        "Join the waitlist. Link in my bio.",
        # TESTING or COMING model work called live.
        "The model reads the snow forecast for every district.",
        "The prediction model learns from real closings every night.",
        "The model retrains itself after every school day.",
        "The night-before outlook raises the chance in the prediction model.",
        "A winter storm watch raises your chance in my prediction model.",
        "The model counts how much snow is on the way.",
        # Numbers the facts do not give, or a fact's number used for something else.
        "The model is trained on 5,000 real school days.",
        "I have 2,388 followers and a prediction model.",
        "The prediction model is 95% right.",
        "The model was tested on 11 states.",
        "The model is trained on twenty years of closings records.",
        # Accuracy, hype and anyone else.
        "The most accurate prediction model for snow days.",
        "A prediction model with 90% accuracy.",
        "My AI model predicts snow days.",
        "An AI-powered prediction model.",
        "A machine learning model for snow days.",
        "Unlike other snow day sites, Snowlight uses a real prediction model.",
        "Unlike most predictors, the model is trained on real records.",
        "Other apps guess. Snowlight uses a statistical model.",
        "Other sites just guess; my prediction model does not.",
        "Most snow day apps are a guess. Mine is a statistical model.",
        "Other predictors use a formula. Mine is a prediction model.",
        "Everyone else guesses; I built a prediction model.",
        "The prediction model is better than a snow day calculator.",
        "My statistical model beats the snow day calculators.",
        "No more calculators: a real prediction model.",
        "A prediction model is smarter than a guess.",
        "It is more accurate than the competition: a real prediction model.",
        "The model is more reliable than the others.",
        "My competitors guess; my prediction model does not.",
        "Not like the other snow day predictors: a real prediction model.",
        "The prediction model is more careful than other tools.",
        "A real prediction model, not a guess like they use.",
        "Snowday Calculator uses a formula; I use a prediction model.",
        "They just guess. Snowlight has a prediction model.",
        "I guess the model is good.",
        # People cannot use it yet.
        "Check your school's chance from the prediction model now.",
        "You can now see every chance from the prediction model.",
        "The model's chances are available now for every district.",
        "Try it: a real prediction model for your school.",
    ],
)
def test_untrue_model_drafts_are_refused(text: str) -> None:
    style: Style = "waitlist" if "link in my bio" in text.lower() else "dev_log"
    assert problems(text, style=style), text


def test_not_a_guess_is_the_one_guess_a_post_may_say() -> None:
    assert problems("The chances come from a statistical model, not a guess.") == []
    assert problems("The chances come from a statistical model, never a guess.") == []
    assert problems("The chances are a guess from a statistical model.")
    assert problems("No guessing: a statistical model.")


def test_the_waitlist_may_be_open_to_everyone() -> None:
    assert (
        problems(
            "The waitlist is open to everyone, and the chances come from a prediction model."
            " Link in my bio.",
            style="waitlist",
        )
        == []
    )
    assert problems("At launch you can see your school's chance from the prediction model.") == []


def test_the_day_model_fact_must_be_the_one_stated() -> None:
    days = FACTS.get("model-days")
    assert days is not None
    said = "The chances come from a prediction model, not a guess."
    found = check(
        said,
        style="dev_log",
        facts=FACTS,
        image_description=FRESH,
        image_is_today=True,
        model_fact=days,
    )
    assert found == ["it does not state the model fact it was given (model-days)"]
    stated = "The model is trained on 2,388 real past school days with a known outcome."
    assert (
        check(
            stated,
            style="dev_log",
            facts=FACTS,
            image_description=FRESH,
            image_is_today=True,
            model_fact=days,
        )
        == []
    )


def test_model_facts_rotate_one_a_day_through_every_live_one() -> None:
    model = FACTS.model
    assert len(model) % 2 == 1, "an odd count pairs every fact with both alternating styles"
    assert all(fact.status == "LIVE" for fact in model)
    start = date(2026, 10, 27)
    seen = [model_fact_for(FACTS, start + timedelta(days=n)) for n in range(len(model))]
    assert {fact.id for fact in seen if fact is not None} == {fact.id for fact in model}
    assert model_fact_for(FACTS, start) != model_fact_for(FACTS, start + timedelta(days=1))


def test_the_model_facts_hold_only_numbers_from_the_runbook_and_the_model_file() -> None:
    predict = (REPO / "docs" / "predict.md").read_text(encoding="utf-8")
    for fact in FACTS.model:
        for number in numbers_in(fact.text):
            if number == "11":  # the committed model's training seasons, 2015 to 2025
                continue
            spaced = f"{int(number):,}" if number.isdigit() else number
            assert spaced in predict, (fact.id, number)
    for fact in FACTS.facts:
        assert "accura" not in fact.text.lower(), fact.id


def test_the_model_file_holds_the_facts_numbers() -> None:
    model = json.loads(
        gzip.decompress((REPO / "pipeline" / "data" / "predict" / "model.json.gz").read_bytes())
    )
    days = FACTS.get("model-days")
    private = FACTS.get("model-private")
    assert days is not None
    assert private is not None
    assert f"{model['training']['labeled_days']:,}" in days.text
    assert f"{len(model['training']['seasons'])} past winters" in days.text
    assert f"{model['private_labeled_days']:,}" in private.text

"""The deterministic checks against the repository's REAL ``social/facts.md``: drafts that
call a TESTING or COMING fact live, invent numbers or dates, hype, or call an older picture
current are refused, and true drafts pass (every draft here is SYNTHETIC)."""

import gzip
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from snowlight.social.content import load
from snowlight.social.rules import (
    FactsError,
    Style,
    chances_shown,
    check,
    model_fact_for,
    numbers_in,
    parse_facts,
)

REPO = Path(__file__).resolve().parents[3]
FACTS = load(REPO).facts
FRESH = (
    "A picture of the Snowlight map taken at 9:47 AM Central time on Monday, October 26, 2026"
    " over the Great Lakes. (taken for this post)"
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
        "Snowlight dev log: the live closings reader runs 24/7, checking school closing lists"
        " every 5 minutes in the morning and evening. The chances come from a prediction model,"
        " not a guess. Waitlist link in my bio.",
        "Dev log: I taught the closings reader to check closing lists every 5 minutes from 4 to"
        " 9 AM. The chances come from a statistical model. Waitlist link in my bio.",
        "Closings on the map are coming this winter. Until then, every district gets a chance"
        " from a prediction model. Waitlist link in my bio.",
        "The map is still in private testing, and its chances come from a statistical model,"
        " not a guess.",
        "Snowlight's school directory holds 118,211 schools in 18,227 districts, and each one"
        " gets a chance from the same prediction model.",
        "Join the waitlist: one email when Snowlight goes live. The chances come from a real"
        " prediction model trained on real closing records. Link in my bio.",
        "Quiet over the Great Lakes in my private test map. The model is trained on 2,388 real"
        " past school days with a known outcome. Waitlist link in my bio.",
        "Closed schools glow on my map in private testing, and the prediction model runs every"
        " school day. Waitlist link in my bio.",
    ],
)
@pytest.mark.parametrize("current", [True, False])
def test_true_drafts_pass_with_a_fresh_or_an_older_picture(text: str, *, current: bool) -> None:
    style: Style = "waitlist" if "link in my bio" in text.lower() else "dev_log"
    assert problems(text, current=current, style=style) == []


def test_a_picture_day_may_be_said_as_the_picture_says_it() -> None:
    assert (
        problems("Monday over the Great Lakes in my test map. The chances come from a model.") == []
    )
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
            # A live claim and a TESTING fact are never in one sentence: the waitlist's openness
            # and the chances (TESTING while the site is locked) are said apart.
            "The waitlist is open to everyone. The chances come from a prediction model."
            " Link in my bio.",
            style="waitlist",
        )
        == []
    )
    assert problems("At launch you can see your school's chance from the prediction model.") == []
    assert problems(
        "The waitlist is open to everyone, and the chances come from a prediction model.",
    ), "a live claim in a sentence that names the TESTING chances"


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


# Chances while the site is locked (F): while the facts file marks chances TESTING, no post
# gives a chance, by number, percent, odds or level; saying where they come from is fine.


def test_the_real_facts_file_marks_chances_testing_and_gives_no_chance_number() -> None:
    chances = FACTS.get("chances")
    assert chances is not None
    assert chances.status == "TESTING", "the site is locked: chances are TESTING"
    assert not chances_shown(FACTS)
    assert not any(number.endswith("%") for number in FACTS.numbers)
    assert "%" not in FACTS.said
    assert "percent" not in FACTS.said.lower()


@pytest.mark.parametrize(
    "text",
    [
        "A public school district in Montana is at 74% for Tuesday, from the prediction model.",
        "The prediction model gives a 1% chance of no school almost everywhere.",
        "The chance of no school is 1% almost everywhere, from a statistical model.",
        "The country sits at 1 percent from my prediction model.",
        "Fifty percent chance in Maine, says the statistical model.",
        "A \uff17\uff14\uff05 chance in Montana, says the prediction model.",
        "The statistical model puts the odds of a snow day in Montana at 3 in 4.",
        "The prediction model says one in four districts may close Tuesday.",
        "Every chance from the statistical model is low this week.",
        "A high chance of no school in Montana, says the prediction model.",
        "Chances are rising across the Northeast, says the prediction model.",
        "The prediction model's chances jumped in Montana.",
        "Near zero chance of a snow day anywhere, per the prediction model.",
        "The model gives Montana the highest chance in the country.",
    ],
)
def test_no_post_gives_a_chance_while_chances_are_testing(text: str) -> None:
    style: Style = "waitlist" if "link in my bio" in text.lower() else "dev_log"
    assert problems(text, style=style), text


def test_a_picture_description_with_a_chance_is_refused_while_chances_are_testing() -> None:
    described = (
        "A picture of the Snowlight map zoomed to a public school district in Montana: its"
        " chance of no school on Tuesday is 74%."
    )
    found = check(
        "The chances come from a statistical model, not a guess.",
        style="dev_log",
        facts=FACTS,
        image_description=described,
        image_is_today=True,
    )
    assert "the picture's description gives a chance while chances are TESTING" in found


def test_the_first_post_names_the_chances_only_as_the_model_s() -> None:
    text = json.loads((REPO / "social" / "queue" / "0001.json").read_text(encoding="utf-8"))
    assert "%" not in text["text"]
    assert problems(text["text"]) == []


def _facts_with_chances(status: str, text: str) -> str:
    real = (REPO / "social" / "facts.md").read_text(encoding="utf-8")
    lines = [
        f"- [{status}] chances: {text} | terms: chance, chances, odds"
        if line.startswith("- [TESTING] chances:")
        else line
        for line in real.splitlines()
    ]
    return "\n".join(lines)


def test_the_facts_file_may_give_no_chance_number_while_chances_are_testing() -> None:
    with pytest.raises(FactsError, match="chance"):
        parse_facts(
            _facts_with_chances("TESTING", "In late October the chance is 1% almost everywhere.")
        )
    with pytest.raises(FactsError, match="chance"):
        parse_facts(_facts_with_chances("TESTING", "The odds are 3 in 4 in a storm."))


def test_marking_chances_live_lets_a_chance_number_from_the_facts_be_posted() -> None:
    live = parse_facts(
        _facts_with_chances(
            "LIVE",
            "Every school day the model works out a chance of no school; in late October that"
            " chance is 1% almost everywhere.",
        )
    )
    assert chances_shown(live)
    text = (
        "In late October the chance of no school is 1% almost everywhere, from a statistical model."
    )
    assert (
        check(text, style="dev_log", facts=live, image_description=FRESH, image_is_today=True) == []
    )
    assert check(text, style="dev_log", facts=FACTS, image_description=FRESH, image_is_today=True)


# -- the critics' adversarial drafts (round 1): each must be refused ---------------------------

COMPARISONS = [
    "Most snow day trackers are vibes. Mine is a prediction model trained on real closing"
    " records. Link in my bio.",
    "The usual snow day sites don't use real records. Snowlight's prediction model does."
    " Link in my bio.",
    "The big snow day sites never show their work. My prediction model is trained on real"
    " closing records. Link in my bio.",
    "Popular snow day trackers run on vibes. Snowlight runs on a prediction model. Link in my bio.",
    "Real records, not vibes like the famous snow day site. Snowlight uses a prediction model."
    " Link in my bio.",
    "Snowday Predictor uses vibes. I use a prediction model. Link in my bio.",
    "Snow-Day Calculator style sliders are not a prediction model. Link in my bio.",
    "Not like SnowDay.AI: Snowlight's chances come from a prediction model. Link in my bio.",
    "Other people eyeball the radar. I built a prediction model trained on real closing"
    " records. Link in my bio.",
    "Lots of folks just look at the radar and hope. I built a prediction model instead. Link"
    " in my bio.",
    "Most people go with a gut feeling about snow days. My chances come from a prediction"
    " model, not a guess. Link in my bio.",
    "No hype, no vibes like you see elsewhere: a prediction model trained on real closing"
    " records. Link in my bio.",
    "There are lots of snow day predictions out there. Mine come from a statistical model"
    " trained on 2,388 real past school days. Link in my bio.",
    "Chatgpt can't tell you this, but my prediction model trained on real closing records"
    " can. Link in my bio.",
    "Snowlight's prediction model outperforms the snow day apps. Link in my bio.",
    "Snowlight's prediction model outdoes every snow day app out there. Link in my bio.",
    "A prediction model trained on real closing records, superior to snow day apps. Link in"
    " my bio.",
]
CHANCE_OFFERED = [
    "See your district's chance from the prediction model. Link in my bio.",
    "Look up your district's chance from the prediction model. Link in my bio.",
    "The model's chances for every district are up on Snowlight. Link in my bio.",
    "The prediction model's chances are posted for every district. Link in my bio.",
    "Your district's chance comes from a prediction model. Find it on Snowlight. Link in my bio.",
    "Parents are already checking each district's chance from the prediction model. Link in"
    " my bio.",
    "Every district now gets a chance from the prediction model, refreshed every 30 minutes"
    " for you. Link in my bio.",
]
ACCURACY_AND_PRODUCT = [
    "The prediction model is always right about snow days. Link in my bio.",
    "I tested the model walk-forward on past winters and it called most snow days right."
    " Waitlist link in my bio.",
    "Walk-forward on past winters, the model's hit rate held up on days it never saw. Link in"
    " my bio.",
    "The prediction model is reliable: trained on real closing records. Link in my bio.",
    "Snowlight's model has chances near nothing for now in every district. Link in my bio.",
    "Download the Snowlight app: its chances come from a prediction model. Link in my bio.",
    "Schools use Snowlight's prediction model. Link in my bio.",
    "Snowlight is free forever, with a prediction model. Link in my bio.",
    "Parents trust the prediction model behind Snowlight. Link in my bio.",
    "The prediction model ran for Bozeman Public Schools. Link in my bio.",
    "The prediction model ran for Katy ISD. Link in my bio.",
    "Snowlight's chances come from an A I model, not a guess. Link in my bio.",
    "Snowlight's chances come from a ML prediction model, not a guess. Link in my bio.",
    "Snowlight's chances come from a neural net prediction model, not a guess. Link in my bio.",
    "Snowlight's prediction model v3 is trained on real closing records. Link in my bio.",
    "Dev log: the prediction model is trained on real closing records. Join the waitlist.",
]


@pytest.mark.parametrize("text", COMPARISONS + CHANCE_OFFERED + ACCURACY_AND_PRODUCT)
@pytest.mark.parametrize("style", ["dev_log", "waitlist"])
def test_comparisons_offers_accuracy_and_product_claims_are_refused(
    text: str, style: Style
) -> None:
    assert problems(text, style=style), text


@pytest.mark.parametrize(
    "text",
    [
        "Dev log: the model sorts each school day by the National Weather Service winter alerts"
        " over the district. Waitlist link in my bio.",
        "Snowlight's chances come from a prediction model trained on real closing records, not"
        " a guess. Join the waitlist, link in my bio.",
        "I tested the model walk-forward on past winters, so it never saw the days it was scored"
        " on. Link in my bio.",
        "Private schools get their own chance from the same kind of model, trained on 661 real"
        " past private school days with a known outcome.",
        "The model works out a new set of chances about every 30 minutes. Waitlist link in my bio.",
        "Dev log: for each kind of weather day, the model uses a district's own recorded days"
        " where it has enough, and leans on its county, state and region where it has fewer.",
    ],
)
def test_plain_true_model_posts_still_pass(text: str) -> None:
    style: Style = "waitlist" if "link in my bio" in text.lower() else "dev_log"
    assert problems(text, style=style) == []


def test_the_first_post_still_passes() -> None:
    first = json.loads((REPO / "social" / "queue" / "0001.json").read_text(encoding="utf-8"))
    assert problems(first["text"]) == []


# -- the critics' adversarial drafts (round 2): each must be refused, with the model fact and
# the waitlist line around it, so only the part under test can be what refuses it -------------

CYRILLIC_A = chr(0x430)
CYRILLIC_DZE = chr(0x405)
ZERO_WIDTH = chr(0x200B)
LINK = " Waitlist link in my bio."
MODEL = " Snowlight's chances come from a prediction model, not a guess."
NOT_LIVE_BLEED = [
    # A not-live word said of one thing never excuses another in the same sentence.
    "Closed schools glow on the map tonight, and phone alerts are coming this winter.",
    "Closings glow on the map; notifications are coming.",
    "Closings glow on the map, notifications next.",
    "Coming next: notifications. Closings glow on the map.",
    "Every closed school glows on the map, and I'm adding more this winter.",
    "Before launch I put every closed school on the map.",
    "The reader finds closings and they show on the map, with more coming.",
    "The night-before outlook is on for every district and notifications are coming.",
    "The model learns from every closing each night, with more coming.",
    "The model uses the forecast for every chance, and the waitlist is open before launch.",
    "Winter storm watches raise the chance now, and I am still building the rest.",
    "I finished the map; every school on it, with launch this winter.",
    # Practice and testing excuse only the reader's practice and the TESTING facts.
    "In practice mode the closings reader lights up closed schools on the map.",
    "The reader puts closed schools on the map in practice mode, every 5 minutes.",
    "The night-before outlook runs on the map while I test it.",
    # On or done next to a TESTING or COMING thing.
    "Watches already raise chances while I test them.",
    "Phone alerts work in testing now.",
    "Practice mode ends this week.",
    "I turned on the night-before outlook.",
    "Search by ZIP code works.",
]
COMPARISONS_2 = [
    "Other products use vibes; Snowlight's chances come from a prediction model.",
    "My rivals use vibes; Snowlight's chances come from a prediction model.",
    "TV stations post lists; Snowlight's chances come from a prediction model, not a guess.",
    "News sites wait for the call; Snowlight's chances come from a prediction model.",
    "Instead of eyeballing radar, Snowlight's chances come from a prediction model.",
    "No rumors, no vibes: Snowlight's chances come from a prediction model, not a guess.",
    "Forget the pajamas inside out trick; Snowlight's chances come from a prediction model.",
    "Your local weatherman goes by feel; Snowlight's chances come from a prediction model.",
    "Alternatives go by feel; Snowlight's chances come from a prediction model.",
    "Weather apps go by feel; Snowlight's chances come from a prediction model.",
    "Snowlight's prediction model is trained on the biggest set of real closing records.",
    "Proud of this: the prediction model is trained on 2,388 real past school days, the"
    " largest set of closing records.",
    "Snowlight's prediction model is the first trained on real closing records.",
    "Snowlight's prediction model is unmatched, trained on real closing records.",
    "Snowlight's prediction model is unique: trained on real closing records.",
    "Snowlight's prediction model is one of a kind, trained on real closing records.",
    "Not S.D.C.: Snowlight's chances come from a prediction model.",
    "Not S D C: Snowlight's chances come from a prediction model.",
    "Not s-d-c: Snowlight's chances come from a prediction model.",
    "Not Snow Day C" + CYRILLIC_A + "lculator: Snowlight's chances come from a prediction model.",
    "Not Snow Day Calcu" + ZERO_WIDTH + "lator: Snowlight's chances come from a prediction model.",
    "Not " + CYRILLIC_DZE + "now Day Predictor: Snowlight's chances come from a prediction model.",
]
NUMBERS_REUSED = [
    "The prediction model learned from 11 past winters of storms in 11 states.",
    "The prediction model is trained on 2,388 real past school days and 661 snow days.",
    "Private schools get their own chance from the same kind of model, and 661 of them closed"
    " last winter.",
    "The reader checks 118,211 schools every 5 minutes, and the prediction model is trained on"
    " 2,388 real past school days.",
    "The prediction model was trained on 1,547 snow days with known outcomes.",
    "The prediction model has 2,388 followers.",
]
ACCURACY_IN_WORDS = [
    "The model, tested walk-forward on past winters, is rarely wrong.",
    "Snowlight's statistical model is proven on past winters it never saw.",
    "I tested the model walk-forward on past winters and it works.",
    "I tested the model walk-forward on past winters and it held up.",
    "I tested the model walk-forward on past winters; it scored well.",
    "I tested the model walk-forward on past winters for precision.",
    "You can count on the model: tested walk-forward on past winters.",
    "Snowlight's chances are science-backed: a statistical model, not a guess.",
]
INVENTED = [
    "HUGE news: Snowlight's statistical model is trained on real past school days.",
    "Massive update: Snowlight's statistical model is trained on real past school days.",
    "Our team trained Snowlight's prediction model on real closing records.",
    "We trained Snowlight's prediction model on real closing records.",
    "Backed by investors, Snowlight's chances come from a prediction model.",
    "My friend Jake helped train Snowlight's prediction model.",
    "Join the waitlist for daily emails. Snowlight's chances come from a prediction model.",
    "Your email is never shared. Snowlight's chances come from a prediction model.",
    "The waitlist keeps growing. Snowlight's chances come from a prediction model.",
    "Parents love it: Snowlight's chances come from a prediction model.",
]
CHANCE_WITHOUT_THE_WORD = [
    "Snowlight's chances come from a prediction model; one district is a coin flip.",
    "Snowlight's model says a snow day is near certain somewhere.",
    "Snowlight's model says some districts probably close.",
    "Snowlight's statistical model is watching Montana closely.",
    "Snowlight's prediction model expects closings in Maine.",
    "It's fifty-fifty for one school district, says Snowlight's prediction model.",
    "Snowlight's prediction model covers every district, Alaska and Hawaii too.",
]
NAMES_2 = [
    "Lincoln High's chance comes from Snowlight's prediction model.",
    "Denver Public School's chance comes from Snowlight's prediction model.",
    "Lincoln Middle School's chance comes from Snowlight's prediction model.",
    "Jefferson Elementary is on Snowlight's prediction model.",
]


@pytest.mark.parametrize(
    "text",
    NOT_LIVE_BLEED
    + COMPARISONS_2
    + NUMBERS_REUSED
    + ACCURACY_IN_WORDS
    + INVENTED
    + CHANCE_WITHOUT_THE_WORD
    + NAMES_2,
)
@pytest.mark.parametrize("style", ["dev_log", "waitlist"])
def test_round_two_drafts_are_refused_with_the_model_fact_and_the_link(
    text: str, style: Style
) -> None:
    whole = text + ("" if "prediction model" in text or "statistical model" in text else MODEL)
    assert problems(whole + LINK, style=style), whole


def test_each_round_two_draft_is_refused_for_what_it_is() -> None:
    def said(text: str) -> str:
        return " | ".join(problems(text + MODEL + LINK, style="waitlist"))

    assert "'the map'" in said("Closings glow on the map; notifications are coming.")
    assert "notifications" not in said("Closings glow on the map; notifications are coming.")
    assert "'practice'" in said("In practice mode the closings reader lights up closed schools.")
    assert "'already'" in said("Watches already raise chances while I test them.")
    assert "'ends'" in said("Practice mode ends.")
    assert "'works'" in said("Search by ZIP code works.")
    assert "number 11 is not used" in said("The model learned from 11 past winters in 11 states.")
    assert "number 118211 is not used" in said("The reader checks 118,211 schools.")
    assert "not plain Latin" in said("Not Snow Day C" + CYRILLIC_A + "lculator.")
    assert "'sdc'" in said("Not S.D.C.").lower() or "sdc" in said("Not S.D.C.").lower()
    assert "Montana" in said("The model is watching Montana closely.")
    assert "person" in said("My friend Jake helped.")


def test_practice_mode_is_stale_once_the_facts_drop_it() -> None:
    """The owner switched the closings reader on: "practice mode" is no fact any more."""
    assert "practice" not in FACTS.said.lower()
    found = problems(
        "Dev log: the closings reader runs 24/7 in practice mode." + MODEL + LINK, style="waitlist"
    )
    assert any("'practice'" in line for line in found), found


def test_live_closings_never_open_the_locked_map() -> None:
    """Closings and the glow are LIVE, but the map stays TESTING: a post that puts them on
    the map says the map is private, and no LIVE fact's own words excuse it."""
    assert all("map" not in fact.text.lower() for fact in FACTS.facts if fact.status == "LIVE")
    refused = problems("Closed schools glow on the map." + MODEL + LINK, style="waitlist")
    assert any("'the map'" in line for line in refused), refused
    assert (
        problems(
            "Closed schools glow on my map in private testing." + MODEL + LINK, style="waitlist"
        )
        == []
    )


TRUE_2 = [
    # A not-live word right by each thing that is not live, in its own clause.
    "Phone alerts are coming this winter, and the night-before outlook is coming too.",
    "Closed schools glow on the map, still in private testing, and phone alerts are coming too.",
    "I am testing the model's forecast reasons, which are built but switched off.",
    "The model's forecast reasons are built, and I am testing them with them switched off.",
    "A winter storm watch can raise a district's chance; I am testing that quietly first.",
    "Every school closing in the US on one map, coming this winter.",
    "The closings reader runs 24/7, checking closing lists, and the map is in private testing.",
    "Closed schools glow on the map while I test it.",
    "Schools glow and phone alerts are coming.",
    # Numbers as the facts use them.
    "The prediction model is trained on records of 11 past winters.",
    "Snowlight's school directory holds 118,211 schools in 18,227 districts.",
    "Private schools get their own chance from the same kind of model, trained on 661 real"
    " past private school days.",
    "The closings reader checks school closing lists every 5 minutes from 4 to 9 AM.",
]


@pytest.mark.parametrize("text", TRUE_2)
def test_round_two_true_drafts_still_pass(text: str) -> None:
    whole = text + ("" if "model" in text else MODEL)
    assert problems(whole + LINK, style="waitlist") == []


def test_the_chances_fact_names_only_the_lower_48_states() -> None:
    chances = FACTS.get("chances")
    assert chances is not None
    assert "lower 48 states" in chances.text
    assert "every US" not in chances.text
    assert "every US public school district" not in FACTS.said


def checked(text: str, *, commits: tuple[str, ...] = (), style: Style = "waitlist") -> list[str]:
    """The problems of ``text`` with the model fact and the link; with ``commits`` holding the
    draft itself, every word of it is in the closed vocabulary, so only the other rules speak."""
    return check(
        text,
        style=style,
        facts=FACTS,
        image_description=NATIONAL,
        image_is_today=True,
        commits=commits,
    )


NATIONAL = (
    "A picture of the dark Snowlight map of the contiguous US taken at 8:05 PM Central time on"
    " October 26, 2026: near-black land, gray state lines and city names. At this zoom the map"
    " draws no school specks. (taken for this post)"
)
MODEL_3 = (
    " Snowlight's chances come from a prediction model trained on real closing records, not a"
    " guess."
)
BLEED_3 = [
    # A not-live word in one clause never excuses a term in the next.
    "Phone alerts are coming; closed schools glow on the map tonight.",
    "Phone alerts are coming; the outlook runs for every state.",
    "Phone alerts are next; the outlook shows for every state.",
    "Push alerts soon, closings on the map tonight.",
    # A coming word with "it" or "them" never speaks of what came before.
    "Closed schools glow on the map, and I will keep polishing it.",
    "Every closed school glows on the map and I will tune them.",
    # One not-live word across a verb never speaks of a list.
    "The outlook runs and phone alerts are coming.",
    "Search by ZIP code runs and phone alerts are coming.",
    "Closings show on the map and notifications are coming.",
    # Testing left behind is a live claim.
    "The map left testing.",
    "The map graduated from testing.",
    "The map came out of testing.",
    "The map moved past testing.",
    "Practice mode is out of beta.",
    # A testing word never excuses an access phrase.
    "You can search by ZIP code while I keep testing.",
    "You can search by ZIP code, still in testing.",
]
OTHERS_3 = [
    "Not Snow Day Calc:",
    "Not SDCalc:",
    "Not SnowDay Predict:",
    "Not snowdaycalc:",
    "Most predictions online are made up;",
    "Plenty of people eyeball the sky.",
    "Influencers hype every storm.",
    "Another site plugs in snowfall totals.",
    "Old wives' tales say flush ice cubes;",
    "Grandma flushes ice cubes down the toilet;",
    "Hunches are fun.",
    "Way beyond a snowfall widget:",
    "Nothing else does this:",
]
CLAIMS_3 = [
    "Snowlight runs an industry-leading prediction model trained on real closing records, not a"
    " guess.",
    "Snowlight's state-of-the-art prediction model is trained on real closing records, not a"
    " guess.",
    "Snowlight's prediction model is the gold standard, trained on real closing records, not a"
    " guess.",
    "Snowlight's prediction model is as good as it gets, trained on real closing records, not a"
    " guess.",
    "Snowlight's prediction model is top-notch and trained on real closing records, not a guess.",
    "Snowlight's prediction model outclasses the field and is trained on real closing records,"
    " not a guess.",
    # Accuracy in other words.
    "The model held its own on past winters it never saw.",
    "The model lands most calls on past winters it never saw.",
    "Strong results walk-forward on past winters it never saw.",
    "Walk-forward tested on past winters it never saw, and the results impressed me.",
    "I'm confident in the model after testing it walk-forward on past winters it never saw.",
    # Invented claims.
    "Android and iPhone are coming this winter.",
    "iPhone version is coming.",
    "You'll get an email every morning there's a snow day.",
    "I hired a meteorology student to help.",
    "Snowlight partnered with a school district.",
    "Snowlight got featured on the local paper.",
    "The waitlist blew up overnight.",
    "A bunch of you joined the waitlist this week.",
    "Some of you joined the waitlist this week.",
    "Superintendents already asked for access.",
    "No charge for families.",
    "My GitHub is viaate.",
    "Snowlight's prediction model is trained on a decade of real closing records, not a guess.",
    "Snowlight's prediction model is trained on years of real closing records, not a guess.",
    # A chance's level without a number while chances are TESTING.
    "The model says a few districts could close.",
    "Some schools might get a snow day this week, says the model.",
    "Snow day looking good for the Northeast, per the model.",
    "The model's numbers are high for the Rockies.",
    "The prediction model has its eye on the Rockies.",
    "The model put Denver's chance way up.",
]


@pytest.mark.parametrize("text", BLEED_3 + OTHERS_3 + CLAIMS_3)
@pytest.mark.parametrize("style", ["dev_log", "waitlist"])
def test_round_three_drafts_are_refused(text: str, style: Style) -> None:
    whole = text + ("" if "prediction model" in text else MODEL_3) + LINK
    assert checked(whole, style=style), whole


@pytest.mark.parametrize("text", BLEED_3)
def test_round_three_bleeds_are_refused_by_the_not_live_rules_alone(text: str) -> None:
    whole = text + MODEL_3 + LINK
    found = checked(whole, commits=(whole,))
    assert any(
        "without saying it is" in line or "live (" in line or "use Snowlight now" in line
        for line in found
    ), (whole, found)


@pytest.mark.parametrize(
    "text",
    ["Not Snow Day Calc:", "Not SDCalc:", "Not SnowDay Predict:", "Not S.D.Calc:", "Not calcs:"],
)
def test_short_competitor_names_are_refused_by_the_name_rules_alone(text: str) -> None:
    whole = text + MODEL_3 + LINK
    found = checked(whole, commits=(whole,))
    assert any("another product" in line or "'SDC'" in line for line in found), (whole, found)


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("The model held its own on past winters it never saw.", "held its own"),
        ("I'm confident in the model.", "confident"),
        ("The results impressed me.", "results"),
        ("You'll get an email every morning there's a snow day.", "email every"),
        ("Join to get emails.", "emails"),
        ("Some of you joined the waitlist.", "joined"),
        ("The model put Denver's chance way up.", "Denver's chance"),
        ("The model says some districts could close.", "could"),
    ],
)
def test_round_three_claims_are_refused_by_their_own_rules_too(text: str, word: str) -> None:
    whole = text + MODEL_3 + LINK
    found = checked(whole, commits=(whole,))
    assert any(f"'{word}" in line for line in found), (whole, found)


@pytest.mark.parametrize(
    ("text", "unknown"),
    [
        ("Most predictions online are made up;", "online"),
        ("Influencers hype every storm.", "influencers"),
        ("Snowlight runs an industry-leading prediction model.", "industry"),
        ("Snowlight's prediction model outclasses the field.", "outclasses"),
        ("I hired a meteorology student to help.", "hired"),
        ("Android and iPhone are coming this winter.", "android"),
        ("The prediction model has its eye on the Rockies.", "eye"),
        ("Way beyond a snowfall widget:", "beyond"),
    ],
)
def test_words_outside_the_closed_vocabulary_are_named(text: str, unknown: str) -> None:
    found = " | ".join(checked(text + MODEL_3 + LINK))
    assert "words the facts" in found
    assert f"'{unknown}'" in found


R3_TRUE = [
    (
        "model",
        "Dev log: Snowlight's chances come from a real model built on real past school days,"
        " where what happened that day is on record. Not a guess. Waitlist link in my bio.",
    ),
    (
        "model",
        "Spent the night on the prediction model. It's fit to real past school days where I"
        " know what happened, so the chances aren't a guess.",
    ),
    (
        "model-days",
        "Snowlight's model learned from 2,388 real past school days with known"
        " outcomes: 1,547 with no school, 109 delayed starts, 732 open. Waitlist link in my bio.",
    ),
    (
        "model-tested",
        "I tested the model walk-forward on past winters: each winter scored by a"
        " model fit only to the winters before it, so it never saw those days.",
    ),
    (
        "model-alerts",
        "When the weather service issues a winter storm warning, the model's chance"
        " moves with it. Waitlist link in my bio.",
    ),
    (
        "model",
        "Snowlight's chances come from a prediction model, not a guess. Phone alerts are"
        " coming this winter, and the map stays in private testing.",
    ),
    (
        "model",
        "Closed schools glow like city lights on my private test map. The chances behind"
        " them come from a statistical model trained on real past school days.",
    ),
    (
        "model",
        "Phone alerts are coming this winter, and the night-before outlook is coming too."
        " Snowlight's chances come from a prediction model, not a guess.",
    ),
    (
        "model",
        "Every school closing in the US on one map, coming this winter. Snowlight's chances"
        " come from a prediction model, not a guess.",
    ),
    (
        "model",
        "At launch you can search by ZIP code. Snowlight's chances come from a prediction"
        " model, not a guess. Waitlist link in my bio.",
    ),
    (
        "model",
        "Once closings are on the map this winter, the model will learn from them."
        " Snowlight's chances come from a prediction model, not a guess.",
    ),
]


@pytest.mark.parametrize(("fact", "text"), R3_TRUE)
def test_true_paraphrases_of_live_facts_pass(fact: str, text: str) -> None:
    style: Style = "waitlist" if "link in my bio" in text else "dev_log"
    assert (
        check(
            text,
            style=style,
            facts=FACTS,
            image_description=NATIONAL,
            image_is_today=True,
            model_fact=FACTS.get(fact),
        )
        == []
    )


def test_a_commit_subject_s_words_join_the_vocabulary_only_when_shown() -> None:
    text = "Dev log: I fixed the card legend." + MODEL_3
    assert any("'card', 'legend'" in line for line in checked(text, style="dev_log"))
    assert checked(text, style="dev_log", commits=("Fix the card legend on small screens",)) == []


def test_a_known_hashtag_is_outside_the_vocabulary_and_any_other_is_a_word() -> None:
    assert checked("Dev log." + MODEL_3 + " #buildinpublic", style="dev_log") == []
    assert any("'snowdaycalc'" in line for line in checked("Dev log." + MODEL_3 + " #SnowDayCalc"))


def test_a_hype_word_is_fine_only_as_a_fact_s_own_words() -> None:
    assert not any(
        "hype" in line
        for line in checked("Each winter was scored by a model fit only to the winters before it.")
    )
    assert any("'only'" in line for line in checked("Snowlight is the only prediction model."))


# -- the owner's voice (Oct 27): personal, plain, one hook and the waitlist ask ----------------

PLAIN_VOICE = [
    "Stayed up late wiring the closings reader into Snowlight. Real closings go in within"
    " minutes, and the chances come from a real prediction model, not a guess. Waitlist link"
    " in my bio.",
    "Does your school usually call a snow day in the evening, or in the morning? I'm testing a"
    " night-before outlook for the model, quietly in the background. Waitlist link in my bio.",
    "When a school is closed or delayed for weather, it glows on my private test map like city"
    " lights seen from space. The model behind the chances is built on real closing records,"
    " not a guess. Waitlist link in my bio.",
    "I'm building Snowlight alone: a private test map of every school in the US. Built on real"
    " closing records, not a guess. Link in my bio to get on the waitlist.",
]


@pytest.mark.parametrize("text", PLAIN_VOICE)
@pytest.mark.parametrize("current", [True, False])
def test_the_plain_personal_voice_passes(text: str, *, current: bool) -> None:
    style: Style = "waitlist" if "get on the waitlist" in text else "dev_log"
    assert problems(text, current=current, style=style) == []


def test_the_plain_model_words_name_the_model_fact() -> None:
    model = FACTS.get("model")
    assert model is not None
    for words in ("real prediction model", "built on real closing records", "not a guess"):
        assert words in model.terms


@pytest.mark.parametrize(
    "text",
    [
        "My school calls a snow day early. The prediction model is not a guess." + LINK,
        "Stayed up late, and the model called it right." + LINK,
        "The map is live, built on real closing records." + LINK,
    ],
)
def test_the_voice_words_let_no_claim_through(text: str) -> None:
    assert problems(text, style="waitlist"), text

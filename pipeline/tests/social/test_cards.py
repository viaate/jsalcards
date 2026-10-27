"""The branded cards (snowlight.social.cards): the style choice from SYNTHETIC glow masks,
every truth guard with adversarial facts, the alt text, the fallback card, and (in the
pre-installed headless Chromium, skipped where none is installed) the three templates laid
over SYNTHETIC map pictures: 1600 x 900, under 5 MB, every word inside the 64 px margin."""

import itertools
import json
import re
import struct
import zlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
from playwright.sync_api import Browser, Page, sync_playwright
from playwright.sync_api import Error as PlaywrightError

import snowlight.social.cards as cards_module
from snowlight.social.cards import (
    FIT_SHARE,
    HEADLINES,
    HERE,
    INSIDER,
    MAX_BYTES,
    Candidate,
    Card,
    CardError,
    Measure,
    Post,
    a_facts,
    alt_text,
    b_card,
    c_slots,
    check_words,
    compose,
    cover,
    glow_mask,
    groups,
    headline_for,
    lay,
    pick,
    without_chances,
)
from snowlight.social.content import ContentError, load
from snowlight.social.picture import Box, Chance, Counts, Seen, Taken
from snowlight.social.rules import (
    Facts,
    mentions_chance,
    mentions_closings,
    parse_facts,
    still_true,
)

REPO = Path(__file__).resolve().parents[3]


def switches(chances: str, closings: str, model: str = "LIVE") -> Facts:
    """A SYNTHETIC facts file with the two switches as given and the A card's model line."""
    return parse_facts(
        f"- [{chances}] chances: SYNTHETIC chances. | terms: chance\n"
        f"- [{closings}] closings: SYNTHETIC closings on the map. | terms: closings\n"
        f"- [{model}] model: A prediction model trained on real closing records, not a guess:"
        " a real model, not a guess. | terms: model\n"
    )


SHOWN = switches("LIVE", "LIVE")
NO_CHANCES = switches("TESTING", "LIVE")
HELD_BACK = switches("TESTING", "COMING")
TAKEN_AT = datetime(2026, 12, 10, 12, 42, tzinfo=UTC)  # 6:42 AM CT
BLUE = (127, 212, 255)
AMBER = (255, 190, 90)
SPECK = (200, 200, 200)
LABEL = (120, 120, 120)


def taken(kind: str, seen: Seen, *, current: bool = True) -> Taken:
    return Taken(
        kind=kind,  # type: ignore[arg-type]
        query="" if kind == "national" else "?at=42.5,-84.3,6.5",
        shows="SYNTHETIC picture description for the card tests",
        taken_at=TAKEN_AT,
        current=current,
        lit=seen.lit,
        seen=seen,
        file="picture.png",
    )


STORM = Seen(
    in_view=Counts(closed=1843, delayed=1338, remote=206, early_dismissal=59),
    states=("Michigan", "Ohio"),
    lit=5021,
    closings_at=datetime(2026, 12, 10, 12, 40, tzinfo=UTC),
    closings_read=True,
)
DISTRICT = Seen(
    chance=Chance(text="77%", day=date(2026, 12, 10), scope="district", districts=18227,
                  at_most=False),
    state="Michigan",
    focus=Box(x0=339, y0=191, x1=749, y1=709),
)  # fmt: skip
CALM = Seen(
    chance=Chance(text="1%", day=date(2026, 12, 10), scope="highest", districts=18227,
                  at_most=True),
)  # fmt: skip
REGION = Seen(place="the Great Lakes and the Northeast")


def with_chance(seen: Seen, **update: object) -> Seen:
    assert seen.chance is not None
    return seen.model_copy(update={"chance": seen.chance.model_copy(update=update)})


# The style choice, from SYNTHETIC glow masks.


def canvas() -> npt.NDArray[np.uint8]:
    return np.zeros((900, 1600, 3), dtype=np.uint8)


def test_the_glow_mask_takes_lit_schools_only() -> None:
    picture = canvas()
    picture[10, 10] = BLUE
    picture[10, 11] = AMBER
    picture[10, 12] = SPECK
    picture[10, 13] = LABEL
    picture[10, 14] = (40, 60, 90)  # a dim blue: water or a far halo, not a school
    mask = glow_mask(picture)
    assert mask[10, 10:15].tolist() == [True, True, False, False, False]
    assert int(mask.sum()) == 2


def darken(picture: npt.NDArray[np.uint8], box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    picture[y0:y1, x0:x1] = picture[y0:y1, x0:x1] // 4


def test_cover_counts_the_glow_a_card_darkens() -> None:
    picture = canvas()
    picture[100:200, 100:200] = BLUE  # 10,000 lit pixels
    card = picture.copy()
    darken(card, (100, 100, 150, 200))  # half of them
    darken(card, (1000, 500, 1200, 600))  # over black: nothing lit
    measured = cover(picture, card)
    assert (measured.glow, measured.covered) == (10_000, 5_000)
    assert not measured.fits
    assert cover(picture, picture).fits


# Where each style's words sit on the card (as the templates lay them out), for the masks.
WORDS: dict[str, list[tuple[int, int, int, int]]] = {
    "c-left": [(64, 64, 760, 400), (64, 750, 1060, 836), (1200, 740, 1536, 836)],
    "c-right": [(830, 64, 1536, 400), (64, 750, 1060, 836), (1200, 740, 1536, 836)],
    "a": [(64, 380, 1120, 836), (1200, 680, 1536, 836)],
}


def choose_from(picture: npt.NDArray[np.uint8], kind: str) -> tuple[Candidate, str]:
    def measure(candidate: Candidate) -> Measure:
        if candidate == "b":  # the words beside the map: none over it
            return Measure(glow=int(glow_mask(picture).sum()), covered=0)
        card = picture.copy()
        for box in WORDS[candidate]:
            darken(card, box)
        return cover(picture, card)

    return pick(groups(taken(kind, STORM if kind == "closings" else CALM)), measure)


def test_a_storm_in_the_middle_takes_the_stamp() -> None:
    picture = canvas()
    picture[420:700, 600:1100] = BLUE
    chosen, why = choose_from(picture, "closings")
    assert chosen == "c-left"
    assert "c-left is the first style that fits" in why


def test_the_stamp_takes_the_corner_the_glow_leaves_free() -> None:
    picture = canvas()
    picture[80:380, 100:700] = BLUE  # under the left stamp
    picture[420:700, 600:1100] = AMBER
    chosen, why = choose_from(picture, "closings")
    assert chosen == "c-right"
    assert "c-left covers" in why


def test_glow_under_both_corners_and_the_lower_third_takes_the_frame() -> None:
    picture = canvas()
    picture[64:836, 64:1536] = BLUE  # lit everywhere a word could go
    chosen, why = choose_from(picture, "closings")
    assert chosen == "b"
    assert "a covers" in why, "A was measured before B"


def test_a_calm_map_takes_the_stamp_and_a_glow_there_moves_it() -> None:
    """The owner's pick: C first on every picture, the map filling the card."""
    assert choose_from(canvas(), "national")[0] == "c-left"
    assert choose_from(canvas(), "region")[0] == "c-left"
    picture = canvas()
    picture[100:300, 100:700] = BLUE  # under C's stamp, clear of A's lower third
    chosen, why = choose_from(picture, "national")
    assert chosen == "a"
    assert why.startswith("a is the first style that fits (c-left covers")


def test_pick_measures_only_what_it_must() -> None:
    asked: list[str] = []

    def measure(candidate: Candidate) -> Measure:
        asked.append(candidate)
        return Measure(glow=100, covered=0)

    assert pick((("c-left", "c-right"), ("a",), ("b",)), measure)[0] == "c-left"
    assert asked == ["c-left", "c-right"]


def test_pick_skips_a_refused_layout_and_never_returns_one() -> None:
    measures = {
        "c-left": Measure(0, 0, refused="template c: 'x' leaves the 64 px margin"),
        "a": Measure(100, 50),
        "b": Measure(100, 40),
    }
    with pytest.raises(CardError, match="no style fits without covering lit schools") as error:
        pick((("c-left",), ("a",), ("b",)), measures.__getitem__)
    assert "not usable" in str(error.value)
    assert "b covers 40 of 100" in str(error.value)
    with pytest.raises(CardError, match="no style"):
        pick((("c-left",),), {"c-left": measures["c-left"]}.__getitem__)
    fitting = {**measures, "b": Measure(100, 0)}
    assert pick((("c-left",), ("a",), ("b",)), fitting.__getitem__)[0] == "b"


PRIVATE_ONLY = Seen(
    in_view=Counts(closed=3, delayed=0, remote=0, early_dismissal=0),
    states=(),
    lit=3,
    closings_read=True,
)


def test_a_closings_stamp_never_names_a_place_it_does_not_know() -> None:
    """The lit schools in view are private (their ids name no state): the stamp gives no
    states and so names no place, never a guessed one."""
    slots = c_slots(taken("closings", PRIVATE_ONLY), "dev-log", "left", fallback=False)
    assert slots["states"] == []
    assert "place" not in slots


def test_the_stamp_lays_a_closings_view_with_no_known_state_without_a_place(
    page: Page, maps: dict[str, Path]
) -> None:
    _, words = lay(
        page, "c-left", taken("closings", PRIVATE_ONLY), "dev-log", maps["storm"],
        fallback=False, headline="Real school closings and delays",
    )  # fmt: skip
    assert "Mostly" not in words
    assert "in this view" in words


@pytest.mark.parametrize("kind", ["national", "region"])
def test_a_daytime_picture_is_never_called_night(kind: str) -> None:
    seen = Seen(place="the Great Lakes") if kind == "region" else Seen()
    for fallback in (False, True):
        alt = alt_text(taken(kind, seen), "dev-log", fallback=fallback)
        assert "night" not in alt.lower(), alt


def test_the_fit_threshold_is_a_small_share() -> None:
    assert Measure(1000, int(1000 * FIT_SHARE)).fits
    assert not Measure(1000, int(1000 * FIT_SHARE) + 1).fits
    assert Measure(0, 0).fits, "a calm map has no glow to cover"
    assert not Measure(100_000, 1, schools=1).fits, "no lit school's centre, whatever the share"


def test_one_school_under_the_lower_third_refuses_a_whatever_the_share() -> None:
    """SYNTHETIC: a big storm far from A's words, and one lit school under them. Its few
    pixels are well under the share's tolerance, but its centre is darkened: A does not fit,
    and the stamp takes the card."""
    picture = canvas()
    picture[100:300, 1250:1500] = BLUE  # 50,000 lit pixels, clear of every style's words
    picture[598:603, 398:403] = AMBER  # one school, 25 pixels, under A's lower third
    spots = ((400, 600),)

    def measure(candidate: Candidate) -> Measure:
        if candidate == "b":
            return Measure(glow=int(glow_mask(picture).sum()), covered=0)
        card = picture.copy()
        for box in WORDS[candidate]:
            darken(card, box)
        return cover(picture, card, spots)

    a = measure("a")
    assert a.share <= FIT_SHARE, "the share alone would let it pass"
    assert a.schools == 1
    assert not a.fits
    assert "over 1 lit schools" in str(a)
    chosen, why = pick((("a",), ("c-left",), ("b",)), measure)
    assert chosen != "a"
    assert "a covers" in why


def test_the_preferred_order_follows_the_owner() -> None:
    assert groups(taken("closings", STORM)) == (("c-left", "c-right"), ("a",), ("b",))
    assert groups(taken("district", DISTRICT)) == (("c-right",), ("a",), ("b",))
    right = DISTRICT.model_copy(update={"focus": Box(x0=900, y0=200, x1=1300, y1=700)})
    assert groups(taken("district", right))[0] == ("c-left",)
    assert groups(taken("national", CALM)) == (("c-left",), ("a",), ("b",))
    assert groups(taken("region", REGION)) == (("c-left",), ("a",), ("b",))


# Truth guards, with adversarial facts.


@pytest.mark.parametrize(
    ("words", "current", "fallback", "problem"),
    [
        ("Mostly Michigan \u2744", True, False, "emoji"),
        ("Snow day \U0001f328", True, False, "emoji"),
        ("Michigan \u2013 Ohio", True, False, "dash"),
        ("Michigan \u2014 Ohio", True, False, "dash"),
        ("Closed!", True, False, "exclamation"),
        ("0 schools closed", True, False, "0 schools"),
        ("No closings on the map", True, False, "no closings"),
        ("Live now", False, False, "now, live"),
        ("Closings today", True, True, "now, live"),
        ("From Oct 26, 2026 6:42 AM CT", True, True, "no clock"),
    ],
)
def test_check_words_refuses_what_is_false_or_stale(
    words: str, current: bool, fallback: bool, problem: str
) -> None:
    with pytest.raises(CardError, match=problem):
        check_words(words, current=current, fallback=fallback)


def test_check_words_passes_a_true_card() -> None:
    check_words("DEV LOG United States 6:42 AM CT · Dec 10", current=True, fallback=False)
    check_words("Live Oak, Florida", current=True, fallback=False)
    check_words("From Dec 10, 2026", current=True, fallback=True)


def test_c_slots_come_from_the_facts() -> None:
    slots = c_slots(taken("closings", STORM), "dev-log", "right", fallback=False)
    assert slots["time"] == "6:42 AM CT"
    assert slots["date"] == "Dec 10"
    assert slots["states"] == ["Michigan", "Ohio"]
    # In-view counts and the country's total stay apart.
    assert slots["counts"] == {"closed": 1843, "delayed": 1338, "remote": 206,
                               "early_dismissal": 59}  # fmt: skip
    assert slots["total"] == 5021
    assert "place" not in slots, "the closings place is the lit states, never free text"
    stale = c_slots(taken("closings", STORM, current=False), "dev-log", "left", fallback=False)
    assert stale["updatedAt"] == {"time": "6:40 AM CT", "date": "Dec 10"}
    old = c_slots(taken("closings", STORM), "waitlist", "left", fallback=True)
    assert "time" not in old
    assert old["date"] == "Dec 10, 2026"
    district = c_slots(taken("district", DISTRICT), "dev-log", "right", fallback=False)
    assert district["place"] == "A district in Michigan"
    assert (district["chance"], district["chanceDay"]) == ("77%", "Thu")
    national = c_slots(taken("national", CALM), "waitlist", "left", fallback=False)
    assert national["place"] == "United States"
    assert "chance" not in national, "the waitlist card carries the address, not the chance"


def test_a_and_b_take_iso_times_and_never_crop_the_map() -> None:
    facts = a_facts(taken("closings", STORM), "dev-log", fallback=False)
    picture = facts["picture"]
    assert isinstance(picture, dict)
    assert picture["taken_at"] == "2026-12-10T12:42:00+00:00"
    assert picture["lit"] == 5021
    district = a_facts(taken("district", DISTRICT), "dev-log", fallback=False)
    frame = district["frame"]
    assert isinstance(frame, dict)
    assert frame["free"]["x0"] >= 749 + 48
    card = b_card(taken("national", CALM), "dev-log", "file:///map.png", fallback=True)
    assert card["bg"] == {"src": "file:///map.png", "path": "map", "focus": [0, 0, 1600, 900],
                          "pad": 0}  # fmt: skip
    assert "time" not in card


def test_alt_text_is_built_from_the_facts() -> None:
    storm = alt_text(taken("closings", STORM), "dev-log", fallback=False)
    assert storm == (
        "The Snowlight map at 6:42 AM CT on Dec 10, zoomed to the area with the most schools "
        "lit up, mostly in Michigan and Ohio: 1,843 schools closed, 1,338 delayed, "
        "206 remote and 59 dismissing early in this view, and 5,021 lit up across the US, "
        "captioned Dev log."
    )
    stale = alt_text(taken("closings", STORM, current=False), "dev-log", fallback=False)
    assert stale.endswith("with the closings last updated at 6:40 AM CT, captioned Dev log.")
    district = alt_text(taken("district", DISTRICT), "waitlist", fallback=False)
    assert "a public school district in Michigan, whose chance of no school Thursday is 77%" in (
        district
    )
    assert district.endswith("captioned Join the waitlist.")
    low = with_chance(DISTRICT, text="<1%")
    assert "is under 1%" in alt_text(taken("district", low), "dev-log", fallback=False)
    national = alt_text(taken("national", CALM), "dev-log", fallback=False)
    assert national == (
        "The dark national Snowlight map, at 6:42 AM CT on Dec 10, with state lines and "
        "city names, and the chance of no school Thursday: at most 1% in every district, "
        "captioned Dev log."
    )
    region = alt_text(taken("region", REGION), "waitlist", fallback=True)
    assert region == (
        "The dark Snowlight map over the Great Lakes and the Northeast, pictured on Dec "
        "10, 2026, schools drawn as faint white specks, captioned Join the waitlist."
    )


def test_a_fallback_alt_never_says_now_or_a_clock() -> None:
    for kind, seen in (("closings", STORM), ("district", DISTRICT), ("national", CALM)):
        text = alt_text(taken(kind, seen), "dev-log", fallback=True)
        assert "pictured on Dec 10, 2026" in text
        assert not re.search(r"\d:\d\d|\bnow\b|\blive\b", text)


def test_the_alt_text_says_nothing_about_closings_it_did_not_read() -> None:
    text = alt_text(taken("national", Seen()), "dev-log", fallback=False)
    assert "closing" not in text.lower()
    assert "0 " not in text


def test_an_adversarial_place_is_refused() -> None:
    sneaky = Seen(place="the Great Lakes \u2014 live now!")
    with pytest.raises(CardError):
        alt_text(taken("region", sneaky), "dev-log", fallback=True)


def test_every_tagline_on_a_card_is_true_per_the_facts_file() -> None:
    facts = parse_facts((REPO / "social" / "facts.md").read_text(encoding="utf-8"))
    true = [fact.text.lower() for fact in facts.facts if fact.status == "LIVE"]
    a = (HERE / "a" / "card.html").read_text(encoding="utf-8")
    b = (HERE / "b" / "card.html").read_text(encoding="utf-8")
    found = re.search(r"const TAGLINE = '([^']+)'", a)
    assert found is not None
    # B's dev-log kicker is the label "Dev log"; its headline is a line of the facts file.
    lines = [found.group(1), *(x for x in re.findall(r"'dev-log': '([^']+)'", b) if x != "Dev log")]
    assert lines == ["A real model, not a guess", "Building Snowlight"]
    assert not mentions_chance(lines[0]), "the model line stays while chances are TESTING"
    model = facts.get("model")
    assert model is not None
    assert model.status == "LIVE"
    assert lines[0].lower() in model.text.lower(), "the A card's line is the LIVE model fact"
    for line in lines:
        assert any(line.lower() in fact for fact in true), line
    for html in (a, b, (HERE / "c" / "card.html").read_text(encoding="utf-8")):
        assert "No closings" not in html
        assert "on one map'" not in html, "the present-tense site line is not on a card"


# The templates in the pre-installed headless Chromium, over SYNTHETIC map pictures.


def png(picture: npt.NDArray[np.uint8]) -> bytes:
    height, width, _ = picture.shape
    rows = b"".join(b"\x00" + picture[y].tobytes() for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )


def storm_map() -> npt.NDArray[np.uint8]:
    """SYNTHETIC: specks everywhere and a lit band in the middle-left."""
    picture = canvas()
    rng = np.random.default_rng(7)
    ys, xs = rng.integers(0, 900, 4000), rng.integers(0, 1600, 4000)
    picture[ys, xs] = SPECK
    for _ in range(1500):
        y, x = int(rng.integers(420, 640)), int(rng.integers(350, 900))
        picture[y - 2 : y + 2, x - 2 : x + 2] = BLUE if x < 700 else AMBER
    return picture


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    try:
        with sync_playwright() as playwright:
            launched = playwright.chromium.launch()
            yield launched
            launched.close()
    except PlaywrightError:
        pytest.skip("no Chromium is installed here")


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1600, "height": 900})
    yield context.new_page()
    context.close()


@pytest.fixture(scope="module")
def maps(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("maps")
    calm = canvas()
    calm[::37, ::41] = SPECK
    out = {"storm": folder / "storm.png", "calm": folder / "calm.png"}
    out["storm"].write_bytes(png(storm_map()))
    out["calm"].write_bytes(png(calm))
    return out


CASES = [
    ("closings", STORM, "storm"),
    ("district", DISTRICT, "calm"),
    ("national", CALM, "calm"),
    ("region", REGION, "calm"),
]


@pytest.mark.parametrize("candidate", ["c-left", "c-right", "a", "b"])
@pytest.mark.parametrize("fallback", [False, True])
def test_every_template_lays_out_every_view_inside_the_margin(
    page: Page, maps: dict[str, Path], candidate: Candidate, fallback: bool
) -> None:
    for kind, seen, picture in CASES:
        for post in ("dev-log", "waitlist"):
            shot, words = lay(
                page, candidate, taken(kind, seen), post, maps[picture], fallback=fallback
            )
            assert shot[:8] == b"\x89PNG\r\n\x1a\n"
            assert struct.unpack(">II", shot[16:24]) == (1600, 900)
            assert len(shot) < MAX_BYTES
            assert "Snowlight" in words
            if fallback:
                assert "dec 10, 2026" in words.lower()
                assert not re.search(r"\d:\d\d", words), (candidate, kind, words)
            else:
                assert "6:42 AM CT" in words.replace("\u00a0", " ") or "6:42" in words
            assert "0 schools" not in words
            assert "2616440" not in words


def test_counts_in_view_are_labeled_and_the_total_named(page: Page, maps: dict[str, Path]) -> None:
    _, c = lay(page, "c-left", taken("closings", STORM), "dev-log", maps["storm"], fallback=False)
    assert "in this view" in c
    assert "5,021" in c
    assert "lit up across the US" in c
    _, a = lay(page, "a", taken("closings", STORM), "dev-log", maps["storm"], fallback=False)
    assert "Mostly in Michigan and Ohio" in a
    assert "Across the US" in a
    for word in ("Closed", "Delayed", "Remote", "Early dismissal"):
        assert f"{word} in this view" in a, a
    _, waitlist = lay(
        page, "a", taken("closings", STORM), "waitlist", maps["storm"], fallback=False
    )
    assert "Closed in this view" in waitlist
    _, c_calm = lay(page, "c-left", taken("national", Seen()), "dev-log", maps["calm"],
                    fallback=False)  # fmt: skip
    assert "closed" not in c_calm, "nothing is said about closings from a 404"


PCT_GAP = """() => {
  // The ink gap between the last digit before each % and the % itself, in px and in em.
  const chars = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.parentElement.closest('[hidden], script, style')) continue;
    for (let i = 0; i < n.textContent.length; i++) chars.push([n, i]);
  }
  const ctx = document.createElement('canvas').getContext('2d');
  const ink = ([n, i]) => {
    const r = document.createRange();
    r.setStart(n, i);
    r.setEnd(n, i + 1);
    const box = r.getBoundingClientRect();
    const cs = getComputedStyle(n.parentElement);
    ctx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const m = ctx.measureText(n.textContent[i]);
    return { left: box.left - m.actualBoundingBoxLeft, right: box.left + m.actualBoundingBoxRight,
      size: parseFloat(cs.fontSize) };
  };
  const out = [];
  for (let k = 1; k < chars.length; k++) {
    const [n, i] = chars[k];
    const [p, j] = chars[k - 1];
    if (n.textContent[i] !== '%' || !/[0-9]/.test(p.textContent[j])) continue;
    const digit = ink(chars[k - 1]);
    const pct = ink(chars[k]);
    out.push({ gap: pct.left - digit.right, size: digit.size });
  }
  return out;
}"""


@pytest.mark.parametrize("chance", ["7%", "17%", "77%", "97%", "71%"])
def test_the_percent_sign_never_touches_a_final_seven(
    page: Page, maps: dict[str, Path], chance: str
) -> None:
    seen = with_chance(DISTRICT, text=chance)
    national = with_chance(CALM, text=chance, at_most=False)
    cases: tuple[tuple[Candidate, str, Seen], ...] = (
        ("c-right", "district", seen),
        ("a", "district", seen),
        ("a", "national", national),
        ("b", "national", national),
    )
    for candidate, kind, facts in cases:
        lay(page, candidate, taken(kind, facts), "dev-log", maps["calm"], fallback=False)
        gaps = page.evaluate(PCT_GAP)
        assert gaps, (candidate, kind)
        for found in gaps:
            assert found["gap"] >= 0.02 * found["size"], (candidate, kind, chance, found)


def test_compose_writes_the_card_its_note_and_alt(
    browser: Browser, maps: dict[str, Path], tmp_path: Path
) -> None:
    said: list[str] = []
    card = compose(
        browser,
        taken("closings", STORM),
        maps["storm"],
        "dev-log",
        tmp_path,
        facts=SHOWN,
        say=said.append,
    )
    assert card.style == "c", said
    assert (tmp_path / "dev-log.png").stat().st_size < MAX_BYTES
    note = Card.model_validate_json((tmp_path / "dev-log.json").read_text())
    assert note == card
    assert note.alt.startswith("The Snowlight map at 6:42 AM CT on Dec 10")
    assert any("the dev-log card is style c" in line for line in said)
    old = compose(
        browser,
        taken("national", CALM),
        maps["calm"],
        "waitlist",
        tmp_path,
        fallback=True,
        facts=SHOWN,
        say=said.append,
    )
    assert old.fallback
    assert "pictured on Dec 10, 2026" in old.alt


def test_a_map_of_the_wrong_size_is_refused(browser: Browser, tmp_path: Path) -> None:
    small = tmp_path / "small.png"
    small.write_bytes(png(np.zeros((90, 160, 3), dtype=np.uint8)))
    with pytest.raises(CardError, match="1600 x 900"):
        compose(
            browser, taken("national", CALM), small, "dev-log", tmp_path, facts=SHOWN, say=print
        )


def test_an_older_national_card_drops_the_days_chance() -> None:
    # "Monday" on a dated card would read as the coming Monday.
    old = taken("national", CALM)
    assert "chance" not in c_slots(old, "dev-log", "left", fallback=True)
    assert "chance" in c_slots(old, "dev-log", "left", fallback=False)
    picture = a_facts(old, "dev-log", fallback=True)["picture"]
    assert isinstance(picture, dict)
    assert picture["top_chance"] is None
    assert "forecast" not in b_card(old, "dev-log", "file:///m.png", fallback=True)
    assert "chance" not in alt_text(old, "dev-log", fallback=True)
    # A district card keeps its chance, dated.
    assert c_slots(taken("district", DISTRICT), "dev-log", "right", fallback=True)["chance"] == (
        "77%"
    )


def test_the_library_holds_dated_cards_for_both_styles() -> None:
    images = load(REPO).images
    assert {image.style for image in images} == {"dev_log", "waitlist"}
    for image in images:
        assert image.alt is not None
        assert f"pictured on {image.day:%b} {image.day.day}, {image.day.year}" in image.alt
        assert not re.search(r"\d:\d\d", image.alt), "a library card carries no clock"
        assert image.fresh is None
        assert not image.current
        assert image.path.stat().st_size < MAX_BYTES
        assert struct.unpack(">II", image.path.read_bytes()[16:24]) == (1600, 900)


def test_a_library_card_whose_line_left_the_facts_file_is_refused(tmp_path: Path) -> None:
    social = tmp_path / "social"
    (social / "queue").mkdir(parents=True)
    images = social / "images"
    images.mkdir()
    source = next(
        path
        for path in sorted((REPO / "social" / "images").glob("*dev-log.json"))
        if json.loads(path.read_text(encoding="utf-8")).get("tagline")
    )
    entry = json.loads(source.read_text(encoding="utf-8"))
    (images / source.name).write_bytes(source.read_bytes())
    (images / entry["file"]).write_bytes((source.parent / entry["file"]).read_bytes())
    facts = (REPO / "social" / "facts.md").read_text(encoding="utf-8")
    (social / "facts.md").write_text(facts, encoding="utf-8")
    assert load(tmp_path).images[0].id == entry["id"]
    # The model fact is reworded: the card's line is no longer words of a LIVE fact.
    line = entry["tagline"]
    assert line.lower() in facts.lower()
    moved = re.sub(re.escape(line), "chances worked out by a model", facts, count=1, flags=re.I)
    assert moved != facts
    (social / "facts.md").write_text(moved, encoding="utf-8")
    with pytest.raises(ContentError, match="re-render the library"):
        load(tmp_path)


def test_a_card_line_is_words_of_a_live_fact_or_a_whole_coming_one() -> None:
    facts = parse_facts(
        "- [LIVE] model: Snowlight gives chances from a prediction model trained on real"
        " closing records, not a guess.\n"
        "- [COMING] aim: Every school closing in the US on one map, coming this winter."
        " | terms: one map\n"
    )
    assert still_true("Chances from a prediction model trained on real closing records", facts)
    assert still_true("Every school closing in the US on one map, coming this winter", facts)
    # Part of a COMING fact drops its "coming": a present-tense claim.
    assert not still_true("Every school closing in the US on one map", facts)
    assert not still_true("Chances from an AI trained on everything", facts)


def test_every_library_card_names_its_line_and_none_is_the_bare_national_map() -> None:
    """Every library card is a C card with its headline kept in its JSON (checked against the
    facts file at load), over a region's city lights: never the bare national map."""
    paths = sorted((REPO / "social" / "images").glob("*.json"))
    assert paths
    for path in paths:
        entry = json.loads(path.read_text(encoding="utf-8"))
        assert entry.get("tagline"), path.name
        assert entry["alt"].endswith(f"captioned {entry['tagline']}."), path.name
        assert "national" not in path.name
        assert "faint white specks" in entry["shows"], path.name


# Chances while the site is locked (F): no card, card word or alt text gives a chance.


def test_while_chances_are_testing_the_card_facts_hold_no_chance() -> None:
    calm = without_chances(taken("national", CALM))
    assert calm.seen.chance is None
    for post in ("dev-log", "waitlist"):
        assert not any(
            "chance" in key.lower() for key in c_slots(calm, post, "left", fallback=False)
        )
        picture = a_facts(calm, post, fallback=False)["picture"]
        assert isinstance(picture, dict)
        assert picture["top_chance"] is None
        assert "forecast" not in b_card(calm, post, "file:///m.png", fallback=False)
        assert not mentions_chance(alt_text(calm, post, fallback=False))
    with pytest.raises(CardError, match="district"):
        without_chances(taken("district", DISTRICT))
    told = taken("national", Seen()).model_copy(
        update={"shows": "SYNTHETIC: a district's chance of no school on Tuesday is 74%"}
    )
    with pytest.raises(CardError, match="description"):
        without_chances(told)
    plain = taken("national", Seen())
    assert without_chances(plain) is plain


@pytest.mark.parametrize("candidate", ["c-left", "c-right", "a", "b"])
def test_while_chances_are_testing_no_template_shows_a_chance(
    page: Page, maps: dict[str, Path], candidate: Candidate
) -> None:
    calm = without_chances(taken("national", CALM))
    for post in ("dev-log", "waitlist"):
        _, words = lay(page, candidate, calm, post, maps["calm"], fallback=False)
        assert not mentions_chance(words), (candidate, post, words)
        if candidate == "a" and post == "dev-log":
            assert "A real model, not a guess" in words


def test_compose_while_closings_are_not_live(
    browser: Browser, maps: dict[str, Path], tmp_path: Path
) -> None:
    """SYNTHETIC: a storm's closings picture while the facts file marks closings COMING gives
    no card; a calm one gives a card whose words and alt text say nothing of closings."""
    with pytest.raises(CardError, match="closings"):
        compose(
            browser, taken("closings", STORM), maps["storm"], "dev-log", tmp_path,
            facts=HELD_BACK, say=print,
        )  # fmt: skip
    calm = taken("national", Seen())
    for post in ("dev-log", "waitlist"):
        card = compose(browser, calm, maps["calm"], post, tmp_path, facts=HELD_BACK, say=print)
        assert not mentions_closings(card.alt), card.alt
    spoken = calm.model_copy(update={"shows": "SYNTHETIC: 3 schools are closed in this view"})
    with pytest.raises(CardError, match="speaks of closings"):
        compose(browser, spoken, maps["calm"], "dev-log", tmp_path, facts=HELD_BACK, say=print)


def test_the_a_cards_model_line_is_checked_against_the_runs_facts(
    browser: Browser, maps: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SYNTHETIC: the facts file demotes the model fact; the A card's line is no longer true,
    so A does not fit and the calm card takes another style (A tried first here: C, first
    on every picture, would fit before A is measured)."""
    monkeypatch.setattr(cards_module, "groups", lambda _taken: (("a",), ("c-left",), ("b",)))
    card = compose(
        browser,
        taken("national", Seen()),
        maps["calm"],
        "dev-log",
        tmp_path,
        facts=switches("TESTING", "COMING", model="TESTING"),
        say=print,
    )
    assert card.style != "a"
    assert "its model line is no longer a LIVE fact's words" in card.why
    again = compose(
        browser, taken("national", Seen()), maps["calm"], "dev-log", tmp_path,
        facts=HELD_BACK, say=print,
    )  # fmt: skip
    assert again.style == "a"


def test_compose_while_chances_are_testing(
    browser: Browser, maps: dict[str, Path], tmp_path: Path
) -> None:
    """SYNTHETIC: a 1% nation on a calm map, and a 77% district, with chances TESTING."""
    for post in ("dev-log", "waitlist"):
        card = compose(
            browser,
            taken("national", CALM),
            maps["calm"],
            post,
            tmp_path,
            facts=NO_CHANCES,
            say=print,
        )
        assert not mentions_chance(card.alt), card.alt
    with pytest.raises(CardError, match="district"):
        compose(
            browser, taken("district", DISTRICT), maps["calm"], "dev-log", tmp_path,
            facts=NO_CHANCES, say=print,
        )  # fmt: skip


# -- the C card's headline (the owner's "less text, more map") ---------------------------------


def real_facts() -> Facts:
    return parse_facts((REPO / "social" / "facts.md").read_text(encoding="utf-8"))


def test_every_headline_is_short_and_true_per_the_real_facts_file() -> None:
    facts = real_facts()
    for (post, kind), lines in HEADLINES.items():
        assert post in {"dev-log", "waitlist"}
        assert kind in {"any", "closings", "district", "national", "region"}
        for line in lines:
            assert 2 <= len(line.split()) <= 6, line
            assert still_true(line, facts), f"{line!r} is not words of a LIVE fact"
            assert not mentions_chance(line), line
            assert not re.search(r"\b(now|live|today|tonight)\b", line, re.IGNORECASE), line
            check_words(line, current=False, fallback=True)
            # Plain words a parent reads at a glance: no insider name for a part of Snowlight.
            assert not INSIDER.search(line), line
    posts: tuple[Post, ...] = ("dev-log", "waitlist")
    for post in posts:
        for kind, seen in (("national", Seen()), ("region", REGION), ("closings", STORM)):
            assert headline_for(taken(kind, seen), post, facts) is not None, (post, kind)


def test_a_headline_rotates_by_run_slot_and_speaks_of_closings_only_over_them() -> None:
    """The three runs of a day (13:07, 17:37 and 00:41 UTC) turn to the next headline each,
    so two dev logs of one day never carry the same line in a row."""
    facts = real_facts()
    runs = (
        datetime(2026, 10, 27, 13, 7, tzinfo=UTC),
        datetime(2026, 10, 27, 17, 37, tzinfo=UTC),
        datetime(2026, 10, 28, 0, 41, tzinfo=UTC),
        datetime(2026, 10, 28, 13, 7, tzinfo=UTC),
    )
    lines = [
        headline_for(
            taken("region", REGION).model_copy(update={"taken_at": moment}), "dev-log", facts
        )
        for moment in runs
    ]
    assert set(lines) == set(HEADLINES[("dev-log", "any")])
    assert all(one != other for one, other in itertools.pairwise(lines)), lines
    calm = {headline_for(taken("region", REGION), post, facts) for post in ("dev-log", "waitlist")}
    assert not any(mentions_closings(line or "") for line in calm)
    # A closings headline only while the facts file marks closings LIVE.
    assert headline_for(taken("closings", STORM), "dev-log", HELD_BACK) is None


def test_a_headline_that_left_the_facts_file_is_never_laid() -> None:
    """SYNTHETIC facts without the model's short line: no headline, and the card keeps its
    plain label."""
    plain = parse_facts("- [LIVE] model: SYNTHETIC model. | terms: model\n")
    assert headline_for(taken("region", REGION), "dev-log", plain) is None


def test_the_stamp_lays_a_headline_small_and_inside_the_margin(
    page: Page, maps: dict[str, Path]
) -> None:
    calm = taken("region", REGION)
    _, words = lay(
        page, "c-left", calm, "dev-log", maps["calm"], fallback=False,
        headline="A real model, not a guess",
    )  # fmt: skip
    assert "A real model, not a guess" in words
    assert "Dev log" not in words
    _, storm = lay(
        page, "c-right", taken("closings", STORM), "dev-log", maps["storm"], fallback=False,
        headline="Real school closings and delays",
    )  # fmt: skip
    assert "in this view" in storm
    with pytest.raises(CardError, match="refused"):
        lay(
            page, "c-left", calm, "dev-log", maps["calm"], fallback=False,
            headline="One two three four five six seven",
        )  # fmt: skip
    alt = alt_text(calm, "dev-log", fallback=False, headline="A real model, not a guess")
    assert alt.endswith("captioned A real model, not a guess.")


def test_the_waitlist_stamp_over_lit_schools_carries_their_counts(
    page: Page, maps: dict[str, Path]
) -> None:
    """The waitlist card's badge is the link; the lit schools in view still show, counted
    from the picture's facts and labeled "in this view", with the country's total named."""
    _, words = lay(
        page, "c-right", taken("closings", STORM), "waitlist", maps["storm"], fallback=False,
        headline="The Snowlight waitlist is open",
    )  # fmt: skip
    assert "snowlightmap.com" in words
    assert "1,843" in words
    assert "schools closed in this view" in words
    assert "5,021" in words
    assert "lit up across the US" in words


def test_a_closings_headline_says_only_the_statuses_in_view() -> None:
    facts = real_facts()
    only_closed = STORM.model_copy(
        update={"in_view": Counts(closed=2, delayed=0, remote=0, early_dismissal=0)}
    )
    lines = {
        headline_for(
            taken("closings", only_closed).model_copy(
                update={"taken_at": datetime(2026, 12, d, 14, tzinfo=UTC)}
            ),
            "dev-log",
            facts,
        )
        for d in range(1, 8)
    }
    assert "Real school closings and delays" not in lines
    assert "Real school closings" in lines
    only_delayed = STORM.model_copy(
        update={"in_view": Counts(closed=0, delayed=4, remote=0, early_dismissal=0)}
    )
    assert headline_for(taken("closings", only_delayed), "dev-log", facts) == (
        "Like city lights seen from space"
    )


FEW_PRIVATE = Seen(
    in_view=Counts(closed=2, delayed=0, remote=0, early_dismissal=0),
    place="New Mexico",
    lit=2,
    closings_at=datetime(2026, 12, 10, 12, 40, tzinfo=UTC),
    closings_read=True,
)
"""Two lit private schools (their ids name no state): the view's own place, by its public
schools' share (SYNTHETIC)."""


def test_lit_private_schools_name_the_view_s_place_on_the_stamp_and_in_the_alt(
    page: Page, maps: dict[str, Path]
) -> None:
    few = taken("closings", FEW_PRIVATE)
    assert c_slots(few, "dev-log", "left", fallback=False)["over"] == "New Mexico"
    assert a_facts(few, "dev-log", fallback=False)["picture"]["over"] == "New Mexico"  # type: ignore[index]
    _, words = lay(
        page, "c-left", few, "dev-log", maps["storm"], fallback=False,
        headline="Real school closings",
    )  # fmt: skip
    assert "Over New Mexico" in words
    assert "Mostly" not in words
    alt = alt_text(few, "dev-log", fallback=False, headline="Real school closings")
    assert ", in a view over New Mexico: 2 schools closed in this view" in alt
    # A stamp with states says "Mostly", never "Over" as well.
    storm = c_slots(taken("closings", STORM), "dev-log", "left", fallback=False)
    assert "over" not in storm

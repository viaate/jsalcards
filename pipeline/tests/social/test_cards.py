"""The branded cards (snowlight.social.cards): the style choice from SYNTHETIC glow masks,
every truth guard with adversarial facts, the alt text, the fallback card, and (in the
pre-installed headless Chromium, skipped where none is installed) the three templates laid
over SYNTHETIC map pictures: 1600 x 900, under 5 MB, every word inside the 64 px margin."""

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

from snowlight.social.cards import (
    FIT_SHARE,
    HERE,
    MAX_BYTES,
    Candidate,
    Card,
    CardError,
    Measure,
    a_facts,
    alt_text,
    b_card,
    c_slots,
    check_words,
    compose,
    cover,
    glow_mask,
    groups,
    lay,
    pick,
)
from snowlight.social.content import ContentError, _still_true, load
from snowlight.social.picture import Box, Chance, Counts, Seen, Taken
from snowlight.social.rules import parse_facts

REPO = Path(__file__).resolve().parents[3]
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


def test_a_calm_map_takes_the_lower_third_and_a_glow_there_moves_it() -> None:
    assert choose_from(canvas(), "national")[0] == "a"
    picture = canvas()
    picture[450:700, 100:1000] = BLUE  # under A's lower third, clear of C's stamp and row
    chosen, why = choose_from(picture, "national")
    assert chosen == "c-left"
    assert why.startswith("c-left is the first style that fits (a covers")


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


def test_a_closings_stamp_never_names_a_place_it_does_not_know() -> None:
    private_only = Seen(
        in_view=Counts(closed=3, delayed=0, remote=0, early_dismissal=0),
        states=(),
        lit=3,
        closings_read=True,
    )
    with pytest.raises(CardError, match="states"):
        c_slots(taken("closings", private_only), "dev-log", "left", fallback=False)


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


def test_the_preferred_order_follows_the_owner() -> None:
    assert groups(taken("closings", STORM)) == (("c-left", "c-right"), ("a",), ("b",))
    assert groups(taken("district", DISTRICT)) == (("c-right",), ("a",), ("b",))
    right = DISTRICT.model_copy(update={"focus": Box(x0=900, y0=200, x1=1300, y1=700)})
    assert groups(taken("district", right))[0] == ("c-left",)
    assert groups(taken("national", CALM)) == (("a",), ("c-left",), ("b",))
    assert groups(taken("region", REGION)) == (("a",), ("c-left",), ("b",))


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
        "lit up for weather, mostly in Michigan and Ohio: 1,843 schools closed, 1,338 delayed, "
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
    assert lines == ["Chances from a prediction model trained on real closing records",
                     "Building Snowlight"]  # fmt: skip
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
        browser, taken("closings", STORM), maps["storm"], "dev-log", tmp_path, say=said.append
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
        say=said.append,
    )
    assert old.fallback
    assert "pictured on Dec 10, 2026" in old.alt


def test_a_map_of_the_wrong_size_is_refused(browser: Browser, tmp_path: Path) -> None:
    small = tmp_path / "small.png"
    small.write_bytes(png(np.zeros((90, 160, 3), dtype=np.uint8)))
    with pytest.raises(CardError, match="1600 x 900"):
        compose(browser, taken("national", CALM), small, "dev-log", tmp_path, say=print)


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
        for path in sorted((REPO / "social" / "images").glob("*national*dev-log.json"))
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
    assert _still_true("Chances from a prediction model trained on real closing records", facts)
    assert _still_true("Every school closing in the US on one map, coming this winter", facts)
    # Part of a COMING fact drops its "coming": a present-tense claim.
    assert not _still_true("Every school closing in the US on one map", facts)
    assert not _still_true("Chances from an AI trained on everything", facts)


def test_every_library_card_with_a_line_names_it() -> None:
    for path in sorted((REPO / "social" / "images").glob("*national*.json")):
        assert json.loads(path.read_text(encoding="utf-8")).get("tagline"), path.name

"""The branded card each post's picture goes out as (``cards/``): the map alone, as the Render
step took it, under Snowlight's own words, laid out by one of three templates the owner saw:

* **C, stamp** (``cards/c``): a small stamp in a top corner (one short bold headline from
  the card library, :data:`HEADLINES`, then the place, time and one badge, small), the other
  statuses in a row along the bottom, the logo bottom right. The owner's pick: the first
  style tried for every picture, so the map fills the card.
* **A, broadcast** (``cards/a``): a lower third, bottom left, with a short model line. Only
  where C does not fit.
* **B, framed** (``cards/b``): the map whole in an inset frame, the words in a black column
  beside it, never over it. Only where neither of the others fits.

The style is chosen by code, never at random (:func:`pick`): the preferred order is C, A, B
for every picture (both of C's corners for a closings one), and a style fits only when
its words, stamp and logo darken no lit school's centre (each school in view is measured
where the picture puts it, :attr:`snowlight.social.picture.Seen.spots`) and at most
:data:`FIT_SHARE` of the lit-school pixels of the map, for the halos' edges (:func:`cover`;
the owner's objection to A was its text over lit schools). B covers no pixel of the map by
construction (checked on its layout). When no style fits, no fresh card is made (the post
goes with the library's dated card). The choice and its measures are logged. The A card's
model line is laid only while it is still words of a LIVE fact of the run's facts file
(:func:`snowlight.social.rules.still_true`); otherwise A does not fit.

Every word, number, place and time on a card comes from the picture's facts
(:class:`snowlight.social.picture.Taken`), filled by code; none comes from Haiku. In-view
counts are labeled "in this view" and the country's total "across the US"; nothing is said
about closings from a practice-mode 404, nor at all while the facts file marks closings not
LIVE (:func:`without_closings`); no district is named; a fallback card shows its own date,
never a clock, "now" or "live". The alt text is built here from the same facts
(:func:`alt_text`). A card is 1600 x 900, under 5 MB, every word inside a 64 px margin.
"""

import base64
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # the browser is needed only to make a card, not to read one
    from playwright.sync_api import Browser, Page

from snowlight.social.picture import (
    HEIGHT,
    SHOWN_ZONE,
    STATUS_WORDS,
    WIDTH,
    Counts,
    Taken,
    clock,
)
from snowlight.social.rules import (
    Facts,
    chances_shown,
    closings_shown,
    mentions_chance,
    mentions_closings,
    still_true,
)

HERE: Final = Path(__file__).parent / "cards"


def _a_tagline() -> str:
    found = re.search(
        r"const TAGLINE = '([^']+)';", (HERE / "a" / "card.html").read_text(encoding="utf-8")
    )
    if found is None:
        raise RuntimeError("cards/a/card.html names no TAGLINE")
    return found.group(1)


A_TAGLINE: Final = _a_tagline()
"""The A card's model line, as its template lays it."""
FIT_SHARE: Final = 0.03
"""The most of the map's lit-school pixels a style's words may darken and still fit (halo
edges: no lit school's centre may be darkened at all, :data:`SPOT`)."""
SPOT: Final = 1
"""How far around a lit school's centre (in pixels, each way) nothing may be darkened."""
MARGIN: Final = 64
"""Every word and the logo stay this far inside the card's edges."""
MAX_BYTES: Final = 5 * 1024 * 1024
TIMEOUT_MS: Final = 30_000
ALT_MAX: Final = 1000
"""X's longest alt text (docs.x.com, POST /2/media/metadata)."""
CAPTION: Final[Mapping[str, str]] = {"dev-log": "Dev log", "waitlist": "Join the waitlist"}
HEADLINES: Final[Mapping[tuple[str, str], tuple[str, ...]]] = {
    ("waitlist", "any"): ("The Snowlight waitlist is open",),
    ("dev-log", "closings"): (
        "Real school closings and delays",
        "Real school closings",
        "Like city lights seen from space",
    ),
    ("dev-log", "any"): (
        "A real model, not a guess",
        "Real closing records, not a guess",
        "Closings reader runs 24/7",
    ),
}
"""The card library's headlines (2 to 6 words) by post and picture kind ("any": every other
kind), each words of a LIVE fact's text as the facts file has them (:func:`headline_for`
checks each against the run's facts file and skips one that is no longer true). A card's
headline says no number, time, place or count of the picture: those are its own slots."""
HEADLINE_WORDS: Final = (2, 6)
SPOKEN: Final = (("<1%", "under 1%"), (">99%", "over 99%"))

type Post = Literal["dev-log", "waitlist"]
type Candidate = Literal["c-left", "c-right", "a", "b"]
POSTS: Final[tuple[Post, ...]] = ("dev-log", "waitlist")

BANNED: Final = re.compile("[\u2012-\u2015!]")
"""Figure, en and em dashes, the horizontal bar, and "!" (emoji: :func:`_pictograph`)."""
NOT_CURRENT: Final = re.compile(r"\b(now|live|today|tonight|this morning|currently)\b", re.I)
CLOCK: Final = re.compile(r"\b(1[0-2]|[1-9]):[0-5]\d\s?(AM|PM)\b")
NEVER: Final = re.compile(r"\b0 schools\b|\bno closings\b", re.I)


class CardError(RuntimeError):
    """A card could not be made true and whole (safe for the log)."""


@dataclass(frozen=True, slots=True)
class Measure:
    """How much of the map's glow a laid-out style darkens."""

    glow: int
    covered: int
    refused: str | None = None
    schools: int = 0
    """How many lit schools' centres the layout darkens (none may be)."""
    """Why the layout could not be used at all (the template refused the facts, a word left
    the margin, or B would crop the map)."""

    @property
    def share(self) -> float:
        return self.covered / self.glow if self.glow else 0.0

    @property
    def fits(self) -> bool:
        return self.refused is None and self.schools == 0 and self.share <= FIT_SHARE

    def __str__(self) -> str:
        if self.refused is not None:
            return f"not usable: {self.refused}"
        schools = f", over {self.schools} lit schools" if self.schools else ""
        return f"covers {self.covered} of {self.glow} lit pixels ({self.share:.1%}){schools}"


class Card(BaseModel):
    """``<post>.json`` beside ``<post>.png``: the card's style, why, and its alt text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    post: Post
    style: Literal["a", "b", "c"]
    why: str = Field(max_length=600)
    alt: str = Field(min_length=20, max_length=ALT_MAX)
    file: str = Field(pattern=r"^(dev-log|waitlist)\.png$")
    fallback: bool


def groups(taken: Taken) -> tuple[tuple[Candidate, ...], ...]:
    """The styles to try, in the owner's order of preference, each with its layouts."""
    if taken.kind == "district":
        focus = taken.seen.focus
        # The stamp takes the corner away from the district.
        away: Candidate = (
            "c-right" if focus is None or (focus.x0 + focus.x1) / 2 < WIDTH / 2 else "c-left"
        )
        return ((away,), ("a",), ("b",))
    if taken.kind == "closings":
        return (("c-left", "c-right"), ("a",), ("b",))
    return (("c-left",), ("a",), ("b",))


def headline_for(taken: Taken, post: Post, facts: Facts) -> str | None:
    """The C card's headline: one of :data:`HEADLINES` for the post and picture kind, in turn
    by the picture's day (so a day's cards vary), among those still words of a LIVE fact of
    ``facts`` (:func:`snowlight.social.rules.still_true`), with no word of closings unless
    the facts file marks them LIVE and the picture is of them; ``None`` when none is."""
    lines = HEADLINES.get((post, taken.kind)) or HEADLINES[(post, "any")]
    counts = taken.seen.in_view
    fitting = [
        line
        for line in lines
        if still_true(line, facts)
        and (taken.kind != "closings" or _fits_counts(line, counts))
        and HEADLINE_WORDS[0] <= len(line.split()) <= HEADLINE_WORDS[1]
        and (not mentions_closings(line) or (closings_shown(facts) and taken.kind == "closings"))
        and not mentions_chance(line)
    ]
    if not fitting:
        return None
    return fitting[day_of(taken).toordinal() % len(fitting)]


def _fits_counts(line: str, counts: Counts | None) -> bool:
    """Whether a headline's status words are all in view: "closings" only over closed
    schools and "delays" only over delayed ones (a card never reads as more than it shows)."""
    lowered = line.lower()
    if "closing" in lowered and (counts is None or counts.closed == 0):
        return False
    return "delay" not in lowered or (counts is not None and counts.delayed > 0)


def pick(
    order: Sequence[Sequence[Candidate]], measure: Callable[[Candidate], Measure]
) -> tuple[Candidate, str]:
    """The first style in ``order`` with a layout that fits (the layout covering least, the
    earlier one on a tie), measuring only what it must, and the reason, for the log.

    Raises:
        CardError: no layout fits: the post then goes with the library's dated card, never
            with words over lit schools.
    """
    tried: list[tuple[Candidate, Measure]] = []
    for group in order:
        measured = [(candidate, measure(candidate)) for candidate in group]
        tried.extend(measured)
        fitting = [pair for pair in measured if pair[1].fits]
        if fitting:
            best = min(fitting, key=lambda pair: pair[1].covered)
            notes = "; ".join(f"{name} {result}" for name, result in tried)
            return best[0], f"{best[0]} is the first style that fits ({notes})"
    notes = "; ".join(f"{name} {result}" for name, result in tried)
    raise CardError(f"no style fits without covering lit schools ({notes})"[:600])


def glow_mask(rgb: npt.NDArray[np.uint8]) -> npt.NDArray[np.bool_]:
    """The lit-school pixels of a map picture: bright and saturated (the glow's blue, amber,
    violet and green; the dark land, gray lines, labels and white specks are not)."""
    channels = rgb.astype(np.int16)
    high = channels.max(axis=2)
    low = channels.min(axis=2)
    mask: npt.NDArray[np.bool_] = (high > 90) & (high - low > 60)  # noqa: PLR2004
    return mask


def _luminance(rgb: npt.NDArray[np.uint8]) -> npt.NDArray[np.float64]:
    values = rgb.astype(np.float64)
    lum: npt.NDArray[np.float64] = 0.2126 * values[..., 0] + 0.7152 * values[..., 1]
    return lum + 0.0722 * values[..., 2]


def cover(
    map_rgb: npt.NDArray[np.uint8],
    card_rgb: npt.NDArray[np.uint8],
    spots: Sequence[tuple[int, int]] = (),
) -> Measure:
    """The lit-school pixels of the map the card darkens below half their brightness (its
    words, badges, stamps, halos and scrims), with the map at the same place in both, and
    how many of the lit schools at ``spots`` have a darkened pixel within :data:`SPOT` of
    their centre."""
    mask = glow_mask(map_rgb)
    darker = _luminance(card_rgb) < 0.5 * _luminance(map_rgb)
    height, width = darker.shape
    schools = 0
    for x, y in spots:
        if not (0 <= x < width and 0 <= y < height):
            continue
        window = darker[max(0, y - SPOT) : y + SPOT + 1, max(0, x - SPOT) : x + SPOT + 1]
        if window.any():
            schools += 1
    return Measure(glow=int(mask.sum()), covered=int((mask & darker).sum()), schools=schools)


def _month_day(moment: datetime) -> str:
    local = moment.astimezone(SHOWN_ZONE)
    return f"{local:%b} {local.day}"


def _long_date(moment: datetime) -> str:
    local = moment.astimezone(SHOWN_ZONE)
    return f"{local:%b} {local.day}, {local.year}"


def _spoken(text: str) -> str:
    for short, words in SPOKEN:
        if text == short:
            return words
    return text


def _and(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _counts_words(taken: Taken) -> str:
    counts = taken.seen.in_view
    if counts is None:
        raise CardError("a closings picture without its counts")
    values = counts.as_list()
    parts = [f"{values[i]:,} {STATUS_WORDS[i]}" for i in range(4) if values[i]]
    first = values[next(i for i in range(4) if values[i])]
    parts[0] = parts[0].replace(" ", f" {'school' if first == 1 else 'schools'} ", 1)
    return _and(parts)


def alt_text(taken: Taken, post: Post, *, fallback: bool, headline: str | None = None) -> str:
    """One plain description of the card for X's alt text, from the picture's facts only,
    captioned with the card's headline when it has one (else the post's caption)."""
    when = (
        f"pictured on {_long_date(taken.taken_at)}"
        if fallback
        else f"at {clock(taken.taken_at)} on {_month_day(taken.taken_at)}"
    )
    seen = taken.seen
    chance = seen.chance
    if taken.kind == "closings":
        where = f", mostly in {_and(seen.states)}" if seen.states else ""
        text = (
            f"The Snowlight map {when}, zoomed to the area with the most schools lit up for "
            f"weather{where}: {_counts_words(taken)} in this view"
        )
        in_view = seen.in_view.total if seen.in_view is not None else 0
        if seen.lit > in_view:
            text += f", and {seen.lit:,} lit up across the US"
        if not taken.current and not fallback and seen.closings_at is not None:
            text += f", with the closings last updated at {clock(seen.closings_at)}"
    elif taken.kind == "district":
        if chance is None:
            raise CardError("a district picture without its chance")
        where = f" in {seen.state}" if seen.state else ""
        text = (
            f"The Snowlight map {when}, zoomed to the schools of a public school district"
            f"{where}, whose chance of no school {chance.day:%A} is {_spoken(chance.text)}, "
            "the highest of any district"
        )
    elif taken.kind == "region":
        text = (
            f"The dark Snowlight map over {seen.place}, {when}, schools drawn as faint white specks"
        )
    else:
        text = f"The dark national Snowlight map, {when}, with state lines and city names"
        if chance is not None and post == "dev-log" and not fallback:
            text += (
                f", and the chance of no school {chance.day:%A}: at most 1% in every district"
                if chance.at_most
                else f", and the highest chance of no school {chance.day:%A} in any district: "
                f"{_spoken(chance.text)}"
            )
    text += f", captioned {headline or CAPTION[post]}."
    check_words(text, current=taken.current, fallback=fallback)
    if len(text) > ALT_MAX:
        raise CardError("the alt text is too long")
    return text


def check_words(words: str, *, current: bool, fallback: bool) -> None:
    """The card's own words and its alt text may say nothing false or stale.

    Raises:
        CardError: an emoji, a dash or "!", "0 schools" or "No closings", or a fallback
            (or not current) card that says now, live, today or a clock time.
    """
    if BANNED.search(words) or any(_pictograph(char) for char in words):
        raise CardError("a card has no emoji, en or em dash and no exclamation mark")
    if NEVER.search(words):
        raise CardError("a card never says 0 schools or no closings")
    if (fallback or not current) and NOT_CURRENT.search(words):
        raise CardError("an older or stale card may not say now, live, today or tonight")
    if fallback and CLOCK.search(words):
        raise CardError("a fallback card carries no clock")


def _pictograph(char: str) -> bool:
    code = ord(char)
    return 0x1F000 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF  # noqa: PLR2004


def _dated_chance(taken: Taken, *, fallback: bool) -> bool:
    """Whether a card shows the chance: always on a district picture (it is the picture's
    point, and a fallback card dates it); on the national one only when fresh (an older
    card's "Monday" would read as the coming one)."""
    return taken.kind == "district" or (taken.kind == "national" and not fallback)


def c_slots(
    taken: Taken, post: Post, anchor: str, *, fallback: bool, headline: str | None = None
) -> dict[str, object]:
    """Template C's slots (``cards/c/card.html``), filled by code from the facts, with the
    card library's ``headline`` (:func:`headline_for`) when there is one."""
    seen = taken.seen
    slots: dict[str, object] = {
        "kind": post,
        "view": taken.kind,
        # The template's "current" speaks of the closings a card shows: the other views show
        # none, so their clock is the picture's own (and the card says nothing of closings).
        "current": taken.current or taken.kind != "closings",
        "anchor": anchor,
        "date": _long_date(taken.taken_at) if fallback else _month_day(taken.taken_at),
        "isFallback": fallback,
    }
    if headline is not None:
        slots["headline"] = headline
    if not fallback:
        slots["time"] = clock(taken.taken_at)
    if taken.kind == "closings":
        # No state known (the lit schools in view are all private, their ids name none): the
        # stamp names no place rather than a false one.
        slots["states"] = list(seen.states)
        if seen.in_view is not None:
            slots["counts"] = seen.in_view.model_dump()
        slots["total"] = seen.lit
        if not taken.current and seen.closings_at is not None and not fallback:
            slots["updatedAt"] = {
                "time": clock(seen.closings_at),
                "date": _month_day(seen.closings_at),
            }
    elif taken.kind == "district":
        slots["place"] = f"A district in {seen.state}" if seen.state else "A school district"
        if seen.focus is not None:
            slots["focus"] = seen.focus.model_dump()
    elif taken.kind == "region":
        slots["place"] = seen.place
    else:
        slots["place"] = "United States"
    chance = seen.chance
    if chance is not None and post == "dev-log" and _dated_chance(taken, fallback=fallback):
        slots["chance"] = chance.text
        slots["chanceDay"] = f"{chance.day:%a}"
        slots["chanceScope"] = chance.scope
    return slots


def a_facts(taken: Taken, post: Post, *, fallback: bool) -> dict[str, object]:
    """Template A's facts (``cards/a/card.html``): times as ISO with their zone, formatted in
    the template in Central time."""
    seen = taken.seen
    picture: dict[str, object] = {
        "kind": taken.kind,
        "taken_at": taken.taken_at.isoformat(),
        "current": taken.current,
    }
    frame: dict[str, object] | None = None
    if taken.kind == "closings":
        picture["in_view"] = seen.in_view.model_dump() if seen.in_view is not None else {}
        picture["states"] = list(seen.states)
        picture["lit"] = seen.lit
        if seen.closings_at is not None:
            picture["closings_generated_at"] = seen.closings_at.isoformat()
    elif taken.kind == "district":
        chance = seen.chance
        if chance is None:
            raise CardError("a district picture without its chance")
        picture.update(state=seen.state, chance_text=chance.text, day=chance.day.isoformat())
        if seen.focus is not None:
            focus = seen.focus
            free_x = max(focus.x1 + 80, WIDTH / 2 + 60)
            frame = {
                "free": {"x0": free_x, "y0": MARGIN, "x1": WIDTH - MARGIN, "y1": HEIGHT - MARGIN},
                "subject": focus.model_dump(),
            }
    elif taken.kind == "region":
        picture["place"] = seen.place
    else:
        chance = seen.chance
        picture["top_chance"] = (
            None
            if chance is None or fallback
            else {
                "text": chance.text,
                "day": chance.day.isoformat(),
                "districts": chance.districts,
            }
        )
    facts: dict[str, object] = {"post": post, "picture": picture, "isFallback": fallback}
    if frame is not None:
        facts["frame"] = frame
    return facts


def b_card(taken: Taken, post: Post, map_url: str, *, fallback: bool) -> dict[str, object]:
    """Template B's card (``cards/b/card.html``): the map whole in the frame, never cropped,
    so the counts "in this view" stay true."""
    seen = taken.seen
    card: dict[str, object] = {
        "scenario": "post",
        "truth": "REAL",
        "kind": post,
        "isFallback": fallback,
        "date": _long_date(taken.taken_at),
        "bg": {"src": map_url, "path": "map", "focus": [0, 0, WIDTH, HEIGHT], "pad": 0},
    }
    if not fallback:
        card["time"] = clock(taken.taken_at)
    chance = seen.chance
    if chance is not None and post == "dev-log" and not fallback:
        card["forecast"] = {
            "districts": chance.districts,
            "top": chance.text,
            "atMost": chance.at_most,
            "day": chance.day.isoformat(),
        }
    return card


PIXELS: Final = """async (url) => {
  const img = new Image();
  img.src = url;
  await img.decode();
  const canvas = document.createElement('canvas');
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const g = canvas.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0);
  const data = g.getImageData(0, 0, canvas.width, canvas.height).data;
  let out = '';
  for (let i = 0; i < data.length; i += 0x8000) {
    out += String.fromCharCode.apply(null, data.subarray(i, i + 0x8000));
  }
  return [canvas.width, canvas.height, btoa(out)];
}"""
"""Decodes a PNG in the browser: its width, height and RGBA bytes."""

INK: Final = """() => {
  const out = [];
  const visible = (el) => {
    if (el.closest('[hidden], script, style, template')) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && Number(cs.opacity) > 0;
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.textContent.trim() || !visible(n.parentElement)) continue;
    const range = document.createRange();
    range.selectNodeContents(n);
    for (const r of range.getClientRects()) {
      if (r.width > 0 && r.height > 0) {
        const what = n.textContent.trim().slice(0, 40);
        out.push({ what, x0: r.left, y0: r.top, x1: r.right, y1: r.bottom });
      }
    }
  }
  for (const svg of document.querySelectorAll('svg')) {
    if (!visible(svg)) continue;
    const r = svg.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) {
      out.push({ what: 'logo', x0: r.left, y0: r.top, x1: r.right, y1: r.bottom });
    }
  }
  return { boxes: out, words: document.body.innerText };
}"""
"""Every visible word's and logo's box, and the card's words."""

FRAME: Final = """() => {
  const copy = document.getElementById('copy').getBoundingClientRect();
  const frame = document.getElementById('frame').getBoundingClientRect();
  const img = document.getElementById('map').getBoundingClientRect();
  return { copyRight: copy.right, frameLeft: frame.left,
    whole: img.left >= frame.left - 0.5 && img.right <= frame.right + 0.5
      && img.top >= frame.top - 0.5 && img.bottom <= frame.bottom + 0.5 };
}"""


def rgb_of(page: "Page", png: bytes) -> npt.NDArray[np.uint8]:
    """A PNG's pixels (height, width, 3), decoded by the browser."""
    url = "data:image/png;base64," + base64.b64encode(png).decode()
    width, height, data = page.evaluate(PIXELS, url)
    raw = np.frombuffer(base64.b64decode(data), dtype=np.uint8)
    rgba: npt.NDArray[np.uint8] = raw.reshape(int(height), int(width), 4)
    return rgba[..., :3]


@dataclass(slots=True)
class Laid:
    """One candidate laid out: its screenshot, words and measure."""

    png: bytes
    words: str
    measure: Measure


def _template(style: str) -> str:
    return (HERE / style / "card.html").as_uri()


def lay(  # noqa: PLR0913 - one layout's parts
    page: "Page",
    candidate: Candidate,
    taken: Taken,
    post: Post,
    map_png: Path,
    *,
    fallback: bool,
    headline: str | None = None,
) -> tuple[bytes, str]:
    """Lay out one candidate on ``page`` and screenshot it; its PNG and its words.

    Raises:
        CardError: the template refused the facts, or a word left the margin.
    """
    style = candidate[0]
    map_url = map_png.resolve().as_uri()
    page.goto(_template(style), wait_until="load", timeout=TIMEOUT_MS)
    try:
        if style == "c":
            anchor = candidate.removeprefix("c-")
            slots = c_slots(taken, post, anchor, fallback=fallback, headline=headline)
            page.evaluate("([s, u]) => window.fill(s, u)", [slots, map_url])
        elif style == "a":
            page.evaluate(
                "([f, u]) => window.renderCard(f, u)",
                [a_facts(taken, post, fallback=fallback), map_url],
            )
        else:
            card = b_card(taken, post, map_url, fallback=fallback)
            result = page.evaluate(
                "(card) => { window.__CARD__ = card; return window.__render(); }", card
            )
            if not isinstance(result, dict) or result.get("overflow"):
                raise CardError("template b: the words do not fit its column")
    except Exception as error:
        if isinstance(error, CardError):
            raise
        raise CardError(f"template {style} refused the facts: {_first_line(error)}") from None
    page.evaluate("() => document.fonts.ready.then(() => true)")
    ink = page.evaluate(INK)
    words = str(ink["words"])
    for box in ink["boxes"]:
        if (
            box["x0"] < MARGIN - 0.5
            or box["y0"] < MARGIN - 0.5
            or box["x1"] > WIDTH - MARGIN + 0.5
            or box["y1"] > HEIGHT - MARGIN + 0.5
        ):
            raise CardError(
                f"template {style}: '{box['what']}' leaves the 64 px margin"
                f" ({box['x0']:.0f}, {box['y0']:.0f}, {box['x1']:.0f}, {box['y1']:.0f})"
            )
    check_words(words, current=taken.current, fallback=fallback)
    return page.screenshot(type="png", full_page=False), words


def _first_line(error: Exception) -> str:
    text = str(error).strip()
    line = text.splitlines()[0] if text else type(error).__name__
    return line.removeprefix("Error: ")[:240]


def compose(  # noqa: PLR0913 - the card's parts
    browser: "Browser",
    taken: Taken,
    map_png: Path,
    post: Post,
    out: Path,
    *,
    fallback: bool = False,
    facts: Facts,
    say: Callable[[str], None],
) -> Card:
    """The card for ``post`` over the map picture, written to ``out/<post>.png`` and
    ``out/<post>.json``; the style chosen by :func:`pick`. While ``facts`` marks chances not
    LIVE (:func:`snowlight.social.rules.chances_shown`) the card, its alt text and the
    picture's description give no chance (:func:`without_chances`), and while it marks
    closings not LIVE they say nothing of closings (:func:`without_closings`).

    Raises:
        CardError: no style gave a true, whole card, or a chance or closings would show
            while the facts file holds them back.
    """
    chances = chances_shown(facts)
    closings = closings_shown(facts)
    if not chances:
        taken = without_chances(taken)
    if not closings:
        without_closings(taken)
    context = browser.new_context(
        viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1, color_scheme="dark"
    )
    # The card page is local files only (the template, its fonts, the map picture): nothing
    # it asks of the network is fetched.
    context.route(re.compile(r"^(?:https?|wss?|ftp):", re.IGNORECASE), lambda route: route.abort())
    try:
        page = context.new_page()
        scratch = context.new_page()
        map_rgb = rgb_of(scratch, map_png.read_bytes())
        if map_rgb.shape[:2] != (HEIGHT, WIDTH):
            raise CardError("the map picture is not 1600 x 900")
        laid: dict[Candidate, Laid] = {}
        headline = headline_for(taken, post, facts)

        def measure(candidate: Candidate) -> Measure:
            try:
                png, words = lay(
                    page, candidate, taken, post, map_png, fallback=fallback, headline=headline
                )
            except CardError as error:
                return Measure(glow=0, covered=0, refused=str(error))
            if candidate == "a" and A_TAGLINE in words and not still_true(A_TAGLINE, facts):
                return Measure(
                    glow=0, covered=0, refused="its model line is no longer a LIVE fact's words"
                )
            if candidate == "b":
                frame = page.evaluate(FRAME)
                if not frame["whole"] or frame["copyRight"] > frame["frameLeft"]:
                    return Measure(glow=0, covered=0, refused="b would crop or cover the map")
                result = Measure(glow=int(glow_mask(map_rgb).sum()), covered=0)
            else:
                result = cover(map_rgb, rgb_of(scratch, png), taken.seen.spots)
            laid[candidate] = Laid(png, words, result)
            return result

        chosen, why = pick(groups(taken), measure)
        png = laid[chosen].png
        if len(png) > MAX_BYTES:
            raise CardError("the card is over 5 MB")
        alt = alt_text(
            taken, post, fallback=fallback, headline=headline if chosen.startswith("c") else None
        )
        if not chances and (mentions_chance(laid[chosen].words) or mentions_chance(alt)):
            raise CardError("the card would give a chance while chances are TESTING")
        if not closings and (mentions_closings(laid[chosen].words) or mentions_closings(alt)):
            raise CardError("the card would show closings while closings are not LIVE")
    finally:
        context.close()
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{post}.png").write_bytes(png)
    card = Card(
        post=post,
        style=chosen[0],  # type: ignore[arg-type]
        why=why[:600],
        alt=alt,
        file=f"{post}.png",
        fallback=fallback,
    )
    (out / f"{post}.json").write_text(card.model_dump_json(indent=2) + "\n", encoding="utf-8")
    say(f"social: the {post} card is style {card.style}: {why}")
    return card


def without_chances(taken: Taken) -> Taken:
    """The picture with no chance in it, for a card while chances are TESTING (the site is
    locked): its chance dropped from the facts. A district's chance picture, or a description
    that gives a chance, cannot be made into one.

    Raises:
        CardError: the picture is a district's chance, or its description gives a chance.
    """
    if taken.kind == "district":
        raise CardError("a district's chance picture while chances are TESTING")
    if mentions_chance(taken.shows):
        raise CardError("the picture's description gives a chance while chances are TESTING")
    if taken.seen.chance is None:
        return taken
    return taken.model_copy(update={"seen": taken.seen.model_copy(update={"chance": None})})


def without_closings(taken: Taken) -> None:
    """Check that a picture shows and says nothing of closings, for a card while the facts
    file marks closings not LIVE (the reader's finds are checked before anything goes
    public).

    Raises:
        CardError: the picture is a closings view, counts lit schools, read a closings file,
            or its description speaks of closings.
    """
    seen = taken.seen
    if (
        taken.kind == "closings"
        or taken.lit
        or seen.lit
        or seen.in_view is not None
        or seen.states
        or seen.spots
        or seen.closings_read
        or seen.closings_at is not None
    ):
        raise CardError("a picture of closings while closings are not LIVE")
    if mentions_closings(taken.shows):
        raise CardError("the picture's description speaks of closings while they are not LIVE")


def load_card(folder: Path, post: Post) -> tuple[Card, Path] | None:
    """A card the Render step made for ``post``, or ``None`` when it made none."""
    note = folder / f"{post}.json"
    if not note.is_file():
        return None
    card = Card.model_validate(json.loads(note.read_text(encoding="utf-8")))
    return card, folder / card.file


def day_of(taken: Taken) -> date:
    """The picture's day in the shown zone (a fallback card's date)."""
    return taken.taken_at.astimezone(SHOWN_ZONE).date()

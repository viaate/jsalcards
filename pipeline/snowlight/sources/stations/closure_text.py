"""The closure-text check: archived captures that show a closing their adapter did not read.

A source is settled by the coverage gate (:mod:`snowlight.sources.stations.gate`)
on what its adapter read from its archived captures: a list read empty in every
capture made on or near the days its schools closed was not in use. That is only
as good as the reads. KULR's capture of 2019-07-16 of ``kulr8.com/schoolclosures/``
held a list of 25 Montana schools ("Amsterdam School CANCELED, Belgrade School
District 2-HOUR DELAY ...") in a page form the Cowles adapter refused; Orange
County Public Schools' homepage of 2022-09-28 said "All Schools/District Offices
Closed Wednesday, Thursday and Friday" (Hurricane Ian) in a slider caption the
SharpSchool reader did not look at. This module reads every downloaded capture of
the sources the gate has to settle as text, independently of the adapters, and
says which captures show a closing that the adapter's rows do not hold.

What is read (:func:`page_lines`): the text a visitor sees. For an HTML page, the
text of the body with scripts, styles, templates and forms' option lists removed,
and the entries of the site's menus (the lists, buttons and short links of ``nav``,
``role="navigation"``, ``footer``, and of elements whose class or id names a menu
or navigation and that are mostly links; the rest of their text is read: Okaloosa
kept its newswire inside its ``<nav>``); an ``aria-hidden`` slider or a ``noscript``
fallback is read, since a visitor sees it; inline markup joined into its block (so a
sentence split by ``<strong>`` stays one line, and two inline runs side by side stay
two words), one line per block.
A JSON body (a list file, an alert service's answer) is read as its string
values, HTML in them reduced to text. Scripts are not read: a Nuxt page's state
holds its drafts and archived banners too, which no visitor saw (Madison's draft
"ALL MADISON SCHOOLS WILL BE CLOSED FEB. 14th DUE TO WEATHER" of 2024-12-26).

What counts (:func:`is_closing`, and :func:`is_notice` for a weather status): a line
that announces a closing,
a delay, an early dismissal, a remote day, cancelled classes, no school or a snow
day (the district notice gate's own patterns,
:mod:`snowlight.sources.stations.notices`, and :data:`STATUS_MORE`) and also names
weather or an emergency, or a day or a date ("SDIRC Closed Monday Nov. 9 Due to
Potential Storm Impacts From Tropical Storm Eta", "Late Start on January 11",
"School cancelled on Monday 9/13/21", "Tropical Storm Nicole Update: District &
School Closures"). A planned day (a holiday, a break, staff development), a
deadline's "closes", a closed session, a school closed for good, a hazard
mitigation plan, a road's closing, and a bare heading ("School Closures",
"Closings & Delays") are not closings. A line of a list with neither (a TV
station's "Amsterdam School CANCELED") is not flagged by itself: such a list is
headed by a line that is ("Statewide school delays and closures for Monday,
March 4"). A district's weather status for a named day is flagged too, open or
not ("School will be in session and follow regular schedules at all PCSD 25 schools
today, Wednesday, January 5, 2022. Please continue to expect winter driving
conditions", :func:`is_notice`), on a district's page, not a TV station's. The few
sentences that are a page's own
furniture rather than a notice are listed in :data:`BOILERPLATE`, each with the
page it comes from; nothing else is excused.

The comparison (:func:`missed`): a line that is a closing is *read* when one of
the adapter's rows for that capture holds it (its name, status or extra text,
compared as lower-case words, on the line's first 60 characters, or the row's
status found in the line), else *missed*. A capture's ``outcome`` is:

* ``unrecognized``: its adapter refused its shape (``ShapeError``): whatever the
  page showed was not read, closings or not;
* ``missed``: a closing line no row holds (a page read empty, populated with
  other rows, or a page shell, while it showed a closing);
* ``shell``: a page the adapter recognized as one that loads its list from
  another address the archive does not hold near it, showing no closing itself;
* ``cut``: a page the archive holds only the first 1,048,576 bytes of, which its
  adapter could not read (:func:`~snowlight.sources.stations.archive.cut_off`: a
  Nuxt 2 homepage whose ``window.__NUXT__`` payload, the only place its alert banner
  is written, runs past the cut), showing no closing in the part the archive holds;
  no reader can read the rest, so it is not misread;
* ``read``: every closing line it showed is in its rows;
* ``clean``: it showed no closing line (or, on a TV station's page, only story
  teasers) and its adapter read it.

The gate (``gate report``) counts a capture with outcome ``unrecognized`` or
``missed`` in a source's closure window as *misread*, and a source with a misread
window capture can never get a settled verdict (``storm-read``,
``no-storm-capture``, ``unreadable``); its verdict is ``misread`` until its
adapter reads that page form.

Written (internal) by ``snowlight stations gate text-check`` to
``archive/closure-text.jsonl``, one record per capture checked::

    {"source_id", "url", "captured_at", "sha256", "read": state | "error",
     "variant", "rows", "reason", "outcome",
     "closing_lines": [{"text", "read": bool}, ...]}

and a summary to ``archive/closure-text.json`` (counts by source and outcome).

The audit (:func:`audit`): a second, wider net over the same captures, independent of
the check's own reading (only scripts, styles, templates and the head removed; any
status word with any weather word, :func:`broad_lines`). The lines it catches that
the check did not count and no row holds are listed by source in
``archive/closure-audit.json`` for review by eye; it changes no verdict.
"""

import json
import re
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from selectolax.parser import HTMLParser, Node

from snowlight.output import JSONValue
from snowlight.sources.stations import notices
from snowlight.sources.stations.archive import (
    WAYBACK_STAMP,
    capture_time,
    find_manifests,
    read_manifest,
    station_index,
    url_key,
)
from snowlight.sources.stations.gap_markup import collapse, html_text
from snowlight.sources.stations.http import iso_utc
from snowlight.sources.stations.model import (
    ListingRead,
    ParsedRow,
    RawRow,
    ShapeError,
    SourceHealth,
)
from snowlight.sources.stations.registry import Registry

CHECK_FILE = "closure-text.jsonl"
SUMMARY_FILE = "closure-text.json"
MAX_LINE = 600
"""Longer blocks are split into sentences before they are checked."""
MAX_KEPT = 12
"""At most this many closing lines are kept per capture (the count is complete)."""
MATCH_PREFIX = 60
"""How many characters of a closing line (as words) a row must hold for it to be read."""

_REMOVED = "script, style, template, svg, head, select, option"
"""What a visitor does not read as the page's text: scripts and styles, inert templates
and a form's option lists. Not removed: ``aria-hidden`` elements, which a sighted
visitor sees (Seminole's homepage slider of 2022-11-10, marked ``aria-hidden="true"``,
headed "Tropical Storm Nicole Update: District & School Closures"), and ``noscript``
fallbacks, which a visitor without scripts sees."""
_NAVIGATION = "nav, footer, [role=navigation], [role=menubar]"
"""The site's navigation, whose menu entries are not read (:func:`_strip_menu`)."""
_MENU_ENTRIES = "ul, ol, li, button"
"""A menu's entries: its lists and buttons."""
MENU_LINK = 60
"""A link in a menu whose text is at most this long is a menu entry ("Inclement Weather
Delay Schedule"); a longer one is a ticker's or a news item's sentence, which is read
(Okaloosa's homepage of 2019-10-17 carried its newswire inside its ``<nav>``: "Schools
will be in session on Friday ... We will continue to monitor weather conditions")."""
_MENU = re.compile(
    r"(?:^|[-_\s])(?:menu|menus|megamenu|nav|navbar|navigation|subnav|breadcrumbs?|sitemap|"
    r"site-?map|quick-?links|footer)(?:$|[-_\s\d])",
    re.IGNORECASE,
)
_INLINE = [
    "a",
    "abbr",
    "b",
    "big",
    "cite",
    "code",
    "del",
    "em",
    "font",
    "i",
    "ins",
    "label",
    "mark",
    "q",
    "s",
    "small",
    "span",
    "strike",
    "strong",
    "sub",
    "sup",
    "time",
    "u",
]
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_TAG = re.compile(r"<[^>]{0,2000}>")

_DAY = notices.DAY
"""A day or a date (:data:`snowlight.sources.stations.notices.DAY`)."""

STATUS_MORE = re.compile(
    r"\bno\s+(?:school|classes|in-person\s+(?:school|classes|learning))\b"
    r"|\b(?:will\s+not|won't)\s+have\s+(?:school|classes)\b"
    r"|\bsnow\s+days?\b|\bsin\s+clases\b",
    re.IGNORECASE,
)
"""Closings the notice gate's patterns do not name: "No School Monday", "Snow Day"."""
_SNOW_DAY = re.compile(r"\bsnow\s+days?\b", re.IGNORECASE)
"""A snow day named: a closing only with the day it falls on (:func:`is_closing`)."""

PLANNED_MORE = re.compile(
    r"\beaster\b|\bvacation\b|\b(?:records?|grading)\s+days?\b"
    r"|\b(?:winter|spring|fall|thanksgiving|christmas|holiday|mid-?winter)\s+recess\b"
    r"|\bprep(?:aration)?\s+days?\b|\bpresident'?s'?\s+day\b|\brecess\s+days?\b"
    r"|\bcomp(?:ensatory)?\s+days?\b",
    re.IGNORECASE,
)
"""Planned days the notice gate's patterns do not name ("Easter Monday-No School"; a
calendar's "Teacher Prep Day (No School)", "President's Day (No School)" and "SEP/SEOP
Comp Recess Day (No School)", Washington County's homepage calendar of 2024)."""

ABOUT = re.compile(
    r"\b(?:procedures?|process|polic(?:y|ies)|protocols?|guidelines?|faqs?|"
    r"frequently\s+asked|information)\b",
    re.IGNORECASE,
)
"""A page about how closings work ("Snow Day Procedures and Process", "School Closure
Information"): with no day or date, a link to that page, not a closing."""

_HEADING = re.compile(
    r"^\W*(?:(?:school|weather|storm|emergency|inclement\s+weather)\s+)?"
    r"(?:closings?|closures?|delays?|cancell?ations?)"
    r"(?:\s*(?:&|and|/|,)\s*(?:delays?|closings?|closures?|cancell?ations?))*\W*$",
    re.IGNORECASE,
)
"""A bare heading of a closings page or menu ("School Closures", "Closings & Delays")."""

BOILERPLATE: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"we update this page regularly so you'll be the first to know if your school is "
            r"closing",
            re.IGNORECASE,
        ),
        "the NBC owned stations' closings page's own empty-state sentence (NBC Los Angeles, "
        "NBC Bay Area, NBC San Diego, NBC 6 Miami): 'Forecast: School's Open. But don't "
        "worry, we update this page regularly ...'",
    ),
    (
        re.compile(
            r"^school closures - yesterday, today, and in the future$"
            r"|^this page is dedicated to listing school closures across santa cruz county",
            re.IGNORECASE,
        ),
        "the Santa Cruz County Office of Education's closures page's own heading and "
        "introduction ('ScHOOL CLOSURES - YESTERDAY, TODAY, AND IN THE FUTuRE', 'This page "
        "is dedicated to listing school closures across Santa Cruz County ...'), above the "
        "list it loads",
    ),
)
"""Sentences that are a page's own furniture, not a notice: each with where it is from."""


class TextCheckError(ValueError):
    """An input of the check does not have the shape it should."""


_NEVER_MENUS = frozenset({"html", "body", "main"})
"""Elements never removed as menus: a page's whole body says what menus it has in its
classes (WordPress' ``mega-menu-primary`` on Murray's ``<body>``)."""
LINK_SHARE = 0.5
"""A menu-named element is removed only when at least this share of its text is link text."""


def _link_text(node: Node) -> int:
    return sum(len(collapse(anchor.text(deep=True))) for anchor in node.css("a"))


def _menu_like(node: Node) -> bool:
    """Whether an element is a menu: named one (class or id) and made mostly of links.

    The name alone is not enough: a page's body or a wrapper says what menus it holds
    in its classes (Murray's homepage of 2022-12-02, ``<body class="... mega-menu-primary
    ...">``, whose slider said "Based on current weather conditions, Murray City School
    District will impose a two-hour late start"), and a menu is mostly links.
    """
    if node.tag in _NEVER_MENUS:
        return False
    attrs = node.attributes
    names = " ".join(str(attrs.get(key) or "") for key in ("class", "id"))
    if not names or _MENU.search(names) is None:
        return False
    total = len(collapse(node.text(deep=True)))
    return total == 0 or _link_text(node) >= LINK_SHARE * total


def _strip_menu(node: Node) -> None:
    """Remove a menu's entries (its lists, buttons and short links), keeping its other text.

    A site's navigation holds more than its menu: Okaloosa's ``<nav>`` held the
    district's newswire, and a header region named for its menu holds the alert banner.
    """
    for entry in node.css(_MENU_ENTRIES):
        if entry.parent is not None:
            entry.decompose()
    for anchor in node.css("a"):
        if anchor.parent is not None and len(collapse(anchor.text(deep=True))) <= MENU_LINK:
            anchor.decompose()


def _json_strings(value: object) -> Iterator[str]:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            stack.extend(reversed(item))


def _split(text: str) -> list[str]:
    text = collapse(text)
    if not text:
        return []
    if len(text) <= MAX_LINE:
        return [text]
    return [part[:MAX_LINE] for part in _SENTENCE.split(text) if part.strip()]


def _from_json(text: str) -> list[str] | None:
    stripped = text.lstrip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        data = json.loads(stripped)
    except ValueError:
        return None
    lines: list[str] = []
    for value in _json_strings(data):
        plain = _TAG.sub(" ", value) if "<" in value else value
        lines.extend(_split(plain))
    return lines


@dataclass(frozen=True, slots=True)
class Line:
    """One line of text a page shows, and whether it is all the text of one link."""

    text: str
    link: bool = False
    notice: bool = False
    """Whether the line is a weather status that is not a closing (:func:`is_notice`)."""


def page_blocks(body: bytes) -> list[Line]:
    """The lines of text a capture shows (see the module docstring), each marked as a link
    when the whole line is the text of one ``<a href>`` (a story's teaser, a menu item).

    An empty list for a body that is neither HTML with a body nor JSON.
    """
    try:
        text = html_text(body)
    except ShapeError:
        return []
    found = _from_json(text)
    if found is not None:
        return [Line(line) for line in found]
    tree = HTMLParser(text)
    if tree.body is None:
        return []
    for node in tree.css(_REMOVED):
        node.decompose()
    menus = tree.body.css(_NAVIGATION)
    menus.extend(item for item in tree.body.traverse() if item.tag and _menu_like(item))
    for node in menus:
        _strip_menu(node)
    links = {
        collapse(anchor.text(deep=True, separator=" "))
        for anchor in tree.body.css("a[href]")
        if not str(anchor.attributes.get("href") or "").strip().startswith(("#", "javascript"))
    }
    for node in tree.body.css(", ".join(_INLINE)):
        # Two inline elements side by side are two runs of text a page styles apart
        # (Citrus' slide of 2020-11-13: <span>Storm Update: Hurricane Eta</span><span>The
        # latest on school closures</span>), not one word: keep a space between them.
        following = node.next
        if following is not None and following.tag in _INLINE:
            node.insert_after(" ")
    tree.unwrap_tags(_INLINE)
    tree.merge_text_nodes()  # type: ignore[no-untyped-call]  # selectolax leaves it untyped
    lines: list[Line] = []
    for raw in tree.body.text(separator="\n").split("\n"):
        lines.extend(Line(part, part in links) for part in _split(raw))
    return lines


def page_lines(body: bytes) -> list[str]:
    """The lines of text a capture shows, without their link marks (see :func:`page_blocks`)."""
    return [line.text for line in page_blocks(body)]


def has_status(text: str) -> bool:
    """Whether a text names a closing, a delay, a dismissal, a remote day or cancelled classes.

    The district notice gate's patterns (:mod:`snowlight.sources.stations.notices`),
    in English and Spanish, with :data:`STATUS_MORE`; a deadline's "closes", a closed
    session or campus, and a school closed for good are not closings.
    """
    cleaned = notices._NOT_A_CLOSING.sub(" ", text)
    return (
        any(pattern.search(cleaned) for pattern in notices._STATUS)
        or notices._SPANISH_STATUS.search(cleaned) is not None
        or STATUS_MORE.search(cleaned) is not None
    )


def has_weather(text: str) -> bool:
    """Whether a text names weather or an emergency (not a planning document's hazards)."""
    found = notices._WEATHER.search(text) or notices._SPANISH_WEATHER.search(text)
    return found is not None and notices._PLANNING.search(text) is None


def is_planned(text: str) -> bool:
    """Whether a text names a planned day (a holiday, a break, staff development)."""
    return bool(
        notices._PLANNED.search(text)
        or notices._SPANISH_PLANNED.search(text)
        or PLANNED_MORE.search(text)
    )


def is_closing(line: str) -> bool:
    """Whether a line of a page announces a closing (see the module docstring).

    A closing (:func:`has_status`) that is not a planned day and names weather or an
    emergency (:func:`has_weather`) or a day or a date (:data:`_DAY`); a line about
    how closings work (:data:`ABOUT`), or whose only closing is a snow day named, only
    when it names a day or a date (Weber's "Utah is a winter state ... Read More About
    Snow Days" is no closing, "Snow Day Monday" is).
    """
    if len(line) < 8 or _HEADING.match(line):  # noqa: PLR2004 - shorter is no sentence
        return False
    if any(pattern.search(line) for pattern, _why in BOILERPLATE):
        return False
    if not has_status(line) or is_planned(line):
        return False
    day = _DAY.search(notices._NOT_A_CLOSING.sub(" ", line)) is not None
    if not day and (ABOUT.search(line) or notices._SERVICE.search(line)):
        return False
    if not day and not has_status(_SNOW_DAY.sub(" ", line)):
        return False  # "Snow Days" alone: a menu's entry, an explainer's title, a story
    return has_weather(line) or day


_ABOUT_LINK = re.compile(r"^(?:(?:read|learn|see)\s+more\s+)?about\s+", re.IGNORECASE)
"""A site's hidden "about <title>" label of a read-more link (Finalsite's)."""


def is_notice(line: str) -> bool:
    """Whether a line is a district's weather status for a named day that is not a closing.

    "School will be in session and follow regular schedules at all PCSD 25 schools
    today, Wednesday, January 5, 2022. Please continue to expect winter driving
    conditions" (:func:`snowlight.sources.stations.notices.page_text_status`): a
    homepage that shows it carries the district's weather notices, so a read that does
    not hold it misread the page as much as one that missed a closing.
    """
    if len(line) < 8 or any(pattern.search(line) for pattern, _why in BOILERPLATE):  # noqa: PLR2004
        return False
    return notices.page_text_status(line) and not is_closing(line)


PAIR_HEAD = 150
"""The longest line read as the title of the line after it (:func:`with_pairs`)."""
PAIR_JOIN = " \u2014 "
"""How a title and the line after it are joined into one line."""
_STAMP_WORDS = re.compile(
    r"\b(?:posted|updated|published|date|time|on|at|am|pm|a\.m|p\.m|event|all\s+day)\b"
    r"|\d+(?::\d+)?|[^\w\s]",
    re.IGNORECASE,
)


def _stamp_only(line: str) -> bool:
    """Whether a line is only a date or a posting stamp ("Posted: Tue. 12-03-2019 - 10:25 AM")."""
    rest = _STAMP_WORDS.sub(" ", _DAY.sub(" ", line))
    return len(rest.split()) == 0


def _qualifies(line: str) -> bool:
    return is_closing(line) or is_notice(line)


def with_pairs(lines: Sequence[str]) -> list[str]:
    """The lines, in page order, each followed by itself joined with the next line when
    neither says anything alone but the two together announce a closing or a weather
    status for a named day.

    A slider's title and its caption are two blocks: "Weather Alert: Tropical Cyclone 16"
    and "Schools are in session Friday. After school activities for Friday & Saturday
    are cancelled…" (Okaloosa's homepage of 2019-10-17). The first must be a title (at
    most :data:`PAIR_HEAD` characters), neither may be only a date or a posting stamp (a
    news item's date under its title: "Why Do Schools Try to Stay Open in Bad Weather?"
    over "February 27, 2023"), and the pair must name weather or an emergency and the day
    (:data:`snowlight.sources.stations.notices.DAY`), so a heading over a schedule
    ("Inclement Weather" over "Delayed Start Schedule") is not one, nor a calendar's date
    over its entry ("Feb 16" over "President's Day - No School"), and neither part may be
    about how closings work (:data:`ABOUT`: a board meeting's notice over "Snow Day
    Procedures and Process").
    """
    found: list[str] = []
    for index, line in enumerate(lines):
        found.append(line)
        if index + 1 >= len(lines) or len(line) > PAIR_HEAD:
            continue
        following = lines[index + 1]
        if _qualifies(line) or _qualifies(following):
            continue
        if _stamp_only(line) or _stamp_only(following):
            continue
        if ABOUT.search(line) or ABOUT.search(following):
            continue
        joined = f"{line}{PAIR_JOIN}{following}"[: MAX_LINE * 2]
        if _DAY.search(joined) and has_weather(joined) and _qualifies(joined):
            found.append(joined)
    return found


def closure_lines(lines: Iterable[str]) -> list[str]:
    """The lines that announce a closing or state a weather status for a day, each once,
    in page order (:func:`is_closing`, :func:`is_notice`).

    A line that only repeats another as a read-more label ("about Delayed start on
    Monday, January 26th") is left out.
    """
    seen: set[str] = set()
    found: list[str] = []
    for line in with_pairs(list(lines)):
        if line not in seen and _qualifies(line):
            seen.add(line)
            found.append(line)
    return [
        line
        for line in found
        if _ABOUT_LINK.sub("", line, count=1) == line
        or _ABOUT_LINK.sub("", line, count=1) not in seen
    ]


def closing_blocks(body: bytes) -> list[Line]:
    """The lines of a capture that announce a closing or state a weather status for a day,
    each once, with their link marks (a weather status marked as a notice)."""
    seen: dict[str, Line] = {}
    blocks = page_blocks(body)
    links: dict[str, bool] = {}
    for block in blocks:  # a line is a link's only when every time it shows it is one
        links[block.text] = links.get(block.text, True) and block.link
    for text in with_pairs([block.text for block in blocks]):
        line = Line(text, links.get(text, False))
        if line.text in seen:
            if not line.link and seen[line.text].link:
                seen[line.text] = Line(line.text, False, seen[line.text].notice)
            continue
        if is_closing(line.text):
            seen[line.text] = line
        elif is_notice(line.text):
            seen[line.text] = Line(line.text, line.link, notice=True)
    kept = set(closure_lines(seen))
    return [line for text, line in seen.items() if text in kept]


_WORDS = re.compile(r"[a-z0-9]+")


def _words(text: str) -> str:
    return " ".join(_WORDS.findall(text.lower()))


def _row_words(name: str, status: str, updated: str | None, extra: Mapping[str, object]) -> str:
    strings = " ".join(str(value) for value in extra.values() if isinstance(value, str))
    return _words(" ".join((name, status, updated or "", strings)))


def row_texts(rows: Iterable[RawRow]) -> list[str]:
    """Each stamped row's name, status, updated text and text extras, as lower-case words."""
    return [
        _row_words(row.raw_name, row.raw_status, row.raw_updated_text, row.raw_extra)
        for row in rows
    ]


def row_texts_of(rows: Iterable[ParsedRow]) -> list[str]:
    """The same for an adapter's rows (before they are stamped)."""
    return [_row_words(row.name, row.status, row.updated_text, row.extra) for row in rows]


def line_read(line: str, rows: Sequence[str]) -> bool:
    """Whether one of ``rows`` (from :func:`row_texts`) holds the closing ``line``."""
    words = _words(line)
    if not words:
        return True
    head = words[:MATCH_PREFIX].rsplit(" ", 1)[0] if len(words) > MATCH_PREFIX else words
    for row in rows:
        if head in row:
            return True
        status_head = row[:MATCH_PREFIX]
        if len(status_head) >= 20 and status_head in words:  # noqa: PLR2004 - a phrase, not a word
            return True
    return False


@dataclass(frozen=True, slots=True)
class ReadOf:
    """What the archive parse made of one capture: its state, rows and any failure."""

    state: str
    variant: str | None
    rows: tuple[RawRow, ...] = ()
    reason: str | None = None


SHELL_REASONS = ("the page holds no list", "the page gives only a count")
"""Failure reasons of a page its adapter recognized that loads its list elsewhere."""
SHELL_STATES = frozenset({"error", "deferred"})
"""Read states of a page that showed no list of its own (an error here is a shell's)."""
CUT_REASON = "cut off"
"""How the failure reason of a capture the archive cut off begins
(:data:`snowlight.sources.stations.archive.CUT_OFF`)."""


def outcome(
    read: ReadOf | None, lines: Sequence[Line], *, teasers: bool = False
) -> tuple[str, list[dict[str, JSONValue]]]:
    """A capture's outcome and its closing lines, each with whether a row holds it.

    ``teasers`` excuses closing lines that are all the text of one link (a story's
    teaser): set for a station list (a TV station's page), whose list is one module of
    a news page full of story links; never for a district's homepage, whose news items
    are its notices. A TV station's page is not checked for weather status lines
    (:func:`is_notice`) either: its list names closings, not the schools that open.
    """
    texts = row_texts(read.rows) if read is not None else []
    kept: list[dict[str, JSONValue]] = [
        {
            "text": line.text,
            "read": line_read(line.text, texts),
            "link": line.link,
            "notice": line.notice,
        }
        for line in lines
        if not (teasers and line.notice)
    ]
    missed = [item for item in kept if not item["read"] and not (teasers and item["link"])]
    if read is None:
        return ("unchecked" if not missed else "missed"), kept
    reason = read.reason or ""
    if read.state == "error" and reason.startswith(CUT_REASON):
        return ("missed" if missed else "cut"), kept
    if read.state == "error" and not reason.startswith(SHELL_REASONS):
        return "unrecognized", kept
    if missed:
        return "missed", kept
    if read.state in SHELL_STATES:
        return "shell", kept
    return ("read" if any(item["read"] for item in kept) else "clean"), kept


def _stamp(moment: datetime) -> str:
    return f"{moment:%Y%m%d%H%M%S}"


@dataclass(slots=True)
class Reads:
    """The archive parse's reads, rows and failures, by (capture timestamp, URL key)."""

    by_capture: dict[tuple[str, str], ReadOf] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        reads: Iterable[ListingRead],
        rows: Iterable[RawRow],
        health: Iterable[SourceHealth],
    ) -> "Reads":
        """Join reads with their rows (by source and capture time) and add failures.

        A page followed to its list file is given the file's read (state and rows),
        so a page that framed a list is compared with the list it loaded.
        """
        rows_of: dict[tuple[str, str], list[RawRow]] = defaultdict(list)
        for row in rows:
            rows_of[(row.source_id, iso_utc(row.fetched_at))].append(row)
        found = cls()
        for read in reads:
            got = tuple(rows_of.get((read.source_id, iso_utc(read.fetched_at)), ()))
            entry = ReadOf(read.state.value, read.variant, got)
            found.by_capture[(_stamp(read.fetched_at), url_key(read.url))] = entry
            for page in read.via:
                key = (_stamp(page.fetched_at), url_key(page.url))
                found.by_capture.setdefault(key, entry)
        for item in health:
            if item.url is None or item.sha256 is None or item.status.value in {"ok", "empty"}:
                continue
            key = (_stamp(item.checked_at), url_key(item.url))
            found.by_capture.setdefault(key, ReadOf("error", item.variant, (), item.reason))
        return found


@dataclass(frozen=True, slots=True)
class CaptureCheck:
    """One capture's check."""

    source_id: str
    url: str
    captured_at: str
    sha256: str
    read: ReadOf | None
    outcome: str
    lines: tuple[dict[str, JSONValue], ...]

    def as_json(self) -> dict[str, JSONValue]:
        """The record as ``closure-text.jsonl`` holds it."""
        missed = sum(1 for item in self.lines if not item["read"])  # teasers included
        return {
            "source_id": self.source_id,
            "url": self.url,
            "captured_at": self.captured_at,
            "sha256": self.sha256,
            "read": self.read.state if self.read is not None else None,
            "variant": self.read.variant if self.read is not None else None,
            "rows": len(self.read.rows) if self.read is not None else 0,
            "reason": (self.read.reason or None) if self.read is not None else None,
            "outcome": self.outcome,
            "closing_lines_count": len(self.lines),
            "missed_count": missed,
            "closing_lines": list(self.lines[:MAX_KEPT]),
        }


def check_captures(
    registry: Registry,
    root: Path,
    reads: Reads,
    wanted: Collection[str],
    *,
    cache: dict[str, list[Line]] | None = None,
) -> list[CaptureCheck]:
    """Check every downloaded capture under ``root`` of the sources in ``wanted``.

    Each capture once (by its page's URL key, capture time and SHA-256, as the
    archive parse reads it). ``cache`` maps a body's SHA-256 to its closing lines,
    filled as bodies are read (the lines depend on the body alone). A TV station's
    page (any source whose adapter is not a district channel's or a status board's)
    has its story teasers excused (:func:`outcome`).
    """
    index = station_index(registry)
    lines_of = cache if cache is not None else {}
    channels = notices.GENERAL_CHANNEL_ADAPTERS | notices.STATUS_BOARD_ADAPTERS
    seen: set[tuple[str, str, str]] = set()
    checks: list[CaptureCheck] = []
    for manifest in find_manifests(root):
        base = manifest.parent.parent
        for record in read_manifest(manifest):
            if record.file is None or record.sha256 is None:
                continue
            original = record.final_original or record.url
            station = index.get(url_key(original)) or index.get(url_key(record.url))
            if station is None or station.id not in wanted:
                continue
            stamp = record.final_timestamp or record.timestamp
            if not WAYBACK_STAMP.match(stamp):
                stamp = record.timestamp
            key = (url_key(original), stamp, record.sha256)
            if key in seen:
                continue
            seen.add(key)
            lines = lines_of.get(record.sha256)
            if lines is None:
                path = base / record.file
                if not path.is_file():
                    continue  # a manifest naming a body the artifact does not hold
                lines = closing_blocks(path.read_bytes())
                lines_of[record.sha256] = lines
            read = reads.by_capture.get((stamp, url_key(original)))
            teasers = registry.platform_of(station).adapter not in channels
            result, kept = outcome(read, lines, teasers=teasers)
            checks.append(
                CaptureCheck(
                    station.id,
                    original,
                    iso_utc(capture_time(stamp)),
                    record.sha256,
                    read,
                    result,
                    tuple(kept),
                )
            )
    checks.sort(key=lambda item: (item.source_id, item.captured_at, item.url))
    return checks


def body_files(registry: Registry, root: Path, wanted: Collection[str]) -> dict[str, Path]:
    """Each downloaded body of the sources in ``wanted``, by SHA-256."""
    index = station_index(registry)
    found: dict[str, Path] = {}
    for manifest in find_manifests(root):
        for record in read_manifest(manifest):
            if record.file is None or record.sha256 is None or record.sha256 in found:
                continue
            original = record.final_original or record.url
            station = index.get(url_key(original)) or index.get(url_key(record.url))
            path = manifest.parent.parent / record.file
            if station is not None and station.id in wanted and path.is_file():
                found[record.sha256] = path
    return found


def blocks_of_file(path: Path) -> list[Line]:
    """:func:`closing_blocks` of one body file (a top-level function, for a process pool)."""
    return closing_blocks(path.read_bytes())


def summary(
    checks: Sequence[CaptureCheck], coverage: Mapping[str, JSONValue] | None = None
) -> dict[str, JSONValue]:
    """Counts by outcome, nationally and by source, and the coverage result the sources came from.

    ``coverage`` (its path, SHA-256 and time) is recorded so the gate can refuse a
    check made against another coverage result.
    """
    total: Counter[str] = Counter(item.outcome for item in checks)
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    for item in checks:
        by_source[item.source_id][item.outcome] += 1
    return {
        "coverage": dict(coverage) if coverage is not None else None,
        "captures": len(checks),
        "outcomes": dict(sorted(total.items())),
        "boilerplate": [{"pattern": p.pattern, "why": why} for p, why in BOILERPLATE],
        "sources": {
            source: dict(sorted(counts.items())) for source, counts in sorted(by_source.items())
        },
    }


AUDIT_FILE = "closure-audit.json"
"""The audit's summary, beside the check's (:func:`audit`)."""
BROAD_STATUS = re.compile(
    r"\b(?:clos(?:ed|es|ing|ings|ure|ures)|cancel+(?:ed|s|ation|ations)?|delay(?:ed|s)?"
    r"|late\s+(?:start|arrival|opening)|(?:one|two|three|[123])[- ]hours?"
    r"|early\s+(?:dismissal|release|out)|dismiss(?:ed|al)|remote|virtual|e-?learning"
    r"|distance\s+learning|no\s+school|snow\s+days?|in\s+session|open(?:ed|s)?|reopen\w*"
    r"|cerrad[oa]s?|sin\s+clases)\b",
    re.IGNORECASE,
)
"""The audit's status words: any closing, delay, dismissal, remote day, or opening."""
BROAD_WEATHER = re.compile(
    r"\b(?:weather|snow\w*|ic(?:e|y)|storm\w*|hurricane\w*|tropical|freez\w*|cold|chill"
    r"|winter|roads?|fog\w*|flood\w*|winds?|power|outage\w*|emergenc\w*|fires?"
    r"|wildfires?|smoke|heat|blizzard|sleet|rain|frigid|temperatures?|hazard\w*"
    r"|conditions|plow\w*|evacua\w*|clima|hurac[aá]n|nieve)\b",
    re.IGNORECASE,
)
"""The audit's weather and emergency words, wider than the check's."""
_AUDIT_REMOVED = "script, style, template, head"


def broad_lines(body: bytes) -> list[str]:
    """Every line of a body's raw text that names a status word and a weather word.

    The audit's net (:func:`audit`), wider than the check's and independent of it:
    the body's text with only scripts, styles, templates and the head removed (menus,
    footers and hidden elements are read), one line per block, longer blocks split
    into sentences, each line once; a JSON body's string values. A line qualifies
    when it holds a word of :data:`BROAD_STATUS` and one of :data:`BROAD_WEATHER`.
    """
    try:
        text = html_text(body)
    except ShapeError:
        return []
    found = _from_json(text)
    if found is None:
        tree = HTMLParser(text)
        if tree.body is None:
            return []
        for node in tree.css(_AUDIT_REMOVED):
            node.decompose()
        found = [part for raw in tree.body.text(separator="\n").split("\n") for part in _split(raw)]
    lines = [line for line in found if BROAD_STATUS.search(line) and BROAD_WEATHER.search(line)]
    return list(dict.fromkeys(lines))


def broad_lines_of_file(path: Path) -> list[str]:
    """:func:`broad_lines` of one body file (a top-level function, for a process pool)."""
    return broad_lines(path.read_bytes())


def audit(
    checks: Sequence[CaptureCheck],
    broad: Mapping[str, Sequence[str]],
    coverage: Mapping[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    """The lines the audit's net caught that the check did not count, by source.

    For each checked capture, the lines of :func:`broad_lines` (``broad``, by the
    body's SHA-256) that are not among the capture's closing lines and that no row of
    its read holds: what the check excused (a heading, a link to a procedure, a
    holiday, a story's teaser, a road's closing, a makeup day). Each source lists its
    distinct excused lines with how many captures showed each and the first one
    (capture time and URL), so every excused line can be read by eye; nothing here
    changes a verdict. Written to ``archive/closure-audit.json``.
    """
    by_source: dict[str, dict[str, dict[str, JSONValue]]] = defaultdict(dict)
    captures: Counter[str] = Counter()
    for item in checks:
        counted = {str(line["text"]) for line in item.lines}
        held = row_texts(item.read.rows) if item.read is not None else []
        excused = [
            line
            for line in broad.get(item.sha256, ())
            if line not in counted and not line_read(line, held)
        ]
        if not excused:
            continue
        captures[item.source_id] += 1
        lines = by_source[item.source_id]
        for line in excused:
            entry = lines.setdefault(
                line,
                {"text": line, "captures": 0, "first": item.captured_at, "url": item.url},
            )
            count = entry["captures"]
            entry["captures"] = (count if isinstance(count, int) else 0) + 1
    sources: dict[str, JSONValue] = {}
    for source_id in sorted(by_source):
        ordered = sorted(
            by_source[source_id].values(),
            key=lambda entry: (-int(str(entry["captures"])), str(entry["text"])),
        )
        sources[source_id] = {"captures": captures[source_id], "lines": list(ordered)}
    return {
        "coverage": dict(coverage) if coverage is not None else None,
        "captures": len(checks),
        "status_words": BROAD_STATUS.pattern,
        "weather_words": BROAD_WEATHER.pattern,
        "sources": sources,
    }


def write_audit(out_dir: Path, result: Mapping[str, JSONValue]) -> Path:
    """Write the audit's summary (:func:`audit`) into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / AUDIT_FILE
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_checks(
    out_dir: Path,
    checks: Sequence[CaptureCheck],
    coverage: Mapping[str, JSONValue] | None = None,
) -> tuple[Path, Path]:
    """Write ``closure-text.jsonl`` and its summary into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / CHECK_FILE
    with path.open("w", encoding="utf-8") as handle:
        for item in checks:
            handle.write(json.dumps(item.as_json(), ensure_ascii=False) + "\n")
    summary_path = out_dir / SUMMARY_FILE
    summary_path.write_text(
        json.dumps(summary(checks, coverage), indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path, summary_path


@dataclass(frozen=True, slots=True)
class Checked:
    """What the check said of each capture, by (capture timestamp, URL key)."""

    outcomes: Mapping[tuple[str, str], str]
    sources: frozenset[str]
    coverage_sha256: str | None = None
    """The SHA-256 of the coverage result whose unproven sources were checked."""

    def misread(self, stamp: str, key: str) -> bool:
        """Whether the capture was refused by its adapter or showed a closing not read."""
        return self.outcomes.get((stamp, key)) in MISREAD


MISREAD = frozenset({"unrecognized", "missed"})
"""Outcomes after which a capture's read cannot settle its source."""


def load_checks(path: Path) -> Checked:
    """Read ``closure-text.jsonl`` into the gate's form."""
    outcomes: dict[tuple[str, str], str] = {}
    sources: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            moment = datetime.strptime(item["captured_at"], "%Y-%m-%dT%H:%M:%SZ")
            key = (_stamp(moment), url_key(str(item["url"])))
            result = str(item["outcome"])
            sources.add(str(item["source_id"]))
        except (ValueError, KeyError, TypeError) as error:
            raise TextCheckError(f"{path}:{number}: {error}") from error
        if outcomes.get(key) not in MISREAD:
            outcomes[key] = result
    sha: str | None = None
    summary_path = path.with_name(SUMMARY_FILE)
    if summary_path.is_file():
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        record = data.get("coverage") if isinstance(data, dict) else None
        value = record.get("sha256") if isinstance(record, dict) else None
        sha = value if isinstance(value, str) else None
    return Checked(outcomes, frozenset(sources), sha)

"""Text normalization, tokens, and the durations and clock times in status text.

:func:`normalize` folds a listing to one lowercase line with ASCII punctuation,
so the patterns elsewhere only deal with one spelling of each mark: curly quotes
become ``'``, every dash becomes ``-``, ``a.m.`` becomes ``am``, abbreviation
periods (``Jan.``, ``Tues.``, ``hrs.``) are dropped, ``&`` becomes ``and``,
line breaks become ``;`` (a clause boundary) and brackets become commas, so a
bracketed aside is a clause of its own. A hyphen or a slash that joins a day to
the word beside it is spaced out ("Closed-Wednesday" reads as "closed - wednesday",
"No School/3/11" as "no school / 3/11"), so the day is read as a day; so is one
that joins a word to a "no", "not" or "none" after it ("Closed/no virtual" reads
as "closed / no virtual"), so the "no" denies what follows it, and a hyphen
after a "no" becomes a space ("no-delay" reads as "no delay"). Offsets in
the normalized text are what every later step works with; the original text is
not consulted again.
"""

import html
import re
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import time
from functools import lru_cache

MAX_CHARS = 2000
"""Listings longer than this are read in part (see :func:`within_limit`): status text is a
line or two, never an essay."""
_PART_CHARS = (MAX_CHARS - 1) // 2  # each of the two parts read, and a line break between
_WORD_CUT = _PART_CHARS // 2  # how far back a part may reach for a space to end at


def within_limit(text: str) -> str:
    """``text`` when it is no longer than :data:`MAX_CHARS`, else its start and its end.

    Each part is about half the limit, ended at a space where one is near, and a
    line break (a sentence of its own once normalized) parts them: an update at
    the end of a long listing ("... UPDATE: open on time") is read, though the
    middle is not.
    """
    if len(text) <= MAX_CHARS:
        return text
    head = text[:_PART_CHARS]
    cut = head.rfind(" ")
    if cut > _WORD_CUT:
        head = head[:cut]
    tail = text[-_PART_CHARS:]
    cut = tail.find(" ")
    if 0 <= cut < _WORD_CUT:
        tail = tail[cut + 1 :]
    return f"{head}\n{tail}"


_BEFORE_NFKC = str.maketrans({"\u00bd": " 1/2 ", "\u00bc": " 1/4 ", "\u00be": " 3/4 "})
_CHARS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u2032": "'",
        "`": "'",
        "\u00b4": "'",
        "\u201c": " ",
        "\u201d": " ",
        '"': " ",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u2044": "/",
        "(": ", ",
        ")": ", ",
        "[": " ",
        "]": " ",
        "{": " ",
        "}": " ",
        "*": " ",
        "#": " ",
        "_": " ",
        "~": " ",
        "<": " ",
        ">": " ",
        "=": " ",
        "\t": " ",
        "\r": "\n",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\u2060": "",
        "\ufeff": "",
        "&": " and ",
        "@": " at ",
        # Accented letters, as Spanish day names carry them ("mañana", "miércoles"): see
        # dates.daylike_word.
        "\u00e1": "a",
        "\u00e9": "e",
        "\u00ed": "i",
        "\u00f3": "o",
        "\u00fa": "u",
        "\u00fc": "u",
        "\u00f1": "n",
    }
)
# "a.m." and "p.m.", also written right after the time: "9:30a.m.". The pattern takes their
# full stops (with what comes between them), so "am" and "pm" are left: it opens with the full
# stop, so the regex engine skips from one to the next, and reads the letter before it looking
# back (after a word boundary or a digit).
_MERIDIEM = re.compile(r"\.(?:(?<=\b[ap]\.)|(?<=\d[ap]\.))\s?m\b\.?", re.ASCII)
_ABBREVIATED = [
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sept", "sep", "oct", "nov", "dec", "mon",
    "tues", "tue", "weds", "wed", "thurs", "thur", "thu", "fri", "sat", "sun", "hrs", "hr", "mins",
    "min", "approx", "st", "mt", "dept", "elem", "jr", "sr",
]  # fmt: skip
# "w/" is "with", except in a list of day letters ("M/W/F", "W/Th").
_WITH = re.compile(r"\bw/o\b|(?<![a-z]/)\bw/(?!(?:th|[mtwrf])\b)", re.ASCII)
_EVENT = re.compile(r"\bin\s+the\s+event\s+(?:of|that)\b", re.ASCII)
# "zero" as a length: "zero hours", "zero minute delay", "zero hour late start". A lone "zero
# hour" is the class period before the first bell ("No zero hour classes"; see lexicon.py).
_ZERO = re.compile(
    r"\bzero(?=[\s-]*(?:hours|hrs|minutes?|mins?)\b"
    r"|[\s-]*(?:hour|hr)\b[\s-]*(?:delay|late|early|start|dismiss))",
    re.ASCII,
)
_DOUBLE_COLON = re.compile(r"(?<=\d)::(?=\d\d)", re.ASCII)
_AROUND_SCHOOL = re.compile(r"\b(after|before)\s+school\b", re.ASCII)
_ASCII_LIMIT = 128
# The same folding for ASCII text, as a byte table (fast), with the marks that become more
# than one character replaced first.
_ASCII_TABLE = bytes(
    ord(value) if len(value) == 1 else code
    for code, value in ((code, _CHARS.get(code, chr(code))) for code in range(256))
)
_ASCII_WIDE = tuple(
    (chr(code), value) for code, value in _CHARS.items() if code < _ASCII_LIMIT and len(value) != 1
)
_LINE = re.compile(r"\s*\n+\s*", re.ASCII)
# An arrow from one status to another says the first changed into the second: "2 hr delay ->
# closed", "Delay => Closing", "2 hour delay \u2192 e-learning".
# An arrow to a day ("Closed -> Thursday") only joins the day to the status.
_ARROW = re.compile(
    r"\s*(?:-+>|=+>|>{2,}|\u2192|\u21d2|\u27f6)\s*(?P<day>(?:mon|tue|wed|thu|fri|sat|sun|tod"
    r"|tom|ton|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|next|this"
    r"|\d{1,2}(?:[/.-]\d|st\b|nd\b|rd\b|th\b))\w*)?",
    re.IGNORECASE,
)


def _arrow(match: re.Match[str]) -> str:
    day = match.group("day")
    return " - now " if day is None else f" - {day}"


# A bracketed bare number ("Closed 3/15 (10)") is a count or a reference, never a day.
_NUMBER_NOTE = re.compile(r"\(\s*\d+\s*\)", re.ASCII)
# A day alone in brackets at the start of a slot after the first ("(TODAY) CLOSED |
# (TOMORROW) OPEN"), with no mark of its own after it and no day or number in its slot: a
# heading. The mark that ends the slot before it comes first ("mark"), so a scan looks for it
# before anything else. (The first slot's day reaches its status across a clause, as a day
# before a comma does: "(Tomorrow) All locations - closed". A slot that names a day of its
# own, "(TODAY) CLOSED ON THURSDAY TOO", is read as the bracket's words beside it, which two
# days that disagree leave unclear.)
_BRACKETED_HEADING = re.compile(
    r"(?P<mark>[|;!?])\s*\(\s*(?P<day>today|tomorrow|tonight|monday|tuesday|wednesday|thursday"
    r"|friday|saturday|sunday)\s*\)(?!\s*[-:,;|.])"
    r"(?=(?:(?!\||\d|\b(?:mon|tue|wed|thu|fri|sat|sun|today|tomorrow|tonight|tmrw|jan|feb|mar|apr"
    r"|may|jun|jul|aug|sep|oct|nov|dec)).)*(?:\||$))",
    re.ASCII | re.IGNORECASE,
)
# Markup ("<a href=...>", "</a>") and a web address ("https://...", "www...."): see
# normalize.
_LINK = re.compile(r"<[^<>]*>|\b(?:https?://|www\.)[^\s<>]*", re.ASCII | re.IGNORECASE)
# A number after "#" ("Closed #674", "Elementary #12") is a reference, never a day or a time.
_REFERENCE = re.compile(r" ?#\s?\d+(?![-/.:]?\d)", re.ASCII)
# When the listing was written or changed: "updated 5:43 AM", "posted Jan. 19 at 9:00 PM",
# "last updated: 1/19/2026 8:45:12 PM EST". The time and the date say nothing about when
# anything happens, so they are dropped and the word is kept.
_STAMP_WEEKDAY = (
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues?|weds?|thu|thur"
    r"|thurs|fri|sat|sun),?"
)
_STAMP_DATE = (
    r"(?:\d{1,2}/\d{1,2}(?:/\d\d(?:\d\d)?)?"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2}(?:,? 20\d\d)?)"
)
_STAMP_TIME = r"(?:\d{1,2}:\d\d(?::\d\d)?(?: ?[ap]m)?|\d{1,2} ?[ap]m)"
_ZONE_WORDS = r"(?: (?:[ecmp][sd]?t|ak[sd]?t|h[sd]?t|eastern|central|mountain|pacific))?"
_DASHED_STAMP = rf"(?: ?-+)(?: {_STAMP_WEEKDAY})? {_STAMP_DATE},?(?: at)?"
_STAMP = re.compile(
    rf"\b(?P<verb>(?:last )?(?:updated|update|posted|revised|modified|edited))"
    rf"(?::?(?: (?:at|on))?(?: {_STAMP_WEEKDAY})?(?: {_STAMP_DATE},?(?: at)?)?"
    # "Hurricane Ian Update - 9/27/22 12:20 p.m.": after a dash, a date and a time ("Update -
    # 10:00 start" is an opening time).
    rf"|{_DASHED_STAMP}) {_STAMP_TIME}{_ZONE_WORDS}(?: on {_STAMP_DATE})?\b",
    re.ASCII,
)
# A heading that says when a list was written: "As of Jan 28, 1:58pm: All schools in Alder
# County will be non-traditional learning on Thu. Jan. 29, 2026". A date and a time with a
# colon after them head the entry, so the day is when it was written, not when anything
# happens ("As of 2:00pm, Tuesday, January 10, all offices will close" keeps its day). The
# heading is dropped here, and read by written_at.
_AS_OF_STAMP = re.compile(
    rf"\bas of(?: {_STAMP_WEEKDAY})? {_STAMP_DATE},?(?: at)? {_STAMP_TIME}"
    rf"{_ZONE_WORDS} ?: ?",
    re.ASCII,
)
_COMMAS = re.compile(r",{2,}", re.ASCII)
# The same stamps read for when they say the listing was written (see written_at): a date and
# a time, in the order each form gives them.
_WRITTEN = re.compile(
    r"\b(?:(?:last )?(?:updated|update|posted|revised|modified|edited)(?::|(?: ?-+))?"
    r"(?: (?:at|on))?"
    rf"(?:(?: {_STAMP_WEEKDAY})? (?P<date>{_STAMP_DATE}),?(?: at)? (?P<time>{_STAMP_TIME})"
    rf"| (?P<time2>{_STAMP_TIME}){_ZONE_WORDS} on (?P<date2>{_STAMP_DATE}))"
    rf"|as of(?: {_STAMP_WEEKDAY})? (?P<date3>{_STAMP_DATE}),?(?: at)? (?P<time3>{_STAMP_TIME})"
    rf"{_ZONE_WORDS} ?:)",
    re.ASCII,
)
_MONTH_NUMBERS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}
_FIRST_AFTERNOON_HOUR = 13
_CENTURY = 2000
_TWO_DIGITS = 100
type Written = tuple[int, int, int | None, int, int]
"""When a listing says it was written: month, day, year (if given), hour and minute."""
_SPACE = re.compile(r"\s+", re.ASCII)
_WORD = re.compile(r"[a-z0-9]+(?:['/-][a-z0-9]+)*", re.ASCII)
WORD = _WORD
"""A word token: letters and digits, joined inside by an apostrophe, a slash or a hyphen."""


def _with(match: re.Match[str]) -> str:
    return "without" if match.group() == "w/o" else "with "


def normalize(text: str) -> str:
    """Fold ``text`` to the single-line lowercase form the parser reads.

    Things that never say when anything happens are dropped: a reference
    number ("#674"), a count in brackets ("(10)"), a link's markup and a web
    address, the time and date of an update stamp ("updated 5:43 AM" keeps
    "updated") and an "as of" heading with a date and a time ("As of Jan 28,
    1:58pm:"), so none is read as a day, an opening time or a dismissal time.
    (:func:`written_at` reads a stamp for when the listing was written.) The
    steps run in one function, each behind a quick test of the text, as most
    listings need few of them.
    """
    return normalize_stamped(text)[0]


def normalize_stamped(text: str) -> tuple[str, bool]:  # noqa: PLR0912, PLR0915 - one branch per step, each skipped when it cannot apply
    """:func:`normalize` of ``text``, and whether :func:`written_at` can find a stamp in it.

    The second is false only when :func:`written_at` of ``text`` is ``None``: the
    steps test for its words anyway ("updat", "posted", "as of", "revised",
    "modified", "edited"), and no step but the ones that say so below takes a
    letter out of a word (a text with markup, a web address, an escaped character
    or a character outside ASCII is said to hold one, whatever the words).
    """
    text = within_limit(text)
    stamped = False
    # Unescaped, and without the numbers that are counts or references ("(10)", "#674"), and
    # without markup and web addresses ("<a href="https://...">More Info</a>", "see
    # www.example.org"), whose words ("weather-and-emergency-information") say nothing.
    if "&" in text and ";" in text:
        text = html.unescape(text)
        stamped = True  # (an entity can take letters out of a word)
    if "<" in text or "://" in text or "www." in text or "WWW." in text:
        text = _LINK.sub(" ", text)
        stamped = True  # (a link's words are dropped)
    if "(" in text:
        # (A number word restated holds a bracketed number: with none, neither step finds any.)
        if _NUMBER_NOTE.search(text) is not None:
            text = _RESTATED_NUMBER.sub(_restated_word, text)
            text = _NUMBER_NOTE.sub(", ", text)
        # "(TODAY) CLOSED | (TOMORROW) OPEN": a day in brackets that opens a slot after the
        # first heads what follows it, as "Tomorrow: Open" does.
        text = _BRACKETED_HEADING.sub(r"\g<mark> \g<day>: ", text)
        # "Closed today (Thursday), Friday": the weekday in brackets names the day before it
        # again, as "today [Thursday]" and "today Thursday" do. The bracket goes, so no comma
        # takes its place: after a word for today or tomorrow a comma could start a list
        # ("today, Thursday and Friday": see dates.find_date_groups).
        if _WEEKDAY_IN_BRACKET(text) is not None:
            text = _bracketed_weekdays(text)
    if "#" in text:
        text = _REFERENCE.sub("", text)
    if ">" in text or "\u2192" in text or "\u21d2" in text:
        text = _ARROW.sub(_arrow, text)  # "2 hr delay -> closed": a change
    if text.isascii():
        text = text.lower()
        if "(" in text or ")" in text or "&" in text or "@" in text:  # (see _ASCII_WIDE)
            for mark, replacement in _ASCII_WIDE:
                text = text.replace(mark, replacement)
        text = text.encode("ascii").translate(_ASCII_TABLE).decode("ascii")
    else:
        text = unicodedata.normalize("NFKC", text.translate(_BEFORE_NFKC))
        text = text.casefold().translate(_CHARS)
        stamped = True  # (folding reads some letters as str.lower does not)
    if "." in text:
        if "a." in text or "p." in text:
            text = _MERIDIEM.sub("m", text)
        text = _ABBREVIATION_PERIOD.sub("", text)  # (see _drop_abbreviation_periods)
    if "::" in text:
        text = _DOUBLE_COLON.sub(":", text)  # "6::00 PM": a typing slip for 6:00 PM
    if "w/" in text:
        text = _WITH.sub(_with, text)
    if "event" in text:
        text = _EVENT.sub("in case of", text)
    if "zero" in text:
        text = _ZERO.sub("0", text)  # "zero hour delay": no delay, as "0 hour delay" is
    if " school" in text and ("after" in text or "before" in text):
        text = _AROUND_SCHOOL.sub(r"\1-school", text)
    if "-" in text or "/" in text:
        text = spaced_joins(text)
    if "\n" in text:
        text = _LINE.sub(" ; ", text.strip())
    if "  " in text or (text and (text[0] == " " or text[-1] == " ")) or not text.isprintable():
        # (Every character str.split takes for a space, but the space, is not printable: a
        # printable text with no space at either end and none doubled is split already.)
        text = " ".join(text.split())
    if "as of" in text:
        text = _AS_OF_STAMP.sub("", text)
        stamped = True
    if (
        "updat" in text
        or "posted" in text
        or "revised" in text
        or "modified" in text
        or "edited" in text
    ):
        text = _without_stamps(text)
        stamped = True
    # The commas brackets leave: "Closed tomorrow (Thursday)" names the day twice.
    if " ," in text or (text and (text[-1] == "," or text[0] == ",")):
        text = text.replace(" ,", ",").strip(" ,")
    if ",," in text:
        text = _COMMAS.sub(",", text)
    return text, stamped


# A number word restated in figures in brackets: "Two (2) hour delay". The figures say the
# word again, so they are dropped with their brackets (any other bracketed number is a note).
_RESTATED_NUMBER = re.compile(
    r"\b(?P<word>one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty"
    r"|forty[- ]five|forty|sixty|ninety)\s*\(\s*(?P<figures>\d{1,3})\s*\)",
    re.ASCII | re.IGNORECASE,
)
_WORD_VALUES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "forty-five": 45, "forty five": 45, "sixty": 60, "ninety": 90,
}  # fmt: skip


def _restated_word(match: re.Match[str]) -> str:
    word = match.group("word")
    if _WORD_VALUES[word.lower()] == int(match.group("figures")):
        return word  # "Two (2)": the word alone
    return match.group()  # "Two (3)": not a restatement, left for the rule on notes


# The words an update stamp's verb starts with (see _STAMP).
_STAMP_VERBS = ("updat", "posted", "revised", "modified", "edited")


def _without_stamps(text: str) -> str:
    """Drop the time and date of each update stamp: "updated 5:43 am" keeps "updated".

    For a text that holds a stamp verb (see :func:`normalize`). The pattern is
    run from the word that holds the first stamp verb, not from the text's
    start: before that word no stamp can start ("last" before "updated" stays
    either way, as the stamp keeps its verb).
    """
    first = len(text)
    for verb in _STAMP_VERBS:
        found = text.find(verb)
        if 0 <= found < first:
            first = found
    start = text.rfind(" ", 0, first) + 1  # (the stretch that holds it, from its start)
    return text[:start] + _STAMP.sub(_stamp_verb, text[start:])


def _stamp_verb(stamp: re.Match[str]) -> str:
    """What a stamp leaves: its verb, and the "at" after a bare "update", which can promise an
    update as much as date one ("Closed Thursday and Friday, update at 5am")."""
    verb = stamp.group("verb")
    if verb == "update" and stamp.group().startswith(" at", len(verb)):
        return "update at"
    return verb


def written_at(text: str) -> Written | None:
    """Return when the listing ``text`` says it was written, from its first stamp with a date
    and a time ("Last updated: 01/09/2025 05:13am", "As of Jan 28, 1:58pm: ...").

    The time must say whether it is morning or afternoon ("5:13am"), or be past
    noon in 24-hour form ("17:30"); otherwise, or when there is no such stamp,
    the result is ``None``. Whether the date exists is left to the caller.
    """
    lowered = within_limit(text).lower()
    if not (
        "updat" in lowered
        or "posted" in lowered
        or "as of" in lowered
        or "revised" in lowered
        or "modified" in lowered
        or "edited" in lowered
    ):
        return None  # (most listings: no stamp word, and nothing more is read)
    return _written_at(lowered)


def _written_at(lowered: str) -> Written | None:
    """:func:`written_at` for a lowercased text that holds a stamp word."""
    if "." in lowered:
        lowered = _drop_abbreviation_periods(_MERIDIEM.sub("m", lowered))
    lowered = " ".join(lowered.split())
    first = len(lowered)
    for word in ("updat", "posted", "as of", "revised", "modified", "edited"):
        place = lowered.find(word)
        if 0 <= place < first:
            first = place
    stamp = _WRITTEN.search(lowered, first)
    if stamp is None:
        return None
    clock = _written_clock(stamp.group("time") or stamp.group("time2") or stamp.group("time3"))
    if clock is None:
        return None
    month, day, year = _written_day(stamp.group("date") or stamp.group("date2") or stamp["date3"])
    return month, day, year, *clock


def _written_clock(stated: str) -> tuple[int, int] | None:
    """The hour and minute of a stamp's time ("8:45:12 pm", "11:08am", "4pm", "17:30"), when
    it says morning or afternoon (see :func:`written_at`)."""
    half = stated[-2:] if stated.endswith(("am", "pm")) else None
    hour_text, _colon, rest = (stated[:-2].strip() if half else stated).partition(":")
    hour, minute = int(hour_text), int(rest[:2] or 0)
    if minute > _LAST_MINUTE:
        return None
    if half is None:
        # "updated 1/28 17:30" is the afternoon; "updated 1/28 5:30" could be either.
        return (hour, minute) if _FIRST_AFTERNOON_HOUR <= hour <= _LAST_HOUR else None
    if not 1 <= hour <= _HALF_DAY:
        return None
    return hour % _HALF_DAY + (_HALF_DAY if half == "pm" else 0), minute


def _written_day(stated: str) -> tuple[int, int, int | None]:
    """The month, day and year (if given) of a stamp's date: "1/19/2026", "jan 28, 2026"."""
    if stated[0].isdigit():
        parts = stated.split("/")
        month, day = int(parts[0]), int(parts[1])
        year_text = parts[2] if len(parts) > 2 else ""  # noqa: PLR2004 - month/day/year
    else:
        name, _space, rest = stated.partition(" ")
        day_text, _space, year_text = rest.replace(",", "").partition(" ")
        month, day = _MONTH_NUMBERS[name[:3]], int(day_text)
    if not year_text:
        return month, day, None
    year = int(year_text)
    return month, day, year + _CENTURY if year < _TWO_DIGITS else year


# The regex engine skips to the places a pattern can start at when every branch of it
# opens with a character of its own; a class, "^" or a word boundary to open a branch
# makes it try every place in the text. These write such branches.
def one_of(chars: str) -> str:
    """A pattern of branches, each one of ``chars`` (as the class of them would match)."""
    return "|".join(map(re.escape, chars))


def at_word_start(word: str) -> str:
    """``\\b`` and ``word`` (which starts with a letter or a digit), as a branch that opens
    with the word's first character: the boundary is read after it, looking back."""
    first = re.escape(word[0])
    return first + r"(?<!\w" + first + ")" + re.escape(word[1:])


# A run of dashes at the text's start or after a space, before a space or the end: the
# branches of "(?:^|\s)-+(?=\s|$)". (Nothing comes before the first character of the text.)
DASH_RUN = r"-(?<![\s\S]-)-*(?=\s|$)|" + "|".join(
    space + r"-+(?=\s|$)" for space in (" ", r"\t", r"\n", r"\r", r"\f", r"\v")
)


type _Trie = dict[str, "_Trie"]


def trie(words: Iterable[str]) -> str:
    """Return a pattern matching any of ``words``, built as a character trie.

    A plain alternation of many words makes the regex engine try every word at
    every position; a trie rejects a position after one or two characters.
    """
    root: _Trie = {}
    for word in words:
        node = root
        for char in word:
            node = node.setdefault(char, {})
        node[""] = {}

    def build(node: _Trie) -> str:
        branches = [re.escape(char) + build(child) for char, child in sorted(node.items()) if char]
        if not branches:
            return ""
        if len(branches) == 1 and "" not in node:
            return branches[0]
        group = "(?:" + "|".join(branches) + ")"
        return group + "?" if "" in node else group

    return build(root)


# An abbreviation that starts a word and ends where the search ends: one of _ABBREVIATED
# right before a full stop.
_ABBREVIATION_BEFORE = re.compile(r"(?<![a-z0-9_])(?:" + trie(_ABBREVIATED) + r")\Z", re.ASCII)
_LONGEST_ABBREVIATION = max(map(len, _ABBREVIATED)) + 1
# The full stop after an abbreviation, which :func:`_drop_abbreviation_periods` drops: the
# pattern opens with the full stop, so the regex engine skips from one to the next, and
# reads back from each as :data:`_ABBREVIATION_BEFORE` does (a lookbehind has one width, so
# there is one for each length of abbreviation).
_ABBREVIATED_BY_LENGTH = {
    length: [word for word in _ABBREVIATED if len(word) == length]
    for length in sorted({len(word) for word in _ABBREVIATED})
}
_ABBREVIATION_PERIOD = re.compile(
    r"\.(?:"
    + "|".join(
        r"(?<=(?<![a-z0-9_])(?:" + trie(words) + r")\.)"
        for words in _ABBREVIATED_BY_LENGTH.values()
    )
    + ")",
    re.ASCII,
)


def _drop_abbreviation_periods(text: str) -> str:
    """Drop the full stop after each abbreviation in ``text`` ("jan. 21" becomes "jan 21").

    An abbreviation is a whole word of :data:`_ABBREVIATED` (``\\b(jan|...)\\.``
    in a pattern): the letters right before a full stop, with no letter, digit or
    underscore before them, as :data:`_ABBREVIATION_BEFORE` finds them at each full stop.
    """
    return _ABBREVIATION_PERIOD.sub("", text)


# Stretch by stretch ------------------------------------------------------------------------
#
# Most listings are words and marks that normalize only lowercases, dropping the full stop
# after an abbreviation: nothing it does reaches from one stretch between spaces to the next.
# Such a listing is its stretches normalized one by one, joined by single spaces, and the
# stretches of listings repeat ("Closed", "Wednesday;", "No"), so each is read once (see
# parse._read_stretches). A stretch is read on its own only when none of normalize's steps
# can change it but those two, or join it to its neighbour.

# The characters normalize folds or reads with what is around them (brackets, quotes, "&",
# "@", "#", markup, a line break, a tab, a space, anything outside ASCII) are not these.
_ALONE_CHARS = frozenset(chr(code) for code in range(33, 127)) - frozenset('"()[]{}*#_~<>=`&@')
# What some step of normalize reads within a stretch, that it would change or read with the
# stretch beside it: a doubled colon or comma, "w/", "zero" ("zero hour"), an update stamp's
# verb, a web address, and an "a." or "p." that ends the stretch ("9:30 a. m.").
_NOT_ALONE = re.compile(
    r"::|,,|w/|zero|" + "|".join(_STAMP_VERBS) + r"|://|www\.|[ap]\.\Z", re.ASCII
).search
NOT_ALONE = _NOT_ALONE
"""Search a lowercase stretch for what normalize reads with the stretches beside it (above)."""


def normalize_stretch(stretch: str) -> str | None:
    """:func:`normalize` of one stretch between spaces, when normalize reads it on its own.

    Then the stretch is only lowercased, with "a.m." read as "am" and the full
    stop after an abbreviation dropped, as within any text ("&" alone becomes
    "and"); ``None`` for a stretch that some other step could change, or that
    could take part in a step with the stretches beside it (an empty one, where
    spaces were doubled, too): "event" of "in the event of", or a comma that
    opens a stretch, which is closed up with the word before it. See
    :func:`joined_alone`.
    """
    if not stretch or stretch[0] == "," or not _ALONE_CHARS.issuperset(stretch):
        return "and" if stretch == "&" else None
    lowered = stretch.lower()
    if lowered == "event" or _NOT_ALONE(lowered) is not None:
        return None
    if "." in lowered:
        if "a." in lowered or "p." in lowered:
            lowered = _MERIDIEM.sub("m", lowered)
        lowered = _ABBREVIATION_PERIOD.sub("", lowered)
    if ("-" in lowered or "/" in lowered) and (
        _NUMBER_DASH_START(lowered) is not None
        or any(_joins_spaced(lowered + tail) for tail in _STRETCH_TAILS)
    ):
        # A day joined to a word by a mark is spaced out, which makes the stretch more than
        # one. What follows the stretch can make it a day, or not: "closed-next" of
        # "closed-next week", "closed-may" of "closed-may 4", "closed-2" of "closed-2 days",
        # "3/11/2" of "3/11/2 hour delay", and "wed-next" at the end of a text. So is a "no"
        # joined to the word before it ("closed/no" of "closed/no virtual").
        return None
    return lowered


# Days joined to a word ------------------------------------------------------------------
#
# "Closed-Wednesday", "No School-Tomorrow", "Closed/3-11" and "Wed-Closed" write the day and
# the status as one word; spaced out, the day is read as "Closed - Wednesday" reads it. (The
# names are those of snowlight.classify.dates, which tests hold to these lists.)

WEEKDAY_NAMES = (
    "monday", "mon", "tuesday", "tues", "tue", "wednesday", "weds", "wed", "thursday", "thurs",
    "thur", "thu", "friday", "fri", "saturday", "sat", "sunday", "sun",
)  # fmt: skip
"""The weekday names and their short forms the date patterns read."""
NEAR_DAY_WORDS = (
    "today", "tonight", "tonite", "2nite", "2night", "tomorrow", "tmrw", "tmw", "tmr", "tmrrw",
    "tomorow", "tommorow", "tommorrow", "tomorro", "tomoro", "tomm", "tomarrow", "tommrow",
    "2morrow", "2morow", "2moro", "2mrw", "2mrrw", "yesterday",
)  # fmt: skip
"""The words for today, tonight, tomorrow and yesterday the date patterns read."""
# A bracket that opens after a word for today or tomorrow, before a weekday name: "today
# (Thursday)", "Tomorrow ( Fri. )" (see normalize_stamped).
_BRACKETED_WEEKDAY = re.compile(
    rf"\b(?P<day>{trie(NEAR_DAY_WORDS)})\s*\((?=\s*(?:{trie(WEEKDAY_NAMES)})\b)",
    re.ASCII | re.IGNORECASE,
)
# The same in a lowercase text, one branch for each first character of the words, which it
# opens with (see at_word_start): the regex engine tries it only where a "t", a "2" or a "y"
# starts a word.
_BRACKETED_WEEKDAY_LOWER = re.compile(
    "(?P<day>"
    + "|".join(
        at_word_start(first)
        + "(?:"
        + trie(word[1:] for word in NEAR_DAY_WORDS if word[0] == first)
        + ")"
        for first in sorted({word[0] for word in NEAR_DAY_WORDS})
    )
    + rf")\s*\((?=\s*(?:{trie(WEEKDAY_NAMES)})\b)",
    re.ASCII,
)


def _bracketed_weekdays(text: str) -> str:
    """``text`` with the bracket after a word for a near day taken out where a weekday name
    opens it: _BRACKETED_WEEKDAY's matches replaced by their day and a space.

    An ASCII text's matches are found in its lowercase, where they stand at the same places
    (the pattern reads letters in any case, and a lowercase ASCII letter is one character).
    """
    if not text.isascii():
        return _BRACKETED_WEEKDAY.sub(r"\g<day> ", text)
    pieces: list[str] = []
    last = 0
    for match in _BRACKETED_WEEKDAY_LOWER.finditer(text.lower()):
        start = match.start()
        pieces += (text[last:start], text[start : match.end("day")], " ")
        last = match.end()
    if not pieces:
        return text
    pieces.append(text[last:])
    return "".join(pieces)


# A weekday name that opens a bracket: the quick test before the pattern above (a bracket
# most often holds something else, such as "(updated 6:41 AM)").
_WEEKDAY_IN_BRACKET = re.compile(
    r"\(\s*(?:mon|tue|wed|thu|fri|sat|sun)", re.ASCII | re.IGNORECASE
).search
MONTH_WORDS = (
    "january", "jan", "february", "feb", "march", "mar", "april", "apr", "may", "june", "jun",
    "july", "jul", "august", "aug", "september", "sept", "sep", "october", "oct", "november",
    "nov", "december", "dec",
)  # fmt: skip
"""The month names and their short forms the date patterns read."""
# Every word that names a day, as a whole run of letters: neither side of a mark is spaced
# out when both are ("Mon-Fri", "Jan-26th", "today/tomorrow").
_DAY_RUNS = frozenset(
    [*WEEKDAY_NAMES, *NEAR_DAY_WORDS, *MONTH_WORDS]
    + [f"{name}days" for name in ("mon", "tues", "wednes", "thurs", "fri", "satur", "sun")]
)
# A day that can follow a mark (the mark is spaced out when a word comes before it): a day's
# name ("may" only before a day number), a date ("3/11", "1-26", "1.26"), a day number
# ("11th"), a word that opens a date or a count of days, before a space ("the 11th", "next
# week", "this afternoon", "until further notice", "last Monday", "several days"), or a count
# of days ("2 days").
_DAY_AFTER_MARK = re.compile(
    r"(?:"
    + trie(sorted(_DAY_RUNS - {"may"}))
    + r")(?:'s)?(?![a-z0-9])|may(?= ?\d)|\d{1,2}(?:[/.-]\d{1,2}(?!\d)|(?:st|nd|rd|th)(?![a-z0-9]))"
    + r"|(?:the|next|this|coming|until|till|through|thru|every|rest|remainder|last|past|several"
    + r"|few|couple|multiple|another)(?= )"
    + r"|\d{1,2}(?=\s?-?(?:more |additional |consecutive |straight |school )?(?:days?|weeks?)\b)",
    re.ASCII,
).match
# A day that can come before a mark (the mark is spaced out when a word comes after it): a
# day's name, but for "sat", "sun", "mar" and "may", which start names and words as often
# ("Sun-Valley", "Mar-Lu"), or a date or a day number ("3/11", "3-11", "3.11", "11th"), before
# a word that is no unit ("3/11-closed", not "6-8-hour", "1.5-hour" or "11th-grade").
_DAY_BEFORE_MARK = _DAY_RUNS - {"sat", "sun", "mar", "may"}
_DATE_BEFORE_MARK = re.compile(
    r"(?<![\d/.:-])\d{1,2}(?:/\d{1,2}(?:/\d\d(?:\d\d)?)?|[-.]\d{1,2}|st|nd|rd|th)\Z", re.ASCII
).search
_UNIT_AFTER_MARK = re.compile(
    r"(?:hours?|hrs?|minutes?|mins?|days?|weeks?|am|pm|grades?|graders?)(?![a-z])", re.ASCII
).match
# The day names that a date after a mark restates or checks ("today/3/11", "wed-3/11"), and
# such a date.
_NAMED_DAY_RUNS = frozenset([*WEEKDAY_NAMES, *NEAR_DAY_WORDS]) - {"sat", "sun"}
_NUMBERED_DAY = re.compile(r"\d{1,2}(?:[/-]\d|st|nd|rd|th)", re.ASCII).match
# A date with a slash, or a day number, before a mark and a length after it: "3/11/2 hour
# delay", "11th-2 hour delay" ("2-1/2 hour" and "1 1/2 hour" are lengths alone).
_SLASHED_DATE_BEFORE_MARK = re.compile(
    r"(?<![\d/.:-])\d{1,2}(?:/\d{1,2}|st|nd|rd|th)\Z", re.ASCII
).search
# ... or a date with a hyphen or a month's name, before a hyphen: "3-11-2 hour delay", "Mar
# 11-2 hour delay" (not "2-1/2 hour").
_DASHED_DATE_BEFORE_MARK = re.compile(
    r"(?<![\d/.:-])\d{1,2}-\d{1,2}\Z|\b(?:" + trie(MONTH_WORDS) + r") ?\d{1,2}\Z", re.ASCII
).search
# A stretch that starts with a number and a hyphen, which a month's name in the stretch before
# can make a day and a length ("11-2" of "Mar 11-2 hour delay"): see normalize_stretch.
_NUMBER_DASH_START = re.compile(r"\d{1,2}-\d", re.ASCII).match
_LENGTH_AFTER_MARK = re.compile(
    r"\d{1,3}\s?-?\s?(?:hours?|hrs?|minutes?|mins?)(?![a-z])", re.ASCII
).match
# A clock time before a mark, which a day can follow ("opening at 10:00-11th").
_TIME_BEFORE_MARK = re.compile(r"(?<![\d:])\d{1,2}:\d\d\Z", re.ASCII).search
# A hyphen or a slash between two letters or digits. The pattern opens with the mark, so the
# regex engine skips from one to the next.
_JOIN_MARK = re.compile(r"[-/](?<=[a-z0-9][-/])(?=[a-z0-9])", re.ASCII)
_RUN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789'")


# What can follow a stretch, for each way what follows a mark decides whether it joins a day
# (see _DAY_AFTER_MARK and _LENGTH_AFTER_MARK): nothing, a number, a count of days, a length.
_STRETCH_TAILS = ("", " 1", " days", " hour")


def _day_join(text: str, at: int) -> bool:
    """Whether the mark at ``at`` joins a day to a word (see :func:`spaced_joins`)."""
    start = at
    while start and text[start - 1] in _RUN_CHARS:
        start -= 1
    before = text[start:at]
    after = _DAY_AFTER_MARK(text, at + 1)
    if after is not None:
        if before in _NAMED_DAY_RUNS and _NUMBERED_DAY(after.group()) is not None:
            # "today/3/11", "wed-3/11": two ways of naming the day, read side by side as in
            # "today / 3/11" (a date after a mark is not read as one: "1/2/3").
            return True
        # "closed-wednesday", "no school-tomorrow", "closed/3/11", "e-learning-wed": a word of
        # two letters or more before the day, not a day itself ("mon-fri", "jan-26th") nor a
        # number ("1st-3rd"), or a clock time ("opening at 10:00-11th").
        if len(before) >= 2 and before[0].isalpha() and before[-1].isalpha():  # noqa: PLR2004
            return before not in _DAY_RUNS
        return _TIME_BEFORE_MARK(text, 0, at) is not None
    # "wed-closed", "tomorrow-no school", "3/11-closed": a day, and a word after it; or a date
    # and a length ("3/11/2 hour delay").
    if not text[at + 1 : at + 3].isalpha():
        return _LENGTH_AFTER_MARK(text, at + 1) is not None and (
            _SLASHED_DATE_BEFORE_MARK(text, 0, at) is not None
            or (text[at] == "-" and _DASHED_DATE_BEFORE_MARK(text, 0, at) is not None)
        )
    if before in _DAY_BEFORE_MARK:
        return True
    return _DATE_BEFORE_MARK(text, 0, at) is not None and _UNIT_AFTER_MARK(text, at + 1) is None


# A word of denial after a mark, whole: the "no" of "closed/no virtual", the "not" of
# "open/not delayed", the "none" of "closed/none". The word before the mark that pairs with a
# "no" as one word of its own, which is not spaced out: "yes/no".
_DENIAL_AFTER_MARK = re.compile(r"no(?:t|ne)?(?![a-z0-9'])", re.ASCII).match
_PAIRED_WITH_NO = frozenset({"yes"})


def _denial_join(text: str, at: int) -> bool:
    """Whether the mark at ``at`` joins a word to a "no", "not" or "none" after it.

    "Closed/no virtual", "CLOSED-NO REMOTE", "2 hr delay/no virtual" and "Open/not
    delayed" write a status and a denied one as one word; spaced out, the "no"
    starts a phrase of its own and denies the noun after it, as in "closed / no
    virtual" (see :func:`spaced_joins`).
    """
    if text[at + 1] != "n" or _DENIAL_AFTER_MARK(text, at + 1) is None:
        return False
    start = at
    while start and text[start - 1] in _RUN_CHARS:
        start -= 1
    return text[start:at] not in _PAIRED_WITH_NO


def _joined_no(text: str, at: int) -> bool:
    """Whether the mark at ``at`` is a hyphen after a "no" of its own: "no-delay", "no-virtual".

    The "no" denies the word after it, as "no delay" does: "No-delay" states no
    delay and "Closed, no-virtual" no remote day ("no-school-related closings"
    is "no school-related closings").
    """
    return (
        text[at] == "-"
        and text.startswith("no", at - 2)
        and (at == 2 or text[at - 3] not in _RUN_CHARS)  # noqa: PLR2004 - the length of "no"
    )


def _spacing(text: str, at: int) -> str | None:
    """What :func:`spaced_joins` puts in place of the mark at ``at``, if it changes it."""
    if _day_join(text, at) or _denial_join(text, at):
        return f" {text[at]} "
    return " " if _joined_no(text, at) else None


def _joins_spaced(text: str) -> bool:
    """Whether :func:`spaced_joins` changes a mark in ``text``."""
    return any(_spacing(text, mark.start()) is not None for mark in _JOIN_MARK.finditer(text))


def spaced_joins(text: str) -> str:
    """Space out each hyphen or slash in lowercase ``text`` that joins a day, or a
    denial, to a word (see :func:`_joined_no` for a hyphen after a "no").

    The day is a day's name ("Closed-Wednesday", "No School-Tomorrow",
    "Wed-Closed"), a date ("Closed-3/11", "3/11-Closed") or a day number
    ("Closed-11th"), or a word that opens a date, before a space ("Closed-Next
    Week"); the word is any other of two letters or more. Both sides a day
    ("Mon-Fri", "Jan-26th", "Today/Tomorrow") or neither ("e-learning",
    "k-12", "2-hour") leave the mark as it is. So the joined listing reads as
    the spaced one does: "closed - wednesday". The denial is a "no", "not" or
    "none" after the mark, as a word of its own ("Closed/no virtual", "Open/not
    delayed"), but for "yes/no": spaced out, it denies what follows it, as in
    "closed / no virtual". A hyphen after a "no" of its own becomes a space, so
    the "no" denies the word it joins: "no-delay" is "no delay".
    """
    pieces: list[str] = []
    last = 0
    for mark in _JOIN_MARK.finditer(text):
        at = mark.start()
        spacing = _spacing(text, at)
        if spacing is not None:
            pieces += (text[last:at], spacing)
            last = at + 1
    if not pieces:
        return text
    pieces.append(text[last:])
    return "".join(pieces)


def joined_alone(text: str, joined: str) -> bool:
    """Whether ``normalize(text)`` is ``joined``: the stretches of ``text`` between single
    spaces, each read on its own by :func:`normalize_stretch` (none ``None``), joined again.

    The steps of normalize that read across stretches must find nothing: a text
    read in part (longer than :data:`MAX_CHARS`), a comma that ends the text (dropped), an "as of"
    heading, and "after school" (joined into one word). Such a text holds no word
    of a stamp, so :func:`written_at` finds none in it.
    """
    return len(text) <= MAX_CHARS and not (
        joined[-1:] == ","
        or "as of" in joined
        or (" school" in joined and ("after" in joined or "before" in joined))
    )


def by_char(prefixes: Iterable[str], index: int) -> dict[str, tuple[str, ...]]:
    """``prefixes`` by their character at ``index``, each longer than that: ``text.startswith(
    table.get(text[at + index : at + index + 1], ()), at)`` is ``text.startswith(prefixes,
    at)``, with only the few prefixes that can match there tried (a quick look on a hot path
    whose tuple of prefixes is long)."""
    table: dict[str, tuple[str, ...]] = {}
    for prefix in prefixes:
        if len(prefix) <= index:
            raise ValueError(prefix)
        table[prefix[index]] = (*table.get(prefix[index], ()), prefix)
    return table


def starts(prefixes: Iterable[str]) -> re.Pattern[str]:
    """Compile a pattern that finds word starts beginning with any of ``prefixes``."""
    return re.compile(r"\b" + trie(prefixes), re.ASCII)


def scan(pattern: re.Pattern[str], text: str, candidates: re.Pattern[str]) -> list[re.Match[str]]:
    """Return ``pattern``'s non-overlapping matches that start where ``candidates`` matches.

    Every pattern used this way begins with a word boundary and one of a known
    set of words, so trying it only where one of those words starts gives the
    same matches as ``finditer`` with far fewer attempts.
    """
    found: list[re.Match[str]] = []
    end = 0
    for candidate in candidates.finditer(text):
        start = candidate.start()
        if start < end:
            continue
        match = pattern.match(text, start)
        if match is not None:
            end = match.end()
            found.append(match)
    return found


# Tokenizing without the regex engine, for ASCII text: every character that no word holds
# becomes a space, so splitting at spaces leaves chunks of letters, digits and joining marks.
# A chunk of letters and digits alone is a word; the few with a mark go through the regex.
_TOKEN_CHARS = frozenset(b"abcdefghijklmnopqrstuvwxyz0123456789'/-")
_TOKEN_TABLE = bytes(code if code in _TOKEN_CHARS else 0x20 for code in range(256))


# A run's start mask: which scans can find something that starts at a run of letters and
# digits (see snowlight.classify.parse). The mention rules take the low 32 bits, one each
# (see snowlight.classify.mentions.RULE_BITS); then come the date and the weather scans, each
# with a bit for a run that surely starts a candidate and one for a run that may (the scan
# checks the text after it). The fields must not overlap: a rule's bit read as a date's or a
# weather term's would send each scan to runs where nothing of its own starts.
DATE_START_SHIFT = 32
WEATHER_START_SHIFT = 34
type Pieces = Sequence[tuple[int, Sequence[tuple[int, int]]]]
"""Where a scan can start in a text, by the stretch between spaces: for each stretch with
such places, where it starts and, for each place, its offset in the stretch and its start
mask (see :mod:`snowlight.classify.parse`)."""


def words(text: str, start: int = 0, end: int | None = None) -> list[str]:
    """Return the word tokens of ``text[start:end]``."""
    if start or end is not None:
        text = text[start:end]
    if len(text) > _LONGEST_SPAN:
        return _words(text)  # (the table keeps short spans only: a bound on its memory)
    return list(_span_words(text))


class _SpanWords(dict[str, tuple[str, ...]]):
    """The word tokens of each span of text read, worked out once: listings repeat the spans
    the parser reads words in (the words after a status, before it, between two marks)."""

    def __missing__(self, span: str) -> tuple[str, ...]:
        found = tuple(_words(span))
        if len(self) >= _MOST_SPANS:
            self.clear()  # a bound on memory; the words are the same when read again
        self[span] = found
        return found


_MOST_SPANS = 16384
_LONGEST_SPAN = 256
_SPAN_WORDS = _SpanWords()
_span_words = _SPAN_WORDS.__getitem__


def _words(text: str) -> list[str]:
    """The word tokens of ``text`` (see :func:`words`)."""
    if not text.isascii():
        return _WORD.findall(text)
    folded = text.encode("ascii").translate(_TOKEN_TABLE).decode("ascii")
    chunks = folded.split()
    if "-" not in folded and "/" not in folded and "'" not in folded:
        return chunks  # (most texts: no word is joined by a mark, so each chunk is a word)
    found: list[str] = []
    for chunk in chunks:
        if chunk.isalnum():
            found.append(chunk)
        else:
            found += _WORD.findall(chunk)
    return found


# Durations ---------------------------------------------------------------------------

_NUMBER_WORDS: dict[str, float] = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "half": 0.5,
    "a half": 0.5,
}
# (A number right after another and a slash or a hyphen is no length: the "2" of "11/2 hour"
# and of "1-2 hour".)
_NUM = r"(?:1/2(?!\d)|(?<!\d[/-])\d+(?:\.\d+)?|one|two|three|four|five|an?|(?:a\s+)?half)"
# Words may be joined by spaces or hyphens: "two and a half", "two-and-a-half".
_JOIN = r"(?:\s*-\s*|\s+)"
# A half after the whole number, set apart from it ("2 1/2", "1-1/2"): "11/2" is no "1 1/2".
_HALF = rf"(?:{_JOIN}1/2|{_JOIN}and{_JOIN}(?:a|one){_JOIN}half)"
_HOURS = r"(?:hours?|hrs?|h)\b"
_MINUTES = r"(?:minutes?|mins?|m)\b"
_MINUTE_WORDS: dict[str, int] = {
    "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "twenty-five": 25, "twenty five": 25,
    "thirty": 30, "forty": 40, "forty-five": 45, "forty five": 45, "fifty": 50, "sixty": 60,
    "seventy": 70, "seventy-five": 75, "seventy five": 75, "eighty": 80, "ninety": 90,
}  # fmt: skip
_MINUTE_COUNT = (
    r"(?:(?<!\d[/-])\d+|(?:twenty|forty|seventy)(?:[\s-]five)?|fifteen|thirty|fifty|sixty|eighty|ninety"
    r"|five|ten)"
)
# A look at the character a half or the minutes after the hours must start with, past the
# spaces, dashes and comma before them: a length with neither, the most common, tries no more
# of their patterns. (Each is a look ahead that the part itself needs to match.)
_HALF_LOOK = r"(?=\s*-?\s*[1a])"
_MINUTES_LOOK = r"(?=\s*,?\s*[0-9aefnst])"
# The minutes after the hours may follow a comma: "2 hour, 30 minute delay".
DURATION = (
    rf"(?:{_NUM}(?:{_HALF_LOOK}{_HALF})?\s*-?\s*{_HOURS}"
    rf"(?:{_MINUTES_LOOK}\s*,?\s*(?:and\s+)?(?:a\s+half|{_MINUTE_COUNT}\s*-?\s*{_MINUTES}))?"
    rf"|{_MINUTE_COUNT}\s*-?\s*{_MINUTES}"
    rf"|(?:(?:an?|one)\s+)?hour\s+and\s+(?:a\s+half|{_MINUTE_COUNT}\s*-?\s*{_MINUTES}))"
)
"""A pattern for a length of time: ``2 hour``, ``two-hour``, ``1 1/2 hrs``, ``1/2 hour``,
``90 min``, ``two-and-a-half hour``, ``two hours and thirty minutes``, ``ninety minute``.
None starts with a number right after another and a slash or a hyphen: the "2" of "11/2 hour"
and of "1-2 hour" is no length."""

_HOUR_PART = re.compile(rf"^(?P<n>{_NUM})(?P<half>{_HALF})?\s*-?\s*{_HOURS}", re.ASCII)
_MINUTE_PART = re.compile(rf"({_MINUTE_COUNT})\s*-?\s*{_MINUTES}", re.ASCII)
_SHORTEST_MINUTES = 10
_LONGEST_MINUTES = 300
_MINUTES_PER_HOUR = 60


def _number(token: str) -> float:
    if "/" in token:
        return 0.5  # "1/2", the one number with a slash (see _NUM)
    if token[0].isdigit():
        return float(token)
    return _NUMBER_WORDS[_SPACE.sub(" ", token)]


@lru_cache(maxsize=1024)
def duration_minutes(text: str) -> int | None:
    """Return the minutes a :data:`DURATION` match stands for.

    Lengths outside 10 minutes to 5 hours are not school delays or early
    dismissals and give ``None``.
    """
    text = text.strip()
    minutes = 0.0
    hours = _HOUR_PART.match(text)
    rest = text
    if hours is not None:
        minutes = _number(hours.group("n")) * 60
        if hours.group("half"):
            minutes += 30
        rest = text[hours.end() :]
    elif "hour" in text:
        minutes = 60
        rest = text[text.index("hour") + 4 :]
    if "half" in rest:
        minutes += 30
    extra = _MINUTE_PART.search(rest)
    if extra is not None:
        count = extra.group(1)
        added = int(count) if count[0].isdigit() else _MINUTE_WORDS[_SPACE.sub(" ", count)]
        if minutes and added >= _MINUTES_PER_HOUR:
            return None  # "2 hour, 90 minute": two lengths, not one
        minutes += added
    result = round(minutes)
    if not _SHORTEST_MINUTES <= result <= _LONGEST_MINUTES:
        return None
    return result


# Clock times -------------------------------------------------------------------------

CLOCK_STRICT = (
    r"(?:(?:12\s*)?noon|midday|\d{1,2}:\d{2}(?:\s*[ap]m\b|[ap]\b)?|\d{1,2}(?:\s*[ap]m|[ap])\b)"
)
"""A clock time that cannot be a bare number: ``10:00``, ``1 pm``, ``9a``, ``noon``."""
CLOCK = (
    r"(?:(?:12\s*)?noon|midday|\d{1,2}(?::\d{2}|\.[0-5][05])?(?:\s*[ap]m\b|[ap]\b)?)"
    r"(?![\d/]|\.\d|(?:st|nd|rd|th)\b)"
)
"""A clock time that may be a bare hour, for use after ``at``: ``1``, ``10:30``, ``10.30``,
``9a``. A day of the month ("11th") is none, and nor is a number with a full stop whose
minutes are not a multiple of five ("3.11" is a date the patterns do not read)."""

_CLOCK_PARTS = re.compile(r"(\d{1,2})(?:[:.](\d{2}))?\s*(?:([ap])m?)?", re.ASCII)
_NOON = time(12, 0)
_LAST_AFTERNOON_HOUR = 6
_HALF_DAY = 12
_LAST_HOUR = 23
_LAST_MINUTE = 59


@lru_cache(maxsize=1024)
def clock_time(text: str) -> time | None:
    """Return the local time a :data:`CLOCK` match stands for, or ``None`` if invalid.

    ``a`` and ``p`` are ``am`` and ``pm`` ("9a", "1:30p"). Without them, hours 1
    to 6 are afternoon (a school day has no 1 a.m. dismissal) and 7 to 12 are
    morning or noon; 13 to 23 are 24-hour times.
    """
    text = text.strip()
    if "noon" in text or text == "midday":
        return _NOON
    parts = _CLOCK_PARTS.fullmatch(text)
    if parts is None:
        return None
    hour = int(parts.group(1))
    minute = int(parts.group(2) or 0)
    meridiem = parts.group(3)
    if minute > _LAST_MINUTE or hour > _LAST_HOUR:
        return None
    if meridiem is not None:
        if hour == 0 or hour > _HALF_DAY:
            return None
        hour %= _HALF_DAY
        if meridiem == "p":
            hour += _HALF_DAY
    elif 1 <= hour <= _LAST_AFTERNOON_HOUR:
        hour += _HALF_DAY
    elif hour == 0:
        return None
    return time(hour, minute)

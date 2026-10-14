"""Throughput benchmark for parse_status on synthetic listing phrasings.

Every text here is generated from phrasing patterns; none is a real listing or
a claim about a real school. Run directly to print timings as JSON::

    uv run python tests/classify/bench_synthetic_listings.py

Nine workloads of 10,000 parses each, timed in CPU seconds (the best of five passes,
so that a pass slowed by other work on a shared machine does not count). "Nothing is
cached" means the text caches are emptied before each pass; the caches kept by word and
by stretch of text between spaces stay as a long run leaves them, except for ``named``:

* ``repeated``: phrasings drawn from a fixed set of about 300, as a live feed
  repeats "Closed", "2 Hour Delay" and the like; the text cache applies.
* ``distinct``: 10,000 different texts in realistic proportions (mostly a
  status with a date, some with a cause or a side note); nothing is cached.
* ``named``: 10,000 different texts that pair a status phrase with a school
  name made up from syllables ("Closed - Bakuzo Temira Elementary"), before or
  after it; every cache starts empty, so each name is new to the parser.
* ``dense``: 10,000 different texts that each carry a status, a date phrase, a
  cause and a side note; nothing is cached. The worst case.
* ``stamped``, ``numbered``, ``prefixed`` and ``side_noted``: 10,000 different
  texts shaped "<status> <day> <cause>", each with an update stamp ("(updated
  6:41 AM)"), a reference number ("#4411"), a made-up name before it
  ("Kubaze Temira Elementary: ") or a side note with a made-up name after it
  (", Kubaze Bus Garage open"); nothing is cached.
* ``real_length``: 10,000 different texts as long as real listings (a median of
  about 40 characters, a 90th percentile of about 107) and in their shapes: a
  side note, a day, no day, a day's slots, a sentence, a phrase joined by a
  hyphen ("No School-No Personnel Report Today"); nothing is cached.
"""

import itertools
import json
import random
import time
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from snowlight.classify import parse_status
from snowlight.classify.parse import _cached_analysis, _forget_words, _normalized_analysis

TZ = "America/New_York"
POSTED = datetime(2026, 1, 20, 5, 30, tzinfo=ZoneInfo(TZ))
COUNT = 10_000

SHORT = [
    "Closed", "CLOSED", "Closed Today", "Closed today", "No school", "2 Hour Delay",
    "2-Hour Delay", "Two Hour Delay", "90 Minute Delay", "Delayed", "Late Start",
    "Early Dismissal", "Early Release", "NTI Day", "AMI Day", "e-Learning Day",
    "Remote Learning", "Virtual Learning Day", "Closed Tomorrow", "2 Hour Delay Tomorrow",
    "Closing at noon", "Snow Day",
]  # fmt: skip
CAUSES = [
    "due to snow", "due to icy roads", "due to inclement weather", "- winter storm",
    "due to extreme cold",
]  # fmt: skip
NOTES = [
    "Offices open", "All after-school activities cancelled", "Buses on snow routes",
    "No AM kindergarten",
]  # fmt: skip
DENSE_STATUSES = [
    "Closed", "No school", "Classes cancelled", "2 Hour Delay", "Two-hour delay",
    "90 minute delay", "Delayed opening", "Late start", "Opening at 10:00", "Early dismissal",
    "Early dismissal at 1:00 pm", "Early release at noon", "Dismissing 2 hours early",
    "NTI Day", "e-Learning day", "Remote learning", "Virtual learning day", "AMI day",
    "Flexible instruction day", "Snow day", "All activities cancelled", "No AM kindergarten",
    "Possible early dismissal", "Offices closed", "Open", "Closed; offices open",
]  # fmt: skip
DENSE_DAYS = [
    "", "today", "tomorrow", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "today and tomorrow", "Monday-Wednesday", "through Friday", "until further notice",
    *(f"Jan. {day}" for day in range(5, 30)),
    *(f"1/{day}" for day in range(5, 30)),
]  # fmt: skip
DENSE_CAUSES = [
    "", "due to snow", "due to icy roads", "- winter storm", "due to extreme cold",
    "due to flooding", "(power outage)", "due to water main break", "due to inclement weather",
    "due to freezing rain",
]  # fmt: skip
DENSE_EXTRAS = [
    "", "; buses on snow routes", ". All after-school activities cancelled.",
    " - offices open", ", staff report at 10",
]  # fmt: skip


NAMED_STATUSES = [
    "NTI day", "AMI day", "e-learning day", "eLearning day", "Virtual learning day",
    "Remote learning", "Flexible instruction day (FID)", "Asynchronous learning day",
    "Snow day", "Closed due to inclement weather", "2-hour delay", "Two hour delay",
    "2hr delay", "2 hrs delay", "90 minute delay", "Opening at 10:00", "Late start",
    "Early release", "Early dismissal 1:00", "Dismissing 2 hours early", "Closing at noon",
    "Closed; offices open", "Closed today and tomorrow", "No school", "Classes cancelled",
    "All activities cancelled", "No AM kindergarten", "Evening activities cancelled",
    "Closed", "Closed tomorrow", "2 Hour Delay Tomorrow", "Closed Friday",
    "Closed Monday, Jan. 26", "Delayed opening 1/22", "Closed today due to snow and ice",
]  # fmt: skip
NAMED_KINDS = [
    "Elementary", "Elementary School", "Middle School", "High School", "Public Schools",
    "School District", "Academy", "Christian School", "Community Schools", "Preschool",
]  # fmt: skip
_SYLLABLES = (
    "ba", "be", "bi", "bo", "bu", "da", "de", "di", "do", "du", "ka", "ke", "ki", "ko", "ku",
    "la", "le", "li", "lo", "lu", "ma", "me", "mi", "mo", "mu",
)  # fmt: skip


def _made_up_name(rng: random.Random) -> str:
    """A school name made up from syllables: synthetic, never a real school."""
    words = [
        "".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(2, 4))).capitalize()
        for _ in range(rng.randint(1, 2))
    ]
    return " ".join([*words, rng.choice(NAMED_KINDS)])


def named_listings(seed: int = 5) -> list[str]:
    """10,000 different synthetic texts: a status phrase with a made-up school name."""
    rng = random.Random(seed)  # noqa: S311 - synthetic benchmark text, not security
    texts: set[str] = set()
    while len(texts) < COUNT:
        status, name = rng.choice(NAMED_STATUSES), _made_up_name(rng)
        form = rng.random()
        if form < 0.4:
            texts.add(f"{name}: {status}")
        elif form < 0.8:
            texts.add(f"{status} - {name}")
        else:
            texts.add(f"{status} ({name})")
    ordered = sorted(texts)
    rng.shuffle(ordered)
    return ordered


def distinct_listings(seed: int = 11) -> list[str]:
    """10,000 different synthetic texts in realistic proportions."""
    rng = random.Random(seed)  # noqa: S311 - synthetic benchmark text, not security
    texts: set[str] = set()
    first = date(2025, 12, 1)
    while len(texts) < COUNT:
        text = rng.choice(SHORT)
        day = first + timedelta(days=rng.randrange(120))
        roll = rng.random()
        if roll < 0.45:  # proportions of the synthetic mix
            text = f"{text} {day:%A}, {day:%b}. {day.day}"
        elif roll < 0.6:
            text = f"{text} {day.month}/{day.day}"
        if rng.random() < 0.25:
            text = f"{text} {rng.choice(CAUSES)}"
        if rng.random() < 0.15:
            text = f"{text}. {rng.choice(NOTES)}"
        if rng.random() < 0.2:
            text = f"{text} ({rng.randint(1, 9999)})"
        texts.add(text)
    ordered = sorted(texts)
    rng.shuffle(ordered)
    return ordered


def dense_listings(seed: int = 7) -> list[str]:
    """10,000 different synthetic texts that each carry every kind of phrase."""
    combos = list(itertools.product(DENSE_STATUSES, DENSE_DAYS, DENSE_CAUSES, DENSE_EXTRAS))
    random.Random(seed).shuffle(combos)  # noqa: S311 - synthetic benchmark text
    return [
        " ".join(part for part in (status, day, cause) if part) + extra
        for status, day, cause, extra in combos[:COUNT]
    ]


def repeated_listings(seed: int = 3) -> list[str]:
    """10,000 synthetic texts drawn from about 300 phrasings, as a live feed repeats them."""
    pool = distinct_listings(seed)[:300]
    rng = random.Random(seed)  # noqa: S311 - synthetic benchmark text
    return [rng.choice(pool) for _ in range(COUNT)]


PLAIN_STATUSES = [
    "Closed", "2 hour delay", "Early dismissal at {hour}:{minute:02d}", "Remote learning",
    "No school", "Opening at {hour}:{minute:02d}", "Closing {count} hours early",
    "NTI day {count}",
]  # fmt: skip
PLAIN_DAYS = ["today", "tomorrow", "Wednesday", "Jan {day}", "1/{day}", "today and tomorrow", ""]
PLAIN_CAUSES = ["due to snow", "due to ice", "- extreme cold", ""]


def _plain_listing(rng: random.Random) -> str:
    """A synthetic "<status> <day> <cause>" text."""
    status = rng.choice(PLAIN_STATUSES).format(
        hour=rng.randint(10, 13), minute=rng.choice((0, 15, 30, 45)), count=rng.randint(1, 3)
    )
    day = rng.choice(PLAIN_DAYS).format(day=rng.randint(1, 28))
    return " ".join(part for part in (status, day, rng.choice(PLAIN_CAUSES)) if part)


def _syllable_name(rng: random.Random) -> str:
    """A made-up word from syllables: synthetic, never a real name."""
    return "".join(rng.choice(_SYLLABLES) for _ in range(3)).capitalize()


def _decorated_listings(decorate: Callable[[str, random.Random, int], str], seed: int) -> list[str]:
    rng = random.Random(seed)  # noqa: S311 - synthetic benchmark text, not security
    texts: set[str] = set()
    while len(texts) < COUNT:
        texts.add(decorate(_plain_listing(rng), rng, len(texts)))
    ordered = sorted(texts)
    rng.shuffle(ordered)
    return ordered


def stamped_listings(seed: int = 13) -> list[str]:
    """10,000 different synthetic texts, each with an update stamp after it."""
    return _decorated_listings(
        lambda text, rng, _n: f"{text} (updated {rng.randint(4, 9)}:{rng.randint(0, 59):02d} AM)",
        seed,
    )


def numbered_listings(seed: int = 17) -> list[str]:
    """10,000 different synthetic texts, each with a reference number after it."""
    return _decorated_listings(lambda text, _rng, count: f"{text} #{count}", seed)


def prefixed_listings(seed: int = 19) -> list[str]:
    """10,000 different synthetic texts, each after a made-up school name."""
    return _decorated_listings(
        lambda text, rng, _n: f"{_syllable_name(rng)} {_syllable_name(rng)} Elementary: {text}",
        seed,
    )


def side_noted_listings(seed: int = 23) -> list[str]:
    """10,000 different synthetic texts, each with a side note that names a made-up place."""
    return _decorated_listings(
        lambda text, rng, _n: f"{text}, {_syllable_name(rng)} Bus Garage open", seed
    )


# Listings as long as real ones and shaped like them: many add a side note after a
# semicolon, a comma or a stop; many name a day, a date or a time, and some name none; some
# give a day's slots ("Wednesday Morning: Closed | Wednesday Afternoon: Closed"); a few are
# sentences, carry an update stamp or join two phrases with a hyphen ("No School-No
# Personnel Report Today"). The lengths follow real listings: a median of about 40
# characters and a 90th percentile of about 107. Every text is generated from these
# patterns and made-up names; none is a real listing.
_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
_WEEKDAY_SHORT = ("Mon", "Tue", "Wed", "Thu", "Fri")
_MONTH_NAMES = ("January", "February", "March", "December")
_MONTH_SHORT = ("Jan.", "Feb.", "Mar.", "Dec.")
_REAL_STATUSES = (
    "Closed", "CLOSED", "Closed", "No School", "2 Hour Delay", "Two Hour Delay", "2-Hour Delay",
    "Delayed 2 Hours", "90 Minute Delay", "Late Start", "Remote Learning", "Virtual Learning Day",
    "NTI Day", "e-Learning Day", "Early Dismissal", "Remote Learning Day", "Closed Today",
    "Opening at {clock} AM", "Delayed Until {clock} AM", "Early Dismissal at {pm} PM",
    "Closing at {pm} PM", "Closed Tomorrow", "Flexible Instruction Day",
)  # fmt: skip
_REAL_NOTES = (
    "No Preschool", "No AM Pre-K", "No PM Activities", "Offices Closed", "Offices Open",
    "No Afternoon Activities", "All Activities Cancelled", "No evening activities",
    "Staff Report at 10", "No Meal Delivery", "Buses on Snow Routes", "No Daycare",
    "Evening Classes Cancelled", "Church Office Closed", "No Personnel Report",
    "Essential Personnel Only", "Workday Optional", "No Before-School Care",
)  # fmt: skip
_REAL_JOINED = (
    "No School-No Personnel Report {day}", "Closed-Flexible Instruction Day",
    "2 Hour Delay-No AM Pre-K", "Closed-Offices Open", "No School-Staff Report at 10",
    "Remote Learning-No In-Person Classes", "CLOSED-NO ACTIVITIES",
)  # fmt: skip
_REAL_SLOT_STATUSES = (
    "Closed", "Closed", "Closed", "2 hour delay", "Remote Learning Day", "No evening activities",
    "Opening At {clock} AM", "Closing At {pm} PM", "Closed, Workday Optional",
    "Closed, no activities, no service", "Services Canceled", "Services Canceled",
    "All activities cancelled", "Youth Activities Canceled", "Online services only",
)  # fmt: skip
# How many slots a listing gives: two for half of them, three for a third.
_REAL_SLOT_COUNTS = (2,) * 10 + (3,) * 7 + (4,) * 2 + (5,)
_REAL_CAUSES = ("due to weather", "due to snow", "due to icy roads", "due to a power outage")
_REAL_SENTENCES = (
    "Closed. School is closed {rel} ({short}, {month_short} {date}) for a snow day. All "
    "practices and activities are canceled.",
    "All schools in {name} County will be non-traditional learning on {short}. {month_short} "
    "{date}, 2026",
    "{name} schools are closed {rel}, {weekday} {month} {date} due to hazardous weather and "
    "driving conditions.",
    "Closed. Out of an abundance of caution we will not be open on {weekday}. Offices open at "
    "{clock} AM.",
    "2 hour delay {rel}. Buses will run on snow routes. No morning kindergarten. Offices open "
    "on time.",
)


# What a status with no day can say instead: who it is for, what runs, what to do.
_REAL_OTHER = (
    "{status} - all locations", "{status}, all campuses", "{status} for students",
    "All classes canceled", "Buses on snow routes", "In person canceled - {status}",
    "{status}. Check email for more information", "{status} - {name} Campus",
    "Schools and offices closed", "{status}; offices open", "All {name} schools {verb}",
)  # fmt: skip
_REAL_VERBS = ("closed", "on a 2 hour delay", "remote", "dismissing early")


def _real_other(rng: random.Random) -> str:
    status = _real_fill(rng.choice(_REAL_STATUSES), rng)
    other = rng.choice(_REAL_OTHER).format(
        status=status, name=_syllable_name(rng), verb=rng.choice(_REAL_VERBS)
    )
    return other[0].upper() + other[1:]


def _real_day(rng: random.Random) -> str:
    """A day as listings name one: a weekday, today or tomorrow, or a date in a few forms."""
    index = rng.randrange(5)
    date = rng.randint(1, 28)
    month = rng.randrange(4)
    return rng.choice(
        (
            _WEEKDAY_NAMES[index],
            _WEEKDAY_NAMES[index],
            _WEEKDAY_SHORT[index],
            "Today",
            "Tomorrow",
            f"{_WEEKDAY_NAMES[index]}, {_MONTH_NAMES[month]} {date}",
            f"{_WEEKDAY_SHORT[index]}, {_MONTH_SHORT[month]} {date}",
            f"{month + 1}/{date}",
            f"{month + 1}/{date}",
            f"{_MONTH_SHORT[month]} {date}",
        )
    )


def _real_fill(template: str, rng: random.Random) -> str:
    index = rng.randrange(5)
    month = rng.randrange(4)
    return template.format(
        clock=f"{rng.choice((9, 10, 11))}:{rng.choice(('00', '15', '30', '45'))}",
        pm=f"{rng.choice((12, 1, 2))}:{rng.choice(('00', '30'))}",
        day=rng.choice(("Today", "Tomorrow", _WEEKDAY_NAMES[index])),
        rel=rng.choice(("today", "tomorrow")),
        weekday=_WEEKDAY_NAMES[index],
        short=_WEEKDAY_SHORT[index],
        month=_MONTH_NAMES[month],
        month_short=_MONTH_SHORT[month],
        date=rng.randint(1, 28),
        name=_syllable_name(rng),
    )


def _real_slots(rng: random.Random) -> str:
    """A day's slots, as some closings pages give them."""
    parts = ("Morning", "Afternoon", "Evening")
    first = rng.randrange(4)
    part = rng.randrange(3)
    slots: list[str] = []
    for step in range(rng.choice(_REAL_SLOT_COUNTS)):
        index = min(first + (part + step) // 3, 4)
        status = _real_fill(rng.choice(_REAL_SLOT_STATUSES), rng)
        slots.append(f"{_WEEKDAY_NAMES[index]} {parts[(part + step) % 3]}: {status}")
    return rng.choice((" | ", "...... ")).join(slots)


def _real_listing(rng: random.Random, shape: str) -> str:  # noqa: PLR0911 - one per shape
    """One synthetic listing of a ``shape`` real listings have (see :data:`_REAL_SHAPES`)."""
    status = _real_fill(rng.choice(_REAL_STATUSES), rng)
    if shape == "alone":  # a status with no day: alone, or with its cause or a word on it
        return rng.choice((status, f"{status} {rng.choice(_REAL_CAUSES)}", _real_other(rng)))
    if shape == "day":  # a status and its day, sometimes with a cause
        joint = " " if rng.random() < 0.8 else " - "
        text = f"{status}{joint}{_real_day(rng)}"
        return f"{text} {rng.choice(_REAL_CAUSES)}" if rng.random() < 0.15 else text
    if shape == "notes":  # a side note or two
        notes = rng.sample(_REAL_NOTES, rng.choice((1, 1, 1, 2)))
        head = f"{status} {_real_day(rng)}" if rng.random() < 0.5 else status
        return rng.choice(("; ", ", ", ". ")).join((head, *notes))
    if shape == "joined":  # two phrases joined by a hyphen, sometimes with the day after
        template = rng.choice(_REAL_JOINED)
        joined = _real_fill(template, rng)
        if "{day}" in template or rng.random() < 0.6:
            return joined
        return f"{joined} {_real_day(rng)}"
    if shape == "slots":
        return _real_slots(rng)
    if shape == "sentence":
        return _real_fill(rng.choice(_REAL_SENTENCES), rng)
    if shape == "stamp":
        day = f"{rng.randint(1, 12)}/{rng.randint(1, 28)}/2025"
        stamp = f"{day} {rng.randint(1, 12)}:{rng.randint(10, 59)}pm"
        return f"{status} {_real_day(rng)} - Last Updated: {stamp}"
    return f"{status}. {_syllable_name(rng)} {rng.choice(('Learning Center', 'Campus'))}"


# How many of the 10,000 different texts take each shape, near the mix of real listings:
# a third add a side note, a quarter name a day, one in six names none, one in eight gives
# a day's slots and one in ten is a sentence or two; a few are joined by a hyphen.
_REAL_SHAPES = {
    "alone": 1600, "day": 2500, "notes": 3300, "joined": 300, "slots": 1300, "sentence": 700,
    "stamp": 150, "place": 150,
}  # fmt: skip


def real_length_listings(seed: int = 29) -> list[str]:
    """10,000 different synthetic texts as long as real listings and shaped like them."""
    rng = random.Random(seed)  # noqa: S311 - synthetic benchmark text, not security
    texts: set[str] = set()
    for shape, count in _REAL_SHAPES.items():
        target = len(texts) + count
        while len(texts) < target:
            texts.add(_real_listing(rng, shape))
    ordered = sorted(texts)
    rng.shuffle(ordered)
    return ordered


def _clear() -> None:
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()


def _clear_words() -> None:
    """Empty the text caches and every cache kept by word: each word is seen for the first time."""
    _forget_words()


PASSES = 5


def best_of_passes(texts: Sequence[str], before: Callable[[], None] = _clear) -> float:
    """The best CPU time, in seconds, of :data:`PASSES` passes of ``parse_status`` on ``texts``."""
    posts = [POSTED + timedelta(minutes=7 * index) for index in range(len(texts))]
    runs: list[float] = []
    for _ in range(PASSES):
        before()
        start = time.process_time()
        for text, posted in zip(texts, posts, strict=True):
            parse_status(text, posted_at=posted, tz=TZ)
        runs.append(time.process_time() - start)
    return min(runs)


def main() -> None:
    parse_status("warm up", posted_at=POSTED, tz=TZ)
    timings = {
        "repeated": best_of_passes(repeated_listings()),
        "distinct": best_of_passes(distinct_listings()),
        "named": best_of_passes(named_listings(), before=_clear_words),
        "dense": best_of_passes(dense_listings()),
        "stamped": best_of_passes(stamped_listings()),
        "numbered": best_of_passes(numbered_listings()),
        "prefixed": best_of_passes(prefixed_listings()),
        "side_noted": best_of_passes(side_noted_listings()),
        "real_length": best_of_passes(real_length_listings()),
    }
    print(json.dumps(timings))  # noqa: T201 - the script's output


if __name__ == "__main__":
    main()

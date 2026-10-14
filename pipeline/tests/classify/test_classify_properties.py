"""Property tests: invariants of every result, and rules that hold for whole families of text."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from snowlight.classify import KINDS, REASONS, ParsedStatus, parse_status
from snowlight.classify import dayparts as dayparts_module
from snowlight.classify import parse as parse_module
from snowlight.classify.dates import MONTHS, WEEKDAYS
from snowlight.classify.model import CONFIDENCE_LEVELS
from snowlight.classify.parse import _cached_analysis, _normalized_analysis

ZONES = (
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Phoenix",
    "America/Los_Angeles",
    "America/Indiana/Indianapolis",
    "America/Kentucky/Louisville",
    "America/Boise",
)
zones = st.sampled_from(ZONES)
instants = st.datetimes(
    min_value=datetime(2015, 1, 1),  # hypothesis adds the zone
    max_value=datetime(2035, 12, 31),
    timezones=st.sampled_from([ZoneInfo(name) for name in ZONES]),
)

STATUS_KIND = {
    "closed": "closed",
    "no school": "closed",
    "classes cancelled": "closed",
    "2 hour delay": "delayed",
    "90 minute delay": "delayed",
    "late start": "delayed",
    "delayed opening": "delayed",
    "early dismissal": "early_dismissal",
    "early release at 1:00": "early_dismissal",
    "nti day": "remote",
    "e-learning day": "remote",
    "remote learning": "remote",
    "virtual learning day": "remote",
    "non-traditional learning day": "remote",
    "ntid": "remote",
    "flexible instruction": "remote",
    "classes online": "remote",
    "no in-person or remote classes": "closed",
    "no day or evening classes": "closed",
    "snow day": "closed",
}
STATUSES = tuple(STATUS_KIND)
# For a status that names no day, in minutes after local midnight: until the first it is
# the posting day's, from the second the next school day's; between them it is unclear.
CUTOFFS = {
    "closed": (12 * 60, 15 * 60),
    "remote": (12 * 60, 15 * 60),
    "delayed": (11 * 60, 11 * 60),
    "early_dismissal": (15 * 60, 15 * 60),
}


def next_school_day(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def undated_day(kind: str, local: datetime) -> date | None:
    """The day a status that names no day applies to, worked out independently of the parser.

    ``None`` when unclear: between the cut-offs, or when that school day is more than a
    day after the posting date (a Friday evening or a Saturday post).
    """
    until, switch = CUTOFFS[kind]
    minutes = local.hour * 60 + local.minute
    today = local.date()
    day: date | None
    if minutes < 4 * 60 or minutes < until:
        day = next_school_day(today)
    elif minutes >= switch:
        day = next_school_day(today + timedelta(days=1))
    else:
        first, second = next_school_day(today), next_school_day(today + timedelta(days=1))
        day = first if first == second else None
    if day is None or (day - today).days > 1:
        return None
    return day


def weekday_ahead(weekday: int, local: datetime) -> date:
    """The day a weekday name alone stands for, worked out independently of the parser.

    Its next occurrence counting the posting day, or counting the day before for a
    post between midnight and 4 a.m. (written the evening before).
    """
    first = local.date() - timedelta(days=1 if local.hour < 4 else 0)
    return first + timedelta(days=(weekday - first.weekday()) % 7)


def just_passed(weekday: int, local: datetime) -> bool:
    """Whether a weekday name alone was a day or two before the posting day.

    Its next occurrence is then 5 or 6 days on: the listing is most likely still up
    after its day ("Closed Monday" seen on a Wednesday), so it states no day.
    """
    return (weekday_ahead(weekday, local) - local.date()).days >= 5


DATES = ("", "today", "tomorrow", "monday", "wednesday", "friday", "jan 21", "1/22")
CAUSES = ("", "due to snow", "due to icy roads", "due to extreme cold", "due to flooding")
HEDGES = (
    "possible",
    "possibly a",
    "may have a",
    "might be a",
    "could be a",
    "potential",
    "likely",
    "tentative",
    "if needed,",
    "if conditions worsen,",
    "should roads ice over,",
    "in the event of snow,",
)
# Hedges and conditions after the status. The first set works after any mark, a sentence
# mark included ("Closed tomorrow. Tentative."), and with none ("closed tomorrow tentative");
# the second after a comma, a dash, "but" or in brackets, and with no mark.
HEDGES_AFTER = (
    "tentative",
    "tbd",
    "possible",
    "pending",
    "not confirmed",
    "to be determined",
    "weather permitting",
    "subject to change",
    "pending road conditions",
    "depending on the forecast",
)
CONDITIONS_AFTER = (
    "if the storm hits",
    "unless roads are cleared",
    "should the storm arrive",
    "if needed",
    "in case of snow",
    "only if roads are icy",
    "assuming the storm arrives",
    "barring a change",
    "provided the forecast holds",
    "as long as roads stay icy",
)
WEAK_MARKS = (", {}", " - {}", " ({})", " but {}", " -- {}")
STRONG_MARKS = (". {}", "; {}", ". {}.")
NOT_SCHOOL = (
    "all activities",
    "evening activities",
    "after school activities",
    "athletics",
    "practices",
    "games",
    "am kindergarten",
    "pm pre-k",
    "preschool",
    "daycare",
    "before and after care",
    "district offices",
    "board meeting",
    "field trips",
)


def check_invariants(result: ParsedStatus) -> None:
    assert result.kind in KINDS
    assert result.confidence in CONFIDENCE_LEVELS
    assert 0.0 <= result.confidence <= 1.0
    if result.kind == "other":
        assert result.dates == ()
        assert result.schedule == ()
        assert result.delay_minutes is None
        assert result.dismissal_time is None
        assert result.confidence <= 0.9
    else:
        assert result.dates
        primary = [entry for entry in result.schedule if entry.dates == result.dates]
        assert primary
        assert primary[0].kind == result.kind
        assert not result.says_open
    seen: set[date] = set()
    for entry in result.schedule:
        assert entry.dates
        assert list(entry.dates) == sorted(set(entry.dates))
        assert seen.isdisjoint(entry.dates)
        seen.update(entry.dates)
        if entry.delay_minutes is not None:
            assert 10 <= entry.delay_minutes <= 300
        if entry.opens_at is not None:
            assert time(6) <= entry.opens_at <= time(13)
        if entry.dismissal_time is not None:
            assert time(8) <= entry.dismissal_time <= time(16, 30)
    assert (result.reason is None) == (result.reasons == ())
    if result.reason is not None:
        assert result.reason == result.reasons[0]
        assert set(result.reasons) <= set(REASONS)
    assert result.names_weather == bool(result.weather_terms)
    assert list(result.notes) == sorted(set(result.notes))


@settings(max_examples=400, deadline=None)
@given(text=st.text(max_size=240), posted=instants, tz=zones)
def test_any_text_gives_a_valid_result(text: str, posted: datetime, tz: str) -> None:
    check_invariants(parse_status(text, posted_at=posted, tz=tz))


phrases = st.builds(
    lambda status, day, cause, extra: " ".join(p for p in (status, day, cause, extra) if p),
    st.sampled_from(STATUSES),
    st.sampled_from(DATES),
    st.sampled_from(CAUSES),
    st.sampled_from(("", "; offices open", ", buses on snow routes", "; all activities cancelled")),
)


@settings(max_examples=300, deadline=None)
@given(text=phrases, posted=instants, tz=zones)
def test_realistic_text_gives_a_valid_status(text: str, posted: datetime, tz: str) -> None:
    result = parse_status(text, posted_at=posted, tz=tz)
    check_invariants(result)
    local = posted.astimezone(ZoneInfo(tz))
    named = [WEEKDAYS[word] for word in text.split() if word in WEEKDAYS]
    if named and just_passed(named[0], local):
        # A weekday that was a day or two ago, whose next occurrence is 5 or 6 days on.
        assert result.kind == "other"
        assert "unreadable_date" in result.notes
        assert result.confidence == 0.3
    elif result.kind == "other":
        # Only a status that names no day, first seen from noon to 3 p.m. (a closure or
        # remote day) or when the next school day is days away (Friday or Saturday).
        assert "undated" in result.notes
        assert result.confidence == 0.3
        assert 12 <= local.hour < 15 or local.weekday() in {4, 5}


@settings(max_examples=300, deadline=None)
@given(text=phrases, posted=instants, tz=zones)
def test_deterministic_and_cache_independent(text: str, posted: datetime, tz: str) -> None:
    first = parse_status(text, posted_at=posted, tz=tz)
    assert parse_status(text, posted_at=posted, tz=tz) == first
    _cached_analysis.cache_clear()
    _normalized_analysis.cache_clear()
    assert parse_status(text, posted_at=posted, tz=tz) == first


@settings(max_examples=200, deadline=None)
@given(text=phrases, posted=instants, tz=zones, spaces=st.integers(1, 4))
def test_case_and_spacing_do_not_matter(text: str, posted: datetime, tz: str, spaces: int) -> None:
    result = parse_status(text, posted_at=posted, tz=tz)
    assert parse_status(text.upper(), posted_at=posted, tz=tz) == result
    assert parse_status(text.title(), posted_at=posted, tz=tz) == result
    padded = (" " * spaces).join(text.split())
    assert parse_status(f"  {padded}\t", posted_at=posted, tz=tz) == result


@settings(max_examples=300, deadline=None)
@given(
    hedge=st.sampled_from(HEDGES),
    status=st.sampled_from(STATUSES),
    day=st.sampled_from(DATES),
    posted=instants,
    tz=zones,
)
def test_a_hedged_status_is_never_stated(
    hedge: str, status: str, day: str, posted: datetime, tz: str
) -> None:
    result = parse_status(f"{hedge} {status} {day}", posted_at=posted, tz=tz)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@settings(max_examples=200, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    tail=st.sampled_from(("possible", "likely", "expected", "is possible", "may be needed")),
    posted=instants,
    tz=zones,
)
def test_a_status_followed_by_a_hedge_is_never_stated(
    status: str, tail: str, posted: datetime, tz: str
) -> None:
    result = parse_status(f"{status} {tail}", posted_at=posted, tz=tz)
    assert result.kind == "other"


hedged_after = st.one_of(
    st.builds(
        lambda hedge, mark: mark.format(hedge),
        st.sampled_from(HEDGES_AFTER),
        st.sampled_from((*WEAK_MARKS, *STRONG_MARKS)),
    ),
    st.builds(
        lambda condition, mark: mark.format(condition),
        st.sampled_from(CONDITIONS_AFTER),
        st.sampled_from(WEAK_MARKS),
    ),
)


@settings(max_examples=400, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    day=st.sampled_from(DATES),
    cause=st.sampled_from(CAUSES),
    tail=hedged_after,
    posted=instants,
    tz=zones,
)
def test_a_hedge_or_condition_after_the_status_is_never_stated(  # noqa: PLR0913, PLR0917
    status: str, day: str, cause: str, tail: str, posted: datetime, tz: str
) -> None:
    text = " ".join(part for part in (status, day, cause) if part) + tail
    result = parse_status(text, posted_at=posted, tz=tz)
    check_invariants(result)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    day=st.sampled_from(DATES),
    tail=st.sampled_from((*HEDGES_AFTER, *CONDITIONS_AFTER)),
    posted=instants,
    tz=zones,
)
def test_a_hedge_or_condition_right_after_the_status_is_never_stated(
    status: str, day: str, tail: str, posted: datetime, tz: str
) -> None:
    text = " ".join(part for part in (status, day, tail) if part)
    result = parse_status(text, posted_at=posted, tz=tz)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@settings(max_examples=300, deadline=None)
@given(
    status=st.sampled_from(STATUSES),
    day=st.sampled_from(("today", "tomorrow", "jan 21", "1/22")),
    tail=st.sampled_from(
        (
            ", possibly longer",
            ", more snow expected",
            ", heavy snow possible",
            " even if the snow stops",
            ", whether or not it snows",
            " unless otherwise noted",
            ", if you have questions call the office",
            ". If conditions improve we will reopen.",
            " (confirmed)",
            ", students should check email",
        )
    ),
    posted=instants,
    tz=zones,
)
def test_a_hedge_about_something_else_leaves_a_dated_status(
    status: str, day: str, tail: str, posted: datetime, tz: str
) -> None:
    plain = parse_status(f"{status} {day}", posted_at=posted, tz=tz)
    result = parse_status(f"{status} {day}{tail}", posted_at=posted, tz=tz)
    check_invariants(result)
    assert result.kind == plain.kind
    assert result.dates == plain.dates


@settings(max_examples=300, deadline=None)
@given(
    subject=st.sampled_from(NOT_SCHOOL),
    verb=st.sampled_from(("cancelled", "canceled", "postponed", "closed", "called off")),
    day=st.sampled_from(DATES),
    posted=instants,
    tz=zones,
)
def test_other_things_cancelled_is_never_a_closure(
    subject: str, verb: str, day: str, posted: datetime, tz: str
) -> None:
    result = parse_status(f"{subject} {verb} {day}", posted_at=posted, tz=tz)
    assert result.kind == "other"
    assert result.notes


@settings(max_examples=100, deadline=None)
@given(
    word=st.sampled_from(("cancelled", "canceled", "closing", "closings", "inclement weather")),
    cause=st.sampled_from(CAUSES),
    posted=instants,
    tz=zones,
)
def test_an_ambiguous_word_is_never_a_closure(
    word: str, cause: str, posted: datetime, tz: str
) -> None:
    result = parse_status(f"{word} {cause}", posted_at=posted, tz=tz)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@settings(max_examples=200, deadline=None)
@given(
    hours=st.integers(1, 5),
    style=st.sampled_from(("{} hour delay", "{}-hour delay", "{}hr delay", "delayed {} hours")),
)
def test_delay_in_hours(hours: int, style: str) -> None:
    posted = datetime(2026, 1, 20, 5, 30, tzinfo=ZoneInfo("America/New_York"))
    result = parse_status(style.format(hours), posted_at=posted, tz="America/New_York")
    assert result.kind == "delayed"
    assert result.delay_minutes == hours * 60


@settings(max_examples=200, deadline=None)
@given(
    minutes=st.integers(10, 300),
    style=st.sampled_from(("{} minute delay", "{}-min delay", "delay of {} minutes")),
)
def test_delay_in_minutes(minutes: int, style: str) -> None:
    posted = datetime(2026, 1, 20, 5, 30, tzinfo=ZoneInfo("America/New_York"))
    result = parse_status(style.format(minutes), posted_at=posted, tz="America/New_York")
    assert result.kind == "delayed"
    assert result.delay_minutes == minutes


@settings(max_examples=200, deadline=None)
@given(hour=st.integers(8, 16), minute=st.sampled_from((0, 15, 30, 45)))
def test_dismissal_clock_times(hour: int, minute: int) -> None:
    clock = time(hour, minute)
    if clock > time(16, 30):
        return
    text = f"early dismissal at {clock.strftime('%I:%M %p').lstrip('0')}"
    posted = datetime(2026, 1, 20, 5, 30, tzinfo=ZoneInfo("America/Chicago"))
    result = parse_status(text, posted_at=posted, tz="America/Chicago")
    assert result.kind == "early_dismissal"
    assert result.dismissal_time == clock


WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday")


@settings(max_examples=300, deadline=None)
@given(weekday=st.integers(0, 4), posted=instants, tz=zones)
def test_weekday_names_land_in_the_coming_days(weekday: int, posted: datetime, tz: str) -> None:
    result = parse_status(f"closed {WEEKDAY_NAMES[weekday]}", posted_at=posted, tz=tz)
    local = posted.astimezone(ZoneInfo(tz))
    if just_passed(weekday, local):
        # "Closed Monday" seen on a Tuesday evening or a Wednesday: Monday just past, most
        # likely, or the next one; neither is stated.
        assert result.kind == "other"
        assert result.notes == ("unreadable_date",)
        assert result.confidence == 0.3
        return
    (day,) = result.dates
    assert day == weekday_ahead(weekday, local)
    assert (day - local.date()).days <= 4  # (from the day before, overnight)


@settings(max_examples=300, deadline=None)
@given(
    first=st.integers(0, 4),
    later=st.sampled_from(("Open on time", "Normal schedule", "No Evening Activities", "Open")),
    part=st.sampled_from(("", " Morning", " Evening")),
    posted=instants,
    tz=zones,
)
def test_a_day_heading_keeps_the_days_before_it_in_order(
    first: int, later: str, part: str, posted: datetime, tz: str
) -> None:
    # "Wednesday: Closed...... Thursday: Open on time": the heading's day comes after the
    # closure's, whatever its slot says, so the closure is never a week on from it.
    second = (first + 1) % 5
    text = f"{WEEKDAY_NAMES[first]}: Closed...... {WEEKDAY_NAMES[second]}{part}: {later}"
    result = parse_status(text, posted_at=posted, tz=tz)
    local = posted.astimezone(ZoneInfo(tz))
    heading = weekday_ahead(second, local)
    closure = heading - timedelta(days=(second - first) % 7)  # the day before, or Friday
    if (closure - local.date()).days >= 4 and (heading - local.date()).days >= 5:
        # Both days a week on, or just past ("Monday: Closed...... Tuesday: Open" seen on a
        # Thursday): most likely the days just past, so neither is stated.
        assert result.kind == "other"
        assert result.confidence == 0.3
        assert "unreadable_date" in result.notes
        return
    reference = local.date() - timedelta(days=1 if local.hour < 4 else 0)  # (overnight)
    if later != "No Evening Activities" and closure < reference:
        # The closure just past, and the posting day open: the news is that school is open.
        assert result.kind == "other"
        assert result.says_open
        assert "superseded" in result.notes
        return
    assert result.kind == "closed"
    assert result.dates == (closure,)


@settings(max_examples=300, deadline=None)
@given(posted=instants, tz=zones)
def test_today_and_tomorrow_follow_the_local_date(posted: datetime, tz: str) -> None:
    local = posted.astimezone(ZoneInfo(tz))
    assert parse_status("closed today", posted_at=posted, tz=tz).dates == (local.date(),)
    tomorrow = parse_status("closed tomorrow", posted_at=posted, tz=tz).dates
    # After midnight "tomorrow" is the day that has begun, except early on a Sunday, which
    # holds no school: then it is the Monday.
    overnight = local.hour < 4 and local.weekday() != 6
    expected = local.date() + timedelta(days=0 if overnight else 1)
    assert tomorrow == (expected,)


@settings(max_examples=300, deadline=None)
@given(status=st.sampled_from(STATUSES), posted=instants, tz=zones)
def test_an_undated_status_lands_on_the_next_school_day(
    status: str, posted: datetime, tz: str
) -> None:
    result = parse_status(status, posted_at=posted, tz=tz)
    local = posted.astimezone(ZoneInfo(tz))
    expected = undated_day(STATUS_KIND[status], local)
    if expected is None:
        assert result.kind == "other"
        assert "undated" in result.notes
        assert result.confidence <= 0.3
        return
    (day,) = result.dates
    assert day == expected
    assert day.weekday() < 5
    assert local.date() <= day <= local.date() + timedelta(days=1)
    assert result.dates_stated is False


def _both_paths(text: str, posted: datetime, tz: str) -> tuple[ParsedStatus, ParsedStatus]:
    """Parse ``text`` with the shortcuts on and off, from cold caches.

    The shortcuts: a lone status read without settling, a text with no scope noun,
    qualifying word or condition settled without them, a status's days resolved
    once per text, a lone mention's dates taken directly, a plain closure put in
    as it is, and the most common bounds of a closure (see dayparts.FAST_PATH).
    """
    results: list[ParsedStatus] = []
    for fast in (True, False):
        parse_module._FAST_PATH = fast
        dayparts_module.FAST_PATH = fast
        _cached_analysis.cache_clear()
        _normalized_analysis.cache_clear()
        try:
            results.append(parse_status(text, posted_at=posted, tz=tz))
        finally:
            parse_module._FAST_PATH = True
            dayparts_module.FAST_PATH = True
    return results[0], results[1]


shortcut_texts = st.one_of(
    phrases,
    st.builds(
        " ".join,
        st.lists(
            st.sampled_from(
                [*STATUSES, *DATES, *CAUSES, *HEDGES, *HEDGES_AFTER, *CONDITIONS_AFTER, "no",
                 "not", "for", "staff", "offices", "students", "evening", "am", "due", "will",
                 "?", ";", ",", "-", "(", ")", "was", "now", "when", "weather", "permitting"]
            ),
            min_size=1,
            max_size=7,
        ),
    ),
)  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(text=shortcut_texts, posted=instants, tz=zones)
def test_the_plain_text_shortcut_changes_nothing(text: str, posted: datetime, tz: str) -> None:
    fast, full = _both_paths(text, posted, tz)
    assert fast == full


@pytest.mark.parametrize(
    "text", ["for tbd", "date tba", "the 21th", "school year 2019", "Concert date TBD"]
)
def test_a_text_with_no_status_reads_its_odd_days_alike_on_both_paths(text: str) -> None:
    # A placeholder day, a misread ordinal or a year alone, with no status: the shortcut for
    # a text with no status reads none of them, and the full path reads them alike.
    posted = datetime(2026, 1, 21, 6, 0, tzinfo=ZoneInfo("America/Chicago"))
    fast, full = _both_paths(text, posted, "America/Chicago")
    assert fast == full


# A closings page's day slots ("Tuesday Morning: Closed | Tuesday Afternoon: Closed"), each
# with a status, a side note or a field answer, as the shortcuts for several statuses meet
# them: days named again, a morning, an afternoon and an evening, a weekend, bounds after the
# closure, a field left blank, and a "no" that covers a list.
SLOT_DAYS = ("monday", "tuesday", "friday", "saturday", "sunday", "tomorrow")
SLOT_PARTS = ("morning", "afternoon", "evening", "am", "")
SLOT_BODIES = (
    "closed", "closed", "remote learning day", "2 hour delay", "opening at 10:00 am",
    "closing at 1:00 pm", "early dismissal", "no evening activities", "all events canceled",
    "closed-flexible instruction day", "closed, offices open", "delay: --", "closed: no",
    "0 hour delay or early release", "closed after 11:30", "closed pm", "open", "snow day",
    "nti day", "services canceled", "closed through friday", "closed this afternoon",
    "on time", "regular schedule", "2 hour delay cancelled", "delay lifted", "delay: --, or closed",
)  # fmt: skip
slot_texts = st.lists(
    st.tuples(
        st.sampled_from(SLOT_DAYS), st.sampled_from(SLOT_PARTS), st.sampled_from(SLOT_BODIES)
    ),
    min_size=2,
    max_size=4,
).flatmap(
    lambda entries: st.sampled_from((" | ", "...... ", "; ", ". ")).map(
        lambda mark: mark.join(
            f"{day} {part}: {body}" if part else f"{day}: {body}" for day, part, body in entries
        )
    )
)
# A status with its day and side notes after it ("Closed Monday; No Preschool, Offices Open").
NOTES = (
    "no preschool", "offices open", "staff report at 10", "no am pre-k", "workday optional",
    "buses on snow routes", "all activities cancelled", "no daycare", "delay: --",
    "remote learning", "2 hour delay", "closed", "0 hour delay or early release",
    "on time tomorrow", "regular schedule tuesday", "delay lifted", "2 hour delay cancelled",
    "business as usual",
)  # fmt: skip
noted_texts = st.builds(
    lambda status, day, notes, mark: mark.join([f"{status} {day}".strip(), *notes]),
    st.sampled_from(STATUSES),
    st.sampled_from(DATES),
    st.lists(st.sampled_from(NOTES), min_size=1, max_size=3),
    st.sampled_from(("; ", ", ", ". ", " - ")),
)


@settings(max_examples=400, deadline=None)
@given(text=st.one_of(slot_texts, noted_texts), posted=instants, tz=zones)
def test_the_shortcuts_for_several_statuses_change_nothing(
    text: str, posted: datetime, tz: str
) -> None:
    fast, full = _both_paths(text, posted, tz)
    assert fast == full


def _switched(
    switch: str, text: str, posted: datetime, tz: str, before: tuple[str, ...] = ()
) -> tuple[ParsedStatus, ParsedStatus]:
    """Parse ``text`` with one of the parser's shortcuts on and off, from cold caches.

    With the shortcut on, the texts ``before`` are parsed first: what they leave
    kept (an analysis that stands for texts that differ from them only in a day
    number) is there for ``text`` to share.
    """
    results: list[ParsedStatus] = []
    for on in (True, False):
        setattr(parse_module, switch, on)
        _cached_analysis.cache_clear()
        _normalized_analysis.cache_clear()
        try:
            for other in before if on else ():
                parse_status(other, posted_at=posted, tz=tz)
            results.append(parse_status(text, posted_at=posted, tz=tz))
        finally:
            setattr(parse_module, switch, True)
    return results[0], results[1]


DAY_FORMS = (
    "jan {d}", "Jan. {d}", "January {d}", "1/{d}", "01/{d}", "12/{d}", "Wednesday, Jan. {d}",
    "jan {d}-{e}", "1/{d} and 1/{e}", "{d} jan", "jan {d}, 2026", "1/{d}/26", "the {d}th",
    "jan {d} at 10", "1/{d} 2 hour", "jan {d}.", "1/{d};", "jan {d} - ", "jan {d} due to snow",
)  # fmt: skip
days = st.integers(1, 35) | st.sampled_from((5, 15, 5, 15))  # (5 and 15: the fixed numbers)
# A text with day numbers, and the same text with other day numbers.
day_texts = st.builds(
    lambda status, form, numbers, tail: tuple(
        f"{status} {form.format(d=d, e=e)} {tail}".strip() for d, e in numbers
    ),
    st.sampled_from(STATUSES),
    st.sampled_from(DAY_FORMS),
    st.tuples(st.tuples(days, days), st.tuples(days, days)),
    st.sampled_from(["", *CAUSES, "; offices open", ", then 2 hour delay jan 23", "or 22", "?"]),
)


@settings(max_examples=400, deadline=None)
@given(
    texts=st.one_of(day_texts, shortcut_texts.map(lambda text: (text, text))),
    posted=instants,
    tz=zones,
)
def test_sharing_an_analysis_across_day_numbers_changes_nothing(
    texts: tuple[str, str], posted: datetime, tz: str
) -> None:
    # The text shares what its sibling, the same but for its day numbers, left kept.
    text, sibling = texts
    shared, direct = _switched("_TEMPLATE", text, posted, tz, before=(sibling,))
    assert shared == direct


# Weekday and month names in every form the parser reads, and where they can stand: alone,
# with marks, inside a word, beside a day number, one of each or two of a kind.
ANY_WEEKDAY = tuple(WEEKDAYS)
ANY_MONTH = tuple(MONTHS)
NAME_FORMS = (
    "{w}", "{w},", "{w}.", "{w};", "{w}:", "({w})", "{w}'s", "{w} {m} {d}", "{w}, {m}. {d}",
    "{m} {d}", "{m}. {d}-{e}", "{w} the {d}th", "this {w}", "{w} and {m} {d}", "{w}-{m} {d}",
    "{d}-{m}", "closed-{w}", "{w}/{m}", "{w} 1/{d}", "{m} {d} through {w}", "through {w}",
    "{w} and {w}", "{m} {d} and {m} {e}", "{w} {d} {m}", "{m} {d}, 2026", "mid-{m}",
)  # fmt: skip
name_days = st.integers(1, 31)
# A text with weekday and month names, and the same text with other names.
name_texts = st.builds(
    lambda status, form, names, numbers, tail: tuple(
        f"{status} {form.format(w=w, m=m, d=numbers[0], e=numbers[1])} {tail}".strip()
        for w, m in names
    ),
    st.sampled_from(STATUSES),
    st.sampled_from(NAME_FORMS),
    st.tuples(
        st.tuples(st.sampled_from(ANY_WEEKDAY), st.sampled_from(ANY_MONTH)),
        st.tuples(st.sampled_from(ANY_WEEKDAY), st.sampled_from(ANY_MONTH)),
    ),
    st.tuples(name_days, name_days),
    st.sampled_from(["", *CAUSES, "; offices open", ", 2 hour delay friday", "or monday", "?"]),
)


@settings(max_examples=400, deadline=None)
@given(texts=name_texts, posted=instants, tz=zones)
def test_sharing_an_analysis_across_weekday_and_month_names_changes_nothing(
    texts: tuple[str, str], posted: datetime, tz: str
) -> None:
    # The text, after its sibling (the same but for its names), reads as it does from cold
    # caches with no analysis shared.
    text, sibling = texts
    shared, direct = _switched("_TEMPLATE", text, posted, tz, before=(sibling,))
    assert shared == direct

"""Less common paths: scope after a status, hedges inside causes, bare-date clauses, conflicts.

The texts are phrasing patterns written for these tests, not real listings. All
are posted at 5:30 a.m. on Tuesday 20 January 2026 in New York.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from snowlight.classify import parse_status
from snowlight.classify.mentions import find_mentions
from snowlight.classify.text import normalize

TZ = "America/New_York"
POSTED = datetime(2026, 1, 20, 5, 30, tzinfo=ZoneInfo(TZ))


def jan(*days: int) -> tuple[date, ...]:
    return tuple(date(2026, 1, day) for day in days)


def parse(text: str) -> tuple[str, tuple[tuple[str, tuple[date, ...]], ...]]:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    return result.kind, tuple((entry.kind, entry.dates) for entry in result.schedule)


@pytest.mark.parametrize(
    ("text", "note"),
    [
        ("Closed for high school students", "partial_program"),
        ("Cancelled for evening classes", "activities_cancelled"),
        ("No school for AM kindergarten", "partial_program"),
        ("2 hour delay for middle school", "partial_program"),
        ("E-learning for staff", "staff"),
    ],
)
def test_the_noun_after_a_status_decides_who_it_is_about(text: str, note: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.kind == "other"
    assert note in result.notes


def test_a_hedge_word_inside_the_cause_does_not_hedge_the_status() -> None:
    assert parse("Closed due to possible flooding") == ("closed", (("closed", jan(20)),))
    assert parse("Closed because of potential icing today")[0] == "closed"
    assert parse("Because of possible icing school is closed today")[0] == "closed"


def test_prefix_dates_with_two_statuses_in_one_clause() -> None:
    assert parse("Today closed and tomorrow delayed") == (
        "closed",
        (("closed", jan(20)), ("delayed", jan(21))),
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A clause of bare dates attaches to the status after it, or before it.
        ("Update - Tuesday - Closed", ("closed", (("closed", jan(20)),))),
        ("Closed. Wednesday.", ("closed", (("closed", jan(21)),))),
        ("Closed - Wednesday and Thursday", ("closed", (("closed", jan(21, 22)),))),
        # Nothing to attach to: the dates are left alone.
        (
            "Closed today. All activities cancelled. Friday.",
            ("closed", (("closed", jan(20)),)),
        ),
        # Only hedged dates: they state nothing.
        ("Closed today. Maybe tomorrow.", ("closed", (("closed", jan(20)),))),
    ],
)
def test_clauses_of_bare_dates(
    text: str, expected: tuple[str, tuple[tuple[str, tuple[date, ...]], ...]]
) -> None:
    assert parse(text) == expected


def test_an_impossible_date_drops_only_its_own_status() -> None:
    assert parse("Closed Feb 30; 2 hour delay tomorrow") == (
        "delayed",
        (("delayed", jan(21)),),
    )


def test_until_further_notice_alongside_another_status() -> None:
    result = parse_status(
        "NTI day Wednesday. Closed today until further notice.", posted_at=POSTED, tz=TZ
    )
    closed = result.on(date(2026, 1, 20))
    remote = result.on(date(2026, 1, 21))
    assert closed is not None
    assert closed.kind == "closed"
    assert closed.until_further_notice
    assert remote is not None
    assert remote.kind == "remote"
    assert not remote.until_further_notice


def test_a_conflict_on_one_day_lowers_the_confidence_of_the_rest() -> None:
    result = parse_status(
        "Closed today. 2 hour delay today. Closed tomorrow.", posted_at=POSTED, tz=TZ
    )
    assert result.kind == "closed"
    assert result.dates == jan(21)
    assert result.on(date(2026, 1, 20)) is None
    assert "conflict" in result.notes
    assert result.confidence <= 0.7


@pytest.mark.parametrize("text", ["Not open", "Open if roads are clear"])
def test_a_negated_or_hedged_open_is_not_open(text: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.kind == "other"
    assert result.says_open is False


@pytest.mark.parametrize(
    "text",
    [
        "Buses leave 2:30",  # a clock after "leave" without "at" is not a dismissal
        "Regular 3:10 dismissal",
        "Normal dismissal at 3:10",
    ],
)
def test_times_that_are_not_early_dismissals(text: str) -> None:
    assert parse_status(text, posted_at=POSTED, tz=TZ).kind == "other"


def test_details_found_after_the_date() -> None:
    early = parse_status("Early dismissal Tuesday - 2 hours early", posted_at=POSTED, tz=TZ)
    assert early.kind == "early_dismissal"
    assert early.dismissal_early_minutes == 120
    two_openings = parse_status(
        "Delayed opening: 10:00 elementary, 10:30 secondary", posted_at=POSTED, tz=TZ
    )
    assert two_openings.kind == "delayed"
    assert two_openings.opens_at is None
    one_opening = parse_status("Delayed opening Tuesday at 10:30", posted_at=POSTED, tz=TZ)
    assert one_opening.opens_at == time(10, 30)


def test_find_mentions_works_without_a_vocabulary() -> None:
    mentions = find_mentions(normalize("2 Hour Delay; all activities cancelled"))
    # "cancelled" stays ambiguous until settling finds the noun it is about.
    assert [mention.kind for mention in mentions] == ["delayed", "ambiguous"]
    assert find_mentions("") == []


def test_weekday_lists_before_a_later_weekday_stay_in_text_order() -> None:
    wednesday = datetime(2026, 1, 21, 5, 30, tzinfo=ZoneInfo(TZ))
    result = parse_status("Closed Monday and Tuesday; NTI Wednesday", posted_at=wednesday, tz=TZ)
    assert [(entry.kind, entry.dates) for entry in result.schedule] == [
        ("closed", jan(19, 20)),
        ("remote", jan(21)),
    ]


@pytest.mark.parametrize(
    ("text", "kind", "note"),
    [
        ("Inclement Weather Closing", "closed", None),
        ("Early release Wednesdays", "other", "recurring"),
        ("Late start every Wednesday", "other", "recurring"),
        ("Closed: high school", "other", "partial_program"),
    ],
)
def test_vendor_wordings(text: str, kind: str, note: str | None) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.kind == kind
    if note is not None:
        assert note in result.notes


def test_times_listed_by_level_keep_the_status_but_no_single_time() -> None:
    result = parse_status(
        "Early dismissal: Elementary 1:15, Middle 1:45, High 2:15", posted_at=POSTED, tz=TZ
    )
    assert result.kind == "early_dismissal"
    assert result.dismissal_time is None
    assert "partial_program" not in result.notes


def test_offices_opening_late_is_not_offices_closed() -> None:
    result = parse_status("Closed today. Offices will open at 10.", posted_at=POSTED, tz=TZ)
    assert result.kind == "closed"
    assert "offices_closed" not in result.notes
    assert result.offices_open is False


@pytest.mark.parametrize(
    "text",
    [
        "Closed?",
        "Snow day tomorrow? Decision by 5 AM",
        "Closed today? No.",
        "Closing early is being considered",
    ],
)
def test_questions_and_deliberations_are_not_statements(text: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.kind == "other"
    assert result.confidence <= 0.3


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Open house cancelled", "other"),
        ("Open gym cancelled tonight", "other"),
        ("Many roads closed; school on 2 hour delay", "delayed"),
        ("Bridge closed - 2 hour delay", "delayed"),
    ],
)
def test_open_house_and_closed_roads_say_nothing_about_the_school(text: str, kind: str) -> None:
    result = parse_status(text, posted_at=POSTED, tz=TZ)
    assert result.kind == kind
    assert result.says_open is False


def test_a_status_for_part_of_the_district_leaves_no_school_wide_one() -> None:
    # Grades 6-12 learn remotely while the rest is closed: the district has no one status.
    result = parse_status(
        "District closed; virtual learning for grades 6-12", posted_at=POSTED, tz=TZ
    )
    assert result.kind == "other"
    assert "partial_program" in result.notes
    assert result.dates == ()


@pytest.mark.parametrize(
    ("text", "expected", "offices_open"),
    [
        # " however" and " but " part clauses as a spaced dash does; a mark inside a date
        # parts none ("Jan. 21, 2026").
        ("Closed today, however offices open", ("closed", (("closed", jan(20)),)), True),
        ("Closed today however offices are open", ("closed", (("closed", jan(20)),)), True),
        ("Closed however", ("closed", (("closed", jan(20)),)), False),
        ("2 hour delay, however buses on snow routes", ("delayed", (("delayed", jan(20)),)), False),
        ("Closed today but open tomorrow", ("closed", (("closed", jan(20)),)), False),
        ("closed but", ("closed", (("closed", jan(20)),)), False),
        ("but closed today", ("closed", (("closed", jan(20)),)), False),
        ("Closed but - open tomorrow", ("other", ()), False),
        ("- Closed today", ("closed", (("closed", jan(20)),)), False),
        ("Closed - - open", ("closed", (("closed", jan(20)),)), False),
        ("Closed; - offices open", ("closed", (("closed", jan(20)),)), True),
        ("-", ("other", ()), False),
        ("--", ("other", ()), False),
        ("Closed Jan. 21, 2026", ("closed", (("closed", jan(21)),)), False),
        ("Closed Wednesday, Jan. 21, due to snow", ("closed", (("closed", jan(21)),)), False),
    ],
)
def test_clause_marks(
    text: str, expected: tuple[str, tuple[tuple[str, tuple[date, ...]], ...]], offices_open: bool
) -> None:
    assert parse(text) == expected
    assert parse_status(text, posted_at=POSTED, tz=TZ).offices_open is offices_open

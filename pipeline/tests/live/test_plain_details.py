"""Plain details (snowlight.live.details): read only from words that state them, carried beside
a lit status through merge, closings.json, the day timelines and status pushes, and never
changing a status, a time or a light. Every row here is SYNTHETIC."""

import json
from datetime import date
from pathlib import Path

import pytest

from live.world import ALPHA_SCHOOL, World, at, row, station
from snowlight.live.details import (
    FOR_STATUS,
    GROUP,
    agreed,
    clauses,
    names_days,
    read_details,
    row_details,
)
from snowlight.live.history import Change, Event, Shown, seed_changes, timeline
from snowlight.live.resolve import Derived
from snowlight.notify.rules import Shown as PushShown
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import Closing, ClosingsDay, ClosingsFile, DayTimeline
from snowlight.schemas.vocab import DETAIL_BY_CODE, Detail, Status

D = Detail
A = "gray-synthetic"
B = "nexstar-synthetic"

# --- reading the words ---------------------------------------------------------------------

STATES: list[tuple[str, tuple[Detail, ...]]] = [
    ("Closed Thursday. Closed for all staff and students", (D.STUDENTS_AND_STAFF,)),
    ("School closed | Staff & students", (D.STUDENTS_AND_STAFF,)),
    ("Schools closed Friday; staff report", (D.STAFF_REPORT,)),
    ("CLOSED FRIDAY - ALL EMPLOYEES TO REPORT", (D.STAFF_REPORT,)),
    ("E-learning day. Staff should report", (D.STAFF_REPORT,)),
    ("Delayed 3 hours. Staff report three hours late", (D.STAFF_LATE,)),
    ("3 hour delay | Buses run on snow routes", (D.BUSES_SNOW_ROUTES,)),
    ("Three Hours Late. Snow routes in effect", (D.BUSES_SNOW_ROUTES,)),
    ("Late start. All buses will be using snow routes", (D.BUSES_SNOW_ROUTES,)),
    ("3 hour delay; emergency routes", (D.BUSES_EMERGENCY_ROUTES,)),
    ("Delayed. Buses travel hard-surfaced roads only", (D.BUSES_PAVED_ROADS,)),
    ("3 hr delay, paved routes only", (D.BUSES_PAVED_ROADS,)),
    ("3 hr delay; Limited transportation", (D.BUSES_LIMITED,)),
    ("Late start. No buses today", (D.NO_BUSES,)),
    ("Remote learning day | No bussing", (D.NO_BUSES,)),
    ("Delayed start, buses are not running", (D.NO_BUSES,)),
    ("3 Hr Delay; No breakfast program", (D.NO_BREAKFAST,)),
    ("Delayed 1 hour; breakfast won't be served", (D.NO_BREAKFAST,)),
    ("Dismissing early. Lunch will not be provided", (D.NO_LUNCH,)),
    ("Early release at 11:30 AM | No hot lunch service", (D.NO_HOT_LUNCH,)),
    ("Virtual learning day. Grab & go lunches provided", (D.GRAB_AND_GO,)),
    ("3 Hr Delay | No morning preschool classes", (D.NO_AM_PREK,)),
    ("Late start; AM Pre-K is cancelled", (D.NO_AM_PREK,)),
    ("Early release | Afternoon pre-K cancelled", (D.NO_PM_PREK,)),
    ("3 hr delay. No a.m./p.m. 4K", (D.NO_PREK,)),
    ("3 hr delay. No PM pre-K; no morning pre-K", (D.NO_PREK,)),
    ("3 hr delay | Pre-kindergarten closed", (D.NO_PREK,)),
    ("School closed. Extracurricular activities have been cancelled", (D.ACTIVITIES_CANCELLED,)),
    ("Delayed-Activities Called Off", (D.ACTIVITIES_CANCELLED,)),
    ("Closed Thursday | No afternoon sports", (D.AFTER_SCHOOL_CANCELLED,)),
    ("Closed | After school athletics canceled", (D.AFTER_SCHOOL_CANCELLED,)),
    ("Early dismissal. Night events cancelled tonight", (D.EVENING_CANCELLED,)),
    ("Closed. No before and after school care", (D.CHILDCARE_CLOSED,)),
    ("Schools closed; latchkey is closed", (D.CHILDCARE_CLOSED,)),
    ("Closed | Extended day open as usual", (D.CHILDCARE_OPEN,)),
    ("Closed Thursday; Central office will be closed", (D.OFFICES_CLOSED,)),
    ("All campuses and offices closed", (D.OFFICES_CLOSED,)),
    ("Classes cancelled. Admin offices open", (D.OFFICES_OPEN,)),
    (
        "3 hour delay | No breakfast | Buses on snow routes | No morning pre-K",
        (D.BUSES_SNOW_ROUTES, D.NO_BREAKFAST, D.NO_AM_PREK),
    ),
    ("Delayed 3 hours; no lunch or breakfast", ()),
    ("Delayed 3 hours; no lunch; no breakfast", (D.NO_BREAKFAST, D.NO_LUNCH)),
    ("No breakfast / no lunch. 3 hour delay", (D.NO_BREAKFAST, D.NO_LUNCH)),
    ("School closed due to icy roads and wind chill. Staff report", (D.STAFF_REPORT,)),
    ("Early dismissal at 12:15 PM Friday. No PM preschool", (D.NO_PM_PREK,)),
    ("Effective Thursday, Jan 7: closed. Staff report", (D.STAFF_REPORT,)),
]


@pytest.mark.parametrize(("text", "expected"), STATES)
def test_each_detail_is_read_from_words_that_state_it(
    text: str, expected: tuple[Detail, ...]
) -> None:
    assert read_details(text) == tuple(sorted(expected))


SAYS_NOTHING = [
    # negations the patterns do not spell
    "Closed. Staff will not report",
    "Closed. No staff reporting",
    "3 hr delay. Breakfast is served",
    "3 hr delay. Buses run",
    "3 hr delay. Buses running normal routes",
    # part of the buses, of the day or of the staff
    "3 hr delay. PM buses on snow routes",
    "3 hr delay. Buses on snow routes this morning",
    "Closed. No transportation to the career center",
    "Late start. No out of town transportation",
    "3 hr delay. Snow routes on the east side",
    "Closed Friday. 10-month staff report at 9 AM",
    "Closed. Essential personnel must report",
    "Late start; Kids Club opens at 6 AM",
    "Closed. Main office closed",
    "Closed. Building offices closed",
    # part of the district or the school, outside the detail clauses
    "Delayed 3 hours, No breakfast, Middle school only",
    "3 hour delay at Maple Grove Elementary. No breakfast",
    "No pre-K at Maple Grove Elementary",
    # two days: which day a detail is for is not said
    "[FRIDAY] CLOSED | [SATURDAY] CLOSED, STAFF REPORT",
    "Closed Thursday. Friday: 3 hour delay, no breakfast",
    "Closed Feb 2. Feb 3 staff report",
    "Closed until Feb 14 - Staff report Thursday",
    "Closed today; March 4. Staff report",
    # part of the day
    "Thursday Morning: Closed | Thursday Night: No events",
    "Thursday Morning: Closed, staff report",
    # a word glued to an abbreviation, a lone route
    "Closed. Every site/Res.Hall Staff Report",
    "3 hr delay. Buses on short routes: Route 44 - Snow Route",
    # two details of one group that cannot both hold
    "3 hr delay, snow routes in effect, no buses",
    "Closed. Staff to report. Staff and students",
    "Closed. No pre-K. No morning pre-K",
    "Closed. Daycare open. Daycare closed",
    # unknown phrasing
    "Closed. No PM vocational center",
    "Closed. Buses running behind",
    "3 hr delay. Bus aides needed",
    "Closed. Pancake breakfast postponed",
    "Closed. Activities postponed",
    "Closed",
    "",
]


@pytest.mark.parametrize("text", SAYS_NOTHING)
def test_words_that_do_not_clearly_state_a_detail_give_none(text: str) -> None:
    assert read_details(text) == ()


# Each detail as the plain words that state it, beside a status it says something for.
SAID: dict[Detail, tuple[str, str]] = {
    D.STUDENTS_AND_STAFF: ("Closed Monday", "Students and staff"),
    D.STAFF_REPORT: ("Closed Monday", "Staff report"),
    D.STAFF_LATE: ("Three hour delay", "Staff report two hours late"),
    D.BUSES_SNOW_ROUTES: ("Three hour delay", "Buses on snow routes"),
    D.BUSES_EMERGENCY_ROUTES: ("Three hour delay", "Emergency routes in effect"),
    D.BUSES_PAVED_ROADS: ("Three hour delay", "Buses on paved roads only"),
    D.BUSES_LIMITED: ("Three hour delay", "Limited bus routes"),
    D.NO_BUSES: ("Three hour delay", "No buses"),
    D.NO_BREAKFAST: ("Three hour delay", "No breakfast"),
    D.NO_LUNCH: ("Early dismissal", "No lunch"),
    D.NO_HOT_LUNCH: ("Early dismissal", "No hot lunch"),
    D.GRAB_AND_GO: ("Remote learning Monday", "Grab and go meals available"),
    D.NO_AM_PREK: ("Three hour delay", "No morning pre-K"),
    D.NO_PM_PREK: ("Early dismissal", "No PM preschool"),
    D.NO_PREK: ("Remote learning Monday", "No pre-K"),
    D.ACTIVITIES_CANCELLED: ("Closed Monday", "Activities cancelled"),
    D.AFTER_SCHOOL_CANCELLED: ("Closed Monday", "After school sports called off"),
    D.EVENING_CANCELLED: ("Closed Monday", "Night events called off"),
    D.CHILDCARE_CLOSED: ("Closed Monday", "Childcare closed"),
    D.CHILDCARE_OPEN: ("Closed Monday", "Childcare open"),
    D.OFFICES_CLOSED: ("Closed Monday", "District offices closed"),
    D.OFFICES_OPEN: ("Closed Monday", "District offices open"),
}

# Words that may limit, hedge, negate or contradict a detail when they stand beside it.
QUALIFIERS = [
    "no",
    "none",
    "NO",
    "not today",
    "TBD",
    "TBA",
    "yes",
    "optional",
    "voluntary",
    "if able",
    "if safe",
    "only if roads allow",
    "except Maple Grove",
    "essential staff",
    "essential personnel",
    "12-month staff",
    "11 month",
    "custodians",
    "building administrators",
    "central office only",
    "Maple Grove",
    "Maple Grove Elementary",
    "Zones 2 and 4",
    "north side",
    "NE and SE",
    "route 9",
    "Bus 31",
    "gravel roads",
    "rural routes",
    "high school",
    "grades 6-12",
    "see website",
    "check email",
    "contact your supervisor",
    "students stay home",
    "staff stay home",
    "staff do not report",
    "breakfast served",
    "buses run regular routes",
    "until 3 pm",
    "at 10 am",
    "10 am",
    "varsity game still on",
]
JOINS = [": ", " (", " - ", " / ", "? ", ", ", ". ", "; ", " | ", "\n"]


def test_every_said_detail_is_read_alone_beside_its_status() -> None:
    assert set(SAID) == set(Detail)
    for detail, (status, words) in SAID.items():
        for join in (". ", ", ", "; ", " | ", " - ", ": "):
            assert read_details(f"{status}{join}{words}") == (detail,), (status, join, words)
        assert row_details(f"{status}. {words}", [_KIND[status]], 1, posted_that_day=True) == (
            detail.name.lower(),
        )


_KIND = {
    "Closed Monday": "closed",
    "Three hour delay": "delayed",
    "Early dismissal": "early_dismissal",
    "Remote learning Monday": "remote",
}


@pytest.mark.parametrize("detail", list(Detail))
def test_a_detail_beside_words_that_may_limit_it_is_never_read(detail: Detail) -> None:
    """A class sweep: every detail, every qualifier, joined to it on either side by every
    mark, or standing in a clause of its own anywhere in the row, gives no detail at all."""
    status, words = SAID[detail]
    for qualifier in QUALIFIERS:
        for join in JOINS:
            close = ")" if join == " (" else ""
            for text in (
                f"{status}. {words}{join}{qualifier}{close}",
                f"{status}. {qualifier}{join}{words}{close}",
                f"{status}{join}{qualifier}{close}. {words}",
                f"{words}. {status}{join}{qualifier}{close}",
            ):
                assert read_details(text) == (), text


@pytest.mark.parametrize(
    "text",
    [
        "Closed Monday. Staff report?",
        "Closed Monday? Staff report",
        "Closed Monday - Activities cancelled (TBD)",
        "Closed Monday. Childcare open [Maple Grove]",
        "Closed Monday. (Staff report)",
        "Closed Monday. Staff report: Thursday",
        "Closed Monday/Staff report",
        "Three hour delay. No breakfast - Maple Grove",
        "Three hour delay. No breakfast / Maple Grove",
    ],
)
def test_a_detail_set_off_by_a_mark_that_may_scope_it_is_never_read(text: str) -> None:
    assert read_details(text) == ()


@pytest.mark.parametrize(
    "status",
    [
        "Closed",
        "CLOSED TODAY",
        "Schools closed Thursday",
        "All schools are closed on Thursday, Jan 7",
        "The district will be closed tomorrow",
        "Closed due to icy roads",
        "Closed 1/7",
        "Classes cancelled",
        "No school today",
        "E-learning day",
        "At-home instruction day",
        "Virtual learning",
        "NTI day",
    ],
)
def test_a_plain_status_beside_a_detail_still_lets_it_be_read(status: str) -> None:
    assert read_details(f"{status}. Staff report") == (D.STAFF_REPORT,)
    assert read_details(f"Staff report, {status}") == (D.STAFF_REPORT,)


@pytest.mark.parametrize(
    "status",
    [
        "Two hour delay",
        "2 hr delay",
        "Delayed 2 hrs.",
        "Delayed start",
        "A 90 minute delay",
        "Late start at 10 AM",
        "School starts at 10:15",
        "Early dismissal at noon",
        "Dismissing early Thursday",
    ],
)
def test_a_shifted_status_shape_the_list_knows_or_not(status: str) -> None:
    found = read_details(f"{status}; No breakfast")
    known = status != "A 90 minute delay"
    assert found == ((D.NO_BREAKFAST,) if known else ()), status


def test_clauses_and_days() -> None:
    assert clauses("3 Hours Late, AM/PM Buses on snow routes; No a.m. Pre-K") == [
        "3 Hours Late",
        "AM and PM Buses on snow routes",
        "No am Pre-K",
    ]
    assert clauses("Delayed-Activities Called Off Today") == [
        "Delayed",
        "Activities Called Off Today",
    ]
    assert clauses("Closed 1/7/2027. Staff report") == ["Closed 1/7/2027", "Staff report"]
    assert names_days("Closed Thursday, January 7th. No preschool") == 1
    assert names_days("Closed Thu. Thursday: no preschool") == 1
    assert names_days("3 Hours Late, Buses on snow routes (For Fri. Jan 8th)") == 1
    assert names_days("Closed today; March 4") == 2
    assert names_days("Closed until Feb 14 - Staff report Thursday") == 2
    assert names_days("Closed today. Closed tomorrow") == 2
    assert names_days("Closed Feb 2 and Feb 3") == 2


def test_every_detail_has_a_group_a_status_and_a_stored_code() -> None:
    assert set(GROUP) == set(FOR_STATUS) == set(Detail)
    assert {detail.name.lower(): detail for detail in Detail} == DETAIL_BY_CODE
    assert all(FOR_STATUS[detail] for detail in Detail)


def test_a_row_gives_details_only_for_one_status_on_one_day_and_beside_that_status() -> None:
    text = "3 Hours Late | No breakfast | No morning pre-K | Buses on snow routes"
    assert row_details(text, ["delayed"], 1, posted_that_day=True) == (
        "buses_snow_routes",
        "no_breakfast",
        "no_am_prek",
    )
    # A closed day has no buses to route and no breakfast to skip.
    assert (
        row_details(
            "Closed. Buses on snow routes. No breakfast", ["closed"], 1, posted_that_day=True
        )
        == ()
    )
    assert row_details("Schools closed; staff report", ["closed"], 1, posted_that_day=True) == (
        "staff_report",
    )
    assert row_details("2 hour delay. Staff report", ["delayed"], 1, posted_that_day=True) == ()
    assert row_details("Closed. Grab-and-go meals", ["remote"], 1, posted_that_day=True) == (
        "grab_and_go",
    )
    # Two days, or two kinds: the row does not say which a detail is for.
    assert row_details(text, ["delayed"], 2, posted_that_day=True) == ()
    assert row_details(text, ["delayed", "closed"], 1, posted_that_day=True) == ()
    assert row_details(text, [], 0, posted_that_day=True) == ()
    # "No evening activities" posted the evening before may be about that evening.
    evening = "Closed tomorrow. No evening activities"
    assert row_details(evening, ["closed"], 1, posted_that_day=True) == ("evening_cancelled",)
    assert row_details(evening, ["closed"], 1, posted_that_day=False) == ()
    staff = "Closed tomorrow. Staff report"
    assert row_details(staff, ["closed"], 1, posted_that_day=False) == ("staff_report",)


def test_agreed_keeps_what_the_winning_rows_state_and_drops_a_group_they_disagree_on() -> None:
    snow = ("buses_snow_routes", "no_breakfast")
    assert agreed([snow, snow]) == (D.BUSES_SNOW_ROUTES, D.NO_BREAKFAST)
    # A row that states nothing of a group is left out of it.
    assert agreed([snow, ()]) == (D.BUSES_SNOW_ROUTES, D.NO_BREAKFAST)
    assert agreed([snow, ("no_breakfast",)]) == (D.BUSES_SNOW_ROUTES, D.NO_BREAKFAST)
    # Two rows that disagree on a group: that group is dropped, the others kept.
    assert agreed([snow, ("no_buses", "no_breakfast")]) == (D.NO_BREAKFAST,)
    assert agreed([("no_breakfast",), ("no_breakfast", "no_lunch")]) == ()
    assert agreed([]) == ()
    assert agreed([("not_a_code",)]) == ()


# --- through the resolver and the merge ----------------------------------------------------


def _world() -> World:
    world = World(stations={A: station(A), B: station(B)})
    for source in (A, B):
        world.read(at("2026-11-17 02:00"), [], source=source)  # Monday evening local
        world.read(at("2026-11-17 11:00"), [], source=source)
    return world


DELAY = "2 hour delay. Buses on snow routes. No breakfast"
EMERGENCY = "2 hour delay. Buses on emergency routes. No breakfast"


def test_a_lit_row_carries_its_details_into_the_published_closing() -> None:
    world = _world()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, DELAY)], source=A)
    merged = world.publish(at("2026-11-17 11:06"))
    (closing,) = merged.closings
    assert closing.status is Status.DELAYED
    assert closing.details == (D.BUSES_SNOW_ROUTES, D.NO_BREAKFAST)
    derived = next(r.derived for s in world.resolve() for r in s.rows if r.present)
    assert derived.details == ("buses_snow_routes", "no_breakfast")


def test_details_never_change_a_status_a_time_or_a_light() -> None:
    plain = _world()
    plain.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "2 hour delay")], source=A)
    said = _world()
    said.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, EMERGENCY)], source=A)
    one, two = plain.publish(at("2026-11-17 11:06")), said.publish(at("2026-11-17 11:06"))
    strip = [
        (c.school, c.day, c.status, c.announced_at, c.reason, c.shift_minutes, c.clock_minute)
        for c in two.closings
    ]
    assert strip == [
        (c.school, c.day, c.status, c.announced_at, c.reason, c.shift_minutes, c.clock_minute)
        for c in one.closings
    ]
    assert one.withheld == two.withheld
    # A row the reader holds stays held, details or not.
    held = _world()
    held.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "Closed. Activities cancelled")], source=A)
    assert held.publish(at("2026-11-17 11:06")).closings == ()


def test_rows_that_agree_merge_their_details_and_a_disagreement_drops_the_group() -> None:
    world = _world()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, DELAY)], source=A)
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "2 hour delay. No buses")], source=B)
    (closing,) = world.publish(at("2026-11-17 11:06")).closings
    assert closing.status is Status.DELAYED
    assert closing.details == (D.NO_BREAKFAST,)
    quiet = _world()
    quiet.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, DELAY)], source=A)
    quiet.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, "2 hour delay")], source=B)
    (closing,) = quiet.publish(at("2026-11-17 11:06")).closings
    assert closing.details == (D.BUSES_SNOW_ROUTES, D.NO_BREAKFAST)


def test_a_status_replaced_takes_its_details_with_it() -> None:
    world = _world()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, DELAY)], source=A)
    world.read(at("2026-11-17 11:10"), [], source=B)
    world.read(at("2026-11-17 11:20"), [row(ALPHA_SCHOOL, "Closed due to snow")], source=B)
    (closing,) = world.publish(at("2026-11-17 11:21")).closings
    assert closing.status is Status.CLOSED
    assert closing.details == ()


def test_a_row_naming_part_of_a_district_or_school_gives_no_details() -> None:
    world = _world()
    world.read(
        at("2026-11-17 11:05"),
        [row(ALPHA_SCHOOL, "2 hour delay at Lincoln Elementary. No breakfast")],
        source=A,
    )
    (closing,) = world.publish(at("2026-11-17 11:06")).closings
    assert closing.status is Status.DELAYED
    assert closing.details == ()


LIT_WITHOUT_DETAILS = [
    "Closed Tuesday - Staff report: no",
    "Closed Tuesday. Offices closed: none",
    "Closed Tuesday. Staff report: TBD",
    "Closed Tuesday. Staff report, if able",
    "Closed Tuesday. Staff report: optional",
    "Closed Tuesday. Staff report (essential staff)",
    "Closed Tuesday. Staff report - 10-month staff",
    "Closed Tuesday. Maple Grove: staff report",
    "Closed Tuesday. Staff report (Maple Grove)",
    "Closed Tuesday, staff report, staff will not report",
    "Closed Tuesday. Staff report. Students and staff stay home",
    "Closed Tuesday. Childcare open: no",
    "3 hour delay. Gravel roads: no buses",
    "3 hour delay. No buses (gravel roads)",
    "3 hour delay. Buses on snow routes. NE and SE buses on snow routes",
    "3 hour delay. Buses on snow routes, with snow routes in Zones 2 and 4 only",
    "3 hour delay. Bus 31: snow routes",
    "3 hour delay. Maple Grove: no breakfast",
]


@pytest.mark.parametrize("text", LIT_WITHOUT_DETAILS)
def test_a_lit_row_whose_other_words_may_limit_a_detail_lights_with_none(text: str) -> None:
    world = _world()
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL, text)], source=A)
    (closing,) = world.publish(at("2026-11-17 11:06")).closings
    assert closing.status in (Status.CLOSED, Status.DELAYED)
    assert closing.details == ()


# --- the stored and published forms --------------------------------------------------------


def test_a_derivation_stores_details_only_when_it_has_some() -> None:
    bare = Derived(withheld=None)
    assert "details" not in bare.to_json()
    assert Derived.from_json(bare.to_json()) == bare
    said = Derived(withheld=None, details=("buses_snow_routes", "no_breakfast"))
    stored = json.loads(json.dumps(said.to_json()))
    assert stored["details"] == ["buses_snow_routes", "no_breakfast"]
    assert Derived.from_json(stored) == said
    with pytest.raises(ValueError, match="details"):
        Derived(withheld=None, details=("Buses on snow routes",)).to_json()


STAMP = DirectoryStamp(generated_on=date(2026, 9, 24), schools=20, districts=2)


def test_closings_json_carries_details_by_row_position_and_old_files_read_none() -> None:
    day = date(2027, 1, 12)
    rows = [
        Closing(3, day, Status.DELAYED, None, None, 120, None, details=(D.BUSES_SNOW_ROUTES,)),
        Closing(5, day, Status.CLOSED, None, None),
        Closing(9, day, Status.CLOSED, None, None, details=(D.STAFF_REPORT, D.OFFICES_CLOSED)),
    ]
    made = ClosingsFile.encode(rows, generated_at=at("2027-01-12 13:05"), directory=STAMP)
    body = json.loads(made.model_dump_json())
    assert body["days"][0]["details"] == [[0, [3]], [2, [1, 20]]]
    assert ClosingsFile.model_validate_json(json.dumps(body)).closings() == rows
    del body["days"][0]["details"]
    assert all(
        row.details == () for row in ClosingsFile.model_validate_json(json.dumps(body)).closings()
    )


@pytest.mark.parametrize(
    "details",
    [
        [[1, [3]], [0, [8]]],
        [[0, [3]], [0, [8]]],
        [[3, [3]]],
        [[0, []]],
        [[0, [8, 3]]],
        [[0, [3, 3]]],
    ],
)
def test_a_details_column_that_breaks_the_rules_is_refused(details: object) -> None:
    rows = [Closing(i, date(2027, 1, 12), Status.CLOSED, None, None) for i in range(3)]
    body = json.loads(
        ClosingsFile.encode(
            rows, generated_at=at("2027-01-12 13:05"), directory=STAMP
        ).model_dump_json()
    )
    body["days"][0]["details"] = details
    with pytest.raises(ValueError, match=r"details|detail rows|too_short|at least"):
        ClosingsFile.model_validate_json(json.dumps(body))


def test_day_timelines_carry_details_and_a_change_of_details_is_a_change() -> None:
    world = _world()
    directory = world.dir
    nces = next(sid for sid, school in directory.schools.items() if school.index == 0)
    day = date(2026, 11, 17)
    plain = Shown(int(Status.DELAYED), None, 120, 600)
    said = Shown(int(Status.DELAYED), None, 120, 600, (int(D.NO_BREAKFAST),))
    changes = [
        Change(at("2026-11-17 11:05"), day, nces, Event.LIT, plain, {}),
        Change(at("2026-11-17 11:35"), day, nces, Event.CHANGED, said, {}),
    ]
    line = changes[1].to_json()
    assert line["details"] == [int(D.NO_BREAKFAST)]
    assert "details" not in changes[0].to_json()
    assert Change.from_json(line).shown == said
    made = timeline(
        day,
        changes,
        directory=directory,
        stamp=STAMP,
        generated_at=at("2026-11-17 12:00"),
        final=False,
    )
    assert made is not None
    assert made.counts == (2,)
    assert made.details == ((1, (D.NO_BREAKFAST,)),)
    assert DayTimeline.model_validate_json(made.model_dump_json()) == made
    assert [c.shown for c in seed_changes(made, directory)] == [plain, said]
    body = json.loads(made.model_dump_json())
    del body["details"]
    with pytest.raises(ValueError, match="change must change something"):
        DayTimeline.model_validate_json(json.dumps(body))


def test_a_status_push_says_its_details_and_details_alone_send_nothing() -> None:
    plain = PushShown(Status.DELAYED, 120, 600)
    said = PushShown(Status.DELAYED, 120, 600, (int(D.BUSES_SNOW_ROUTES),))
    assert plain.value() == said.value()


def test_a_closings_day_without_the_column_reads_as_none() -> None:
    day = ClosingsDay.model_validate_json(
        json.dumps(
            {
                "day": "2027-01-12",
                "gaps": [0],
                "statuses": [0],
                "announced": [None],
                "reasons": [None],
                "shifts": [],
                "clocks": [],
            }
        )
    )
    assert day.details == ()


def test_a_day_timeline_written_before_the_column_reads_as_none() -> None:
    example = Path(__file__).parents[1] / "schemas" / "examples" / "synthetic-live-day.json"
    body = json.loads(example.read_text())
    del body["details"]
    made = DayTimeline.model_validate_json(json.dumps(body))
    assert made.details == ()


def test_evening_activities_posted_the_evening_before_are_not_said_for_the_next_day() -> None:
    world = World(stations={A: station(A)})
    world.read(at("2026-11-17 00:30"), [], source=A)  # Monday 6:30 PM local
    world.read(
        at("2026-11-17 00:35"),
        [row(ALPHA_SCHOOL, "Closed tomorrow. No evening activities")],
        source=A,
    )
    (closing,) = world.publish(at("2026-11-17 00:41")).closings
    assert closing.day == date(2026, 11, 17)
    assert closing.details == ()
    same = World(stations={A: station(A)})
    same.read(at("2026-11-17 13:00"), [], source=A)  # Tuesday 7:00 AM local
    same.read(
        at("2026-11-17 13:05"),
        [row(ALPHA_SCHOOL, "Closed Tuesday | No evening events")],
        source=A,
    )
    (closing,) = same.publish(at("2026-11-17 13:06")).closings
    assert closing.details == (D.EVENING_CANCELLED,)

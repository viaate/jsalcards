"""An open statement beside the row's own status words (LIVE-WORDS-SAFETY, the lead's rulings R7
and R8): a row whose own words say closed, delayed, remote or early dismissal, or whose open
words have a subject that names someone else (R8 (iv): "Governors School report on time"),
never writes an open statement for any school it reaches (``CARVE_OUT``), and it darkens
exactly as the open would have, so no status lights or goes dark that did not before. Every
name here is SYNTHETIC and every text a written shape, never a copied row.

On 2026-11-11 a district row said "Closed Wednesday" with a comment that two regional programs
report on time, and an open statement of the comment's shape, on another list with no status
beside it, stood for the district's schools in opens.json. Lighting such a row's closing is
LIVE-WORDS-LIGHT's, not this file's.

Most tests here fail at the base for want of the guards; :class:`TestARealOpenStillOpens` and
:class:`TestTheRowsOwnStatusIsNeverTakenBackByItsOwnOpenWords` pin what the base already does
and must keep doing, and :class:`TestTheInvariant` pins lanes counted at the base.
"""

import functools
import hashlib
from datetime import UTC, date, datetime, timedelta

import pytest

from live.world import ALPHA_DISTRICT, World, lit, reasons, row, station
from snowlight.classify import parse_status
from snowlight.live.guards import (
    NEGATION_REACH,
    OTHERS,
    STATUS_WORDS,
    Withheld,
    names_a_status,
    opens_for_others,
)
from snowlight.live.ledger import Outcome
from snowlight.live.merge import Merged
from snowlight.live.resolve import Derived, f5_reader

WEDNESDAY = date(2026, 11, 18)
OTHER = "nexstar-synthetic"

BESIDE_A_STATUS = [
    "Schools open, closed to visitors",
    "Open on time, offices closed",
    "Open, after-school activities closed",
    "Open - buses delayed 2 hours",
    "2 hour delay for buses; schools open on time",
    "Open on time. District office closed",
    "Open on time, pool closed",
    "Schools open on time, child care closed",
    "Schools open, buses delayed",
    "Schools open; evening classes canceled",
    "Open, buses 2 hours late",
    "Open; abbreviated day",
    "Open, buses running late",
]
"""Rows the reader reads as an open statement and nothing else, whose own words also say
closed, delayed, remote or early dismissal: the open is never published."""

ABOUT_OTHERS = [
    "ANTC and Governors School report on time",
    "Governor's School on time",
    "Gov. School on time",
    "Daycare open on time",
    "Update: Child care open on time",
]
"""Rows the reader reads as an open statement and nothing else, with no status word, whose
open words have a subject naming someone else (R8 (iv)): the open is never published."""

REAL_OPENS = [
    "Open",
    "Normal schedule",
    "Schools are open on time",
    "All schools will be open on time",
    "Open On Time, Buses On Snow Routes",
    "ANTC on time",
    "Superintendent says schools open on time",
    "SYNTHETIC Alpha District open on time",
]
"""Rows with no status word and no phrase of OTHERS before their open words: their open
stands as before (an acronym alone is no phrase of OTHERS; lighting a carve-out is
LIVE-WORDS-LIGHT's)."""


def at_(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=UTC)


def _world() -> World:
    world = World(
        reader=f5_reader(),
        stations={"gray-synthetic": station(), OTHER: station(OTHER)},
    )
    world.ledger.observe("zz-synthetic", Outcome.EMPTY, at_(WEDNESDAY - timedelta(days=10), 12), ())
    return world


def _alone(text: str, world: World | None = None) -> tuple[World, Merged]:
    """``text`` for the district on a list that read empty before, at Wednesday 11:35:38Z."""
    world = world or _world()
    world.read(at_(WEDNESDAY - timedelta(days=1), 23), [], source=OTHER)
    world.read(at_(WEDNESDAY, 11, 10), [], source=OTHER)
    world.read(at_(WEDNESDAY, 11, 35, 38), [row(ALPHA_DISTRICT, text)], source=OTHER)
    return world, world.publish(at_(WEDNESDAY, 11, 36))


def _after_a_closing(text: str) -> Merged:
    """The district's list says "Closed Wednesday" from Tuesday 23:00Z; another list says
    ``text`` from Wednesday 11:30Z."""
    world = _world()
    for source in ("gray-synthetic", OTHER):
        world.read(at_(WEDNESDAY - timedelta(days=1), 20), [], source=source)
    world.read(at_(WEDNESDAY - timedelta(days=1), 23), [row(ALPHA_DISTRICT, "Closed Wednesday")])
    world.read(at_(WEDNESDAY - timedelta(days=1), 23), [], source=OTHER)
    world.read(at_(WEDNESDAY, 11, 10), [], source=OTHER)
    world.read(at_(WEDNESDAY, 11, 30), [row(ALPHA_DISTRICT, "Closed Wednesday")])
    world.read(at_(WEDNESDAY, 11, 30), [row(ALPHA_DISTRICT, text)], source=OTHER)
    return world.publish(at_(WEDNESDAY, 11, 31))


def _derived(world: World) -> Derived:
    return world.resolve()[0].rows[0].derived


class TestNamesAStatus:
    @pytest.mark.parametrize(
        "text",
        [
            "Closed Wednesday. ANTC and Governors School report on time",
            "Open today, closed tomorrow",
            "Schools open, closed to visitors",
            "Open, 2 hour delay for buses",
            "Open. Delayed opening Thursday",
            "Late start for the high school",
            "Open. Remote learning Thursday",
            "Open, virtual day Friday",
            "E-learning day",
            "NTI day",
            "AMI day",
            "Online learning for grades 6-12",
            "Distance learning",
            "Flexible instruction day",
            "At-home learning",
            "Learning from home",
            "Open, early dismissal at 1",
            "Early release Friday",
            "Dismissing early",
            "Released early",
            "Half day",
            "Closing at noon",
            "Building closures",
            "Open; evening classes cancelled",
            "Practice canceled",
            "Open, 2 hrs. late",
            "Buses running late",
            "Shortened day Friday",
            "Not closed, 2 hour delay",
            "No buses, delayed opening",
            "No buses 2 hour delay",
            "Closed or delayed",
            "No school. Delayed",
        ],
    )
    def test_a_status_word_counts(self, text: str) -> None:
        assert names_a_status(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Open",
            "Open. No delay",
            "Open - No Delays",
            "Schools will not be closed",
            "Open, no early dismissal",
            "Not closed",
            "Open without delay",
            "No closures or delays. Open on time",
            "There will not be a delay today. Schools open on time",
            "Open on time, no two hour delay",
            "Open, no 2-hour delay",
            "Not closed or delayed",
            "Open, no cancellations",
            "ANTC and Governors School report on time",
            "Open on time, buses on snow routes",
            "Disclosed schedule",
            "Amish school open",
        ],
    )
    def test_no_status_word_or_one_taken_back_does_not(self, text: str) -> None:
        assert not names_a_status(text)

    def test_a_negation_reaches_only_its_own_words(self) -> None:
        far = " ".join(["no"] + ["word"] * NEGATION_REACH + ["closed"])
        assert names_a_status(far)
        assert not names_a_status("no " + "word " * (NEGATION_REACH - 1) + "closed")

    def test_a_negation_reaches_over_filler_and_a_joined_list_only(self) -> None:
        assert not names_a_status("not " + "be a two hour " + "delay")
        assert names_a_status("not word be a delay")
        assert not names_a_status("no closures or delays or early dismissals")
        assert names_a_status("closures or delays")
        assert names_a_status("no buses and delays")

    def test_the_status_words_are_one_closed_list(self) -> None:
        assert STATUS_WORDS.flags & 2  # re.IGNORECASE
        assert names_a_status("SCHOOLS OPEN, OFFICES CLOSED")


COUNTY = "SYNTHETIC Alpha County Public Schools"


class TestOpensForOthers:
    """R8 (iv): the subject words of an open statement, read as wip-live-words-light reads
    them, hold a phrase of OTHERS that is not the row's own."""

    @pytest.mark.parametrize(
        ("text", "name"),
        [
            ("ANTC and Governors School report on time", COUNTY),
            ("ANTC and Governors School report on time", "SYNTHETIC Alpha Co. Schools"),
            ("Closed Wednesday|ANTC and Governors School report on time", COUNTY),
            ("Governor's School on time", COUNTY),
            ("Governor\u2019s School on time", COUNTY),
            ("Gov. School on time", COUNTY),
            ("Head Start on time", COUNTY),
            ("Daycare open on time", COUNTY),
            ("After-school care open", COUNTY),
            ("Vo-Tech on time", COUNTY),
            ("Career & Technical Center open", COUNTY),
            ("Update: Child care open on time", COUNTY),
            ("Staff on time", COUNTY),
            ("Schools open, child care opens at 7", COUNTY),
            ("Regional schools open", ALPHA_DISTRICT),
            ("Schools open on time and Governors School on time", COUNTY),
        ],
    )
    def test_a_phrase_of_others_before_the_open_words(self, text: str, name: str) -> None:
        assert opens_for_others(text, name)

    @pytest.mark.parametrize(
        ("text", "name"),
        [
            ("Open on time", COUNTY),
            ("Schools open on time", COUNTY),
            ("SYNTHETIC Alpha Co. Schools open on time", COUNTY),
            ("Normal schedule", COUNTY),
            ("ANTC on time", COUNTY),
            ("Open on time for staff only", COUNTY),
            ("Open as usual - Central Office", COUNTY),
            ("Superintendent says schools open on time", COUNTY),
            ("Central Office says schools now open on time", COUNTY),
            ("Open; staff report at 7:30", COUNTY),
            ("Staff report at 7:30", COUNTY),
            ("Regional schools open", "SYNTHETIC Regional School District"),
            ("SYNTHETIC Vocational Center open on time", "SYNTHETIC Vocational Center"),
            ("Alpha-Beta Vocational open on time", "SYNTHETIC Alpha-Beta Vocational"),
        ],
    )
    def test_none_or_the_rows_own_or_after_the_open_words(self, text: str, name: str) -> None:
        assert not opens_for_others(text, name)

    def test_every_run_of_open_words_has_its_subject_read(self) -> None:
        # the phrase is in the subject of the part's second run of open words only
        assert not opens_for_others("Schools open on time", COUNTY)
        assert opens_for_others("Schools open on time and Governors School on time", COUNTY)
        assert opens_for_others("Open as usual and the daycare open", COUNTY)

    def test_others_is_the_light_branchs_list_with_nothing_added(self) -> None:
        # wip-live-words-light 796b775's OTHERS, exactly: R8 adds no spelling
        joined = "|".join(sorted(" ".join(phrase) for phrase in OTHERS))
        assert len(OTHERS) == 63
        assert hashlib.sha256(joined.encode()).hexdigest()[:16] == "919d6bc00fff9d27"


class TestAStatusBesideAnOpenIsNeverPublished:
    @pytest.mark.parametrize("text", [*BESIDE_A_STATUS, *ABOUT_OTHERS])
    def test_the_open_is_kept_as_carve_out_and_never_published(self, text: str) -> None:
        world, merged = _alone(text)
        assert reasons(world.resolve()) == [Withheld.CARVE_OUT.value]
        derived = _derived(world)
        # it keeps the open's days and schools, so it darkens exactly as the open did
        assert derived.opens == (WEDNESDAY,)
        assert len(derived.targets) == 2
        assert merged.opens == ()
        assert lit(merged) == {}
        assert merged.withheld.get(Withheld.CARVE_OUT.value) == 2

    @pytest.mark.parametrize("text", [*BESIDE_A_STATUS, *ABOUT_OTHERS])
    def test_it_takes_an_older_closing_back_as_the_open_did(self, text: str) -> None:
        merged = _after_a_closing(text)
        plain = _after_a_closing("Open")
        assert (lit(merged), lit(plain)) == ({}, {})
        assert merged.opens == ()
        assert len(plain.opens) == 2
        assert merged.withheld.get(Withheld.RETRACTED.value) == plain.withheld.get(
            Withheld.RETRACTED.value
        )

    @pytest.mark.parametrize("text", BESIDE_A_STATUS[:3])
    def test_a_reused_derivation_stays_unpublished(self, text: str) -> None:
        world, merged = _alone(text)
        assert merged.opens == ()
        world.read(at_(WEDNESDAY, 11, 45, 38), [row(ALPHA_DISTRICT, text)], source=OTHER)
        again = world.publish(at_(WEDNESDAY, 11, 46))
        assert again.opens == ()
        assert reasons(world.resolve()) == [Withheld.CARVE_OUT.value]

    def test_the_derivation_round_trips_with_its_reason(self) -> None:
        world, _merged = _alone(BESIDE_A_STATUS[0])
        derived = _derived(world)
        assert Derived.from_json(derived.to_json()) == derived


class TestARealOpenStillOpens:
    @pytest.mark.parametrize("text", REAL_OPENS)
    def test_at_the_readers_confidence(self, text: str) -> None:
        world, merged = _alone(text)
        assert reasons(world.resolve()) == [None]
        confidence = parse_status(text, posted_at=at_(WEDNESDAY, 11, 35), tz="UTC").confidence
        assert {signal.school for signal in merged.opens} == {0, 1}
        assert {signal.confidence for signal in merged.opens} == {confidence}
        assert Withheld.CARVE_OUT.value not in merged.withheld


TEGNA = "tegna-synthetic"


def _two_lists(first: str | None, second: str, *, minute: int = 35, swap: bool = False) -> Merged:
    """``first`` (None: nothing) on one list at Wednesday 11:35Z and ``second`` on another at
    11:``minute``Z, both read empty before. ``first`` is on the list merge chooses first
    among equals, or with ``swap`` on the other."""
    lists = (TEGNA, OTHER) if swap else (OTHER, TEGNA)
    world = _world()
    world.stations[TEGNA] = station(TEGNA)
    for source in lists:
        world.read(at_(WEDNESDAY - timedelta(days=1), 23), [], source=source)
        world.read(at_(WEDNESDAY, 11, 10), [], source=source)
    rows = [] if first is None else [row(ALPHA_DISTRICT, first)]
    world.read(at_(WEDNESDAY, 11, 35), rows, source=lists[0])
    world.read(at_(WEDNESDAY, 11, minute), [row(ALPHA_DISTRICT, second)], source=lists[1])
    return world.publish(at_(WEDNESDAY, 11, max(minute, 35) + 1))


class TestACarveOutBesideARealOpenOnAnotherList:
    """A row that is ``CARVE_OUT`` never writes or sources an open, and never takes away the
    open a real row on another list writes at the same moment (the base writes it too)."""

    @pytest.mark.parametrize(
        "text",
        [
            BESIDE_A_STATUS[0],
            *ABOUT_OTHERS,
            "Regional school on time",
            "ANTC and Governors School report on time",
        ],
    )
    @pytest.mark.parametrize("swap", [False, True])
    def test_the_real_open_stands_on_its_own_row(self, text: str, swap: bool) -> None:
        merged = _two_lists("Open", text, swap=swap)
        plain = _two_lists("Open", "Open", swap=swap)
        assert (lit(merged), lit(plain)) == ({}, {})
        assert {signal.school for signal in merged.opens} == {0, 1}
        assert {signal.source_id for signal in merged.opens} == {TEGNA if swap else OTHER}
        assert {signal.at for signal in merged.opens} == {at_(WEDNESDAY, 11, 35)}
        assert Withheld.CARVE_OUT.value not in merged.withheld

    @pytest.mark.parametrize("minute", [35, 45])
    @pytest.mark.parametrize("swap", [False, True])
    def test_a_later_carve_out_never_sources_it(self, minute: int, swap: bool) -> None:
        merged = _two_lists("Open", ABOUT_OTHERS[0], minute=minute, swap=swap)
        assert lit(merged) == {}
        assert {signal.source_id for signal in merged.opens} <= {TEGNA if swap else OTHER}

    def test_carve_outs_on_both_lists_publish_none(self) -> None:
        merged = _two_lists(BESIDE_A_STATUS[0], ABOUT_OTHERS[0])
        assert (lit(merged), merged.opens) == ({}, ())
        assert merged.withheld.get(Withheld.CARVE_OUT.value) == 2


class TestTheRowsOwnStatusIsNeverTakenBackByItsOwnOpenWords:
    """(ii): a row whose words carry a status and an open sentence never lights less, and
    never opens, where a row of its status alone would light."""

    @pytest.mark.parametrize(
        "comment",
        [
            "ANTC and Governors School report on time",
            "STC and the Governor's School report on time",
            "Governors School on time",
        ],
    )
    def test_closed_wednesday_with_a_carve_out_sentence(self, comment: str) -> None:
        text = f"Closed Wednesday. {comment}"
        _world_a, merged = _alone(text)
        _world_b, closed = _alone("Closed Wednesday")
        assert merged.opens == ()
        assert lit(merged) == lit(closed)
        assert Withheld.CARVE_OUT.value not in merged.withheld

    def test_a_successor_with_the_sentence_never_opens(self) -> None:
        world = _world()
        world.read(at_(WEDNESDAY - timedelta(days=1), 23), [], source=OTHER)
        world.read(at_(WEDNESDAY, 11, 10), [], source=OTHER)
        world.read(at_(WEDNESDAY, 11, 25), [row(ALPHA_DISTRICT, "Closed Wednesday")], source=OTHER)
        first = world.publish(at_(WEDNESDAY, 11, 26))
        assert set(lit(first).values()) == {"CLOSED"}
        for minute in (35, 45, 55):
            text = "Closed Wednesday. ANTC and Governors School report on time"
            world.read(at_(WEDNESDAY, 11, minute, 38), [row(ALPHA_DISTRICT, text)], source=OTHER)
            assert world.publish(at_(WEDNESDAY, 11, minute + 1)).opens == ()


MAY_DROP = [
    *BESIDE_A_STATUS,
    *ABOUT_OTHERS,
    "Head Start on time",
    "Closed Wednesday. ANTC and Governors School report on time",
    "Closed every Wednesday. ANTC and Governors School report on time",
    "Normal schedule. Child care closed",
    "Open Transportation 2 hour delay",
    "Open, no bus service, lunch program closed",
    "Open today, closed tomorrow",
    "Two hour delay",
    "Remote learning day",
    "Early dismissal at noon",
    "Closed Wednesday",
]
"""Shapes whose own words, read by hand, carry a status word or a phrase of OTHERS: the only
ones that may lose an open (never read with the guards under test)."""
NEVER_DROP = [*REAL_OPENS, "Open on time for staff only", "Open. No delay", "Open as usual"]
"""Shapes with neither, read by hand: they keep every open the base writes."""
TIMES = [(11, 25), (18, 30), (21, 30), (23, 30)]
Lanes = dict[str, tuple[dict[tuple[int, str], str], int]]


def _lanes(text: str) -> Lanes:
    """What lights and how many schools open, at each of :data:`TIMES` on Wednesday: ``text``
    alone on a list (WA), after the district's "Closed Wednesday" on another (WB), and beside
    a plain "Open" on another list at the same moment (WC)."""
    found: Lanes = {}
    for hour, minute in TIMES:
        world = _world()
        world.read(at_(WEDNESDAY - timedelta(days=1), 23), [], source=OTHER)
        world.read(at_(WEDNESDAY, hour, minute - 15), [], source=OTHER)
        world.read(at_(WEDNESDAY, hour, minute), [row(ALPHA_DISTRICT, text)], source=OTHER)
        alone = world.publish(at_(WEDNESDAY, hour, minute + 1))
        found[f"WA@{hour}:{minute}"] = (lit(alone), len({s.school for s in alone.opens}))
        world = _world()
        for source in ("gray-synthetic", OTHER):
            world.read(at_(WEDNESDAY - timedelta(days=1), 20), [], source=source)
        world.read(
            at_(WEDNESDAY - timedelta(days=1), 23), [row(ALPHA_DISTRICT, "Closed Wednesday")]
        )
        world.read(at_(WEDNESDAY - timedelta(days=1), 23), [], source=OTHER)
        world.read(at_(WEDNESDAY, hour, minute), [row(ALPHA_DISTRICT, "Closed Wednesday")])
        world.read(at_(WEDNESDAY, hour, minute), [row(ALPHA_DISTRICT, text)], source=OTHER)
        beside = world.publish(at_(WEDNESDAY, hour, minute + 1))
        found[f"WB@{hour}:{minute}"] = (lit(beside), len({s.school for s in beside.opens}))
        world = _world()
        world.stations[TEGNA] = station(TEGNA)
        for source in (OTHER, TEGNA):
            world.read(at_(WEDNESDAY - timedelta(days=1), 23), [], source=source)
            world.read(at_(WEDNESDAY, hour, minute - 15), [], source=source)
        world.read(at_(WEDNESDAY, hour, minute), [row(ALPHA_DISTRICT, "Open")], source=TEGNA)
        world.read(at_(WEDNESDAY, hour, minute), [row(ALPHA_DISTRICT, text)], source=OTHER)
        both = world.publish(at_(WEDNESDAY, hour, minute + 1))
        found[f"WC@{hour}:{minute}"] = (lit(both), len({s.school for s in both.opens}))
    return found


def _base_lanes(
    text: str, patch: pytest.MonkeyPatch, *, status: bool = True, others: bool = True
) -> Lanes:
    """:func:`_lanes` with the status-word guard (``status``) and the OTHERS guard
    (``others``) taken out."""
    with patch.context() as inside:
        if status:
            inside.setattr("snowlight.live.resolve.names_a_status", lambda _text: False)
        if others:
            inside.setattr("snowlight.live.resolve.opens_for_others", lambda _text, _name: False)
        return _lanes(text)


def _counted(lanes: Lanes) -> dict[str, tuple[int, int]]:
    return {lane: (len(lights), opens) for lane, (lights, opens) in lanes.items()}


def _pins(**lanes: list[tuple[int, int]]) -> dict[str, tuple[int, int]]:
    """Per lane kind (WA, WB, WC), one count for each of :data:`TIMES` in turn."""
    return {f"{kind}@{h}:{m}": lanes[kind][at] for kind in lanes for at, (h, m) in enumerate(TIMES)}


_NONE = (0, 0)
_OPENS = (0, 2)
_CLOSED = (2, 0)
_MORNING_OPEN = [_OPENS, _NONE, _NONE, _NONE]
AT_THE_BASE = {
    text: _pins(WA=_MORNING_OPEN, WB=[_NONE] * 4, WC=_MORNING_OPEN)
    for text in ("Open", "ANTC and Governors School report on time", BESIDE_A_STATUS[0])
} | {
    "Closed Wednesday": _pins(
        WA=[_CLOSED] * 4, WB=[_CLOSED] * 4, WC=[_NONE, _NONE, _CLOSED, _CLOSED]
    )
}
"""(statuses lit, schools opened) per lane, counted with the real base's live code (origin
ba2a30a, before these guards): no lane may light other, nor open more, and a plain "Open"
beside the shape (WC) keeps every open it writes alone."""


@functools.cache
def _plain_open(lane: str) -> int:
    """How many schools the plain "Open" of the WC lanes opens alone at ``lane``'s time."""
    return _lanes("Open")["WA" + lane[2:]][1]


class TestTheInvariant:
    """R7 item 3 and R8 over written shapes, on one list and on two: every lit status is the
    same as with the guards taken out, no open is new, and an open is dropped only from a
    shape whose words, read by hand, carry a status word or a phrase of OTHERS; beside a
    plain "Open" on another list (WC) every open that row writes alone stands (an open the
    shape alone wrote may go)."""

    @pytest.mark.parametrize("text", [*MAY_DROP, *NEVER_DROP])
    def test_against_the_guards_taken_out(self, text: str, monkeypatch: pytest.MonkeyPatch) -> None:
        head = _lanes(text)
        base = _base_lanes(text, monkeypatch)
        for lane, (lights, opens) in head.items():
            assert lights == base[lane][0], lane
            assert opens <= base[lane][1], lane
            if text in NEVER_DROP:
                assert opens == base[lane][1], lane
            if lane.startswith("WC"):
                assert opens >= min(base[lane][1], _plain_open(lane)), lane

    @pytest.mark.parametrize("text", AT_THE_BASE)
    def test_against_lanes_counted_at_the_base(self, text: str) -> None:
        head = _counted(_lanes(text))
        for lane, (lights, opens) in AT_THE_BASE[text].items():
            assert head[lane][0] == lights, lane
            assert head[lane][1] <= opens, lane
            if text in NEVER_DROP:
                assert head[lane][1] == opens, lane
            if lane.startswith("WC"):
                assert head[lane][1] >= min(opens, _plain_open(lane)), lane

    def test_the_shapes_drop_some_opens_and_keep_others(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dropped = kept = 0
        for text in (BESIDE_A_STATUS[0], ABOUT_OTHERS[0], REAL_OPENS[0]):
            head = _lanes(text)
            base = _base_lanes(text, monkeypatch)
            dropped += sum(base[lane][1] - head[lane][1] for lane in head)
            kept += sum(head[lane][1] for lane in head)
        assert dropped > 0
        assert kept > 0

    @pytest.mark.parametrize(
        ("text", "guard"),
        [
            *((text, "others") for text in ABOUT_OTHERS),
            *(
                (text, "status")
                for text in BESIDE_A_STATUS
                if not opens_for_others(text, ALPHA_DISTRICT)
            ),
        ],
    )
    def test_each_guard_is_needed(
        self, text: str, guard: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The mutation check: with only its own guard taken out, a shape opens again on its
        own list, and the other guard alone never drops it."""
        head = _lanes(text)
        without_it = _base_lanes(
            text, monkeypatch, status=guard == "status", others=guard == "others"
        )
        without_the_other = _base_lanes(
            text, monkeypatch, status=guard == "others", others=guard == "status"
        )
        alone = [lane for lane in head if lane.startswith("WA")]
        assert sum(head[lane][1] for lane in alone) == 0
        assert sum(without_it[lane][1] for lane in alone) > 0
        assert without_the_other == head

"""Round 3 of the coverage gate, resumed: initials, Scripps' empty layout, a calendar.

Forms the closure-text check still left misread after round 3's first passes:

* Victoria ISD's homepage of 2021-02-16 (an Edlio site then), whose news headline
  "Victoria ISD Will Remain Closed Through Tuesday Due To Inclement Weather" the notice
  gate did not take for a closing: "ISD" was no subject it knew, and "closed through
  Tuesday" no day's closing. Only the line under it ("All Victoria ISD buildings and
  schools will be closed through Tuesday, February 16.", which names no weather) was
  read, so the source was not proven.
* KGUN's closings page of 2017 on Scripps' Liferay template, whose layout held no
  portlet at all, refused as a form the Scripps adapter did not know.
* Washington County's homepage calendar (2024-2026), whose planned days ("Teacher Prep
  Day (No School)", "President's Day (No School)") were read as closings, and its
  WCSD Alerts answers of 2022-2025, which write their numbers as strings.

Fixtures are real captures (``fixtures/gate/``, provenance in its PROVENANCE.json);
the snippets built here are synthetic and say so.
"""

import pytest

from snowlight.sources.stations import (
    closure_text,
    district_homepage,
    edlio,
    gate_fixtures,
    notices,
    scripps,
)
from snowlight.sources.stations.closure_text import ReadOf
from snowlight.sources.stations.model import ListingState, ShapeError

FOLDER = gate_fixtures.DEFAULT_FOLDER
HEADLINE = "Victoria ISD Will Remain Closed Through Tuesday Due To Inclement Weather"


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def test_a_district_named_by_its_initials_closes() -> None:
    victoria = edlio.parse(_body("edlio/victoria-20210216.html"))
    assert victoria.state is ListingState.POPULATED
    names = [row.name for row in victoria.rows]
    assert names == [
        "Apply Now for 2021-2022 Tuition-Based Pre-K!",
        HEADLINE,
        "All Victoria ISD buildings and schools will be closed through Tuesday, February 16.",
    ]
    assert [row.extra.get("section") for row in victoria.rows[1:]] == ["page-text"] * 2
    # The headline names the weather, so it proves the channel; the line under it does not.
    assert notices.page_text_closing(HEADLINE)
    assert not notices.page_text_closing(victoria.rows[2].name)
    assert closure_text.is_closing(HEADLINE)


@pytest.mark.parametrize(
    ("line", "closing"),
    [
        # SYNTHETIC lines, in the forms districts write them.
        ("Edinburg CISD closed Monday due to winter weather", True),
        ("PSUSD campuses closed Tuesday due to the windstorm", True),
        ("Schools closed through Wednesday due to snow", True),
        ("Offices closed until Friday", True),
        ("PSUSD schools are open", False),
        ("Registration for Victoria ISD closes Friday", False),
    ],
)
def test_initials_and_closed_through(line: str, *, closing: bool) -> None:
    assert closure_text.has_status(line) is closing


def test_a_liferay_layout_with_no_portlet_holds_no_list() -> None:
    kgun = scripps.parse(_body("lists/kgun-liferay-20170316.html"))
    assert (kgun.variant, kgun.state, kgun.rows, kgun.follows) == (
        "scripps-liferay-empty-layout",
        ListingState.DEFERRED,
        (),
        (),
    )
    # The closure-text check finds no closing on it and counts it a shell, not misread.
    lines = closure_text.closing_blocks(_body("lists/kgun-liferay-20170316.html"))
    assert lines == []
    read = ReadOf("deferred", kgun.variant)
    assert closure_text.outcome(read, lines)[0] == "shell"


def test_a_liferay_layout_with_text_is_unknown() -> None:
    # SYNTHETIC: the same layout with something written in it is no empty layout.
    page = (
        b'<html><body><div id="main-content"><div class="portlet-dropzone empty">'
        b"</div><p>Closings will be posted here.</p></div></body></html>"
    )
    with pytest.raises(ShapeError):
        scripps.parse(page)
    # SYNTHETIC: a dropzone not marked empty is no empty layout either.
    filled = (
        b'<html><body><div id="main-content"><div class="portlet-dropzone">'
        b"</div></div></body></html>"
    )
    with pytest.raises(ShapeError):
        scripps.parse(filled)


@pytest.mark.parametrize(
    "line",
    [
        # Washington County's homepage calendar (2024-2026), as its archived captures show it.
        "Monday - Mar. 18, 2024 Teacher Prep Day (No School)",
        "Friday - Feb. 16, 2024 Legislative Teacher Prep Day (No School)",
        "Monday - Feb. 19, 2024 President's Day (No School)",
        "Wed - Nov. 27, 2024 to - Nov. 27, 2024 SEP/SEOP Comp Recess Day (No School)",
    ],
)
def test_a_calendars_planned_days_are_no_closings(line: str) -> None:
    assert closure_text.is_planned(line)
    assert not closure_text.is_closing(line)


def test_a_wcsd_answer_that_writes_its_numbers_as_strings() -> None:
    older = district_homepage.parse(_body("district/washington-alerts-20240124.json.gz"))
    assert (older.variant, older.state) == (district_homepage.WCSD, ListingState.POPULATED)
    (row,) = older.rows
    assert row.name == "NEW STUDENT REGISTRATION"
    assert (row.extra["alert_id"], row.extra["active"]) == (96, 1)
    # SYNTHETIC: an id that is no number at all is still refused.
    with pytest.raises(ShapeError):
        district_homepage.parse(b'[{"id": "x96", "title": "A", "message": "B"}]')

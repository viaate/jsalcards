"""A district's dated closing, corroborated by an NWS warning, proves its channel.

The notice texts are real rows read from archived captures of the districts' homepages
(capture times in each case; the bodies are in the archive-captures artifacts, and
Granite's of 2023-02-22 is the fixture gate/district/granite-20230222.html). The warning
days are the values :func:`snowlight.sources.stations.storms.warning_days` gives for each
district's county from the NWS record the closure weights count (the Iowa Environmental
Mesonet's archive): weight 1.0 is a Winter Storm, Blizzard, Ice Storm or Lake Effect Snow
Warning, 0.25 a Winter Weather Advisory. Mappings and proofs marked ``SYNTHETIC`` are made
up here, confined to these tests.
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from snowlight.output import JSONValue
from snowlight.sources.stations import notices
from snowlight.sources.stations.adapters import adapter_for
from snowlight.sources.stations.registry import load_registry
from snowlight.sources.stations.storms import WarningDay, warning_days

FIXTURES = Path(__file__).parent / "fixtures"
REGISTRY = load_registry()
SALT_LAKE = "49035"

GRANITE_AT = datetime(2023, 2, 22, 5, 37, 20, tzinfo=UTC)
GRANITE_ROW = (
    "Distance Learning Day for Granite School District \u2013 Wednesday, February 22, 2023"
)
GRANITE_NEXT_AT = datetime(2023, 2, 23, 21, 48, 25, tzinfo=UTC)
GRANITE_DELAY = (
    "2-Hour Delayed Start for Granite School District \u2013 Thursday, February 23, 2023"
)
CANYONS_AT = datetime(2022, 12, 2, 22, 24, 56, tzinfo=UTC)
CANYONS_ROW = "Remote-Learning Day Announced for all CSD Schools for Friday. Dec. 2"
CANYONS_HOLIDAY_AT = datetime(2022, 2, 21, 18, 19, 33, tzinfo=UTC)
CANYONS_HOLIDAY = "Schools, District Office Closed Feb. 21"

ROMA_ROW = "Delayed Start for Roma ISD on Monday, January 26, 2026!"
CANYONS_LATER = "Canyons Announces Remote-Learning Day for Monday, March 6"
KINGSVILLE_ROW = "January 27th, 2026 Bus Routes for our 2-Hr Late Start"

CONVERSE_AT = datetime(2021, 10, 16, 17, 17, 0, tzinfo=UTC)
CONVERSE_ROW = "No School in Converse 1-October 13, 2021"
PUTNAM_AT = datetime(2017, 9, 10, 17, 2, 0, tzinfo=UTC)
PUTNAM_ROW = (
    "All Putnam County schools will be closed on Friday, September 8th, and Monday, "
    "September 11th, 2017."
)
DARBY_AT = datetime(2019, 2, 14, 4, 40, 0, tzinfo=UTC)
DARBY_ROW = (
    "No School Friday, February 15th and Monday, February 18th in observance of "
    "President\u2019s Day."
)

# Salt Lake County's NWS days around these notices, as warning_days gives them.
SALT_LAKE_DAYS = {
    date(2022, 2, 21): WarningDay(date(2022, 2, 21), 0.25, SALT_LAKE),
    date(2022, 12, 2): WarningDay(date(2022, 12, 2), 1.0, SALT_LAKE),
    date(2023, 2, 22): WarningDay(date(2023, 2, 22), 1.0, SALT_LAKE),
    date(2023, 2, 23): WarningDay(date(2023, 2, 23), 0.25, SALT_LAKE),
}


@pytest.mark.parametrize(
    ("text", "near", "days"),
    [
        (GRANITE_ROW, date(2023, 2, 22), {date(2023, 2, 22)}),
        (CANYONS_ROW, date(2022, 12, 3), {date(2022, 12, 2)}),
        ("Delayed Start to Class on Jan 26, 2026", date(2026, 1, 26), {date(2026, 1, 26)}),
        (ROMA_ROW, date(2026, 1, 26), {date(2026, 1, 26)}),
        (CANYONS_LATER, date(2023, 2, 26), {date(2023, 3, 6)}),
        (KINGSVILLE_ROW, date(2026, 1, 27), {date(2026, 1, 27)}),
        ("SYNTHETIC: closed 1/26/2026", date(2026, 1, 26), {date(2026, 1, 26)}),
        ("Delayed start Tuesday", date(2026, 1, 26), set()),
    ],
)
def test_pinned_days(text: str, near: date, days: set[date]) -> None:
    assert notices.pinned_days(text, near) == days


@pytest.mark.parametrize(
    ("day", "off"),
    [
        (date(2022, 2, 21), True),  # Presidents' Day
        (date(2024, 1, 15), True),  # Martin Luther King Jr. Day
        (date(2023, 11, 22), True),  # the Wednesday before Thanksgiving
        (date(2021, 12, 30), True),  # the winter holidays
        (date(2023, 2, 25), True),  # a Saturday
        (date(2023, 5, 29), True),  # Memorial Day
        (date(2023, 2, 22), False),
        (date(2022, 12, 2), False),
        (date(2026, 1, 26), False),
    ],
)
def test_school_break(day: date, off: bool) -> None:
    assert notices.school_break(day) is off


def test_a_notice_up_days_later_and_one_naming_two_days_are_corroborated() -> None:
    # Converse County's Winter Storm Warning of 2021-10-13; Putnam County's Hurricane Warning
    # (Irma) of 2017-09-11, none on the 8th; Ravalli County's advisory of 2019-02-15.
    converse = {date(2021, 10, 13): WarningDay(date(2021, 10, 13), 1.0, "56009")}
    putnam = {date(2017, 9, 11): WarningDay(date(2017, 9, 11), 1.0, "12107")}
    darby = {date(2019, 2, 15): WarningDay(date(2019, 2, 15), 0.25, "30081")}
    assert (
        notices.dated_closing(CONVERSE_ROW, None, CONVERSE_AT, converse)
        == converse[date(2021, 10, 13)]
    )
    assert notices.dated_closing(PUTNAM_ROW, None, PUTNAM_AT, putnam) == putnam[date(2017, 9, 11)]
    stormy = {day: WarningDay(day, 1.0, "30081") for day in darby}
    assert notices.dated_closing(DARBY_ROW, None, DARBY_AT, stormy) is None  # a holiday


def test_a_storm_days_unexplained_closing_is_corroborated_by_its_warning() -> None:
    warning = notices.dated_closing(GRANITE_ROW, GRANITE_ROW, GRANITE_AT, SALT_LAKE_DAYS)
    assert warning == WarningDay(date(2023, 2, 22), 1.0, SALT_LAKE)
    # the page-text rule alone reads no reason in it
    assert not notices.page_text_proves(GRANITE_ROW)
    canyons = notices.dated_closing(CANYONS_ROW, None, CANYONS_AT, SALT_LAKE_DAYS)
    assert canyons is not None
    assert canyons.day == date(2022, 12, 2)


@pytest.mark.parametrize(
    ("text", "at", "why"),
    [
        (GRANITE_DELAY, GRANITE_NEXT_AT, "an advisory alone"),
        (CANYONS_HOLIDAY, CANYONS_HOLIDAY_AT, "Presidents' Day"),
        ("No School, April 4-8", datetime(2022, 4, 11, 2, 21, 18, tzinfo=UTC), "a run of days"),
        (
            "There is NO Early Out Thursday, February 14th. It is a regular school day!",
            datetime(2019, 2, 14, 4, 40, tzinfo=UTC),
            "an ordinary day",
        ),
        (
            "WCSD# 1 will have a 2 hour late start February 18th and 19th.",
            datetime(2025, 3, 17, 18, 15, tzinfo=UTC),
            "two days, a month old",
        ),
        (GRANITE_ROW, datetime(2023, 3, 2, 5, 0, tzinfo=UTC), "read a week after its day"),
        ("Inclement Weather Closure Procedures", GRANITE_AT, "no day, no closing notice"),
        (
            "San Benito CISD will be CLOSED Thursday, January 20 and Friday, January 21, "
            "2022 due to COVID-related health and safety issues.",
            datetime(2022, 1, 20, 20, 33, tzinfo=UTC),
            "another reason",
        ),
    ],
)
def test_what_a_warning_does_not_corroborate(text: str, at: datetime, why: str) -> None:
    # SYNTHETIC: every day of these weeks under a Winter Storm Warning, so only the rule decides.
    stormy = {
        day: WarningDay(day, 1.0, SALT_LAKE)
        for day in (
            date(2019, 2, 14),
            date(2025, 2, 18),
            date(2025, 2, 19),
            date(2022, 4, 4),
            date(2023, 2, 22),
            date(2022, 1, 20),
            date(2022, 1, 21),
        )
    }
    days = SALT_LAKE_DAYS if why in {"an advisory alone", "Presidents' Day"} else stormy
    assert notices.dated_closing(text, None, at, days) is None, why


def test_warning_days_take_the_strongest_county() -> None:
    granite = REGISTRY.stations["district-homepage-granite-ut"]
    assert granite.counties is not None
    assert list(granite.counties.fips) == [SALT_LAKE]
    # SYNTHETIC: county days.
    counties = {SALT_LAKE: {date(2023, 2, 22): 1.0, date(2023, 2, 23): 0.25}}
    found = warning_days(REGISTRY, counties)
    assert found["district-homepage-granite-ut"][date(2023, 2, 22)] == WarningDay(
        date(2023, 2, 22), 1.0, SALT_LAKE
    )


@dataclass(frozen=True)
class _Proof:
    """SYNTHETIC: the fields of a proof the gate reads."""

    source_id: str
    mode: str
    url: str
    captured_at: datetime
    variant: str
    basis: str


def test_the_gate_keeps_a_corroborated_proof_and_lists_its_warning(tmp_path: Path) -> None:
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        json.dumps(
            {
                "source_id": "district-homepage-granite-ut",
                "fetched_at": "2023-02-22T05:37:20Z",
                "raw_name": GRANITE_ROW,
                "raw_status": GRANITE_ROW,
                "raw_updated_text": None,
                "raw_extra": {"section": notices.PAGE_TEXT},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    item = _Proof(
        "district-homepage-granite-ut",
        "archive",
        "https://www.graniteschools.org/",
        GRANITE_AT,
        "district-homepage-text",
        "archive reads",
    )
    without = {"district-homepage-granite-ut": [item]}
    notices.gate_proofs(without, REGISTRY, live_rows=[], archive_rows=[rows], fixtures=None)
    assert without["district-homepage-granite-ut"] == []
    proofs = {"district-homepage-granite-ut": [item]}
    report = notices.gate_proofs(
        proofs,
        REGISTRY,
        live_rows=[],
        archive_rows=[rows],
        fixtures=None,
        warnings={"district-homepage-granite-ut": SALT_LAKE_DAYS},
    )
    assert proofs["district-homepage-granite-ut"] == [item]
    entry = report["district-homepage-granite-ut"]
    assert isinstance(entry, dict)
    kept = entry["kept_proofs"]
    assert isinstance(kept, list)
    assert isinstance(kept[0], dict)
    assert kept[0]["warning"] == {"day": "2023-02-22", "weight": 1.0, "county": SALT_LAKE}
    assert entry["corroborated"] == kept
    # SYNTHETIC: a coverage result whose Granite proof is the corroborated capture.
    result: dict[str, JSONValue] = {
        "stations": {
            "district-homepage-granite-ut": {
                "proof": {"captured_at": "2023-02-22T05:37:20Z", "url": item.url, "rows": 1}
            }
        }
    }
    notices.annotate_warnings(result, report)
    stations = result["stations"]
    assert isinstance(stations, dict)
    granite = stations["district-homepage-granite-ut"]
    assert isinstance(granite, dict)
    assert granite["proof"] == {
        "captured_at": "2023-02-22T05:37:20Z",
        "url": item.url,
        "rows": 1,
        "warning": {"day": "2023-02-22", "weight": 1.0, "county": SALT_LAKE},
    }


def test_the_granite_storm_capture_proves_through_its_adapter_and_the_rule() -> None:
    body = (FIXTURES / "gate" / "district" / "granite-20230222.html").read_bytes()
    listing = adapter_for("district-homepage")(body)
    rows = [(row.name, row.status, row.extra.get("section")) for row in listing.rows]
    assert rows == [(GRANITE_ROW, GRANITE_ROW, notices.PAGE_TEXT)]
    status, title = notices.row_text(GRANITE_ROW, GRANITE_ROW, listing.variant, notices.PAGE_TEXT)
    assert not notices.row_qualifies(
        GRANITE_ROW, GRANITE_ROW, listing.variant, section=notices.PAGE_TEXT
    )
    assert (
        notices.dated_closing(status, title, GRANITE_AT, SALT_LAKE_DAYS)
        == SALT_LAKE_DAYS[date(2023, 2, 22)]
    )

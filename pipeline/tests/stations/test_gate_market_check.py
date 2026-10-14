"""A county across a state line is evidenced only by a row naming a place in it.

KNEB's rows below are REAL (weatherthreat-kneb, archived capture of 2023-01-18T12:33:48Z:
every row names a Nebraska Panhandle place in its ``location``). Place names and shares
marked SYNTHETIC are made up for these tests.
"""

from datetime import UTC, datetime

from snowlight.output import JSONValue
from snowlight.sources.stations import coverage, gate, notices, observed
from snowlight.sources.stations.model import RawRow
from snowlight.sources.stations.registry import load_registry

KNEB_ROWS = [  # name, location
    ("WESTERN COMMUNITY COLLEGE AREA BOARD OF GOVERNORS", "Scottsbluff"),
    ("CITY OF GERING", "Gering"),
    ("SIDNEY PUBLIC SCHOOLS", "Sidney"),
    ("KIMBALL PUBLIC SCHOOLS", "Kimball"),
]
WHEN = datetime(2023, 1, 18, 12, 33, 48, tzinfo=UTC)
NE, WY, CO = "31", "56", "08"

# SYNTHETIC: a few directory places (city, district, county FIPS)
PLACES = observed.PlaceIndex.build(
    [
        ("Scottsbluff", "Scottsbluff Public Schools", "31157"),
        ("Gering", "Gering Public Schools", "31157"),
        ("Sidney", "Sidney Public Schools", "31033"),
        ("Kimball", "Kimball Public Schools", "31105"),
        ("Torrington", "Goshen County School District #1", "56015"),
        ("Torrington", "Torrington Public Schools", "09005"),  # Torrington, Connecticut
        ("Cheyenne", "Laramie County School District #1", "56021"),
        ("Laramie", "Albany County School District #1", "56001"),
        ("Sheridan", "Sheridan County School District #2", "56033"),
        ("Sheridan", "Sheridan School District 2", "08005"),  # Sheridan, Colorado
        ("Story", "Sheridan County School District #2", "56033"),
        (None, "Goshen County", "56015"),
        (None, "Laramie County", "56021"),
    ]
)


def _rows(source: str, pairs: list[tuple[str, str]]) -> list[RawRow]:
    return [
        RawRow(
            source_id=source,
            fetched_at=WHEN,
            raw_name=name,
            raw_status="Closed",
            raw_updated_text=None,
            raw_extra={"location": place},
        )
        for name, place in pairs
    ]


def test_a_location_field_names_its_county() -> None:
    seen = observed.observe(
        _rows("weatherthreat-kneb", KNEB_ROWS),
        [],
        {},
        places=PLACES,
        scopes={"weatherthreat-kneb": frozenset({NE, WY})},
    )
    kneb = seen["weatherthreat-kneb"]
    assert kneb.counties == {"31157", "31033", "31105"}
    assert kneb.named["31157"].endswith("| Scottsbluff")
    # no Wyoming county: the radio list's rows named only Nebraska places
    assert not {fips for fips in kneb.counties if fips.startswith(WY)}


def test_a_place_two_counties_carry_in_scope_names_neither() -> None:
    both = frozenset({CO, WY})
    assert PLACES.named("Sheridan Schools", both) == set()
    assert PLACES.named("Sheridan Schools", frozenset({WY})) == {"56033"}
    # Torrington is Connecticut's too, but not within a Nebraska and Wyoming list's states
    assert PLACES.named("Torrington Middle School", frozenset({NE, WY})) == {"56015"}
    # the longest name present is read: the district, not the city of Laramie
    assert PLACES.named("Laramie County School District #1 closed", frozenset({WY})) == {"56021"}
    # a town whose name is a common word is never read alone
    assert PLACES.named("A story of the storm", frozenset({WY})) == set()


def test_a_cross_state_county_no_row_named_is_a_market_assumption() -> None:
    registry = load_registry()
    state_fips = {"NE": NE, "WY": WY}
    seen = {"weatherthreat-kneb": observed.Observed(rows=22, counties={"31157", "31033"})}
    found = coverage.market_assumptions(registry, seen, state_fips)
    assert found["weatherthreat-kneb"] == ["56015", "56021"]
    # a row naming a Torrington school would evidence Goshen County, not Laramie County
    seen["weatherthreat-kneb"].counties.add("56015")
    found = coverage.market_assumptions(registry, seen, state_fips)
    assert found["weatherthreat-kneb"] == ["56021"]
    # with no row named at all, the home state is the market's first: Cheyenne's, WY
    found = coverage.market_assumptions(registry, {}, state_fips)
    assert found["weatherthreat-kneb"] == ["31157"]


def test_without_counties_trims_a_copy() -> None:
    registry = load_registry()
    trimmed = coverage.without_counties(registry, {"weatherthreat-kneb": ["56015", "56021"]})
    kneb = trimmed.stations["weatherthreat-kneb"].counties
    assert kneb is not None
    assert kneb.fips == ("31157",)
    original = registry.stations["weatherthreat-kneb"].counties
    assert original is not None
    assert original.fips == ("31157", "56015", "56021")
    gone = coverage.without_counties(registry, {"weatherthreat-kneb": ["31157", "56015", "56021"]})
    assert gone.stations["weatherthreat-kneb"].counties is None


def _share(covered: int, schools: int, weighted: float) -> dict[str, JSONValue]:
    return {
        "schools": schools,
        "covered": covered,
        "share": round(covered / schools, 4),
        "meets_target": covered / schools >= coverage.STATE_TARGET,
        "weighted": {
            "schools": 100.0,
            "covered": weighted * 100,
            "share": weighted,
            "meets_target": weighted >= coverage.STATE_TARGET,
        },
    }


def test_the_owner_gate_states_wyoming_with_and_without_market_credits() -> None:
    # SYNTHETIC shares in coverage.json's shape; Wyoming's counts are 2026-10-13's
    proven = {"WY": _share(334, 389, 0.8776), "ID": _share(898, 906, 0.9863)}
    proven["GA"] = _share(2652, 2932, 0.9073)
    checked: dict[str, JSONValue] = {
        "rule": "rows seen",
        "national": {"weighted": {"share": 0.9367}},
        "states": {
            "WY": _share(100, 389, 0.2904),
            "ID": _share(695, 906, 0.6296),
            "GA": _share(2576, 2932, 0.8693),
        },
        "assumed": {"weatherthreat-kneb": ["56015", "56021"], "nexstar-kdvr": ["56001"]},
    }
    counties: dict[str, JSONValue] = {
        "56015": {"state": "WY", "schools": 12},
        "56021": {"state": "WY", "schools": 45},
        "56001": {"state": "WY", "schools": 20},
    }
    proven_counties: dict[str, JSONValue] = {
        "56015": {"proven": ["weatherthreat-kneb"]},
        "56021": {"proven": ["weatherthreat-kneb", "edlio-lcsd2-wy"]},
        "56001": {"proven": []},  # KDVR's credit there is not a proven station's
    }
    found = gate.owner_gate(
        proven,
        {},
        {"weighted": {"share": 0.9701}},
        checked=checked,
        counties=counties,
        proven_counties=proven_counties,
    )
    dig = found["dig"]
    assert isinstance(dig, list)
    wyoming = next(line for line in dig if isinstance(line, dict) and line["state"] == "WY")
    check = wyoming["market_checked"]
    assert isinstance(check, dict)
    assert check["share"] == 0.2571
    assert check["meets"] is False
    assert check["assumed_credits"] == [
        {"station": "weatherthreat-kneb", "counties": ["56015", "56021"], "schools": 57}
    ]
    national = found["national"]
    assert isinstance(national, dict)
    assert national["market_checked_weighted_share"] == 0.9367
    kept = found["kept"]
    assert isinstance(kept, dict)
    assert kept["thin"] == [
        {"state": "GA", "share": 0.9045, "weighted_share": 0.9073, "schools_above_target": 13}
    ]
    assert kept["market_checked_short"] == [
        {"state": "GA", "share": 0.8786, "weighted_share": 0.8693}
    ]
    text = "\n".join(gate._owner_lines({"owner_gate": found}))
    assert "WY: counting a county across a state line only where" in text
    assert "`weatherthreat-kneb`: 56015, 56021 (57 schools)" in text
    assert "Kept, thin: GA is proven 90.4% (90.7% closure-weighted), 13 schools above the" in text
    assert "National: with no county credited across a state line by a market alone, 93.6%" in text


def test_every_table_the_gate_writes_cuts_its_percentages() -> None:
    # Wyoming's 334 of 389 is 85.861%: never printed as 85.9%
    wyoming = _share(334, 389, 0.8776)
    assert gate._percent(wyoming) == "85.8%"
    assert gate._weighted_percent(wyoming) == "87.7%"
    section = gate.gate_section(
        {
            "generated_at": "2026-10-13T21:00:00Z",
            "coverage": {"generated_at": "2026-10-13T20:00:00Z"},
            "national": {
                "proven": {"share": 0.8537, "weighted": {"share": 0.97006}},
                "to_target": {"schools": 1, "weighted": 1},
            },
            "states": {"WY": {"proven": wyoming, "meets_target": False, "stations": []}},
            "stations": {},
        }
    )
    assert "| WY | 85.8% | 87.7% |" in section
    assert "85.9%" not in section
    assert "97.0% closure-weighted" in section


# A list seen only with the pandemic's closings ----------------------------------------

KMVT_2022 = notices.GateRow(  # REAL: gray-kmvt, archived 2022-01-27T21:34:30Z
    "North Valley Academy",
    "Closed Through Monday",
    None,
    "2022-01-27 13:37:53",
    '["Health Concerns"]',
)
KMVT_2020 = notices.GateRow(  # REAL: gray-kmvt, archived 2020-03-20T02:29:35Z
    "Bliss Schools", "Closed Through Monday 3/30", None, "2020-03-17 06:52:13", "Health Concerns"
)


def test_a_list_read_of_the_first_wave_or_of_health_closings_is_the_pandemics() -> None:
    assert notices.pandemic_read([KMVT_2020], datetime(2020, 3, 20, 2, 29, 35, tzinfo=UTC))
    assert notices.pandemic_read([KMVT_2022], datetime(2022, 1, 27, 21, 34, 30, tzinfo=UTC))
    snow = notices.GateRow("Bliss Schools", "Closed", None)  # SYNTHETIC: a closing, no reason
    assert not notices.pandemic_read(
        [KMVT_2022, snow], datetime(2022, 1, 27, 21, 34, 30, tzinfo=UTC)
    )
    assert not notices.pandemic_read([], datetime(2022, 1, 27, tzinfo=UTC))


def test_the_owner_gate_states_idaho_without_its_pandemic_only_list() -> None:
    proven = {"ID": _share(898, 906, 0.9863), "WY": _share(334, 389, 0.8776)}
    pandemic: dict[str, JSONValue] = {
        "rule": "pandemic reads only",
        "stations": ["gray-kmvt"],
        "states": {"ID": _share(779, 906, 0.8654), "WY": _share(334, 389, 0.8776)},
    }
    found = gate.owner_gate(proven, {}, {"weighted": {"share": 0.97}}, pandemic=pandemic)
    dig = found["dig"]
    assert isinstance(dig, list)
    lines = {line["state"]: line for line in dig if isinstance(line, dict)}
    idaho = lines["ID"]["pandemic_checked"]
    assert isinstance(idaho, dict)
    assert idaho["share"] == 0.8598
    assert lines["WY"]["pandemic_checked"] is None  # no such list counts in Wyoming
    text = "\n".join(gate._owner_lines({"owner_gate": found}))
    assert "ID: without the proven lists never seen holding a closing but the pandemic's" in text
    assert "proven 85.9% (779 of 906 schools), 86.5% closure-weighted" in text


def test_a_first_hand_records_proof_block_follows_todays_coverage() -> None:
    # Palm Beach's record of round 1 said proven on a storm-information link (2024-10-10);
    # SYNTHETIC coverage of today: the notice gate dropped it, so the station is unproven.
    record: dict[str, JSONValue] = {
        "source_id": "PALM BEACH (FL)",
        "gap_state": "FL",
        "built_as": ["finalsite-palm-beach-fl"],
        "proof": {"finalsite-palm-beach-fl": {"state": "working", "proven": True}},
    }
    result: dict[str, JSONValue] = {
        "generated_at": "2026-10-13T21:00:00Z",
        "stations": {"finalsite-palm-beach-fl": {"state": "working", "proof": None}},
        "unproven": [{"id": "finalsite-palm-beach-fl"}],
        "district_notice_gate": {
            "finalsite-palm-beach-fl": {
                "kind": "channel",
                "kept": 0,
                "dropped_count": 2,
                "dropped": [
                    {
                        "captured_at": "2024-10-10T02:50:56Z",
                        "mode": "archive",
                        "row": "Learn more about the storm, including shelter information",
                        "reason": "no row announces a closing",
                        "url": "https://www.palmbeachschools.org/",
                    }
                ],
            }
        },
    }
    merged = gate.merge_records([record], [], None, result)
    assert isinstance(merged[0], dict)
    proof = merged[0]["proof"]
    assert isinstance(proof, dict)
    palm = proof["finalsite-palm-beach-fl"]
    assert isinstance(palm, dict)
    assert palm["proven"] is False
    assert palm["as_of"] == "2026-10-13T21:00:00Z"
    assert palm["evidence"] is None
    notice = palm["notice_gate"]
    assert isinstance(notice, dict)
    assert notice["dropped"] == 2
    # and a station that is in error is not proven, whatever its old proof
    result["stations"] = {"finalsite-palm-beach-fl": {"state": "error", "proof": {"rows": 1}}}
    result["unproven"] = []
    again = gate.merge_records([record], [], None, result)[0]
    assert isinstance(again, dict)
    block = again["proof"]
    assert isinstance(block, dict)
    entry = block["finalsite-palm-beach-fl"]
    assert isinstance(entry, dict)
    assert entry["proven"] is False
    assert entry["state"] == "error"

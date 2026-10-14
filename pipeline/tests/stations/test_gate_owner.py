"""The owner's coverage gate of 2026-10-13: dig Idaho and Wyoming to 90%, keep the rest.

Shares here are SYNTHETIC unless noted: they are made up for these tests, in the shape
``coverage.json`` gives them (a state's proven share and its closure-weighted part).
"""

from snowlight.output import JSONValue
from snowlight.sources.stations import coverage, gate


def _share(plain: float, weighted: float, schools: int = 100) -> dict[str, JSONValue]:
    return {
        "schools": schools,
        "covered": round(plain * schools),
        "share": plain,
        "weighted": {"schools": schools, "covered": weighted * schools, "share": weighted},
    }


def _states(**overrides: tuple[float, float]) -> dict[str, JSONValue]:
    shares: dict[str, tuple[float, float]] = {
        "ID": (0.95, 0.95),
        "WY": (0.91, 0.92),
        "TX": (0.913, 0.95),
        "UT": (1.0, 1.0),
        "CA": (0.173, 0.70),
        "FL": (0.68, 0.68),
        "AZ": (0.77, 0.87),
        "LA": (0.77, 0.78),
        "MS": (0.71, 0.69),
        "NV": (0.35, 0.87),
    }
    shares.update(overrides)
    return {code: _share(*pair) for code, pair in shares.items()}


NATIONAL: dict[str, JSONValue] = {"share": 0.867, "weighted": {"share": 0.977}}


def test_the_gate_passes_when_idaho_and_wyoming_reach_ninety_and_the_rest_hold() -> None:
    proven = _states()
    covered = _states(CA=(0.98, 0.99))
    found = gate.owner_gate(proven, covered, NATIONAL)
    assert found["passes"] is True
    assert found["decided_on"] == "2026-10-13"
    dig = found["dig"]
    assert isinstance(dig, list)
    assert [line["state"] for line in dig if isinstance(line, dict)] == ["ID", "WY"]
    rare = found["rare"]
    assert isinstance(rare, list)
    assert {line["state"] for line in rare if isinstance(line, dict)} == {
        "AZ",
        "CA",
        "FL",
        "LA",
        "MS",
        "NV",
    }
    california = next(line for line in rare if isinstance(line, dict) and line["state"] == "CA")
    assert california["note"] == gate.NOT_PURSUED
    assert california["meets"] is False
    assert california["missing"] == {"uncovered": 2, "covered_unproven": 81}
    sentence = gate.state_sentence(california)
    assert "17.3%" in sentence
    assert "81 covered by sources never seen holding a closing" in sentence


def _line(found: dict[str, JSONValue], code: str) -> dict[str, JSONValue]:
    dig = found["dig"]
    assert isinstance(dig, list)
    line = next(item for item in dig if isinstance(item, dict) and item["state"] == code)
    assert isinstance(line, dict)
    return line


def _wyoming(proven_schools: int, weighted_part: float) -> dict[str, JSONValue]:
    # Wyoming's 389 schools and 952.5 weighted schools, as coverage.json gives them.
    return coverage._share(389, proven_schools, coverage.STATE_TARGET, (952.5, weighted_part))


def test_wyoming_meets_on_the_figures_the_owner_accepted() -> None:
    # Wyoming's measured shares at the decision: 334 of 389 plain (0.8586), 835.9 of 952.5
    # weighted (0.8776), both under 90%, accepted by the owner on 2026-10-13.
    proven = _states()
    proven["WY"] = _wyoming(334, 835.9)
    found = gate.owner_gate(proven, _states(), NATIONAL)
    assert found["passes"] is True
    wyoming = _line(found, "WY")
    assert wyoming["meets"] is True
    accepted = wyoming["accepted"]
    assert isinstance(accepted, dict)
    assert accepted["note"] == "accepted: owner decision 2026-10-13"
    assert accepted["decided_on"] == "2026-10-13"
    assert accepted["quote"] == "yea call it done nw"
    assert accepted["plain"] == 0.858
    assert accepted["weighted"] == 0.877
    assert accepted["plain_measured"] == "85.8% (334 of 389 schools)"
    assert accepted["weighted_measured"] == "87.7%"
    assert str(wyoming["rule"]) == (
        "proven at least 85.8% plain and 87.7% closure-weighted, "
        "accepted: owner decision 2026-10-13 (target 90.0%)"
    )


def test_the_gate_stores_wyomings_accepted_figures() -> None:
    accepted = gate.OWNER_GATE.accepted
    assert set(accepted) == {"WY"}
    wyoming = accepted["WY"]
    assert (wyoming.decided_on.isoformat(), wyoming.plain, wyoming.weighted) == (
        "2026-10-13",
        0.858,
        0.877,
    )
    assert wyoming.quote == "yea call it done nw"


def test_wyoming_dropping_below_its_accepted_plain_share_fails() -> None:
    proven = _states()
    proven["WY"] = _wyoming(333, 835.9)  # 85.6% plain
    found = gate.owner_gate(proven, _states(), NATIONAL)
    assert _line(found, "WY")["meets"] is False
    assert found["passes"] is False


def test_wyoming_dropping_below_its_accepted_weighted_share_fails() -> None:
    proven = _states()
    proven["WY"] = _wyoming(334, 835.0)  # 87.66% weighted
    found = gate.owner_gate(proven, _states(), NATIONAL)
    assert _line(found, "WY")["meets"] is False
    assert found["passes"] is False
    found = gate.owner_gate(_states(WY=(0.889, 0.8769)), _states(), NATIONAL)
    assert found["passes"] is False


def test_an_accepted_figure_is_met_exactly_and_never_by_rounding() -> None:
    # 858 of 1000 meets 85.8% exactly; 85799 of 100000 is stored as 0.858 by coverage's
    # rounding, but its counts fall short, so it fails.
    proven = _states()
    proven["WY"] = coverage._share(1000, 858, coverage.STATE_TARGET, (1000.0, 877.0))
    assert _line(gate.owner_gate(proven, _states(), NATIONAL), "WY")["meets"] is True
    wyoming = coverage._share(100000, 85799, coverage.STATE_TARGET, (1000.0, 877.0))
    assert wyoming["share"] == 0.858
    proven["WY"] = wyoming
    assert _line(gate.owner_gate(proven, _states(), NATIONAL), "WY")["meets"] is False


def test_wyoming_reaching_ninety_meets_as_without_the_acceptance() -> None:
    found = gate.owner_gate(_states(WY=(0.91, 0.92)), _states(), NATIONAL)
    assert _line(found, "WY")["meets"] is True


def test_idaho_still_needs_ninety_plain_and_weighted() -> None:
    found = gate.owner_gate(_states(ID=(0.899, 0.95)), _states(), NATIONAL)
    assert found["passes"] is False
    idaho = _line(found, "ID")
    assert idaho["meets"] is False
    assert idaho["accepted"] is None
    found = gate.owner_gate(_states(ID=(0.95, 0.899)), _states(), NATIONAL)
    assert _line(found, "ID")["meets"] is False


def test_the_shares_are_kept_exactly_and_never_rounded_up() -> None:
    proven = _states()
    proven["WY"] = _share(0.89996, 0.95, schools=100000)
    found = gate.owner_gate(proven, _states(), NATIONAL)
    wyoming = _line(found, "WY")
    share = wyoming["proven"]
    assert isinstance(share, dict)
    assert share["share"] == 0.89996
    accepted = wyoming["accepted"]
    assert isinstance(accepted, dict)
    assert str(accepted["plain_measured"]).startswith("89.9% (")
    assert gate.percent(0.89996) == "89.9%"
    assert gate.percent(0.8895) == "88.9%"
    assert gate.percent(0.9) == "90.0%"


def test_the_section_says_wyomings_shares_were_accepted() -> None:
    proven = _states()
    proven["WY"] = _wyoming(334, 835.9)
    owner = gate.owner_gate(proven, _states(), NATIONAL)
    text = "\n".join(gate._owner_lines({"owner_gate": owner}))
    assert (
        "| dig to 90%; accepted: owner decision 2026-10-13 at 85.8% / 87.7% | WY | 85.8% | "
        "87.7% | yes |"
    ) in text
    assert "| dig to 90% | ID |" in text
    assert (
        '- WY: accepted by the owner on 2026-10-13 ("yea call it done nw") at 85.8% proven '
        "plain and 87.7% closure-weighted, under the 90.0% target"
    ) in text
    assert "Measured: 85.8% (334 of 389 schools), 87.7% closure-weighted." in text


def test_a_kept_state_falling_under_ninety_fails_the_gate() -> None:
    found = gate.owner_gate(_states(TX=(0.899, 0.95)), _states(), NATIONAL)
    assert found["passes"] is False
    kept = found["kept"]
    assert isinstance(kept, dict)
    short = kept["short"]
    assert isinstance(short, list)
    assert [line["state"] for line in short if isinstance(line, dict)] == ["TX"]


def test_the_national_weighted_share_must_hold_ninety_five() -> None:
    found = gate.owner_gate(_states(), _states(), {"weighted": {"share": 0.949}})
    assert found["passes"] is False
    national = found["national"]
    assert isinstance(national, dict)
    assert national["meets"] is False


def test_rare_states_never_count_for_or_against_the_gate() -> None:
    found = gate.owner_gate(_states(CA=(0.01, 0.01), FL=(0.0, 0.0)), _states(), NATIONAL)
    assert found["passes"] is True


def test_a_rare_states_record_says_the_decision_first() -> None:
    line = gate.owner_gate(_states(), _states(), NATIONAL)["rare"]
    assert isinstance(line, list)
    florida = next(item for item in line if isinstance(item, dict) and item["state"] == "FL")
    assert isinstance(florida, dict)
    report: dict[str, JSONValue] = {"owner_gate": {"rare": [florida]}}
    lines = gate.rare_lines(report)
    record = gate._not_pursued({"notes": "storm-read.", "gate": {"piece": "s4"}}, lines["FL"])
    assert record["owner_decision"] == gate.NOT_PURSUED
    notes = record["notes"]
    assert isinstance(notes, str)
    assert notes.startswith(gate.NOT_PURSUED)
    block = record["gate"]
    assert isinstance(block, dict)
    assert block["owner_gate"] == florida


def test_the_section_states_the_owner_gate() -> None:
    owner = gate.owner_gate(_states(), _states(), NATIONAL)
    lines = gate._owner_lines({"owner_gate": owner})
    text = "\n".join(lines)
    assert "dig for 90%+ of Idaho and Wyoming and leave it there" in text
    assert "**passes**" in text
    assert text.count(gate.NOT_PURSUED) == 12  # a table row and a sentence per rare state


def test_every_first_hand_record_of_a_rare_state_carries_the_decision() -> None:
    owner = gate.owner_gate(_states(), _states(), NATIONAL)
    rare = gate.rare_lines({"owner_gate": owner})
    first_hand: list[dict[str, JSONValue]] = [
        {"source_id": "ST. LUCIE", "gap_state": "FL", "notes": "not built", "states": ["FL"]},
        {"source_id": "KTVB", "gap_state": "ID", "notes": "a list", "states": ["ID"]},
        {"source_id": "x", "gap_state": "WY", "gate": {"piece": "s4"}},
    ]
    merged = gate.merge_records(first_hand, [], rare)
    assert len(merged) == 2  # this piece's earlier gate record is replaced (by none here)
    florida, idaho = merged
    assert isinstance(florida, dict)
    assert isinstance(idaho, dict)
    assert florida["owner_decision"] == gate.NOT_PURSUED
    assert str(florida["owner_gate_state"]).startswith("FL: 100 schools")
    assert florida["notes"] == "not built"
    assert "owner_decision" not in idaho


def test_a_share_coverage_rounds_up_to_the_target_still_fails() -> None:
    # coverage.json rounds every share to four decimals: a true 89.997% weighted is stored
    # as 0.9, a true 94.9996% national as 0.95. The gate decides on what is exact.
    idaho = coverage._share(906, 898, coverage.STATE_TARGET, (1495.9, 1495.9 * 0.89997))
    weighted = idaho["weighted"]
    assert isinstance(weighted, dict)
    assert weighted["share"] == 0.9
    assert weighted["meets_target"] is False
    proven = _states()
    proven["ID"] = idaho
    found = gate.owner_gate(proven, _states(), NATIONAL)
    assert _line(found, "ID")["meets"] is False
    assert found["passes"] is False

    national = coverage._share(
        100000, 86000, coverage.NATIONAL_TARGET, (100000.0, 100000.0 * 0.949996)
    )
    inner = national["weighted"]
    assert isinstance(inner, dict)
    assert inner["share"] == 0.95
    found = gate.owner_gate(_states(), _states(), national)
    national_line = found["national"]
    assert isinstance(national_line, dict)
    assert national_line["meets"] is False
    assert found["passes"] is False


def test_a_plain_share_is_decided_on_its_counts() -> None:
    # 89996 of 100000 schools is stored as 0.9 by coverage's rounding; Idaho fails.
    idaho = coverage._share(100000, 89996, coverage.STATE_TARGET, (100.0, 95.0))
    assert idaho["share"] == 0.9
    assert idaho["meets_target"] is False
    proven = _states()
    proven["ID"] = idaho
    found = gate.owner_gate(proven, _states(), NATIONAL)
    assert _line(found, "ID")["meets"] is False
    # and a share that coverage did not judge is held to its counts all the same
    del idaho["meets_target"]
    found = gate.owner_gate(proven, _states(), NATIONAL)
    assert _line(found, "ID")["meets"] is False


def test_the_owner_gate_uses_coverages_targets() -> None:
    assert gate.OWNER_GATE.state_target == coverage.STATE_TARGET
    assert gate.OWNER_GATE.national_weighted == coverage.NATIONAL_TARGET

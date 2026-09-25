"""Published codes never change meaning.

A code, once published, is read by every copy of the site still cached in a
browser. These tables pin every code: renumbering or renaming one fails here, and
a new member has to be added to both the enum and this table.
"""

from snowlight.schemas.vocab import NO_SCHOOL, REASON_BY_LABEL, SHIFTED, Reason, Status

STATUS_CODES = {"CLOSED": 0, "DELAYED": 1, "REMOTE": 2, "EARLY_DISMISSAL": 3}
REASON_CODES = {
    "WINTER_STORM": 0,
    "ICE": 1,
    "EXTREME_COLD": 2,
    "FLOODING": 3,
    "HURRICANE": 4,
    "SEVERE_STORMS": 5,
    "HEAT": 6,
    "POWER_OUTAGE": 7,
}


def test_status_codes_are_pinned() -> None:
    assert {member.name: member.value for member in Status} == STATUS_CODES


def test_reason_codes_are_pinned() -> None:
    assert {member.name: member.value for member in Reason} == REASON_CODES


def test_codes_are_dense_from_zero() -> None:
    for enum in (Status, Reason):
        assert sorted(member.value for member in enum) == list(range(len(enum)))


def test_status_groups() -> None:
    assert {Status.CLOSED, Status.REMOTE} == NO_SCHOOL
    assert {Status.DELAYED, Status.EARLY_DISMISSAL} == SHIFTED
    assert not NO_SCHOOL & SHIFTED
    assert set(Status) == NO_SCHOOL | SHIFTED


def test_reason_labels_map_one_to_one() -> None:
    assert len(set(REASON_BY_LABEL.values())) == len(REASON_BY_LABEL) == len(Reason)

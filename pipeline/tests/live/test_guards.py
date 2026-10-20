"""The guards' pure checks: holds, breaker limits, wording, and the publish gate (T10)."""

from datetime import timedelta

import pytest

from live.world import at
from snowlight.live.guards import (
    MAX_GZIP_BYTES,
    GateInput,
    Refusal,
    Rules,
    SpikeState,
    breaker_limit,
    gate_refusals,
    held,
    names_part,
    spike_hold,
    wording_reason,
)


def test_g13_holds() -> None:
    rules = Rules()
    now = at("2026-11-17 12:00")
    assert held(now - timedelta(minutes=45), now, boosted=True, rules=rules)
    assert not held(now - timedelta(minutes=46), now, boosted=True, rules=rules)
    assert held(now - timedelta(minutes=90), now, boosted=False, rules=rules)
    assert not held(now - timedelta(minutes=91), now, boosted=False, rules=rules)
    assert not held(None, now, boosted=True, rules=rules)
    assert not held(now + timedelta(minutes=1), now, boosted=True, rules=rules)


def test_g9_breaker_limits() -> None:
    assert breaker_limit("s", Rules()) == 50
    assert breaker_limit("s", Rules(breaker_limits={"s": 400})) == 1200


@pytest.mark.parametrize(
    ("text", "name", "remote", "found"),
    [
        ("Closed", "SYNTHETIC High", False, None),
        ("Closed - teacher work day", "SYNTHETIC High", False, "planned"),
        ("Closed", "SYNTHETIC TEST Listing", False, "planned"),
        ("Closed. Snow packet day, buses resume Wednesday", "SYNTHETIC", False, "learning"),
        ("Closed - Flexible Learning Day", "SYNTHETIC", False, "learning"),
        ("Closed - Digital Day", "SYNTHETIC", False, "learning"),
        ("Remote learning - Flex learning", "SYNTHETIC", True, None),
        ("Closed - SAT testing moved", "SYNTHETIC", False, "sat"),
        ("Closed Saturday", "SYNTHETIC", False, None),
        ("Closed Monday, 15th & 16th", "SYNTHETIC", False, "weekday_numbers"),
        ("Closed Monday 1/15", "SYNTHETIC", False, None),
    ],
)
def test_wording(text: str, name: str, remote: bool, found: str | None) -> None:
    assert wording_reason(text, name, remote=remote) == found


@pytest.mark.parametrize(
    ("text", "part"),
    [
        ("Closed", False),
        ("Closed - all campuses", False),
        ("Closed - Lincoln Elementary only", True),
        ("Intermediate schools closed", True),
        ("Bus routes 4 and 7 cancelled", True),
        ("Closed for the north side", True),
        ("2 hour delay for high schools", True),
    ],
)
def test_names_part(text: str, part: bool) -> None:
    assert names_part(text) is part


def _gate(**changes: object) -> GateInput:
    base: dict[str, object] = {
        "edition_ok": True,
        "healthy_share": 0.9,
        "previous_healthy_share": 0.9,
        "generated_at": at("2026-11-17 12:00"),
        "last_published": at("2026-11-17 11:55"),
        "now": at("2026-11-17 12:00"),
        "gzip_bytes": 1000,
    }
    base.update(changes)
    return GateInput(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "refusal"),
    [
        ({"edition_ok": False}, Refusal.EDITION),
        ({"healthy_share": 0.59}, Refusal.HEALTH),
        ({"healthy_share": 0.61, "previous_healthy_share": 1.3}, Refusal.HEALTH),
        ({"last_published": at("2026-11-17 12:00")}, Refusal.NOT_NEWER),
        ({"last_published": at("2026-11-17 12:05")}, Refusal.NOT_NEWER),
        ({"gzip_bytes": MAX_GZIP_BYTES + 1}, Refusal.OVERSIZE),
        (
            {"generated_at": at("2026-11-17 12:02"), "now": at("2026-11-17 12:00")},
            Refusal.CLOCK_AHEAD,
        ),
        ({"spike": True}, Refusal.SPIKE_HOLD),
        ({"valid": False}, Refusal.INVALID),
    ],
)
def test_t10_each_refusal_has_its_own_reason(changes: dict[str, object], refusal: Refusal) -> None:
    assert gate_refusals(_gate(**changes)) == [refusal]


def test_t10_a_good_pass_publishes() -> None:
    assert gate_refusals(_gate()) == []
    assert gate_refusals(_gate(last_published=None, previous_healthy_share=None)) == []


def test_t10e_spike_holds_once_then_publishes_on_confirmation() -> None:
    rows = frozenset((index, "2026-11-17") for index in range(2500))
    hold, state = spike_hold(
        lit_before=0, lit_now=2500, new_rows=rows, alert_share=0.1, pending=None
    )
    assert hold
    assert state == SpikeState(rows=rows)
    hold, state = spike_hold(
        lit_before=0, lit_now=2500, new_rows=rows, alert_share=0.1, pending=state
    )
    assert not hold
    assert state is None
    other = frozenset((index, "2026-11-17") for index in range(3000, 5600))
    hold, _ = spike_hold(
        lit_before=0, lit_now=2600, new_rows=other, alert_share=0.1, pending=SpikeState(rows)
    )
    assert hold
    assert spike_hold(lit_before=0, lit_now=2500, new_rows=rows, alert_share=0.6, pending=None) == (
        False,
        None,
    )
    assert spike_hold(
        lit_before=100, lit_now=2000, new_rows=rows, alert_share=0.0, pending=None
    ) == (
        False,
        None,
    )

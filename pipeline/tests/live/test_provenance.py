"""Source types for every platform (T20), provenance lines, and no raw text kept (T15a)."""

import json
import logging
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from live.world import (
    ALPHA,
    ALPHA_SCHOOL,
    EASTERN,
    PACIFIC,
    SPLIT,
    SynParsed,
    World,
    accepted,
    at,
    refused,
    row,
    station,
)
from snowlight.listed.build import GUARD_REASON
from snowlight.live.guards import Withheld
from snowlight.live.ledger import Ledger, Observed, norm
from snowlight.live.provenance import (
    PLATFORM_TYPES,
    PROVENANCE_KEYS,
    SourceType,
    provenance_line,
    source_type,
)
from snowlight.live.resolve import MATCH_REASONS, DayClaim, Derived, code
from snowlight.sources.stations.registry import load_registry

SOURCES = Path(__file__).resolve().parents[2] / "config" / "sources"


def test_t20_every_registry_platform_has_a_source_type() -> None:
    registry = load_registry(SOURCES)
    platforms = set(registry.platforms)
    assert platforms <= set(PLATFORM_TYPES), sorted(platforms - set(PLATFORM_TYPES))
    assert set(PLATFORM_TYPES) == platforms
    assert source_type("gray") is SourceType.BROADCASTER_LIST
    with pytest.raises(KeyError):
        source_type("unknown")


def test_provenance_lines_hold_exactly_their_keys() -> None:
    fields = dict.fromkeys(PROVENANCE_KEYS)
    assert provenance_line(fields) == fields
    with pytest.raises(ValueError, match="missing"):
        provenance_line({"school": 1})
    with pytest.raises(ValueError, match="unknown"):
        provenance_line({**fields, "raw_name": "x"})


MARK = "qzxmarkq"
"""A word in every raw name and text, and in no source id, code or school id."""


def test_t15a_no_raw_text_is_kept_or_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    names = {
        "school": f"SYNTHETIC {MARK.title()} Alpha Elementary",
        "district": f"SYNTHETIC {MARK.upper()} Alpha District",
        "dissent": f"SYNTHETIC {MARK} Pacific",
        "open": f"SYNTHETIC {MARK} Eastern",
        "located": f"SYNTHETIC {MARK} Elsewhere",
        "unknown": f"SYNTHETIC {MARK} Unknown Listing",
        "board": f"SYNTHETIC {MARK} Split",
    }
    texts = {
        "school": f"Closed due to snow {MARK.upper()}",
        "district": f"2 hour delay {MARK.title()}",
        "dissent": f"Closing rescinded {MARK}",
        "open": f"Open {MARK}",
        "located": f"Closed {MARK}",
        "unknown": f"Closed {MARK}",
        "board": f"Closed {MARK}",
    }
    world = World(
        ledger=Ledger(tmp_path / "ledger.sqlite"),
        stations={"gray-synthetic": station(), "gohsep-synthetic": station("gohsep-synthetic")},
    )
    table = world.matcher.table
    table[names["school"]] = accepted(direct=(ALPHA[0],))
    table[names["district"]] = accepted(via=ALPHA)
    table[names["dissent"]] = accepted(direct=(PACIFIC,))
    table[names["open"]] = accepted(direct=(EASTERN,))
    table[names["located"]] = refused(GUARD_REASON, best="x")
    table[names["board"]] = accepted(direct=(SPLIT,))
    observed: list[Observed] = []
    observe = world.ledger.observe

    def watched(*args: Any, **kwargs: Any) -> Observed:
        found = observe(*args, **kwargs)
        observed.append(found)
        return found

    world.ledger.observe = watched  # type: ignore[method-assign]
    station_rows = [row(names[part], texts[part]) for part in names if part != "board"]
    board = [row(names["board"], texts["board"], row_date=f"{MARK} 2026-11-17")]
    for source in world.stations:
        world.read(at("2026-11-17 02:00"), [], source=source)
        world.read(at("2026-11-17 11:00"), [], source=source)
    world.read(at("2026-11-17 11:05"), station_rows)
    world.read(at("2026-11-17 11:05"), board, source="gohsep-synthetic")
    resolved = world.resolve()
    merged = world.publish(at("2026-11-17 11:06"))
    assert merged.closings
    assert merged.opens
    without = [r for r in station_rows if r.name != names["district"]]
    world.read(at("2026-11-17 11:30"), without)  # the district row vanishes fast
    later = world.publish(at("2026-11-17 11:31"))
    assert later.fast_vanishes
    assert later.held_vanishes
    reasons_seen = {r.derived.withheld for source in world.resolve() for r in source.rows}
    assert {Withheld.LOCATED, Withheld.UNMATCHED, Withheld.NOTE, Withheld.BOARD_DATE} <= (
        reasons_seen
    )
    world.ledger.close()
    kept = [
        (tmp_path / "ledger.sqlite").read_bytes(),
        *(json.dumps(list(found.provenance), default=str).encode() for found in (merged, later)),
        json.dumps([signal.to_public_json() for signal in merged.opens]).encode(),
        json.dumps([signal.to_private_json() for signal in merged.opens]).encode(),
        json.dumps([dict(merged.withheld), dict(merged.counts)]).encode(),
        repr([later.fast_vanishes, later.held_vanishes, merged.opens]).encode(),
        json.dumps([dict(source.counts) for source in resolved]).encode(),
        repr(resolved).encode(),
        repr(observed).encode(),
        json.dumps([dict(found.counts) for found in observed]).encode(),
        repr(world.resolver().reader).encode(),
        caplog.text.encode(),
    ]
    raw = [*names.values(), *texts.values()]
    for blob in kept:
        folded = blob.lower()
        assert MARK.encode() not in folded
        for text in raw:
            assert norm(text).encode() not in folded
            assert text.encode() not in blob
    # Only the private unmatched queue holds a raw name.
    assert [query.name for source in resolved for query in source.unmatched] == [names["unknown"]]


def test_a_derivation_keeps_only_codes() -> None:
    with pytest.raises(ValueError, match="notes"):
        Derived(withheld=None, notes=(f"{MARK} words",)).to_json()
    with pytest.raises(ValueError, match="match_reason"):
        Derived(withheld=None, match_reason=f"alias|{MARK}").to_json()
    claim = DayClaim(date(2026, 11, 17), "closed", MARK, None, None, ufn=False)
    with pytest.raises(ValueError, match=r"claim\.reason"):
        Derived(withheld=None, claims=(claim,)).to_json()
    with pytest.raises(ValueError, match="source_type"):
        Derived.from_json({**Derived(withheld=None).to_json(), "source_type": MARK})
    assert code(f"alias|{MARK}", MATCH_REASONS) == "unknown"
    assert code("alias", MATCH_REASONS) == "alias"


def test_a_matcher_or_reader_that_returns_words_keeps_only_unknown() -> None:
    world = World()
    world.matcher.table[ALPHA_SCHOOL] = replace(
        accepted(direct=(ALPHA[0],)), reason=f"alias|{MARK}", level=MARK
    )
    base = world.reader

    def wordy(text: str, *, posted_at: datetime, tz: str) -> SynParsed:
        parsed = base(text, posted_at=posted_at, tz=tz)
        assert isinstance(parsed, SynParsed)
        return replace(parsed, notes=(*parsed.notes, f"{MARK} note"))

    world.reader = wordy
    world.read(at("2026-11-17 02:00"), [])
    world.read(at("2026-11-17 11:00"), [])
    world.read(at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)])
    (source,) = world.resolve()
    (result,) = source.rows
    assert result.derived.match_reason == "unknown"
    assert result.derived.match_level == "unknown"
    assert result.derived.withheld is Withheld.NOTE  # an unknown note is not an allowed one

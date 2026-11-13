"""Reason codes above 7 (ALL-CLOSINGS lane T): every live reader takes them, and read through
``as_dark`` they are the dark they replace. Today no code above 7 is written; these tests are
the revert test (a change log, a day timeline and a closings file holding codes 13 and 99 read
on this code) and the base sequences ``as_dark`` must give back. Every school, status and day
here is SYNTHETIC.

X is a closing for a code this code has no name for; W a weather closing. Each case gives a
school's change lines as the head would write them (X lit where the weather left the school
dark) and as the base writes them (the same moments, without X), and asserts that the head
read through ``as_dark`` (and ``as_dark_changes``) is the base, with a control school lit
for the weather in both.
"""

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from live.world import ALPHA, EASTERN, PACIFIC, directory
from snowlight.live.history import (
    BY,
    BY_HOLD,
    Change,
    ChangeLog,
    Event,
    Shown,
    as_dark_changes,
    seed_changes,
    timeline,
)
from snowlight.live.season import build_season, edition_ids
from snowlight.predict import dark_reads
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import (
    REASON_CODE_MAX,
    Closing,
    ClosingsFile,
    DayTimeline,
    as_dark,
    as_dark_closings,
    named_reason,
)
from snowlight.schemas.vocab import Detail, Reason, Status

WORLD = directory()
STAMP = DirectoryStamp(generated_on=date(2026, 10, 14), schools=11, districts=6)
DAY = date(2026, 11, 18)
MADE = datetime(2026, 11, 20, tzinfo=UTC)
SCHOOL, CONTROL, OTHER = ALPHA[0], ALPHA[1], EASTERN
CODES = (8, 13, 24, 99, REASON_CODE_MAX)
HOLD = "hold"

type Step = tuple[str, Shown | str | None]
"""A change line: the UTC time ("HH:MM") and what the map shows from then (``None``: taken
back; ``HOLD``: the emergency stop's dark line)."""


def closed(reason: int | None) -> Shown:
    return Shown(int(Status.CLOSED), reason, None, None)


W = closed(int(Reason.WINTER_STORM))
ICE = Shown(int(Status.DELAYED), int(Reason.ICE), 120, 600, (3,))


def at(clock: str) -> datetime:
    hour, minute = (int(part) for part in clock.split(":"))
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=UTC)


def lines(runs: dict[str, Sequence[Step]]) -> list[Change]:
    """The change log's lines for ``runs`` (by NCES id), in time order, as the publisher
    writes them: ``lit``, ``changed`` and ``dark`` by what was shown before; a hold line
    only for a school that shows a status."""
    found: list[tuple[datetime, int, Change]] = []
    for order, (nces_id, run) in enumerate(runs.items()):
        before: Shown | None = None
        for clock, step in run:
            if step == HOLD:
                if before is not None:
                    found.append(
                        (at(clock), order, Change(at(clock), DAY, nces_id, Event.DARK, None,
                                                  {BY: BY_HOLD}))
                    )  # fmt: skip
                before = None
                continue
            assert not isinstance(step, str)
            event = Event.DARK if step is None else Event.LIT if before is None else Event.CHANGED
            fields = {} if step is None else {"source_id": "tv", "row": "r1"}
            found.append((at(clock), order, Change(at(clock), DAY, nces_id, event, step, fields)))
            before = step
    return [change for _, _, change in sorted(found, key=lambda item: (item[0], item[1]))]


def day_of(changes: Sequence[Change]) -> DayTimeline | None:
    return timeline(DAY, changes, directory=WORLD, stamp=STAMP, generated_at=MADE, final=True)


def x(code: int) -> Shown:
    return closed(code)


CONTROL_RUN: Sequence[Step] = (("09:00", W),)


def cases(code: int) -> dict[str, tuple[Sequence[Step], Sequence[Step]]]:
    """Each case: (head run, base run) of the one school."""
    X = x(code)  # noqa: N806 - the cause's closing, named as the docs name it
    return {
        "X alone": ((("10:00", X),), ()),
        "X then none": ((("10:00", X), ("11:00", None)), ()),
        "X then weather": ((("10:00", X), ("11:00", W)), (("11:00", W),)),
        "weather then X": ((("09:30", W), ("10:00", X)), (("09:30", W), ("10:00", None))),
        "weather, X, none": (
            (("09:30", W), ("10:00", X), ("11:00", None)),
            (("09:30", W), ("10:00", None)),
        ),
        "X, none, weather": ((("10:00", X), ("11:00", None), ("12:00", W)), (("12:00", W),)),
        "X, another X, weather": (
            (("10:00", X), ("10:30", closed(7 if code == 8 else 8)), ("11:00", W)),
            (("10:30", closed(7)), ("11:00", W)) if code == 8 else (("11:00", W),),
        ),
        "delay, X, delay": (
            (("09:30", ICE), ("10:00", X), ("11:00", ICE)),
            (("09:30", ICE), ("10:00", None), ("11:00", ICE)),
        ),
        # V1-S1: the emergency stop after X keeps the weather status the base kept.
        "weather, X, hold": (
            (("09:30", W), ("10:00", X), ("11:00", HOLD)),
            (("09:30", W), ("10:00", None), ("11:00", HOLD)),
        ),
        "weather, X, ice, hold": (
            (("09:30", W), ("10:00", X), ("10:30", ICE), ("11:00", HOLD)),
            (("09:30", W), ("10:00", None), ("10:30", ICE), ("11:00", HOLD)),
        ),
        "X, weather, hold": (
            (("10:00", X), ("10:30", W), ("11:00", HOLD)),
            (("10:30", W), ("11:00", HOLD)),
        ),
        "X, hold": ((("10:00", X), ("11:00", HOLD)), ()),
        # After the release a redacted school-day lights again only from a listed row.
        "hold, release, X again": (
            (("09:30", W), ("10:00", X), ("11:00", HOLD), ("12:00", X)),
            (("09:30", W), ("10:00", None), ("11:00", HOLD)),
        ),
        "hold, release, weather again": (
            (("09:30", W), ("10:00", X), ("11:00", HOLD), ("12:00", W)),
            (("09:30", W), ("10:00", None), ("11:00", HOLD), ("12:00", W)),
        ),
    }


def both(code: int, case: str) -> tuple[list[Change], list[Change]]:
    head, base = cases(code)[case]
    holds: list[Step] = [(clock, HOLD) for clock, step in head if step == HOLD]
    # The stop darkens the control school too; it lights again after the release.
    control = [*CONTROL_RUN, *holds, *((("13:00", W),) if holds else ())]
    return (
        lines({SCHOOL: head, CONTROL: control}),
        lines({SCHOOL: base, CONTROL: control}),
    )


@pytest.mark.parametrize("case", list(cases(13)))
@pytest.mark.parametrize("code", CODES)
def test_the_head_read_as_dark_is_the_base(code: int, case: str) -> None:
    head, base = both(code, case)
    made, kept = day_of(head), day_of(base)
    assert made is not None
    assert kept is not None
    # The timeline the head publishes reads (on this code), and as_dark gives the base's.
    assert DayTimeline.from_json_bytes(made.to_json_bytes()) == made
    assert as_dark(made) == kept
    assert as_dark(DayTimeline.from_json_bytes(made.to_json_bytes())).to_json_bytes() == (
        kept.to_json_bytes()
    )
    # The change log read as dark is the base's log, and builds the base's timeline.
    assert as_dark_changes(head) == base
    assert day_of(as_dark_changes(head)) == kept
    # The base itself is left as it is.
    assert as_dark(kept) is kept
    assert as_dark_changes(base) == base


def test_as_dark_is_the_identity_on_named_codes() -> None:
    every = [closed(int(reason)) for reason in Reason]
    run = [(f"{9 + i}:00", shown) for i, shown in enumerate([*every, None, ICE, None, W])]
    changes = lines({SCHOOL: run, CONTROL: CONTROL_RUN, OTHER: (("10:00", closed(None)),)})
    made = day_of(changes)
    assert made is not None
    assert as_dark(made) is made
    found = as_dark_changes(changes)
    assert found == changes
    assert all(a is b for a, b in zip(found, changes, strict=True))
    # The emergency stop on named codes drops every status back to the last dark, as before.
    held = lines({SCHOOL: [*run, ("23:00", HOLD)], CONTROL: CONTROL_RUN})
    after = day_of(held)
    assert after is not None
    assert after.schools() == (0, 1)
    assert after.counts == (len(every) + 3, 1)
    assert after.statuses[len(every) :] == (None, Status.DELAYED, None, Status.CLOSED)


def test_a_day_with_only_x_reads_as_an_empty_day() -> None:
    made = day_of(lines({SCHOOL: (("10:00", x(13)),), PACIFIC: (("18:00", x(99)),)}))
    assert made is not None
    dark = as_dark(made)
    assert dark.schools() == ()
    assert (dark.day, dark.final, dark.directory) == (made.day, made.final, made.directory)
    assert dark.counts == dark.minutes == dark.statuses == dark.reasons == ()


def test_the_revert_test_a_change_log_holding_13_and_99_reads_on_this_code(
    tmp_path: Path,
) -> None:
    head, base = both(13, "weather then X")
    other_head, other_base = cases(99)["X then weather"]
    more = lines({OTHER: other_head})
    log = ChangeLog(tmp_path / "changes")
    log.commit([*head, *more])
    again = ChangeLog(tmp_path / "changes")
    read = again.changes(DAY)
    assert {change.shown.reason for change in read if change.shown} >= {13, 99}
    assert again.shown[(SCHOOL, DAY)] == x(13)
    made = day_of(read)
    assert made is not None
    data = made.to_json_bytes()
    assert {13, 99} <= set(made.reasons)
    # A successor that lost its log seeds it from the day file: the codes are kept.
    seeded = seed_changes(DayTimeline.from_json_bytes(data), WORLD)
    assert {change.shown.reason for change in seeded if change.shown} >= {13, 99}
    # The prediction's loaders read it as dark.
    expected = day_of([*base, *lines({OTHER: other_base})])
    assert dark_reads.timeline(data, where="live/days/x.json") == expected
    assert dark_reads.DarkChanges(again).changes(DAY) == as_dark_changes(read)
    # The season counts still build from it (what they count is lane P1's).
    ids = edition_ids(WORLD)
    season = build_season(
        [made], ids_of=lambda _made: ids, through=DAY, directory=WORLD, stamp=STAMP
    )
    assert season is not None


def test_a_closings_file_holding_13_and_99_reads_and_reads_as_dark() -> None:
    generated = datetime(2026, 11, 18, 16, 0, tzinfo=UTC)
    weather = [
        Closing(0, DAY, Status.CLOSED, generated - timedelta(minutes=30), Reason.ICE),
        Closing(3, DAY, Status.DELAYED, None, None, 120, 600, manual=True),
        Closing(
            7,
            DAY,
            Status.EARLY_DISMISSAL,
            generated,
            Reason.POWER_OUTAGE,
            None,
            780,
            details=(Detail(2),),
        ),
        Closing(5, DAY + timedelta(days=1), Status.CLOSED, None, Reason.WINTER_STORM),
    ]
    coded = [
        Closing(1, DAY, Status.CLOSED, generated - timedelta(minutes=5), 13),
        Closing(2, DAY, Status.DELAYED, None, 99, 60, None, details=(Detail(1),)),
        Closing(4, DAY + timedelta(days=1), Status.REMOTE, None, 13, manual=True),
        Closing(6, DAY + timedelta(days=1), Status.CLOSED, None, REASON_CODE_MAX),
    ]
    head = ClosingsFile.encode([*weather, *coded], generated_at=generated, directory=STAMP)
    base = ClosingsFile.encode(weather, generated_at=generated, directory=STAMP)
    data = head.to_json_bytes()
    read = ClosingsFile.from_json_bytes(data)
    assert read == head
    unnamed = [c.reason for c in read.closings() if c.reason is not None and c.reason > 7]
    assert sorted(unnamed) == [13, 13, 99, REASON_CODE_MAX]
    assert as_dark_closings(read) == base
    assert dark_reads.closings(data, where="live/closings.json") == base
    assert as_dark_closings(base) is base
    # A day left with no row is left out.
    only = ClosingsFile.encode(coded[2:], generated_at=generated, directory=STAMP)
    assert as_dark_closings(only).days == ()
    # The named codes read as their Reason; a code past the last one any file may hold, or
    # one that is not a whole number, is still refused.
    assert [type(code) for code in read.days[0].reasons] == [Reason, int, int, type(None), Reason]
    for bad in (REASON_CODE_MAX + 1, -1, True, 1.0, "3"):
        value = json.loads(data)
        value["days"][0]["reasons"][0] = bad
        with pytest.raises(ValidationError):
            ClosingsFile.model_validate_json(json.dumps(value))


def test_named_reason_refuses_a_code_not_read_as_dark() -> None:
    assert named_reason(None) is None
    assert named_reason(3) is Reason.FLOODING
    for code in CODES:
        with pytest.raises(ValueError, match="is not a valid Reason"):
            named_reason(code)

"""The "school is on" rule (contract C3, rule 7): every one of a district's eligible schools, or
a private school itself, said school is on for a day, with no posted status that day, in a fresh
opens file of the same publish as the closings file. SYNTHETIC statements only."""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from predict import world
from predict.test_publish import NOW, MemoryHost, make_pass
from snowlight.predict import cli
from snowlight.predict.opens import NOTHING_SAID, OpensError, SaidOpen, said_open
from snowlight.predict.publish import Dark, DarkError
from snowlight.predict.serve import build_model, forecast_file
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import Closing, ClosingsFile, OpensFile, local_days
from snowlight.schemas.predictions import Forecast
from snowlight.schemas.vocab import Reason, Status

TODAY, TOMORROW = local_days(NOW)


def opens(
    statements: Sequence[tuple[int, date]],
    at: datetime = NOW,
    stamp: DirectoryStamp = world.STAMP,
) -> OpensFile:
    """SYNTHETIC open statements: (school, day)."""
    return OpensFile.model_validate(
        {
            "schema_version": 1,
            "generated_at": at,
            "directory": stamp,
            "opens": tuple(
                {"school": school, "day": day, "kind": "open", "at": at, "confidence": 0.95}
                for school, day in sorted(statements, key=lambda item: (item[1], item[0]))
            ),
        }
    )


def closings(rows: Sequence[tuple[int, date, Status]] = (), at: datetime = NOW) -> ClosingsFile:
    """SYNTHETIC posted statuses: (school, day, status)."""
    return ClosingsFile.encode(
        [
            Closing(
                school=school,
                day=day,
                status=status,
                announced_at=at - timedelta(hours=1),
                reason=Reason.WINTER_STORM,
                shift_minutes=120 if status is Status.DELAYED else None,
            )
            for school, day, status in rows
        ],
        generated_at=at,
        directory=world.STAMP,
    )


def rule(found: OpensFile | None, shown: ClosingsFile | None, **kwargs: Any) -> SaidOpen:
    model = build_model(world.directory(), world.model(), world.CONFIG, lambda _x, _y: None)
    assert model.private is not None
    return said_open(
        found,
        shown,
        stamp=kwargs.get("stamp", world.STAMP),
        eligible=model.eligible,
        private=model.private.positions,
        now=kwargs.get("now", NOW),
        max_age=timedelta(minutes=60),
    )


def test_a_district_said_it_only_when_every_eligible_school_did() -> None:
    # District 1 is schools 0 and 1: one of two said school is on, so the district did not
    # ("Riverside said school is on." would not be true of it); both did, so it did. District
    # 2's only eligible school is 2 (school 3 is a charter): a charter's word is not the
    # district's.
    said = rule(opens([(0, TODAY), (3, TODAY)]), closings())
    assert said.districts[TODAY] == frozenset()
    assert not said.district(TODAY, 1)
    assert not said.district(TODAY, 2)
    said = rule(opens([(0, TODAY), (1, TODAY), (3, TODAY)]), closings())
    assert said.districts[TODAY] == frozenset({1})


def test_both_days_are_read() -> None:
    said = rule(opens([(0, TODAY), (1, TODAY), (1, TOMORROW), (2, TOMORROW)]), closings())
    assert said.districts[TODAY] == frozenset({1})
    assert said.districts[TOMORROW] == frozenset({2})


def test_never_on_a_day_a_school_of_the_unit_posted_a_status() -> None:
    # School 1 posted a delay today: district 1 did not say school is on, whatever its schools
    # said.
    statements = [(0, TODAY), (1, TODAY), (0, TOMORROW), (1, TOMORROW)]
    said = rule(opens(statements), closings([(1, TODAY, Status.DELAYED)]))
    assert not said.district(TODAY, 1)
    assert said.district(TOMORROW, 1)


def test_a_private_school_said_it_itself() -> None:
    said = rule(opens([(7, TODAY), (10, TODAY)]), closings())
    # School 10 is in Alaska: not served.
    assert said.schools[TODAY] == frozenset({7})
    assert said.school(TODAY, 7)
    assert not said.school(TOMORROW, 7)


def test_only_a_fresh_pair_of_files_of_one_publish_says_anything() -> None:
    statements = [(0, TODAY), (7, TODAY)]
    assert rule(None, closings()) == NOTHING_SAID
    assert rule(opens(statements), None) == NOTHING_SAID
    other = closings(at=NOW - timedelta(minutes=5))
    assert rule(opens(statements), other) == NOTHING_SAID
    later = NOW + timedelta(minutes=61)
    assert rule(opens(statements), closings(), now=later) == NOTHING_SAID
    assert rule(opens(statements), closings(), now=NOW - timedelta(minutes=1)) == NOTHING_SAID


def test_another_directorys_statements_darken_the_pass() -> None:
    other = DirectoryStamp(generated_on=date(2026, 10, 1), schools=11, districts=5)
    with pytest.raises(OpensError):
        rule(opens([(0, TODAY)], stamp=other), closings())
    assert rule(opens([], stamp=other), closings()) == NOTHING_SAID


def test_a_district_that_said_school_is_on_drops_to_the_floor() -> None:
    model = build_model(world.directory(), world.model(), world.CONFIG, lambda _x, _y: None)
    classes = np.full((len(world.DISTRICTS), 2), 6, dtype=np.int64)  # a snow warning
    days = (date(2026, 1, 6), date(2026, 1, 7))
    said = SaidOpen(districts={days[1]: frozenset({1})})

    before = forecast_file(
        model, classes, days, NOW - timedelta(minutes=30), closed_on=lambda _d: None, last=None
    )
    found = forecast_file(
        model, classes, days, NOW, closed_on=lambda _d: None, last=before, said=said
    )
    usual, quiet = found.districts[1].days
    assert isinstance(usual, Forecast)
    assert isinstance(quiet, Forecast)
    assert usual.p_no_school > 0.3
    assert (quiet.p_no_school, quiet.p_delay) == (0.01, 0.0)
    assert quiet.why.base == usual.why.base
    assert [(r.kind, r.points) for r in quiet.why.reasons] == [
        ("said_open", 1 - usual.why.base.points)
    ]
    # Its record stays under the base it proves. It shows no previous chance though the last
    # file gave another: its why shows the fall (and the file's worst case stays in budget).
    assert quiet.record == usual.record
    assert quiet.previous is None
    with pytest.raises(ValueError, match="no previous"):
        Forecast.model_validate(
            {
                **quiet.model_dump(),
                "previous": {"p_no_school": 0.43, "at": NOW - timedelta(minutes=30)},
            }
        )
    # A district at the floor already: no line to take anything away.
    calm = np.zeros((len(world.DISTRICTS), 2), dtype=np.int64)
    floor = forecast_file(model, calm, days, NOW, closed_on=lambda _d: None, last=None, said=said)
    plain = floor.districts[1].days[1]
    assert isinstance(plain, Forecast)
    assert plain.p_no_school == 0.01
    assert plain.why.reasons == ()


def test_the_pass_reads_both_files_from_the_live_host() -> None:
    host = MemoryHost()
    run = make_pass(host, directory=world.directory())
    model = run.serve_model(world.directory())
    assert cli._said_open(run, model, NOW) == NOTHING_SAID
    host.files["v1/live/opens.json"] = opens([(0, TODAY), (1, TODAY)]).to_json_bytes()
    host.files["v1/live/closings.json"] = closings().to_json_bytes()
    assert cli._said_open(run, model, NOW).district(TODAY, 1)
    host.files["v1/live/opens.json"] = b"{}"
    with pytest.raises(DarkError) as error:
        cli._said_open(run, model, NOW)
    assert error.value.reason is Dark.OPENS

"""The standing file's complete records (records-mo MO-4): shown per district and class from the
committed records, refused when they do not add up, left out when there are none, and no chance
moves with them."""

import gzip
import json
from dataclasses import replace

import numpy as np
import pytest
from pydantic import ValidationError

from predict import world
from predict.test_forecast_adjust import SETTINGS as ADJUST
from predict.test_why_steps import CLIMATE, EXPOSURE
from snowlight.predict import anchor as an
from snowlight.predict import habit_record, standing, state_records
from snowlight.predict.config import PredictConfig
from snowlight.predict.habit_record import FullRow
from snowlight.predict.serve import ServeModel, build_model
from snowlight.schemas.standing import StandingFile

CONFIG = PredictConfig.load()
FULL = {
    "2900002": {
        "advisory": FullRow("2900002", "advisory", 13, 7, 2, 1, 719, 5, "EAX"),
        "warning": FullRow("2900002", "warning", 6, 6, 2, 0, 597, 5, "EAX"),
    }
}


def _model(full: dict[str, dict[str, FullRow]] | None) -> ServeModel:
    anchor = an.fit(an.AnchorSettings.of(CONFIG), EXPOSURE, an.NO_LABELS, {})
    anchor = replace(anchor, climate=CLIMATE, adjust=ADJUST)
    return build_model(
        world.directory(), world.model(), world.CONFIG, lambda _x, _y: None, anchor=anchor,
        full=full,
    )  # fmt: skip


@pytest.fixture(scope="module")
def both() -> tuple[ServeModel, ServeModel]:
    return _model(None), _model(FULL)


def test_the_complete_records_are_shown_by_district_and_class(
    both: tuple[ServeModel, ServeModel],
) -> None:
    before, after = both
    assert before.steps is not None
    assert after.steps is not None
    i = world.DISTRICTS.index("2900002")
    found = after.steps.file.record_full
    assert found.advisory == ((i, 7, 2, 1, 13, 719, 5),)
    assert found.warning == ((i, 6, 2, 0, 6, 597, 5),)
    assert found.cold == ()
    # with none, the field is left out of the file, so its bytes and stamp stay today's
    assert "record_full" not in json.loads(before.steps.file.to_json_bytes())
    assert after.steps.file.stamp != before.steps.file.stamp
    plain = after.steps.file.model_copy(update={"record_full": before.steps.file.record_full})
    assert standing.stamp_of(plain) == before.steps.file.stamp


def test_no_chance_and_no_other_part_moves_with_them(both: tuple[ServeModel, ServeModel]) -> None:
    before, after = both
    assert np.array_equal(before.p, after.p)
    assert before.steps is not None
    assert after.steps is not None
    assert np.array_equal(before.steps.served, after.steps.served)
    one = json.loads(before.steps.file.to_json_bytes())
    other = json.loads(after.steps.file.to_json_bytes())
    other.pop("record_full")
    one.pop("stamp")
    other.pop("stamp")
    assert one == other
    settings = an.AnchorSettings.of(CONFIG)
    assert not standing.guard(
        after.steps, settings.beta, settings.offset, an.Grid(0.01, 0.99), 4_000_000, 600_000
    )


@pytest.mark.parametrize(
    "row",
    [
        (1, 7, 8, 1, 13, 700, 5),  # home more than no school
        (1, 7, 2, 7, 13, 700, 5),  # no school and short more than the days
        (1, 7, 2, 1, 13, 1301, 5),  # same100 above 100 x days
        (1, 0, 0, 0, 0, 0, 5),  # no days
    ],
)
def test_the_file_refuses_a_complete_record_that_does_not_add_up(
    both: tuple[ServeModel, ServeModel], row: tuple[int, ...]
) -> None:
    _before, after = both
    assert after.steps is not None
    data = json.loads(after.steps.file.to_json_bytes())
    data["record_full"]["advisory"] = [list(row)]
    with pytest.raises(ValidationError, match="complete record does not add up"):
        StandingFile.model_validate_json(json.dumps(data))
    data["record_full"]["advisory"] = [[99, 1, 0, 0, 5, 100, 1]]
    with pytest.raises(ValidationError, match="sorted, unique, named"):
        StandingFile.model_validate_json(json.dumps(data))


def test_missouris_records_fit_the_budgets_beside_todays_file() -> None:
    """Every Missouri row (1,522) as the standing file writes it: today's published file was
    875,391 B raw and 195,925 B gzip (spec SPEC RECORDS-MO r2 section 0), against 4,000,000 and
    600,000."""
    rows = standing.full_records()
    by: dict[str, list[list[int]]] = {"advisory": [], "warning": [], "cold": []}
    for i, (_leaid, kinds) in enumerate(sorted(rows.items())):
        for kind, row in kinds.items():
            by[kind].append(
                [i * 3, row.no_school, row.home, row.short, row.days, row.same100, row.winters]
            )
    assert sum(len(v) for v in by.values()) == 1522
    data = json.dumps({"record_full": by}, separators=(",", ":")).encode()
    assert 875_391 + len(data) < 4_000_000
    assert 195_925 + len(gzip.compress(data, 9, mtime=0)) < 600_000


def test_the_committed_records_are_read_once_and_checked_by_their_pin() -> None:
    assert standing.full_records() is standing.full_records()
    mo = state_records.load().states["mo"]
    assert mo.full_record is not None
    rows = habit_record.read_record_file(state_records.read_derived(mo, mo.full_record.name))
    assert len(standing.full_records()) == len({r.leaid for r in rows})


@pytest.mark.parametrize(
    "bad",
    [
        state_records.StateRecordError("mo: mo-record-ed1.csv off its pin"),
        habit_record.FullRecordError("not a record file"),
        OSError("no such file"),
    ],
)
def test_a_record_file_that_does_not_read_never_stops_the_pass_and_no_chance_moves(
    both: tuple[ServeModel, ServeModel], monkeypatch: pytest.MonkeyPatch, bad: Exception
) -> None:
    def refuse(_state: object, _name: str) -> bytes:
        raise bad

    said: list[str] = []
    standing.full_records.cache_clear()
    monkeypatch.setattr(state_records, "read_derived", refuse)
    try:
        found = standing.full_records_read(said.append)
    finally:
        standing.full_records.cache_clear()
    assert found == {}
    assert said == [f"the complete records were not read, so no habit box shows one: {bad}"]
    before, _after = both
    plain = _model({u: dict(kinds) for u, kinds in found.items()})
    assert np.array_equal(before.p, plain.p)
    assert before.steps is not None
    assert plain.steps is not None
    assert plain.steps.file.to_json_bytes() == before.steps.file.to_json_bytes()

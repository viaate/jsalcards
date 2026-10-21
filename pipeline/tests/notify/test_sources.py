"""The published files as the rules read them: statuses and open statements by school id, and
each school's chance from its district or, for a private school, its own (S7-2). The files
are the schemas' SYNTHETIC examples."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from snowlight.notify.rules import Shown
from snowlight.notify.sources import fresh, open_days, outlooks, status_days, statuses
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import ClosingsFile, OpensFile
from snowlight.schemas.predictions import PredictionsFile
from snowlight.schemas.vocab import Status

EXAMPLES = Path(__file__).resolve().parents[1] / "schemas" / "examples"
IDS = ("000000000001", "000000000002", "000000000003", "000000000004", "A0000005", "A0000006")
DISTRICT_OF = (0, 0, 1, 1, None, None)
ALL = set(IDS)


def closings() -> ClosingsFile:
    return ClosingsFile.from_json_bytes((EXAMPLES / "synthetic-closings.json").read_bytes())


def predictions() -> PredictionsFile:
    return PredictionsFile.from_json_bytes((EXAMPLES / "synthetic-predictions.json").read_bytes())


def test_statuses_by_school_id_with_their_delay_and_time() -> None:
    found = statuses(closings(), IDS, ALL)
    jan12, jan13 = date(2027, 1, 12), date(2027, 1, 13)
    assert found["000000000001"] == {jan12: Shown(Status.CLOSED), jan13: Shown(Status.CLOSED)}
    assert found["000000000002"][jan12] == Shown(Status.DELAYED, shift=120, clock=600)
    assert found["000000000003"][jan12] == Shown(Status.DELAYED)
    assert found["000000000004"][jan12] == Shown(Status.REMOTE)
    assert found["A0000006"][jan12] == Shown(Status.EARLY_DISMISSAL, shift=180, clock=750)
    assert found["A0000005"] == {jan13: Shown(Status.CLOSED)}
    assert set(statuses(closings(), IDS, {"000000000002"})) == {"000000000002"}


def test_open_statements() -> None:
    opens = OpensFile.from_json_bytes((EXAMPLES / "synthetic-opens.json").read_bytes())
    assert open_days(opens, IDS, ALL) == {
        ("000000000003", date(2027, 1, 12)),
        ("A0000006", date(2027, 1, 13)),
    }
    assert open_days(None, IDS, ALL) == frozenset()


def test_chances_from_the_district_or_the_private_schools_own() -> None:
    found = outlooks(predictions(), IDS, DISTRICT_OF, ALL)
    jan12, jan13 = date(2027, 1, 12), date(2027, 1, 13)
    assert found["000000000001"].percent == {jan12: 62, jan13: 22}
    assert found["000000000001"].zone == "America/Chicago"
    assert found["000000000003"].percent == {jan12: None, jan13: 20}, "no_threat is no chance"
    assert found["A0000005"].percent == {jan12: 1, jan13: 20}
    assert found["A0000006"].percent == {jan12: None, jan13: 20}
    assert found["A0000006"].zone == "America/Chicago"
    assert "nobody" not in outlooks(predictions(), IDS, DISTRICT_OF, {"nobody"})


def test_a_school_the_file_left_out_gets_no_chance() -> None:
    file = predictions()
    left_out = file.model_copy(update={"districts": file.districts[:1]})
    assert set(outlooks(left_out, IDS, DISTRICT_OF, ALL)) == {
        "000000000001",
        "000000000002",
        "A0000005",
        "A0000006",
    }


def test_freshness() -> None:
    made = datetime(2027, 1, 12, 13, 5, tzinfo=UTC)
    assert fresh(made, made + timedelta(minutes=20))
    assert not fresh(made, made + timedelta(minutes=21))
    assert fresh(made, made - timedelta(seconds=60))
    assert not fresh(made, made - timedelta(seconds=61))


def test_status_days_only_from_a_current_file_of_this_directory() -> None:
    file = closings()
    now = file.generated_at + timedelta(minutes=5)
    days = status_days(file, file.directory, IDS, ALL, now)
    assert ("000000000001", date(2027, 1, 13)) in days
    other = DirectoryStamp(generated_on=date(2026, 9, 25), schools=6, districts=2)
    assert status_days(file, other, IDS, ALL, now) == frozenset()
    assert status_days(file, file.directory, IDS, ALL, now + timedelta(hours=1)) == frozenset()
    assert status_days(None, file.directory, IDS, ALL, now) == frozenset()

"""What each published model accepts and refuses, beyond its example."""

import json
import random
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import HttpUrl, ValidationError

from schemas.helpers import example
from schemas.synthetic import synthetic_row
from snowlight.schemas import internal, live
from snowlight.schemas.directory import DirectoryStamp, SchoolDirectoryMeta
from snowlight.schemas.live import (
    AlertsFile,
    Closing,
    ClosingsDay,
    ClosingsFile,
    CoveredFile,
    check_live_pair,
    local_days,
    ranges_from_indices,
)
from snowlight.schemas.predictions import PredictionsFile
from snowlight.schemas.registry import PublishedFile
from snowlight.schemas.replays import ReplayFile, ReplayIndex, check_summary
from snowlight.schemas.scalars import (
    MAX_MINUTES_AGO,
    SchoolGap,
    format_instant,
    minute_of,
    minutes_ago,
    school_year_bounds,
    unix_seconds,
)
from snowlight.schemas.stats import SeasonStats, TrackRecord
from snowlight.schemas.vocab import Reason, Status


def _parse(model: type[Any], value: Any) -> Any:
    return model.from_json_bytes(json.dumps(value))


def _refused(model: type[Any], value: Any, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _parse(model, value)


# Times, dates and strictness ---------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "2027-01-12T13:05:00+00:00",
        "2027-01-12T13:05:00.000Z",
        "2027-01-12T13:05:00",
        "2027-01-12 13:05:00Z",
        "2027-01-12T08:05:00-05:00",
        "2027-01-12",
        "1799755500",
    ],
)
def test_utc_instants_have_one_spelling(text: str) -> None:
    value = example("closings") | {"generated_at": text}
    _refused(ClosingsFile, value, "generated_at")


@pytest.mark.parametrize(
    ("moment", "match"),
    [
        (datetime(2027, 1, 12, 13, 5), "naive"),
        (datetime(2027, 1, 12, 13, 5, 0, 500, tzinfo=UTC), "whole seconds"),
        (datetime(2027, 1, 12, 7, 5, tzinfo=timezone(timedelta(hours=-6))), "offset 0"),
    ],
)
def test_python_datetimes_must_be_whole_utc_seconds(moment: datetime, match: str) -> None:
    stamp = DirectoryStamp(generated_on=date(2026, 9, 24), schools=1, districts=1)
    with pytest.raises(ValidationError, match=match):
        ClosingsFile(schema_version=1, generated_at=moment, directory=stamp, days=())


@pytest.mark.parametrize("day", ["2027-1-12", "20270112", "2027-01-12T00:00:00Z", "2027-13-01"])
def test_local_dates_have_one_spelling(day: str) -> None:
    value = example("closings")
    value["days"][0]["day"] = day
    _refused(ClosingsFile, value, r"days\.0\.day")


@pytest.mark.parametrize("bad", ["0", True, 0.0, 1.0, -1, 2**32])
@pytest.mark.parametrize("column", ["gaps", "announced", "shifts", "clocks"])
def test_numbers_are_not_coerced(column: str, bad: Any) -> None:
    value = example("closings")
    value["days"][0][column][0] = bad
    _refused(ClosingsFile, value, rf"days\.0\.{column}\.0")


@pytest.mark.parametrize("status", [4, -1, "closed", None, True, 1.0])
def test_status_codes_are_closed(status: Any) -> None:
    value = example("closings")
    value["days"][0]["statuses"][1] = status
    _refused(ClosingsFile, value, r"days\.0\.statuses\.1")


@pytest.mark.parametrize("version", [2, 0, True, 1.0, "1", None])
def test_only_schema_version_1_is_read(entry: PublishedFile, version: Any) -> None:
    value = example(entry.name)
    key = "schema" if "schema" in value else "schema_version"
    assert value[key] == 1
    _refused(entry.model, value | {key: version}, key)


# closings.json -----------------------------------------------------------------------

GENERATED = datetime(2027, 1, 12, 13, 5, tzinfo=UTC)
# 01:30 in New York and 22:30 the evening before in Los Angeles.
NIGHT = datetime(2027, 1, 12, 6, 30, tzinfo=UTC)
STAMP = DirectoryStamp(generated_on=date(2026, 9, 24), schools=6, districts=2)


def test_closings_example_decodes_to_its_rows() -> None:
    document = _parse(ClosingsFile, example("closings"))
    today, tomorrow = date(2027, 1, 12), date(2027, 1, 13)

    def at(hour: int, minute: int) -> datetime:
        return datetime(2027, 1, 12, hour, minute, tzinfo=UTC)

    assert document.closings() == [
        Closing(0, today, Status.CLOSED, at(11, 42), Reason.WINTER_STORM),
        Closing(1, today, Status.DELAYED, at(11, 3), Reason.ICE, 120, 600),
        Closing(2, today, Status.DELAYED, None, None),
        Closing(3, today, Status.REMOTE, at(1, 15), Reason.EXTREME_COLD),
        Closing(5, today, Status.EARLY_DISMISSAL, at(13, 0), Reason.SEVERE_STORMS, 180, 750),
        Closing(0, tomorrow, Status.CLOSED, at(12, 50), Reason.WINTER_STORM),
        Closing(4, tomorrow, Status.CLOSED, at(12, 58), None),
    ]
    assert [group.schools() for group in document.days] == [(0, 1, 2, 3, 5), (0, 4)]
    assert [group.last_school() for group in document.days] == [5, 4]
    again = ClosingsFile.encode(document.closings(), generated_at=GENERATED, directory=STAMP)
    assert again == document


def test_the_documented_day_group_reads_as_documented() -> None:
    """The example in snowlight.schemas.live's docstring, and SchoolGap's."""
    docstring = live.__doc__
    assert docstring is not None
    text = docstring.split("reads::", 1)[1].split("\n\n", 2)[1]
    group = ClosingsDay.from_json_bytes(text)
    assert group.schools() == (4, 5, 8)
    assert (group.shifts, group.clocks) == ((120,), (None,))
    assert "So [4, 0, 2] is schools 4, 5 and 8." in " ".join(str(SchoolGap.__value__).split())


def test_closings_days_are_sorted_unique_and_non_empty() -> None:
    value = example("closings")
    value["days"].reverse()
    _refused(ClosingsFile, value, "sorted and unique")
    value = example("closings")
    value["days"][1]["day"] = value["days"][0]["day"]
    _refused(ClosingsFile, value, "sorted and unique")
    value = example("closings")
    value["days"][1] |= {key: [] for key in ("gaps", "statuses", "announced", "reasons")}
    _refused(ClosingsFile, value, "at least 1")


@pytest.mark.parametrize(
    ("column", "match"),
    [
        ("statuses", "5 gaps but 4 statuses"),
        ("announced", "5 gaps but 4 announced"),
        ("reasons", "5 gaps but 4 reasons"),
        ("shifts", "3 delays and early dismissals but 2 shifts"),
        ("clocks", "3 delays and early dismissals but 2 clocks"),
    ],
)
def test_closings_columns_line_up(column: str, match: str) -> None:
    value = example("closings")
    value["days"][0][column].pop()
    _refused(ClosingsFile, value, match)


def test_only_delays_and_dismissals_have_times() -> None:
    value = example("closings")
    value["days"][0]["statuses"][0] = int(Status.DELAYED)
    _refused(ClosingsFile, value, "4 delays and early dismissals but 3 shifts")
    value = example("closings")
    value["days"][0]["statuses"][1] = int(Status.REMOTE)
    _refused(ClosingsFile, value, "2 delays and early dismissals but 3 shifts")
    closed = Closing(0, date(2027, 1, 12), Status.CLOSED, None, None, shift_minutes=60)
    with pytest.raises(ValueError, match="only delays and dismissals have times"):
        ClosingsFile.encode([closed], generated_at=GENERATED, directory=STAMP)


def test_closings_schools_must_be_in_the_directory() -> None:
    value = example("closings")
    value["days"][1]["gaps"][-1] += 2
    _refused(ClosingsFile, value, "school 6 is not in the directory")
    value = example("closings")
    value["days"][0]["gaps"][0] = 2**32 - 2
    _refused(ClosingsFile, value, "is not in the directory")


def test_closings_times_are_minutes_before_generated_at() -> None:
    value = example("closings")
    value["days"][0]["announced"][0] = MAX_MINUTES_AGO
    assert _parse(ClosingsFile, value)
    for bad in (-1, MAX_MINUTES_AGO + 1):
        value["days"][0]["announced"][0] = bad
        _refused(ClosingsFile, value, r"days\.0\.announced\.0")
    late = Closing(0, date(2027, 1, 12), Status.CLOSED, GENERATED + timedelta(seconds=1), None)
    with pytest.raises(ValueError, match="is after"):
        ClosingsFile.encode([late], generated_at=GENERATED, directory=STAMP)


@pytest.mark.parametrize(
    ("generated", "moment", "ago"),
    [
        (datetime(2027, 1, 12, 13, 5, 0), datetime(2027, 1, 12, 13, 5, 0), 0),
        (datetime(2027, 1, 12, 13, 5, 59), datetime(2027, 1, 12, 13, 5, 0), 0),
        (datetime(2027, 1, 12, 13, 5, 0), datetime(2027, 1, 12, 13, 4, 59), 1),
        (datetime(2027, 1, 12, 13, 5, 30), datetime(2027, 1, 11, 23, 59, 59), 786),
    ],
)
def test_minutes_ago_keeps_the_announced_minute(
    generated: datetime, moment: datetime, ago: int
) -> None:
    generated, moment = generated.replace(tzinfo=UTC), moment.replace(tzinfo=UTC)
    assert minutes_ago(generated, moment) == ago
    assert minute_of(generated, ago) == moment.replace(second=0)


@pytest.mark.parametrize(
    ("moment", "first", "last"),
    [
        (datetime(2027, 1, 12, 3, 59, 59), date(2027, 1, 11), date(2027, 1, 12)),
        (datetime(2027, 1, 12, 4, 0, 0), date(2027, 1, 11), date(2027, 1, 13)),
        (datetime(2027, 1, 12, 7, 59, 59), date(2027, 1, 11), date(2027, 1, 13)),
        (datetime(2027, 1, 12, 8, 0, 0), date(2027, 1, 12), date(2027, 1, 13)),
        (datetime(2027, 1, 12, 13, 5, 0), date(2027, 1, 12), date(2027, 1, 13)),
        (datetime(2027, 1, 12, 23, 59, 59), date(2027, 1, 12), date(2027, 1, 13)),
    ],
)
def test_local_days_follow_midnight_across_the_country(
    moment: datetime, first: date, last: date
) -> None:
    assert local_days(moment.replace(tzinfo=UTC)) == (first, last)


def test_closings_keep_to_each_schools_today_and_tomorrow() -> None:
    value = example("closings")
    value["days"][0]["day"] = "2027-01-11"
    _refused(ClosingsFile, value, "2027-01-11 is over everywhere")
    value = example("closings")
    value["days"][1]["day"] = "2027-01-14"
    _refused(ClosingsFile, value, "2027-01-14 is not today or tomorrow anywhere yet")

    night = example("closings") | {"generated_at": format_instant(NIGHT)}
    assert _parse(ClosingsFile, night)
    night["days"][0]["day"] = "2027-01-11"
    _refused(ClosingsFile, night, "school 0 has rows on 2027-01-11 and 2027-01-13")
    night["days"][1] |= {"gaps": [4], "statuses": [0], "announced": [7], "reasons": [None]}
    document = _parse(ClosingsFile, night)  # the West's today, the East's tomorrow
    assert [group.day for group in document.days] == [date(2027, 1, 11), date(2027, 1, 13)]
    night["days"][0]["day"] = "2027-01-10"
    _refused(ClosingsFile, night, "2027-01-10 is over everywhere")
    night["days"][0]["day"] = "2027-01-11"
    night["days"][1]["day"] = "2027-01-14"
    _refused(ClosingsFile, night, "2027-01-14 is not today or tomorrow anywhere yet")

    value = example("closings")
    value["days"] = [value["days"][0]] * 4
    _refused(ClosingsFile, value, "at most 3")


@pytest.mark.parametrize(("column", "bad"), [("shifts", 0), ("shifts", 721), ("clocks", 1440)])
def test_shift_and_clock_are_bounded(column: str, bad: int) -> None:
    value = example("closings")
    value["days"][0][column][0] = bad
    _refused(ClosingsFile, value, rf"days\.0\.{column}\.0")


def test_encode_refuses_two_rows_for_one_school_and_day() -> None:
    row = Closing(3, date(2027, 1, 12), Status.CLOSED, None, None)
    with pytest.raises(ValueError, match="two rows for 2027-01-12"):
        ClosingsFile.encode([row, row], generated_at=GENERATED, directory=STAMP)


@st.composite
def _closing_rows(draw: st.DrawFn) -> list[Closing]:
    days = draw(
        st.sampled_from(
            [
                (date(2027, 1, 12),),
                (date(2027, 1, 12), date(2027, 1, 13)),
                (date(2027, 1, 11), date(2027, 1, 12)),
                (date(2027, 1, 13),),
            ]
        )
    )
    schools = draw(st.lists(st.integers(0, 199), unique=True, max_size=40))
    seed = draw(st.integers(0, 2**16))
    rng = random.Random(seed)  # noqa: S311 - synthetic test data
    rows = []
    for school in schools:
        for day in days[: draw(st.integers(1, len(days)))]:
            row = synthetic_row(rng, school, day, generated_at=NIGHT)
            if draw(st.booleans()):
                row = replace(row, announced_at=None)
            if row.status in {Status.DELAYED, Status.EARLY_DISMISSAL} and draw(st.booleans()):
                row = replace(row, shift_minutes=None)
            rows.append(row)
    return rows


@given(_closing_rows())
def test_closings_encode_and_decode_are_inverse(rows: list[Closing]) -> None:
    stamp = DirectoryStamp(generated_on=date(2026, 9, 24), schools=200, districts=1)
    document = ClosingsFile.encode(reversed(rows), generated_at=NIGHT, directory=stamp)
    expected = sorted(
        (
            row
            if row.announced_at is None
            else replace(row, announced_at=row.announced_at.replace(second=0))
            for row in rows
        ),
        key=lambda row: (row.day, row.school),
    )
    assert document.closings() == expected
    assert all(
        row.announced_at is None or row.announced_at.second == 0 for row in document.closings()
    )
    assert ClosingsFile.from_json_bytes(document.to_json_bytes()) == document
    assert ClosingsFile.encode(expected, generated_at=NIGHT, directory=stamp) == document


# covered.json ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ranges", "match"),
    [
        ([[3, 0]], "after last"),
        ([[0, 1], [2, 3]], "not touching"),
        ([[0, 3], [2, 5]], "not touching"),
        ([[4, 5], [0, 1]], "sorted"),
        ([[0, 6]], "not in the directory"),
    ],
)
def test_covered_ranges_are_canonical(ranges: list[list[int]], match: str) -> None:
    _refused(CoveredFile, example("covered") | {"ranges": ranges}, match)


@given(st.sets(st.integers(min_value=0, max_value=400), max_size=120))
def test_ranges_from_indices_round_trip(indices: set[int]) -> None:
    ranges = ranges_from_indices(indices)
    covered = CoveredFile(
        schema_version=1,
        generated_at=datetime(2027, 1, 12, 13, 5, tzinfo=UTC),
        directory=DirectoryStamp(generated_on=date(2026, 9, 24), schools=401, districts=1),
        ranges=ranges,
    )
    assert covered.count() == len(indices)
    assert {i for i in range(402) if covered.covers(i)} == indices
    assert ranges_from_indices(list(indices) + list(indices)) == ranges


def test_live_pair_must_match() -> None:
    closings = _parse(ClosingsFile, example("closings"))
    covered = _parse(CoveredFile, example("covered"))
    check_live_pair(closings, covered)
    later = _parse(CoveredFile, example("covered") | {"generated_at": "2027-01-12T13:10:00Z"})
    with pytest.raises(ValueError, match="generated_at"):
        check_live_pair(closings, later)
    other = example("covered")
    other["directory"]["generated_on"] = "2026-09-25"
    with pytest.raises(ValueError, match="different directories"):
        check_live_pair(closings, _parse(CoveredFile, other))


# alerts.json -------------------------------------------------------------------------


def test_alerts_use_the_publishers_camel_case_keys() -> None:
    document = _parse(AlertsFile, example("alerts"))
    assert set(json.loads(document.to_json_bytes())) == {"schema", "asOf", "generatedAt", "alerts"}
    snake = example("alerts")
    snake["generated_at"] = snake.pop("generatedAt")
    _refused(AlertsFile, snake, "generatedAt")


def test_alert_rings_close_and_bbox_fits() -> None:
    value = example("alerts")
    value["alerts"][0]["polygons"][0][0][-1] = [-91.4, 40.0]
    _refused(AlertsFile, value, "end where it starts")
    value = example("alerts")
    value["alerts"][0]["polygons"][0][0] = value["alerts"][0]["polygons"][0][0][:3]
    _refused(AlertsFile, value, "at least 4")
    value = example("alerts")
    value["alerts"][0]["bbox"][2] = -89.0
    _refused(AlertsFile, value, "bbox does not fit")
    value = example("alerts")
    value["alerts"][0]["bbox"] = [-90.0, 40.0, -91.5, 41.25]
    _refused(AlertsFile, value, "inverted")


def test_alert_times_are_ordered_and_ids_unique() -> None:
    value = example("alerts")
    value["alerts"][0]["ends"] = "2027-01-12T05:00:00Z"
    _refused(AlertsFile, value, "ends before")
    _refused(AlertsFile, example("alerts") | {"asOf": "2027-01-12T13:10:00Z"}, "asOf is after")
    value = example("alerts")
    value["alerts"][1]["id"] = value["alerts"][0]["id"]
    _refused(AlertsFile, value, "unique")


@pytest.mark.parametrize(
    ("field", "bad"),
    [("hazard", "fire"), ("level", "statement"), ("severity", "severe"), ("event", "WSW")],
)
def test_alert_vocabularies_are_closed(field: str, bad: str) -> None:
    value = example("alerts")
    value["alerts"][0][field] = bad
    _refused(AlertsFile, value, field)


# predictions/latest.json -------------------------------------------------------------


def test_forecast_states_are_discriminated() -> None:
    document = _parse(PredictionsFile, example("predictions"))
    states = [day.state for entry in document.districts for day in entry.days]
    assert states == ["forecast", "forecast", "no_threat", "not_enough_data"]
    value = example("predictions")
    value["districts"][1]["days"][0] = {"state": "maybe"}
    _refused(PredictionsFile, value, "state")
    value = example("predictions")
    value["districts"][1]["days"][0] = {"state": "no_threat", "p_no_school": 0.0}
    _refused(PredictionsFile, value, "Extra inputs")


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"p_no_school": 0.8, "p_delay": 0.3}, "sum is over 1"),
        ({"p_no_school": 0.625}, "hundredths"),
        ({"p_no_school": 1.2}, "less than or equal"),
        ({"reasons": []}, "at least 1"),
        ({"reasons": [0, 0]}, "must not repeat"),
        ({"reasons": [9]}, "reasons"),
    ],
)
def test_forecast_values_are_checked(change: dict[str, Any], match: str) -> None:
    value = example("predictions")
    value["districts"][0]["days"][0] |= change
    _refused(PredictionsFile, value, match)


def test_prediction_days_and_districts_line_up() -> None:
    _refused(
        PredictionsFile,
        example("predictions") | {"days": ["2027-01-12", "2027-01-14"]},
        "consecutive",
    )
    value = example("predictions")
    value["districts"][1]["days"].pop()
    _refused(PredictionsFile, value, "1 entries for 2 days")
    value = example("predictions")
    value["districts"].reverse()
    _refused(PredictionsFile, value, "sorted")
    value = example("predictions")
    value["districts"][1]["district"] = 2
    _refused(PredictionsFile, value, "not in the directory")


# stats/season.json and track-record.json ----------------------------------------------


def test_season_stats_add_up() -> None:
    value = example("season-stats")
    value["states"][0][1] += 1
    _refused(SeasonStats, value, "add up")
    value = example("season-stats")
    value["days"][0][0] = "2026-06-30"
    _refused(SeasonStats, value, "outside")
    _refused(SeasonStats, example("season-stats") | {"through": "2027-07-01"}, "outside")
    _refused(SeasonStats, example("season-stats") | {"schools": 9}, "cannot give")
    _refused(SeasonStats, example("season-stats") | {"districts": 6}, "more affected districts")
    _refused(SeasonStats, example("season-stats") | {"season": "2026-2028"}, "consecutive")


def test_school_year_bounds() -> None:
    assert school_year_bounds("2026-2027") == (date(2026, 7, 1), date(2027, 6, 30))


def test_calibration_bins_cover_zero_to_one_hundred() -> None:
    value = example("track-record")
    value["leads"][0]["no_school"]["bins"].pop()
    _refused(TrackRecord, value, "0 to 100")
    value = example("track-record")
    value["leads"][0]["no_school"]["bins"][3][3] = 99
    _refused(TrackRecord, value, "more outcomes than forecasts")
    value = example("track-record")
    value["leads"][0]["no_school"]["forecasts"] += 1
    _refused(TrackRecord, value, "sum of the bins")


def test_track_record_span_matches_scoring() -> None:
    value = example("track-record") | {"first_day": None, "last_day": None}
    _refused(TrackRecord, value, "set once any day is scored")
    value = example("track-record") | {"first_day": "2027-01-12"}
    _refused(TrackRecord, value, "scored span")
    empty = example("track-record")
    empty["leads"] = [
        lead | {"no_school": empty["leads"][1]["delay"], "delay": empty["leads"][1]["delay"]}
        for lead in empty["leads"]
    ]
    assert _parse(TrackRecord, empty | {"first_day": None, "last_day": None})


# replays -----------------------------------------------------------------------------


def test_replay_summary_matches_its_file() -> None:
    replay = _parse(ReplayFile, example("replay"))
    index = _parse(ReplayIndex, example("replay-index"))
    check_summary(index.replays[0], replay)
    assert replay.end == datetime(2026, 12, 19, 23, 0, tzinfo=UTC)
    wrong = example("replay-index")
    wrong["replays"][0]["peak_frame"] = 11
    with pytest.raises(ValueError, match="peak_frame"):
        check_summary(_parse(ReplayIndex, wrong).replays[0], replay)


@pytest.mark.parametrize(
    ("position", "row", "match"),
    [
        (2, [1, 0, 15, 20, 0], "spans apart"),
        (0, [0, 0, 40, 30, 0], "not within"),
        (0, [0, 0, 40, 48, 0], "not within"),
        (5, [6, 0, 1, 2, 0], "not in the directory"),
        (5, [3, 0, 1, 2, 0], "sorted"),
    ],
)
def test_replay_rows_are_checked(position: int, row: list[Any], match: str) -> None:
    value = example("replay")
    if row[0] == 0:
        value["rows"][position] = row
    else:
        value["rows"].insert(position, row)
    _refused(ReplayFile, value, match)


@st.composite
def _replays(draw: st.DrawFn) -> ReplayFile:
    frames = draw(st.integers(min_value=1, max_value=30))
    rows = []
    for school in sorted(draw(st.sets(st.integers(0, 49), max_size=12))):
        cursor = 0
        for _ in range(draw(st.integers(0, 3))):
            if cursor >= frames:
                break
            first = draw(st.integers(cursor, frames - 1))
            last = draw(st.integers(first, frames - 1))
            status = draw(st.sampled_from(list(Status)))
            reason = draw(st.none() | st.sampled_from(list(Reason)))
            rows.append((school, status, first, last, reason))
            cursor = last + 1
    return ReplayFile(
        schema_version=1,
        id="2026-12-18",
        generated_at=datetime(2026, 12, 20, 8, tzinfo=UTC),
        directory=DirectoryStamp(generated_on=date(2026, 9, 24), schools=50, districts=1),
        start=datetime(2026, 12, 18, tzinfo=UTC),
        step_minutes=60,
        frames=frames,
        rows=tuple(rows),
    )


@given(_replays())
def test_spans_draw_the_same_frames_as_a_frame_by_frame_listing(replay: ReplayFile) -> None:
    naive = [
        sorted(
            (school, status)
            for school, status, first, last, _ in replay.rows
            if first <= frame <= last
        )
        for frame in range(replay.frames)
    ]
    assert [sorted(replay.frame(frame)) for frame in range(replay.frames)] == naive
    assert replay.frame_counts() == [len(frame) for frame in naive]
    assert ReplayFile.from_json_bytes(replay.to_json_bytes()) == replay


def test_replay_frame_index_is_bounded() -> None:
    replay = _parse(ReplayFile, example("replay"))
    with pytest.raises(IndexError):
        replay.frame(48)


def test_replay_index_is_sorted_and_unique() -> None:
    value = example("replay-index")
    value["replays"].append(value["replays"][0])
    _refused(ReplayIndex, value, "unique")
    value = example("replay-index")
    later = value["replays"][0] | {"id": "2026-12-01", "start": "2026-12-01T00:00:00Z"}
    value["replays"].append(later)
    _refused(ReplayIndex, value, "sorted")
    value = example("replay-index")
    value["replays"][0]["peak_frame"] = 48
    _refused(ReplayIndex, value, "past the last frame")
    value = example("replay-index")
    value["replays"][0]["states"] = ["IL", "IA"]
    _refused(ReplayIndex, value, "sorted and unique")


# schools/meta.json -------------------------------------------------------------------


def test_directory_meta_orders_public_before_private() -> None:
    value = example("school-directory")
    value["ids"][3], value["ids"][4] = value["ids"][4], value["ids"][3]
    _refused(SchoolDirectoryMeta, value, "public schools must all come before")
    value = example("school-directory")
    value["ids"][0], value["ids"][1] = value["ids"][1], value["ids"][0]
    _refused(SchoolDirectoryMeta, value, "sorted and unique")
    _refused(SchoolDirectoryMeta, example("school-directory") | {"count": 5}, "count is 5")
    value = example("school-directory")
    value["districts"]["names"].pop()
    _refused(SchoolDirectoryMeta, value, "2 district ids but 1 names")


def test_directory_stamp_matches_meta() -> None:
    meta = _parse(SchoolDirectoryMeta, example("school-directory"))
    closings = _parse(ClosingsFile, example("closings"))
    assert meta.stamp() == closings.directory


# internal projections ----------------------------------------------------------------


def _observation(**change: Any) -> internal.ClosingObservation:
    base: dict[str, Any] = {
        "school_index": 1,
        "school_id": "000000000002",
        "status": Status.DELAYED,
        "day": date(2027, 1, 12),
        "announced_at": datetime(2027, 1, 12, 11, 3, tzinfo=UTC),
        "reason": Reason.ICE,
        "shift_minutes": 120,
        "clock_minute": 600,
        "source_id": "synthetic-a",
        "source_url": HttpUrl("https://example.com/a"),
        "snapshot_at": datetime(2027, 1, 12, 12, 0, tzinfo=UTC),
        "listing_text": "Synthetic Middle School B: 2 hour delay",
    }
    return internal.ClosingObservation(**(base | change))


def test_closings_file_merges_agreeing_observations() -> None:
    stamp = DirectoryStamp(generated_on=date(2026, 9, 24), schools=6, districts=2)
    generated = datetime(2027, 1, 12, 13, 5, tzinfo=UTC)
    earlier = _observation(
        source_id="synthetic-b", announced_at=datetime(2027, 1, 12, 10, 0, 42, tzinfo=UTC)
    )
    untimed = _observation(source_id="synthetic-c", announced_at=None)
    closings = internal.closings_file(
        [_observation(), earlier, untimed, _observation(school_index=0, school_id="000000000001")],
        generated_at=generated,
        directory=stamp,
    )
    rows = closings.closings()
    assert [row.school for row in rows] == [0, 1]
    assert rows[1] == replace(
        _observation().closing(), announced_at=datetime(2027, 1, 12, 10, 0, tzinfo=UTC)
    )
    only_untimed = internal.closings_file([untimed], generated_at=generated, directory=stamp)
    assert only_untimed.closings()[0].announced_at is None
    with pytest.raises(internal.ConflictError):
        internal.closings_file(
            [
                _observation(),
                _observation(status=Status.CLOSED, shift_minutes=None, clock_minute=None),
            ],
            generated_at=generated,
            directory=stamp,
        )


def test_covered_file_counts_only_complete_listings() -> None:
    stamp = DirectoryStamp(generated_on=date(2026, 9, 24), schools=6, districts=2)

    def seen(source: str, *, complete: bool, schools: tuple[int, ...]) -> Any:
        return internal.CoverageObservation(
            source_id=source,
            source_url=HttpUrl("https://example.com/list"),
            snapshot_at=datetime(2027, 1, 12, 13, 0, tzinfo=UTC),
            complete=complete,
            school_indices=schools,
        )

    covered = internal.covered_file(
        [
            seen("a", complete=True, schools=(0, 1, 2)),
            seen("b", complete=True, schools=(3,)),
            seen("c", complete=False, schools=(5,)),
        ],
        generated_at=datetime(2027, 1, 12, 13, 5, tzinfo=UTC),
        directory=stamp,
    )
    assert covered.ranges == ((0, 3),)


def test_observation_checks() -> None:
    with pytest.raises(ValidationError, match="only delays"):
        _observation(status=Status.CLOSED)
    with pytest.raises(ValidationError, match="announced after the snapshot"):
        _observation(announced_at=datetime(2027, 1, 12, 12, 1, tzinfo=UTC))

    def snapshot(sha256: str | None, size: int | None, error: str | None) -> Any:
        return internal.SourceSnapshot(
            source_id="a",
            url=HttpUrl("https://example.com/list"),
            fetched_at=datetime(2027, 1, 12, 13, 0, tzinfo=UTC),
            http_status=200,
            sha256=sha256,
            bytes=size,
            error=error,
        )

    with pytest.raises(ValidationError, match="both set"):
        snapshot("0" * 64, None, None)
    with pytest.raises(ValidationError, match="what went wrong"):
        snapshot(None, None, None)
    assert snapshot(None, None, "timed out").error == "timed out"
    assert snapshot("0" * 64, 10, None).bytes == 10


# Remaining refusals ------------------------------------------------------------------


def test_season_days_and_states_are_sorted_and_non_empty() -> None:
    value = example("season-stats")
    value["days"].reverse()
    _refused(SeasonStats, value, "sorted and unique")
    value = example("season-stats")
    value["days"].insert(0, ["2026-12-01", 0, 0, 0, 0])
    _refused(SeasonStats, value, "at least one school")
    value = example("season-stats")
    value["states"].reverse()
    _refused(SeasonStats, value, "states must be sorted")


def test_calibration_totals_and_leads() -> None:
    value = example("track-record")
    value["leads"][0]["no_school"]["bins"] = []
    _refused(TrackRecord, value, "cover 0 to 100")
    value = example("track-record")
    value["leads"][0]["no_school"]["bins"][1][0] = 15
    _refused(TrackRecord, value, "without gaps")
    value = example("track-record")
    value["leads"][0]["no_school"]["outcomes"] += 1
    _refused(TrackRecord, value, "outcomes is not the sum")
    value = example("track-record")
    value["leads"].reverse()
    _refused(TrackRecord, value, "sorted by lead_days")
    value = example("track-record")
    value["leads"][0]["lead_days"] = 3
    _refused(TrackRecord, value, "lead_days")


def test_district_ids_are_sorted() -> None:
    value = example("school-directory")
    value["districts"]["ids"].reverse()
    _refused(SchoolDirectoryMeta, value, "district ids must be sorted")


def test_replay_peak_cannot_exceed_distinct_schools() -> None:
    value = example("replay-index")
    value["replays"][0]["peak_schools"] = 5
    _refused(ReplayIndex, value, "more than the distinct schools")


def test_local_dates_are_not_datetimes() -> None:
    stamp = {"generated_on": datetime(2026, 9, 24, tzinfo=UTC), "schools": 1, "districts": 1}
    with pytest.raises(ValidationError, match="calendar day"):
        DirectoryStamp.model_validate(stamp)


def test_unix_seconds_needs_an_aware_datetime() -> None:
    assert unix_seconds(datetime(1970, 1, 1, 0, 1, 1, 999_999, tzinfo=UTC)) == 61
    with pytest.raises(ValueError, match="aware"):
        unix_seconds(datetime(2027, 1, 12))

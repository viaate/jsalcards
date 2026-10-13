"""What a replay reads beside ``load_rows``: a row's comments and its list's posted time.

Every value here is SYNTHETIC; the posted texts copy only the forms lists use.
"""

import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from replays.world import CHICAGO
from snowlight.replays.rows import (
    DETAIL_FIELDS,
    NO_EXTRA,
    RowExtra,
    detail_of,
    posted_stamp,
    reader_text,
    row_extras,
)

CAPTURE = datetime(2025, 1, 8, 11, 26, tzinfo=UTC)  # 05:26 in Chicago


@pytest.mark.parametrize(
    ("extra", "detail"),
    [
        ({"comments_line1": "AMI Day"}, "AMI Day"),
        ({"comment": "  NTI   Day "}, "NTI Day"),
        ({"comments": '["Remote learning", "No buses"]'}, "Remote learning. No buses"),
        ({"comments": "[not json"}, "[not json"),
        ({"comments": "[not json]"}, "[not json]"),
        ({"comments": '{"a": 1}'}, '{"a": 1}'),
        ({"comments": "[]"}, ""),
        ({"comments": ["E-Learning", ["Day 2"]]}, "E-Learning. Day 2"),
        ({"comments": 3, "note": None, "message": ""}, ""),
        ({"complete_status": "Closed Tuesday"}, ""),  # repeats the status
        ({"comments": "Closed Tuesday Closed Closed Tuesday"}, ""),
        ({"status_two_name_one": "Wrenfield R-3 - Closed Tuesday"}, ""),
        (
            {"status_two_name_one": "Schools: Wrenfield R-3 - Closed Tuesday"},
            "Schools: Wrenfield R-3 - Closed Tuesday",
        ),
        ({"comment": "AMI Day", "comments_line1": "AMI day"}, "AMI Day"),  # said once
        ({"day_label": "Tomorrow Tue Jan 16, 2024"}, "Tomorrow Tue Jan 16, 2024"),
        ({"location": "Jackson, Wrenfield, MO", "line": "Wrenfield R-3: Closed"}, ""),
    ],
)
def test_the_detail_is_each_field_that_adds_a_word(extra: dict[str, object], detail: str) -> None:
    assert detail_of("Wrenfield R-3", "Closed Tuesday", extra) == detail


def test_the_detail_fields_keep_their_order() -> None:
    extra = {"note": "Snow day", "status2": "No buses", "comment": "AMI Day"}
    assert detail_of("x", "Closed", extra) == "No buses. AMI Day. Snow day"
    assert DETAIL_FIELDS.index("status2") < DETAIL_FIELDS.index("comment")


@pytest.mark.parametrize(
    ("status", "detail", "text"),
    [
        ("Closed Tuesday", "", "Closed Tuesday"),
        ("Closed Tuesday", "AMI Day", "Closed Tuesday. AMI Day"),
        ("Closed Tuesday. ", "AMI Day", "Closed Tuesday. AMI Day"),
        ("Closed;", "E-Learning", "Closed. E-Learning"),
        ("", "Closed", "Closed"),
    ],
)
def test_the_reader_text(status: str, detail: str, text: str) -> None:
    assert reader_text(status, detail) == text


def test_row_extras_follow_the_rows_file(tmp_path: Path) -> None:
    rows = [
        {
            "source_id": "gray-syn",
            "fetched_at": "2025-01-08T11:26:00+00:00",
            "raw_name": "Wrenfield R-3",
            "raw_status": "Closed Wednesday",
            "raw_updated_text": " 1/7/2025 4:41:31 PM ",
            "raw_extra": {"comments_line1": "AMI Day", "updated_zone": "UTC"},
        },
        {
            "source_id": "gray-syn",
            "fetched_at": "2025-01-08T11:26:00Z",
            "raw_name": None,
            "raw_status": None,
            "raw_updated_text": "",
            "raw_extra": "not a mapping",
        },
        {
            "source_id": "gray-syn",
            "fetched_at": "2025-01-08T11:26:00Z",
            "raw_name": "Kestrel R-1",
            "raw_status": "Closed tomorrow",
            "raw_updated_text": "1/7/2025 7:41:31 AM",
            "raw_extra": {"updated_scope": "page"},
        },
    ]
    path = tmp_path / "rows.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows) + "\n[]\n", encoding="utf-8")
    assert row_extras(path) == {
        ("gray-syn", "2025-01-08T11:26:00Z"): (
            RowExtra(detail="AMI Day", posted="1/7/2025 4:41:31 PM", posted_zone="UTC"),
            NO_EXTRA,
            RowExtra(posted="1/7/2025 7:41:31 AM", page_stamp=True),
        )
    }


@pytest.mark.parametrize(
    ("text", "named", "expected"),
    [
        ("1/7/2025 4:41:31 PM", None, "2025-01-07T22:41"),
        ("01/07/2025 04:41pm", None, "2025-01-07T22:41"),
        ("01/07/2025 04:41:53 PM CST", None, "2025-01-07T22:41"),
        ("01/07/2025 04:41:53 PM EST", None, "2025-01-07T21:41"),
        ("4:41pm on 1/7/2025", None, "2025-01-07T22:41"),
        ("4:41pm on 1/7/25", None, "2025-01-07T22:41"),
        ("January 7, 2025 4:41 pm CST", None, "2025-01-07T22:41"),
        ("Jan. 7, 2025 4:41 p.m.", None, "2025-01-07T22:41"),
        ("UPDATED TUESDAY, JAN 7 AT 4:41 PM", None, "2025-01-07T22:41"),
        ("SYNTHETIC Emergency Info for Tue. Jan. 7 - 4:41 pm", None, "2025-01-07T22:41"),
        ("UPDATED FRIDAY, DEC 27 AT 4:41 PM", None, "2024-12-27T22:41"),  # last year
        ("2025-01-07 16:41:30", None, "2025-01-07T22:41"),
        ("2025-01-07 22:41:30", "UTC", "2025-01-07T22:41"),
        ("2025-01-07T16:41:00-06:00", None, "2025-01-07T22:41"),
        ("2025-01-07T22:41:00Z", None, "2025-01-07T22:41"),
        ("2025-01-07T22:41:00.5+0000", None, "2025-01-07T22:41"),
        ("12:10am on 1/8/2025", None, "2025-01-08T06:10"),
        ("12:10pm on 1/8/2025", None, None),  # after the capture: not believed
        ("1/8/2025 6:00 AM", None, "2025-01-08T12:00"),  # within the hour's slack
        ("01/07/25 04:41:53 PM EST", None, "2025-01-07T21:41"),  # a two-digit year
        ("4:41 PM CST January 7, 2025", None, "2025-01-07T22:41"),
        ("Tue Jan 07 16:41:30 CST 2025", None, "2025-01-07T22:41"),  # a 24-hour clock
        ("Updated 55 mins ago", None, None),
        ("Smarch 7, 2025 4:41 pm", None, None),
        ("2/30/2025 4:41 PM", None, None),
        ("", None, None),
        (None, None, None),
    ],
)
def test_posted_stamps(text: str | None, named: str | None, expected: str | None) -> None:
    posted = posted_stamp(text, CAPTURE, CHICAGO, named)
    assert (None if posted is None else posted.at.strftime("%Y-%m-%dT%H:%M")) == expected
    assert posted is None or (posted.at.tzinfo is UTC and not posted.date_only)
    assert posted is None or posted.day == posted.at.astimezone(ZoneInfo(CHICAGO)).date()


@pytest.mark.parametrize(
    ("text", "day"),
    [
        ("2025-01-07", date(2025, 1, 7)),
        ("1/7/2025", date(2025, 1, 7)),
        ("2025-01-08", date(2025, 1, 8)),  # the capture's own day
        ("2025-01-09", None),  # a day after the capture: not believed
        ("2025-02-30", None),
    ],
)
def test_a_stamp_with_a_date_only_is_known_to_the_day(text: str, day: date | None) -> None:
    """Gray lists give "2025-01-07": a day, no time. It stands at noon of that day."""
    posted = posted_stamp(text, CAPTURE, CHICAGO)
    assert (None if posted is None else posted.day) == day
    if posted is not None and day is not None:
        assert posted.date_only
        assert posted.at == datetime.combine(day, time(12), tzinfo=ZoneInfo(CHICAGO))

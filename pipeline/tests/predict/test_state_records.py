"""Public state records of past school days (each-school P2d): Kentucky's files read, checked
and joined to districts, on synthetic files only (no state file's text is kept here)."""

import hashlib
import io
import re
import zipfile
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Final
from xml.sax.saxutils import escape

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.predict import record, state_records
from snowlight.predict.config import PIPELINE_ROOT
from snowlight.predict.record import (
    Call,
    Cause,
    PastDay,
    Scope,
    SourceKind,
    YearCount,
    counts_of,
    past_days_of,
)
from snowlight.predict.state_records import (
    StateFile,
    StateRecordError,
    StateRecords,
    build_ky,
    checked,
    past_keys,
    pdf_lines,
    read_summary,
    read_trend,
    text_runs,
    wanted,
)
from snowlight.sources.nces.xlsx import column_index

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
HEADER = (
    "District Number", "District Name", "Opening Day", "Students First Day",
    "Students Last Day", "Total Number of Professional Development Days",
    "Professional Development Days", "Holiday Days", "Planning Days",
    "Total Number of Weather Days", "Weather Days", "Total Number of Illness Days",
    "Illness Days", "Total Number of District Wide Disaster Days",
    "District Wide Disaster Days", "Fall Break Days", "Winter Break Days", "Spring Break Days",
    "Other Break Days", "Number of NTI Days Used\n\nDistricts with over 10 NTI days",
)  # fmt: skip


def _letters(index: int) -> str:
    out = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        out = chr(ord("A") + rest) + out
    return out


def workbook(rows: Sequence[Sequence[str]]) -> bytes:
    """A one-sheet workbook of inline strings (a synthetic summary)."""
    cells = "".join(
        f'<row r="{r + 1}">'
        + "".join(
            f'<c r="{_letters(c)}{r + 1}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
            for c, v in enumerate(row)
            if v
        )
        + "</row>"
        for r, row in enumerate(rows)
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
            '<sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        book.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="t" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        book.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{MAIN}"><sheetData>{cells}</sheetData></worksheet>',
        )
    return buffer.getvalue()


def district(  # noqa: PLR0913 - one synthetic district row
    number: str,
    *,
    weather: Sequence[str] = (),
    illness: Sequence[str] = (),
    disaster: Sequence[str] = (),
    holidays: Sequence[str] = (),
    nti: str = "0",
    weather_total: int | None = None,
    first: str = "08/12/2024",
    last: str = "05/23/2025",
) -> list[str]:
    values = {
        "District Number": number,
        "District Name": f"Synthetic {number}",
        "Students First Day": first,
        "Students Last Day": last,
        "Holiday Days": ", ".join(holidays),
        "Total Number of Weather Days": str(
            len(weather) if weather_total is None else weather_total
        ),
        "Weather Days": ", ".join(weather),
        "Total Number of Illness Days": str(len(illness)),
        "Illness Days": ", ".join(illness),
        # the real files read 0 here even in rows that list D days
        "Total Number of District Wide Disaster Days": "0",
        "District Wide Disaster Days": ", ".join(disaster),
        "Number of NTI Days Used\n\nDistricts with over 10 NTI days": nti,
    }
    return [values.get(name, "") for name in HEADER]


def summary(*rows: list[str]) -> bytes:
    return workbook([list(HEADER), *rows])


def _pdf_string(text: str) -> bytes:
    return b"(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode() + b")"


def trend_pdf(rows: Sequence[tuple[str, Sequence[int | str]]], *, split: int = 1) -> bytes:
    """A synthetic Five Year Weather Trend: one cell a text run, the header's years in runs of
    their own, the page's content in two streams split inside row ``split``."""
    years = ("2020-2021", "2021-2022", "2022-2023", "2023-2024", "2024-2025")
    cells: list[list[tuple[float, bytes]]] = [
        [
            (28.8, _pdf_string("District")),
            *((150.0 + 60 * i, _pdf_string(y)) for i, y in enumerate(years)),
        ]
    ]
    for number, counts in rows:
        line = [
            (38.0, _pdf_string(number)),
            (80.0, b"[(Synth)-3 (etic )12 (" + number.encode() + b")]"),
        ]
        line += [(150.0 + 60 * i, _pdf_string(str(c))) for i, c in enumerate(counts)]
        line.append(
            (470.0, _pdf_string(str(max(*(int(c) for c in counts if str(c).isdigit()), 1))))
        )
        cells.append(line)
    streams: list[bytes] = []
    body = b""
    for r, line in enumerate(cells):
        y = 550.0 - 15 * r
        for c, (x, text) in enumerate(line):
            op = b"TJ" if text.startswith(b"[") else b"Tj"
            body += b"BT\n/P <</MCID 1 >>BDC\n/TT0 1 Tf\n"
            body += f"12 -0 0 12 {x} {y} Tm\n".encode() + text + b" " + op + b"\nEMC\nET\n"
            if r == split + 1 and c == 0:
                streams.append(body)
                body = b""
    streams.append(body)
    out = b"%PDF-1.6\n"
    refs = " ".join(f"{10 + i} 0 R" for i in range(len(streams)))
    out += f"3 0 obj\n<</Type/Page/Parent 2 0 R/Contents[{refs}]>>\nendobj\n".encode()
    out += b"2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n"
    for i, stream in enumerate(streams):
        packed = zlib.compress(stream)
        out += f"{10 + i} 0 obj\n<</Filter/FlateDecode/Length {len(packed)}>>stream\n".encode()
        out += packed + b"\nendstream\nendobj\n"
    return out + b"%%EOF\n"


def _file(id_: str, form: str, years: Sequence[str], data: bytes) -> StateFile:
    return StateFile(
        id=id_,
        form=form,  # type: ignore[arg-type]
        url=f"https://example.invalid/{id_}",
        page="https://example.invalid/page",
        fetched=date(2026, 11, 14),
        bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        years=tuple(years),
        parser=state_records.PARSER_VERSION,
        edition=1,
    )


CODES: dict[str, Any] = yaml.safe_load(
    (state_records.STATE_RECORDS_PATH).read_text(encoding="utf-8")
)["states"]["ky"]["codes"]


def state(files: Mapping[str, tuple[str, Sequence[str], bytes]], **extra: Any) -> StateRecords:
    return StateRecords.model_validate(
        {
            "state": "ky",
            "complete": "synthetic",
            "files": [_file(i, f, y, d).model_dump() for i, (f, y, d) in files.items()],
            "codes": CODES,
            "ids": extra.get("ids", {"001": "9900001", "005": "9900005"}),
            "id_rule": "synthetic",
            "unmapped": extra.get("unmapped", {"606": "no LEA"}),
            "not_weather": extra.get("not_weather", ()),
            "unconfirmed": extra.get("unconfirmed", ()),
        }
    )


def pinned(ky: StateRecords, files: Mapping[str, bytes]) -> StateRecords:
    """``ky`` with each file's ``written`` pins set to what it builds now (a reviewed pin)."""
    keys = build_ky(ky, files).keys
    return ky.model_copy(
        update={
            "files": tuple(
                item.model_copy(
                    update={
                        "written": {
                            kind: hashlib.sha256(
                                keys[record.past_key(item.id, item.edition, kind)]
                            ).hexdigest()
                            for kind in state_records.KINDS[item.form]
                        }
                    }
                )
                for item in ky.files
            )
        }
    )


def built(
    rows24: Sequence[list[str]],
    trend: Sequence[tuple[str, Sequence[int]]] = (),
    **extra: Any,
) -> state_records.Built:
    files: dict[str, tuple[str, Sequence[str], bytes]] = {
        "ky-summary-2024-25": ("ky_summary", ("2024-25",), summary(*rows24))
    }
    if trend:
        files["ky-trend-2025-26"] = (
            "ky_trend",
            ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25"),
            trend_pdf(trend),
        )
    ky = state(files, **extra)
    return build_ky(ky, {i: d for i, (_, _, d) in files.items()})


def days_of(found: state_records.Built) -> dict[tuple[str, date], PastDay]:
    return {(d.unit, d.day): d for d in found.days}


# --- reading ----------------------------------------------------------------------------------


def test_the_summary_is_read_by_header_never_by_position() -> None:
    rows = read_summary(
        summary(district("001", weather=["01/07/25", "01/08/25"], nti="9")), "2024-25"
    )
    assert len(rows) == 1
    (row,) = rows
    assert row.number == "001"
    assert row.dated["W"] == (date(2025, 1, 7), date(2025, 1, 8))
    assert row.counts == {"W": 2, "I": 0, "N": 9, "D": 0}
    assert (row.first, row.last) == (date(2024, 8, 12), date(2025, 5, 23))
    # a column moved changes nothing; a column missing refuses the file
    moved = [list(reversed(HEADER)), list(reversed(district("001", weather=["01/07/25"])))]
    assert read_summary(workbook(moved), "2024-25")[0].dated["W"] == (date(2025, 1, 7),)
    with pytest.raises(StateRecordError, match="columns missing"):
        read_summary(workbook([list(HEADER[:-1]), district("001")[:-1]]), "2024-25")
    assert column_index("T") == len(HEADER) - 1


@pytest.mark.parametrize(
    ("cell", "said"),
    [
        ("01/07/2025", "does not read"),
        ("13/07/25", "does not read"),
        ("01/07/25; 01/08/25", "does not read"),
        ("01/07/26", "outside 2024-25"),
    ],
)
def test_a_date_that_does_not_read_or_lies_outside_the_year_refuses_the_file(
    cell: str, said: str
) -> None:
    row = district("001")
    row[HEADER.index("Weather Days")] = cell
    row[HEADER.index("Total Number of Weather Days")] = "1"
    with pytest.raises(StateRecordError, match=said):
        read_summary(summary(row), "2024-25")


def test_a_count_that_does_not_read_refuses_the_file() -> None:
    with pytest.raises(StateRecordError, match="count that does not read"):
        read_summary(summary(district("001", nti="ten")), "2024-25")


def test_pdf_text_runs_follow_tm_td_and_strings() -> None:
    content = b"BT 12 0 0 12 10 500 Tm (A\\(b\\)\\101) Tj 0 -1.5 Td [(x)-300 (y)] TJ <4142> Tj ET"
    assert text_runs(content) == [(10.0, 500.0, "A(b)A"), (10.0, 482.0, "x y"), (10.0, 482.0, "AB")]
    with pytest.raises(StateRecordError):
        text_runs(b"BT (open Tj ET")


def test_pdf_lines_join_a_row_split_across_content_streams() -> None:
    data = trend_pdf([("001", (1, 2, 0, 2, 0)), ("005", (0, 0, 0, 0, 1))], split=1)
    lines = pdf_lines(data)
    assert ["005", "Synthetic 005", "0", "0", "0", "0", "1", "1"] in lines
    rows = read_trend(data)
    assert [(r.number, r.counts) for r in rows] == [
        ("001", {"2020-21": 1, "2021-22": 2, "2022-23": 0, "2023-24": 2, "2024-25": 0}),
        ("005", {"2020-21": 0, "2021-22": 0, "2022-23": 0, "2023-24": 0, "2024-25": 1}),
    ]


def test_a_trend_row_that_does_not_read_refuses_the_file() -> None:
    data = trend_pdf([("001", (1, "two", 0, 2, 0))])
    with pytest.raises(StateRecordError, match="does not read"):
        read_trend(data)


# --- the rows ---------------------------------------------------------------------------------


def test_weather_days_become_closed_past_rows_closings_only_of_class_unknown() -> None:
    found = built([district("001", weather=["01/07/25", "01/08/25"])])
    rows = days_of(found)
    assert set(rows) == {("9900001", date(2025, 1, 7)), ("9900001", date(2025, 1, 8))}
    for row in rows.values():
        assert row.source_kind is SourceKind.PAST_RECORDS
        assert (row.call, row.cause, row.scope, row.code) == (
            Call.CLOSED, Cause.WEATHER, Scope.WHOLE, "W",
        )  # fmt: skip
        assert row.weather_day
        assert row.closings_only
        assert not row.source_complete
        # LR14: a class not known is kept as unknown and never fit-usable
        assert (row.klass, row.weather, row.situation, row.tropical) == (
            "unknown",
            None,
            None,
            None,
        )
        assert not row.fit_usable
        assert not record.past_fit_rule(row)
        assert row.sources == ("ky-summary-2024-25",)


def test_the_id_rule_maps_by_number_and_lists_the_unmapped_never_guessed() -> None:
    found = built([district("001", weather=["01/07/25"]), district("606", weather=["01/07/25"])])
    assert {d.unit for d in found.days} == {"9900001"}
    assert {c.unit for c in found.counts} == {"9900001"}
    assert found.unmapped == ["606"]
    assert any("not matched: 606" in line for line in found.lines)
    with pytest.raises(StateRecordError, match="007: a district number in neither"):
        built([district("007", weather=["01/07/25"])])


def test_a_weather_count_unlike_its_dated_days_refuses_the_file() -> None:
    with pytest.raises(StateRecordError, match="3 W days counted, 2 dated"):
        built([district("001", weather=["01/07/25", "01/08/25"], weather_total=3)])


def test_a_weather_day_off_the_districts_own_calendar_is_listed_and_not_written() -> None:
    found = built(
        [
            district(
                "001",
                weather=["01/07/25", "01/20/25", "01/25/25", "05/27/25"],
                holidays=["01/20/25"],
            )
        ]
    )
    # a holiday, a Saturday, and a day after its last student day
    assert {d.day for d in found.days} == {date(2025, 1, 7)}
    assert found.dropped == [
        ("001", date(2025, 1, 20)), ("001", date(2025, 1, 25)), ("001", date(2025, 5, 27)),
    ]  # fmt: skip
    # the count stays the state's count
    (w,) = [c for c in found.counts if c.code == "W"]
    assert w.days == 4


def test_the_day_after_comes_from_the_districts_own_calendar() -> None:
    found = built(
        [
            district(
                "001",
                # Fri W; Tue W after a Monday holiday; Thu W after a Wed illness day; Mon W
                # after a Fri emergency day; Wed W after a Tue held (or at home: not known)
                weather=["01/10/25", "01/21/25", "01/30/25", "02/10/25", "02/19/25"],
                illness=["01/29/25"],
                disaster=["02/07/25"],
                holidays=["01/20/25"],
            ),
            district("005", weather=["08/12/24"]),
        ]
    )
    rows = days_of(found)
    u = "9900001"
    assert (rows[u, date(2025, 1, 10)].after, rows[u, date(2025, 1, 10)].after_weather) == (
        None, None,
    )  # fmt: skip
    # the Tuesday after a Monday holiday reads back to the Friday... which held school
    assert (rows[u, date(2025, 1, 21)].after, rows[u, date(2025, 1, 21)].after_weather) == (
        None, None,
    )  # fmt: skip
    assert (rows[u, date(2025, 1, 30)].after, rows[u, date(2025, 1, 30)].after_weather) == (
        True, False,
    )  # fmt: skip
    assert (rows[u, date(2025, 2, 10)].after, rows[u, date(2025, 2, 10)].after_weather) == (
        True, None,
    )  # fmt: skip
    assert rows[u, date(2025, 2, 19)].after is None
    # its first student day has no day before it
    assert rows["9900005", date(2024, 8, 12)].after is None


def test_a_weather_day_after_a_weather_day_across_a_holiday_is_a_day_after() -> None:
    found = built([district("001", weather=["01/17/25", "01/21/25"], holidays=["01/20/25"])])
    row = days_of(found)["9900001", date(2025, 1, 21)]
    assert (row.after, row.after_weather) == (True, True)
    assert not row.fit_usable


def test_counts_are_kept_as_counts_and_never_spread_into_dates() -> None:
    found = built(
        [
            district("001", weather=["01/07/25"], nti="10", disaster=["04/28/25", "04/29/25"]),
            district("005"),
            district("606", weather=["01/07/25"]),
        ],
        trend=[("001", (1, 2, 0, 2, 1)), ("005", (0, 0, 3, 0, 0)), ("606", (4, 4, 4, 4, 1))],
    )
    counts = {(c.unit, c.year, c.code): c for c in found.counts}
    # the trend gives 2020-21 to 2023-24; the summary its own year and every code
    assert {k[1] for k in counts if k[2] == "W"} == {
        "2020-21", "2021-22", "2022-23", "2023-24", "2024-25",
    }  # fmt: skip
    assert counts["9900001", "2021-22", "W"].days == 2
    assert counts["9900001", "2021-22", "W"].sources == ("ky-trend-2025-26",)
    assert counts["9900001", "2024-25", "W"].sources == ("ky-summary-2024-25",)
    assert counts["9900005", "2022-23", "W"].days == 3
    # the summary's own year: its W count is the state's number of dated W days, never the NTI
    # days added in, and a dated count is checked (0 named), an undated one cannot be (None)
    w24 = counts["9900001", "2024-25", "W"]
    assert (w24.days, w24.not_weather, w24.unconfirmed) == (1, 0, 0)
    assert (counts["9900005", "2024-25", "W"].days, counts["9900005", "2024-25", "N"].days) == (
        0, 0,
    )  # fmt: skip
    trend = counts["9900001", "2021-22", "W"]
    assert (trend.not_weather, trend.unconfirmed) == (None, None)
    assert all(
        (c.not_weather, c.unconfirmed) == (None, None)
        for c in found.counts
        if c.sources == ("ky-trend-2025-26",)
    )
    assert counts["9900001", "2024-25", "N"].days == 10
    assert counts["9900001", "2024-25", "D"].days == 2
    assert counts["9900001", "2024-25", "D"].disaster is True
    assert counts["9900005", "2024-25", "D"].disaster is False
    assert counts["9900001", "2020-21", "W"].covid
    assert counts["9900001", "2020-21", "W"].disaster is None
    assert not counts["9900001", "2021-22", "W"].covid
    # the only dated rows are the summary's weather days: no count became a date
    assert [(d.unit, d.day) for d in found.days] == [("9900001", date(2025, 1, 7))]
    assert "past/ky-trend-2025-26/v1/days" not in found.keys
    assert all(c.source_kind is SourceKind.PAST_RECORDS for c in found.counts)


def test_the_trends_year_must_equal_the_summarys_in_every_row() -> None:
    rows = [district("001", weather=["01/07/25"]), district("005")]
    ok = built(rows, trend=[("001", (0, 0, 0, 0, 1)), ("005", (0, 0, 0, 0, 0))])
    assert any("2024-25 equals the summary in 2 of 2 rows" in line for line in ok.lines)
    with pytest.raises(StateRecordError, match="equals the summary in 1 of 2 rows"):
        built(rows, trend=[("001", (0, 0, 0, 0, 2)), ("005", (0, 0, 0, 0, 0))])
    with pytest.raises(StateRecordError, match="equals the summary"):
        built(rows, trend=[("001", (0, 0, 0, 0, 1))])


def test_the_keys_hold_the_rows_and_read_back_as_the_record() -> None:
    found = built(
        [district("001", weather=["01/07/25", "01/08/25"]), district("005", weather=["02/03/25"])],
        trend=[("001", (1, 1, 1, 1, 2)), ("005", (0, 0, 0, 0, 1))],
    )
    assert sorted(found.keys) == [
        "past/ky-summary-2024-25/v1/counts", "past/ky-summary-2024-25/v1/days",
        "past/ky-trend-2025-26/v1/counts",
    ]  # fmt: skip
    assert past_days_of(found.keys["past/ky-summary-2024-25/v1/days"]) == found.days
    assert counts_of(found.keys["past/ky-trend-2025-26/v1/counts"]) + counts_of(
        found.keys["past/ky-summary-2024-25/v1/counts"]
    ) == sorted(found.counts, key=lambda c: c.sources != ("ky-trend-2025-26",))
    # codes, ids, counts and dates only: no name, no address
    for data in found.keys.values():
        assert b"Synthetic" not in data
        assert b"://" not in data
        assert b"example" not in data
    # the counts said equal the rows written (the truth test)
    said = next(line for line in found.lines if "ky-summary-2024-25: " in line)
    assert said.startswith(
        "predict each-school past: ky-summary-2024-25: 3 dated rows over 2 districts (3 weather"
        " days, 3 of class unknown, 1 the day after a day off school, 0 fit-usable)"
    )
    w = sum(c.days for c in found.counts if c.code == "W" and c.year == "2024-25")
    assert f"W {w} days" in said


# --- pins and the step ------------------------------------------------------------------------


def test_a_file_unlike_its_pin_is_refused() -> None:
    data = summary(district("001"))
    item = _file("ky-summary-2024-25", "ky_summary", ("2024-25",), data)
    assert checked(item, data) is data
    with pytest.raises(StateRecordError, match="needs a reviewed pin"):
        checked(item, data + b" ")
    with pytest.raises(StateRecordError, match="needs a reviewed pin"):
        checked(item, data[:-1] + bytes([data[-1] ^ 1]))


def _sources(rows: Sequence[list[str]], **extra: Any) -> tuple[StateRecords, dict[str, bytes]]:
    data = {"ky-summary-2024-25": summary(*rows)}
    ky = state(
        {"ky-summary-2024-25": ("ky_summary", ("2024-25",), data["ky-summary-2024-25"])}, **extra
    )
    return pinned(ky, data), {f"https://example.invalid/{k}": v for k, v in data.items()}


def test_past_keys_reads_a_state_only_while_a_key_is_missing() -> None:
    ky, served = _sources([district("001", weather=["01/07/25"])])
    asked: list[str] = []

    def fetch(url: str) -> bytes:
        asked.append(url)
        return served[url]

    said: list[str] = []
    keys = past_keys([ky], (), None, fetch, said.append)
    assert sorted(keys) == ["past/ky-summary-2024-25/v1/counts", "past/ky-summary-2024-25/v1/days"]
    assert asked == ["https://example.invalid/ky-summary-2024-25"]
    # one key held: only the other is offered (the file is read again to make it)
    keys = past_keys([ky], ("past/ky-summary-2024-25/v1/days",), None, fetch, said.append)
    assert sorted(keys) == ["past/ky-summary-2024-25/v1/counts"]
    # every key held: nothing is fetched
    asked.clear()
    held = ("past/ky-summary-2024-25/v1/days", "past/ky-summary-2024-25/v1/counts")
    assert past_keys([ky], held, None, fetch, said.append) == {}
    assert asked == []
    assert wanted(ky, held) == []


def test_past_keys_writes_nothing_of_a_state_that_fails_a_check() -> None:
    ky, served = _sources([district("001", weather=["01/07/25"])])
    said: list[str] = []
    keys = past_keys([ky], (), None, lambda url: served[url] + b"changed", said.append)
    assert keys == {}
    assert any(
        line.startswith("::warning::predict each-school past: ky:") and "reviewed pin" in line
        for line in said
    )


def test_past_keys_reads_a_folder_by_file_id(tmp_path: Path) -> None:
    ky, served = _sources([district("001", weather=["01/07/25"])])
    (tmp_path / "ky-summary-2024-25").write_bytes(
        served["https://example.invalid/ky-summary-2024-25"]
    )

    def no_fetch(url: str) -> bytes:
        raise AssertionError(url)

    assert len(past_keys([ky], (), tmp_path, no_fetch, lambda _: None)) == 2


# --- the committed config ---------------------------------------------------------------------


def _keys(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def test_the_committed_config_pins_kentuckys_three_files_and_maps_171_of_172() -> None:
    config = state_records.load()
    ky = config.states["ky"]
    assert [f.id for f in ky.files] == [
        "ky-summary-2024-25", "ky-summary-2025-26", "ky-trend-2025-26",
    ]  # fmt: skip
    assert {f.sha256 for f in ky.files} == {
        "3732d6556382bca7f42d112d0b5e6ff999e112133710f98b1d2bafb649c74acf",
        "69e00e92b95d66d8ef2920c39e3d7d1c016536806aedc4e17c1975a3d5c7dbae",
        "ea219f5b8574f28386ab7284b9d9f9b843a4ecb4b0bd1b46b207ce01e0207a14",
    }
    assert all((f.url or "").startswith("https://www.education.ky.gov/") for f in ky.files)
    assert len(ky.ids) == 171
    assert set(ky.unmapped) == {"606"}
    assert all(u.startswith("21") for u in ky.ids.values())
    # each file's keys are of a reviewed edition and their bytes pinned
    assert [(f.edition, sorted(f.written)) for f in ky.files] == [
        (1, ["counts", "days"]), (1, ["counts", "days"]), (1, ["counts"]),
    ]  # fmt: skip
    # the W days found by review to be another cause (each checked against the district's own
    # notice or local news): Jefferson County's shelter-in-place day, Bullitt County's water
    # main break and its three illness days of the February 2025 flu wave
    assert {(n.number, n.day, n.code) for n in ky.not_weather} == {
        ("275", date(2025, 11, 5), "W"), ("071", date(2025, 8, 19), "W"),
        ("071", date(2025, 2, 5), "W"), ("071", date(2025, 2, 6), "W"),
        ("071", date(2025, 2, 7), "W"),
    }  # fmt: skip
    # the checked W days the review could not tie to the weather: every W day of the illness
    # wave's two weeks not tied to it, every W date of three districts or fewer not tied, and
    # Letcher County's two days with no water after line breaks the reports tie to the freeze
    # and thaw (so never another cause)
    unsure = {(n.number, n.day) for n in ky.unconfirmed}
    assert len(unsure) == len(ky.unconfirmed) == 42
    assert sum(n.day >= date(2025, 7, 1) for n in ky.unconfirmed) == 13
    assert {("331", date(2026, 2, 12)), ("331", date(2026, 2, 13))} <= unsure
    assert {n.code for n in ky.unconfirmed} == {"W"}
    assert {
        ("301", date(2025, 2, 7)), ("325", date(2025, 2, 7)), ("331", date(2025, 2, 7)),
        ("485", date(2025, 2, 7)), ("301", date(2025, 2, 13)), ("025", date(2025, 2, 6)),
        ("415", date(2025, 2, 6)), ("495", date(2025, 2, 6)), ("271", date(2026, 1, 23)),
        ("493", date(2026, 1, 20)), ("125", date(2024, 12, 4)), ("585", date(2025, 4, 15)),
    } <= unsure  # fmt: skip
    assert not unsure & {(n.number, n.day) for n in ky.not_weather}
    assert all(date(2024, 7, 1) <= n.day < date(2026, 7, 1) for n in ky.unconfirmed)
    # the written map: only W is dated; N, I and D are counts
    assert {c for c, m in ky.codes.items() if m.dated} == {"W"}
    assert {c for c, m in ky.codes.items() if m.counted} == {"W", "N", "I", "D"}
    w = ky.codes["W"]
    assert (w.call, w.cause, w.weather_day) == (Call.CLOSED, Cause.WEATHER, True)
    # LR8: no field named with the words the schema guard refuses
    names = set(_keys(yaml.safe_load(state_records.STATE_RECORDS_PATH.read_text("utf-8"))))
    assert not {n for n in names if re.search("source|host", n, re.IGNORECASE)}


def test_a_config_that_maps_a_number_twice_or_both_ways_is_refused(tmp_path: Path) -> None:
    raw = yaml.safe_load(state_records.STATE_RECORDS_PATH.read_text("utf-8"))
    raw["states"]["ky"]["unmapped"]["001"] = "both"
    path = tmp_path / "s.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(StateRecordError, match="both mapped and unmapped"):
        state_records.load(path)
    raw["states"]["ky"]["unmapped"].pop("001")
    raw["states"]["ky"]["ids"]["999"] = raw["states"]["ky"]["ids"]["001"]
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(StateRecordError, match="mapped twice"):
        state_records.load(path)


def test_past_rows_refuse_what_they_cannot_be() -> None:
    (row,) = built([district("001", weather=["01/07/25"])]).days
    body = row.model_dump()
    for change in (
        {"source_kind": SourceKind.LIVE_MAP},
        {"source_complete": True},
        {"call": Call.OPEN},
        {"weather": 3},
        {"tropical": False},
        {"fit_usable": True},
        {"after_weather": True},
        {"cause": Cause.NAMED},
    ):
        with pytest.raises(ValueError, match=r"\d{4}-\d{2}-\d{2} 9900001|fit_usable"):
            PastDay.model_validate(body | change)
    count = built([district("001")]).counts[0].model_dump()
    with pytest.raises(ValueError, match="live kind"):
        YearCount.model_validate(count | {"source_kind": SourceKind.LIVE_READ})


# --- days listed under the weather code that were another cause (LR12) ------------------------


def _other(number: str, day: date) -> dict[str, Any]:
    return {"number": number, "day": day, "code": "W", "why": "synthetic", "checked": day}


def test_a_weather_day_the_written_list_names_is_kept_never_a_weather_day() -> None:
    found = built(
        [district("001", weather=["01/07/25", "01/08/25"]), district("005", weather=["01/07/25"])],
        not_weather=[_other("001", date(2025, 1, 7))],
    )
    rows = days_of(found)
    other = rows["9900001", date(2025, 1, 7)]
    assert (other.code, other.call, other.cause, other.weather_day, other.fit_usable) == (
        "W", Call.CLOSED, Cause.NAMED, False, False,
    )  # fmt: skip
    # the next day is the day after a day off for a named cause, never for the weather
    after = rows["9900001", date(2025, 1, 8)]
    assert (after.cause, after.weather_day, after.after, after.after_weather) == (
        Cause.WEATHER, True, True, False,
    )  # fmt: skip
    # another district's day of the same date stays a weather day
    assert rows["9900005", date(2025, 1, 7)].weather_day
    # the count stays the state's number and says how many of it are not the weather
    w = {c.unit: c for c in found.counts if c.code == "W"}
    assert (w["9900001"].days, w["9900001"].not_weather) == (2, 1)
    assert (w["9900005"].days, w["9900005"].not_weather) == (1, 0)
    assert all(c.not_weather == 0 for c in found.counts if c.code != "W")
    said = next(line for line in found.lines if "ky-summary-2024-25: " in line)
    assert "(3 dated rows" not in said
    assert "3 dated rows over 2 districts (2 weather days," in said
    assert said.endswith("(D 0, I 0, N 0, W 3 days, 1 W days not the weather)")
    assert (
        "predict each-school past: ky: 1 days listed under a weather code were another cause"
        " (written list), kept with cause named and never a weather day: 001 2025-01-07"
    ) in found.lines


def test_a_written_exception_the_files_do_not_list_refuses_them() -> None:
    with pytest.raises(StateRecordError, match="not_weather days the files do not list: 001"):
        built(
            [district("001", weather=["01/07/25"])],
            not_weather=[_other("001", date(2025, 1, 8))],
        )


def test_a_weather_day_the_review_could_not_confirm_is_kept_never_a_weather_day() -> None:
    found = built(
        [district("001", weather=["01/07/25", "01/08/25"]), district("005", weather=["01/07/25"])],
        unconfirmed=[_other("001", date(2025, 1, 7))],
    )
    rows = days_of(found)
    unsure = rows["9900001", date(2025, 1, 7)]
    assert (unsure.code, unsure.call, unsure.cause, unsure.weather_day, unsure.fit_usable) == (
        "W", Call.CLOSED, Cause.ANY, False, False,
    )  # fmt: skip
    # the next day is the day after a day off school whose cause is not known
    after = rows["9900001", date(2025, 1, 8)]
    assert (after.weather_day, after.after, after.after_weather) == (True, True, None)
    assert rows["9900005", date(2025, 1, 7)].weather_day
    w = {c.unit: c for c in found.counts if c.code == "W"}
    assert (w["9900001"].days, w["9900001"].not_weather, w["9900001"].unconfirmed) == (2, 0, 1)
    assert (w["9900005"].days, w["9900005"].unconfirmed) == (1, 0)
    assert all(c.unconfirmed == 0 for c in found.counts if c.code != "W")
    said = next(line for line in found.lines if "ky-summary-2024-25: " in line)
    assert "3 dated rows over 2 districts (2 weather days," in said
    assert said.endswith("(D 0, I 0, N 0, W 3 days, 1 W days not confirmed the weather)")
    assert (
        "predict each-school past: ky: 1 days listed under a weather code the review could not"
        " tie to the weather (written list), kept with cause any and never a weather day:"
        " 001 2025-01-07"
    ) in found.lines


def test_an_unconfirmed_day_the_files_do_not_list_refuses_them() -> None:
    with pytest.raises(StateRecordError, match="unconfirmed days the files do not list: 001"):
        built(
            [district("001", weather=["01/07/25"])],
            unconfirmed=[_other("001", date(2025, 1, 8))],
        )


def test_a_date_listed_twice_in_a_cell_refuses_the_file() -> None:
    with pytest.raises(StateRecordError, match="001: a W date twice"):
        built([district("001", weather=["01/07/25", "01/07/25"])])


def test_the_config_refuses_an_unpinned_key_or_an_exception_of_no_weather_day(
    tmp_path: Path,
) -> None:
    raw = yaml.safe_load(state_records.STATE_RECORDS_PATH.read_text("utf-8"))
    path = tmp_path / "s.yaml"
    changes: tuple[Callable[[dict[str, Any]], object], ...] = (
        lambda r: r["files"][0]["written"].pop("days"),
        lambda r: r["files"][2]["written"].update(days="0" * 64),
        lambda r: r["files"][1]["written"].update(counts="xyz"),
    )
    for change in changes:
        broken = yaml.safe_load(yaml.safe_dump(raw))
        change(broken["states"]["ky"])
        path.write_text(yaml.safe_dump(broken))
        with pytest.raises(StateRecordError, match="written keys are not all pinned"):
            state_records.load(path)
    for name in ("not_weather", "unconfirmed"):
        for entry in (
            _other("606", date(2025, 11, 5)),
            _other("275", date(2025, 11, 5)) | {"code": "N"},
        ):
            broken = yaml.safe_load(yaml.safe_dump(raw))
            broken["states"]["ky"][name].append(entry)
            path.write_text(yaml.safe_dump(broken))
            with pytest.raises(StateRecordError, match=f"{name} .* not a mapped weather day"):
                state_records.load(path)
    # a day in both lists, or twice in one, is refused
    for name, entry in (
        ("unconfirmed", _other("071", date(2025, 2, 5))),
        ("not_weather", _other("071", date(2025, 2, 5))),
        ("unconfirmed", _other("301", date(2025, 2, 7))),
    ):
        broken = yaml.safe_load(yaml.safe_dump(raw))
        broken["states"]["ky"][name].append(entry)
        path.write_text(yaml.safe_dump(broken))
        with pytest.raises(StateRecordError, match="a day written twice"):
            state_records.load(path)


# --- the step's own report and its pins ---------------------------------------------------------


def test_past_keys_says_each_files_line_the_unmapped_and_the_days_not_written() -> None:
    ky, served = _sources(
        [
            district("001", weather=["01/07/25", "01/20/25"], holidays=["01/20/25"]),
            district("606", weather=["01/07/25"]),
        ]
    )
    said: list[str] = []
    assert len(past_keys([ky], (), None, lambda u: served[u], said.append)) == 2
    assert said[0].startswith(
        "predict each-school past: ky-summary-2024-25: 1 dated rows over 1 districts (1 weather"
        " days,"
    )
    assert (
        "predict each-school past: ky: district numbers with no LEA, listed and not matched: 606"
        in said
    )
    assert said[-1] == (
        "predict each-school past: ky: 1 weather days are not school days on the district's own"
        " calendar, not written: 001 2025-01-20"
    )


def test_past_keys_refuses_a_build_unlike_its_pins_and_writes_nothing() -> None:
    ky, served = _sources([district("001", weather=["01/07/25"])])
    item = ky.files[0]
    for written in ({"days": item.written["days"]}, item.written | {"counts": "0" * 64}):
        drifted = ky.model_copy(update={"files": (item.model_copy(update={"written": written}),)})
        said: list[str] = []
        assert past_keys([drifted], (), None, lambda u: served[u], said.append) == {}
        (warning,) = [line for line in said if line.startswith("::warning::")]
        assert "past/ky-summary-2024-25/v1/counts SHA-256" in warning
        assert warning.endswith(
            "a changed output needs a reviewed pin and a new edition: nothing written"
        )
        assert "/v1/days" not in warning


def test_a_new_edition_writes_new_keys_beside_the_kept_ones() -> None:
    ky, served = _sources([district("001", weather=["01/07/25"])])
    held = ("past/ky-summary-2024-25/v1/days", "past/ky-summary-2024-25/v1/counts")
    assert wanted(ky, held) == []
    # a reviewed fix bumps the edition (and its pins): its keys are new, the old ones stay
    item = ky.files[0].model_copy(update={"edition": 2})
    two = pinned(
        ky.model_copy(update={"files": (item,)}),
        {item.id: served[f"https://example.invalid/{item.id}"]},
    )
    assert wanted(two, held) == [
        "past/ky-summary-2024-25/v2/counts", "past/ky-summary-2024-25/v2/days",
    ]  # fmt: skip
    keys = past_keys([two], held, None, lambda u: served[u], lambda _: None)
    assert sorted(keys) == wanted(two, held)


# --- New York's Schedule A-8 (records-ny, edition 1; synthetic workbooks only) ------------------

NY_CODES: dict[str, Any] = yaml.safe_load(
    (state_records.STATE_RECORDS_PATH).read_text(encoding="utf-8")
)["states"]["ny"]["codes"]
PHRASES: dict[str, str] = {m: code for code, v in NY_CODES.items() for m in v["match"]}
"""The form's pick-list phrases, read from the config (they are written nowhere else)."""
WX, SOE, ELEC = (NY_CODES[code]["match"][0] for code in ("WX", "SOE", "ELEC"))
NY_IDS = {"010100": "3600001", "020200": "3600002", "030300": "3600003", "040400": "3600004"}
NYC = "300000"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
SLOTS = 3


def _a8_columns(slots: int) -> list[tuple[str, str]]:
    """Each column's key and its row-3 label, in the export's own order (the code and name
    columns are labeled in the second header row instead)."""
    cols = [
        ("code", ""),
        ("name", ""),
        ("comment", "SED Use Form - sch A5 item 4b disapproved comment"),
        ("status", "SED Use Only Form: Extraordinary Condition status"),
    ]
    for k in range(1, slots + 1):
        cols += [
            (f"date{k}", f"Sch A8:Extra Condition Date{'' if k == 1 else k}"),
            (f"reason{k}", f"Sch A8:Extra Condition Reason-{k}"),
            (f"building{k}", f"Sch A8:Extra Condition Building-{k}"),
            (f"grade{k}", f"Sch A8:Extra Condition k-3-{k}"),
        ]
    return [*cols, ("total", "Sch A8:Extra Condition Total Days-1"), ("url", "Sch A8:URL")]


def a8_book(
    claim: str,
    rows: Sequence[Mapping[str, str]],
    *,
    order: Sequence[int] | None = None,
    title: str | None = None,
) -> bytes:
    """A synthetic yearly A-8 export: the title, the Refkey row (with the code and name
    columns' labels), the row-3 labels, the SEQ row, one row per district, the marker."""
    cols = _a8_columns(SLOTS)
    if order is not None:
        cols = [cols[i] for i in order]
    start, end = claim.split("-")
    head = title or f"Extract of data from Claim Year {start}-20{end} Data as of: synthetic"
    refkey = [
        {"code": "Beds Code", "name": "Institution Name"}.get(key, f"Refkey: {9000 + i}")
        for i, (key, _) in enumerate(cols)
    ]
    labels = [f"{label} | Field size 10 | CY:{claim}" if label else "" for _, label in cols]
    seq = ["" if key in {"code", "name"} else f"SEQ: {i}" for i, (key, _) in enumerate(cols)]
    body = [[row.get(key, "") for key, _ in cols] for row in rows]
    marker = ["XXXXXX" if key == "code" else "" for key, _ in cols]
    return workbook([[head], refkey, labels, seq, *body, marker])


def serial(day: date) -> str:
    return str((day - date(1899, 12, 30)).days)


def a8_row(code: str, *slots: tuple[date | str, str, str], **cells: str) -> dict[str, str]:
    """One district's row: each slot's (date or raw cell, reason, building)."""
    row = {"code": code, "name": f"Synthetic {code}", **cells}
    for k, (day, reason, building) in enumerate(slots, start=1):
        row |= {
            f"date{k}": serial(day) if isinstance(day, date) else day,
            f"reason{k}": reason,
            f"building{k}": building,
            f"grade{k}": "1",
        }
    return row


def _school_year(claim: str) -> str:
    start = int(claim[:4]) - 1
    return f"{start}-{(start + 1) % 100:02d}"


def ny_state(books: Mapping[str, bytes], **extra: Any) -> StateRecords:
    """A New York state of received files (claim year to bytes), with synthetic ids."""
    return StateRecords.model_validate(
        {
            "state": "ny",
            "id_digits": 6,
            "complete": "synthetic",
            "files": [
                StateFile(
                    id=f"ny-a8-{claim}",
                    form="ny_a8",
                    received="synthetic-request",
                    fetched=date(2026, 11, 18),
                    bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    years=(_school_year(claim),),
                    parser=state_records.PARSER_VERSION,
                    edition=1,
                ).model_dump()
                for claim, data in books.items()
            ],
            "codes": NY_CODES,
            "ids": extra.get("ids", NY_IDS),
            "id_rule": "synthetic",
            "one_school": extra.get("one_school", ()),
            "unmapped": extra.get("unmapped", {NYC: "New York City: never spread"}),
        }
    )


def ny_built(*rows: Mapping[str, str], claim: str = "2026-27", **extra: Any) -> state_records.Built:
    book = a8_book(claim, rows)
    return state_records.build_ny(ny_state({claim: book}, **extra), {f"ny-a8-{claim}": book})


def ny_pinned(ny: StateRecords, files: Mapping[str, bytes]) -> StateRecords:
    keys = state_records.build_ny(ny, files).keys
    return ny.model_copy(
        update={
            "files": tuple(
                item.model_copy(
                    update={
                        "written": {
                            kind: hashlib.sha256(
                                keys[record.past_key(item.id, item.edition, kind)]
                            ).hexdigest()
                            for kind in state_records.KINDS[item.form]
                        }
                    }
                )
                for item in ny.files
            )
        }
    )


MON, TUE, WED, FRI = date(2025, 12, 8), date(2025, 12, 9), date(2025, 12, 10), date(2025, 12, 12)
"""School days of school year 2025-26 (claim year 2026-27)."""


def test_a8_is_read_by_label_never_by_position() -> None:
    rows = [
        a8_row("010100", (MON, WX, "WHOLE DISTRICT"), (TUE, SOE, "Synthetic Building")),
        a8_row("020200", (WED, ELEC, "")),
        a8_row("030300"),
    ]
    codes = {k: state_records.StateCode.model_validate(v) for k, v in NY_CODES.items()}
    plain = state_records.read_a8(a8_book("2026-27", rows), "2026-27", codes)
    width = len(_a8_columns(SLOTS))
    shuffled = list(range(width))
    shuffled.reverse()  # every column moves, the code column too
    moved = state_records.read_a8(a8_book("2026-27", rows, order=shuffled), "2026-27", codes)
    assert moved == plain
    assert [(r.number, [(e.day, e.code, e.scope) for e in r.entries]) for r in plain] == [
        ("010100", [(MON, "WX", Scope.WHOLE), (TUE, "SOE", Scope.SHARE)]),
        ("020200", [(WED, "ELEC", Scope.UNKNOWN)]),
        ("030300", []),
    ]
    # a slot with no reason column refuses the file
    cut = [i for i, (key, _) in enumerate(_a8_columns(SLOTS)) if key != "reason2"]
    with pytest.raises(StateRecordError, match="without its date, reason or building"):
        state_records.read_a8(a8_book("2026-27", rows, order=cut), "2026-27", codes)


def test_a8_title_claim_year_must_equal_the_pin() -> None:
    book = a8_book("2026-27", [a8_row("010100", (MON, WX, "WHOLE DISTRICT"))])
    ny = ny_state({"2026-27": book})
    other = ny.model_copy(
        update={"files": (ny.files[0].model_copy(update={"years": ("2024-25",)}),)}
    )
    # the pin's school year 2024-25 is claim year 2025-26: its id and title must say so
    with pytest.raises(StateRecordError, match="not the id of claim year 2025-26"):
        state_records.build_ny(other, {"ny-a8-2026-27": book})
    renamed = other.model_copy(
        update={"files": (other.files[0].model_copy(update={"id": "ny-a8-2025-26"}),)}
    )
    with pytest.raises(StateRecordError, match="title names another claim year"):
        state_records.build_ny(renamed, {"ny-a8-2025-26": book})
    titled = a8_book("2026-27", [], title="Extract of data from Claim Year 2025-2026")
    codes = {k: state_records.StateCode.model_validate(v) for k, v in NY_CODES.items()}
    with pytest.raises(StateRecordError, match="title names another claim year"):
        state_records.read_a8(titled, "2026-27", codes)


def test_a8_a_date_outside_the_base_school_year_is_held_not_written() -> None:
    found = ny_built(
        a8_row(
            "010100",
            (MON, WX, "WHOLE DISTRICT"),
            (date(2026, 12, 9), WX, "WHOLE DISTRICT"),  # the claim year itself
            (date(2025, 6, 10), WX, "WHOLE DISTRICT"),  # the year before
        )
    )
    assert [d.day for d in found.days] == [MON]
    assert "held 2 outside the school year" in found.lines[0]


def test_a8_a_weekend_date_is_held_not_written() -> None:
    found = ny_built(a8_row("010100", (date(2025, 12, 13), WX, "WHOLE DISTRICT"), (FRI, WX, "")))
    assert [d.day for d in found.days] == [FRI]
    assert "1 on a weekend" in found.lines[0]
    # a weekday our default calendar has no school (after June 15: lead ruling RN6) is held too
    june = ny_built(a8_row("010100", (date(2026, 6, 22), ELEC, "")))
    assert june.days == []
    assert "1 not a school day by the default calendar" in june.lines[0]
    assert june.dropped == []  # held and counted, never listed by district and date


def test_a8_a_date_twice_in_a_row_is_one_day() -> None:
    found = ny_built(
        a8_row("010100", (MON, WX, "WHOLE DISTRICT"), (MON, WX, "WHOLE DISTRICT"), (TUE, WX, ""))
    )
    assert [d.day for d in found.days] == [MON, TUE]
    assert "1 the same date twice in a row" in found.lines[0]
    assert [(c.code, c.days) for c in found.counts] == [("WX", 2)]


def test_a8_reasons_map_to_codes_and_causes() -> None:
    days = [date(2025, 12, d) for d in (1, 2, 3, 4, 5, 8, 9, 10, 11)]
    phrases = list(PHRASES.items())
    assert len(phrases) == len(days)
    rows = [
        a8_row(f"{50 + i:02d}0000", (day, phrase, "WHOLE DISTRICT"))
        for i, (day, (phrase, _)) in enumerate(zip(days, phrases, strict=True))
    ]
    blank = a8_row("600000", (date(2025, 12, 15), "   ", "WHOLE DISTRICT"))
    ids = {r["code"]: f"36{70 + i:05d}" for i, r in enumerate([*rows, blank])}
    book = a8_book("2026-27", [*rows, blank])
    found = state_records.build_ny(ny_state({"2026-27": book}, ids=ids), {"ny-a8-2026-27": book})
    by_unit = {d.unit: d for d in found.days}
    got = [(by_unit[ids[r["code"]]].code, by_unit[ids[r["code"]]].cause) for r in rows]
    assert [c for c, _ in got] == [c for _, c in phrases]
    named = {"ELEC", "WATER", "HEAT", "BLDG", "THREAT", "CHEM"}
    for code, cause in got:
        assert cause is (
            Cause.WEATHER if code == "WX" else Cause.NAMED if code in named else Cause.ANY
        )
    assert {d.code for d in found.days if d.weather_day} == {"WX"}  # SOE is never a weather day
    none = by_unit[ids["600000"]]
    assert (none.code, none.cause, none.weather_day) == ("NONE", Cause.ANY, False)


def test_a8_building_is_whole_share_or_unknown_and_its_text_is_never_kept() -> None:
    found = ny_built(
        a8_row(
            "010100",
            (MON, WX, "WHOLE DISTRICT"),
            (TUE, WX, " District "),
            (WED, WX, "Plantedbuildingname Elementary"),
        ),
        a8_row("020200", (MON, WX, "")),
    )
    assert [(d.unit, d.day, d.scope) for d in found.days] == [
        ("3600001", MON, Scope.WHOLE), ("3600002", MON, Scope.UNKNOWN),
        ("3600001", TUE, Scope.WHOLE), ("3600001", WED, Scope.SHARE),
    ]  # fmt: skip
    assert all(b"lanted" not in data for data in found.keys.values())
    assert not any("lanted" in line for line in found.lines)


def test_a8_rows_are_closings_only_class_unknown_never_fit_usable() -> None:
    found = ny_built(a8_row("010100", (MON, WX, "WHOLE DISTRICT"), (TUE, SOE, "")))
    assert found.days
    for day in found.days:
        assert (day.call, day.source_kind) == (Call.CLOSED, SourceKind.PAST_RECORDS)
        assert (day.closings_only, day.source_complete) == (True, False)
        assert (day.klass, day.weather, day.situation, day.tropical) == (
            "unknown",
            None,
            None,
            None,
        )
        assert day.fit_usable is False
        assert day.reasons == ()
        assert day.sources == ("ny-a8-2026-27",)


def test_a8_counts_only_for_a_district_year_with_a_day_never_zero() -> None:
    found = ny_built(
        a8_row("010100", (MON, WX, ""), (TUE, WX, ""), (WED, SOE, "")),
        a8_row("020200"),  # files a row, lists no date: no count, never a zero
        a8_row("030300", (date(2025, 12, 13), WX, "")),  # its only date is held
    )
    assert [(c.unit, c.year, c.code, c.days) for c in found.counts] == [
        ("3600001", "2025-26", "SOE", 1), ("3600001", "2025-26", "WX", 2),
    ]  # fmt: skip
    assert all(c.days > 0 for c in found.counts)
    assert all((c.not_weather, c.unconfirmed, c.disaster) == (0, 0, None) for c in found.counts)
    covid = ny_built(a8_row("010100", (date(2020, 12, 17), WX, "")), claim="2021-22")
    assert [c.covid for c in covid.counts] == [True]


def test_a8_the_id_rule_maps_six_digit_codes_and_lists_the_unmapped() -> None:
    found = ny_built(
        a8_row("010100", (MON, WX, "")), a8_row(NYC, (MON, WX, "WHOLE DISTRICT")), a8_row("020200")
    )
    assert [d.unit for d in found.days] == ["3600001"]
    assert found.unmapped == [NYC]
    assert "1 of a code the id rule does not map" in found.lines[0]
    assert "2 of 3 codes mapped, 1 of 2 with a date" in found.lines[1]
    assert found.lines[-1].endswith(f"listed and not matched: {NYC}")
    with pytest.raises(StateRecordError, match="in neither ids nor unmapped"):
        ny_built(a8_row("990000"))
    # a row that is not a 6-digit code (nor the closing marker) refuses the file
    with pytest.raises(StateRecordError, match="not a district code"):
        ny_built(a8_row("01010"))


DATED: Final = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{2}")


def test_a8_key_bytes_and_lines_carry_no_name_url_comment_or_building_text(
    tmp_path: Path,
) -> None:
    planted = {
        "name": "Plantedname Central School District",
        "comment": "Plantedcomment about the claim",
        "url": "https://plantedurl.invalid/a8",
        "status": "PLANTEDSTATUS",
    }
    rows = [
        a8_row("010100", (MON, WX, "Plantedbuilding Hall"), (TUE, SOE, ""), **planted),
        a8_row(NYC, (WED, WX, "WHOLE DISTRICT"), name="Plantedname City"),
        a8_row("020200", (date(2025, 12, 13), WX, ""), (date(2026, 6, 22), WX, "")),
    ]
    book = a8_book("2026-27", rows)
    ny = ny_pinned(ny_state({"2026-27": book}), {"ny-a8-2026-27": book})
    (tmp_path / "ny-a8-2026-27").write_bytes(book)
    said: list[str] = []
    keys = past_keys([ny], (), tmp_path, lambda _: b"", said.append)
    assert keys
    # a refused file and a drifted pin: their warning lines too
    bad = a8_book("2026-27", [a8_row("010100", ("4566x", WX, ""))])
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "ny-a8-2026-27").write_bytes(bad)
    past_keys([ny_state({"2026-27": bad})], (), tmp_path / "bad", lambda _: b"", said.append)
    drifted = ny_state({"2026-27": book})  # pinned with no written keys
    past_keys([drifted], (), tmp_path, lambda _: b"", said.append)
    assert any("not a serial" in line for line in said)
    assert any("reviewed pin" in line for line in said)
    for text in (*keys.values(), *(line.encode() for line in said)):
        assert b"lanted" not in text.lower()
        assert b"PLANTEDSTATUS" not in text
    for line in said:
        # counts, codes, file ids and SHA-256 prefixes only: no mapped district code at all,
        # and never a date
        assert not any(code in line for code in ("010100", "020200"))
        assert not DATED.search(line), line


def test_a8_a_date_that_is_not_a_serial_or_a_reason_not_on_the_list_refuses_the_file() -> None:
    for cell in ("12/09/2025", "4566", "45999.5", "x"):
        with pytest.raises(StateRecordError, match="not a serial"):
            ny_built(a8_row("010100", (cell, WX, "")))
    with pytest.raises(StateRecordError, match="a reason on no list"):
        ny_built(a8_row("010100", (MON, "PLANTED REASON", "")))
    # an empty or space-only date cell is blank (its slot is not read); a blank reason on a
    # dated slot reads as NONE
    found = ny_built(a8_row("010100", ("   ", WX, "WHOLE DISTRICT"), (MON, "  ", "")))
    assert [(d.day, d.code) for d in found.days] == [(MON, "NONE")]


def test_a8_the_day_after_comes_from_the_previous_school_day_written() -> None:
    found = ny_built(
        a8_row(
            "010100",
            (MON, WX, ""),
            (TUE, ELEC, ""),
            (WED, SOE, ""),
        ),
        a8_row("020200", (FRI, WX, ""), (date(2025, 12, 15), "   ", "")),  # Friday, then Monday
        a8_row("030300", (date(2025, 12, 13), WX, ""), (date(2025, 12, 15), WX, "")),
    )
    after = {(d.unit, d.day): (d.after, d.after_weather) for d in found.days}
    assert after == {
        ("3600001", MON): (None, None),  # its school day before is not a written day
        ("3600001", TUE): (True, True),  # after a weather day
        ("3600001", WED): (True, False),  # after a named cause
        ("3600002", FRI): (None, None),
        ("3600002", date(2025, 12, 15)): (True, True),  # across the weekend
        ("3600003", date(2025, 12, 15)): (None, None),  # a held Saturday is never a day before
    }
    soe = ny_built(a8_row("010100", (MON, SOE, ""), (TUE, WX, "")))
    assert {d.day: (d.after, d.after_weather) for d in soe.days}[TUE] == (True, None)


def test_received_files_are_never_fetched_and_write_nothing_without_files_or_keys() -> None:
    book = a8_book("2026-27", [a8_row("010100", (MON, WX, ""))])
    ny = ny_pinned(ny_state({"2026-27": book}), {"ny-a8-2026-27": book})

    def no_fetch(url: str) -> bytes:
        raise AssertionError(url)

    said: list[str] = []
    assert past_keys([ny], (), None, no_fetch, said.append) == {}
    assert said == [
        "predict each-school past: ny: 1 of its files were received, never fetched: they are"
        " built only with --files, so 2 keys are not written"
    ]
    with pytest.raises(StateRecordError, match="read only from --files"):
        state_records.read_files(ny, None, no_fetch)
    # a received file has no URL and no page; a file has exactly one of a URL and a label
    item = ny.files[0].model_dump()
    for change in (
        {"url": "https://example.invalid/a8"},
        {"received": None},
        {"page": "https://example.invalid/page"},
    ):
        with pytest.raises(ValueError, match=r"exactly one of url and received|a page only"):
            StateFile.model_validate({**item, **change})


def test_the_committed_config_pins_sixteen_ny_files_and_maps_686_of_701() -> None:
    ny = state_records.load().states["ny"]
    claims = [f"{y}-{(y + 1) % 100:02d}" for y in range(2011, 2027)]
    assert [f.id for f in ny.files] == [f"ny-a8-{c}" for c in claims]
    assert [f.years for f in ny.files] == [(_school_year(c),) for c in claims]
    assert all(f.form == "ny_a8" and f.received and f.url is None for f in ny.files)
    assert all(f.page is None and f.fetched == date(2026, 11, 18) for f in ny.files)
    assert len({f.sha256 for f in ny.files}) == 16
    assert (ny.id_digits, ny.dated_public) == (6, False)
    assert len(ny.ids) == 686
    assert len(ny.unmapped) == 15
    assert len(ny.ids) + len(ny.unmapped) == 701
    assert NYC in ny.unmapped  # never spread over the city's LEAs (lead ruling RN3)
    assert all(re.fullmatch(r"36\d{5}", u) for u in ny.ids.values())
    assert len(ny.one_school) == 102  # fix r2 (B1): at most one open school in the directory
    assert set(ny.one_school) <= set(ny.ids.values())
    assert set(ny.codes) == {"WX", "SOE", "ELEC", "WATER", "HEAT", "BLDG", "THREAT", "CHEM", "NONE"}
    assert {c for c, m in ny.codes.items() if m.weather_day} == {"WX"}
    assert ny.codes["SOE"].cause is Cause.ANY  # lead ruling RN4
    assert ny.codes["NONE"].match == ()
    # every file writes both keys; the 2012-13 and 2013-14 files (no row written) pin empty bytes
    assert all(sorted(f.written) == ["counts", "days"] for f in ny.files)
    empty = {f.id for f in ny.files if set(f.written.values()) == {EMPTY_SHA256}}
    assert empty == {"ny-a8-2012-13", "ny-a8-2013-14"}
    assert not any(EMPTY_SHA256 in f.written.values() for f in ny.files if f.id not in empty)
    # Kentucky's files are public pages: its dated rows may be published
    ky = state_records.load().states["ky"]
    assert (ky.id_digits, ky.dated_public) == (3, True)
    assert StateRecords.model_fields["dated_public"].default is False  # publishing is chosen


def _tracked() -> list[Path]:
    import subprocess  # noqa: PLC0415

    root = PIPELINE_ROOT.parent
    if not (root / ".git").exists():
        pytest.skip("not a git checkout: no committed files to read")
    names = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    return [root / n.decode() for n in names if n]


KEY_BYTES_MAX: Final = 256 * 1024
"""Above every New York key's bytes (the largest is under 32 KB)."""


def test_no_committed_file_has_the_bytes_of_a_pinned_ny_file() -> None:
    ny = state_records.load().states["ny"]
    sizes = {f.bytes: f.sha256 for f in ny.files}
    pins = {f.sha256 for f in ny.files}
    written = {p for f in ny.files for p in f.written.values()} - {EMPTY_SHA256}
    assert len(written) == 28
    checked_files = 0
    for path in _tracked():
        if not path.is_file() or path.is_symlink():
            continue
        size = path.stat().st_size
        if size not in sizes and not 0 < size <= KEY_BYTES_MAX:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest not in pins, path  # a received A-8 file
        assert digest not in written, path  # a built key's bytes (dated rows, never public)
        checked_files += 1
    assert checked_files > 100


def test_a_file_with_no_written_row_writes_two_empty_pinned_keys_and_never_stops_the_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = a8_book("2013-14", [a8_row("010100"), a8_row("020200")])
    ny = ny_pinned(ny_state({"2013-14": book}), {"ny-a8-2013-14": book})
    assert ny.files[0].written == {"days": EMPTY_SHA256, "counts": EMPTY_SHA256}
    (tmp_path / "ny-a8-2013-14").write_bytes(book)
    keys = past_keys([ny], (), tmp_path, lambda _: b"", lambda _: None)
    assert keys == {"past/ny-a8-2013-14/v1/days": b"", "past/ny-a8-2013-14/v1/counts": b""}
    assert wanted(ny, keys) == []
    # a builder that leaves a wanted key unbuilt: one warning for its state, and Kentucky's
    # keys in the same call are still given
    ky, served = _sources([district("001", weather=["01/07/25"])])
    (tmp_path / "ky-summary-2024-25").write_bytes(
        served["https://example.invalid/ky-summary-2024-25"]
    )
    real = state_records.BUILDERS["ny"]

    def half(state: StateRecords, files: Mapping[str, bytes]) -> state_records.Built:
        out = real(state, files)
        out.keys.pop("past/ny-a8-2013-14/v1/counts")
        return out

    monkeypatch.setitem(state_records.BUILDERS, "ny", half)
    said: list[str] = []
    keys = past_keys([ny, ky], (), tmp_path, lambda _: b"", said.append)
    assert sorted(keys) == ["past/ky-summary-2024-25/v1/counts", "past/ky-summary-2024-25/v1/days"]
    assert (
        said.count(
            "::warning::predict each-school past: ny: built no key"
            " past/ny-a8-2013-14/v1/counts: nothing written"
        )
        == 1
    )


@pytest.mark.parametrize(
    ("cell", "scope"),
    [
        # the reviewed whole-district phrases, as generic words in any case and spacing
        ("WHOLE DISTRICT", Scope.WHOLE),
        (" district ", Scope.WHOLE),
        ("DISTRICT WIDE", Scope.WHOLE),
        ("District-Wide", Scope.WHOLE),
        ("DISTRICTWIDE", Scope.WHOLE),
        ("ENTIRE DISTRICT", Scope.WHOLE),
        ("WHOLE SCHOOL DISTRICT", Scope.WHOLE),
        ("ALL", Scope.WHOLE),
        ("all schools", Scope.WHOLE),
        ("ALL BUILDINGS", Scope.WHOLE),
        # a reason after the phrase, or after WHOLE/ENTIRE DISTRICT, says nothing of the part
        ("WHOLE DISTRICT - LOCAL STATE OF EMERGENCY", Scope.WHOLE),
        ("WHOLE DISTRICT (COUNTY STATE OF EMERGENCY)", Scope.WHOLE),
        ("WHOLE DISTRICT GOVERNOR DECLARED STATE OF EMERGENCY", Scope.WHOLE),
        ("ENTIRE DISTRICT TOWN DECLARED STATE OF EMERG", Scope.WHOLE),  # cut by the cell's width
        ("ENTIRE DISTRICT (SPECIAL ELECTION)", Scope.WHOLE),
        ("DISTRICT WIDE (NO POWER)", Scope.WHOLE),
        ("Plantedtown CSD - state of emergency", Scope.WHOLE),
        # a note that is not a reason may say a part: never whole (fix r2, S1)
        ("WHOLE DISTRICT EXCEPT HIGH SCHOOL", Scope.UNKNOWN),
        ("ALL (EXCEPT HIGH SCHOOL)", Scope.UNKNOWN),
        ("DISTRICT (HIGH SCHOOL ONLY)", Scope.UNKNOWN),
        ("ALL SCHOOLS - ELEMENTARY ONLY", Scope.UNKNOWN),
        ("ENTIRE DISTRICT BUT THE MIDDLE SCHOOL", Scope.UNKNOWN),
        ("WHOLE DISTRICT NOT THE EMERGENCY", Scope.UNKNOWN),
        ("WHOLE DISTRICT - PARTIAL", Scope.UNKNOWN),
        ("WHOLE DISTRICT - PLANTED NOTE", Scope.UNKNOWN),
        ("WHOLE DISTRICT (PLANTED NOTE)", Scope.UNKNOWN),
        ("WHOLE DISTRICT PLANTED NOTE WORDS", Scope.UNKNOWN),
        ("WHOLE DISTRICT 2", Scope.UNKNOWN),
        ("Plantedtown CSD (Plantedname Elementary)", Scope.UNKNOWN),
        # DISTRICT misspelled by one letter
        ("WHOLE DISTRIICT", Scope.WHOLE),
        ("WHOLE DISTRIC", Scope.WHOLE),
        ("ENTIRE DISTRUCT", Scope.WHOLE),
        ("WHOLE DITSRICT", Scope.WHOLE),
        ("WHOLE DISTRIKT", Scope.WHOLE),
        # a cell naming the district itself by its kind word
        ("Plantedtown CSD", Scope.WHOLE),
        ("Plantedtown UFSD", Scope.WHOLE),
        ("Plantedtown Central School District", Scope.WHOLE),
        # blank, the form's own label words, or a reason with no building: no part is said
        (None, Scope.UNKNOWN),
        ("", Scope.UNKNOWN),
        ("   ", Scope.UNKNOWN),
        ("SCHOOL/BUILDING", Scope.UNKNOWN),
        ("School / Building", Scope.UNKNOWN),
        ("BUILDING", Scope.UNKNOWN),
        ("N/A", Scope.UNKNOWN),
        ("GOVERNOR DECLARED STATE OF EMERGENCY", Scope.UNKNOWN),
        # a building, or part of the district, is a share
        ("Plantedname Elementary", Scope.SHARE),
        ("Plantedname Elementary - county state of emergency", Scope.SHARE),
        ("Plantedname Elementary School(360000000000)", Scope.SHARE),
        ("SCHOOL BUILDING - PLANTEDNAME ELEMENTARY", Scope.SHARE),
        ("ALL PLANTED BUILDINGS", Scope.SHARE),
        ("ALL PRIMARY AND PLANTED SCHOOLS", Scope.SHARE),
        ("PLANTED HIGH SCHOOL", Scope.SHARE),
        ("PLANTED MIDDLE SCHOOL ONLY", Scope.SHARE),
        ("DISTRICT OFFICE", Scope.SHARE),
        ("WHOLE PLANTED ACADEMY", Scope.SHARE),
        ("DISTRICT 7 SCHOOL", Scope.SHARE),
        ("PS 999", Scope.SHARE),
        # a building word before a district-kind word names a building (fix r2, S2)
        ("HIGH SCHOOL, PLANTEDTOWN CSD", Scope.SHARE),
        ("PLANTEDNAME ELEMENTARY SD", Scope.SHARE),
        ("Plantedname Middle School UFSD", Scope.SHARE),
        ("Plantedname High School District", Scope.SHARE),
        ("PS 9 CCSD", Scope.SHARE),
    ],
)
def test_a8_building_cell_is_read_as_a_class_of_generic_words(
    cell: str | None, scope: Scope
) -> None:
    """records-ny test 7 (fix r1, B1): every reviewed way the form's building cell says the
    whole district is ``whole``, its placeholder and a reason-only cell are ``unknown``, and
    only a building or part is ``share``."""
    assert state_records.a8_scope(cell) is scope


def test_a8_a_building_of_a_one_school_district_is_never_a_part() -> None:
    """records-ny fix r2 (B1): a building cell of a district the pinned directory lists with at
    most one open school names its one school, so a ``share`` there reads ``unknown`` (the
    directory is one year's, so never ``whole`` either); a whole or unknown cell is kept, and a
    district with more schools keeps its ``share``."""
    rows = (
        a8_row("010100", (MON, WX, "Plantedname Central School"), (TUE, WX, "WHOLE DISTRICT")),
        a8_row("020200", (MON, WX, "Plantedname Elementary"), (TUE, WX, "")),
    )
    found = ny_built(*rows, one_school=("3600001",))
    assert [(d.unit, d.day, d.scope) for d in found.days] == [
        ("3600001", MON, Scope.UNKNOWN), ("3600002", MON, Scope.SHARE),
        ("3600001", TUE, Scope.WHOLE), ("3600002", TUE, Scope.UNKNOWN),
    ]  # fmt: skip
    assert [d.scope for d in ny_built(*rows).days][:1] == [Scope.SHARE]
    # a repeat is compared after the one-school reading: a building and a blank are one class
    same = ny_built(
        a8_row("010100", (MON, WX, "Plantedname Central School"), (MON, WX, "")),
        one_school=("3600001",),
    )
    assert [(d.day, d.scope) for d in same.days] == [(MON, Scope.UNKNOWN)]


def test_a_config_one_school_list_must_be_mapped_once_and_sorted(tmp_path: Path) -> None:
    raw = yaml.safe_load(state_records.STATE_RECORDS_PATH.read_text("utf-8"))
    path = tmp_path / "s.yaml"
    listed = raw["states"]["ny"]["one_school"]
    for bad in (
        [*listed, "3699999"],  # a LEAID the id rule does not map
        [listed[0], *listed],  # twice
        listed[::-1],  # unsorted
    ):
        raw["states"]["ny"]["one_school"] = bad
        path.write_text(yaml.safe_dump(raw))
        with pytest.raises(StateRecordError, match="ny: a one-school LEAID"):
            state_records.load(path)


def test_a8_whole_district_words_and_the_placeholder_reach_the_written_row() -> None:
    found = ny_built(
        a8_row(
            "010100",
            (MON, WX, "DISTRICT WIDE"),
            (TUE, WX, "SCHOOL/BUILDING"),
            (WED, WX, "WHOLE SCHOOL DISTRICT"),
        ),
        a8_row("020200", (MON, SOE, "ENTIRE DISTRICT"), (TUE, SOE, "Plantedname Elementary")),
    )
    assert [(d.unit, d.day, d.scope) for d in found.days] == [
        ("3600001", MON, Scope.WHOLE), ("3600002", MON, Scope.WHOLE),
        ("3600001", TUE, Scope.UNKNOWN), ("3600002", TUE, Scope.SHARE),
        ("3600001", WED, Scope.WHOLE),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ((MON, WX, "WHOLE DISTRICT"), (MON, SOE, "WHOLE DISTRICT")),  # another reason
        ((MON, WX, "WHOLE DISTRICT"), (MON, WX, "Plantedname Elementary")),  # another part
        ((MON, WX, ""), (MON, WX, "WHOLE DISTRICT")),
    ],
)
def test_a8_a_repeat_with_another_reason_or_building_refuses_the_file(
    first: tuple[date, str, str], second: tuple[date, str, str]
) -> None:
    """records-ny fix r1 (S4): a date a row lists twice with another reason or building class
    would lose one silently, so it refuses the file, said by file id with no date or code."""
    with pytest.raises(StateRecordError) as refused:
        ny_built(a8_row("010100", first, second))
    said = str(refused.value)
    assert said == "ny-a8-2026-27: a date twice in a row with another reason or building"
    # the same reason and building class is one day, held and counted (test 5)
    same = ny_built(a8_row("010100", first, (first[0], first[1], first[2].lower())))
    assert len(same.days) == 1


def test_a8_a_row_the_record_refuses_is_said_by_file_id_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """records-ny fix r1 (safety S1): a row the record's own models refuse (their message names
    the day and the district) is said by the file id only, through the builder and the step,
    never as a traceback or a line with a district code or a date."""
    book = a8_book("2026-27", [a8_row("010100", (MON, WX, "WHOLE DISTRICT"))])
    ny = ny_state({"2026-27": book})
    monkeypatch.setattr(record, "past_fit_rule", lambda _row: True)  # every row is refused
    with pytest.raises(StateRecordError) as refused:
        state_records.build_ny(ny, {"ny-a8-2026-27": book})
    assert str(refused.value) == "ny-a8-2026-27: a row the record refuses"
    assert refused.value.__cause__ is None
    assert refused.value.__suppress_context__
    (tmp_path / "ny-a8-2026-27").write_bytes(book)
    said: list[str] = []
    assert past_keys([ny], (), tmp_path, lambda _: b"", said.append) == {}
    assert said == [
        "::warning::predict each-school past: ny: ny-a8-2026-27: a row the record refuses:"
        " nothing written"
    ]

    # a model refusal from any builder is said by its type only
    def refusing(_state: StateRecords, _files: Mapping[str, bytes]) -> state_records.Built:
        record.YearCount.model_validate({"unit": "3600001", "year": MON.isoformat()})
        raise AssertionError  # pragma: no cover - the model refuses first

    monkeypatch.setitem(state_records.BUILDERS, "ny", refusing)
    said.clear()
    assert past_keys([ny], (), tmp_path, lambda _: b"", said.append) == {}
    assert said == ["::warning::predict each-school past: ny: ValidationError: nothing written"]
    for line in said:
        assert "3600001" not in line
        assert "010100" not in line
        assert not DATED.search(line)


KY_PINNED: Final = {
    "ky-summary-2024-25": (
        91389,
        "3732d6556382bca7f42d112d0b5e6ff999e112133710f98b1d2bafb649c74acf",
        {
            "days": "8d5571b02b07455094cf34f526d20ab6a359ade0fa7b4cf7d1ce923101a27490",
            "counts": "32afa88ced7da63b9018f21e097a6491e82d09d2ea02624b2f7361df7ef6b27b",
        },
    ),
    "ky-summary-2025-26": (
        79304,
        "69e00e92b95d66d8ef2920c39e3d7d1c016536806aedc4e17c1975a3d5c7dbae",
        {
            "days": "94b55e5e3d1dddb08d4baaef9c3088e7b1a29f21218a1976925067bf7514d9fd",
            "counts": "d562d29f679cba79ec3ce3e62162efaa27db700fc89bd1b76c2c3d3b092da6e6",
        },
    ),
    "ky-trend-2025-26": (
        145246,
        "ea219f5b8574f28386ab7284b9d9f9b843a4ecb4b0bd1b46b207ce01e0207a14",
        {"counts": "6015073a17235b3d34a1b96911709c36cdebf20bdc1cd6f77dacd3949ca77162"},
    ),
}
"""Kentucky's committed files and written pins before records-ny (base 7a4ae59e), literal."""


def test_kentucky_files_and_written_pins_are_the_ones_before_new_york() -> None:
    """records-ny test 21, Kentucky half (fix r1, S3): Kentucky's committed files, their
    editions and parsers, its codes and its written pins are the literal values from before New
    York entered the config, so no change to StateFile, StateCode or id_digits moves them
    silently (a build whose bytes differ from these pins is refused at run time)."""
    ky = state_records.load().states["ky"]
    assert {f.id: (f.bytes, f.sha256, f.written) for f in ky.files} == KY_PINNED
    assert all(
        (f.edition, f.parser, f.received, f.url is not None) == (1, 1, None, True) for f in ky.files
    )
    assert [f.years for f in ky.files] == [
        ("2024-25",), ("2025-26",), ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25"),
    ]  # fmt: skip
    assert (ky.id_digits, ky.dated_public) == (3, True)
    assert {code: (c.call, c.cause, c.weather_day, c.day_off) for code, c in ky.codes.items()} == {
        "W": (Call.CLOSED, Cause.WEATHER, True, "weather"),
        "N": (None, None, False, None),
        "I": (None, None, False, "named"),
        "D": (None, None, False, "unknown"),
    }

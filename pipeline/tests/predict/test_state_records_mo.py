"""Missouri's school calendar file (records-mo MO-1): the parser, the roll-up and the derived
files, on a small synthetic workbook and directory; the committed files against their pins."""

import gzip
import hashlib
import io
import zipfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from snowlight.predict import state_records, state_records_mo
from snowlight.predict.state_records import StateRecordError
from snowlight.predict.state_records_mo import (
    DATED_HEADER,
    SHEETS,
    YEARLY_HEADER,
    MoCalendarError,
    build,
    read_calendar,
    read_schools,
    roll_up,
)

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
SHARES = (0.5, 0.10)


def _letters(index: int) -> str:
    out = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        out = chr(ord("A") + rest) + out
    return out


def _sheet(rows: Sequence[Sequence[str]]) -> str:
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
    return f'<worksheet xmlns="{MAIN}"><sheetData>{cells}</sheetData></worksheet>'


def workbook(
    dated: Sequence[Sequence[str]],
    yearly: Sequence[Sequence[str]] = (),
    names: Sequence[str] = SHEETS,
) -> bytes:
    """A two-sheet workbook of inline strings, headers first (a synthetic calendar file)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'
            + "".join(
                f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                for i, n in enumerate(names)
            )
            + "</sheets></workbook>",
        )
        book.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{i + 1}" Type="t" Target="worksheets/sheet{i + 1}.xml"/>'
                for i in range(len(names))
            )
            + "</Relationships>",
        )
        book.writestr("xl/worksheets/sheet1.xml", _sheet([DATED_HEADER, *dated]))
        book.writestr("xl/worksheets/sheet2.xml", _sheet([YEARLY_HEADER, *yearly]))
    return buffer.getvalue()


def serial(day: date) -> str:
    return str((day - date(1899, 12, 30)).days)


KIND = {"W": "Actual Weather Day", "M": "Actual Weather Make-up Day", "A": "AMI Day"}


def row(  # noqa: PLR0913, PLR0917 - one synthetic dated row
    code: str, day: date, kind: str, hours: str = "0", building: str = "", half: str = ""
) -> list[str]:
    year = str(day.year + 1 if day.month >= 7 else day.year)
    return [year, code.lstrip("0"), "A DISTRICT", building, "A BUILDING" if building else "",
            "K", "12", half, serial(day), hours, KIND[kind]]  # fmt: skip


def yearly_row(code: str, year: str, building: str, *hours: str) -> list[str]:
    full, partial, ami, std, nonstd = hours
    return [year, code, "A DISTRICT", building, "", "K", "12", "", "0", full, "0", partial,
            ami, "0", std, "0", nonstd]  # fmt: skip


def directory(schools: Sequence[tuple[str, str, str, str, str]]) -> bytes:
    """A CCD school directory zip: (code, LEAID, building, status, charter) per school."""
    lines = ["ST_LEAID,LEAID,ST_SCHID,SY_STATUS_TEXT,CHARTER_TEXT"]
    lines += [
        f"MO-{code},{leaid},MO-{code}-{building}{code},{status},{charter}"
        for code, leaid, building, status, charter in schools
    ]
    lines.append("KS-D0001,2000001,KS-D0001-0001,Open,No")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr(state_records_mo.CCD_MEMBER, "\n".join(lines) + "\n")
    return buffer.getvalue()


# Two LEAs: 000001 with ten deciding schools (0001-0010) and a closed one, 000002 a charter LEA
# with two charter schools; 000003 has no school in the directory.
SCHOOLS = directory(
    [("000001", "2900001", f"{b:04d}", "Open", "No") for b in range(1, 11)]
    + [("000001", "2900001", "0011", "Closed", "No"), ("000001", "2900001", "0012", "Open", "Yes")]
    + [("000002", "2900002", "0001", "Open", "Yes"), ("000002", "2900002", "0002", "Added", "Yes")]
)
IDS = {"000001": "2900001", "000002": "2900002"}
UNMAPPED = {"000003": "no school in the directory"}
TUE = date(2025, 1, 14)


def calls_of(dated: Sequence[Sequence[str]]) -> dict[tuple[str, date], str]:
    rolled = roll_up(read_calendar(workbook(dated)), read_schools(SCHOOLS), *SHARES)
    return {key: call for key, (call, _scope) in rolled.calls.items()}


def buildings(day: date, kind: str, hours: str, n: int, start: int = 1) -> list[list[str]]:
    return [row("000001", day, kind, hours, f"{b:04d}") for b in range(start, start + n)]


def test_a_district_wide_row_decides_ami_remote_zero_hours_closed_hours_short() -> None:
    days = [TUE.replace(day=d) for d in (14, 15, 16, 17)]
    found = calls_of([
        row("000001", days[0], "A"),
        row("000001", days[1], "W"),
        row("000001", days[2], "W", "3.5"),
        row("000001", days[3], "M", "7"),
        row("000002", days[0], "A"),
        row("000002", days[0], "W"),
    ])  # fmt: skip
    assert found == {
        ("000001", days[0]): "remote",
        ("000001", days[1]): "closed",
        ("000001", days[2]): "short",
        ("000001", days[3]): "makeup",
        ("000002", days[0]): "closed",  # a 0-hour weather row beside the AMI row
    }


def test_half_day_program_rows_are_left_out_of_the_roll_up() -> None:
    calendar = read_calendar(
        workbook([row("000001", TUE, "W", half="A"), row("000001", TUE, "W", half="P")])
    )
    rolled = roll_up(calendar, read_schools(SCHOOLS), *SHARES)
    assert rolled.left_half == 2
    assert not rolled.calls


def test_building_rows_decide_by_the_deciding_schools_shares() -> None:
    # 5 of 10 deciding schools with no school: closed; a charter school (0012) and a closed
    # school (0011) never count
    half = buildings(TUE, "W", "0", 5)
    assert calls_of(half) == {("000001", TUE): "closed"}
    assert calls_of(buildings(TUE, "A", "0", 5)) == {("000001", TUE): "remote"}
    four = [*buildings(TUE, "W", "0", 4), row("000001", TUE, "W", "0", "0011"),
            row("000001", TUE, "W", "0", "0012")]  # fmt: skip
    assert calls_of(four) == {("000001", TUE): "some"}
    assert calls_of(buildings(TUE, "W", "0", 1)) == {("000001", TUE): "none"}
    assert calls_of(buildings(TUE, "W", "2", 5)) == {("000001", TUE): "short"}
    made = [*buildings(TUE, "M", "7", 9, start=2), *buildings(TUE, "W", "0", 1)]
    assert calls_of(made) == {("000001", TUE): "makeup"}
    # a charter LEA's deciding schools are its open charter schools
    charter = [row("000002", TUE, "W", "0", "0001")]
    assert calls_of(charter) == {("000002", TUE): "closed"}


def test_a_make_up_row_is_never_a_closing() -> None:
    found = calls_of([row("000001", TUE, "M", "0"), *buildings(TUE.replace(day=15), "M", "0", 10)])
    assert set(found.values()) == {"makeup"}


def test_a_code_with_no_directory_school_is_unknown_listed_and_never_written() -> None:
    data = workbook([row("000003", TUE, "W", building="0001"), row("000001", TUE, "W")])
    built = build(data, SCHOOLS, IDS, UNMAPPED, SHARES)
    days = built.files[state_records_mo.DAYS_FILE].decode().splitlines()
    assert days == [state_records_mo.DAYS_HEADER, "2900001,2025-01-14,C,W,1"]
    assert built.rolled.calls["000003", TUE] == ("unknown", "nodeciding")
    # a day of building rows with no call is written N with its weather flag; a make-up day 0
    later = [*buildings(TUE.replace(day=15), "W", "0", 1), row("000001", TUE.replace(day=16), "M")]
    written = build(workbook(later), SCHOOLS, IDS, UNMAPPED, SHARES).files[
        state_records_mo.DAYS_FILE
    ]
    assert written.decode().splitlines()[1:] == [
        "2900001,2025-01-15,N,B,1",
        "2900001,2025-01-16,M,W,0",
    ]
    with pytest.raises(MoCalendarError, match="in neither ids nor unmapped"):
        build(data, SCHOOLS, IDS, {}, SHARES)
    with pytest.raises(MoCalendarError, match="not the config's ids"):
        build(data, SCHOOLS, {**IDS, "000001": "2900009"}, UNMAPPED, SHARES)


def test_counts_per_year_and_kind_and_the_date_spans_come_from_the_cells() -> None:
    dated = [
        row("000001", date(2016, 8, 15), "W"),
        row("000001", date(2017, 5, 19), "W"),
        row("000001", date(2017, 6, 20), "M", "7"),
        row("000002", date(2025, 1, 6), "A"),
    ]
    calendar = read_calendar(workbook(dated))
    assert calendar.cells == {("2017", "W"): 2, ("2017", "M"): 1, ("2025", "A"): 1}
    assert calendar.spans["2017", "W"] == (date(2016, 8, 15), date(2017, 5, 19))
    assert calendar.spans["2017", "M"] == (date(2017, 6, 20), date(2017, 6, 20))
    assert calendar.names == 2  # codes counted, names never kept
    assert not any("DISTRICT" in repr(r) or "BUILDING" in repr(r) for r in calendar.dated)


def test_the_counts_file_takes_the_district_row_else_each_columns_largest_building() -> None:
    yearly = [
        yearly_row("1", "2021", "0001", "6", "1", "0", "2", "0"),
        yearly_row("1", "2021", "0002", "3", "4", "0", "0", "1"),
        yearly_row("2", "2021", "0001", "9", "0", "0", "0", "0"),
        yearly_row("2", "2021", "", "-100", "0", "5", "1", "1"),
        yearly_row("3", "2021", "", "1", "0", "0", "0", "0"),
    ]
    built = build(workbook([], yearly), SCHOOLS, IDS, UNMAPPED, SHARES)
    assert built.files[state_records_mo.COUNTS_FILE].decode().splitlines() == [
        state_records_mo.COUNTS_HEADER,
        "2900001,2021,6,4,0,2",
        "2900002,2021,-100,0,5,2",
    ]


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda d: workbook(d, names=("Sheet1", "2020-2024")), "not the pinned sheets"),
        (lambda d: workbook([[*d[0][:10], "Other Day"]]), "no school year or kind"),
        (lambda d: workbook([[*d[0][:9], "13", d[0][10]]]), "outside 0 to 12"),
        (lambda d: workbook([[*d[0][:7], "X", *d[0][8:]]]), "not A or P"),
        (lambda d: workbook([[*d[0][:8], "45000.5", *d[0][9:]]]), "not a whole day"),
        (lambda _d: b"not a zip", "does not read"),
    ],
)
def test_a_file_that_does_not_read_is_refused(change: object, match: str) -> None:
    dated = [row("000001", TUE, "W")]
    with pytest.raises(MoCalendarError, match=match):
        read_calendar(change(dated))  # type: ignore[operator]


def test_a_changed_byte_of_the_received_file_is_refused() -> None:
    mo = state_records.load().states["mo"]
    item = next(f for f in mo.files if f.form == "mo_calendar")
    with pytest.raises(StateRecordError, match="needs a reviewed pin"):
        state_records.checked(item, b"x" * item.bytes)


def test_derive_needs_the_files_and_refuses_a_derived_file_off_its_pin(tmp_path: Path) -> None:
    mo = state_records.load().states["mo"]
    with pytest.raises(StateRecordError, match="only with --files"):
        state_records.derive(mo, None, lambda _url: b"", lambda _line: None)
    with pytest.raises(StateRecordError, match="not the pinned"):
        state_records.check_derived(mo, "mo-days-ed1.csv", b"leaid,date,call,scope\n")
    (tmp_path / "mo").mkdir()
    (tmp_path / "mo" / "mo-days-ed1.csv.gz").write_bytes(b"not gzip")
    with pytest.raises(StateRecordError, match="does not read"):
        state_records.read_derived(mo, "mo-days-ed1.csv", tmp_path)


def test_the_committed_derived_files_hold_their_pinned_rows() -> None:
    mo = state_records.load().states["mo"]
    assert {(d.name, d.rows) for d in mo.derived} == {
        ("mo-days-ed1.csv", 26265),
        ("mo-counts-ed1.csv", 2784),
    }
    days = state_records.read_derived(mo, "mo-days-ed1.csv").decode().splitlines()
    counts = state_records.read_derived(mo, "mo-counts-ed1.csv").decode().splitlines()
    assert days[0] == state_records_mo.DAYS_HEADER
    assert counts[0] == state_records_mo.COUNTS_HEADER
    assert {line.split(",")[0] for line in days[1:]} <= set(mo.ids.values())
    assert {line.split(",")[2] for line in days[1:]} == set("CHSMPNU")
    assert len(mo.ids) == 561
    assert len(mo.unmapped) == 10
    # the gzip is the same every time (no time, no name)
    raw = state_records.DERIVED_ROOT / "mo" / "mo-days-ed1.csv.gz"
    data = gzip.decompress(raw.read_bytes())
    assert state_records.gzipped(data) == raw.read_bytes()
    assert hashlib.sha256(data).hexdigest() == mo.derived[0].sha256
    # LR-6: the provenance names the raw file's own SHA-256
    raw_pin = next(f for f in mo.files if f.form == "mo_calendar").sha256
    assert mo.provenance is not None
    assert raw_pin in mo.provenance.replace(" ", "")


def test_the_record_step_writes_no_missouri_key() -> None:
    mo = state_records.load().states["mo"]
    said: list[str] = []
    assert state_records.past_keys([mo], (), None, lambda _url: b"", said.append) == {}
    assert said == [
        "predict each-school past: mo: writes no record keys; its 2 derived files are built"
        " with --derive"
    ]

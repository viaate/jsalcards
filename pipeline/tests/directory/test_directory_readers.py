"""Parser tests against slices of the real NCES files (see fixtures/README.md)."""

import io
import shutil
import zipfile
from pathlib import Path

import polars as pl
import pytest

from snowlight.sources.nces import readers, xlsx

EDGE_PUBLIC = "EDGE_GEOCODE_PUBLICSCH_2425.zip"
EDGE_LEA = "EDGE_GEOCODE_PUBLICLEA_2425.zip"
EDGE_PRIVATE = "EDGE_GEOCODE_PRIVATESCH_2324.zip"
CCD_DIRECTORY = "ccd_sch_029_2425_w_1a_073025.zip"
CCD_MEMBERSHIP = "ccd_sch_052_2425_l_1a_073025.zip"
CCD_CHARACTERISTICS = "ccd_sch_129_2425_w_1a_073025.zip"
PSS = "pss2324_pu_csv.zip"


def _row(frame: pl.DataFrame, key: str, value: str) -> dict[str, str | None]:
    rows = frame.filter(pl.col(key) == value).to_dicts()
    assert len(rows) == 1
    return rows[0]


def test_edge_public_schools(fixtures_dir: Path) -> None:
    frame = readers.read_edge_public_schools(
        fixtures_dir / EDGE_PUBLIC,
        "EDGE_GEOCODE_PUBLICSCH_2425.TXT",
        "EDGE_GEOCODE_PUBLICSCH_2425.xlsx",
    )
    assert frame.height == 25
    assert frame.width == 23
    assert set(frame.dtypes) == {pl.String}
    albertville = _row(frame, "NCESSCH", "010000500870")
    assert albertville["LAT"] == "34.260200"
    assert albertville["LON"] == "-86.206200"
    assert albertville["CNTY"] == "01095"
    assert albertville["SCHOOLYEAR"] == "2024-2025"  # no stray carriage return
    # A quoted field holding the delimiter, and one with doubled quotes.
    assert _row(frame, "NCESSCH", "180020202661")["NAME"] == (
        "Bethel Park Elementary | pilotED Schools"
    )
    assert _row(frame, "NCESSCH", "280237000462")["STREET"] == '71 F.D. "Buddy" East Parkway'
    bie = _row(frame, "NCESSCH", "590002500172")
    assert (bie["OPSTFIPS"], bie["STFIP"], bie["STATE"]) == ("59", "38", "ND")


def test_edge_leas(fixtures_dir: Path) -> None:
    frame = readers.read_edge_leas(
        fixtures_dir / EDGE_LEA,
        "EDGE_GEOCODE_PUBLICLEA_2425.TXT",
        "EDGE_GEOCODE_PUBLICLEA_2425.xlsx",
    )
    assert frame.height == 24
    assert frame.width == 34
    assert _row(frame, "LEAID", "0100005")["NAME"] == "Albertville City"
    assert _row(frame, "LEAID", "0200001")["STFIP"] == "02"
    assert frame["PCT_RURAL43"].str.contains("\r").sum() == 0


def test_edge_private_schools(fixtures_dir: Path) -> None:
    frame = readers.read_edge_private_schools(
        fixtures_dir / EDGE_PRIVATE, "EDGE_GEOCODE_PRIVATESCH_2324.xlsx"
    )
    assert frame.height == 8
    row = _row(frame, "PPIN", "00073137")
    assert row["NAME"] == "ST TIMOTHY SCHOOL"
    assert row["SCHOOLYEAR"] == "2023-2024"
    assert row["ZIP"] is not None
    assert len(row["ZIP"]) == 5


def test_ccd_directory(fixtures_dir: Path) -> None:
    frame = readers.read_ccd_directory(
        fixtures_dir / CCD_DIRECTORY, "ccd_sch_029_2425_w_1a_073025.csv"
    )
    assert frame.height == 25
    assert frame.width == 65
    closed = _row(frame, "NCESSCH", "010210000806")
    assert (closed["UPDATED_STATUS"], closed["UPDATED_STATUS_TEXT"]) == ("2", "Closed")
    albertville = _row(frame, "NCESSCH", "010000500870")
    assert albertville["WEBSITE"] == "http://www.albertk12.org"
    assert albertville["LSTREET2"] is None  # empty field is null, not ""


def test_ccd_membership_keeps_one_total_per_school(fixtures_dir: Path) -> None:
    frame = readers.read_ccd_membership_totals(
        fixtures_dir / CCD_MEMBERSHIP, "ccd_sch_052_2425_l_1a_073025.csv", "Education Unit Total"
    )
    assert frame["NCESSCH"].n_unique() == frame.height
    assert set(frame["TOTAL_INDICATOR"]) == {"Education Unit Total"}
    assert _row(frame, "NCESSCH", "010000500870")["STUDENT_COUNT"] == "849"
    suppressed = _row(frame, "NCESSCH", "040386003535")
    assert suppressed["DMS_FLAG"] == "Suppressed"


def test_ccd_membership_total_without_adult_education(fixtures_dir: Path) -> None:
    derived = "Derived - Education Unit Total minus Adult Education Count"
    member = "ccd_sch_052_2425_l_1a_073025.csv"
    frame = readers.read_ccd_membership_totals(fixtures_dir / CCD_MEMBERSHIP, member, derived)
    plain = readers.read_ccd_membership_totals(
        fixtures_dir / CCD_MEMBERSHIP, member, "Education Unit Total"
    )
    assert frame["NCESSCH"].n_unique() == frame.height
    assert sorted(frame["NCESSCH"]) == sorted(plain["NCESSCH"])
    assert set(frame["TOTAL_INDICATOR"]) == {derived}
    ballou = _row(frame, "NCESSCH", "110003000207")
    assert (ballou["STUDENT_COUNT"], ballou["DMS_FLAG"]) == ("278", "Derived")
    assert _row(plain, "NCESSCH", "110003000207")["STUDENT_COUNT"] == "433"
    assert _row(frame, "NCESSCH", "040386003535")["DMS_FLAG"] == "Suppressed"


def test_ccd_membership_through_unzip(fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if shutil.which("unzip") is None:
        pytest.skip("Info-ZIP unzip is not installed")
    # Treat Deflate (8) as Deflate64 so the fixture streams through `unzip -p`,
    # the path the real 2.3 GB member takes.
    monkeypatch.setattr(readers, "DEFLATE64", zipfile.ZIP_DEFLATED)
    frame = readers.read_ccd_membership_totals(
        fixtures_dir / CCD_MEMBERSHIP, "ccd_sch_052_2425_l_1a_073025.csv", "Education Unit Total"
    )
    assert _row(frame, "NCESSCH", "010000500871")["STUDENT_COUNT"] == "1244"


def test_unzip_failure_is_reported(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if shutil.which("unzip") is None:
        pytest.skip("Info-ZIP unzip is not installed")
    broken = tmp_path / CCD_MEMBERSHIP
    data = bytearray((fixtures_dir / CCD_MEMBERSHIP).read_bytes())
    data[200] ^= 0xFF  # corrupt the compressed stream; unzip reports it
    broken.write_bytes(bytes(data))
    monkeypatch.setattr(readers, "DEFLATE64", zipfile.ZIP_DEFLATED)
    with pytest.raises(readers.SourceFormatError):
        readers.read_ccd_membership_totals(
            broken, "ccd_sch_052_2425_l_1a_073025.csv", "Education Unit Total"
        )


def test_unzip_missing_is_reported(fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readers, "DEFLATE64", zipfile.ZIP_DEFLATED)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(readers.SourceFormatError, match="install Info-ZIP"):
        readers.read_ccd_membership_totals(
            fixtures_dir / CCD_MEMBERSHIP, "ccd_sch_052_2425_l_1a_073025.csv", "x"
        )


def test_ccd_characteristics(fixtures_dir: Path) -> None:
    frame = readers.read_ccd_characteristics(
        fixtures_dir / CCD_CHARACTERISTICS, "ccd_sch_129_2425_w_1a_073025.csv"
    )
    assert _row(frame, "NCESSCH", "010000602705")["VIRTUAL"] == "FULLVIRTUAL"


def test_pss(fixtures_dir: Path) -> None:
    frame = readers.read_pss(fixtures_dir / PSS, "pss2324_pu.csv", ("LOGR2024", "HIGR2024"))
    assert frame.height == 8
    assert frame.width == 359
    imputed = _row(frame, "PPIN", "00083393")
    assert imputed["F_P305"] == "4"
    with pytest.raises(readers.SourceFormatError, match="LOGR2026"):
        readers.read_pss(fixtures_dir / PSS, "pss2324_pu.csv", ("LOGR2026",))


def test_grep_lines_handles_chunk_edges() -> None:
    # Synthetic stream: the needle straddles a chunk boundary and ends the stream.
    data = b"h\nab NEED x\nzz\nNEED end"
    lines = readers.grep_lines(io.BytesIO(data), b"NEED", chunk_size=5)
    assert lines == [b"ab NEED x\n", b"NEED end\n"]


def test_bad_inputs_raise_format_errors(fixtures_dir: Path, tmp_path: Path) -> None:
    not_zip = tmp_path / "x.zip"
    not_zip.write_bytes(b"<html>not found</html>")
    with pytest.raises(readers.SourceFormatError, match="not a zip"):
        readers.read_member(not_zip, "a.csv")
    with pytest.raises(readers.SourceFormatError, match="not a zip"):
        readers.read_ccd_membership_totals(not_zip, "a.csv", "x")
    with pytest.raises(readers.SourceFormatError, match="no member"):
        readers.read_member(fixtures_dir / PSS, "missing.csv")
    with pytest.raises(readers.SourceFormatError, match="no member"):
        readers.read_ccd_membership_totals(fixtures_dir / PSS, "missing.csv", "x")


def _zip_with(tmp_path: Path, member: str, data: bytes) -> Path:
    path = tmp_path / "synthetic.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, data)
    return path


def test_non_utf8_text_is_refused(tmp_path: Path) -> None:
    path = _zip_with(tmp_path, "a.csv", b"NCESSCH\n\xe9\n")
    with pytest.raises(readers.SourceFormatError, match="not UTF-8"):
        readers.read_ccd_csv(path, "a.csv", ("NCESSCH",))


def test_missing_columns_are_refused(tmp_path: Path) -> None:
    path = _zip_with(tmp_path, "a.csv", b"NCESSCH,NAME\n1,a\n")
    with pytest.raises(readers.SourceFormatError, match="lacks columns"):
        readers.read_ccd_directory(path, "a.csv")


def test_quoted_newline_row_count_is_checked(tmp_path: Path) -> None:
    # A quoted newline is one record for both parsers, so the counts agree.
    path = _zip_with(tmp_path, "a.csv", b'A,B\n"x\ny",1\n2,3\n')
    frame = readers.read_ccd_csv(path, "a.csv", ("A", "B"))
    assert frame["A"].to_list() == ["x\ny", "2"]


def test_pipe_table_width_must_match_header(fixtures_dir: Path, tmp_path: Path) -> None:
    header = readers.read_member(fixtures_dir / EDGE_PUBLIC, "EDGE_GEOCODE_PUBLICSCH_2425.xlsx")
    path = tmp_path / "edge.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("h.xlsx", header)
        archive.writestr("t.TXT", "a|b|c\r\n")
    with pytest.raises(readers.SourceFormatError, match="record 1 has 3 fields, not 23"):
        readers.read_edge_public_schools(path, "t.TXT", "h.xlsx")


def test_private_rows_longer_than_header_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [["PPIN", "NAME"], ["1", "a", "extra"]]
    monkeypatch.setattr(xlsx, "iter_rows", lambda _data: iter(rows))
    path = _zip_with(tmp_path, "p.xlsx", b"synthetic")
    with pytest.raises(readers.SourceFormatError, match="cells"):
        readers.read_edge_private_schools(path, "p.xlsx")
    monkeypatch.setattr(xlsx, "iter_rows", lambda _data: iter([]))
    with pytest.raises(readers.SourceFormatError, match="empty"):
        readers.read_edge_private_schools(path, "p.xlsx")

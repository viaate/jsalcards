"""The matcher's directory: record checks, lookups, and loading the build's parquet files."""

from pathlib import Path

import polars as pl
import pytest

from snowlight.match import Directory, DirectoryError, DirectoryRecord, load_directory


def _district(record_id: str = "SYN-D1", **fields: object) -> DirectoryRecord:
    values: dict[str, object] = {
        "id": record_id,
        "name": "Tollgate SD",
        "kind": "district",
        "district_id": None,
        "state": "PA",
        "county_fips": "80101",
        "city": "Tollgate",
        "lat": 40.0,
        "lon": -76.0,
    }
    values.update(fields)
    return DirectoryRecord(**values)  # type: ignore[arg-type]


def _school(record_id: str = "SYN-S1", **fields: object) -> DirectoryRecord:
    return _district(
        record_id, **{"name": "Tollgate HS", "kind": "school", "district_id": "SYN-D1", **fields}
    )


def test_lookups() -> None:
    directory = Directory([_district(), _school(), _school("SYN-S2", name="Tollgate MS")])
    assert len(directory) == 3
    assert [r.id for r in directory] == ["SYN-D1", "SYN-S1", "SYN-S2"]
    assert "SYN-S1" in directory
    assert "SYN-S9" not in directory
    assert directory["SYN-S1"].name == "Tollgate HS"
    assert directory.get("SYN-S9") is None
    assert [r.id for r in directory.schools_of("SYN-D1")] == ["SYN-S1", "SYN-S2"]
    assert directory.schools_of("SYN-S1") == ()
    assert [r.id for r in directory.expand("SYN-D1")] == ["SYN-S1", "SYN-S2"]
    assert directory.expand(directory["SYN-S2"]) == (directory["SYN-S2"],)
    assert directory["SYN-S1"].point == (40.0, -76.0)
    assert _school(lat=None, lon=None).point is None


def test_a_district_may_name_itself() -> None:
    assert len(Directory([_district(district_id="SYN-D1")])) == 1


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([_district(), _district()], "appears twice"),
        ([_school()], "not listed"),
        ([_district(), _school(district_id="SYN-S0"), _school("SYN-S0")], "not listed"),
        ([_district(" SYN-D1")], "padded id"),
        ([_district("")], "padded id"),
        ([_district(name=" ")], "empty name"),
        ([_district(kind="campus")], "kind"),
        ([_district(state="Penn")], "state"),
        ([_district(county_fips="801")], "county FIPS"),
        ([_district(county=" ")], "empty county name"),
        ([_district(lat=None)], "only one of lat and lon"),
        ([_district(lat=91.0)], "coordinates"),
        ([_district(lon=-181.0)], "coordinates"),
        ([_district(district_id="SYN-D2")], "district_id"),
        ([_district(grade_low="KG", grade_high="05")], "grades or a level on a district"),
        ([_district(level="Elementary")], "grades or a level on a district"),
        ([_district(), _school(grade_low="K", grade_high="05")], "grade 'K'"),
        ([_district(), _school(grade_low="KG")], "only one of grade_low and grade_high"),
        ([_district(), _school(grade_low="09", grade_high="05")], "grades '09' to '05'"),
        ([_district(), _school(level=" ")], "empty level"),
    ],
)
def test_bad_records_are_refused(records: list[DirectoryRecord], message: str) -> None:
    with pytest.raises(DirectoryError, match=message):
        Directory(records)


def test_a_school_s_grades_and_level() -> None:
    """A school's NCES grades are its span; failing them, its level says one."""
    assert _school(grade_low="PK", grade_high="08", level="Elementary").span == (-1, 8)
    assert _school(grade_low="TK", grade_high="T1").span == (0, 1)
    assert _school(level="High").span == (9, 12)
    assert _school(grade_low="UG", grade_high="UG", level="Middle").span == (6, 8)
    assert _school(grade_low="UG", grade_high="UG", level="Other").span is None
    assert _school().span is None
    assert _district().span is None
    # Ungraded is a code the directory knows, with no grade.
    assert len(Directory([_district(), _school(grade_low="UG", grade_high="12")])) == 2


def test_load_directory_reads_the_build_output(tmp_path: Path) -> None:
    # SYNTHETIC rows in the column layout snowlight.directory writes.
    pl.DataFrame(
        {
            "index": [0, 1],
            "district_id": ["SYN-D1", "SYN-D2"],
            "name": ["Tollgate SD", "Quarry Hill SD"],
            "state": ["PA", "PA"],
            "state_fips": ["42", "42"],
            "county_fips": ["80101", "80102"],
            "county_name": ["Harwick County", ""],
            "city": ["Tollgate", "Quarry Hill"],
            "locale": ["41", "42"],
            "lat": [40.0, 40.5],
            "lon": [-76.0, -76.5],
            "school_count": [2, 0],
            "lea_geocoded": [True, True],
        }
    ).write_parquet(tmp_path / "districts.parquet")
    pl.DataFrame(
        {
            "id": ["SYN-S1", "SYN-S2", "SYN-P1"],
            "kind": ["public", "public", "private"],
            "name": ["Tollgate HS", "Tollgate MS", "St. Rita School"],
            "district_id": ["SYN-D1", "SYN-D1", None],
            "state": ["PA", "PA", "PA"],
            "county_fips": ["80101", "80101", "80102"],
            "city": ["Tollgate", "Tollgate", "Quarry Hill"],
            "lat": [40.01, 40.02, 40.5],
            "lon": [-76.01, -76.02, -76.5],
            "enrollment": [500, 400, 90],
            "grade_low": ["09", "XX", "PK"],
            "grade_high": ["12", "08", "KG"],
            "level": ["High", "Middle", " "],
        }
    ).write_parquet(tmp_path / "schools.parquet")
    directory = load_directory(tmp_path)
    assert [(r.id, r.kind) for r in directory] == [
        ("SYN-D1", "district"),
        ("SYN-D2", "district"),
        ("SYN-S1", "school"),
        ("SYN-S2", "school"),
        ("SYN-P1", "school"),
    ]
    assert [r.id for r in directory.expand("SYN-D1")] == ["SYN-S1", "SYN-S2"]
    private = directory["SYN-P1"]
    assert private.district_id is None
    assert private.point == (40.5, -76.5)
    assert directory["SYN-D2"].city == "Quarry Hill"
    # The districts file names counties (an empty name is none); this schools
    # file has no county names at all.
    assert directory["SYN-D1"].county == "Harwick County"
    assert directory["SYN-D2"].county is None
    assert directory["SYN-S1"].county is None
    # Grades and levels: a code the directory does not know leaves both grades
    # unknown, and an empty level is none.
    high = directory["SYN-S1"]
    assert (high.grade_low, high.grade_high, high.level, high.span) == ("09", "12", "High", (9, 12))
    middle = directory["SYN-S2"]
    assert (middle.grade_low, middle.grade_high, middle.level) == (None, None, "Middle")
    assert middle.span == (6, 8)
    assert (private.grade_low, private.grade_high, private.level) == ("PK", "KG", None)
    assert directory["SYN-D1"].level is None
    # A folder given as a string reads the same.
    assert list(load_directory(str(tmp_path))) == list(directory)


def test_load_directory_reads_a_build_without_grades(tmp_path: Path) -> None:
    """An older build's schools file has no grades or levels: they read as unknown."""
    pl.DataFrame(
        {
            "district_id": ["SYN-D1"],
            "name": ["Tollgate SD"],
            "state": ["PA"],
            "county_fips": ["80101"],
            "city": ["Tollgate"],
            "lat": [40.0],
            "lon": [-76.0],
        }
    ).write_parquet(tmp_path / "districts.parquet")
    pl.DataFrame(
        {
            "id": ["SYN-S1", "SYN-S2"],
            "name": ["Tollgate HS", "Tollgate MS"],
            "district_id": ["SYN-D1", "SYN-D1"],
            "state": ["PA", "PA"],
            "county_fips": ["80101", "80101"],
            "city": ["Tollgate", "Tollgate"],
            "lat": [40.01, 40.02],
            "lon": [-76.01, -76.02],
            "grade_low": ["12", "06"],
            "grade_high": ["09", "08"],
        }
    ).write_parquet(tmp_path / "schools.parquet")
    directory = load_directory(tmp_path)
    # A lowest grade above the highest is no span; the file names no levels.
    assert (directory["SYN-S1"].grade_low, directory["SYN-S1"].span) == (None, None)
    assert directory["SYN-S2"].span == (6, 8)
    assert directory["SYN-S2"].level is None
    assert directory["SYN-D1"].county is None

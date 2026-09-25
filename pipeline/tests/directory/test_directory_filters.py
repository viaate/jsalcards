"""Filter and assembly tests.

The main tests run the real fixture rows through the filters and check each
school's outcome against the reason recorded for it in PROVENANCE.json. Small
synthetic frames, built in the tests, cover the expression edge cases.
"""

from pathlib import Path
from typing import Any

import polars as pl
import pytest

from snowlight.directory import filters
from snowlight.directory.assemble import (
    PrivateSources,
    PublicSources,
    assemble_districts,
    assemble_private,
    assemble_public,
    coordinate_e6,
    degrees,
    finer_than_e6,
    more_than_six_decimals,
    require_unique,
)
from snowlight.directory.config import DirectoryConfig
from snowlight.directory.filters import Reason
from snowlight.sources.nces import readers
from snowlight.sources.nces.readers import SourceFormatError

EXPECTED_PUBLIC: dict[str, str | None] = {
    "010000500870": None,
    "010000500871": None,
    "010019702432": None,
    "010000602705": None,
    "040386003535": None,
    "010000600986": None,
    "590002500172": None,
    "180020202661": None,
    "280237000462": None,
    "120008410898": None,
    "050040801686": None,
    "010020902504": None,
    "110003000207": None,
    "010000600876": Reason.PREK_ONLY,
    "010000902231": Reason.GRADES_NOT_REPORTED,
    "010020402727": Reason.STATUS_FUTURE,
    "010210000806": Reason.STATUS_CLOSED,
    "040000101203": Reason.STATUS_INACTIVE,
    "050042005157": Reason.ADULT_ONLY,
    "250000102401": Reason.NO_K12_GRADE,
    "100023000378": Reason.UNGRADED_ONLY,
    "230264000057": Reason.NO_GRADES,
    "020000100206": Reason.OUTSIDE_CONTINENTAL_US,
    "150003000001": Reason.OUTSIDE_CONTINENTAL_US,
    "720003000004": Reason.OUTSIDE_CONTINENTAL_US,
}
EXPECTED_PRIVATE: dict[str, str | None] = {
    "00000033": None,
    "00000044": None,
    "00073137": None,
    "00083393": None,
    "00089781": Reason.UNGRADED_ONLY,
    "00538514": Reason.PREK_ONLY,
    "00023629": Reason.OUTSIDE_CONTINENTAL_US,
    "00326554": Reason.OUTSIDE_CONTINENTAL_US,
}


@pytest.fixture(scope="module")
def public_sources(fixtures_dir: Path, fixture_config: DirectoryConfig) -> PublicSources:
    return PublicSources(
        directory=readers.read_ccd_directory(
            fixtures_dir / "ccd_sch_029_2425_w_1a_073025.zip", "ccd_sch_029_2425_w_1a_073025.csv"
        ),
        geocodes=readers.read_edge_public_schools(
            fixtures_dir / "EDGE_GEOCODE_PUBLICSCH_2425.zip",
            "EDGE_GEOCODE_PUBLICSCH_2425.TXT",
            "EDGE_GEOCODE_PUBLICSCH_2425.xlsx",
        ),
        membership=readers.read_ccd_membership_totals(
            fixtures_dir / "ccd_sch_052_2425_l_1a_073025.zip",
            "ccd_sch_052_2425_l_1a_073025.csv",
            fixture_config.enrollment.ccd_total_indicator,
        ),
        characteristics=readers.read_ccd_characteristics(
            fixtures_dir / "ccd_sch_129_2425_w_1a_073025.zip", "ccd_sch_129_2425_w_1a_073025.csv"
        ),
    )


@pytest.fixture(scope="module")
def private_sources(fixtures_dir: Path) -> PrivateSources:
    return PrivateSources(
        geocodes=readers.read_edge_private_schools(
            fixtures_dir / "EDGE_GEOCODE_PRIVATESCH_2324.zip", "EDGE_GEOCODE_PRIVATESCH_2324.xlsx"
        ),
        pss=readers.read_pss(
            fixtures_dir / "pss2324_pu_csv.zip", "pss2324_pu.csv", ("LOGR2024", "HIGR2024")
        ),
        low_grade_column="LOGR2024",
        high_grade_column="HIGR2024",
    )


@pytest.fixture(scope="module")
def public(public_sources: PublicSources, fixture_config: DirectoryConfig) -> pl.DataFrame:
    return assemble_public(public_sources, fixture_config)


@pytest.fixture(scope="module")
def private(private_sources: PrivateSources, fixture_config: DirectoryConfig) -> pl.DataFrame:
    return assemble_private(private_sources, fixture_config)


def _by_id(frame: pl.DataFrame) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in frame.to_dicts()}


def test_expectations_match_the_fixture_manifest(provenance: dict[str, Any]) -> None:
    assert set(EXPECTED_PUBLIC) == set(provenance["public_school_ids"])
    assert set(EXPECTED_PRIVATE) == set(provenance["private_school_ids"])
    for school, note in provenance["public_school_ids"].items():
        assert note.startswith("kept") == (EXPECTED_PUBLIC[school] is None)


def test_public_filters_give_each_real_row_its_reason(public: pl.DataFrame) -> None:
    outcome = dict(zip(public["id"], public["drop_reason"], strict=True))
    assert outcome == EXPECTED_PUBLIC


def test_private_filters_give_each_real_row_its_reason(private: pl.DataFrame) -> None:
    outcome = dict(zip(private["id"], private["drop_reason"], strict=True))
    assert outcome == EXPECTED_PRIVATE


def test_public_fields_come_straight_from_the_sources(public: pl.DataFrame) -> None:
    rows = _by_id(public)
    school = rows["010000500870"]
    assert school["name"] == "Albertville Middle School"
    assert (school["district_id"], school["district_name"]) == ("0100005", "Albertville City")
    assert (school["city"], school["state"], school["zip"]) == ("Albertville", "AL", "35950")
    assert (school["county_fips"], school["county_name"]) == ("01095", "Marshall County")
    assert (school["lat_e6"], school["lon_e6"]) == (34_260_200, -86_206_200)
    assert (school["lat"], school["lon"]) == (34.2602, -86.2062)
    assert (school["grade_low"], school["grade_high"]) == ("07", "08")
    assert school["grades_offered"] == ["07", "08"]
    assert school["enrollment"] == 849
    assert school["kind_flags"] == 0
    assert school["website"] == "http://www.albertk12.org"
    assert school["school_year"] == "2024-2025"
    assert rows["010019702432"]["charter"] is True
    assert rows["010019702432"]["kind_flags"] == 0x02
    assert rows["010000602705"]["virtual"] == "FULLVIRTUAL"
    assert rows["010000602705"]["kind_flags"] & 0x04
    bie = rows["590002500172"]
    assert (bie["state"], bie["state_fips"]) == ("ND", "38")


def test_enrollment_leaves_out_adult_education(public: pl.DataFrame) -> None:
    # The CCD 052 rows for Ballou STAY HS: "Education Unit Total" 433 (Reported)
    # and "Derived - Education Unit Total minus Adult Education Count" 278
    # (Derived). Its adult education students are not K-12 enrollment.
    rows = _by_id(public)
    ballou = rows["110003000207"]
    assert (ballou["name"], ballou["state"], ballou["state_fips"]) == ("Ballou STAY HS", "DC", "11")
    assert (ballou["enrollment"], ballou["enrollment_flag"]) == (278, "Derived")
    # A school without adult education students: both rows give the same count.
    assert (rows["010000500870"]["enrollment"], rows["010000500870"]["enrollment_flag"]) == (
        849,
        "Derived",
    )


def test_enrollment_is_left_empty_unless_reported(public: pl.DataFrame) -> None:
    rows = _by_id(public)
    assert rows["040386003535"]["enrollment"] is None
    assert rows["040386003535"]["enrollment_flag"] == "Suppressed"
    assert rows["010000600986"]["enrollment"] is None
    assert rows["010000600986"]["enrollment_flag"] == "Missing"


def test_private_fields_and_unimputed_enrollment(private: pl.DataFrame) -> None:
    rows = _by_id(private)
    school = rows["00000033"]
    assert school["kind"] == "private"
    assert school["kind_flags"] == 0x01
    assert school["name"] == "ST JAMES CATHOLIC SCHOOL"
    assert (school["lat_e6"], school["lon_e6"]) == (34_023_810, -85_989_151)
    assert (school["grade_low"], school["grade_high"]) == ("PK", "08")
    assert school["level"] == "Elementary"
    assert school["enrollment"] == 144
    assert school["district_id"] is None
    assert rows["00073137"]["grade_low"] == "TK"
    assert rows["00083393"]["enrollment_flag"] == "4"
    assert rows["00083393"]["enrollment"] is None


def test_districts_reconcile_with_the_lea_file(
    public: pl.DataFrame, fixtures_dir: Path, fixture_config: DirectoryConfig
) -> None:
    leas = readers.read_edge_leas(
        fixtures_dir / "EDGE_GEOCODE_PUBLICLEA_2425.zip",
        "EDGE_GEOCODE_PUBLICLEA_2425.TXT",
        "EDGE_GEOCODE_PUBLICLEA_2425.xlsx",
    )
    kept = public.filter(pl.col("drop_reason").is_null())
    districts, lea_rows = assemble_districts(kept, leas, fixture_config)
    assert districts["district_id"].to_list() == sorted(kept["district_id"].unique())
    assert districts["index"].to_list() == list(range(districts.height))
    albertville = districts.filter(pl.col("district_id") == "0100005").to_dicts()[0]
    assert albertville["school_count"] == 2
    assert albertville["name"] == "Albertville City"
    reasons = dict(zip(lea_rows["district_id"], lea_rows["drop_reason"], strict=True))
    assert reasons["0100005"] is None
    assert reasons["0200001"] == Reason.OUTSIDE_CONTINENTAL_US
    assert reasons["5000021"] == Reason.NO_SCHOOL_ON_MAP
    assert reasons["0102100"] == Reason.NO_SCHOOL_ON_MAP  # its only school closed
    assert lea_rows.filter(pl.col("drop_reason").is_null()).height == districts.height


def test_district_with_two_names_is_refused(
    public: pl.DataFrame, fixtures_dir: Path, fixture_config: DirectoryConfig
) -> None:
    leas = readers.read_edge_leas(
        fixtures_dir / "EDGE_GEOCODE_PUBLICLEA_2425.zip",
        "EDGE_GEOCODE_PUBLICLEA_2425.TXT",
        "EDGE_GEOCODE_PUBLICLEA_2425.xlsx",
    )
    kept = public.filter(pl.col("drop_reason").is_null())
    clash = kept.with_columns(
        district_name=pl.when(pl.col("id") == "010000500871")
        .then(pl.lit("Another name"))
        .otherwise(pl.col("district_name"))
    )
    with pytest.raises(SourceFormatError, match="two names"):
        assemble_districts(clash, leas, fixture_config)


def test_require_unique() -> None:
    frame = pl.DataFrame({"k": ["a", "a"]})
    with pytest.raises(SourceFormatError, match="repeated"):
        require_unique(frame, "k", "synthetic")
    with pytest.raises(SourceFormatError, match="no k"):
        require_unique(pl.DataFrame({"k": ["a", None]}), "k", "synthetic")


def test_coordinate_parsing_edge_cases() -> None:
    # Synthetic coordinate texts.
    frame = pl.DataFrame(
        {"v": ["34.260200", "-86.206200", "91", "abc", None, "NaN", "34.2602001", "1e1"]}
    )
    out = frame.select(e6=coordinate_e6("v", 90.0), fine=finer_than_e6("v"))
    assert out["e6"].to_list() == [
        34_260_200,
        -86_206_200,
        None,
        None,
        None,
        None,
        34_260_200,
        10_000_000,
    ]
    assert out["fine"].to_list() == [False, False, False, False, False, False, True, False]


def test_float_noise_is_long_but_not_finer_than_e6(private_sources: PrivateSources) -> None:
    # Real workbook values: St James Catholic School (PPIN 00000033) is published
    # as 34.023810000000005, -85.989151000000007; the float noise is dropped.
    geocodes = private_sources.geocodes.filter(pl.col("PPIN") == "00000033")
    out = geocodes.select(
        long=more_than_six_decimals("LAT") & more_than_six_decimals("LON"),
        fine=finer_than_e6("LAT") | finer_than_e6("LON"),
        lat_e6=coordinate_e6("LAT", 90.0),
        lon_e6=coordinate_e6("LON", 180.0),
    )
    assert out.row(0) == (True, False, 34_023_810, -85_989_151)
    texts = pl.DataFrame({"v": ["34.260200", "34.2602001", "-118.142025", None, "1e1"]})
    assert texts.select(more_than_six_decimals("v"))["v"].to_list() == [
        False,
        True,
        False,
        False,
        False,
    ]


def test_degrees_matches_exact_division() -> None:
    values = [0, 1, -1, 33_173_709, -86_206_200, 179_999_999, -180_000_000]
    frame = pl.DataFrame({"v": values}, schema={"v": pl.Int32}).select(d=degrees("v"))
    assert frame["d"].to_list() == [v / 1_000_000 for v in values]


def test_status_check_names_each_status() -> None:
    frame = pl.DataFrame({"s": ["1", "2", "3", "4", "5", "6", "7", "8", "9", None]})
    got = frame.select(r=filters.status_check("s", ["1", "3", "4", "5", "8"]))["r"].to_list()
    assert got == [
        None,
        Reason.STATUS_CLOSED,
        None,
        None,
        None,
        Reason.STATUS_INACTIVE,
        Reason.STATUS_FUTURE,
        None,
        Reason.STATUS_NOT_OPERATIONAL,
        Reason.STATUS_NOT_OPERATIONAL,
    ]


def test_pss_grade_check_codes() -> None:
    frame = pl.DataFrame({"h": ["1", "2", "3", "4", "17", "18", None, "x"]})
    got = frame.select(r=filters.pss_grades_check("h"))["r"].to_list()
    assert got == [
        Reason.UNGRADED_ONLY,
        Reason.PREK_ONLY,
        None,
        None,
        None,
        Reason.GRADES_NOT_REPORTED,
        Reason.GRADES_NOT_REPORTED,
        Reason.GRADES_NOT_REPORTED,
    ]


def test_bounds_check(fixture_config: DirectoryConfig) -> None:
    frame = pl.DataFrame({"lat": [40_000_000, 60_000_000], "lon": [-100_000_000, -100_000_000]})
    got = frame.select(r=filters.bounds_check("lat", "lon", fixture_config.filters.bounds))
    assert got["r"].to_list() == [None, Reason.COORDINATES_OUTSIDE_BOUNDS]


def test_every_reason_is_described() -> None:
    assert set(filters.REASON_DESCRIPTIONS) == set(Reason)
    assert filters.PSS_GRADE_LABELS["6"] == "01"
    assert filters.PSS_GRADE_LABELS["17"] == "12"

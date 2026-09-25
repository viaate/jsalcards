"""Join the NCES tables into one row per school and decide which rows are kept.

:func:`assemble_public` starts from the CCD school directory (one row per NCES
school id) and :func:`assemble_private` from the EDGE private school geocode file
(one row per PSS PPIN). Both return every source row, in the shared
:data:`SCHOOL_SCHEMA`, with a ``drop_reason`` that is ``null`` for kept rows.
Nothing is inferred: a value missing from the sources stays ``null``.

Where each field comes from:

========================  =====================================  ==================================
field                     public school                          private school
========================  =====================================  ==================================
id                        CCD NCESSCH (12 digits)                PSS PPIN (8 characters)
name                      CCD SCH_NAME                           EDGE NAME (identical to PSS PINST)
district_id, _name        CCD LEAID, LEA_NAME                    null
street, city, zip         CCD LSTREET1, LCITY, LZIP              EDGE STREET, CITY, ZIP
state, state_fips         EDGE STATE, STFIP                      EDGE STATE, STFIP
county_fips, _name        EDGE CNTY, NMCNTY                      EDGE CNTY, NMCNTY
locale                    EDGE LOCALE                            EDGE LOCALE
lat, lon                  EDGE LAT, LON                          EDGE LAT, LON
grade_low, grade_high     CCD GSLO, GSHI                         PSS LOGR/HIGR, codebook labels
grades_offered            CCD G_*_OFFERED = Yes                  null
level                     CCD LEVEL                              PSS LEVEL, codebook label
school_type               CCD SCH_TYPE_TEXT                      null
charter                   CCD CHARTER_TEXT (Yes/No)              null
virtual                   CCD 129 VIRTUAL                        null
status                    CCD UPDATED_STATUS_TEXT                null
enrollment                CCD 052 total less adult ed, see (1)   PSS P305, if not imputed
phone, website            CCD PHONE, WEBSITE                     PSS PPHONE, null
school_year               CCD SCHOOL_YEAR                        EDGE SCHOOLYEAR
========================  =====================================  ==================================

(1) The membership row named by ``enrollment.ccd_total_indicator`` in the config
("Derived - Education Unit Total minus Adult Education Count"), used only when its
``DMS_FLAG`` is ``enrollment.ccd_accepted_flag`` ("Derived"); ``enrollment_flag``
holds that ``DMS_FLAG``.

Names come from CCD rather than EDGE for public schools because the EDGE text
garbles some non-ASCII letters (``"Para Los NiEos"`` for CCD ``"Para Los Ninos"``).
"""

from dataclasses import dataclass

import polars as pl

from snowlight.directory import filters
from snowlight.directory.config import DirectoryConfig
from snowlight.sources.nces.readers import SourceFormatError

KIND_PRIVATE = 0x01
KIND_CHARTER = 0x02
KIND_VIRTUAL = 0x04

SCHOOL_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.String(),
    "kind": pl.String(),
    "kind_flags": pl.UInt8(),
    "name": pl.String(),
    "district_id": pl.String(),
    "district_name": pl.String(),
    "street": pl.String(),
    "city": pl.String(),
    "state": pl.String(),
    "zip": pl.String(),
    "state_fips": pl.String(),
    "county_fips": pl.String(),
    "county_name": pl.String(),
    "locale": pl.String(),
    "lat": pl.Float64(),
    "lon": pl.Float64(),
    "lat_e6": pl.Int32(),
    "lon_e6": pl.Int32(),
    "grade_low": pl.String(),
    "grade_high": pl.String(),
    "grades_offered": pl.List(pl.String()),
    "level": pl.String(),
    "school_type": pl.String(),
    "charter": pl.Boolean(),
    "virtual": pl.String(),
    "status": pl.String(),
    "enrollment": pl.Int32(),
    "enrollment_flag": pl.String(),
    "phone": pl.String(),
    "website": pl.String(),
    "school_year": pl.String(),
    "drop_reason": pl.String(),
}

# CCD grade-offered flags in grade order, with the label GSLO/GSHI use for each.
CCD_GRADE_FLAGS: tuple[tuple[str, str], ...] = (
    ("G_PK_OFFERED", "PK"),
    ("G_KG_OFFERED", "KG"),
    *((f"G_{grade}_OFFERED", f"{grade:02d}") for grade in range(1, 14)),
    ("G_UG_OFFERED", "UG"),
    ("G_AE_OFFERED", "AE"),
)

_E6 = 1_000_000
# Per-row facts for the build report, returned beside SCHOOL_SCHEMA and not stored:
# coordinates_long: the published LAT or LON text has more than six decimals;
# coordinates_rounded: rounding to six decimals moved it by more than float noise;
# geocoded: the school has an EDGE geocode row.
_AUDIT_COLUMNS = ("coordinates_long", "coordinates_rounded", "geocoded")
_ROUNDING_TOLERANCE_E6 = 1e-3  # float noise, far below the sixth decimal


@dataclass(frozen=True, slots=True)
class PublicSources:
    """The parsed NCES tables a public school row is built from."""

    directory: pl.DataFrame
    geocodes: pl.DataFrame
    membership: pl.DataFrame
    characteristics: pl.DataFrame


@dataclass(frozen=True, slots=True)
class PrivateSources:
    """The parsed NCES tables a private school row is built from."""

    geocodes: pl.DataFrame
    pss: pl.DataFrame
    low_grade_column: str
    high_grade_column: str


def require_unique(frame: pl.DataFrame, key: str, what: str) -> pl.DataFrame:
    """Return ``frame`` if ``key`` is present and unique in every row.

    Raises:
        SourceFormatError: on a null or repeated key, which would make a join
            duplicate or lose schools.
    """
    if frame[key].null_count():
        raise SourceFormatError(f"{what}: {frame[key].null_count()} rows have no {key}")
    duplicates = frame.height - frame[key].n_unique()
    if duplicates:
        raise SourceFormatError(f"{what}: {duplicates} repeated {key} values")
    return frame


def coordinate_e6(column: str, limit: float) -> pl.Expr:
    """Parse a published coordinate into integer millionths of a degree.

    Text that is not a finite number within ``±limit`` degrees becomes ``null``.
    """
    value = pl.col(column).cast(pl.Float64, strict=False)
    valid = value.is_finite() & (value.abs() <= limit)
    return pl.when(valid).then((value * _E6).round(0).cast(pl.Int32)).otherwise(None)


def degrees(e6_column: str) -> pl.Expr:
    """Turn integer millionths of a degree into the float nearest the exact decimal.

    The integer is written out as its decimal text (``-86206200`` becomes
    ``"-86.206200"``) and parsed, because a float division such as
    ``33173709 / 1e6`` can land one unit in the last place away (33.173708999999995).
    """
    value = pl.col(e6_column)
    magnitude = value.abs()
    text = pl.concat_str(
        [
            pl.when(value < 0).then(pl.lit("-")).otherwise(pl.lit("")),
            (magnitude // _E6).cast(pl.String),
            pl.lit("."),
            (magnitude % _E6).cast(pl.String).str.zfill(6),
        ]
    )
    return text.cast(pl.Float64)


def more_than_six_decimals(column: str) -> pl.Expr:
    """True where the published coordinate text has more than six decimal digits.

    The private school workbook stores some coordinates as binary floats, whose
    text carries noise such as ``34.023810000000004``; :func:`finer_than_e6`
    tells that noise apart from real extra precision.
    """
    return pl.col(column).str.contains(r"\.\d{7,}").fill_null(value=False)


def finer_than_e6(column: str) -> pl.Expr:
    """True where a published coordinate has digits beyond the sixth decimal.

    Digits that only express floating-point noise (under a thousandth of a
    millionth of a degree) do not count.
    """
    scaled = pl.col(column).cast(pl.Float64, strict=False) * _E6
    beyond = (scaled - scaled.round(0)).abs() > _ROUNDING_TOLERANCE_E6
    return (scaled.is_finite() & beyond).fill_null(value=False)


def _with_coordinates(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        lat_e6=coordinate_e6("LAT", 90.0),
        lon_e6=coordinate_e6("LON", 180.0),
        coordinates_rounded=finer_than_e6("LAT") | finer_than_e6("LON"),
        coordinates_long=more_than_six_decimals("LAT") | more_than_six_decimals("LON"),
    ).with_columns(
        lat=degrees("lat_e6"),
        lon=degrees("lon_e6"),
    )


def _count(column: str, what: str, frame: pl.DataFrame) -> pl.Series:
    """Parse a whole-number count column, refusing anything but plain digits."""
    series = frame[column]
    bad = series.drop_nulls().filter(~series.drop_nulls().str.contains(r"^\d+$"))
    if bad.len():
        raise SourceFormatError(f"{what}: non-integer {column} values such as {bad[0]!r}")
    return series.cast(pl.Int32)


def _checks(config: DirectoryConfig, state_fips_column: str) -> list[pl.Expr]:
    """The geographic checks, on the joined source columns."""
    rules = config.filters
    return [
        filters.coordinates_check("lat_e6", "lon_e6"),
        filters.state_check(state_fips_column, rules.state_fips),
        filters.bounds_check("lat_e6", "lon_e6", rules.bounds),
    ]


def assemble_public(sources: PublicSources, config: DirectoryConfig) -> pl.DataFrame:
    """Return one row per CCD directory record, with its drop reason."""
    directory = require_unique(sources.directory, "NCESSCH", "CCD directory")
    geocodes = require_unique(sources.geocodes, "NCESSCH", "EDGE public geocodes")
    membership = require_unique(sources.membership, "NCESSCH", "CCD membership totals")
    characteristics = require_unique(sources.characteristics, "NCESSCH", "CCD characteristics")
    enrollment = config.enrollment

    membership = membership.select(
        "NCESSCH",
        pl.Series("STUDENT_COUNT", _count("STUDENT_COUNT", "CCD membership", membership)),
        "DMS_FLAG",
    )
    edge = geocodes.select(
        "NCESSCH",
        "LAT",
        "LON",
        pl.col("STATE").alias("EDGE_STATE"),
        pl.col("STFIP").alias("EDGE_STFIP"),
        pl.col("CNTY").alias("EDGE_CNTY"),
        pl.col("NMCNTY").alias("EDGE_NMCNTY"),
        pl.col("LOCALE").alias("EDGE_LOCALE"),
        pl.lit(value=True).alias("geocoded"),
    )
    joined = (
        directory.join(edge, on="NCESSCH", how="left")
        .join(membership, on="NCESSCH", how="left")
        .join(characteristics.select("NCESSCH", "VIRTUAL"), on="NCESSCH", how="left")
    )
    joined = _with_coordinates(joined)

    accepted = pl.col("DMS_FLAG") == enrollment.ccd_accepted_flag
    charter = pl.col("CHARTER_TEXT")
    grades = pl.concat_list(
        [pl.when(pl.col(flag) == "Yes").then(pl.lit(label)) for flag, label in CCD_GRADE_FLAGS]
    ).list.drop_nulls()
    # Distinct bits, so adding them sets each flag independently.
    kind_flags = pl.when(charter == "Yes").then(KIND_CHARTER).otherwise(0) + pl.when(
        pl.col("VIRTUAL") == "FULLVIRTUAL"
    ).then(KIND_VIRTUAL).otherwise(0)
    schools = joined.select(
        id=pl.col("NCESSCH"),
        kind=pl.lit("public"),
        kind_flags=kind_flags.cast(pl.UInt8),
        name=pl.col("SCH_NAME"),
        district_id=pl.col("LEAID"),
        district_name=pl.col("LEA_NAME"),
        street=pl.col("LSTREET1"),
        city=pl.col("LCITY"),
        state=pl.coalesce("EDGE_STATE", "LSTATE"),
        zip=pl.col("LZIP"),
        state_fips=pl.col("EDGE_STFIP"),
        county_fips=pl.col("EDGE_CNTY"),
        county_name=pl.col("EDGE_NMCNTY"),
        locale=pl.col("EDGE_LOCALE"),
        lat=pl.col("lat"),
        lon=pl.col("lon"),
        lat_e6=pl.col("lat_e6"),
        lon_e6=pl.col("lon_e6"),
        grade_low=pl.col("GSLO"),
        grade_high=pl.col("GSHI"),
        grades_offered=grades,
        level=pl.col("LEVEL"),
        school_type=pl.col("SCH_TYPE_TEXT"),
        charter=pl.when(charter == "Yes")
        .then(pl.lit(value=True))
        .when(charter == "No")
        .then(pl.lit(value=False)),
        virtual=pl.col("VIRTUAL"),
        status=pl.col("UPDATED_STATUS_TEXT"),
        enrollment=pl.when(accepted).then(pl.col("STUDENT_COUNT")),
        enrollment_flag=pl.col("DMS_FLAG"),
        phone=pl.col("PHONE"),
        website=pl.col("WEBSITE"),
        school_year=pl.col("SCHOOL_YEAR"),
        drop_reason=filters.first_reason(
            [
                *_checks(config, "EDGE_STFIP"),
                filters.status_check("UPDATED_STATUS", config.filters.operational_status_codes),
                filters.ccd_grades_check(config.filters.k12_grade_flags),
            ]
        ),
        coordinates_rounded=pl.col("coordinates_rounded"),
        coordinates_long=pl.col("coordinates_long"),
        geocoded=pl.col("geocoded").fill_null(value=False),
    )
    return schools.select(*SCHOOL_SCHEMA, *_AUDIT_COLUMNS).cast(
        SCHOOL_SCHEMA  # type: ignore[arg-type]
    )


def assemble_private(sources: PrivateSources, config: DirectoryConfig) -> pl.DataFrame:
    """Return one row per EDGE private school geocode record, with its drop reason."""
    geocodes = require_unique(sources.geocodes, "PPIN", "EDGE private geocodes")
    pss = require_unique(sources.pss, "PPIN", "PSS public-use file")
    enrollment = config.enrollment
    low, high = sources.low_grade_column, sources.high_grade_column

    survey = pss.select(
        "PPIN",
        pl.col(low).alias("PSS_LOW"),
        pl.col(high).alias("PSS_HIGH"),
        pl.col("LEVEL").alias("PSS_LEVEL"),
        pl.Series("P305", _count("P305", "PSS", pss)),
        "F_P305",
        "PPHONE",
    )
    joined = _with_coordinates(geocodes.join(survey, on="PPIN", how="left"))
    unimputed = pl.col("F_P305") == enrollment.pss_unimputed_flag
    schools = joined.select(
        id=pl.col("PPIN"),
        kind=pl.lit("private"),
        kind_flags=pl.lit(KIND_PRIVATE, pl.UInt8),
        name=pl.col("NAME"),
        district_id=pl.lit(None, pl.String),
        district_name=pl.lit(None, pl.String),
        street=pl.col("STREET"),
        city=pl.col("CITY"),
        state=pl.col("STATE"),
        zip=pl.col("ZIP"),
        state_fips=pl.col("STFIP"),
        county_fips=pl.col("CNTY"),
        county_name=pl.col("NMCNTY"),
        locale=pl.col("LOCALE"),
        lat=pl.col("lat"),
        lon=pl.col("lon"),
        lat_e6=pl.col("lat_e6"),
        lon_e6=pl.col("lon_e6"),
        grade_low=pl.col("PSS_LOW").replace_strict(
            filters.PSS_GRADE_LABELS, default=None, return_dtype=pl.String
        ),
        grade_high=pl.col("PSS_HIGH").replace_strict(
            filters.PSS_GRADE_LABELS, default=None, return_dtype=pl.String
        ),
        grades_offered=pl.lit(None, pl.List(pl.String)),
        level=pl.col("PSS_LEVEL").replace_strict(
            filters.PSS_LEVEL_LABELS, default=None, return_dtype=pl.String
        ),
        school_type=pl.lit(None, pl.String),
        charter=pl.lit(None, pl.Boolean),
        virtual=pl.lit(None, pl.String),
        status=pl.lit(None, pl.String),
        enrollment=pl.when(unimputed).then(pl.col("P305")),
        enrollment_flag=pl.col("F_P305"),
        phone=pl.col("PPHONE"),
        website=pl.lit(None, pl.String),
        school_year=pl.col("SCHOOLYEAR"),
        drop_reason=filters.first_reason(
            [*_checks(config, "STFIP"), filters.pss_grades_check("PSS_HIGH")]
        ),
        coordinates_rounded=pl.col("coordinates_rounded"),
        coordinates_long=pl.col("coordinates_long"),
        geocoded=pl.lit(value=True),
    )
    return schools.select(*SCHOOL_SCHEMA, *_AUDIT_COLUMNS).cast(
        SCHOOL_SCHEMA  # type: ignore[arg-type]
    )


DISTRICT_SCHEMA: dict[str, pl.DataType] = {
    "index": pl.UInt32(),
    "district_id": pl.String(),
    "name": pl.String(),
    "state": pl.String(),
    "state_fips": pl.String(),
    "county_fips": pl.String(),
    "county_name": pl.String(),
    "city": pl.String(),
    "locale": pl.String(),
    "lat": pl.Float64(),
    "lon": pl.Float64(),
    "school_count": pl.UInt32(),
    "lea_geocoded": pl.Boolean(),
}


def assemble_districts(
    kept_public: pl.DataFrame, leas: pl.DataFrame, config: DirectoryConfig
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build the district list and reconcile it against the EDGE LEA file.

    Returns ``(districts, lea_rows)``. ``districts`` holds one row per district
    with at least one kept school, sorted by id; ``index`` is its position, which
    ``points.bin`` stores for each school. Its name is CCD ``LEA_NAME``; its
    location fields come from the EDGE LEA geocode when the LEA is in that file.
    ``lea_rows`` is every EDGE LEA row with a ``drop_reason`` (``null`` when the
    district is on the map).

    Raises:
        SourceFormatError: if one district id carries two different CCD names.
    """
    leas = require_unique(leas, "LEAID", "EDGE LEA geocodes")
    named = kept_public.select("district_id", "district_name").unique()
    clashes = named.height - named["district_id"].n_unique()
    if clashes:
        raise SourceFormatError(f"CCD directory: {clashes} district ids have two names")
    counts = kept_public.group_by("district_id").agg(school_count=pl.len())
    lea = leas.select(
        pl.col("LEAID").alias("district_id"),
        pl.col("STATE").alias("state"),
        pl.col("STFIP").alias("state_fips"),
        pl.col("CNTY").alias("county_fips"),
        pl.col("NMCNTY").alias("county_name"),
        pl.col("CITY").alias("city"),
        pl.col("LOCALE").alias("locale"),
        coordinate_e6("LAT", 90.0).alias("lat_e6"),
        coordinate_e6("LON", 180.0).alias("lon_e6"),
        pl.lit(value=True).alias("lea_geocoded"),
    )
    districts = (
        named.join(counts, on="district_id")
        .join(lea, on="district_id", how="left")
        .sort("district_id")
        .with_row_index("index")
        .select(
            "index",
            "district_id",
            pl.col("district_name").alias("name"),
            "state",
            "state_fips",
            "county_fips",
            "county_name",
            "city",
            "locale",
            degrees("lat_e6").alias("lat"),
            degrees("lon_e6").alias("lon"),
            "school_count",
            pl.col("lea_geocoded").fill_null(value=False),
        )
        .cast(DISTRICT_SCHEMA)  # type: ignore[arg-type]
    )
    on_map = districts.select("district_id", pl.lit(value=True).alias("on_map"))
    lea_rows = (
        leas.select(
            pl.col("LEAID").alias("district_id"),
            pl.col("NAME").alias("name"),
            pl.col("STATE").alias("state"),
            pl.col("STFIP").alias("state_fips"),
        )
        .join(on_map, on="district_id", how="left")
        .with_columns(
            drop_reason=pl.when(pl.col("on_map").fill_null(value=False))
            .then(None)
            .when(pl.col("state_fips").is_in(config.filters.state_fips).not_())
            .then(pl.lit(filters.Reason.OUTSIDE_CONTINENTAL_US.value))
            .otherwise(pl.lit(filters.Reason.NO_SCHOOL_ON_MAP.value))
        )
        .drop("on_map")
    )
    return districts, lea_rows

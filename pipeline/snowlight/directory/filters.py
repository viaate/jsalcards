"""Why a source row does or does not become a school on the map.

Each filter is a polars expression that evaluates to a drop reason (a string)
or ``null`` when the row passes. :func:`first_reason` applies them in order, so
every dropped row carries exactly one reason: the first filter it fails. The
build report counts rows per reason, which is how every dropped row is
explained and how kept + dropped is reconciled against the source row counts.

Order: coordinates, then geography, then operational status, then grades.
"""

from collections.abc import Sequence
from enum import StrEnum

import polars as pl

from snowlight.directory.config import Bounds


class Reason(StrEnum):
    """Every reason a row can be dropped."""

    NO_COORDINATES = "no_coordinates"
    OUTSIDE_CONTINENTAL_US = "outside_continental_us"
    COORDINATES_OUTSIDE_BOUNDS = "coordinates_outside_continental_bounds"
    STATUS_CLOSED = "status_closed"
    STATUS_INACTIVE = "status_inactive"
    STATUS_FUTURE = "status_future"
    STATUS_NOT_OPERATIONAL = "status_not_operational"
    PREK_ONLY = "grades_prek_only"
    ADULT_ONLY = "grades_adult_education_only"
    UNGRADED_ONLY = "grades_ungraded_only"
    NO_GRADES = "grades_none_offered"
    GRADES_NOT_REPORTED = "grades_not_reported"
    NO_K12_GRADE = "grades_no_k12_grade"
    NO_SCHOOL_ON_MAP = "no_school_on_map"


REASON_DESCRIPTIONS: dict[Reason, str] = {
    Reason.NO_COORDINATES: "No usable latitude and longitude in the geocode file.",
    Reason.OUTSIDE_CONTINENTAL_US: (
        "Geocoded state FIPS is not one of the 48 contiguous states or DC "
        "(Alaska, Hawaii, territories)."
    ),
    Reason.COORDINATES_OUTSIDE_BOUNDS: (
        "Geocode falls outside the continental US bounding box configured in directory.yaml."
    ),
    Reason.STATUS_CLOSED: "CCD updated status 2 (Closed).",
    Reason.STATUS_INACTIVE: "CCD updated status 6 (Inactive: temporarily closed).",
    Reason.STATUS_FUTURE: "CCD updated status 7 (Future: not yet open).",
    Reason.STATUS_NOT_OPERATIONAL: "CCD updated status code not listed as operational.",
    Reason.PREK_ONLY: "Offers prekindergarten and no grade from K to 12.",
    Reason.ADULT_ONLY: "Offers adult education and no grade from K to 12.",
    Reason.UNGRADED_ONLY: "Offers only ungraded instruction, no grade from K to 12.",
    Reason.NO_GRADES: "Reports that it offers no grades (CCD NOGRADES = Yes).",
    Reason.GRADES_NOT_REPORTED: "Grades offered were not reported, so K-12 cannot be confirmed.",
    Reason.NO_K12_GRADE: "Offers no grade from K to 12 (other combination of grades).",
    Reason.NO_SCHOOL_ON_MAP: "District has no school that passed the filters.",
}

# CCD UPDATED_STATUS codes with a specific reason; any other non-kept code maps to
# STATUS_NOT_OPERATIONAL.
_STATUS_REASONS = {
    "2": Reason.STATUS_CLOSED,
    "6": Reason.STATUS_INACTIVE,
    "7": Reason.STATUS_FUTURE,
}

# CCD grade-offered flags that are not K-12, and the grade each names.
_NON_K12_FLAGS = {
    "G_PK_OFFERED": "PK",
    "G_13_OFFERED": "13",
    "G_UG_OFFERED": "UG",
    "G_AE_OFFERED": "AE",
}

# PSS grade-span recode (2023-24 codebook, LOGR2024/HIGR2024): 1 all ungraded,
# 2 prekindergarten, 3 kindergarten, 4 transitional kindergarten, 5 transitional
# first grade, 6..17 grades 1..12.
PSS_ALL_UNGRADED = 1
PSS_PREKINDERGARTEN = 2
PSS_KINDERGARTEN = 3
PSS_GRADE_12 = 17
PSS_GRADE_LABELS: dict[str, str] = {
    "1": "UG",
    "2": "PK",
    "3": "KG",
    "4": "TK",
    "5": "T1",
    **{str(code): f"{code - 5:02d}" for code in range(6, 18)},
}
# PSS LEVEL (2023-24 codebook).
PSS_LEVEL_LABELS: dict[str, str] = {
    "1": "Elementary",
    "2": "Secondary",
    "3": "Combined elementary and secondary",
}


def first_reason(checks: Sequence[pl.Expr]) -> pl.Expr:
    """Return the first non-null reason among ``checks`` (``null`` if all pass)."""
    return pl.coalesce(list(checks))


def coordinates_check(lat_e6: str, lon_e6: str) -> pl.Expr:
    """Drop rows whose coordinate columns are null."""
    return (
        pl.when(pl.col(lat_e6).is_null() | pl.col(lon_e6).is_null())
        .then(pl.lit(Reason.NO_COORDINATES.value))
        .otherwise(None)
    )


def state_check(state_fips: str, allowed: Sequence[str]) -> pl.Expr:
    """Drop rows whose geocoded state FIPS is not in ``allowed``."""
    return (
        pl.when(pl.col(state_fips).is_in(list(allowed)).fill_null(value=False).not_())
        .then(pl.lit(Reason.OUTSIDE_CONTINENTAL_US.value))
        .otherwise(None)
    )


def bounds_check(lat_e6: str, lon_e6: str, bounds: Bounds) -> pl.Expr:
    """Drop rows whose coordinates fall outside ``bounds``."""
    lat, lon = pl.col(lat_e6), pl.col(lon_e6)
    inside = (
        (lon >= round(bounds.west * 1_000_000))
        & (lon <= round(bounds.east * 1_000_000))
        & (lat >= round(bounds.south * 1_000_000))
        & (lat <= round(bounds.north * 1_000_000))
    )
    return (
        pl.when(inside.not_()).then(pl.lit(Reason.COORDINATES_OUTSIDE_BOUNDS.value)).otherwise(None)
    )


def status_check(status_code: str, operational: Sequence[str]) -> pl.Expr:
    """Drop public schools whose CCD updated status is not operational."""
    column = pl.col(status_code)
    reason = pl.lit(Reason.STATUS_NOT_OPERATIONAL.value)
    for code, specific in _STATUS_REASONS.items():
        reason = pl.when(column == code).then(pl.lit(specific.value)).otherwise(reason)
    kept = column.is_in(list(operational)).fill_null(value=False)
    return pl.when(kept).then(None).otherwise(reason)


def ccd_grades_check(k12_flags: Sequence[str]) -> pl.Expr:
    """Drop public schools that offer no grade from K to 12, naming what they do offer."""
    offers = {flag: pl.col(flag) == "Yes" for flag in (*k12_flags, *_NON_K12_FLAGS)}
    any_k12 = pl.any_horizontal([offers[f] for f in k12_flags]).fill_null(value=False)
    grade_flags = [*k12_flags, *_NON_K12_FLAGS]
    all_not_reported = pl.all_horizontal([pl.col(f) == "Not reported" for f in grade_flags])
    only = {
        grade: pl.all_horizontal(
            [offers[f] if f == flag else offers[f].not_() for f in _NON_K12_FLAGS]
        )
        for flag, grade in _NON_K12_FLAGS.items()
    }
    return (
        pl.when(any_k12)
        .then(None)
        .when(all_not_reported.fill_null(value=True))
        .then(pl.lit(Reason.GRADES_NOT_REPORTED.value))
        .when(pl.col("NOGRADES") == "Yes")
        .then(pl.lit(Reason.NO_GRADES.value))
        .when(only["PK"])
        .then(pl.lit(Reason.PREK_ONLY.value))
        .when(only["AE"])
        .then(pl.lit(Reason.ADULT_ONLY.value))
        .when(only["UG"])
        .then(pl.lit(Reason.UNGRADED_ONLY.value))
        .otherwise(pl.lit(Reason.NO_K12_GRADE.value))
    )


def pss_grades_check(high_grade: str) -> pl.Expr:
    """Drop private schools whose highest grade (PSS recode) is below kindergarten.

    Codes 3 to 17 (kindergarten through grade 12) keep the school; 2 means the
    highest grade is prekindergarten, 1 means all ungraded. A missing or unknown
    code means the grades are not known.
    """
    code = pl.col(high_grade).cast(pl.Int32, strict=False)
    return (
        pl.when(code.is_between(PSS_KINDERGARTEN, PSS_GRADE_12))
        .then(None)
        .when(code == PSS_PREKINDERGARTEN)
        .then(pl.lit(Reason.PREK_ONLY.value))
        .when(code == PSS_ALL_UNGRADED)
        .then(pl.lit(Reason.UNGRADED_ONLY.value))
        .otherwise(pl.lit(Reason.GRADES_NOT_REPORTED.value))
    )

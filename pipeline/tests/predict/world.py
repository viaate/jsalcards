"""A small synthetic world for the predict tests: districts, schools, a model, alerts.

Every name, place and number here is made up for the tests; nothing comes from a
real list or a real storm.
"""

import json
from datetime import UTC, date, datetime
from typing import Any, Final

import numpy as np
import shapely

from snowlight.directory.points import NO_DISTRICT, Points, decode, encode
from snowlight.predict.artifact import (
    SITUATION_KEYS,
    DistrictModel,
    ModelArtifact,
    RecordDay,
    Settings,
    Training,
)
from snowlight.predict.config import PredictConfig
from snowlight.predict.pool import LEVELS
from snowlight.predict.serve import DeployedDirectory
from snowlight.predict.situations import GROUPS
from snowlight.schemas.directory import DirectoryStamp
from snowlight.schemas.live import DayTimeline
from snowlight.schemas.vocab import Reason, Status

CONFIG = PredictConfig.load()

# One district in Kansas, three in one county of Missouri, one far away in Utah.
DISTRICTS = ("2000004", "2900001", "2900002", "2900003", "4900005")
# Each school: (lon, lat, district position or None, kind flags).
SCHOOLS: tuple[tuple[float, float, int | None, int], ...] = (
    (-94.58, 39.10, 1, 0),
    (-94.57, 39.11, 1, 0),
    (-94.50, 39.12, 2, 0),
    (-94.49, 39.13, 2, 2),  # a charter of district 2
    (-94.40, 39.05, 3, 0),
    (-94.68, 38.95, 0, 0),
    (-111.89, 40.76, 4, 0),
    (-94.59, 39.09, None, 1),  # a private school
    (-94.60, 39.08, None, 1),  # a private school next to it
    (-111.90, 40.75, None, 1),  # a private school in Utah
    (-149.90, 61.20, None, 1),  # a private school in Alaska: outside the contiguous states
)
FIRST_PRIVATE: Final = 7
PRIVATE_IDS: Final = ("A0000007", "A0000008", "A0000009", "A0000010")
"""The private schools' made-up NCES ids (schools 7 to 10)."""
STAMP = DirectoryStamp(generated_on=date(2026, 10, 14), schools=len(SCHOOLS), districts=5)
ZONES = {
    "2900001": "America/Chicago",
    "2900002": "America/Chicago",
    "2900003": "America/Chicago",
    "2000004": "America/Chicago",
    "4900005": "America/Denver",
}


def points() -> Points:
    """The schools as ``points.bin`` holds them."""
    return decode(points_bytes())


def points_bytes() -> bytes:
    """The schools as ``points.bin`` bytes."""
    return encode(
        [round(lon * 1e6) for lon, _lat, _d, _k in SCHOOLS],
        [round(lat * 1e6) for _lon, lat, _d, _k in SCHOOLS],
        [NO_DISTRICT if d is None else d for _lon, _lat, d, _k in SCHOOLS],
        [k for _lon, _lat, _d, k in SCHOOLS],
        len(DISTRICTS),
    )


def meta_bytes() -> bytes:
    """A ``meta.json`` for the schools (written the way the directory build writes it)."""
    value = {
        "schema_version": 1,
        "generated_on": STAMP.generated_on.isoformat(),
        "count": len(SCHOOLS),
        "ids": school_ids(),
        "names": [f"School {i}" for i in range(1, len(SCHOOLS) + 1)],
        "districts": {"ids": list(DISTRICTS), "names": [f"District {i}" for i in range(5)]},
        "school_years": {"private": "2023-2024", "public": "2024-2025"},
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def school_ids() -> list[str]:
    """Every school's id: the public ones' (12 digits), then the private ones'."""
    return [f"{i:012d}" for i in range(1, FIRST_PRIVATE + 1)] + list(PRIVATE_IDS)


def directory() -> DeployedDirectory:
    """The deployed directory."""
    return DeployedDirectory(STAMP, DISTRICTS, points(), school_ids=tuple(school_ids()))


def counts(n_none: int = 0, y_none: int = 0, n_snow: int = 0, y_snow: int = 0) -> dict[str, Any]:
    """Counts with ``none`` and ``snow_warning`` days (delays: none)."""
    n = [0] * len(SITUATION_KEYS)
    y = [0] * len(SITUATION_KEYS)
    n[SITUATION_KEYS.index("none")], y[SITUATION_KEYS.index("none")] = n_none, y_none
    n[SITUATION_KEYS.index("snow_warning")] = n_snow
    y[SITUATION_KEYS.index("snow_warning")] = y_snow
    nd = [a - b for a, b in zip(n, y, strict=True)]
    return {"y": tuple(y), "n": tuple(n), "yd": (0,) * len(n), "nd": tuple(nd)}


SETTINGS: Final = Settings(
    own_min_days=4,
    level_min_days=8,
    nation_min_days=8,
    almost_share=0.05,
    fallback={
        "lake_snow": "snow_warning",
        "blizzard": "snow_warning",
        "ice": "snow_warning",
        "cold": "snow_warning",
        "tropical": "snow_warning",
        "advisory_after": "advisory",
        "none_after": "none",
        "advisory": "snow_warning",
    },
    floor=0.01,
    ceiling=0.99,
)
"""The model settings of the synthetic world (the shipped rules, smaller minimums)."""


def private_models(*, with_counts: bool = True) -> dict[str, DistrictModel]:
    """The private schools' places and counts: the first Kansas City private school has its
    own snow record, its neighbor a short one; Utah's and Alaska's none."""
    found: dict[str, DistrictModel] = {}
    places = (("MO", "29095", "America/Chicago"), ("MO", "29095", "America/Chicago"),
              ("UT", "49035", "America/Denver"), ("AK", "02020", "America/Anchorage"))  # fmt: skip
    for i, (school, (state, county, zone)) in enumerate(zip(PRIVATE_IDS, places, strict=True)):
        extra: dict[str, Any] = {}
        if with_counts and i == 0:
            extra = counts(n_none=12, y_none=0, n_snow=6, y_snow=6)
            extra["record"] = {
                "snow_warning": (
                    RecordDay(day=date(2024, 1, 9), did="closed"),
                    RecordDay(day=date(2025, 1, 6), did="closed"),
                )
            }
        elif with_counts and i == 1:
            extra = counts(n_none=4, y_none=0, n_snow=3, y_snow=2)
        found[school] = DistrictModel(state=state, county=county, time_zone=zone, **extra)
    return found


def model(*, with_counts: bool = True, private: bool = True) -> ModelArtifact:
    """A model: district 1 has an own snow record, district 2 a short one, the others none;
    the private schools as :func:`private_models` (none with ``private`` false)."""
    strengths: dict[str, dict[str, float]] = {level: dict.fromkeys(GROUPS, 4.0) for level in LEVELS}
    districts: dict[str, DistrictModel] = {}
    for i, leaid in enumerate(DISTRICTS):
        state = "UT" if leaid.startswith("49") else ("KS" if leaid.startswith("20") else "MO")
        extra: dict[str, Any] = {}
        if with_counts and i == 1:
            extra = counts(n_none=40, y_none=0, n_snow=10, y_snow=6)
            extra["record"] = {
                "snow_warning": (
                    RecordDay(day=date(2024, 1, 9), did="closed"),
                    RecordDay(day=date(2025, 1, 6), did="remote"),
                    RecordDay(day=date(2025, 2, 18), did="open"),
                )
            }
        elif with_counts and i == 2:
            extra = counts(n_none=30, y_none=0, n_snow=6, y_snow=2)
        districts[leaid] = DistrictModel(
            state=state, county="29095" if state == "MO" else None, time_zone=ZONES[leaid], **extra
        )
    return ModelArtifact(
        schema_version=2,
        situations=SITUATION_KEYS,
        training=Training(
            seasons=(2023, 2024), labeled_days=86, directory_generated_on=date(2026, 9, 25)
        ),
        settings=SETTINGS,
        strengths={"no_school": strengths, "delay": strengths},
        districts=districts,
        private=private_models(with_counts=with_counts) if private else {},
        private_strengths={"no_school": strengths, "delay": strengths} if private else {},
        private_labeled_days=25 if private and with_counts else 0,
    )


def feature(  # noqa: PLR0913 - one alert's fields
    vtec: str,
    ugcs: tuple[str, ...],
    *,
    sent: str,
    onset: str | None,
    ends: str | None,
    event: str = "Winter Storm Warning",
    message_type: str = "Alert",
    status: str = "Actual",
) -> dict[str, Any]:
    """One CAP alert as the NWS active feed gives it."""
    return {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "id": f"urn:test:{vtec}",
            "event": event,
            "status": status,
            "messageType": message_type,
            "severity": "Moderate",
            "sent": sent,
            "effective": sent,
            "onset": onset,
            "expires": ends,
            "ends": ends,
            "affectedZones": [],
            "geocode": {"UGC": list(ugcs)},
            "parameters": {"VTEC": [vtec]},
        },
    }


def feed_bytes(features: list[dict[str, Any]], updated: str) -> bytes:
    """An active-alerts response."""
    return json.dumps(
        {"type": "FeatureCollection", "updated": updated, "features": features}
    ).encode()


def utc(text: str) -> datetime:
    """``2026-01-07T12:00`` as an aware UTC time."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def ugc_areas() -> dict[str, shapely.Geometry]:
    """Two zones (a box over the Missouri and Kansas schools, one over Utah)."""
    return {
        "MOZ028": shapely.box(-94.65, 39.0, -94.3, 39.2),
        "KSZ104": shapely.box(-94.9, 38.8, -94.65, 39.0),
        "UTZ105": shapely.box(-112.2, 40.5, -111.5, 41.0),
    }


def lon_lat() -> tuple[np.ndarray, np.ndarray]:
    """The schools' longitudes and latitudes, in degrees, as points.bin rounds them."""
    found = points()
    return found.lon_e6.astype(np.float64) * 1e-6, found.lat_e6.astype(np.float64) * 1e-6


def timeline(stamp: DirectoryStamp = STAMP) -> DayTimeline:
    """SYNTHETIC: schools 0 and 1 (district 1) closed and remote for snow, school 4 closed with
    no reason named."""
    return DayTimeline(
        schema_version=1,
        day=date(2026, 1, 6),
        generated_at=utc("2026-01-07T05:00:00"),
        directory=stamp,
        content_sha256=None,
        final=True,
        gaps=(0, 0, 2),
        counts=(1, 1, 1),
        minutes=(-120, -100, 300),
        statuses=(Status.CLOSED, Status.REMOTE, Status.CLOSED),
        reasons=(Reason.WINTER_STORM, Reason.WINTER_STORM, None),
        shifts=(),
        clocks=(),
    )

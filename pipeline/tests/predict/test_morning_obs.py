"""The label dates' 5 AM airport reports (synthetic answers)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs

import polars as pl
import pytest

from snowlight.predict.morning_obs import (
    ObsError,
    Present,
    Station,
    asos_query,
    cached_get,
    distance_km,
    district_points,
    label_rows,
    morning_report,
    nearest,
    parse_asos,
    parse_network,
    present,
)

DAY = date(2023, 2, 28)
ANSWER = """station,valid,tmpf,wxcodes
EWR,2023-02-28 08:51,34.0,-RASN BR
EWR,2023-02-28 09:51,33.1,-DZ
EWR,2023-02-28 10:51,33.0,FZRA
HPN,2023-02-28 08:56,30.9,-SN
HPN,2023-02-28 09:56,M,M
"""


def test_station_lists_and_the_nearest_station() -> None:
    payload = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "id": "EWR",
                    "properties": {"sid": "EWR"},
                    "geometry": {"type": "Point", "coordinates": [-74.17, 40.69]},
                },
                {
                    "id": "TEB",
                    "properties": {"sid": "TEB"},
                    "geometry": {"type": "Point", "coordinates": [-74.06, 40.85]},
                },
            ],
        }
    ).encode()
    stations = parse_network(payload, "NJ")
    assert [s.sid for s in stations] == ["EWR", "TEB"]
    hit = nearest(stations, 40.73, -74.17)
    assert hit is not None
    assert hit[0].sid == "EWR"
    assert hit[1] == pytest.approx(4.45, abs=0.05)
    assert nearest(stations, 45.0, -100.0) is None
    assert distance_km(0, 0, 0, 1) == pytest.approx(111.19, abs=0.01)
    with pytest.raises(ObsError):
        parse_network(b'{"features": [{}]}', "NJ")


def test_the_request_asks_for_routine_reports_from_06_to_15_utc() -> None:
    query = parse_qs(asos_query(["HPN", "EWR", "EWR"], DAY))
    assert query["station"] == ["EWR", "HPN"]
    assert query["data"] == ["tmpf", "wxcodes"]
    assert (query["hour1"], query["hour2"]) == (["6"], ["15"])
    assert query["tz"] == ["Etc/UTC"]
    assert query["report_type"] == ["3"]


def test_the_report_at_or_before_5_am_local_and_never_after() -> None:
    reports = parse_asos(ANSWER)
    assert reports.height == 5
    # 05:00 EST is 10:00 UTC: the 09:51 report (EWR), never the 10:51 one.
    found = morning_report(reports, "EWR", DAY, "America/New_York")
    assert found is not None
    assert found["valid"] == datetime(2023, 2, 28, 9, 51, tzinfo=UTC)
    assert found["minutes_before"] == 9
    assert found["tmpf"] == pytest.approx(33.1)
    assert found["drizzle"] is True
    # HPN's 09:56 report has no values: it is still the report at 05:00, with nothing in it.
    hpn = morning_report(reports, "HPN", DAY, "America/New_York")
    assert hpn is not None
    assert hpn["tmpf"] is None
    # 05:00 CST is 11:00 UTC: EWR's 10:51 freezing rain.
    chicago = morning_report(reports, "EWR", DAY, "America/Chicago")
    assert chicago is not None
    assert chicago["freezing"] is True
    # Too old: nothing within 90 minutes before 05:00 PST (13:00 UTC).
    assert morning_report(reports, "EWR", DAY, "America/Los_Angeles") is None
    with pytest.raises(ObsError):
        parse_asos("a,b\n1,2\n")
    with pytest.raises(ObsError):
        parse_asos("station,valid,tmpf,wxcodes\nEWR,yesterday,1,M\n")


def test_present_weather_codes() -> None:
    assert present("-RASN BR") == Present(rain=True, snow=True)
    assert present("-RASN BR").mix
    assert present("FZRA") == Present(rain=True, freezing=True)
    assert not present("FZRA").mix
    assert present("+SHSN") == Present(snow=True)
    assert present("PL -SN").mix
    assert present("BLSN") == Present()
    assert present(None) == Present()
    assert present("BR FG") == Present()
    assert present("TSRA").rain


def test_district_points_and_label_rows() -> None:
    schools = pl.DataFrame(
        {
            "district_id": ["d1", "d1", "d1", "d2", None],
            "lat": [40.0, 40.2, 50.0, 41.0, 0.0],
            "lon": [-74.0, -74.2, -80.0, -74.0, 0.0],
            "state": ["NJ", "NJ", "NJ", "NY", "NJ"],
            "kind": ["public"] * 5,
            "kind_flags": [0, 0, 2, 2, 0],  # 2: a charter
        }
    )
    points = district_points(schools)
    first = points.row(0, named=True)
    assert first["district"] == "d1"
    assert first["lat"] == pytest.approx(40.1)  # the charter school is left out
    assert points.row(1, named=True)["lat"] == pytest.approx(41.0)  # d2 has only a charter
    labels = pl.DataFrame(
        {
            "district": ["d1", "d2", "d1"],
            "day": [DAY, DAY, date(2023, 3, 1)],
            "outcome": ["no_school", "unknown", "open"],
        }
    )
    table = pl.DataFrame(
        {"district": ["d1", "d2"], "time_zone": ["America/New_York", "America/New_York"]}
    )
    stations = {
        "NJ": [Station("XYZ", 40.15, -74.1, "NJ")],
        "PA": [Station("FAR", 45.0, -80.0, "PA")],
    }
    rows = label_rows(labels, table, points, stations)
    assert rows["station"].to_list() == ["XYZ", "XYZ"]
    assert rows["day"].to_list() == [DAY, date(2023, 3, 1)]


def test_a_cached_answer_is_never_asked_again(tmp_path: Path) -> None:
    asked: list[str] = []
    pauses: list[int] = []

    def get(url: str) -> bytes:
        asked.append(url)
        return b"body"

    path = tmp_path / "a" / "b.csv"
    assert cached_get("u", path, get, lambda: pauses.append(1)) == (b"body", True)
    assert cached_get("u", path, get, lambda: pauses.append(1)) == (b"body", False)
    assert asked == ["u"]
    assert pauses == [1]

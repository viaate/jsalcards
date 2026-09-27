"""Storm-based polygons (FF.W) read from IEM's school-year shapefiles.

Real slices: the polygon rows of the fixtures' FF.W events (``iem-polygons-*.zip``)
and BOI's FF.W 1 of 2017, whose event ``ISSUED`` is blank.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from snowlight.sources.nws.shapefile import ShapeRecord, read_zip
from snowlight.weather.hazards import CONUS_STATES
from snowlight.weights import polygons
from snowlight.weights.cache import WeightsCache

if TYPE_CHECKING:
    from weights.conftest import Kit


def test_polygon_request() -> None:
    url = polygons.polygon_url(2024)
    assert url.startswith("https://mesonet.agron.iastate.edu/cgi-bin/request/gis/watchwarn.py?")
    assert "sts=2024-08-01T00:00Z&ets=2025-06-17T00:00Z" in url
    assert "phenomena=FF&significance=W" in url
    assert "simple=1&addsvs=1" in url
    assert f"states={','.join(sorted(CONUS_STATES))}" in url
    assert polygons.polygon_path(Path("c"), 2024) == Path(
        "c/mesonet.agron.iastate.edu/watchwarn-polygons/2024-2025.zip"
    )


def test_read_polygon_file(kit: "Kit") -> None:
    rows, stats = polygons.read_polygon_file(kit.path("iem-polygons-2024-2025.zip"))
    assert stats.polygon_rows == len(rows) == 22
    assert stats.county_rows == 0
    assert stats.events["BOX.FF.W.0015.2024"] == 1
    assert stats.events["TAE.FF.W.0103.2024"] == 4  # four versions of one warning's polygon
    first = next(row for row in rows if row.event_key == "BOX.FF.W.0015.2024")
    assert first.code == "FF.W"
    assert first.product_id.startswith("202408152118-KBOX-")
    assert first.product_issued == datetime(2024, 8, 15, 21, 18, tzinfo=UTC)
    assert (first.begin, first.end) == (
        datetime(2024, 8, 15, 21, 18, tzinfo=UTC),
        datetime(2024, 8, 15, 23, 6, tzinfo=UTC),
    )
    assert first.geometry.area > 0


def test_blank_event_times_fall_back_to_the_polygon(kit: "Kit") -> None:
    rows, stats = polygons.read_polygon_file(kit.path("iem-polygons-2016-2017-blank.zip"))
    assert stats.without_event_times == 2
    assert stats.ended_before_start == 1  # the expiry statement's polygon, drawn after the end
    assert {row.event_key for row in rows} == {"BOI.FF.W.0001.2017"}
    assert min(row.begin for row in rows) == datetime(2017, 2, 10, 10, 55, tzinfo=UTC)


def test_malformed_polygon_files(kit: "Kit", monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(polygons.PolygonFileError, match="GTYPE"):
        polygons.read_polygon_file(kit.path("c_16ap26.zip"))
    with pytest.raises(polygons.PolygonFileError):
        polygons.read_polygon_file(kit.path("iem-2019-2020-slc.csv"))
    with pytest.raises(polygons.PolygonFileError, match="was not asked for"):
        polygons.read_polygon_file(kit.path("iem-polygons-2024-2025.zip"), codes={"TO.W"})
    real = read_zip(kit.path("iem-polygons-2024-2025.zip"))[0]

    def serve(record: ShapeRecord) -> None:
        monkeypatch.setattr("snowlight.weights.polygons.read_zip", lambda _path: [record])

    # Synthetic: the first real record with one attribute spoiled at a time.
    serve(ShapeRecord(0, {**real.attributes, "POLY_BEG": "2024-08-15"}, real.geometry))
    with pytest.raises(polygons.PolygonFileError, match="POLY_BEG"):
        polygons.read_polygon_file(Path("x.zip"))
    serve(ShapeRecord(0, {**real.attributes, "ETN": "fifteen"}, real.geometry))
    with pytest.raises(polygons.PolygonFileError, match="ETN"):
        polygons.read_polygon_file(Path("x.zip"))
    serve(ShapeRecord(0, real.attributes, None))
    with pytest.raises(polygons.PolygonFileError, match="no polygon"):
        polygons.read_polygon_file(Path("x.zip"))
    serve(ShapeRecord(0, {**real.attributes, "GTYPE": "C", "NWS_UGC": "PRC001"}, None))
    _, stats = polygons.read_polygon_file(Path("x.zip"))
    assert (stats.county_rows, stats.outside_states) == (1, 1)
    serve(ShapeRecord(0, {**real.attributes, "ETN": "15", "VTEC_YR": "2024"}, real.geometry))
    (row,), _ = polygons.read_polygon_file(Path("x.zip"))
    assert row.event_key == "BOX.FF.W.0015.2024"


def test_load_polygons(kit: "Kit", tmp_path: Path) -> None:
    loaded = polygons.load_polygons(kit.cache(), 2024)
    assert loaded.final
    assert loaded.label == "2024-25"
    assert "BOX.FF.W.0015.2024" in loaded.events
    assert len(loaded.rows) == 22
    both = polygons.load_polygon_years(kit.cache(), [2018, 2021])
    assert [item.label for item in both] == ["2018-19", "2021-22"]
    # Fetched three days after the 2024-25 window closed, the file is still provisional.
    kit.now = datetime(2025, 6, 20, tzinfo=UTC)
    fresh = WeightsCache(kit.http(), tmp_path / "fresh", siblings=())
    assert not polygons.load_polygons(fresh, 2024).final

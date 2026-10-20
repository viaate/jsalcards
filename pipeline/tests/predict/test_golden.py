"""The contract golden file: ``golden/synthetic_predictions.json``, written by the serving
pass from the SYNTHETIC world and a SYNTHETIC winter storm warning, and read back by
web/src/data/tests/predictions.contract.test.ts with ``parsePredictions`` and
``forecastDetail``.

Set SNOWLIGHT_WRITE_GOLDEN=1 to write it again after a deliberate change.
"""

import os
from datetime import time
from pathlib import Path

from predict import world
from snowlight.predict.alerts_live import UgcIndex, live_events
from snowlight.predict.serve import build_model, district_classes, forecast_file, pass_days
from snowlight.predict.situations import Window
from snowlight.schemas.predictions import Forecast, NoThreat, PredictionsFile
from snowlight.sources.nws.alerts import parse_active

GOLDEN = Path(__file__).parent / "golden" / "synthetic_predictions.json"
NOW = world.utc("2026-01-07T02:00:00")  # 8 PM in Chicago on a Tuesday


def golden_file() -> PredictionsFile:
    """Two passes over a SYNTHETIC storm: the second carries the first as ``previous``."""
    model = build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)
    lon, lat = world.lon_lat()
    index = UgcIndex.build(lon, lat, world.ugc_areas())
    window = Window(time(18), time(9), 21)
    days = pass_days(NOW, world.CONFIG)
    calm = district_classes(model, [], index, days, NOW, window, 0.5)
    first = forecast_file(model, calm, days, NOW, closed_on=lambda _day: None, last=None)
    feed = parse_active(
        world.feed_bytes(
            [
                world.feature(
                    "/O.NEW.KEAX.WS.W.0004.260107T0600Z-260108T0000Z/",
                    ("MOZ028",),
                    sent="2026-01-07T02:10:00+00:00",
                    onset="2026-01-07T06:00:00+00:00",
                    ends="2026-01-08T00:00:00+00:00",
                )
            ],
            "2026-01-07T02:12:00+00:00",
        )
    )
    later = world.utc("2026-01-07T02:15:00")
    storm = district_classes(model, live_events(feed), index, days, later, window, 0.5)
    return forecast_file(model, storm, days, later, closed_on=lambda _day: None, last=first)


def test_the_golden_file_is_what_the_pass_writes() -> None:
    data = golden_file().to_json_bytes()
    if os.environ.get("SNOWLIGHT_WRITE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes(data)
    assert GOLDEN.read_bytes() == data


def test_the_golden_file_holds_what_the_web_test_reads() -> None:
    found = PredictionsFile.from_json_bytes(GOLDEN.read_bytes())
    assert [day.isoformat() for day in found.days] == ["2026-01-06", "2026-01-07"]
    kinds = {type(day).__name__ for entry in found.districts for day in entry.days}
    assert kinds == {"Forecast"}
    under = found.districts[1].days[1]
    assert isinstance(under, Forecast)
    assert under.previous is not None
    assert under.record is not None
    assert under.p_no_school > 0.3
    clear = found.districts[0].days[1]
    assert isinstance(clear, Forecast)
    assert clear.reasons == ()
    assert clear.p_no_school == 0.01
    assert not any(isinstance(day, NoThreat) for entry in found.districts for day in entry.days)

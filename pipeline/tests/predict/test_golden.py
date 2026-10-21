"""The contract golden file: ``golden/synthetic_predictions.json``, written by the serving
pass from the SYNTHETIC world and a SYNTHETIC winter storm warning, and read back by
web/src/data/tests/predictions.contract.test.ts with ``parsePredictions`` and
``forecastDetail``.

Set SNOWLIGHT_WRITE_GOLDEN=1 to write it again after a deliberate change.
"""

import json
import os
from datetime import time
from pathlib import Path

from predict import world
from snowlight.predict.alerts_live import UgcIndex, live_events
from snowlight.predict.opens import SaidOpen
from snowlight.predict.serve import build_model, forecast_file, pass_days, unit_classes
from snowlight.predict.situations import Window
from snowlight.schemas.predictions import Forecast, NoThreat, PredictionsFile
from snowlight.sources.nws.alerts import parse_active

GOLDEN = Path(__file__).parent / "golden" / "synthetic_predictions.json"
NOW = world.utc("2026-01-07T02:00:00")  # 8 PM in Chicago on a Tuesday


def golden_file() -> PredictionsFile:
    """Two passes over a SYNTHETIC storm: the second carries the first as ``previous``; the
    private schools get their own chances, and one SYNTHETIC private school said school is on
    for the second day."""
    model = build_model(world.directory(), world.model(), world.CONFIG, lambda _lon, _lat: None)
    lon, lat = world.lon_lat()
    index = UgcIndex.build(lon, lat, world.ugc_areas())
    window = Window(time(18), time(9), 21)
    days = pass_days(NOW, world.CONFIG)
    calm, calm_private = unit_classes(model, [], index, days, NOW, window, 0.5)
    first = forecast_file(
        model, calm, days, NOW, closed_on=lambda _day: None, last=None, private_classes=calm_private
    )
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
    storm, storm_private = unit_classes(model, live_events(feed), index, days, later, window, 0.5)
    return forecast_file(
        model,
        storm,
        days,
        later,
        closed_on=lambda _day: None,
        last=first,
        private_classes=storm_private,
        said=SaidOpen(schools={days[1]: frozenset({8})}),
    )


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
    # The private schools: Kansas City's two under the warning, Utah's clear; none in Alaska.
    assert [entry.school for entry in found.schools] == [7, 8, 9]
    own = found.outlook_of(found.schools[0])[1]
    assert isinstance(own, Forecast)
    assert own.why.base.kind == "alert"
    assert own.record is not None
    assert own.previous is not None
    said = found.outlook_of(found.schools[1])[1]
    assert isinstance(said, Forecast)
    assert (said.p_no_school, said.p_delay) == (0.01, 0.0)
    assert [reason.kind for reason in said.why.reasons] == ["said_open"]
    assert said.why.base.kind == "pooled"
    assert said.why.base.of == "private_schools"
    utah = found.outlook_of(found.schools[2])[1]
    assert isinstance(utah, Forecast)
    assert utah.p_no_school == 0.01
    assert len(found.outlooks) < 2 * len(found.schools)


def test_a_reader_from_before_the_compact_file_still_takes_it() -> None:
    """The web reader live before this file left its defaults out (web/src/data/school-day.ts
    at ed5d405, parseForecast) refuses the whole file unless every forecast carries its
    ``reasons`` list, even empty, and each district its time zone: a page still on that
    script would hide every chance. The pass keeps both on every day it writes."""
    raw = json.loads(GOLDEN.read_bytes())
    days = [day for entry in raw["districts"] for day in entry["days"]] + raw["outlooks"]
    forecasts = [day for day in days if day["state"] == "forecast"]
    assert forecasts
    assert all(isinstance(day.get("reasons"), list) for day in forecasts)
    assert any(day["reasons"] == [] for day in forecasts)
    assert all(isinstance(entry.get("time_zone"), str) for entry in raw["districts"])

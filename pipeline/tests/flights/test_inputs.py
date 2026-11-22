"""The live inputs' readers, the polite fetcher, and the hourly reports' weather kinds."""

import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import polars as pl
import pytest

from snowlight.flights import fetch, inputs, obs
from snowlight.schemas.flights import (
    FlightsAlert,
    FlightsKind,
    FlightsProgram,
    FlightsProgramNow,
    FlightsProgramWhy,
    FlightsWeatherNow,
)

NOW = datetime(2026, 11, 21, 22, 30, tzinfo=UTC)

FAA = b"""<AIRPORT_STATUS_INFORMATION><Update_Time>Sat Nov 21 22:24:16 2026 GMT</Update_Time>
<Delay_type><Name>Ground Delay Programs</Name><Ground_Delay_List><Ground_Delay><ARPT>AAA</ARPT>
<Reason>low ceilings</Reason><Avg>1 hour and 6 minutes</Avg><Max>2 hours</Max></Ground_Delay>
</Ground_Delay_List></Delay_type>
<Delay_type><Name>Ground Stop Programs</Name><Ground_Stop_List><Program><ARPT>BBB</ARPT>
<Reason>thunderstorms</Reason><End_Time>2215 UTC</End_Time></Program><Program><ARPT>TOOLONG</ARPT>
</Program></Ground_Stop_List></Delay_type>
<Delay_type><Name>General Arrival/Departure Delay Info</Name><Arrival_Departure_Delay_List><Delay>
<ARPT>CCC</ARPT><Reason>WX:Snow</Reason><Arrival_Departure Type="Arrival"><Min>15 minutes</Min>
<Max>45 minutes</Max></Arrival_Departure><Arrival_Departure Type="Departure"><Min>1 minute</Min>
<Max>16 minutes</Max></Arrival_Departure></Delay></Arrival_Departure_Delay_List></Delay_type>
<Delay_type><Name>Airport Closures</Name><Airport_Closure_List><Airport><ARPT>AAA</ARPT>
<Reason>!AAA 05/277 AAA AD AP CLSD TO NON SKED TRANSIENT GA ACFT</Reason></Airport><Airport>
<ARPT>DDD</ARPT><Reason>!DDD 11/001 DDD AD AP CLSD</Reason></Airport></Airport_Closure_List>
</Delay_type><Delay_type><Name>Deicing</Name><Deicing_List><Airport><ARPT>EEE</ARPT>
<Reason>deicing</Reason></Airport></Deicing_List></Delay_type></AIRPORT_STATUS_INFORMATION>"""


def test_faa_programs_are_read_and_closures_to_others_left_out() -> None:
    at, programs = inputs.read_faa(FAA, NOW)
    assert at == datetime(2026, 11, 21, 22, 24, 16, tzinfo=UTC)
    found = {(p.code, p.program): p for p in programs}
    assert found[("AAA", FlightsProgram.GROUND_DELAY)].minutes == 66
    stop = found[("BBB", FlightsProgram.GROUND_STOP)]
    # 2215 UTC, read at 22:30: just past, kept as written, never moved to the next day.
    assert stop.until == datetime(2026, 11, 21, 22, 15, tzinfo=UTC)
    assert stop.kind == FlightsProgramWhy.WEATHER
    assert found[("CCC", FlightsProgram.ARRIVAL_DELAY)].minutes == 45
    assert found[("CCC", FlightsProgram.DEPARTURE_DELAY)].minutes == 16
    assert ("DDD", FlightsProgram.CLOSED) in found
    assert ("AAA", FlightsProgram.CLOSED) not in found
    assert ("EEE", FlightsProgram.DEICING) in found


# Cut from the FAA's own status (Nov 22 2026, 00:15Z): its ground stop end as it writes it.
REAL_STOP = b"""<AIRPORT_STATUS_INFORMATION><Update_Time>Sun Nov 22 00:15:02 2026 GMT</Update_Time>
<Delay_type><Name>Ground Stop Programs</Name><Ground_Stop_List><Program><ARPT>AAA</ARPT>
<Reason>TM Initiatives:MIT:WX</Reason><End_Time>8:00 pm EST</End_Time></Program>
</Ground_Stop_List></Delay_type></AIRPORT_STATUS_INFORMATION>"""


def test_a_ground_stop_end_in_a_us_zone_reads_as_its_true_instant() -> None:
    now = datetime(2026, 11, 22, 0, 16, tzinfo=UTC)
    _, programs = inputs.read_faa(REAL_STOP, now)
    (stop,) = programs
    # 8:00 pm EST on Nov 21 is 01:00Z on Nov 22, not 08:00Z.
    assert stop.until == datetime(2026, 11, 22, 1, 0, tzinfo=UTC)
    assert stop.kind == FlightsProgramWhy.WEATHER


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("8:00 pm EST", datetime(2026, 11, 22, 1, 0, tzinfo=UTC)),
        ("7:30 PM CST", datetime(2026, 11, 22, 1, 30, tzinfo=UTC)),
        ("11:15 p.m. PDT", datetime(2026, 11, 22, 6, 15, tzinfo=UTC)),
        ("12:00 am EST", datetime(2026, 11, 22, 5, 0, tzinfo=UTC)),
        ("12:30 pm HST", datetime(2026, 11, 21, 22, 30, tzinfo=UTC)),
        ("6:45 pm AKST", datetime(2026, 11, 22, 3, 45, tzinfo=UTC)),
        ("0130 UTC", datetime(2026, 11, 22, 1, 30, tzinfo=UTC)),
        ("Nov 22 at 02:00 UTC.", datetime(2026, 11, 22, 2, 0, tzinfo=UTC)),
        ("8:00 pm XYZ", None),
        ("13:00 pm EST", None),
        ("2215", None),
        ("soon", None),
        ("", None),
    ],
)
def test_faa_end_times(text: str, expected: datetime | None) -> None:
    assert inputs._when(text, datetime(2026, 11, 22, 0, 16, tzinfo=UTC)) == expected


@pytest.mark.parametrize(
    ("reason", "kind"),
    [
        ("TM Initiatives:MIT:WX", FlightsProgramWhy.WEATHER),
        ("WX:Snow/Ice", FlightsProgramWhy.WEATHER),
        ("low ceilings", FlightsProgramWhy.WEATHER),
        ("Volume:Volume", FlightsProgramWhy.VOLUME),
        ("equipment / outage", FlightsProgramWhy.EQUIPMENT),
        ("RWY 17R closed", FlightsProgramWhy.RUNWAY),
        ("other", FlightsProgramWhy.OTHER),
        (None, FlightsProgramWhy.OTHER),
    ],
)
def test_faa_reasons_are_published_as_kinds(reason: str | None, kind: FlightsProgramWhy) -> None:
    assert inputs.why_kind(reason) == kind


@pytest.mark.parametrize(
    "data",
    [
        b"not xml",
        b"<OTHER/>",
        b"<AIRPORT_STATUS_INFORMATION><Update_Time>soon</Update_Time></AIRPORT_STATUS_INFORMATION>",
    ],
)
def test_faa_bytes_that_do_not_read_are_refused(data: bytes) -> None:
    with pytest.raises(inputs.InputError):
        inputs.read_faa(data, NOW)


def test_durations_and_clocks() -> None:
    assert inputs.minutes_of("2 hours") == 120
    assert inputs.minutes_of("") is None
    assert inputs.minutes_of("soon") is None
    assert inputs._when("Nov 21 at 23:00 UTC.", NOW) == datetime(2026, 11, 21, 23, 0, tzinfo=UTC)
    assert inputs._when("9999", NOW) is None
    assert inputs._when(None, NOW) is None
    assert inputs._when("no time", NOW) is None


def _alert(
    event: str, ugc: str, onset: str, ends: str, status: str = "Actual"
) -> dict[str, object]:
    return {
        "properties": {
            "event": event,
            "status": status,
            "onset": onset,
            "ends": ends,
            "geocode": {"UGC": [ugc]},
        }
    }


def test_alerts_in_effect_reach_their_airports() -> None:
    doc = {
        "updated": "2026-11-21T22:24:35+00:00",
        "features": [
            _alert(
                "Winter Storm Warning",
                "MOZ001",
                "2026-11-21T12:00:00-06:00",
                "2026-11-22T12:00:00-06:00",
            ),
            _alert(
                "Blizzard Warning",
                "MOC001",
                "2026-11-23T12:00:00-06:00",
                "2026-11-24T12:00:00-06:00",
            ),
            _alert(
                "High Surf Advisory",
                "MOZ001",
                "2026-11-21T12:00:00-06:00",
                "2026-11-22T12:00:00-06:00",
            ),
            _alert(
                "Dense Fog Advisory",
                "GAZ001",
                "2026-11-21T12:00:00-05:00",
                "2026-11-21T13:00:00-05:00",
            ),
            _alert(
                "Ice Storm Warning",
                "GAZ001",
                "2026-11-21T12:00:00-05:00",
                "2026-11-22T13:00:00-05:00",
                "Test",
            ),
        ],
    }
    updated, found = inputs.read_alerts(
        json.dumps(doc).encode(), {"AAA": ("MOZ001", "MOC001"), "BBB": ("GAZ001", "")}, NOW
    )
    assert updated == datetime(2026, 11, 21, 22, 24, 35, tzinfo=UTC)
    assert found == {"AAA": [FlightsAlert.WINTER_STORM]}


@pytest.mark.parametrize("data", [b"{", b"{}", b'{"features": [], "updated": "x"}'])
def test_alert_bytes_that_do_not_read_are_refused(data: bytes) -> None:
    with pytest.raises(inputs.InputError):
        inputs.read_alerts(data, {}, NOW)


METARS = """\
raw_text,station_id,observation_time,wind_speed_kt,wind_gust_kt,visibility_statute_mi,wx_string,sky_cover,cloud_base_ft_agl,sky_cover,cloud_base_ft_agl
"METAR KAAA",KAAA,2026-11-21T21:53:00.000Z,12,45,0.50,-FZRA SN,OVC,300,,
"METAR KAAA",KAAA,2026-11-21T20:53:00.000Z,5,,10+,,CLR,,,
"METAR KBBB",KBBB,2026-11-21T21:52:00.000Z,30,,10+,TSRA,BKN,4000,OVC,8000
short,row
"METAR KZZZ",KZZZ,2026-11-21T21:52:00.000Z,3,,10,,,,,
"""


def test_weather_reports_give_the_newest_per_airport() -> None:
    found = inputs.read_metars(gzip.compress(METARS.encode()), {"KAAA": "AAA", "KBBB": "BBB"}, NOW)
    assert set(found) == {"AAA", "BBB"}
    aaa = found["AAA"]
    assert aaa.at == datetime(2026, 11, 21, 21, 53, tzinfo=UTC)
    assert aaa.kinds == (
        FlightsKind.FREEZING_RAIN,
        FlightsKind.SNOW,
        FlightsKind.FOG,
        FlightsKind.WIND,
    )
    assert aaa.gust == 45
    assert found["BBB"].kinds == (FlightsKind.THUNDER, FlightsKind.WIND)
    assert found["BBB"].visibility == 10.0
    with pytest.raises(inputs.InputError):
        inputs.read_metars(b"plain", {}, NOW)
    with pytest.raises(inputs.InputError):
        inputs.read_metars(gzip.compress(b""), {}, NOW)


def test_tafs_keep_the_newest_text() -> None:
    xml = (
        b"<response><data><TAF><raw_text>TAF KAAA OLD</raw_text><station_id>KAAA</station_id>"
        b"<issue_time>2026-11-21T18:00:00Z</issue_time></TAF><TAF><raw_text>TAF KAAA NEW</raw_text>"
        b"<station_id>KAAA</station_id><issue_time>2026-11-21T21:00:00Z</issue_time></TAF>"
        b"<TAF><raw_text>TAF KZZZ</raw_text><station_id>KZZZ</station_id></TAF></data></response>"
    )
    assert inputs.read_tafs(gzip.compress(xml), {"KAAA": "AAA"}) == {"AAA": "TAF KAAA NEW"}
    with pytest.raises(inputs.InputError):
        inputs.read_tafs(b"x", {})


def _client(statuses: list[int]) -> httpx.Client:
    answers = iter(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(answers)
        if status == 0:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(status, content=b"body")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_fetcher_tries_again_and_says_what_is_not_there(tmp_path: Path) -> None:
    waits: list[float] = []
    assert fetch.get_bytes(_client([0, 500, 200]), "https://x/a", sleep=waits.append) == b"body"
    assert waits == [5.0, 10.0]
    assert fetch.get_bytes(_client([404]), "https://x/a", sleep=waits.append) is None
    with pytest.raises(fetch.FetchError, match="HTTP 503"):
        fetch.get_bytes(_client([503, 503]), "https://x/a", tries=2, sleep=waits.append)
    target = tmp_path / "f.bin"
    assert fetch.download(_client([200]), "https://x/a", target, sleep=waits.append)
    assert target.read_bytes() == b"body"
    assert fetch.download(_client([]), "https://x/a", target)  # kept: no request
    assert not fetch.download(_client([404]), "https://x/b", tmp_path / "g.bin")


REPORTS = """station,valid,sknt,gust,vsby,skyc1,skyc2,skyc3,skyl1,skyl2,skyl3,wxcodes
AAA,2026-01-05 12:53,10,M,0.25,OVC,M,M,200,M,M,+SN
AAA,2026-01-05 13:53,10,M,1.00,OVC,M,M,800,M,M,-SN
AAA,2026-01-05 14:53,35,M,10,FEW,M,M,4000,M,M,BLSN
AAA,2026-01-05 15:53,8,45,10,CLR,M,M,M,M,M,-FZRA
BBB,2026-01-05 20:53,10,M,10,BKN,M,M,3000,M,M,VCTS
BBB,bad,10,M,10,BKN,M,M,3000,M,M,
"""


def test_hourly_reports_become_flags_and_block_kinds(tmp_path: Path) -> None:
    path = tmp_path / "r.csv"
    path.write_text(REPORTS)
    flags = obs.reduce_csv(path)
    aaa = flags.filter(pl.col("station") == "AAA").sort("hour")
    assert aaa.get_column("snow").to_list() == [True, True, False, False]
    assert aaa.get_column("fog").to_list() == [True, False, False, False]
    assert aaa.get_column("wind").to_list() == [False, False, True, True]
    assert aaa.get_column("frz").to_list() == [False, False, False, True]
    zones = pl.DataFrame(
        {
            "station": ["AAA", "BBB"],
            "apt": ["AAA", "BBB"],
            "tz": ["America/Chicago", "America/New_York"],
        }
    )
    kinds = obs.block_kinds(flags.lazy(), zones).collect()
    early = kinds.filter((pl.col("apt") == "AAA") & (pl.col("block") == 0)).row(0, named=True)
    # 07:00 to 09:00 Central: two snow hours and freezing rain at 10 is in the morning block.
    assert early["day"] == date(2026, 1, 5)
    assert early["kind"] == int(obs.Kind.SNOW)
    morning = kinds.filter((pl.col("apt") == "AAA") & (pl.col("block") == 1)).row(0, named=True)
    assert morning["kind"] == int(obs.Kind.FRZ)
    bbb = kinds.filter(pl.col("apt") == "BBB").row(0, named=True)
    assert bbb["kind"] == int(obs.Kind.THUNDER)
    url = obs.request_url(["AAA", "BBB"], 2026, 12)
    assert "station=AAA&station=BBB" in url
    assert "year2=2027&month2=1" in url


def test_a_bad_number_in_a_weather_report_never_stops_the_reports() -> None:
    bad = METARS.replace("OVC,300", "OVC,nan").replace("BKN,4000", "BKN,12O0")
    bad += '"METAR KCCC",KCCC,2026-11-21T21:52:00.000Z,inf,nan,abc,,OVC,1e999,,\n'
    found = inputs.read_metars(
        gzip.compress(bad.encode()), {"KAAA": "AAA", "KBBB": "BBB", "KCCC": "CCC"}, NOW
    )
    assert set(found) == {"AAA", "BBB", "CCC"}
    assert FlightsKind.FREEZING_RAIN in found["AAA"].kinds
    assert found["CCC"].visibility is None
    assert found["CCC"].gust is None


def test_observed_reports_read_as_the_history_does() -> None:
    body = (
        b"station,valid,sknt,gust,vsby,skyc1,skyc2,skyc3,skyl1,skyl2,skyl3,wxcodes\n"
        b"AAA,2026-11-20 22:53,5,M,1,OVC,M,M,800,M,M,-SN\n"
        b"AAA,2026-11-20 23:53,5,M,1,OVC,M,M,800,M,M,SN\n"
    )
    run = datetime(2026, 11, 21, tzinfo=UTC)
    flags = inputs.read_observed(body, run)
    assert flags.get_column("snow").to_list() == [True, True]
    assert flags.equals(obs.reduce_bytes(body))
    with pytest.raises(inputs.InputError, match="too early"):
        inputs.read_observed(body, datetime(2026, 11, 22, tzinfo=UTC))
    with pytest.raises(inputs.InputError, match="not the table"):
        inputs.read_observed(b"#ERROR: server busy\n", run)
    with pytest.raises(inputs.InputError, match="none"):
        inputs.read_observed(body.splitlines(keepends=True)[0], run)
    start, end = inputs.observed_window([run, datetime(2026, 11, 20, tzinfo=UTC)])
    assert (start, end) == (datetime(2026, 11, 17, 23, tzinfo=UTC), run)
    url = obs.window_url(["AAA", "BBB"], start, end)
    assert "hour1=23" in url
    assert "day2=21" in url
    assert "hour2" not in url
    assert url == obs.window_url(["AAA", "BBB"], start, end)


def test_the_observed_hours_before_a_run_count_by_day() -> None:
    hours = [datetime(2026, 11, 19, h, tzinfo=UTC) for h in range(24)]
    hours += [datetime(2026, 11, 20, h, tzinfo=UTC) for h in range(24)]
    flags = pl.DataFrame(
        {
            "station": ["AAA"] * 48,
            "hour": hours,
            "frz": [h.day == 19 and h.hour < 3 for h in hours],
            "snow": [h.day == 20 and h.hour >= 14 for h in hours],
            "thunder": [False] * 48,
            "fog": [False] * 48,
            "wind": [False] * 48,
        }
    )
    runs = pl.DataFrame(
        {
            "apt": ["AAA", "AAA"],
            "run": [datetime(2026, 11, 21, tzinfo=UTC), datetime(2026, 11, 22, tzinfo=UTC)],
        }
    )
    stations = pl.DataFrame({"station": ["AAA"], "apt": ["AAA"]})
    found = obs.before_runs(flags.lazy(), stations, runs.lazy()).collect().sort("run")
    first, second = found.to_dicts()
    assert (first["obs_snow"], first["obs_snow_old"], first["obs_frz"]) == (10.0, 0.0, 3.0)
    assert (second["obs_snow"], second["obs_snow_old"], second["obs_frz"]) == (0.0, 10.0, 0.0)
    none = obs.with_observed(runs.lazy(), None, stations).collect()
    assert none.get_column("obs_snow").to_list() == [0.0, 0.0]


def test_a_request_stops_at_its_deadline_even_while_its_body_streams() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/a"
        return httpx.Response(200, content=iter([b"a", b"b", b"c"]))

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch.get_bytes(http, "https://x/a", deadline=10.0, clock=lambda: 0.0) == b"abc"
    ticks = iter([0.0, 0.0, 11.0, 11.0])
    with pytest.raises(fetch.FetchError, match="out of time while reading"):
        fetch.get_bytes(http, "https://x/a", deadline=10.0, clock=lambda: next(ticks))
    with pytest.raises(fetch.FetchError, match="out of time"):
        fetch.get_bytes(http, "https://x/a", deadline=10.0, clock=lambda: 12.0)


def test_a_number_out_of_the_published_range_is_read_as_none() -> None:
    rows = METARS + (
        '"METAR KCCC",KCCC,2026-11-21T21:52:00.000Z,250,999,150,,OVC,-300,,\n'
        '"METAR KDDD",KDDD,2026-11-21T21:52:00.000Z,-5,99999999999,-1,,,,,\n'
        '"METAR KEEE",KEEE,2026-11-21T21:52:00.000Z,10,200,100,,,,,\n'
    )
    found = inputs.read_metars(
        gzip.compress(rows.encode()), {"KCCC": "CCC", "KDDD": "DDD", "KEEE": "EEE"}, NOW
    )
    for code in ("CCC", "DDD"):
        assert (found[code].visibility, found[code].gust) == (None, None)
        assert found[code].kinds == ()
    assert (found["EEE"].visibility, found["EEE"].gust) == (100.0, 200)
    assert inputs.minutes_of("24 hours") == inputs.MINUTES_MAX
    for text in ("25 hours", "1 hour and 2000 minutes", "99999999999999999999 minutes"):
        assert inputs.minutes_of(text) is None
    late = FAA.replace(b"<Max>16 minutes</Max>", b"<Max>25 hours</Max>")
    _, programs = inputs.read_faa(late, NOW)
    departure = [p for p in programs if p.program is FlightsProgram.DEPARTURE_DELAY]
    assert departure[0].minutes is None


def test_the_bounds_are_the_published_files_bounds() -> None:
    schema = FlightsWeatherNow.model_json_schema()["properties"]
    assert schema["visibility"]["anyOf"][0]["maximum"] == inputs.VISIBILITY_MAX
    assert schema["gust"]["anyOf"][0]["maximum"] == inputs.GUST_MAX
    minutes = FlightsProgramNow.model_json_schema()["properties"]["minutes"]
    assert minutes["anyOf"][0]["maximum"] == inputs.MINUTES_MAX


def test_a_report_off_the_pass_clock_never_hides_the_newest_real_one() -> None:
    rows = METARS + (
        '"METAR KAAA",KAAA,2026-11-29T04:00:00.000Z,5,,10,,,,,\n'
        '"METAR KAAA",KAAA,9999-12-31T23:59:59.000Z,5,,10,,,,,\n'
        '"METAR KBBB",KBBB,0001-01-01T00:00:00.000Z,5,,10,,,,,\n'
        '"METAR KBBB",KBBB,0999-06-01T00:00:00.000Z,5,,10,,,,,\n'
        '"METAR KCCC",KCCC,2026-11-01T00:00:00.000Z,5,,10,,,,,\n'
        '"METAR KDDD",KDDD,2026-11-21T22:39:00.000Z,5,,10,,,,,\n'
    )
    stations = {"KAAA": "AAA", "KBBB": "BBB", "KCCC": "CCC", "KDDD": "DDD"}
    with inputs.counting() as dropped:
        found = inputs.read_metars(gzip.compress(rows.encode()), stations, NOW)
    assert found["AAA"].at == datetime(2026, 11, 21, 21, 53, tzinfo=UTC)
    assert found["BBB"].at == datetime(2026, 11, 21, 21, 52, tzinfo=UTC)
    assert "CCC" not in found  # three weeks old: not a report of now
    assert found["DDD"].at == datetime(2026, 11, 21, 22, 39, tzinfo=UTC)  # within the minutes
    assert dropped["times"] == 5


def test_a_source_update_time_after_the_pass_is_not_read() -> None:
    ahead = FAA.replace(b"Sat Nov 21 22:24:16 2026", b"Sat Nov 21 23:32:54 2026")
    with pytest.raises(inputs.InputError, match="off the clock"):
        inputs.read_faa(ahead, NOW)
    old = FAA.replace(b"Sat Nov 21 22:24:16 2026", b"Sat Nov 01 22:24:16 2026")
    with pytest.raises(inputs.InputError, match="off the clock"):
        inputs.read_faa(old, NOW)
    for updated in ("2030-01-01T00:00:00+00:00", "0001-01-01T00:00:00+00:00"):
        doc: dict[str, object] = {"updated": updated, "features": []}
        with pytest.raises(inputs.InputError, match="off the clock"):
            inputs.read_alerts(json.dumps(doc).encode(), {}, NOW)


OBSERVED_HEAD = b"station,valid,sknt,gust,vsby,skyc1,skyc2,skyc3,skyl1,skyl2,skyl3,wxcodes\n"


def test_an_observed_hour_after_the_run_never_marks_a_station_fresh() -> None:
    run = datetime(2026, 11, 21, tzinfo=UTC)
    body = OBSERVED_HEAD + (
        b"AAA,2026-11-20 23:53,5,M,1,OVC,M,M,800,M,M,SN\n"
        b"BBB,2026-11-20 12:53,5,M,10,M,M,M,M,M,M,\n"
        b"BBB,2026-11-23 12:00,5,M,10,M,M,M,M,M,M,\n"
    )
    with inputs.counting() as dropped:
        flags = inputs.read_observed(body, run)
    assert flags.get_column("hour").max() == run
    assert dropped["times"] == 1
    assert inputs.fresh_stations(flags, run) == frozenset({"AAA"})


@pytest.mark.parametrize("valid", ["9999-12-31 23:59", "0001-01-01 00:00", "2026-11-22 99:99", "x"])
def test_one_observed_row_whose_time_does_not_read_is_that_rows_alone(valid: str) -> None:
    run = datetime(2026, 11, 21, tzinfo=UTC)
    body = OBSERVED_HEAD + (
        b"AAA,2026-11-20 23:53,5,M,1,OVC,M,M,800,M,M,SN\n"
        + f"BBB,{valid},5,M,10,M,M,M,M,M,M,\n".encode()
    )
    flags = inputs.read_observed(body, run)
    assert flags.get_column("station").to_list() == ["AAA"]
    assert flags.get_column("snow").to_list() == [True]


def test_values_out_of_range_are_counted_for_the_warning_line() -> None:
    rows = METARS + '"METAR KCCC",KCCC,2026-11-21T21:52:00.000Z,-5,nan,1e999,,OVC,-300,,\n'
    with inputs.counting() as dropped:
        inputs.read_metars(gzip.compress(rows.encode()), {"KCCC": "CCC"}, NOW)
        assert inputs.minutes_of("25 hours") is None
    assert dropped["values"] == 5
    assert inputs.within(-1.0, 1.0) is None  # outside counting(): nothing is counted, no error

"""The forecast bulletin's reader and the block features made from it."""

from datetime import UTC, date, datetime

import polars as pl
import pytest

from flights.synth import AIRPORTS, HOURS, bulletin, calm
from snowlight.flights import cli, features, nbs
from snowlight.flights.live import rows_of
from snowlight.flights.train import zones

RUN = datetime(2026, 1, 5, 0, tzinfo=UTC)


def test_a_bulletin_reads_its_stations_and_cells() -> None:
    snow = [None if i % 2 else 10 * (i // 2 + 1) for i in range(len(HOURS))]
    text = bulletin(RUN, {"KAAA": calm(S06=snow, CIG=[5] + [-88] * 22), "KBBB": calm()}, "V4.2")
    runs = list(nbs.parse(text))
    assert [r.station for r in runs] == ["KAAA", "KBBB"]
    aaa = runs[0]
    assert aaa.run == RUN
    assert aaa.valid[0] == datetime(2026, 1, 5, 6, tzinfo=UTC)
    assert aaa.get("S06")[:4] == (10, None, 20, None)
    assert aaa.get("CIG")[:2] == (5, -88)
    assert aaa.get("XND") == (None,) * len(HOURS)
    only = list(nbs.parse(text.splitlines(keepends=True), frozenset({"KBBB"})))
    assert [r.station for r in only] == ["KBBB"]


def test_a_section_without_hours_is_skipped() -> None:
    text = " KAAA    NBM  NBS GUIDANCE    1/05/2026  0000 UTC\n TMP  1\n"
    assert list(nbs.parse(text)) == []


def test_a_block_that_does_not_read_is_skipped_and_the_rest_kept() -> None:
    text = bulletin(RUN, {"KAAA": calm(), "KBBB": calm(), "KCCC": calm()})
    lines = text.splitlines()
    fhr = [i for i, line in enumerate(lines) if line.startswith(" FHR")]
    lines[fhr[0]] = lines[fhr[0]][:8] + "x0"  # KAAA's hours do not read
    bad_header = lines.index(next(line for line in lines if line.startswith(" KCCC")))
    lines[bad_header] = lines[bad_header].replace("1/05/2026", "13/05/2026")
    assert [r.station for r in nbs.parse("\n".join(lines))] == ["KBBB"]
    # Hours past any bulletin's, or a header naming another run than the one asked for.
    lines = text.splitlines()
    lines[fhr[0]] = lines[fhr[0]][:8] + "264268"
    lines[bad_header] = lines[bad_header].replace("1/05/2026", "1/05/1164")
    assert [r.station for r in nbs.parse("\n".join(lines), None, RUN)] == ["KBBB"]
    assert [r.station for r in nbs.parse("\n".join(lines))] == ["KBBB", "KCCC"]


def test_a_run_counts_only_when_it_gives_rows() -> None:
    today = datetime(2026, 11, 22, 3, tzinfo=UTC)
    older = datetime(2026, 11, 20, tzinfo=UTC)
    answers = {
        nbs.run_url(datetime(2026, 11, 22, tzinfo=UTC)): b"<html>not here</html>",
        nbs.run_url(datetime(2026, 11, 21, tzinfo=UTC)): bulletin(
            datetime(2026, 11, 21, tzinfo=UTC), {"KMCI": calm()}
        ).encode(),
        nbs.run_url(older): bulletin(older, {"KMCI": calm()}).encode(),
    }
    found = cli.newest_runs(None, today, answers.get)
    assert sorted({r.run.day for r in found}) == [20, 21]


def test_run_urls_and_days() -> None:
    assert nbs.run_url(RUN).endswith("/blend.20260105/00/text/blend_nbstx.t00z")
    assert len(list(nbs.runs_between(date(2026, 1, 1), date(2026, 1, 3)))) == 3


def _features(run: datetime = RUN, **changes: list[int | None]) -> pl.DataFrame:
    text = bulletin(run, {"KAAA": calm(**changes), "KBBB": calm()})
    rows = rows_of(list(nbs.parse(text)))
    z = zones(AIRPORTS).select("station", "apt", "tz")
    return features.block_features(rows.lazy(), z).collect()


def test_blocks_take_the_columns_in_them() -> None:
    snow = [None if i % 2 else 0 for i in range(len(HOURS))]
    snow[4] = 40  # 4.0 in. in the 6 hours to 18Z on the 5th (06-12 Central): early and morning
    found = _features(S06=snow, GST=[30] * len(HOURS))
    aaa = found.filter(pl.col("apt") == "AAA").sort("day", "block")
    first = aaa.row(0, named=True)
    # 00Z is 18:00 Central on the 4th: that night is the run's own day (class 0, never used),
    # so the first block is the early block of the 5th, 11 hours on, the evening before's run.
    assert (first["day"], first["block"], first["lead"]) == (date(2026, 1, 5), 0, 11.0)
    assert first["lead_class"] == 1
    assert aaa.get_column("snow").sum() == pytest.approx(4.0)
    assert aaa.get_column("gust").max() == 30
    # A block after snow carries it as snow before.
    after = aaa.filter((pl.col("day") == date(2026, 1, 5)) & (pl.col("block") == 2)).row(
        0, named=True
    )
    assert after["snow_before"] > 0
    # Every block kept starts at least 3 hours after the run and ends by 72.
    assert min(aaa.get_column("lead").to_list()) >= features.FIRST_HOURS


def test_only_whole_blocks_of_the_days_after_the_run_are_kept() -> None:
    for run in (RUN, datetime(2026, 1, 4, 22, tzinfo=UTC)):
        found = _features(run)
        assert found.height > 0
        # The run's own local day (Jan 4 in Central) is never kept, whatever the run's hour.
        assert date(2026, 1, 4) not in found.get_column("day").to_list()
        assert set(found.get_column("lead_class").to_list()) <= {1, 2, 3}
        latest = found.select((pl.col("end") - pl.col("run")).dt.total_hours().max()).item()
        assert latest <= features.LAST_HOURS
        assert min(found.get_column("lead").to_list()) >= features.FIRST_HOURS


def test_the_lead_class_counts_days_by_the_airports_own_calendar() -> None:
    # 00Z on Jan 5 is 10:00 on Jan 5 in Guam: Jan 5 is the run's own day there (never used)
    # and Jan 6 is lead 1, the day after the run; in Central, Jan 5 is lead 1.
    text = bulletin(RUN, {"KAAA": calm()})
    rows = rows_of(list(nbs.parse(text)))
    guam = pl.DataFrame({"station": ["KAAA"], "apt": ["GGG"], "tz": ["Pacific/Guam"]})
    found = features.block_features(rows.lazy(), guam).collect()
    days = dict(found.select("day", "lead_class").unique().iter_rows())
    assert date(2026, 1, 5) not in days
    assert days[date(2026, 1, 6)] == 1


def test_lead_classes_and_hubs() -> None:
    assert features.lead_class(date(2026, 1, 5), date(2026, 1, 4)) == 1
    assert features.lead_class(date(2026, 1, 7), date(2026, 1, 4)) == 3
    found = features.with_hubs(_features(), ("AAA",))
    assert {"hub_snow", "hub_storm"} <= set(found.columns)
    assert features.newest_run(pl.DataFrame({"run": [RUN]})) == RUN
    assert features.newest_run(pl.DataFrame()) is None


def test_no_airports_gives_no_rows() -> None:
    rows = rows_of(list(nbs.parse(bulletin(RUN, {"KAAA": calm()}))))
    empty = zones(()).select("station", "apt", "tz")
    assert features.block_features(rows.lazy(), empty).collect().height == 0

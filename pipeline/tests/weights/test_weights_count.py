"""School days, the 6 AM rule and the per-county tally.

Every event row here is a real line of an IEM school-year file
(``fixtures/iem-*.csv``); the zone mapping and the counties come from the real
slices of the NWS correlation and county files (see ``fixtures/provenance.json``).
"""

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

from snowlight.weights import archive, count, zones
from snowlight.weights.codes import SUBSETS

if TYPE_CHECKING:
    from weights.conftest import Kit

NEW_YORK = ("America/New_York",)
GULF_ZONES = ("America/Chicago", "America/New_York")


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def _rows(kit: "Kit", name: str) -> list[archive.EventRow]:
    rows, _ = archive.read_rows(kit.text(name))
    return rows


def _row(kit: "Kit", name: str, event: str, ugc: str) -> archive.EventRow:
    found = [row for row in _rows(kit, name) if row.event_key == event and row.ugc == ugc]
    assert len(found) == 1, (event, ugc, found)
    return found[0]


def _days(row: archive.EventRow, zones_: tuple[str, ...] = NEW_YORK) -> list[date]:
    return sorted(count.counted_days(row.begin, row.end, row.product_issued, zones_))


def _catalog(kit: "Kit") -> tuple[zones.ZoneCountyCatalog, zones.CountyList]:
    releases = zones.load_releases(kit.cache(), kit.releases)
    counties = zones.read_counties(kit.path("c_16ap26.zip"))
    return zones.ZoneCountyCatalog(releases, counties.state_fips), counties


def test_school_days() -> None:
    days = count.school_days(2024)
    assert days[0] == date(2024, 8, 15)  # a Thursday
    assert days[-1] == date(2025, 6, 13)  # 15 June 2025 is a Sunday
    assert all(day.weekday() < 5 for day in days)
    assert date(2025, 1, 20) in days  # holidays are not removed
    assert date(2025, 1, 19) not in days
    assert len(days) == 217  # 305 days: 43 weeks and Thursday to Sunday
    assert count.school_year_of(date(2025, 8, 1)) == 2025
    assert count.school_year_of(date(2025, 7, 31)) == 2024


def test_in_effect_at_six(kit: "Kit") -> None:
    # BOX.WS.W.0001.2025 on RIZ001: Sunday 1 PM to Monday 6:46 AM EST.
    row = _row(kit, "iem-2024-2025.csv", "BOX.WS.W.0001.2025", "RIZ001")
    monday = date(2025, 1, 20)
    assert count.row_counts_on(row.begin, row.end, row.product_issued, monday, NEW_YORK[0])
    # Sunday counts too (issued at 1:42 AM for 1 PM), but is not a school day.
    assert _days(row) == [date(2025, 1, 19), date(2025, 1, 20)]


def test_cancelled_before_six_does_not_count(kit: "Kit") -> None:
    # BOX.WW.Y.0004.2025: Sunday 7 PM to Monday 2:57 AM EST (cancelled).
    row = _row(kit, "iem-2024-2025.csv", "BOX.WW.Y.0004.2025", "RIZ001")
    assert row.status == "CAN"
    assert _days(row) == []


def test_issued_for_the_day_by_six(kit: "Kit") -> None:
    # BOX.WW.Y.0005.2025: issued Tuesday for Thursday 7 AM EST.
    row = _row(kit, "iem-2024-2025.csv", "BOX.WW.Y.0005.2025", "RIZ001")
    assert row.begin == _utc("2025-02-06T12:00")
    assert _days(row) == [date(2025, 2, 6)]


def test_issued_after_six_does_not_count(kit: "Kit") -> None:
    # BOX.WW.Y.0014.2024 on RIZ001: issued and begun Friday 10:08 AM EST.
    row = _row(kit, "iem-2024-2025.csv", "BOX.WW.Y.0014.2024", "RIZ001")
    assert row.product_issued == row.begin == _utc("2024-12-20T15:08")
    assert _days(row) == []


def test_row_upgraded_before_it_began(kit: "Kit") -> None:
    # BOX.WW.Y.0022.2018 on RIZ001 was upgraded at 11:20 AM EST, before its 4 PM start:
    # IEM records it ending before it began. It is kept, but it was for 4 PM, after
    # the school day, so it does not count. Nor does the warning that replaced it,
    # issued after 6 AM and over by 2:11 AM the next morning.
    advisory = _row(kit, "iem-2018-2019.csv", "BOX.WW.Y.0022.2018", "RIZ001")
    assert advisory.status == "UPG"
    assert advisory.end < advisory.begin
    assert _days(advisory) == []
    warning = _row(kit, "iem-2018-2019.csv", "BOX.WS.W.0009.2018", "RIZ001")
    assert warning.product_issued == advisory.end
    assert _days(warning) == []


def test_withdrawn_after_six_still_counts() -> None:
    """Synthetic times on the real BOX.WW.Y.0005.2025 row: withdrawn at 7 AM, before its start.

    At 6 AM it had been issued for that day, so the day counts; withdrawn at 5 AM, it
    does not.
    """
    begin, issued = _utc("2025-02-06T15:00"), _utc("2025-02-04T19:27")
    withdrawn_late, withdrawn_early = _utc("2025-02-06T12:00"), _utc("2025-02-06T10:00")
    zone = "America/New_York"
    assert count.row_counts_on(begin, withdrawn_late, issued, date(2025, 2, 6), zone)
    assert not count.row_counts_on(begin, withdrawn_early, issued, date(2025, 2, 6), zone)
    assert count.counted_days(begin, withdrawn_late, issued, (zone,)) == {date(2025, 2, 6)}


def test_start_after_the_school_day_does_not_count(kit: "Kit") -> None:
    # BOX.WS.W.0002.2025 on RIZ001: issued at 2:55 AM EST for 7 PM, over by 3:41 AM.
    row = _row(kit, "iem-2024-2025.csv", "BOX.WS.W.0002.2025", "RIZ001")
    assert row.begin == _utc("2025-02-09T00:00")
    assert _days(row) == []
    # BOX.WW.Y.0008.2025: issued Friday for Saturday 1 PM EST (before 3 PM), in
    # effect at 6 AM Sunday.
    row = _row(kit, "iem-2024-2025.csv", "BOX.WW.Y.0008.2025", "RIZ001")
    assert _days(row) == [date(2025, 2, 15), date(2025, 2, 16)]
    assert count.SCHOOL_DAY_END.hour == 15


def test_split_county_counts_in_either_zone(kit: "Kit") -> None:
    # TAE.FF.W.0074.2024 on Gulf County (FLC045): 6:30 AM EDT = 5:30 AM CDT. At 6 AM
    # Eastern it had not begun (and was issued at 6:30); at 6 AM Central it was in effect.
    row = _row(kit, "iem-2024-2025.csv", "TAE.FF.W.0074.2024", "FLC045")
    assert _days(row, ("America/New_York",)) == []
    assert _days(row, ("America/Chicago",)) == [date(2024, 9, 12)]
    assert _days(row, GULF_ZONES) == [date(2024, 9, 12)]


def test_tally_keeps_the_heaviest_code_per_day(kit: "Kit") -> None:
    catalog, counties = _catalog(kit)
    files = archive.load_years(kit.cache(), [2024])
    tally = count.count_years(files, catalog, counties)
    gulf, franklin = tally.year("12045", 2024), tally.year("12037", 2024)
    # Helene: a Hurricane Warning in effect at 6 AM on the 25th and 26th; in Franklin
    # County (FLZ115) a Tropical Storm Warning replaced it at 5:09 AM EDT on the 27th.
    # Milton's Tropical Storm Warning covered Franklin on 8 and 9 October.
    assert gulf.days("HU.W") == {date(2024, 9, 25), date(2024, 9, 26)}
    assert franklin.days("HU.W") == {date(2024, 9, 25), date(2024, 9, 26)}
    assert gulf.days("TR.W") == set()
    assert franklin.days("TR.W") == {date(2024, 9, 27), date(2024, 10, 8), date(2024, 10, 9)}
    helene = {date(2024, 9, 25), date(2024, 9, 26), date(2024, 9, 27)}
    assert franklin.weighted({"HU.W", "TR.W"}) == pytest.approx(1.0 + 1.0 + 0.5 + 0.5 + 0.5)
    assert franklin.any_days({"HU.W", "TR.W"}) >= helene
    # January 2025: the Winter Storm Warning (1.0) and the Extreme Cold Warning (0.5)
    # both covered the 22nd, which counts once at 1.0.
    assert date(2025, 1, 22) in gulf.days("WS.W") & gulf.days("EC.W")
    only_jan = {"WS.W", "EC.W"}
    jan_days = gulf.any_days(only_jan)
    assert jan_days == {date(2025, 1, 21), date(2025, 1, 22), date(2025, 1, 23)}
    assert gulf.weighted(only_jan) == pytest.approx(1.0 + 1.0 + 0.5)
    providence = tally.year("44007", 2024)
    assert providence.days("WS.W") == {date(2025, 1, 20)}
    assert providence.by_code["WS.W"][date(2025, 1, 20)] == {"RIZ001", "RIZ002"}
    assert tally.year("99999", 2024).any_days() == set()
    assert tally.stats.rows == len(files[0].rows)
    assert tally.stats.rows_without_county == 0


def test_county_days_summary(kit: "Kit") -> None:
    catalog, counties = _catalog(kit)
    files = archive.load_years(kit.cache(), [2018, 2024])
    tally = count.count_years(files, catalog, counties)
    zones_on = count.ZonesOnDay(catalog)
    summary = count.summarize(tally, counties.counties, zones_on, SUBSETS)
    assert set(summary) == set(counties.counties)
    providence = summary["44007"]
    year_2024 = providence.by_year[2024]
    assert year_2024 is not None
    weighted_2024, days_2024 = year_2024
    assert days_2024 == len(tally.year("44007", 2024).any_days())
    assert providence.years_counted == (2018, 2024)
    assert providence.years_left_out == ()
    assert providence.days_per_year == pytest.approx(providence.weighted_days_total / 2)
    assert providence.code_days["WS.W"] == len(tally.year("44007", 2018).days("WS.W")) + 1
    assert providence.subset_days_per_year["flood"] == 0.0
    assert providence.any_days_per_year >= providence.days_per_year
    assert providence.whole_county_days_per_year <= providence.days_per_year
    assert weighted_2024 > 0
    # RIZ001 and RIZ002 make up Providence County: 20 Jan 2025 (both) is a
    # whole-county day; the drivers list both zones.
    assert set(providence.drivers) >= {"RIZ001", "RIZ002"}
    assert zones_on("44007", date(2025, 1, 20)) == frozenset({"RIZ001", "RIZ002"})
    whole = count.whole_days(tally.year("44007", 2024), zones_on, "44007")
    assert date(2025, 1, 20) in whole["WS.W"]
    # A county never touched has all zeros.
    assert summary["09003"].days_per_year == 0.0
    assert summary["09003"].drivers == {}


def test_summary_leaves_out_incomplete_years(kit: "Kit") -> None:
    """A county-year left out is not a zero: the county is averaged over its other years."""
    catalog, counties = _catalog(kit)
    files = archive.load_years(kit.cache(), [2018, 2024])
    tally = count.count_years(files, catalog, counties)
    zones_on = count.ZonesOnDay(catalog)
    full = count.summarize(tally, counties.counties, zones_on, SUBSETS)
    part = count.summarize(tally, counties.counties, zones_on, SUBSETS, {"44007": {2018}})
    providence, whole = part["44007"], full["44007"]
    assert providence.years_counted == (2024,)
    assert providence.years_left_out == (2018,)
    assert providence.by_year[2018] is None
    assert providence.by_year[2024] == whole.by_year[2024]
    only_2024 = tally.year("44007", 2024)
    # Every per-year figure is over 2024 alone, not over two years with 2018 as zero.
    assert providence.days_per_year == pytest.approx(only_2024.weighted())
    assert providence.weighted_days_total == pytest.approx(only_2024.weighted())
    assert providence.any_days_per_year == len(only_2024.any_days())
    assert providence.code_days["WS.W"] == len(only_2024.days("WS.W")) == 1
    assert providence.code_days_per_year("WS.W") == 1.0
    assert providence.subset_days_per_year["winter"] == pytest.approx(
        only_2024.weighted(SUBSETS["winter"])
    )
    assert providence.whole_county_days_per_year <= providence.days_per_year
    assert whole.code_days["WS.W"] > providence.code_days["WS.W"]
    # Leaving out 2018-19 (3.25 weighted days in the slice, against 1.75 in 2024-25)
    # moves the average to 2024-25's value, not to half of it.
    year_2018 = whole.by_year[2018]
    assert year_2018 is not None
    assert year_2018[0] == pytest.approx(3.25)
    assert only_2024.weighted() == pytest.approx(1.75)
    assert whole.days_per_year == pytest.approx((3.25 + 1.75) / 2)
    assert providence.days_per_year == pytest.approx(1.75)
    # Other counties keep both years.
    assert part["44003"] == full["44003"]
    assert part["44003"].years_counted == (2018, 2024)


def test_every_year_left_out_is_an_error(kit: "Kit") -> None:
    catalog, counties = _catalog(kit)
    files = archive.load_years(kit.cache(), [2024])
    tally = count.count_years(files, catalog, counties)
    zones_on = count.ZonesOnDay(catalog)
    with pytest.raises(count.CountError, match="44007: every school year is left out"):
        count.summarize(tally, counties.counties, zones_on, SUBSETS, {"44007": {2024}})

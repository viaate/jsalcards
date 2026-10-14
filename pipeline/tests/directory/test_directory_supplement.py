"""The supplement of schools the NCES files miss: the file's checks and the build's merge.

Entries written by these tests are SYNTHETIC (names start "Synthetic" or copy a
fixture school's to test the duplicate rule); only the test for the committed
file reads real entries.
"""

import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]
from pydantic import ValidationError

from snowlight.directory import points, tiles
from snowlight.directory.build import BuildPaths, BuildResult, build, summary_lines
from snowlight.directory.config import DirectoryConfig, SupplementSettings, load_config
from snowlight.directory.supplement import (
    EXPIRY_WARNING_DAYS,
    SupplementError,
    SupplementSchool,
    address_expires_on,
    address_stale,
    check_prefix_unused,
    evidence_expires_on,
    evidence_stale,
    expiring,
    load_supplement,
    meters_between,
    same_name,
    same_words,
    school_year_of,
    school_year_start,
    street_key,
)

if TYPE_CHECKING:
    from directory.conftest import FixtureServer, SyntheticTiles


@pytest.fixture(autouse=True)
def tippecanoe_or_stand_in(
    monkeypatch: pytest.MonkeyPatch, synthetic_tiles: type["SyntheticTiles"]
) -> None:
    """Use tippecanoe when installed; otherwise tile the input synthetically."""
    if shutil.which("tippecanoe") is not None:
        return

    def synthetic(source: Path, target: Path, settings: tiles.TileSettings) -> list[str]:
        text = source.read_text(encoding="utf-8")
        target.write_bytes(
            synthetic_tiles.from_geojsonseq(
                text, settings.layer, settings.minzoom, settings.maxzoom
            )
        )
        return ["synthetic-tippecanoe"]

    monkeypatch.setattr(tiles, "run_tippecanoe", synthetic)


def entry(**changes: Any) -> dict[str, Any]:
    """A valid SYNTHETIC supplement entry (a made-up school in Montgomery, AL)."""
    base: dict[str, Any] = {
        "id": "SN000001",
        "name": "SYNTHETIC ST. ANN CATHOLIC SCHOOL",
        "street": "100 SYNTHETIC ST",
        "city": "MONTGOMERY",
        "state": "AL",
        "zip": "36104",
        "county_fips": "01101",
        "county_name": "Montgomery County",
        "lat": 32.3668,
        "lon": -86.3,
        "grade_low": "PK",
        "grade_high": "08",
        "source": "diocese-list",
        "evidence_url": "https://example.org/schools",
        "address_from": "diocese-list",
        "address_url": "https://example.org/schools",
        "address_checked_on": "2026-10-14",
        "geocoded_address": "100 SYNTHETIC ST, MONTGOMERY, AL, 36104",
        "checked_on": "2026-10-14",
    }
    base.update(changes)
    # An entry with an earlier PSS id records that row's grades; unless a test
    # says otherwise, they are the entry's own.
    if base.get("nces_ppin") is not None and "pss_grade_low" not in changes:
        base["pss_grade_low"], base["pss_grade_high"] = base["grade_low"], base["grade_high"]
    # Names and places are written as the NCES files write theirs.
    for key in ("name", "street", "city"):
        if isinstance(base.get(key), str):
            base[key] = base[key].upper()
    return base


def write(
    path: Path,
    entries: list[dict[str, Any]],
    retired: tuple[str, ...] = (),
    last_id: str | None = None,
) -> Path:
    """Write a supplement file; ``last_id`` defaults to the highest id in it."""
    ids = [str(e["id"]) for e in entries] + list(retired)
    last = last_id if last_id is not None else max(ids, default=None)
    body: dict[str, Any] = {"last_id": last, "retired_ids": list(retired), "schools": entries}
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


def test_committed_supplement_checks_out() -> None:
    config = load_config()
    assert config.supplement is not None
    assert config.supplement.id_prefix == "SN"
    supplement = load_supplement(config.supplement.resolved(), config.supplement.id_prefix)
    bounds = config.filters.bounds
    for school in supplement.schools:
        assert bounds.south < school.lat < bounds.north, school.id
        assert bounds.west < school.lon < bounds.east, school.id
        assert school.county_fips[:2] in config.filters.state_fips, school.id
        assert school.checked_on <= datetime.now(UTC).date()
        # Every address was matched this school year against a current source,
        # never taken from an earlier PSS file alone.
        assert school.address_checked_on >= school_year_start(school.checked_on), school.id
        assert school.geocoded_address.upper().startswith(school.street.split()[0]), school.id
        # Grades that differ from the school's earlier PSS row name the page that
        # settles them, and an NCES point stands only where a reviewer matched it.
        if school.nces_ppin is not None:
            pss = (school.pss_grade_low, school.pss_grade_high)
            if pss != (school.grade_low, school.grade_high):
                assert school.grades_url is not None, school.id
        if school.geocoder == "nces-pss":
            assert school.location_url is not None, school.id


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"grade_low": "PK", "grade_high": "PK"}, "no grade from K to 12"),
        ({"grade_low": "08", "grade_high": "KG"}, "grade_low is above grade_high"),
        ({"county_fips": "20091"}, "is not in AL"),
        ({"zip": "3610"}, "five digits"),
        ({"lat": 32.36681234}, "six decimals"),
        ({"evidence_url": None}, "needs evidence"),
        ({"evidence_url": "http://example.org"}, "https"),
        ({"evidence_station": "synthetic-station"}, "go together"),
        ({"source": "pss-2021-22"}, "nces_ppin"),
        ({"geocoder": "nces-pss"}, "nces_ppin"),
        # NCES's own point stands only once matched against the school's own map.
        ({"geocoder": "nces-pss", "nces_ppin": "A0000001"}, "location_url and location"),
        (
            {
                "geocoder": "nces-pss",
                "nces_ppin": "A0000001",
                "location_url": "https://example.org/map",
                "location_checked_on": "2026-10-15",
            },
            "location_checked_on is after checked_on",
        ),
        ({"location_url": "https://example.org/map"}, "for nces-pss geocodes"),
        ({"location_checked_on": "2026-10-14"}, "for nces-pss geocodes"),
        # Grades that differ from the earlier PSS row need the page that settles them.
        (
            {"nces_ppin": "A0000001", "pss_grade_low": "KG", "pss_grade_high": "12"},
            "grades PK-08 differ from its PSS row's KG-12: grades_url",
        ),
        (
            {"nces_ppin": "A0000001", "pss_grade_low": None, "pss_grade_high": None},
            "records its PSS row's grades",
        ),
        (
            {"nces_ppin": "A0000001", "pss_grade_low": "PK", "pss_grade_high": None},
            "records its PSS row's grades",
        ),
        ({"pss_grade_low": "PK", "pss_grade_high": "08"}, "and only such an entry"),
        (
            {"nces_ppin": "A0000001", "pss_grade_low": "UG", "pss_grade_high": "08"},
            "grade must be one of",
        ),
        (
            {
                "nces_ppin": "A0000001",
                "pss_grade_low": "KG",
                "pss_grade_high": "12",
                "grades_url": "http://example.org/grades",
            },
            "https",
        ),
        ({"geocoder": "google"}, "geocoder"),
        (
            {"evidence_station": "synthetic-station", "evidence_seen_on": "2026-11-01"},
            "after checked_on",
        ),
        ({"state": "XX"}, "unknown state"),
        ({"grade_high": None}, "valid string"),
        ({"grade_low": None, "grade_high": None}, "valid string"),
        (
            {"grade_high": "KG", "source": "pss-2021-22", "nces_ppin": "A0000001"},
            "current source",
        ),
        (
            {"grade_low": "KG", "grade_high": "KG", "source": "pss-2019-20", "nces_ppin": "1"},
            "current source",
        ),
        ({"website": "https://example.org"}, "Extra inputs"),
        # An address needs a current source of its own: an earlier PSS file is not one.
        ({"address_from": None}, "address_from"),
        ({"address_from": "pss-2021-22"}, "address_from"),
        ({"address_url": None}, "needs its address_url"),
        ({"address_url": "http://example.org/schools"}, "https"),
        ({"address_checked_on": None}, "address_checked_on"),
        ({"address_checked_on": "2026-10-15"}, "address_checked_on is after checked_on"),
        ({"address_from": "closings-row"}, "needs evidence_station"),
        (
            {
                "address_from": "closings-row",
                "address_url": None,
                "evidence_station": "synthetic-station",
                "evidence_seen_on": "2026-09-02",
                "address_checked_on": "2026-10-14",
            },
            "row's evidence_seen_on",
        ),
        # A closings row is evidence for this school year or the last only.
        (
            {"evidence_station": "synthetic-station", "evidence_seen_on": "2025-07-31"},
            "school year of checked_on or the one before",
        ),
    ],
)
def test_malformed_entries_are_refused(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        SupplementSchool.model_validate(entry(**changes))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "Synthetic St. Ann Catholic School"),
        ("name", "SYNTHETIC CURÉ OF ARS SCHOOL"),
        ("street", "100 Synthetic St"),
        ("city", "Montgomery"),
    ],
)
def test_names_are_written_as_nces_writes_them(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match="ASCII capitals"):
        SupplementSchool.model_validate({**entry(), field: value})


def test_closings_evidence_alone_is_enough() -> None:
    school = SupplementSchool.model_validate(
        entry(
            evidence_url=None,
            evidence_station="synthetic-station",
            evidence_seen_on="2026-01-23",
            source="pss-2021-22",
            nces_ppin="A0000001",
        )
    )
    assert school.evidence_seen_on == date(2026, 1, 23)


def test_a_closings_row_may_give_the_address() -> None:
    school = SupplementSchool.model_validate(
        entry(
            evidence_url=None,
            evidence_station="synthetic-station",
            evidence_seen_on="2026-09-02",
            address_from="closings-row",
            address_url=None,
            address_checked_on="2026-09-02",
        )
    )
    assert school.evidence_on == date(2026, 9, 2)


def _at(**changes: Any) -> SupplementSchool:
    return SupplementSchool.model_validate(entry(**changes))


def test_evidence_ages_from_its_own_date() -> None:
    # A closings row from December, checked by hand in October: it ages from December.
    row = _at(
        evidence_url=None, evidence_station="synthetic-station", evidence_seen_on="2025-12-05"
    )
    assert row.evidence_on == date(2025, 12, 5)
    assert not evidence_stale(row, date(2026, 12, 5), 365)
    assert evidence_stale(row, date(2026, 12, 6), 365)
    # Whatever the age limit, evidence from before last school year is stale.
    assert not evidence_stale(row, date(2027, 7, 31), None)
    assert evidence_stale(row, date(2027, 8, 1), None)
    # A current page ages from the day it was checked.
    page = _at(evidence_station="synthetic-station", evidence_seen_on="2025-12-05")
    assert page.evidence_on == date(2026, 10, 14)
    assert not evidence_stale(page, date(2027, 10, 14), 365)
    assert evidence_stale(page, date(2027, 10, 15), 365)


def test_an_address_is_checked_every_school_year() -> None:
    school = _at(address_checked_on="2026-08-01")
    assert not address_stale(school, date(2027, 7, 31))
    assert address_stale(school, date(2027, 8, 1))
    # Matched in July: a school may move over the summer, so not current in August.
    july = _at(address_checked_on="2026-07-31")
    assert not address_stale(july, date(2026, 7, 31))
    assert address_stale(july, date(2026, 8, 1))


def test_grades_differing_from_the_pss_row_are_settled_by_a_page() -> None:
    # The earlier survey says K-12; the school's own site says PK-12 now.
    school = _at(
        grade_high="12",
        nces_ppin="A0000001",
        pss_grade_low="KG",
        pss_grade_high="12",
        grades_url="https://example.org/our-school",
    )
    assert (school.grade_low, school.grade_high) == ("PK", "12")
    # Grades equal to the PSS row's need no page.
    assert _at(nces_ppin="A0000001").grades_url is None


def test_an_nces_point_needs_a_matched_map() -> None:
    school = _at(
        geocoder="nces-pss",
        nces_ppin="A0000001",
        location_url="https://example.org/map",
        location_checked_on="2026-10-14",
    )
    assert school.location_checked_on == date(2026, 10, 14)


def test_expiry_dates_are_the_first_stale_builds() -> None:
    schools = [
        _at(evidence_url=None, evidence_station="synthetic-station", evidence_seen_on=seen)
        for seen in ("2025-08-01", "2025-12-05", "2026-07-31", "2026-09-02")
    ] + [_at(address_checked_on=day) for day in ("2026-07-31", "2026-08-01", "2026-10-14")]
    for school in schools:
        for max_age in (365, 120, None):
            first = evidence_expires_on(school, max_age)
            day = school.evidence_on
            while day < date(2028, 9, 1):
                assert evidence_stale(school, day, max_age) == (day >= first), (school, day)
                day += timedelta(days=1)
        first = address_expires_on(school)
        day = school.address_checked_on
        while day < date(2028, 9, 1):
            assert address_stale(school, day) == (day >= first), (school, day)
            day += timedelta(days=7)


def test_entries_about_to_go_stale_are_listed() -> None:
    row = _at(
        id="SN000002",
        evidence_url=None,
        evidence_station="synthetic-station",
        evidence_seen_on="2025-12-05",
    )
    page = _at(id="SN000001")
    soon = expiring([page, row], date(2026, 10, 14), 365)
    # The row turns a year old on 2026-12-06, within 60 days; the page's evidence
    # (2027-10-15) and both addresses (2027-08-01) are further off.
    assert [(e.id, e.what, e.expires_on) for e in soon] == [
        ("SN000002", "evidence", date(2026, 12, 6))
    ]
    assert EXPIRY_WARNING_DAYS == 60
    # Sixty days before August 1, every address goes on the list, soonest first.
    june = expiring([page, row], date(2027, 6, 2), 365)
    assert [(e.id, e.what) for e in june] == [("SN000001", "address"), ("SN000002", "address")]
    # A check already stale is not listed: the build has dropped the entry.
    assert expiring([row], date(2026, 12, 6), 365) == []


def test_kindergarten_from_a_current_source_is_kept() -> None:
    school = SupplementSchool.model_validate(entry(grade_high="KG", source="school-site"))
    assert school.grade_high == "KG"


def test_ids_are_the_prefix_and_unique(tmp_path: Path) -> None:
    path = tmp_path / "supplement.yaml"
    assert len(load_supplement(write(path, [entry()]), "SN").schools) == 1
    with pytest.raises(SupplementError, match="SN and six digits"):
        load_supplement(write(path, [entry(id="A0000001")]), "SN")
    with pytest.raises(SupplementError, match="SN and six digits"):
        load_supplement(write(path, [entry(id="SN00001")]), "SN")
    twice = [entry(), entry(name="Synthetic Other Academy", lat=33.0)]
    with pytest.raises(SupplementError, match="repeated id"):
        load_supplement(write(path, twice), "SN")


def test_ids_are_never_reused_or_skipped(tmp_path: Path) -> None:
    path = tmp_path / "supplement.yaml"
    second = entry(id="SN000003", name="Synthetic Other Academy", lat=33.0)
    # SN000002 was deleted: it must be retired, never left as a gap to fill.
    with pytest.raises(SupplementError, match="SN000002 is neither an entry nor retired"):
        load_supplement(write(path, [entry(), second]), "SN")
    kept = load_supplement(write(path, [entry(), second], retired=("SN000002",)), "SN")
    assert [s.id for s in kept.schools] == ["SN000001", "SN000003"]
    # A retired id is never issued again.
    reused = entry(id="SN000002", name="Synthetic New Academy", lat=34.0)
    with pytest.raises(SupplementError, match="retired and in use"):
        load_supplement(write(path, [entry(), reused, second], retired=("SN000002",)), "SN")
    # Deleting the newest entry still retires its id: last_id keeps it issued.
    with pytest.raises(SupplementError, match="SN000003 is neither"):
        load_supplement(write(path, [entry()], retired=("SN000002",), last_id="SN000003"), "SN")
    with pytest.raises(SupplementError, match="above last_id"):
        load_supplement(write(path, [entry(), second], ("SN000002",), "SN000002"), "SN")
    path.write_text(yaml.safe_dump({"schools": [entry()]}), encoding="utf-8")
    with pytest.raises(SupplementError, match="last_id is missing"):
        load_supplement(path, "SN")


def test_one_school_listed_twice_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "supplement.yaml"
    near = entry(id="SN000002", name="SYNTHETIC SAINT ANN SCHOOL", lat=32.3669)
    with pytest.raises(SupplementError, match="same school"):
        load_supplement(write(path, [entry(), near]), "SN")
    far = entry(id="SN000002", lat=32.5)
    assert len(load_supplement(write(path, [entry(), far]), "SN").schools) == 2
    campus = entry(id="SN000002", name="Synthetic St. Ann Collegiate High School", lat=32.3669)
    assert len(load_supplement(write(path, [entry(), campus]), "SN").schools) == 2


def test_nces_ids_never_take_the_prefix() -> None:
    check_prefix_unused(pl.Series(["A0000001", "00000033", None]), "SN", "PSS file")
    with pytest.raises(SupplementError, match="uses the supplement id prefix"):
        check_prefix_unused(pl.Series(["A0000001", "SN123456"]), "SN", "PSS file")


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("St. Ann Catholic School", "ST ANN CATHOLIC SCHOOL", True),
        ("Saint Ann School", "ST ANN CATHOLIC SCHOOL", True),
        ("St. Ann Catholic School", "ST ANNE ELEMENTARY SCHOOL", False),
        ("Bishop Ward High School", "BISHOP WARD HIGH SCHOOL", True),
        ("Holy Trinity Catholic School", "HOLY TRINITY CATHOLIC SCHOOL", True),
        ("Holy Trinity Catholic School", "HOLY SPIRIT SCHOOL", False),
        ("Curé of Ars Catholic School", "CURE OF ARS CATHOLIC SCHOOL", True),
        ("St. Mary's School", "ST MARYS SCHOOL", True),
        # NCES's longer formal name, its initials aside.
        ("Powers Catholic High School", "LUKE M POWERS CATHOLIC HIGH SCHOOL", True),
        ("St. Mary's Elementary School", "ST MARYS COLGAN ELEMENTARY AND JR/SR HIGH SCHOOL", True),
        # A one-letter typo in a long word (NCES's "GERTUDE").
        ("St. Gertrude School", "ST GERTUDE CATHOLIC SCHOOL", True),
        # Short words are not stretched: Mark is not Mary, Ann is not Anne.
        ("St. Mark School", "ST MARY SCHOOL", False),
        ("Holy Family School", "HOLY CROSS SCHOOL", False),
    ],
)
def test_same_name(a: str, b: str, same: bool) -> None:
    assert same_name(a, b) is same
    assert same_name(b, a) is same


@pytest.mark.parametrize(
    ("a", "b", "town", "same"),
    [
        ("ST MARY ELEMENTARY SCHOOL", "ST MARY SCHOOL", "ALEXANDRIA", True),
        ("Faith Christian School", "FAITH CHRISTIAN ACADEMY", "ROANOKE", True),
        # The town's own words are set aside: York High School is not a York Montessori.
        ("THE MONTESSORI CHILDREN'S HOUSE OF YORK", "York High School", "YORK", False),
        (
            "TRINITY CHRISTIAN SCHOOL OF FAYETTEVILLE",
            "FAYETTEVILLE CHRISTIAN SCHOOL",
            "FAYETTEVILLE",
            False,
        ),
        ("St. Mary's School", "ST MARYS COLGAN SCHOOL", "PITTSBURG", False),
    ],
)
def test_same_words(a: str, b: str, town: str, same: bool) -> None:
    assert same_words(a, b, frozenset([town])) is same


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("1505 West Court St.", "1505 W CT ST"),
        ("6520 State Road YY", "6520 HWY YY"),
        ("301 E. 9th Street", "301 E 9TH ST"),
        ("100 North Main Avenue", "100 N MAIN AVE"),
    ],
)
def test_street_key_reads_one_address_one_way(a: str, b: str) -> None:
    assert street_key(a) == street_key(b) is not None


def test_street_key_needs_a_house_number() -> None:
    assert street_key("PO Box 12") is None
    assert street_key(None) is None
    assert street_key("1505 W CT ST") != street_key("1507 W CT ST")


def test_distance_and_school_year() -> None:
    assert meters_between(39.0, -94.6, 39.0, -94.6) == 0
    assert 1_100 < meters_between(39.0, -94.6, 39.01, -94.6) < 1_120
    assert school_year_of(date(2026, 10, 14)) == "2026-2027"
    assert school_year_of(date(2026, 7, 31)) == "2025-2026"
    assert school_year_start(date(2026, 7, 31)) == date(2025, 8, 1)
    assert school_year_start(date(2026, 8, 1)) == date(2026, 8, 1)


def _paths(tmp_path: Path) -> BuildPaths:
    return BuildPaths(
        cache_dir=tmp_path / "cache",
        out_dir=tmp_path / "site-data",
        internal_dir=tmp_path / "internal",
        work_dir=tmp_path / "work",
    )


def _build(config: DirectoryConfig, out: Path, server: "FixtureServer") -> BuildResult:
    return build(
        config,
        _paths(out),
        client_factory=server.client,
        log=lambda _message: None,
        now=lambda: datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
    )


def test_build_merges_the_supplement(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    plain = _build(fixture_config, tmp_path / "plain", server)
    kept = pl.read_parquet(plain.internal_dir / "schools.parquet")
    private = kept.filter(pl.col("kind") == "private").row(0, named=True)
    public = kept.filter(pl.col("kind") == "public").row(0, named=True)
    dropped_private = pl.read_parquet(plain.internal_dir / "dropped.parquet").filter(
        pl.col("kind") == "private"
    )
    ppin = dropped_private["id"][0]
    entries = [
        entry(id="SN000001"),
        # The same school as a kept NCES one, 300 m away: NCES lists it.
        entry(
            id="SN000002",
            name=str(private["name"]),
            state=private["state"],
            county_fips=private["county_fips"],
            lat=round(private["lat"] + 0.0027, 6),
            lon=round(private["lon"], 6),
        ),
        # An earlier PSS school whose id the current NCES files hold, dropped there.
        entry(
            id="SN000003",
            name="Synthetic Former Survey School",
            lat=33.5,
            source="pss-2019-20",
            nces_ppin=ppin,
        ),
        # A public school's name nearby is another school: CCD lists no private ones.
        # Grades 7 to 12 are secondary, as PSS labels them. Its evidence, a closings
        # row from December, turns a year old within 60 days of the build.
        entry(
            id="SN000005",
            grade_low="07",
            grade_high="12",
            evidence_url=None,
            evidence_station="synthetic-station",
            evidence_seen_on="2025-12-01",
            name=str(public["name"]),
            state=public["state"],
            county_fips=public["county_fips"],
            lat=round(public["lat"] + 0.0027, 6),
            lon=round(public["lon"], 6),
        ),
        entry(
            id="SN000004",
            name="Synthetic Far North School",
            state="AK",
            county_fips="02020",
            lat=61.2,
            lon=-149.9,
        ),
        # Checked more than a year before the build (2026-10-14): left off until
        # rechecked, even though it stands a reviewer's ruling short (it is next to
        # the kept NCES private school): a dropped entry needs none.
        entry(
            id="SN000006",
            name="Synthetic Long Ago Academy",
            state=private["state"],
            county_fips=private["county_fips"],
            lat=round(private["lat"] + 0.0009, 6),
            lon=round(private["lon"], 6),
            checked_on="2025-10-13",
            address_checked_on="2025-10-13",
        ),
        # Its address last matched before this school year began: it may have moved.
        entry(
            id="SN000007",
            name="Synthetic Moved Academy",
            lat=34.5,
            address_checked_on="2026-07-31",
        ),
    ]
    path = write(tmp_path / "supplement.yaml", entries)
    config = fixture_config.model_copy(
        update={
            "supplement": SupplementSettings(
                path=str(path), id_prefix="SN", max_evidence_age_days=365
            )
        }
    )
    result = _build(config, tmp_path / "with", server)

    meta = json.loads((result.site_dir / "meta.json").read_bytes())
    plain_meta = json.loads((plain.site_dir / "meta.json").read_bytes())
    assert meta["ids"] == [*plain_meta["ids"], "SN000001", "SN000005"]
    assert meta["names"][-2] == "SYNTHETIC ST. ANN CATHOLIC SCHOOL"
    assert meta["school_years"] == plain_meta["school_years"]
    decoded = points.decode((result.site_dir / "points.bin").read_bytes())
    assert decoded.lat_e6.tolist()[-2] == 32_366_800
    assert decoded.district.tolist()[-2] == points.NO_DISTRICT

    table = pl.read_parquet(result.internal_dir / "schools.parquet")
    row = table.filter(pl.col("id") == "SN000001").row(0, named=True)
    assert (row["kind"], row["kind_flags"], row["county_fips"]) == ("private", 1, "01101")
    assert (row["grade_low"], row["grade_high"], row["level"]) == ("PK", "08", "Elementary")
    assert row["school_year"] == "2026-2027"
    assert row["enrollment"] is None

    report = result.report
    supplement = report["supplement"]
    assert (supplement["source_rows"], supplement["kept"]) == (7, 2)
    assert supplement["dropped"] == {
        "no_coordinates": 0,
        "outside_continental_us": 1,
        "coordinates_outside_continental_bounds": 0,
        "listed_by_nces": 2,
        "evidence_stale": 1,
        "address_stale": 1,
    }
    assert supplement["listed_by_nces"] == {"SN000002": private["id"], "SN000003": ppin}
    assert supplement["oldest_evidence_on"] == "2025-10-13"
    assert supplement["oldest_address_checked_on"] == "2025-10-13"
    assert supplement["kept_by_address_source"] == {"diocese-list": 2}
    assert supplement["max_evidence_age_days"] == 365
    assert supplement["expiring"] == [
        {
            "id": "SN000005",
            "name": str(public["name"]).upper(),
            "what": "evidence",
            "expires_on": "2026-12-02",
        }
    ]
    assert (
        f"supplement entry SN000005 {str(public['name']).upper()}: its evidence goes stale "
        "on 2026-12-02; check it again before then"
    ) in summary_lines(result)
    assert supplement["by_state"]["AK"] == {
        "source_rows": 1,
        "kept": 0,
        "dropped": {"outside_continental_us": 1},
    }
    assert sum(state["kept"] for state in supplement["by_state"].values()) == 2
    assert supplement["kept_by_source"] == {"diocese-list": 2}
    assert report["schools_on_map"]["private_from_supplement"] == 2
    assert report["schools_on_map"]["private"] == plain.report["schools_on_map"]["private"] + 2
    dropped = pl.read_parquet(result.internal_dir / "dropped.parquet")
    assert sorted(dropped.filter(pl.col("id").str.starts_with("SN"))["id"]) == [
        "SN000002",
        "SN000003",
        "SN000004",
        "SN000006",
        "SN000007",
    ]
    secondary = table.filter(pl.col("id") == "SN000005").row(0, named=True)
    assert secondary["level"] == "Secondary"
    _check_report_markdown(result, str(private["id"]))
    manifest = json.loads((result.site_dir / "manifest.internal.json").read_bytes())
    assert manifest["supplement"]["entries"] == 7
    assert manifest["supplement"]["id_prefix"] == "SN"


def _check_report_markdown(result: BuildResult, private_id: str) -> None:
    markdown = (result.internal_dir / "build_report.md").read_text()
    assert "| Supplement schools (private) | 7 | 2 | 5 |" in markdown
    assert "| supplement | `evidence_stale` | 1 |" in markdown
    assert "| supplement | `address_stale` | 1 |" in markdown
    assert f"  - SN000002 is NCES {private_id}" in markdown
    assert "Oldest evidence that an entry operates: 2025-10-13" in markdown
    assert "street address against a current source: 2025-10-13" in markdown
    assert "| supplement | `listed_by_nces` | 2 |" in markdown
    assert "| diocese-list | 2 |" in markdown
    assert "goes stale within 60 days: 1 (check each again before the date):" in markdown
    assert "evidence goes stale on 2026-12-02" in markdown


def test_bad_supplement_stops_the_build(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    path = write(tmp_path / "supplement.yaml", [entry(id="SN1")])
    config = fixture_config.model_copy(
        update={
            "supplement": SupplementSettings(
                path=str(path), id_prefix="SN", max_evidence_age_days=365
            )
        }
    )
    with pytest.raises(SupplementError, match="six digits"):
        _build(config, tmp_path / "bad", server)


def _kept_row(result: BuildResult, kind: str) -> dict[str, Any]:
    kept = pl.read_parquet(result.internal_dir / "schools.parquet")
    return kept.filter(pl.col("kind") == kind).row(0, named=True)


def _with(fixture_config: DirectoryConfig, path: Path) -> DirectoryConfig:
    settings = SupplementSettings(path=str(path), id_prefix="SN", max_evidence_age_days=365)
    return fixture_config.model_copy(update={"supplement": settings})


def test_a_nearby_nces_school_needs_a_ruling(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    plain = _build(fixture_config, tmp_path / "plain", server)
    private, public = _kept_row(plain, "private"), _kept_row(plain, "public")
    place = {"state": private["state"], "county_fips": private["county_fips"]}
    # Another name, 100 m from a kept NCES private school: the build cannot tell.
    near = entry(
        name="Synthetic Unrelated Academy",
        lat=round(private["lat"] + 0.0009, 6),
        lon=round(private["lon"], 6),
        **place,
    )
    path = write(tmp_path / "near.yaml", [near])
    with pytest.raises(SupplementError, match=f"NCES {private['id']} private .* m away"):
        _build(_with(fixture_config, path), tmp_path / "near", server)
    # A reviewer rules it another school: merged, and the report counts the ruling.
    path = write(tmp_path / "ruled.yaml", [{**near, "distinct_from": [private["id"]]}])
    ruled = _build(_with(fixture_config, path), tmp_path / "ruled", server)
    assert ruled.report["supplement"]["kept"] == 1
    assert ruled.report["supplement"]["near_nces_cleared"] == 1
    # The same street address, whatever the name and however far the geocodes.
    same_address = entry(
        name="Synthetic Renamed Academy",
        street=str(private["street"]),
        zip=private["zip"],
        lat=round(private["lat"] + 0.009, 6),
        lon=round(private["lon"], 6),
        **place,
    )
    path = write(tmp_path / "address.yaml", [same_address])
    with pytest.raises(SupplementError, match="at the same address"):
        _build(_with(fixture_config, path), tmp_path / "address", server)
    # A campus of an NCES school 2 km away: its name holds the NCES school's.
    campus = entry(
        name=f"{private['name']} - Synthetic Campus",
        lat=round(private["lat"] + 0.018, 6),
        lon=round(private["lon"], 6),
        **place,
    )
    path = write(tmp_path / "campus.yaml", [campus])
    with pytest.raises(SupplementError, match="shares its name"):
        _build(_with(fixture_config, path), tmp_path / "campus", server)
    # A public school within 150 m.
    by_public = entry(
        name="Synthetic Parish Academy",
        state=public["state"],
        county_fips=public["county_fips"],
        lat=round(public["lat"] + 0.0009, 6),
        lon=round(public["lon"], 6),
    )
    path = write(tmp_path / "public.yaml", [by_public])
    with pytest.raises(SupplementError, match=f"NCES {public['id']} public"):
        _build(_with(fixture_config, path), tmp_path / "public", server)


def test_closings_evidence_naming_a_school_elsewhere_is_refused(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    plain = _build(fixture_config, tmp_path / "plain", server)
    private = _kept_row(plain, "private")
    other = ("AL", "01101") if private["state"] != "AL" else ("GA", "13121")
    twin = entry(
        name=str(private["name"]),
        city=str(private["city"]),
        state=other[0],
        county_fips=other[1],
        source="pss-2021-22",
        nces_ppin="A0000001",
        evidence_url=None,
        evidence_station="synthetic-station",
        evidence_seen_on="2026-01-28",
    )
    path = write(tmp_path / "twin.yaml", [twin])
    with pytest.raises(SupplementError, match="its only evidence is a closings row"):
        _build(_with(fixture_config, path), tmp_path / "twin", server)
    # A current page of its own settles it.
    path = write(tmp_path / "page.yaml", [{**twin, "evidence_url": "https://example.org/x"}])
    assert (
        _build(_with(fixture_config, path), tmp_path / "page", server).report["supplement"]["kept"]
        == 1
    )

"""The directory's edition (its stamp kept while its content is unchanged) and school zones."""

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]
from hypothesis import example, given, settings
from hypothesis import strategies as st

from snowlight.cli import main
from snowlight.directory import build as build_module
from snowlight.directory import cli as cli_module
from snowlight.directory.build import (
    MAX_DAYS_AHEAD,
    BuildError,
    BuildPaths,
    BuildResult,
    ZoneSource,
    build,
    choose_generated_on,
    read_edition,
)
from snowlight.directory.cli import REFUSED
from snowlight.directory.config import DirectoryConfig
from snowlight.directory.zones import (
    EDITION_KEYS,
    MIN_KNOWN_SHARE,
    ZONE_OVERRIDES,
    ZONES_FILE,
    ZoneError,
    ZoneTableError,
    check_coverage,
    override_for,
    read_zones_edition,
    school_zones,
    write_school_zones,
    zone_counts,
)
from snowlight.output import dumps_json
from snowlight.schemas.directory import DirectoryEdition, written_digest
from snowlight.schemas.site import validate_site

if TYPE_CHECKING:
    from directory.conftest import FixtureServer

pytestmark = pytest.mark.usefixtures("tippecanoe_or_stand_in")

DAY_ONE = datetime(2026, 9, 24, 23, 0, tzinfo=UTC)
DAY_TWO = datetime(2026, 10, 13, 6, 0, tzinfo=UTC)
CENTRAL = "America/Chicago"
EASTERN = "America/New_York"


def _paths(root: Path) -> BuildPaths:
    return BuildPaths(
        cache_dir=root.parent / "cache",
        out_dir=root / "site-data",
        internal_dir=root / "internal",
        work_dir=root / "work",
    )


def _build(  # noqa: PLR0913 - one build, as each test varies it
    config: DirectoryConfig,
    root: Path,
    server: "FixtureServer",
    now: datetime,
    *,
    previous: DirectoryEdition | None = None,
    zones: ZoneSource | None = None,
    write_tiles: bool = False,
) -> BuildResult:
    return build(
        config,
        _paths(root),
        client_factory=server.client,
        log=lambda _message: None,
        now=lambda: now,
        previous=previous,
        zones=zones,
        write_tiles=write_tiles,
    )


def _bytes(result: BuildResult, name: str) -> bytes:
    return (result.site_dir / name).read_bytes()


def _edition(result: BuildResult) -> DirectoryEdition:
    return DirectoryEdition.from_json_bytes(_bytes(result, "edition.json"))


def test_the_edition_names_the_meta_beside_it(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    result = _build(fixture_config, tmp_path / "a", server, DAY_ONE)
    meta_bytes = _bytes(result, "meta.json")
    meta = json.loads(meta_bytes)
    edition = _edition(result)
    assert edition.generated_on == date(2026, 9, 24)
    assert (edition.schools, edition.districts) == (17, len(meta["districts"]["ids"]))
    points_bytes = _bytes(result, "points.bin")
    # The digest is the file's own bytes with the date's text emptied, then points.bin,
    # and the meta.json written with an empty date gives those bytes.
    blanked = meta_bytes.replace(b'"generated_on":"2026-09-24"', b'"generated_on":""')
    assert hashlib.sha256(blanked + points_bytes).hexdigest() == edition.content_sha256
    assert dumps_json({**meta, "generated_on": ""}) == blanked
    assert _bytes(result, "edition.json") == edition.to_json_bytes()
    assert result.report["edition"]["date_from"] == "no edition was deployed before: the build date"
    manifest = json.loads(_bytes(result, "manifest.internal.json"))
    assert (
        manifest["outputs"]["edition.json"]["sha256"]
        == hashlib.sha256(_bytes(result, "edition.json")).hexdigest()
    )
    report = validate_site(result.site_dir.parent)
    assert report.problems == []
    assert "schools/edition.json" in report.checked


def test_unchanged_content_keeps_the_deployed_date(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    """T13a: a later build of the same inputs, told the deployed edition, is byte-identical."""
    first = _build(fixture_config, tmp_path / "a", server, DAY_ONE)
    deployed = read_edition(first.site_dir / "edition.json")
    second = _build(fixture_config, tmp_path / "b", server, DAY_TWO, previous=deployed)
    for name in ("meta.json", "edition.json", "points.bin"):
        assert _bytes(second, name) == _bytes(first, name), name
    assert second.report["edition"]["date_from"] == "the content is unchanged: its date"
    # Without the deployed edition the same build takes its own date.
    alone = _build(fixture_config, tmp_path / "c", server, DAY_TWO)
    assert _edition(alone).generated_on == date(2026, 10, 13)
    assert _edition(alone).content_sha256 == _edition(first).content_sha256


@pytest.mark.parametrize("change", ["drop a school", "rename a school"])
def test_changed_content_takes_the_build_date(
    fixture_config: DirectoryConfig,
    tmp_path: Path,
    server: "FixtureServer",
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    """T13b: any change to the schools gives a new digest and the build's date."""
    first = _build(fixture_config, tmp_path / "a", server, DAY_ONE)
    deployed = read_edition(first.site_dir / "edition.json")
    if change == "drop a school":
        order = build_module.order_schools

        def fewer(kept: pl.DataFrame, districts: pl.DataFrame) -> pl.DataFrame:
            return order(kept.filter(pl.col("id") != "010000500870"), districts)

        monkeypatch.setattr(build_module, "order_schools", fewer)
    else:
        document = build_module.meta_document

        def renamed(*args: Any) -> dict[str, Any]:
            meta = document(*args)
            meta["names"][0] = "Albertville Middle School Annex"
            return meta

        monkeypatch.setattr(build_module, "meta_document", renamed)
    second = _build(fixture_config, tmp_path / "b", server, DAY_TWO, previous=deployed)
    edition = _edition(second)
    assert edition.generated_on == date(2026, 10, 13)
    assert edition.content_sha256 != _edition(first).content_sha256
    assert json.loads(_bytes(second, "meta.json"))["generated_on"] == "2026-10-13"
    assert second.report["edition"]["date_from"] == "the content changed: the build date"
    if change == "rename a school":
        assert (edition.schools, edition.districts) == (
            _edition(first).schools,
            _edition(first).districts,
        )


def _edition_of(digest: str, day: date, schools: int = 17, districts: int = 9) -> DirectoryEdition:
    return DirectoryEdition(
        schema_version=1,
        generated_on=day,
        schools=schools,
        districts=districts,
        content_sha256=digest,
    )


def test_choose_generated_on() -> None:
    digest, other = "a" * 64, "b" * 64
    today = date(2026, 10, 13)

    def chosen(previous: DirectoryEdition | None, schools: int = 17) -> str:
        return choose_generated_on(digest, schools, 9, today, previous).generated_on

    # The same content keeps its date, even one already moved past the build day.
    assert chosen(_edition_of(digest, date(2026, 9, 24))) == "2026-09-24"
    assert chosen(_edition_of(digest, today)) == "2026-10-13"
    assert chosen(_edition_of(digest, date(2026, 10, 15))) == "2026-10-15"
    # Other content, or no edition, takes the build date.
    assert chosen(None) == "2026-10-13"
    assert chosen(_edition_of(other, date(2026, 9, 24))) == "2026-10-13"
    assert chosen(_edition_of(digest, date(2026, 9, 24), schools=16)) == "2026-10-13"
    assert chosen(_edition_of(digest, date(2026, 9, 24), districts=8)) == "2026-10-13"
    # Other content on a day already used moves on, so no stamp names two contents,
    # whatever the counts.
    assert chosen(_edition_of(other, today)) == "2026-10-14"
    assert chosen(_edition_of(other, today, schools=16)) == "2026-10-14"
    assert chosen(_edition_of(other, date(2026, 10, 14))) == "2026-10-15"
    # Changed content after an edition dated far ahead is refused: the build date would
    # move the stamp backwards, to a date that may name other content.
    far = date(2026, 11, 14)
    assert chosen(_edition_of(other, today + MAX_DAYS_AHEAD)) == "2026-11-14"
    with pytest.raises(BuildError, match="more than 31 days after 2026-10-13"):
        chosen(_edition_of(other, far))
    # The same content keeps even that date: it names nothing else.
    assert chosen(_edition_of(digest, far)) == "2026-11-14"


@settings(max_examples=200, deadline=None)
@given(
    steps=st.lists(
        st.tuples(st.integers(min_value=0, max_value=3), st.integers(min_value=0, max_value=4)),
        min_size=1,
        max_size=40,
    )
)
# Changes on one day, each moving the date a day on, until the 31-day refusal.
@example(steps=[(0, i % 2) for i in range(34)])
def test_a_stamp_never_names_two_contents(steps: list[tuple[int, int]]) -> None:
    """Deploys read in order: each step waits some days, then deploys some content.

    Whatever the order, no stamp ever names two contents, and the date of the
    deployed directory never moves backwards. A build is refused only when the
    content changed and the deployed date is more than MAX_DAYS_AHEAD after the
    build day; nothing deploys then, and the sequence ends.
    """
    day = date(2026, 10, 13)
    deployed: DirectoryEdition | None = None
    named: dict[str, str] = {}
    for wait, content in steps:
        day = day.fromordinal(day.toordinal() + wait)
        digest = f"{content:064x}"
        try:
            chosen = choose_generated_on(digest, 17, 9, day, deployed).generated_on
        except BuildError:
            assert deployed is not None
            assert deployed.content_sha256 != digest
            assert deployed.generated_on > day + MAX_DAYS_AHEAD
            return
        assert named.setdefault(chosen, digest) == digest, (chosen, named)
        if deployed is not None:
            assert chosen >= deployed.generated_on.isoformat()
        deployed = _edition_of(digest, date.fromisoformat(chosen))


def test_a_second_change_on_one_day_never_reuses_a_stamp(
    fixture_config: DirectoryConfig,
    tmp_path: Path,
    server: "FixtureServer",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Risk R6: two directory changes deployed on one day get two stamps."""
    first = _build(fixture_config, tmp_path / "a", server, DAY_TWO)
    document = build_module.meta_document

    def renamed(*args: Any) -> dict[str, Any]:
        meta = document(*args)
        meta["names"][0] = "Albertville Middle School Annex"
        return meta

    monkeypatch.setattr(build_module, "meta_document", renamed)
    deployed = read_edition(first.site_dir / "edition.json")
    second = _build(fixture_config, tmp_path / "b", server, DAY_TWO, previous=deployed)
    assert _edition(first).stamp() != _edition(second).stamp()
    assert _edition(second).generated_on == date(2026, 10, 14)
    # Redeployed the same day, the second content keeps its stamp.
    again = _build(fixture_config, tmp_path / "c", server, DAY_TWO, previous=_edition(second))
    assert _bytes(again, "edition.json") == _bytes(second, "edition.json")
    assert _bytes(again, "meta.json") == _bytes(second, "meta.json")


def test_a_missing_or_bad_previous_edition_stops_the_build(tmp_path: Path) -> None:
    """Dated without the deployed edition, changed content could reuse a stamp."""
    with pytest.raises(BuildError, match=r"absent\.json"):
        read_edition(tmp_path / "absent.json")
    for name, body in (
        ("empty.json", b""),
        ("page.json", b"<!doctype html><title>Not found</title>"),
        ("wrong.json", b'{"generated_on":"2026-09-24","schools":17}'),
    ):
        (tmp_path / name).write_bytes(body)
        with pytest.raises(BuildError, match="not an edition"):
            read_edition(tmp_path / name)
    good = _edition_of("c" * 64, date(2026, 9, 24))
    (tmp_path / "good.json").write_bytes(good.to_json_bytes())
    assert read_edition(tmp_path / "good.json") == good


def test_a_changed_district_or_kind_changes_the_digest(
    fixture_config: DirectoryConfig,
    tmp_path: Path,
    server: "FixtureServer",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """points.bin's district index and kind flags are content: meta.json alone misses them."""
    first = _build(fixture_config, tmp_path / "a", server, DAY_ONE)
    deployed = read_edition(first.site_dir / "edition.json")
    encode = build_module._encode_points

    def moved(schools: pl.DataFrame, district_count: int) -> bytes:
        districts = schools["district_index"].to_list()
        other = next(d for d in districts if d is not None and d != districts[0])
        changed = schools.with_columns(
            pl.Series(
                "district_index", [other, *districts[1:]], dtype=schools["district_index"].dtype
            ),
            (pl.col("kind_flags") ^ 2).alias("kind_flags"),
        )
        return encode(changed, district_count)

    monkeypatch.setattr(build_module, "_encode_points", moved)
    second = _build(fixture_config, tmp_path / "b", server, DAY_TWO, previous=deployed)
    blank = b'"generated_on":""'
    first_meta = _bytes(first, "meta.json").replace(b'"generated_on":"2026-09-24"', blank)
    second_meta = _bytes(second, "meta.json").replace(b'"generated_on":"2026-10-13"', blank)
    assert first_meta == second_meta
    assert _bytes(first, "points.bin") != _bytes(second, "points.bin")
    assert _edition(second).content_sha256 != deployed.content_sha256
    assert _edition(second).generated_on == date(2026, 10, 13)


def test_the_edition_is_checked_against_the_bytes_written(
    fixture_config: DirectoryConfig,
    tmp_path: Path,
    server: "FixtureServer",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A digest that the written files do not give stops the build before any file is written."""
    written = written_digest

    def dating_disagrees(meta_bytes: bytes, generated_on: str, points_bytes: bytes) -> str:
        # The digest taken to date the directory (of meta.json with an empty date)
        # is not the one the dated file gives.
        return "0" * 64 if generated_on == "" else written(meta_bytes, generated_on, points_bytes)

    monkeypatch.setattr(build_module, "written_digest", dating_disagrees)
    with pytest.raises(BuildError, match="content digest"):
        _build(fixture_config, tmp_path / "a", server, DAY_ONE)
    site = _paths(tmp_path / "a").site_dir
    assert not site.exists() or not any(site.iterdir())


def test_the_date_must_be_written_once() -> None:
    meta: dict[str, Any] = {"generated_on": "2026-09-24", "count": 0, "districts": {"ids": []}}
    dated = b'"generated_on":"2026-09-24"'
    twice = b"{" + dated + b',"x":{' + dated + b"}}"
    blank = twice.replace(dated, b'"generated_on":""')
    digest = hashlib.sha256(blank).hexdigest()
    with pytest.raises(BuildError, match="date is not written once"):
        build_module._edition(meta, twice, b"", digest)
    with pytest.raises(BuildError, match="date is not written once"):
        build_module._edition(meta, b'{"generated_on":""}', b"", digest)


class _ByCounty:
    """A stand-in time zone lookup: Alabama Central, Arizona Mountain, Indiana split.

    Every other state is Eastern; a school with no county has no known zone.
    """

    def zones_for(
        self, county_fips: str | None, lat: float | None, lon: float | None
    ) -> tuple[str, ...]:
        assert lat is not None
        assert lon is not None
        state = (county_fips or "")[:2]
        return {
            "01": (CENTRAL,),
            "04": ("America/Phoenix",),
            "18": (CENTRAL, EASTERN),
        }.get(state, (EASTERN,) if state else ())


def _zone_source(calls: list[date]) -> ZoneSource:
    def source(day: date) -> tuple[_ByCounty, dict[str, Any]]:
        calls.append(day)
        return _ByCounty(), {"county": {"valid_from": "2026-04-16"}}

    return source


def test_school_zones_follow_the_published_order(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    calls: list[date] = []
    result = _build(fixture_config, tmp_path / "a", server, DAY_ONE, zones=_zone_source(calls))
    assert calls == [date(2026, 9, 24)]
    zones = pl.read_parquet(result.internal_dir / ZONES_FILE)
    schools = pl.read_parquet(result.internal_dir / "schools.parquet")
    assert zones.schema == pl.Schema({"index": pl.UInt32(), "zones": pl.List(pl.String())})
    assert zones["index"].to_list() == schools["index"].to_list() == list(range(17))
    lookup = _ByCounty()
    for row, zone_list in zip(schools.iter_rows(named=True), zones["zones"].to_list(), strict=True):
        assert tuple(zone_list) == lookup.zones_for(row["county_fips"], row["lat"], row["lon"])
    counts = result.report["zones"]
    assert counts["schools"] == 17
    assert counts["one_zone"] + counts["several_zones"] + counts["unknown"] == 17
    assert counts["boundaries"] == {"county": {"valid_from": "2026-04-16"}}
    manifest = json.loads(_bytes(result, "manifest.internal.json"))
    assert ZONES_FILE in manifest["internal_outputs"]
    # The table names the directory it indexes into, as its edition does.
    assert read_zones_edition(result.internal_dir / ZONES_FILE) == _edition(result)
    # A build without zones removes the older table: it would index another directory.
    again = _build(fixture_config, tmp_path / "a", server, DAY_TWO)
    assert not (again.internal_dir / ZONES_FILE).exists()
    assert "zones" not in again.report


def _drop_a_school(monkeypatch: pytest.MonkeyPatch) -> None:
    order = build_module.order_schools

    def fewer(kept: pl.DataFrame, districts: pl.DataFrame) -> pl.DataFrame:
        return order(kept.filter(pl.col("id") != "010000500870"), districts)

    monkeypatch.setattr(build_module, "order_schools", fewer)


def _files(result_root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(result_root)): path.read_bytes()
        for path in sorted(result_root.rglob("*"))
        if path.is_file() and path.name != "build_report.md"
    }


def test_a_failed_zone_lookup_writes_nothing(
    fixture_config: DirectoryConfig,
    tmp_path: Path,
    server: "FixtureServer",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lookup comes first: when it fails, the last build's files stay, all of a piece."""
    root = tmp_path / "a"
    first = _build(fixture_config, root, server, DAY_ONE, zones=_zone_source([]))
    before = _files(root)
    _drop_a_school(monkeypatch)
    fetched: list[str] = []
    monkeypatch.setattr(build_module, "fetch_sources", lambda *_args: fetched.append("nces"))

    def failing(_day: date) -> tuple[_ByCounty, dict[str, Any]]:
        raise ZoneError("NWS boundary files: HTTP 503")

    with pytest.raises(ZoneError, match="503"):
        _build(fixture_config, root, server, DAY_TWO, zones=failing)
    assert fetched == []
    assert _files(root) == before
    assert read_zones_edition(first.internal_dir / ZONES_FILE) == _edition(first)


def test_no_zone_table_outlives_its_directory(
    fixture_config: DirectoryConfig,
    tmp_path: Path,
    server: "FixtureServer",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A build that fails after writing a new directory leaves no older table beside it."""
    root = tmp_path / "a"
    _build(fixture_config, root, server, DAY_ONE, zones=_zone_source([]))
    _drop_a_school(monkeypatch)

    def broken(*_args: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(build_module, "write_school_zones", broken)
    with pytest.raises(OSError, match="disk full"):
        _build(fixture_config, root, server, DAY_TWO, zones=_zone_source([]))
    paths = _paths(root)
    assert json.loads((paths.site_dir / "meta.json").read_bytes())["count"] == 16
    assert not (paths.internal_dir / ZONES_FILE).exists()


def test_zone_coverage_has_a_floor(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    """A lookup that knows too few schools is refused, not written as a mostly dark table."""
    rows = 1000
    known = pl.DataFrame(
        {"index": range(rows), "zones": [[CENTRAL]] * (rows - 1) + [[]]},
        schema={"index": pl.UInt32(), "zones": pl.List(pl.String())},
    )
    check_coverage(known)
    assert MIN_KNOWN_SHARE == 0.999
    two_unknown = known.with_columns(
        pl.when(pl.col("index") == 0).then([]).otherwise(pl.col("zones")).alias("zones")
    )
    with pytest.raises(ZoneError, match="998 of 1,000 schools"):
        check_coverage(two_unknown)

    class Nowhere:
        def zones_for(
            self, county_fips: str | None, _lat: float | None, _lon: float | None
        ) -> tuple[str, ...]:
            return (EASTERN,) if (county_fips or "").startswith("01") else ()

    with pytest.raises(ZoneError, match=r"below the 99\.9%"):
        _build(fixture_config, tmp_path / "a", server, DAY_ONE, zones=lambda _day: (Nowhere(), {}))
    assert not _paths(tmp_path / "a").site_dir.exists()


# Schools of Elko (32007) and Humboldt (32013) counties, Nevada, and Wendover, Utah
# (49045), where they stand in the 2024-25 NCES files.
_NEVADA_PLACES = {
    "West Wendover": ("32007", 40.729098, -114.086284),
    "Jackpot": ("32007", 41.982371, -114.668852),
    "Owyhee": ("32007", 41.943123, -116.097321),
    "McDermitt": ("32013", 41.997862, -117.716764),
    "Elko": ("32007", 40.839167, -115.761052),
    "Wells": ("32007", 41.108354, -114.970202),
    "Montello": ("32007", 41.262363, -114.196788),
    "Winnemucca": ("32013", 40.971603, -117.708087),
    "Wendover, Utah": ("49045", 40.737, -114.037),
}


# Schools of Russell (01113), Lee (01081) and Chambers (01017) counties, Alabama,
# and of Muscogee County, Georgia (13215), where they stand in the 2024-25 NCES files.
_ALABAMA_PLACES = {
    "Central High, Phenix City": ("01113", 32.485, -85.0397),
    "Sherwood Elementary, Phenix City": ("01113", 32.493285, -85.003535),
    "Ladonia Elementary": ("01113", 32.46792, -85.083971),
    "Mount Olive Intermediate, Fort Mitchell": ("01113", 32.3585, -85.031762),
    "Russell County High, Seale": ("01113", 32.33355, -85.149941),
    "Smiths Station High": ("01081", 32.521416, -85.080214),
    "Lakewood Elementary, Phenix City": ("01081", 32.511779, -85.032565),
    "Beulah High, Valley": ("01081", 32.711135, -85.188072),
    "Valley High": ("01017", 32.802209, -85.181546),
    "Lanett Senior High": ("01017", 32.856567, -85.197062),
    "W O Lance Elementary, Lanett": ("01017", 32.8674, -85.1959),
    "Auburn High": ("01081", 32.603878, -85.446081),
    "Opelika High": ("01081", 32.668149, -85.369438),
    "Beauregard High, Opelika": ("01081", 32.550019, -85.372559),
    "Lafayette High": ("01017", 32.8994, -85.3965),
    "Columbus, Georgia": ("13215", 32.47, -84.99),
}


class _NwsCodes:
    """The NWS county codes: Nevada Pacific, Utah Mountain, Alabama Central, Georgia Eastern."""

    def zones_for(
        self, county_fips: str | None, lat: float | None, lon: float | None
    ) -> tuple[str, ...]:
        assert lat is not None
        assert lon is not None
        state = (county_fips or "")[:2]
        return {
            "01": (CENTRAL,),
            "13": (EASTERN,),
            "32": ("America/Los_Angeles",),
            "49": ("America/Denver",),
        }[state]


def _zones_of(places: dict[str, tuple[str, float, float]]) -> dict[str, list[str]]:
    names = list(places)
    schools = pl.DataFrame(
        {
            "index": list(range(len(names))),
            "county_fips": [places[name][0] for name in names],
            "lat": [places[name][1] for name in names],
            "lon": [places[name][2] for name in names],
        },
        schema_overrides={"index": pl.UInt32()},
    )
    zones = school_zones(schools, _NwsCodes())["zones"].to_list()
    return dict(zip(names, zones, strict=True))


def test_places_off_their_countys_zone_take_their_own() -> None:
    """West Wendover keeps Mountain time by law; Jackpot, Owyhee and McDermitt by custom.

    NWS codes their counties Pacific. By law the school takes Mountain; by custom
    it takes both, so the ingest withholds a read the two zones would date
    differently. Their neighbors keep the county's zone.
    """
    mountain, both = ["America/Denver"], ["America/Denver", "America/Los_Angeles"]
    assert _zones_of(_NEVADA_PLACES) == {
        "West Wendover": mountain,
        "Jackpot": both,
        "Owyhee": both,
        "McDermitt": both,
        "Elko": ["America/Los_Angeles"],
        "Wells": ["America/Los_Angeles"],
        "Montello": ["America/Los_Angeles"],
        "Winnemucca": ["America/Los_Angeles"],
        "Wendover, Utah": mountain,
    }
    for entry in ZONE_OVERRIDES:
        assert entry.zones == tuple(sorted(entry.zones))
        assert entry.south < entry.north
        assert entry.west < entry.east
        assert entry.why


def test_alabamas_eastern_custom_towns_take_both_zones() -> None:
    """Phenix City, Smiths Station, Valley, Lanett, Fort Mitchell and Seale keep Eastern time.

    By law they are Central, as NWS codes their counties; by custom they keep
    Columbus's and West Point's Eastern time, so each school there takes both
    zones. Auburn, Opelika and LaFayette, farther from the river, keep Central only,
    and Columbus itself keeps Eastern.
    """
    both = [CENTRAL, EASTERN]
    zones = _zones_of(_ALABAMA_PLACES)
    assert zones == {
        **dict.fromkeys(list(_ALABAMA_PLACES)[:11], both),
        "Auburn High": [CENTRAL],
        "Opelika High": [CENTRAL],
        "Beauregard High, Opelika": [CENTRAL],
        "Lafayette High": [CENTRAL],
        "Columbus, Georgia": [EASTERN],
    }


def test_a_place_takes_in_the_edges_of_its_box() -> None:
    for entry in ZONE_OVERRIDES:
        for lat in (entry.south, entry.north):
            for lon in (entry.west, entry.east):
                assert override_for(entry.county_fips, lat, lon) is entry
        assert override_for(entry.county_fips, entry.south - 0.001, entry.west) is None
        assert override_for(entry.county_fips, entry.north, entry.east + 0.001) is None
        assert override_for("99999", entry.south, entry.west) is None
        assert override_for(entry.county_fips, None, entry.west) is None


def test_zone_counts() -> None:
    lookup = _ByCounty()
    frame = pl.DataFrame(
        {
            "index": [0, 1, 2, 3],
            "county_fips": ["01001", "18001", None, "04001"],
            "lat": [33.0, 40.0, 41.0, 34.0],
            "lon": [-86.0, -86.0, -87.0, -111.0],
        },
        schema={
            "index": pl.UInt32(),
            "county_fips": pl.String(),
            "lat": pl.Float64(),
            "lon": pl.Float64(),
        },
    )
    table = school_zones(frame, lookup)
    assert table["zones"].to_list() == [
        [CENTRAL],
        [CENTRAL, EASTERN],
        [],
        ["America/Phoenix"],
    ]
    assert zone_counts(table) == {
        "schools": 4,
        "one_zone": 2,
        "several_zones": 1,
        "unknown": 1,
        "known_share": 0.75,
    }


def test_no_tiles_leaves_every_other_file_byte_identical(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    calls: list[date] = []
    full = _build(
        fixture_config, tmp_path / "a", server, DAY_ONE, zones=_zone_source(calls), write_tiles=True
    )
    lean_root = tmp_path / "b"
    stale = _paths(lean_root).site_dir / "schools.pmtiles"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"an older tileset")
    lean = _build(fixture_config, lean_root, server, DAY_ONE, zones=_zone_source(calls))
    for name in ("meta.json", "points.bin", "edition.json"):
        assert _bytes(lean, name) == _bytes(full, name), name
    for name in ("schools.parquet", "districts.parquet", "dropped.parquet", ZONES_FILE):
        assert (lean.internal_dir / name).read_bytes() == (full.internal_dir / name).read_bytes()
    assert (full.site_dir / "schools.pmtiles").exists()
    assert not stale.exists()
    assert "schools.pmtiles" not in lean.report["outputs"]
    assert "tileset_check" not in lean.report


def _write_config(config: DirectoryConfig, path: Path) -> Path:
    path.write_text(yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    return path


def _cli(config_path: Path, root: Path, *extra: str) -> list[str]:
    paths = _paths(root)
    return [
        "directory",
        "build",
        "--config",
        str(config_path),
        "--cache-dir",
        str(paths.cache_dir),
        "--out-dir",
        str(paths.out_dir),
        "--internal-dir",
        str(paths.internal_dir),
        "--work-dir",
        str(paths.work_dir),
        *extra,
    ]


def test_cli_previous_edition_zones_and_no_tiles(
    fixture_config: DirectoryConfig,
    tmp_path: Path,
    server: "FixtureServer",
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(build_module, "make_client", server.client)
    config_path = _write_config(fixture_config, tmp_path / "directory.yaml")
    # The deploy before this one: the same content, dated earlier.
    first = _build(fixture_config, tmp_path / "deployed", server, DAY_ONE)
    deployed = tmp_path / "edition.json"
    deployed.write_bytes(_bytes(first, "edition.json"))
    zone_days: list[tuple[Path, date]] = []

    def lookup(cache_dir: Path, day: date) -> tuple[_ByCounty, dict[str, Any]]:
        zone_days.append((cache_dir, day))
        return _ByCounty(), {}

    monkeypatch.setattr(cli_module, "nws_zone_lookup", lookup)
    extra = (
        "--previous-edition",
        str(deployed),
        "--zones",
        "--zones-cache-dir",
        "nws",
        "--no-tiles",
    )
    assert main(_cli(config_path, tmp_path / "now", *extra)) == 0
    out = capsys.readouterr()
    assert "dated 2026-09-24: the content is unchanged: its date" in out.out
    assert "time zones: " in out.out
    site = _paths(tmp_path / "now").site_dir
    assert (site / "edition.json").read_bytes() == deployed.read_bytes()
    assert not (site / "schools.pmtiles").exists()
    assert [cache for cache, _day in zone_days] == [Path("nws")]
    # A previous edition that is not there refuses the build: exit 4, never retried.
    missing = ("--previous-edition", str(tmp_path / "absent.json"), "--no-tiles")
    assert main(_cli(config_path, tmp_path / "later", *missing)) == REFUSED == 4
    out = capsys.readouterr()
    assert "snowlight directory build: refused: previous edition" in out.err
    assert not _paths(tmp_path / "later").site_dir.exists()
    # So does a changed directory after an edition dated too far ahead.
    ahead = _edition_of("c" * 64, date(2099, 1, 1))
    deployed.write_bytes(ahead.to_json_bytes())
    previous = ("--previous-edition", str(deployed), "--no-tiles")
    assert main(_cli(config_path, tmp_path / "ahead", *previous)) == REFUSED
    assert "refused: the deployed directory is dated 2099-01-01" in capsys.readouterr().err
    ahead_site = _paths(tmp_path / "ahead").site_dir
    assert not ahead_site.exists() or not any(ahead_site.iterdir())


def test_cli_a_zone_error_fails_the_build(
    fixture_config: DirectoryConfig,
    tmp_path: Path,
    server: "FixtureServer",
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(build_module, "make_client", server.client)
    config_path = _write_config(fixture_config, tmp_path / "directory.yaml")
    root = tmp_path / "now"
    first = _build(fixture_config, root, server, DAY_ONE, zones=_zone_source([]))
    zones_before = (first.internal_dir / ZONES_FILE).read_bytes()

    def lookup(_cache_dir: Path, _day: date) -> tuple[_ByCounty, dict[str, Any]]:
        raise ZoneError("NWS boundary files: weather.gov timed out")

    monkeypatch.setattr(cli_module, "nws_zone_lookup", lookup)
    _drop_a_school(monkeypatch)
    assert main(_cli(config_path, root, "--zones", "--no-tiles")) == 1
    err = capsys.readouterr().err
    assert "snowlight directory build: error: NWS boundary files: weather.gov timed out" in err
    # The older table still sits only beside the directory it was made with.
    assert (first.internal_dir / ZONES_FILE).read_bytes() == zones_before
    assert json.loads(_bytes(first, "meta.json"))["count"] == 17

    # Too few known zones is a refusal the inputs decide: exit 4, never retried.
    class _Nowhere:
        def zones_for(self, *_place: object) -> tuple[str, ...]:
            return ()

    monkeypatch.setattr(cli_module, "nws_zone_lookup", lambda *_args: (_Nowhere(), {}))
    assert main(_cli(config_path, root, "--zones", "--no-tiles")) == REFUSED
    assert "snowlight directory build: refused: time zones are known for 0 of" in (
        capsys.readouterr().err
    )


def test_only_the_tiles_may_be_missing_from_the_outputs(
    fixture_config: DirectoryConfig,
    tmp_path: Path,
    server: "FixtureServer",
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A published file the build failed to write stops it; only --no-tiles leaves one out."""
    write = build_module._write_directory

    def without_edition(site: Path, *args: Any) -> None:
        write(site, *args)
        (site / "edition.json").unlink()

    monkeypatch.setattr(build_module, "_write_directory", without_edition)
    with pytest.raises(FileNotFoundError, match=r"edition\.json"):
        _build(fixture_config, tmp_path / "a", server, DAY_ONE)


def test_a_zone_table_is_written_only_for_its_own_directory(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        {"index": [0], "zones": [[CENTRAL]]},
        schema={"index": pl.UInt32(), "zones": pl.List(pl.String())},
    )
    with pytest.raises(ValueError, match="1 rows for a directory of 17 schools"):
        write_school_zones(frame, tmp_path / ZONES_FILE, _edition_of("a" * 64, date(2026, 9, 24)))
    assert not (tmp_path / ZONES_FILE).exists()


def test_a_zone_table_names_every_field_of_its_edition(tmp_path: Path) -> None:
    """The table carries the whole edition, and a table naming less is refused, not guessed."""
    assert set(EDITION_KEYS) == set(DirectoryEdition.model_fields) - {"schema_version"}
    edition = _edition_of("a" * 64, date(2026, 9, 24))
    frame = pl.DataFrame(
        {"index": list(range(edition.schools)), "zones": [[CENTRAL]] * edition.schools},
        schema={"index": pl.UInt32(), "zones": pl.List(pl.String())},
    )
    target = tmp_path / ZONES_FILE
    write_school_zones(frame, target, edition)
    assert read_zones_edition(target) == edition
    metadata = pl.read_parquet_metadata(target)
    assert metadata["snowlight.directory.districts"] == str(edition.districts)
    for dropped in EDITION_KEYS.values():
        partial = {key: value for key, value in metadata.items() if key in EDITION_KEYS.values()}
        del partial[dropped]
        frame.write_parquet(target, metadata=partial)
        with pytest.raises(ZoneTableError, match=f"does not name its directory: no {dropped}"):
            read_zones_edition(target)
    frame.write_parquet(target, metadata={**metadata, "snowlight.directory.schools": "many"})
    with pytest.raises(ZoneTableError, match="does not name a valid directory edition"):
        read_zones_edition(target)

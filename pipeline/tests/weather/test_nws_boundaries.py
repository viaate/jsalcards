"""Tests for the NWS zone and county boundary releases."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from shapely.geometry import Point

from snowlight.sources.nws.boundaries import (
    NOTE_NAME,
    PAGES,
    RETRY_AFTER,
    BoundaryCatalog,
    BoundaryError,
    BoundaryKind,
    BoundaryRelease,
    NotAskedError,
    parse_releases,
    read_boundary_set,
    ugc_kind,
)
from snowlight.sources.nws.http import (
    ChecksumMismatchError,
    FetchError,
    HttpCache,
    NotFoundError,
    sidecar_path,
)

if TYPE_CHECKING:
    from weather.conftest import Kit

FIXTURES = Path(__file__).parent / "fixtures"
ZONE_PAGE = (FIXTURES / "PublicZones.table.html").read_text()
COUNTY_PAGE = (FIXTURES / "Counties.table.html").read_text()


def test_parses_the_real_release_tables() -> None:
    zones = parse_releases(ZONE_PAGE, "zone", PAGES["zone"])
    assert [(r.valid_from, r.url, r.md5, r.records) for r in zones] == [
        (
            date(2025, 3, 18),
            "https://www.weather.gov/source/gis/Shapefiles/WSOM/z_18mr25.zip",
            "388062c3036e4518d07c9fb09d68ff6f",
            4114,
        ),
        (
            date(2026, 4, 16),
            "https://www.weather.gov/source/gis/Shapefiles/WSOM/z_16ap26.zip",
            "004dc6501dc3d50e7b36652cb9d02bd3",
            4157,
        ),
    ]
    counties = parse_releases(COUNTY_PAGE, "county", PAGES["county"])
    assert [(r.valid_from, r.md5, r.records) for r in counties] == [
        (date(2025, 3, 18), "37feacd979ecdad99550017130023e06", 3359),
        (date(2026, 4, 16), "734d75df3791bdc0cbb29fd6ed75a387", 3352),
    ]
    assert counties[0].as_json()["valid_from"] == "2025-03-18"


def test_incomplete_or_missing_tables_are_errors() -> None:
    with pytest.raises(BoundaryError, match="lacks a valid date or MD5"):
        parse_releases(ZONE_PAGE.replace("388062c3036e4518d07c9fb09d68ff6f", "n/a"), "zone", "p")
    with pytest.raises(BoundaryError, match="no zone release"):
        parse_releases(COUNTY_PAGE, "zone", "p")
    with pytest.raises(BoundaryError, match="share a valid date"):
        parse_releases(ZONE_PAGE.replace("16 April 2026", "18 March 2025"), "zone", "p")
    two_links = ZONE_PAGE.replace(
        ">z_18mr25.zip</a>",
        '>z_18mr25.zip</a><a href="/source/gis/Shapefiles/WSOM/z_01ja20.zip">x</a>',
    )
    with pytest.raises(BoundaryError, match="several release files"):
        parse_releases(two_links, "zone", "p")


def test_ugc_kind() -> None:
    assert ugc_kind("NYZ072") == "zone"
    assert ugc_kind("NMC009") == "county"
    with pytest.raises(ValueError, match="not a UGC"):
        ugc_kind("NY072")


def test_reads_the_real_zone_and_county_slices(kit: "Kit") -> None:
    catalog = kit.catalog()
    zones = catalog.boundaries_for("zone", date(2026, 9, 25))
    counties = catalog.boundaries_for("county", date(2026, 9, 25))
    assert zones is not None
    assert counties is not None
    assert zones.release.url.endswith("/z_16ap26.zip")
    assert {"NCZ204", "NYZ074", "DCZ001", "CTZ002", "FLZ014"} <= set(zones.areas)
    assert zones.county_fips == {}
    assert zones.time_zones["AZZ010"] == ("M",)
    assert zones.time_zones["AZZ014"] == ("Mm",)
    assert counties.county_fips["NMC009"] == "35009"
    assert counties.county_fips["CTC003"] == "09003"
    assert counties.time_zones["FLC045"] == ("CE",)
    # Gulf County, Florida is stored as two records; both are in its geometry.
    assert counties.areas["FLC045"].contains(Point(-85.25, 29.9))
    assert counties.areas["FLC045"].contains(Point(-85.2, 30.15))


def test_record_counts_must_match_the_page(kit: "Kit") -> None:
    catalog = kit.catalog()
    release = catalog.releases("zone")[1]
    loaded = catalog.load(release)
    with pytest.raises(BoundaryError, match="the page lists 4157"):
        read_boundary_set(replace(release, records=4157), loaded.file)
    not_a_shapefile = replace(loaded.file, path=FIXTURES / "alert-types.json")
    with pytest.raises(BoundaryError, match="not a zip"):
        read_boundary_set(release, not_a_shapefile)


def test_catalog_picks_the_release_in_effect(kit: "Kit") -> None:
    catalog = kit.catalog()
    assert catalog.release_for("zone", date(2025, 1, 21)) is None
    assert catalog.boundaries_for("zone", date(2025, 1, 21)) is None
    before = catalog.release_for("zone", date(2026, 4, 15))
    after = catalog.release_for("zone", date(2026, 4, 16))
    assert before is not None
    assert after is not None
    assert (before.valid_from, after.valid_from) == (date(2025, 3, 18), date(2026, 4, 16))
    assert catalog.lookup("LAZ077", date(2025, 1, 21)) == (None, None)
    geometry, boundaries = catalog.lookup("LAZ077", date(2025, 6, 1))
    assert geometry is not None
    assert boundaries is not None
    assert boundaries.release.url.endswith("z_18mr25.zip")
    missing, current = catalog.lookup("LAZ077", date(2026, 9, 25))
    assert missing is None
    assert current is not None
    provenance = catalog.provenance()
    assert provenance["pages"] == {}
    files = provenance["files"]
    assert isinstance(files, list)
    assert len(files) == 2


def test_catalog_reads_the_release_lists_from_the_pages(kit: "Kit") -> None:
    catalog = BoundaryCatalog(kit.cache(), kit.cache_dir)
    assert [r.valid_from for r in catalog.releases("county")] == [
        date(2025, 3, 18),
        date(2026, 4, 16),
    ]
    catalog.releases("county")
    assert kit.server.hits[PAGES["county"]] == 1
    page = kit.cache_dir / "www.weather.gov" / "gis" / "Counties.html"
    assert page.is_file()
    pages = catalog.provenance()["pages"]
    assert isinstance(pages, dict)
    assert set(pages) == {"county"}
    # The fixture slices are not the listed files, so their MD5 sums do not match.
    with pytest.raises(ChecksumMismatchError):
        catalog.load(catalog.releases("county")[0])
    with pytest.raises(BoundaryError, match="unexpected URL"):
        catalog.load(replace(catalog.releases("county")[0], url="https:///../x.zip"))


# --- the start-up with the page blocked (predict-next ON-AIR) ------------------------------------

ZONE_NEWEST = parse_releases(ZONE_PAGE, "zone", PAGES["zone"])[-1].valid_from
COUNTY_NEWEST = parse_releases(COUNTY_PAGE, "county", PAGES["county"])[-1].valid_from
"""The newest release date each fixture page lists."""


def page_path(kit: "Kit", kind: BoundaryKind) -> Path:
    name = "PublicZones.html" if kind == "zone" else "Counties.html"
    return kit.cache_dir / "www.weather.gov" / "gis" / name


def falling_back(
    kit: "Kit", said: list[str], *, ask_first: bool = False, down: list[bool] | None = None
) -> BoundaryCatalog:
    """A catalog as the chance job builds it: two tries, the fallback on. ``down``: while its
    one entry is true, nothing answers at all (a transport error)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if down is not None and down[0]:
            kit.server.hits[str(request.url)] += 1
            raise httpx.ConnectError("nothing answers")
        return kit.server.handler(request)

    cache = HttpCache(
        httpx.Client(transport=httpx.MockTransport(handler)),
        attempts=2,
        sleep=kit.sleeps.append,
        clock=kit.clock,
    )
    return BoundaryCatalog(
        cache, kit.cache_dir, fallback=True, warn=said.append, ask_first=ask_first
    )


def saved_copy(kit: "Kit") -> dict[Path, bytes]:
    """Both pages fetched and saved now; the files and sidecars as they are on disk."""
    fresh = falling_back(kit, [])
    fresh.releases("zone")
    fresh.releases("county")
    assert not fresh.held
    assert fresh.held_pages == {}
    paths = [page_path(kit, "zone"), page_path(kit, "county")]
    return {path: path.read_bytes() for item in paths for path in (item, sidecar_path(item))}


def note_of(kit: "Kit") -> datetime | None:
    path = kit.cache_dir / NOTE_NAME
    if not path.is_file():
        return None
    found = json.loads(path.read_text())
    assert set(found) == {"at"}
    return datetime.fromisoformat(found["at"].replace("Z", "+00:00"))


def test_a_silent_page_uses_the_cached_copy_whatever_its_age(kit: "Kit") -> None:
    saved = saved_copy(kit)
    checked = kit.clock.now
    expected = [r.valid_from for r in parse_releases(ZONE_PAGE, "zone", PAGES["zone"])]
    assert expected[-1] == ZONE_NEWEST
    url = PAGES["zone"]
    kit.clock.now += timedelta(days=30)
    down = [False]

    def twice_503() -> None:
        kit.server.queue(url, 503)
        kit.server.queue(url, 503)

    def nothing_answers() -> None:
        down[0] = True

    def once(status: int) -> Callable[[], None]:
        return lambda: kit.server.queue(url, status)

    silences: dict[str, Callable[[], None]] = {
        "FetchError": twice_503,
        "FetchError (a transport error)": nothing_answers,
        "FetchError (a 403)": once(403),
        "NotFoundError": once(404),
    }
    for name, silence in silences.items():
        kit.clock.now += timedelta(hours=1)  # the note of the case before is no longer fresh
        said: list[str] = []
        catalog = falling_back(kit, said, down=down)
        silence()
        before = kit.server.hits[url]
        assert [r.valid_from for r in catalog.releases("zone")] == expected, name
        assert catalog.releases("zone") == catalog.releases("zone")
        assert kit.server.hits[url] - before == (1 if "403" in name or "Not" in name else 2), name
        down[0] = False
        assert said == [
            f"NWS zone boundaries: the release page did not answer ({name.split(' ')[0]}); "
            f"using the copy checked {checked:%Y-%m-%dT%H:%M:%SZ}"
        ]
        assert catalog.held
        assert catalog.held_pages == {"zone": (checked, ZONE_NEWEST)}
        assert {path: path.read_bytes() for path in saved} == saved, name
        assert note_of(kit) == kit.clock.now
        assert set(catalog.provenance()["pages"]) == {"zone"}  # type: ignore[arg-type]
        # The release in effect comes from the copy's list.
        release = catalog.release_for("zone", date(2026, 9, 25))
        assert release is not None
        assert release.valid_from == ZONE_NEWEST


def test_a_page_that_answers_but_does_not_read_keeps_the_cached_copy(kit: "Kit") -> None:
    saved = saved_copy(kit)
    checked = kit.clock.now
    kit.clock.now += timedelta(days=30)
    for body in (b"<html><body>Maintenance</body></html>", COUNTY_PAGE.encode()):
        (kit.cache_dir / NOTE_NAME).unlink(missing_ok=True)
        kit.server.queue(PAGES["zone"], 200, body, {"Content-Length": str(len(body))})
        said: list[str] = []
        catalog = falling_back(kit, said)
        assert catalog.releases("zone")[-1].valid_from == ZONE_NEWEST
        assert said == [
            "NWS zone boundaries: the release page did not answer (BoundaryError); "
            f"using the copy checked {checked:%Y-%m-%dT%H:%M:%SZ}"
        ]
        # The other page's bytes had replaced the copy and its sidecar: both are back.
        assert {path: path.read_bytes() for path in saved} == saved
        assert catalog.cache.cached(PAGES["zone"], page_path(kit, "zone")) is not None
        assert catalog.held
        assert note_of(kit) == kit.clock.now
    # A saved copy that itself no longer reads is not papered over.
    (kit.cache_dir / NOTE_NAME).unlink()
    path = page_path(kit, "zone")
    record = json.loads(sidecar_path(path).read_text())
    path.write_bytes(b"<html></html>")
    record["sha256"] = hashlib.sha256(b"<html></html>").hexdigest()
    sidecar_path(path).write_text(json.dumps(record))
    kit.server.queue(PAGES["zone"], 403)
    with pytest.raises(BoundaryError, match="no zone release is listed"):
        falling_back(kit, []).releases("zone")


def given(kit: "Kit", said: list[str], md5: str | None = None) -> BoundaryCatalog:
    """A falling-back catalog over the fixture slices' own release lists (the pages list the
    real files' sums, which the slices do not have); ``md5``: the sum the newer zone release
    is listed with."""
    zones = kit.catalog().releases("zone")
    if md5 is not None:
        zones = [zones[0], replace(zones[1], md5=md5)]
    lists: dict[BoundaryKind, list[BoundaryRelease]] = {
        "zone": zones,
        "county": kit.catalog().releases("county"),
    }
    return BoundaryCatalog(
        kit.cache(attempts=2), kit.cache_dir, lists, fallback=True, warn=said.append
    )


def test_a_release_that_cannot_be_downloaded_falls_back_to_the_newest_cached_one(
    kit: "Kit",
) -> None:
    day = date(2026, 9, 25)
    older, newer = kit.catalog().releases("zone")
    assert (older.valid_from, newer.valid_from) == (date(2025, 3, 18), date(2026, 4, 16))
    kit.catalog().load(older)  # the older release is in the cache
    garbage = b"not a zip file"

    def fail_download() -> str | None:
        kit.server.queue(newer.url, 503)
        kit.server.queue(newer.url, 503)
        return None

    def gone() -> str | None:
        kit.server.queue(newer.url, 404)
        return None

    def serve_garbage() -> str | None:
        kit.server.queue(newer.url, 200, garbage, {"Content-Length": str(len(garbage))})
        return hashlib.md5(garbage, usedforsecurity=False).hexdigest()

    cases: dict[str, Callable[[], str | None]] = {
        "FetchError": fail_download,
        "NotFoundError": gone,
        "ChecksumMismatchError": lambda: "0" * 32,
        "BoundaryError": serve_garbage,
    }
    for name, arrange in cases.items():
        kit.clock.now += timedelta(hours=1)
        said: list[str] = []
        catalog = given(kit, said, arrange())
        found = catalog.boundaries_for("zone", day)
        assert found is not None
        assert found.release == older, name
        assert catalog.boundaries_for("zone", day) is found
        assert said == [
            f"NWS zone boundaries: the release of 2026-04-16 could not be had ({name}); "
            "using the cached release of 2025-03-18"
        ]
        assert catalog.held
        assert catalog.held_pages == {}  # the list was not from a saved page
        assert note_of(kit) == kit.clock.now
        # A day the older release covers anyway needs no fallback.
        calm = given(kit, [])
        assert calm.boundaries_for("zone", date(2025, 6, 1)) is not None
        assert not calm.held
        # While the note is fresh, a release that is not cached is not asked for either.
        if name != "BoundaryError":  # (the unreadable file itself is cached)
            quiet: list[str] = []
            before = kit.server.hits[newer.url]
            again = given(kit, quiet, "0" * 32 if "Checksum" in name else None)
            if "Checksum" not in name:
                (kit.cache_dir / "www.weather.gov/source/gis/Shapefiles/WSOM/z_16ap26.zip").unlink(
                    missing_ok=True
                )
            found = again.boundaries_for("zone", day)
            assert found is not None
            assert found.release == older
            assert kit.server.hits[newer.url] == before
            assert quiet == [
                "NWS zone boundaries: the release of 2026-04-16 could not be had "
                "(NotAskedError); using the cached release of 2025-03-18"
            ]
            assert again.held
            assert note_of(kit) == kit.clock.now  # not stamped anew
    # With the service back and the note old, the release in effect is had.
    kit.clock.now += RETRY_AFTER
    back = given(kit, [])
    found = back.boundaries_for("zone", day)
    assert found is not None
    assert found.release == newer
    assert not back.held


def test_no_cached_copy_still_fails(kit: "Kit") -> None:
    said: list[str] = []
    kit.server.queue(PAGES["zone"], 503)
    kit.server.queue(PAGES["zone"], 503)
    catalog = falling_back(kit, said)
    with pytest.raises(FetchError, match="giving up"):
        catalog.releases("zone")
    kit.server.queue(PAGES["county"], 404)
    with pytest.raises(NotFoundError):
        catalog.releases("county")
    body = b"<html></html>"
    kit.server.queue(PAGES["county"], 200, body, {"Content-Length": str(len(body))})
    with pytest.raises(BoundaryError):
        catalog.releases("county")
    assert said == []
    assert not catalog.held
    assert note_of(kit) is None
    # No earlier release in the cache: the release's own error.
    newer = kit.catalog().releases("zone")[1]
    kit.server.queue(newer.url, 404)
    with pytest.raises(NotFoundError):
        given(kit, said).boundaries_for("zone", date(2026, 9, 25))
    # ... and, the service silent a moment ago, it is not asked for and still fails.
    (kit.cache_dir / NOTE_NAME).write_text(
        json.dumps({"at": f"{kit.clock.now:%Y-%m-%dT%H:%M:%SZ}"})
    )
    before = kit.server.hits[newer.url]
    with pytest.raises(NotAskedError):
        given(kit, said).boundaries_for("zone", date(2026, 9, 25))
    assert kit.server.hits[newer.url] == before
    assert said == []


def test_without_fallback_nothing_changes(kit: "Kit") -> None:
    saved = saved_copy(kit)
    kit.clock.now += timedelta(days=30)
    (kit.cache_dir / NOTE_NAME).write_text(
        json.dumps({"at": f"{kit.clock.now:%Y-%m-%dT%H:%M:%SZ}"})
    )
    plain = BoundaryCatalog(kit.cache(attempts=2), kit.cache_dir)
    assert (plain.fallback, plain.held, plain.held_pages) == (False, False, {})
    kit.server.queue(PAGES["zone"], 503)
    kit.server.queue(PAGES["zone"], 503)
    with pytest.raises(FetchError, match="giving up"):
        plain.releases("zone")  # asked though a note is fresh, and not papered over
    assert kit.server.hits[PAGES["zone"]] == 3
    assert [r.valid_from for r in plain.releases("zone")][-1] == ZONE_NEWEST  # asked again
    assert not plain.held
    assert note_of(kit) == kit.clock.now  # the note is neither read nor removed
    assert {path for path in saved if not path.is_file()} == set()
    older, newer = kit.catalog().releases("zone")
    kit.catalog().load(older)
    kit.server.queue(newer.url, 404)
    with pytest.raises(NotFoundError):
        kit.catalog().boundaries_for("zone", date(2026, 9, 25))


def test_a_silent_service_is_asked_once_in_15_minutes(kit: "Kit") -> None:
    saved_copy(kit)
    checked = kit.clock.now
    zone, county = PAGES["zone"], PAGES["county"]
    kit.clock.now += timedelta(days=2)
    del kit.server.files[zone], kit.server.files[county]  # a 404 from now on
    silent = kit.clock.now
    said: list[str] = []
    first = falling_back(kit, said)
    first.releases("zone")
    assert note_of(kit) == silent
    first.releases("county")  # the note is fresh: the second kind is not asked
    assert (kit.server.hits[zone], kit.server.hits[county]) == (2, 1)
    assert said == [
        "NWS zone boundaries: the release page did not answer (NotFoundError); "
        f"using the copy checked {checked:%Y-%m-%dT%H:%M:%SZ}",
        "NWS county boundaries: not asked again (the release page did not answer 0 min ago); "
        f"using the copy checked {checked:%Y-%m-%dT%H:%M:%SZ}",
    ]
    # A second catalog on the folder, 14 minutes on: nothing is asked, and it says so.
    kit.clock.now += timedelta(minutes=14)
    said.clear()
    second = falling_back(kit, said)
    assert second.releases("zone")[-1].valid_from == ZONE_NEWEST
    assert second.releases("county")[-1].valid_from == COUNTY_NEWEST
    assert (kit.server.hits[zone], kit.server.hits[county]) == (2, 1)
    assert said == [
        f"NWS {kind} boundaries: not asked again (the release page did not answer 14 min ago); "
        f"using the copy checked {checked:%Y-%m-%dT%H:%M:%SZ}"
        for kind in ("zone", "county")
    ]
    assert second.held
    assert second.held_pages == {"zone": (checked, ZONE_NEWEST), "county": (checked, COUNTY_NEWEST)}
    assert note_of(kit) == silent  # not stamped anew
    # After 15 minutes it is asked again.
    kit.clock.now = silent + RETRY_AFTER
    third = falling_back(kit, [])
    third.releases("zone")
    assert kit.server.hits[zone] == 3
    assert note_of(kit) == kit.clock.now
    # A note stamped in the future, one 15 minutes old and one that is not JSON: as no note.
    now = kit.clock.now
    stamp = "%Y-%m-%dT%H:%M:%SZ"
    for text in (
        json.dumps({"at": (now + timedelta(seconds=1)).strftime(stamp)}),
        json.dumps({"at": (now - RETRY_AFTER).strftime(stamp)}),
        json.dumps({"at": 7}),
        json.dumps(["at"]),
        "not JSON",
    ):
        (kit.cache_dir / NOTE_NAME).write_text(text)
        before = kit.server.hits[zone]
        falling_back(kit, []).releases("zone")
        assert kit.server.hits[zone] == before + 1, text
        assert note_of(kit) == now


def test_the_long_run_asks_once_for_itself(kit: "Kit") -> None:
    saved_copy(kit)
    checked = kit.clock.now
    zone, county = PAGES["zone"], PAGES["county"]
    kit.clock.now += timedelta(days=2)
    pages = (kit.server.files.pop(zone), kit.server.files.pop(county))  # a 404 from now on
    falling_back(kit, []).releases("zone")
    assert note_of(kit) == kit.clock.now
    said: list[str] = []
    # ask_first on a fresh note: the first kind is asked all the same. Still silent: the note
    # is stamped anew and the second kind is not asked.
    kit.clock.now += timedelta(minutes=5)
    said.clear()
    asking = falling_back(kit, said, ask_first=True)
    before = (kit.server.hits[zone], kit.server.hits[county])
    asking.releases("zone")
    asking.releases("county")
    assert (kit.server.hits[zone], kit.server.hits[county]) == (before[0] + 1, before[1])
    assert note_of(kit) == kit.clock.now
    assert asking.held
    assert asking.held_pages == {"zone": (checked, ZONE_NEWEST), "county": (checked, COUNTY_NEWEST)}
    assert [text.split(":")[1].strip().split(" (")[0] for text in said] == [
        "the release page did not answer",
        "not asked again",
    ]
    # Answering: the note is gone and the second kind is asked as on any day.
    kit.server.files[zone], kit.server.files[county] = pages
    kit.clock.now += timedelta(minutes=5)
    said.clear()
    answered = falling_back(kit, said, ask_first=True)
    before = (kit.server.hits[zone], kit.server.hits[county])
    answered.releases("zone")
    assert note_of(kit) is None  # a page that answers removes the note
    answered.releases("county")
    assert (kit.server.hits[zone], kit.server.hits[county]) == (before[0] + 1, before[1] + 1)
    assert said == []
    assert not answered.held
    assert answered.held_pages == {}
    assert datetime.now(UTC) > checked  # the cache's clock, never the wall clock, stamps a note

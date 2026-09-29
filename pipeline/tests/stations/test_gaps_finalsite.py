"""Finalsite district sites read through their homepages (piece s4d, round 5).

``/fs/pages/<id>/page-pops`` answers HTTP 200 with an empty body for any ID, right,
made up or not a number, so a Finalsite station is read through its homepage: the
adapter reads the page's own ``data-pageid``, the poller follows it to that page's
pops, and :func:`snowlight.sources.stations.fetch.page_check_mismatch` holds every
live read to the address the station's browser check saw the page ask for.

The homepages are real (fixtures/gaps/finalsite/, provenance in PROVENANCE.json): live
ones of 2026-09-28 (Billings, Chickasaw, Baldwin County), Gulf Shores' of 2020 (page
ID 329, not the 1994 of today: a changed ID) and of the 2025 Gulf Coast snow, Volusia's
of 2024-10-14 (an older template holding its pops in the page), Palm Beach's Web
Community Manager page of 2024-10-10, and San Benito's Edlio page of 2025-01-21 (not
a Finalsite page, under errors/). The servers are synthetic (httpx.MockTransport) and
serve those bodies; bodies named ``SYNTHETIC`` are made up here and confined to these
tests.
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from snowlight.sources.stations import fetch, finalsite, finalsite_check, gap_fixtures
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, PoliteClient, Timing
from snowlight.sources.stations.model import HealthStatus, ListingState, ShapeError
from snowlight.sources.stations.registry import StationStatus, load_registry

FOLDER = gap_fixtures.DEFAULT_FOLDER
REGISTRY = load_registry()
NOW = datetime(2026, 9, 28, 23, 0, tzinfo=UTC)

BILLINGS = "https://www.billingsschools.org/"
BILLINGS_POPS = "https://www.billingsschools.org/fs/pages/2465/page-pops"
CHICKASAW = "https://www.chickasawschools.com/"
CHICKASAW_POPS = "https://www.chickasawschools.com/fs/pages/2/page-pops"
GULF_SHORES = "https://www.gsboe.org/"
SAN_BENITO = "https://www.sbcisd.net/"


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


# The adapter on real homepages ------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "page_id"),
    [
        ("finalsite/billings-home-live-20260928.html", "2465"),
        ("finalsite/chickasaw-home-live-20260928.html", "2"),
        ("finalsite/baldwin-home-live-20260928.html", "10398"),
        ("finalsite/gulf-shores-home-20250121.html", "1994"),
        ("finalsite/gulf-shores-home-20201101.html", "329"),
    ],
)
def test_a_homepage_is_followed_to_its_own_page_pops(name: str, page_id: str) -> None:
    listing = finalsite.parse(_body(name))
    assert listing.variant == finalsite.HOMEPAGE
    assert listing.state is ListingState.DEFERRED
    assert listing.rows == ()
    assert listing.follows == (f"/fs/pages/{page_id}/page-pops",)


def test_an_older_template_holds_its_page_pops_in_the_page() -> None:
    listing = finalsite.parse(_body("finalsite/volusia-home-20241014.html"))
    assert listing.variant == finalsite.HOMEPAGE_POPS
    assert listing.state is ListingState.POPULATED
    (row,) = listing.rows
    assert row.name == "Hurricane Milton Update"
    assert row.status.startswith("Dear Volusia County Schools Family")
    assert row.extra["pop_id"] == 14
    assert row.updated_text == "2024-09-06T19:00:00Z"


def test_a_web_community_manager_homepage_is_read_by_its_announcements() -> None:
    listing = finalsite.parse(_body("finalsite/palm-beach-home-20241010.html"))
    assert listing.variant == "schoolwires-important-announcements"
    (row,) = listing.rows
    assert row.name == "The School District of Palm Beach County"
    assert row.status.startswith("Learn more about the storm , including shelter information")


def test_a_page_that_is_not_finalsites_is_refused() -> None:
    body = _body("errors/finalsite-san-benito-home-20250121.html")
    with pytest.raises(ShapeError, match="not a Finalsite page"):
        finalsite.parse(body)


def _billings_with(old: bytes, new: bytes) -> bytes:
    # SYNTHETIC: Billings' real homepage slice with its body tag changed.
    body = _body("finalsite/billings-home-live-20260928.html")
    assert old in body
    return body.replace(old, new)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (b' data-pageid="2465"', b"", "names no data-pageid"),
        (b'data-pageid="2465"', b'data-pageid=""', "names no data-pageid"),
        (b'data-pageid="2465"', b'data-pageid="abc"', "not a number"),
        (b'data-pageid="2465"', b'data-pageid="-2"', "not a number"),
        (b"fsLiveMode ", b"fsComposeMode ", "no fsLiveMode class"),
    ],
)
def test_a_finalsite_page_without_a_usable_page_id_is_refused(
    old: bytes, new: bytes, message: str
) -> None:
    with pytest.raises(ShapeError, match=message):
        finalsite.parse(_billings_with(old, new))


def test_the_page_pops_answers_still_read_as_before() -> None:
    assert finalsite.parse(_body("finalsite/billings-page-pops-live-20260927.html")).variant == (
        finalsite.NONE
    )
    assert finalsite.parse(_body("finalsite/chickasaw-page-pops-live-20260928.html")).state is (
        ListingState.POPULATED
    )
    # The archive's one-character answer for Palm Beach's page pops stays refused.
    with pytest.raises(ShapeError, match="no fsPagePopCollection"):
        finalsite.parse(_body("errors/finalsite-palm-beach-page-pops-20250105.txt"))


@pytest.mark.parametrize(
    "name",
    [
        "finalsite/billings-home-live-20260928.html",
        "finalsite/volusia-home-20241014.html",
        "finalsite/palm-beach-home-20241010.html",
        "finalsite/broward-page-pops-live-20260927.html",
        "finalsite/billings-page-pops-live-20260927.html",
    ],
)
def test_slicing_a_slice_changes_nothing(name: str) -> None:
    body = _body(name)
    assert finalsite.slice_body(body) == body
    assert finalsite.parse(finalsite.slice_body(body)) == finalsite.parse(body)


def test_page_pops_path_takes_only_a_number() -> None:
    assert finalsite.page_pops_path("2465") == "/fs/pages/2465/page-pops"
    for bad in ("", "abc", "12a", "-1", "1234567890"):
        with pytest.raises(ShapeError):
            finalsite.page_pops_path(bad)


# The registry: every station's browser check -----------------------------------------


def test_each_live_homepage_fixture_names_the_page_its_check_saw() -> None:
    for station_id, name in [
        ("finalsite-billings-mt", "finalsite/billings-home-live-20260928.html"),
        ("finalsite-chickasaw-al", "finalsite/chickasaw-home-live-20260928.html"),
        ("finalsite-baldwin-al", "finalsite/baldwin-home-live-20260928.html"),
    ]:
        station = REGISTRY.stations[station_id]
        assert station.page_check is not None
        assert station.page_url is not None
        targets = fetch.follow_targets(station.page_url, finalsite.parse(_body(name)), station)
        assert targets == list(station.page_check.loads)
        assert fetch.page_check_mismatch(station, targets) is None


def test_every_finalsite_station_is_read_through_its_checked_homepage() -> None:
    stations = [s for s in REGISTRY.stations.values() if s.platform == "finalsite"]
    assert len(stations) == 82
    for station in stations:
        assert station.status is StationStatus.ACTIVE
        assert station.data_url is None
        check = station.page_check
        assert check is not None, station.id
        assert check.method == finalsite_check.METHOD
        (address,) = check.loads
        page_id = re.fullmatch(r"https://[^/]+/fs/pages/([0-9]+)/page-pops", address)
        assert page_id is not None, address
        assert f'data-pageid="{page_id.group(1)}"' in check.shows
        assert check.checked_at >= datetime(2026, 9, 28, tzinfo=UTC)


# Live reads, end to end -----------------------------------------------------------------


class _Ticker:
    def __init__(self) -> None:
        self.now = NOW
        self.mono = 0.0

    def clock(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.mono += seconds
        self.now += timedelta(seconds=seconds)


class _Server:
    def __init__(self, served: dict[str, bytes]) -> None:
        self.served = served
        self.seen: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == USER_AGENT
        url = str(request.url)
        self.seen.append(url)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=b"User-agent: *\nDisallow: /cms/\n")
        if url in self.served:
            return httpx.Response(200, content=self.served[url])
        # Finalsite answers any page-pops address, any ID, with an empty 200 (2026-09-28).
        if re.search(r"/fs/pages/[^/]+/page-pops$", request.url.path):
            return httpx.Response(200, content=b"")
        return httpx.Response(404, content=b"not found")


def _read(
    tmp_path: Path, station_id: str, served: dict[str, bytes]
) -> tuple[fetch.RunResult, _Server]:
    server = _Server(served)
    ticker = _Ticker()
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(server), headers={"User-Agent": USER_AGENT}),
        ConditionalStore(tmp_path / "cache"),
        timing=Timing(clock=ticker.clock, monotonic=ticker.monotonic, sleep=ticker.sleep),
    )
    return fetch.run(REGISTRY, client, clock=lambda: NOW, only=[station_id]), server


def test_a_homepage_with_its_checked_id_is_followed_to_an_empty_list(tmp_path: Path) -> None:
    result, server = _read(
        tmp_path,
        "finalsite-billings-mt",
        {BILLINGS: _body("finalsite/billings-home-live-20260928.html")},
    )
    (health,) = result.health
    assert (health.status, health.rows, health.variant) == (
        HealthStatus.EMPTY,
        0,
        finalsite.NONE,
    )
    assert (health.url, health.via_url) == (BILLINGS_POPS, BILLINGS)
    assert [(r.url, r.allowed) for r in health.robots] == [(BILLINGS, True), (BILLINGS_POPS, True)]
    (read,) = result.reads
    assert [(page.url, page.variant, page.follows) for page in read.via] == [
        (BILLINGS, finalsite.HOMEPAGE, BILLINGS_POPS)
    ]
    assert [u for u in server.seen if "/fs/pages/" in u] == [BILLINGS_POPS]


def test_a_homepage_with_its_checked_id_is_followed_to_its_pops(tmp_path: Path) -> None:
    result, _server = _read(
        tmp_path,
        "finalsite-chickasaw-al",
        {
            CHICKASAW: _body("finalsite/chickasaw-home-live-20260928.html"),
            CHICKASAW_POPS: _body("finalsite/chickasaw-page-pops-live-20260928.html"),
        },
    )
    (health,) = result.health
    assert (health.status, health.rows, health.variant) == (HealthStatus.OK, 1, finalsite.POPS)
    assert [row.raw_name for row in result.rows] == ["Parent University - October 3, 2026"]


def test_a_homepage_naming_another_page_id_is_an_error_not_an_empty_list(
    tmp_path: Path,
) -> None:
    # Gulf Shores' real homepage of 2020 (page ID 329) where today's (1994) was checked.
    result, server = _read(
        tmp_path,
        "finalsite-gulf-shores-al",
        {GULF_SHORES: _body("finalsite/gulf-shores-home-20201101.html")},
    )
    (health,) = result.health
    assert health.status is HealthStatus.ERROR
    assert health.rows == 0
    assert health.reason is not None
    assert health.reason.startswith(
        "the page now loads https://www.gsboe.org/fs/pages/329/page-pops, not "
        "https://www.gsboe.org/fs/pages/1994/page-pops (its browser check of 2026-09-28T"
    )
    assert result.rows == []
    assert result.reads == []
    # The empty answer its page pops would have given is never asked for.
    assert not [u for u in server.seen if "/fs/pages/" in u]


def test_a_homepage_that_is_not_finalsites_is_an_error(tmp_path: Path) -> None:
    result, server = _read(
        tmp_path,
        "finalsite-san-benito-tx",
        {SAN_BENITO: _body("errors/finalsite-san-benito-home-20250121.html")},
    )
    (health,) = result.health
    assert health.status is HealthStatus.ERROR
    assert (health.reason or "").startswith("unrecognized shape: not a Finalsite page")
    assert not [u for u in server.seen if "/fs/pages/" in u]


def test_an_empty_homepage_is_an_error_not_an_empty_list(tmp_path: Path) -> None:
    # SYNTHETIC: the homepage answers 200 with an empty body, as the page pops of any ID do.
    result, _server = _read(tmp_path, "finalsite-billings-mt", {BILLINGS: b""})
    (health,) = result.health
    assert health.status is HealthStatus.ERROR
    assert (health.reason or "").startswith("the page names no list file to follow")
    assert "finalsite-no-page-pops" in (health.reason or "")


def test_the_check_leaves_stations_polled_at_a_data_file_alone() -> None:
    # Every station of every part with a data URL, or without a browser check of the
    # page it is polled at, is read as before, whatever its page names.
    affected = {
        s.id
        for s in REGISTRY.stations.values()
        if fetch.page_check_mismatch(s, ["https://example.invalid/other"]) is not None
    }
    polled_at_a_checked_page = {
        s.id
        for s in REGISTRY.stations.values()
        if s.data_url is None and s.page_check is not None and s.page_check.loads
    }
    assert affected == polled_at_a_checked_page
    # On 2026-09-28 those are exactly this part's 82 Finalsite stations.
    finalsite_ids = {s.id for s in REGISTRY.stations.values() if s.platform == "finalsite"}
    assert finalsite_ids <= affected
    kulr = REGISTRY.stations["cowles-kulr"]
    assert kulr.data_url is not None
    assert fetch.page_check_mismatch(kulr, []) is None

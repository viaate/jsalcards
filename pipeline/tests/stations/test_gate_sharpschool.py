"""SharpSchool district homepages: the alert service read by POST, and the older homepage forms.

The fixtures under ``fixtures/gate/sharpschool/`` are real bodies (archived Wayback
captures of the Lee and Marion homepages, and Lee's live answer to the alert
service), with their provenance in ``fixtures/gate/PROVENANCE.json``. The alert
answers with alerts in them, the registries and the HTTP servers built here are
synthetic (every URL is under .test), since no district had an alert up when the
service was read.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]

from snowlight.sources.stations import fetch, gate_fixtures, notices, sharpschool
from snowlight.sources.stations.gap_markup import document
from snowlight.sources.stations.http import USER_AGENT, ConditionalStore, FetchError, PoliteClient
from snowlight.sources.stations.model import ListingState, ShapeError
from snowlight.sources.stations.registry import (
    DEFAULT_REGISTRY_DIR,
    RegistryError,
    Station,
    load_registry,
)

FOLDER = gate_fixtures.DEFAULT_FOLDER
SERVICE = "/WebServices/UnifiedPublishing/UnifiedPublishingService.asmx/GetActiveAlerts"


def _fixture(name: str) -> bytes:
    return (FOLDER / "sharpschool" / name).read_bytes()


def test_lees_hurricane_ian_slider_reads_the_closing() -> None:
    listing = sharpschool.parse(_fixture("lee-20221004.html"))
    assert (listing.variant, listing.state) == ("sharpschool-slider", ListingState.POPULATED)
    assert [row.name for row in listing.rows] == [
        "Hurricane Ian",
        "Connect with LEE (Live Educational Experts)",
        "Mental Health and Wellness Portal",
        "Bus Drivers WANTED",
    ]
    first = listing.rows[0]
    assert "close all schools and District offices next week (October 3-7, 2022)" in first.status
    assert first.extra["link"] == "https://www.leeschools.net/weather_watch"
    # A district's general channel: the gate counts the closing slide, not the others.
    assert notices.row_qualifies(first.name, first.status, listing.variant)
    assert not notices.row_qualifies(listing.rows[2].name, listing.rows[2].status, listing.variant)


def test_a_slider_before_the_closing_reads_the_weather_watch() -> None:
    listing = sharpschool.parse(_fixture("lee-20220926.html"))
    assert listing.variant == "sharpschool-slider"
    assert [row.name for row in listing.rows] == [
        "Weather Watch Alert",
        "Connect with LEE (Live Educational Experts)",
        "Mental Health and Wellness Portal",
        "Superintendent Town Hall Meetings",
        "Annual Vendor Open House",
        "Bus Drivers WANTED",
        "School Attendance Awareness Month",
        "Suicide Prevention Awareness Month",
    ]
    # The first slide has no heading: its image's alt text names it. It is a weather
    # notice for the district, but no closing: the gate counts none of the slides.
    first = listing.rows[0]
    assert (
        first.status
        == "The School District of Lee County is closely monitoring Tropical Storm Ian."
    )
    qualifying = [
        row.name
        for row in listing.rows
        if notices.row_qualifies(row.name, row.status, listing.variant)
    ]
    assert qualifying == []


def test_marions_web_community_manager_homepage_is_read_by_the_wcm_reader() -> None:
    listing = sharpschool.parse(_fixture("marion-20220927.html"))
    assert (listing.variant, listing.state) == ("wcm-announcements", ListingState.POPULATED)
    assert [row.name for row in listing.rows] == ["Marion County Public Schools"]
    assert "closed Wednesday, Thursday and Friday due to Hurricane Ian" in listing.rows[0].status


def test_the_component_homepage_defers_to_the_alert_service() -> None:
    listing = sharpschool.parse(_fixture("marion-20241007.html"))
    assert (listing.variant, listing.state) == ("sharpschool-homepage", ListingState.DEFERRED)
    assert listing.follows == (SERVICE,)


def test_the_live_answer_on_a_quiet_day_is_empty() -> None:
    body = _fixture("lee-alerts-live-20261003.json")
    assert body == b'{"d":[]}'
    listing = sharpschool.parse(body)
    assert (listing.variant, listing.state, listing.rows) == (
        "sharpschool-alerts",
        ListingState.EMPTY,
        (),
    )


SYNTHETIC_ALERT = {
    "__type": "Presence.ExternalServicesWrapper.UnifiedPublish.Models.EmergencyAlert",
    "AlertId": "6f1c2a7e-0000-4000-8000-000000000001",
    "Title": "Synthetic District Closed Today",
    "Body": "<p>All synthetic schools are <strong>closed</strong> today due to weather.</p>",
    "AlertType": "Emergency",
    "Expiry": "/Date(1768521600000)/",
    "Modified": "/Date(1768478400000)/",
}


def test_a_synthetic_alert_answer_gives_one_row_per_alert() -> None:
    body = json.dumps({"d": [SYNTHETIC_ALERT, {**SYNTHETIC_ALERT, "Title": ""}]}).encode()
    listing = sharpschool.parse(body)
    assert listing.state is ListingState.POPULATED
    assert listing.skipped_rows == 1  # the alert with no title
    (row,) = listing.rows
    assert row.name == "Synthetic District Closed Today"
    assert row.status == "All synthetic schools are closed today due to weather."
    assert row.updated_text == "/Date(1768478400000)/"
    assert row.extra == {
        "alert_id": "6f1c2a7e-0000-4000-8000-000000000001",
        "alert_type": "Emergency",
        "expiry": "2026-01-16T00:00:00Z",
    }


@pytest.mark.parametrize(
    "body",
    [
        b"{not json",
        b'{"e": []}',
        b'{"d": {}}',
        json.dumps({"d": [{"Title": "x"}]}).encode(),
        # The service's own sample alerts (what returnDummyAlerts: true asks for).
        json.dumps({"d": [{**SYNTHETIC_ALERT, "AlertId": sharpschool.SAMPLE_ID}]}).encode(),
        b"A synthetic body that is neither JSON nor a page.",
    ],
)
def test_bodies_in_no_known_form_are_refused(body: bytes) -> None:
    with pytest.raises(ShapeError):
        sharpschool.parse(body)


def test_a_page_in_no_known_form_is_read_by_its_text() -> None:
    # SYNTHETIC: since round 3 of the coverage gate a homepage in none of the forms is
    # read by its text: showing no closing, it holds no list of its own.
    page = b"<html><body><p>A synthetic page in no form the adapter knows.</p></body></html>"
    listing = sharpschool.parse(page)
    assert (listing.variant, listing.state, listing.follows) == (
        "homepage-text",
        ListingState.DEFERRED,
        (),
    )


def test_slices_read_as_their_originals_and_are_stable() -> None:
    for name in ("lee-20221004.html", "lee-20220926.html", "marion-20241007.html"):
        body = _fixture(name)
        assert sharpschool.slice_body(body) == body
    answer = _fixture("lee-alerts-live-20261003.json")
    assert sharpschool.slice_body(answer) == answer
    assert sharpschool.slice_body(b"<html><title>T</title></html>").startswith(b"<!DOCTYPE")


def test_registry_posts_the_components_body_to_the_service() -> None:
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    ids = sorted(sid for sid in registry.stations if sid.startswith("sharpschool-"))
    # Lee, Marion and Polk (round 1), and Corona-Norco, Desert Sands and Butte County (ID),
    # found by the gate's round 5 among the districts the gap-state part had not read
    assert ids == [
        "sharpschool-butte-id",
        "sharpschool-corona-norco-ca",
        "sharpschool-desert-sands-ca",
        "sharpschool-lee-fl",
        "sharpschool-marion-fl",
        "sharpschool-polk-fl",
    ]
    for sid in ids:
        station = registry.stations[sid]
        assert station.data_post == sharpschool.POST_BODY
        assert station.page_url is not None
        assert station.data_url is not None
        assert station.data_url == station.page_url.rstrip("/") + SERVICE
        assert station.poll_url == station.data_url
        assert set(station.archive_urls) == {station.page_url, station.data_url}
        assert [(item.url, item.loaded_by) for item in station.list_files] == [
            (station.data_url, "script")
        ]
        assert len(station.leaids) == 1
        robots = {check.url: check.allowed for check in station.robots}
        assert robots == {station.page_url: True, station.data_url: False}
    # The gate reads the alert service as a general channel: only closings prove it.
    assert "sharpschool" in notices.GENERAL_CHANNEL_ADAPTERS


def _station(data_post: str | None, data_url: str | None) -> dict[str, object]:
    return {
        "id": "sharpschool-synthetic-fl",
        "platform": "sharpschool",
        "call_sign": "SYN",
        "name": "synthetic",
        "market": "synthetic",
        "dma": None,
        "states": ["FL"],
        "counties": {"basis": "district", "source": "synthetic", "fips": ["12071"]},
        "page_url": "https://synthetic.test/",
        "data_url": data_url,
        "archive_urls": ["https://synthetic.test/"] + ([data_url] if data_url else []),
        "poll_minutes": None,
        "status": "active",
        "evidence": "synthetic",
        "leaids": ["1201080"],
        "data_post": data_post,
    }


def test_a_post_body_needs_a_data_url() -> None:
    Station.model_validate_json(json.dumps(_station('{"a":1}', "https://synthetic.test/s")))
    with pytest.raises(ValueError, match="POST body is sent only to a data_url"):
        Station.model_validate_json(json.dumps(_station('{"a":1}', None)))
    with pytest.raises(ValueError, match="data_post"):
        Station.model_validate_json(json.dumps(_station("not json", "https://synthetic.test/s")))


def test_the_registry_file_writes_a_post_body_only_where_there_is_one(tmp_path: Path) -> None:
    text = (DEFAULT_REGISTRY_DIR / "sharpschool.yaml").read_text(encoding="utf-8")
    assert text.count("\n  data_post: ") == 6  # (the platform's notes name the field too)
    other = (DEFAULT_REGISTRY_DIR / "nisd.yaml").read_text(encoding="utf-8")
    assert "data_post" not in other
    data = yaml.safe_load(text)
    data["stations"][0]["data_url"] = None
    broken = tmp_path / "sources"
    broken.mkdir()
    (broken / "sharpschool.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(broken)


def _client(tmp_path: Path, handler: httpx.MockTransport) -> PoliteClient:
    client = httpx.Client(transport=handler, headers={"User-Agent": USER_AGENT})
    return PoliteClient(client, ConditionalStore(tmp_path / "store"), host_interval=0.0)


def test_the_client_posts_json_without_a_conditional_request(tmp_path: Path) -> None:
    seen: list[tuple[str, str, bytes, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.method,
                request.url.path,
                request.content,
                request.headers.get("content-type"),
            )
        )
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /WebServices/\n")
        assert "if-none-match" not in request.headers
        return httpx.Response(200, json={"d": []}, headers={"ETag": '"v1"'})

    client = _client(tmp_path, httpx.MockTransport(handler))
    url = "https://district.test" + SERVICE
    answers = [client.fetch(url, post=sharpschool.POST_BODY.encode()) for _ in range(2)]
    assert [answer.body for answer in answers] == [b'{"d":[]}'] * 2
    fetched = answers[-1]
    posts = [item for item in seen if item[1] == SERVICE]
    assert (
        posts
        == [("POST", SERVICE, b'{"returnDummyAlerts":false}', "application/json; charset=utf-8")]
        * 2
    )
    (verdict,) = fetched.robots
    assert (verdict.allowed, verdict.rule) == (False, "Disallow: /WebServices/")


def test_a_post_answered_with_a_redirect_is_an_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"Location": "https://district.test/login"})

    client = _client(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(FetchError, match="POST answered with a redirect"):
        client.fetch("https://district.test" + SERVICE, post=b"{}")


def test_robots_reached_through_redirects_is_read_once(tmp_path: Path) -> None:
    # SharpSchool sites send /robots.txt to /robots.txt/ and on to /robots.txt/Default.aspx;
    # reading it must not ask for robots.txt again for the redirect hops.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        hops = {"/robots.txt": "/robots.txt/", "/robots.txt/": "/robots.txt/Default.aspx"}
        if request.url.path in hops:
            return httpx.Response(301, headers={"Location": hops[request.url.path]})
        if request.url.path == "/robots.txt/Default.aspx":
            return httpx.Response(200, text="User-agent: *\nDisallow: /WebServices/\n")
        return httpx.Response(200, text="<html></html>")

    client = _client(tmp_path, httpx.MockTransport(handler))
    verdict = client.robots_verdict("https://district.test/")
    assert verdict.allowed
    assert seen == ["/robots.txt", "/robots.txt/", "/robots.txt/Default.aspx"]


def test_the_poller_posts_only_to_the_stations_data_url(tmp_path: Path) -> None:
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    station = registry.stations["sharpschool-lee-fl"]
    methods: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        methods[request.url.path] = request.method
        if request.url.path.startswith("/robots.txt"):
            return httpx.Response(404)
        return httpx.Response(200, json={"d": [SYNTHETIC_ALERT]})

    client = _client(tmp_path, httpx.MockTransport(handler))
    result = fetch.run(
        registry, client, clock=lambda: datetime(2026, 1, 15, 12, tzinfo=UTC), only=[station.id]
    )
    assert methods[SERVICE] == "POST"
    (health,) = result.health
    assert (health.status.value, health.rows) == ("ok", 1)
    assert [row.raw_name for row in result.rows] == ["Synthetic District Closed Today"]


def test_polks_wordpress_homepage_of_ian_reads_its_storm_slide() -> None:
    listing = sharpschool.parse(_fixture("polk-20220928.html"))
    assert (listing.variant, listing.state) == ("wordpress-smartslider", ListingState.POPULATED)
    assert [row.name for row in listing.rows] == ["Designer", "Featured Video"]
    assert listing.skipped_rows == 1  # the heritage-month banner: images alone
    storm = listing.rows[0]
    assert storm.status.startswith(
        "Public schools in Polk County will be closed Tuesday (Sept. 27) through Thursday"
    )
    assert storm.extra == {"slider": "n2-ss-107"}
    qualifying = [
        row.name
        for row in listing.rows
        if notices.row_qualifies(row.name, row.status, listing.variant)
    ]
    assert qualifying == ["Designer"]
    body = _fixture("polk-20220928.html")
    assert sharpschool.slice_body_v2(body) == body


def test_a_smart_slider_page_with_no_words_is_empty_and_one_without_wordpress_is_text() -> None:
    # SYNTHETIC: a WordPress page whose only slider slide is an image.
    slide = '<div class="n2-ss-slider" id="s"><div class="n2-ss-slide" data-title="B"></div></div>'
    empty = sharpschool.parse(document(f'<link href="/wp-content/x.css">{slide}'))
    assert (empty.variant, empty.state, empty.skipped_rows) == (
        "wordpress-smartslider",
        ListingState.EMPTY,
        1,
    )
    # Without WordPress it is no Smart Slider page: read by its text, which shows nothing.
    bare = sharpschool.parse(document(slide))
    assert (bare.variant, bare.state) == ("homepage-text", ListingState.DEFERRED)

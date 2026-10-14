"""Web Community Manager on-screen alerts: the file a WCM homepage loads beside its apps.

A WCM district homepage fetched the district's on-screen alert by script from
``/cms/Tools/OnScreenAlerts/UserControls/OnScreenAlertDialogListWrapper.aspx`` (its
``SiteID`` naming the district's site). The homepages here are real archived captures
(fixtures/gate/wcm/, provenance in PROVENANCE.json): Hillsborough's of 2024-10-09
(Hurricane Milton; its announcements app held the district's impact report, not a
closing), Pinellas' of 2024-10-08 and Broward's of 2022-09-28 (Hurricane Ian; no
announcements app) and Socorro's of 2022-02-03, and the alert files the archive captured
beside them: Broward's closure for Ian, Pinellas' for Milton, Hillsborough's after Ian,
and Broward's empty one on the eve of Milton. Registries, manifests and the small
documents a few tests build are synthetic and say so.
"""

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped, unused-ignore]
from pydantic import ValidationError

from snowlight.sources.stations import (
    apptegy,
    archive,
    finalsite,
    gate_fixtures,
    notices,
    smartsites,
    wcm,
)
from snowlight.sources.stations.archive import url_key
from snowlight.sources.stations.model import Listing, ListingState, ShapeError, ViaPage
from snowlight.sources.stations.registry import Registry, load_registry

FOLDER = gate_fixtures.DEFAULT_FOLDER
DIALOG = "/cms/Tools/OnScreenAlerts/UserControls/OnScreenAlertDialogListWrapper.aspx"
SHA = "0" * 64


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def test_a_homepage_names_its_sites_alert_file() -> None:
    hillsborough = _body("wcm/hillsborough-20241009.html").decode()
    socorro = _body("wcm/socorro-20220203.html").decode()
    assert wcm.alert_file(hillsborough) == f"{DIALOG}?OnScreenAlertCookie=&SiteID=4"
    assert wcm.alert_file(socorro) == f"{DIALOG}?OnScreenAlertCookie=&SiteID=1"
    assert wcm.alert_file("<html><body>synthetic: no loader</body></html>") is None


def test_a_homepage_with_announcements_loads_its_alert_file_beside_them() -> None:
    body = _body("wcm/hillsborough-20241009.html")
    listing = apptegy.parse(body)
    assert listing.variant == wcm.VARIANT
    assert listing.state is ListingState.POPULATED
    assert [row.name for row in listing.rows] == ["Hillsborough County Public Schools"]
    assert listing.also_loads == (f"{DIALOG}?OnScreenAlertCookie=&SiteID=4",)
    assert listing.follows == ()


@pytest.mark.parametrize("parse", [apptegy.parse, finalsite.parse, smartsites.parse])
def test_each_adapter_defers_a_homepage_without_announcements_to_its_alert_file(
    parse: object,
) -> None:
    assert callable(parse)
    listing = parse(_body("wcm/socorro-20220203.html"))
    assert isinstance(listing, Listing)
    assert listing.variant == wcm.ALERT_PAGE_VARIANT
    assert listing.state is ListingState.DEFERRED
    assert listing.follows == (f"{DIALOG}?OnScreenAlertCookie=&SiteID=1",)


def test_the_v2_slice_keeps_the_loader_and_reads_as_the_page() -> None:
    body = _body("wcm/hillsborough-20241009.html")
    assert wcm.slice_body_v2(body) == body
    # The v1 slice drops scripts: the same page cut that way names no alert file.
    assert wcm.alert_file(wcm.slice_body(body).decode()) is None
    assert wcm.slice_body_v2(b"<html><body>synthetic: nothing to keep</body></html>") == (
        b"<!DOCTYPE html><html><body></body></html>\n"
    )


def test_only_a_page_holding_its_own_list_loads_files_beside_it() -> None:
    with pytest.raises(ValidationError):
        Listing(
            variant="synthetic",
            state=ListingState.DEFERRED,
            rows=(),
            follows=("/list",),
            also_loads=("/alert",),
        )
    empty = Listing(variant="synthetic", state=ListingState.EMPTY, rows=(), also_loads=("/a",))
    assert empty.also_loads == ("/a",)


def test_a_page_read_alongside_holds_its_own_list() -> None:
    fields = {
        "url": "https://synthetic.test/",
        "fetched_at": datetime(2024, 10, 9, tzinfo=UTC),
        "sha256": SHA,
        "variant": "synthetic",
        "declared_count": None,
        "follows": "https://synthetic.test/alert",
        "gap_seconds": 60,
    }
    beside = ViaPage.model_validate({**fields, "state": ListingState.POPULATED, "alongside": True})
    assert beside.alongside
    with pytest.raises(ValidationError):
        ViaPage.model_validate({**fields, "state": ListingState.DEFERRED, "alongside": True})
    with pytest.raises(ValidationError):
        ViaPage.model_validate({**fields, "state": ListingState.POPULATED})


def test_the_alert_files_of_a_districts_sites_are_told_apart_by_site() -> None:
    district = f"https://www.browardschools.com{DIALOG}?OnScreenAlertCookie=&SiteID=4&_=1664"
    school = f"https://www.browardschools.com{DIALOG}?OnScreenAlertCookie=&SiteID=179&_=1664"
    assert url_key(district) == f"browardschools.com{DIALOG}?siteid=4"
    assert url_key(district) != url_key(school)
    assert url_key(f"https://www.browardschools.com{DIALOG}?OnScreenAlertCookie=&SiteID=4") == (
        url_key(district)
    )


@pytest.mark.parametrize(
    ("name", "status", "variant"),
    [
        # Real: Medina Valley ISD's Edlio homepage alert captured 2023-02-02T01:40:38Z (run
        # 36547271072), the day after the ice storm closed its campuses.
        (
            "Weather Update - February 2, 2023",
            "We anticipate all MVISD campuses & offices to be open and back to normal "
            "operation on Thursday, February 2.",
            "edlio-homepage-alert",
        ),
        # SYNTHETIC: a notice titled as a weather statement.
        ("Weather Statement", "Buses will run on snow routes.", "finalsite-page-pops"),
    ],
)
def test_a_notice_titled_as_a_weather_update_that_closes_nothing_does_not_prove(
    name: str, status: str, variant: str
) -> None:
    # A weather update that announces no closing, delay or remote day is no closing (the
    # gate of 2026-10-13: a channel is proven only by a closing).
    assert not notices.row_qualifies(name, status, variant)


BROWARD = "https://www.browardschools.com/"
PINELLAS = "https://www.pcsb.org/"
ALERT_QUERY = "?OnScreenAlertCookie=&SiteID=4"


def _registry(tmp_path: Path) -> Registry:
    """A SYNTHETIC registry: Broward and Pinellas on the real Finalsite adapter."""
    folder = tmp_path / "sources"
    folder.mkdir()
    platform = {
        "id": "fsdemo",
        "name": "Demo (synthetic)",
        "operator": "Nobody",
        "adapter": "finalsite",
        "poll_minutes": 15,
        "terms": {"automated_access": "unread", "summary": "synthetic", "evidence": []},
        "notes": "synthetic",
    }

    def station(sid: str, page: str, fips: str) -> dict[str, object]:
        return {
            "id": sid,
            "platform": "fsdemo",
            "call_sign": "DEMO",
            "name": "synthetic",
            "market": "synthetic",
            "dma": None,
            "states": ["FL"],
            "counties": {"basis": "observed", "source": "synthetic", "fips": [fips]},
            "page_url": page,
            "data_url": None,
            "archive_urls": [page, page.rstrip("/") + DIALOG + ALERT_QUERY],
            "poll_minutes": None,
            "status": "active",
            "evidence": "synthetic",
        }

    stations = [
        station("fsdemo-broward", BROWARD, "12011"),
        station("fsdemo-pinellas", PINELLAS, "12103"),
    ]
    content = {"platform": platform, "stations": stations}
    (folder / "fsdemo.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    return load_registry(folder)


def _artifact(tmp_path: Path, captures: Sequence[tuple[str, str, bytes]]) -> Path:
    """Lay out real bodies under a SYNTHETIC manifest in the archive workflow's format."""
    root = tmp_path / "artifact"
    (root / "snapshots").mkdir(parents=True)
    lines = []
    for number, (stamp, url, body) in enumerate(captures):
        name = f"snapshots/{number}.body"
        (root / name).write_bytes(body)
        record = {
            "timestamp": stamp,
            "url": url,
            "requested": f"https://web.archive.org/web/{stamp}id_/{url}",
            "retrieved_at": "2026-09-29T11:18:36Z",
            "final_timestamp": stamp,
            "final_original": url,
            "http_status": 200,
            "file": name,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        lines.append(json.dumps(record) + "\n")
    (root / "snapshots" / "manifest.jsonl").write_text("".join(lines), encoding="utf-8")
    return root


def test_a_homepage_without_announcements_is_read_through_its_alert_file(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    alert = f"https://www.browardschools.com{DIALOG}{ALERT_QUERY}&_=1627683547399"
    root = _artifact(
        tmp_path,
        [
            ("20220928020740", BROWARD, _body("wcm/broward-20220928.html")),
            ("20220928001729", alert, _body("wcm/broward-alert-20220928.html")),
        ],
    )
    result = archive.parse_snapshots(registry, root)
    assert result.failures == []
    (read,) = result.reads
    assert (read.url, read.variant, read.state, read.rows) == (
        alert,
        wcm.ALERT_VARIANT,
        ListingState.POPULATED,
        1,
    )
    (page,) = read.via
    assert (page.url, page.state, page.alongside) == (BROWARD, ListingState.DEFERRED, False)
    assert page.gap_seconds == -6611
    (row,) = result.rows
    assert row.raw_name == "BCPS Update on School Operations Due to Hurricane Ian"
    assert "will be closed on Wednesday, September 28, 2022" in row.raw_status
    assert notices.row_qualifies(row.raw_name, row.raw_status, read.variant)


def test_a_homepage_with_announcements_is_read_and_its_alert_file_beside_it(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    alert = f"https://www.pcsb.org{DIALOG}{ALERT_QUERY}&_=1728395414600"
    root = _artifact(
        tmp_path,
        [
            ("20241008091114", PINELLAS, _body("wcm/pinellas-20241008.html")),
            ("20241008135017", alert, _body("wcm/pinellas-alert-20241008.html")),
        ],
    )
    result = archive.parse_snapshots(registry, root)
    assert result.failures == []
    page_read, alert_read = result.reads
    assert (page_read.url, page_read.variant, page_read.rows, page_read.via) == (
        PINELLAS,
        wcm.VARIANT,
        6,
        (),
    )
    assert (alert_read.url, alert_read.variant, alert_read.rows) == (alert, wcm.ALERT_VARIANT, 1)
    (beside,) = alert_read.via
    assert (beside.url, beside.state, beside.alongside) == (
        PINELLAS,
        ListingState.POPULATED,
        True,
    )
    assert beside.gap_seconds == 16743
    assert len(result.health) == 2
    names = [row.raw_name for row in result.rows]
    assert names[-1] == "Weather Update and School Closure Information"


def test_an_alert_file_beyond_the_window_is_read_on_its_own(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    alert = f"https://www.pcsb.org{DIALOG}{ALERT_QUERY}&_=1728395414600"
    # SYNTHETIC timing: the real alert body placed seven hours after the real homepage.
    root = _artifact(
        tmp_path,
        [
            ("20241008091114", PINELLAS, _body("wcm/pinellas-20241008.html")),
            ("20241008161114", alert, _body("wcm/pinellas-alert-20241008.html")),
        ],
    )
    result = archive.parse_snapshots(registry, root)
    assert [read.via for read in result.reads] == [(), ()]


def test_the_alert_files_of_real_hurricane_days_read_as_their_provenance_says() -> None:
    empty = finalsite.parse(_body("wcm/broward-alert-20241008.html"))
    assert (empty.variant, empty.state) == (wcm.ALERT_VARIANT, ListingState.EMPTY)
    closed = apptegy.parse(_body("wcm/hillsborough-alert-20220930.html"))
    (row,) = closed.rows
    assert row.name.startswith("Schools will remain closed this Friday")
    assert row.extra == {"alert_id": "23", "heading": "Important Message", "links": None}
    assert (
        smartsites.parse(_body("wcm/pinellas-alert-20241008.html")).rows[0].extra["alert_id"]
        == "47"
    )
    with pytest.raises(ShapeError):
        wcm.parse_alert_dialog("<div>synthetic: no message list</div>")


def test_an_older_loader_names_no_site() -> None:
    # SYNTHETIC: the loader as the real homepages write it, without the SiteID part that
    # older Web Community Manager versions left out (their alert files carry no SiteID).
    page = (
        '<script>GetContent(homeURL + "' + DIALOG + '?OnScreenAlertCookie=" + '
        'onscreenAlertCookie, "onscreenalert-holder", 2, "OnScreenAlertCheckListItem();");'
        "</script>"
    )
    assert wcm.alert_file(page) == f"{DIALOG}?OnScreenAlertCookie="
    assert url_key(f"https://www.hsd3.org{DIALOG}?OnScreenAlertCookie=&_=1616650000000") == (
        f"hsd3.org{DIALOG}"
    )

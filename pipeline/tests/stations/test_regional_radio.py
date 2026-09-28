"""KXXO's closings page and the FlashAlert report it frames; WFRD's page, refused.

The fixtures are archived captures (fixtures/regional/radio and errors/, provenance
in PROVENANCE.json and PROVENANCE.errors.json): neither site answers from the build
environment, so they were read in the Internet Archive.
"""

import pytest

from snowlight.sources.stations import radio, regional_fixtures
from snowlight.sources.stations.model import ListingState, ShapeError
from snowlight.sources.stations.registry import StationStatus, load_registry

FOLDER = regional_fixtures.DEFAULT_FOLDER


def _body(name: str) -> bytes:
    return (FOLDER / name).read_bytes()


def test_kxxo_page_follows_the_framed_report() -> None:
    page = radio.parse(_body("radio/kxxo-page-20220104.html"))
    assert (page.variant, page.state, page.follows) == (
        radio.PAGE,
        ListingState.DEFERRED,
        ("//www.kxxo.com/kxxo-sftp/school_closures.html",),
    )
    station = load_registry().stations["radio-kxxo"]
    assert station.data_url == "https:" + page.follows[0]


def test_kxxo_report_on_a_snow_day() -> None:
    report = radio.parse(_body("radio/kxxo-report-20220104.html"))
    assert (report.variant, report.state, len(report.rows)) == (
        radio.COPY,
        ListingState.POPULATED,
        113,
    )
    first, auburn = report.rows[0], report.rows[2]
    assert (first.name, first.status, first.updated_text) == (
        "Evergreen State College",
        "Opening at 11 am",
        "Tue. Jan. 4 - 8:30 am",
    )
    assert first.extra == {
        "region": "Seattle/Western Wash.",
        "updated_scope": "page",
        "category": "Colleges & Universities",
    }
    assert auburn.name == "Auburn SD"
    assert auburn.status.startswith("2 Hours Late, No preschool, AM Buses on snow routes")
    assert not auburn.status.endswith("UPDATE")
    assert auburn.extra["marked_update"] is True
    assert sum(1 for row in report.rows if row.extra.get("marked_update")) == 46
    assert len({row.extra["category"] for row in report.rows}) == 14
    assert report.rows[-1].name == "South Sound YMCA-Child Care Services"


def test_kxxo_report_with_nothing_reported_is_empty() -> None:
    report = radio.parse(_body("radio/kxxo-report-20260306.html"))
    assert (report.variant, report.state, report.rows) == (radio.COPY, ListingState.EMPTY, ())


def test_unseen_report_markup_is_refused() -> None:
    body = _body("radio/kxxo-report-20220104.html")
    with pytest.raises(ShapeError, match="header of another form"):
        radio.parse(body.replace(b"Emergency Info for", b"Emergency Notes on"))
    with pytest.raises(ShapeError, match="no ' - '"):
        radio.parse(body.replace(b"</strong>&nbsp;- Opening", b"</strong> Opening", 1))
    empty = _body("radio/kxxo-report-20260306.html")
    with pytest.raises(ShapeError, match="names no organization"):
        radio.parse(empty.replace(b"No information reported.", b"Nothing today."))
    with pytest.raises(ShapeError, match="not KXXO's closings page"):
        radio.parse(b"<html><body><p>School Closings</p></body></html>")


def test_wfrd_is_registered_without_an_endpoint() -> None:
    station = load_registry().stations["radio-wfrd"]
    assert station.status is StationStatus.NO_ENDPOINT
    assert "list-front.php" in station.evidence
    errors = {item.file: item for item in regional_fixtures.load_errors(FOLDER)}
    refused = errors["errors/wfrd-page-20240717.html"]
    assert refused.source_id == "radio-wfrd"
    with pytest.raises(ShapeError):
        radio.parse(_body(refused.file))

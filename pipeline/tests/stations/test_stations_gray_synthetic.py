"""Error handling in the Gray S3 export reader, on synthetic bodies.

Every body in this file is synthetic: written for one rule each, in the export's
documented shape (docs/research/sources.json, the gray-arc endpoint_format), with
made-up organizations. Real exports are tested in test_stations_gray.py.
"""

import gzip
import json

import pytest

from snowlight.sources.stations import gray
from snowlight.sources.stations.model import ListingState, ShapeError


def synthetic_item(name: str | None, status: str = "Closed Monday") -> dict[str, object]:
    return {
        "forced_organization_name": name,
        "forced_status_name": status,
        "updated": "2026-01-25",
        "county_name1": "Example",
        "zipcode": "00000",
        "rec_id": "1",
        "comments_line1": None,
    }


def synthetic_export(items: list[dict[str, object]] | None, count: object) -> bytes:
    export: dict[str, object] = {
        "locations": [],
        "num_closings": count,
        "export_type": "L1",
        "source": "GSync",
        "run_date": "",
    }
    if items is not None:
        export["record"] = items
    return json.dumps([export]).encode()


def test_synthetic_empty_export() -> None:
    listing = gray.parse(synthetic_export(None, 0))
    assert listing.variant == "gray-s3-json"
    assert listing.state is ListingState.EMPTY
    assert listing.declared_count == 0


def test_synthetic_populated_export_keeps_raw_fields() -> None:
    body = synthetic_export([synthetic_item("Example School District ")], "1")
    (row,) = gray.parse(body).rows
    assert row.name == "Example School District"
    assert row.status == "Closed Monday"
    assert row.updated_text == "2026-01-25"
    assert row.extra == {
        "county_name1": "Example",
        "zipcode": "00000",
        "rec_id": "1",
        "comments_line1": None,
    }


def test_synthetic_nameless_rows_are_counted_not_kept() -> None:
    listing = gray.parse(synthetic_export([synthetic_item("A"), synthetic_item("  ")], 2))
    assert [row.name for row in listing.rows] == ["A"]
    assert listing.skipped_rows == 1


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (synthetic_export(None, 3), "no record list"),
        (synthetic_export([synthetic_item(None)], 1), "missing its name"),
        (synthetic_export([{"forced_status_name": 5}], 1), "as text"),
        (synthetic_export([synthetic_item("A")], -1), "not a count"),
        (synthetic_export([synthetic_item("A")], True), "not a count"),
        (b"[]", "empty"),
        (b"[{}]", "not a GSync export"),
        (b"[1", "not JSON"),
        (b'["\xff\xfe"]', "not UTF-8"),
        (b"<html>moved</html>", "not a Gray closings body"),
        (json.dumps([{"num_closings": 1, "locations": [], "record": {}}]).encode(), "not a list"),
    ],
)
def test_synthetic_bad_bodies_are_shape_errors(body: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        gray.parse(body)


def test_synthetic_nested_values_are_refused() -> None:
    item = synthetic_item("A")
    item["event"] = {"nested": True}
    with pytest.raises(ShapeError, match="plain value"):
        gray.parse(synthetic_export([item], 1))


def test_synthetic_gzip_and_bom_bodies() -> None:
    body = synthetic_export([synthetic_item("A")], 1)
    assert gray.parse(gzip.compress(body)).rows[0].name == "A"
    assert gray.parse(b"\xef\xbb\xbf" + body).rows[0].name == "A"


# Station pages (Arc XP Fusion): synthetic pages in the shape the real captures in
# fixtures/gray/ have, with made-up organizations.


def synthetic_page(data: dict[str, object] | None, *, entries: int = 1) -> bytes:
    cache: dict[str, object] = {"site-navigation": {"{}": {"data": {"children": []}}}}
    if data is not None:
        cache["gsync-closings"] = {f'{{"n":{n}}}': {"data": data} for n in range(entries)}
    script = "Fusion.contentCache=" + json.dumps(cache) + ';Fusion.layout="Homepage";'
    return f"<html><head><script>{script}</script></head><body></body></html>".encode()


def synthetic_org(name: str | None, status: object = "Closed Monday") -> dict[str, object]:
    return {
        "address": {"line1": "", "city": "", "state": "EXAMPLE", "zipcode": "00000"},
        "category": "School",
        "comments": ["Example comment"],
        "county": "Example",
        "id": "1",
        "name": name,
        "status": status,
        "updatedDate": "2026-01-25",
    }


def test_synthetic_page_rows_flatten_nested_values() -> None:
    body = synthetic_page({"organizations": [synthetic_org(" Example School ")], "totalResults": 1})
    listing = gray.parse(body)
    assert listing.variant == "gray-fusion-orgs"
    (row,) = listing.rows
    assert row.name == "Example School"
    assert row.updated_text == "2026-01-25"
    assert row.extra["address.zipcode"] == "00000"
    assert row.extra["comments"] == '["Example comment"]'
    assert listing.declared_count == 1


def test_synthetic_page_empty_and_count_only_states() -> None:
    empty = gray.parse(synthetic_page({"organizations": [], "totalResults": 0}))
    assert (empty.variant, empty.state) == ("gray-fusion-orgs", ListingState.EMPTY)
    zero = gray.parse(synthetic_page({"totalResults": 0, "_id": "x"}))
    assert (zero.variant, zero.state) == ("gray-fusion-count", ListingState.EMPTY)
    counted = gray.parse(synthetic_page({"totalResults": 7, "_id": "x"}))
    assert counted.state is ListingState.COUNT_ONLY
    assert counted.declared_count == 7


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (synthetic_page(None), "no gsync-closings"),
        (synthetic_page({"totalResults": 1}, entries=2), "2 queries"),
        (synthetic_page({"totalResults": "many"}), "not a count"),
        (synthetic_page({"totalResults": 3, "lastUpdated": "x"}), "no organizations"),
        (synthetic_page({"organizations": {}, "totalResults": 0}), "not a list"),
        (synthetic_page({"organizations": [], "totalResults": 4}), "list is empty"),
        (synthetic_page({"organizations": [synthetic_org(None)], "totalResults": 1}), "name"),
        (synthetic_page({"organizations": ["x"], "totalResults": 1}), "not an object"),
        (
            synthetic_page({"organizations": [synthetic_org("A", status=None)], "totalResults": 1}),
            "name or status",
        ),
        (b"<script>Fusion.contentCache={broken</script>", "not complete JSON"),
        (b"<script>Fusion.contentCache=[1];</script>", "not an object"),
    ],
)
def test_synthetic_bad_pages_are_shape_errors(body: bytes, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        gray.parse(body)


def test_synthetic_page_slice_keeps_only_the_closings_member() -> None:
    body = synthetic_page({"organizations": [synthetic_org("A")], "totalResults": 1})
    sliced = gray.slice_page(body)
    assert b"site-navigation" not in sliced
    assert gray.parse(sliced) == gray.parse(body)
    export = synthetic_export([synthetic_item("A")], 1)
    assert gray.slice_page(gzip.compress(export)) == export
    with pytest.raises(ShapeError):
        gray.slice_page(b"<html>moved</html>")


def test_synthetic_content_api_bodies() -> None:
    orgs = {"organizations": [synthetic_org("A")], "totalResults": 1}
    listing = gray.parse(json.dumps(orgs).encode())
    assert (listing.variant, [row.name for row in listing.rows]) == ("gray-api-orgs", ["A"])
    counted = gray.parse(json.dumps({"totalResults": 5, "_id": "x"}).encode())
    assert (counted.variant, counted.state) == ("gray-api-count", ListingState.COUNT_ONLY)


def test_synthetic_lazy_page_is_deferred() -> None:
    # The closings component's markup with no gsync-closings cache entry.
    cache = json.dumps({"site-navigation": {"{}": {"data": {}}}})
    body = (
        f'<div class="gsync-closings-detailed | mb-3"></div>'
        f"<script>Fusion.contentCache={cache};</script>"
    ).encode()
    listing = gray.parse(body)
    assert (listing.variant, listing.state, listing.declared_count) == (
        "gray-fusion-lazy",
        ListingState.DEFERRED,
        None,
    )

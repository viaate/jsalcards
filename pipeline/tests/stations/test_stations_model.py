"""The raw-row, listing and health models refuse inconsistent records (synthetic values)."""

import gzip
import zlib

import pytest
from pydantic import ValidationError

from snowlight.sources.stations.body import decode
from snowlight.sources.stations.fetch import listing_health
from snowlight.sources.stations.model import (
    MAX_EXTRA_TEXT,
    HealthStatus,
    Listing,
    ListingState,
    ParsedRow,
    RawRow,
    ShapeError,
    SourceHealth,
    count_only_reason,
)


def test_row_names_are_kept_stripped() -> None:
    with pytest.raises(ValidationError, match="stripped"):
        ParsedRow(name=" Padded ", status="Closed")


def test_row_extra_text_is_bounded() -> None:
    with pytest.raises(ValidationError, match="longer than"):
        ParsedRow(name="A", status="Closed", extra={"note": "x" * (MAX_EXTRA_TEXT + 1)})


def test_listing_state_agrees_with_rows() -> None:
    row = ParsedRow(name="A", status="Closed")
    with pytest.raises(ValidationError, match="populated listing has rows"):
        Listing(variant="demo", state=ListingState.EMPTY, rows=(row,))
    with pytest.raises(ValidationError, match="populated listing has rows"):
        Listing(variant="demo", state=ListingState.POPULATED, rows=())
    with pytest.raises(ValidationError, match="populated listing has rows"):
        Listing(variant="demo", state=ListingState.COUNT_ONLY, rows=(row,), declared_count=1)
    with pytest.raises(ValidationError, match="count above zero"):
        Listing(variant="demo", state=ListingState.COUNT_ONLY, rows=(), declared_count=0)


def test_count_only_listing_is_an_error_with_its_count() -> None:
    listing = Listing(variant="demo", state=ListingState.COUNT_ONLY, rows=(), declared_count=318)
    status, reason = listing_health(listing)
    assert status is HealthStatus.ERROR
    assert reason == count_only_reason(listing)
    assert "318" in reason
    empty = Listing(variant="demo", state=ListingState.EMPTY, rows=())
    assert listing_health(empty) == (HealthStatus.EMPTY, None)
    deferred = Listing(variant="demo", state=ListingState.DEFERRED, rows=())
    status, reason = listing_health(deferred)
    assert status is HealthStatus.ERROR
    assert "no list and no count" in (reason or "")
    with pytest.raises(ValidationError, match="declares no count"):
        Listing(variant="demo", state=ListingState.DEFERRED, rows=(), declared_count=0)


def test_raw_row_needs_whole_second_utc_time() -> None:
    fields: dict[str, object] = {
        "source_id": "demo-a",
        "raw_name": "A",
        "raw_status": "Closed",
        "raw_updated_text": None,
        "raw_extra": {},
    }
    row = RawRow.model_validate({**fields, "fetched_at": "2026-01-26T12:00:00Z"})
    assert row.fetched_at.isoformat() == "2026-01-26T12:00:00+00:00"
    with pytest.raises(ValidationError):
        RawRow.model_validate({**fields, "fetched_at": "2026-01-26T12:00:00.5Z"})


@pytest.mark.parametrize(
    ("status", "rows", "reason", "message"),
    [
        (HealthStatus.ERROR, 0, None, "says why"),
        (HealthStatus.SKIPPED, 0, None, "says why"),
        (HealthStatus.EMPTY, 2, None, "only an ok read"),
        (HealthStatus.OK, 0, None, "has rows"),
    ],
)
def test_health_is_consistent(
    status: HealthStatus, rows: int, reason: str | None, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        SourceHealth.model_validate(
            {
                "source_id": "demo-a",
                "url": None,
                "checked_at": "2026-01-26T12:00:00Z",
                "status": status,
                "rows": rows,
                "reason": reason,
            }
        )


def test_decode_handles_gzip_zlib_and_plain() -> None:
    assert decode(gzip.compress(b"<html>")) == b"<html>"
    assert decode(zlib.compress(b"<html>")) == b"<html>"
    assert decode(b"<html>") == b"<html>"
    assert decode(b"x\x9cnot zlib") == b"x\x9cnot zlib"
    with pytest.raises(ShapeError, match="gzip"):
        decode(b"\x1f\x8b\x08broken")

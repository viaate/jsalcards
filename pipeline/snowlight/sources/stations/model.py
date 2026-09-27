"""What a station adapter reads: raw listing rows, the listing they came in, and health.

Nothing here classifies a status or matches a name. An adapter turns one response
body into a :class:`Listing` (its rows plus whether the page said "nothing is
closed"); the runner stamps each row with the source id and the time the body was
read, giving :class:`RawRow`, and records how the read went as
:class:`SourceHealth`. The status parser and the name matcher are later steps.

Output shapes (JSON Lines and JSON, written by :mod:`snowlight.sources.stations.fetch`
under ``pipeline/out/internal/stations/``; internal, never published)::

    rows.jsonl     one RawRow per line:
                   {"source_id": "gray-kwch", "fetched_at": "2026-09-25T01:37:00Z",
                    "raw_name": "USD 214 Ulysses", "raw_status": "Alert Thursday",
                    "raw_updated_text": "2026-09-24",
                    "raw_extra": {"county_name1": "Grant", "zipcode": "67880", ...}}
    reads.jsonl    one ListingRead per source read (live or archived): where the body
                   came from, its SHA-256, the variant parsed, its state (populated,
                   empty, count_only: the page gave a count but not the list, or
                   deferred: the page loads its list after it loads) and the row count;
                   for a list read by following a page to the file it frames or
                   loads, ``via`` names each page on the way (see ViaPage: its
                   count, when the page says the count was made, and whether the
                   count equals the list read)
    health.json    {"generated_at": ..., "stale_before": ..., "sources": [SourceHealth, ...],
                    "totals": {"ok": n, "empty": n, "stale": n, "error": n,
                               "skipped": n, "rows": n, "sources": n,
                               "robots_disallowed": n}}
                   Each SourceHealth records robots.txt's verdict on every URL read
                   for the source (``robots``: the owner decided on 2026-09-26 to
                   read closings pages and files even where robots.txt disallows
                   them, so the verdict is recorded, not obeyed) and the list
                   file's ``Last-Modified`` when the server sent one.

``fetched_at`` is when the bytes were read from the station: the time of the live
request, or for an archived page the Wayback capture time (the moment the archive
read the page from the station), never the time the archive copy was downloaded.
A row read by following a page to its list file carries the list file's time.

A list file whose ``Last-Modified`` is older than the start of the last winter
(:func:`stale_before`) is ``stale``: nothing has been written to it for a whole
winter, so its rows are not kept (a station that stopped using a file leaves it
behind with whatever it held, or empty) and the source does not count as working.

A page that holds no list of its own names the file it loads in
:attr:`Listing.follows` (as the page writes it, resolved against the page's URL by
the reader); the reader follows it and records the page as a :class:`ViaPage`.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from snowlight.schemas.base import InternalModel
from snowlight.schemas.internal import Sha256, SourceId
from snowlight.schemas.scalars import Count, UtcInstant
from snowlight.sources.stations.robots import RobotsState

type JsonScalar = str | int | float | bool | None
"""A value an adapter keeps verbatim from the source, as JSON can carry it."""

MAX_NAME = 500
MAX_STATUS = 2000
MAX_EXTRA_TEXT = 4000
MAX_REASON = 500
WINTER_START_MONTH = 11
WINTER_END_MONTH = 3

type RawText = Annotated[str, StringConstraints(max_length=MAX_STATUS)]
type Url = Annotated[str, StringConstraints(pattern=r"^https?://[^\s]+$", max_length=2000)]
type Reference = Annotated[
    str, StringConstraints(min_length=1, max_length=2000, pattern=r"^[^\s]+$")
]
"""A URL as a page writes it: absolute, scheme-relative (``//host/...``) or relative."""


class ListingState(StrEnum):
    """What a page said about itself, as far as the adapter can tell."""

    POPULATED = "populated"
    """The page listed one or more organizations."""
    EMPTY = "empty"
    """The page said, in its own words or structure, that nothing is listed."""
    COUNT_ONLY = "count_only"
    """The page said how many are listed but not who (the list loads from elsewhere)."""
    DEFERRED = "deferred"
    """The page holds neither the list nor a count: its list loads after the page does."""


class ReadMode(StrEnum):
    """Where a body was read from."""

    LIVE = "live"
    ARCHIVE = "archive"


class ParsedRow(InternalModel):
    """One listing row as an adapter found it, before the runner stamps it."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=MAX_NAME)]
    status: RawText
    updated_text: RawText | None = None
    extra: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.name != self.name.strip():
            raise ValueError("a row name is kept stripped of outer whitespace")
        for key, value in self.extra.items():
            if isinstance(value, str) and len(value) > MAX_EXTRA_TEXT:
                raise ValueError(f"extra field {key!r} is longer than {MAX_EXTRA_TEXT}")
        return self


class Listing(InternalModel):
    """Everything an adapter read from one body."""

    variant: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=60)]
    state: ListingState
    rows: tuple[ParsedRow, ...]
    declared_count: Count | None = Field(
        default=None, description="The number of rows the body itself claims, when it says."
    )
    skipped_rows: Count = Field(
        default=0, description="Rows the body held but that had no name to keep."
    )
    declared_at: UtcInstant | None = Field(
        default=None,
        description=(
            "When the body says its count (and list, if it holds one) was computed, "
            "when it says (a Gray Arc page's content cache entry records it); whole "
            "seconds, rounded down."
        ),
    )
    follows: tuple[Reference, ...] = Field(
        default=(),
        description=(
            "The files a count-only or deferred page loads its list from, as the page "
            "names them (possibly relative or scheme-relative), in the order it names them."
        ),
    )
    list_updated_at: UtcInstant | None = Field(
        default=None,
        description=(
            "When the body itself says its list was last changed, for a page that says "
            "so in machine-readable form (an ABC OTV page's school-closings state); the "
            "live reader treats a list last changed before the last winter began as "
            "stale, as it does a file whose Last-Modified says so. None when it does not say."
        ),
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        if (self.state is ListingState.POPULATED) != bool(self.rows):
            raise ValueError("a populated listing has rows; any other listing has none")
        if self.state is ListingState.COUNT_ONLY and not self.declared_count:
            raise ValueError("a count-only listing declares a count above zero")
        if self.state is ListingState.DEFERRED and self.declared_count is not None:
            raise ValueError("a deferred listing declares no count")
        if self.follows and self.state not in {ListingState.COUNT_ONLY, ListingState.DEFERRED}:
            raise ValueError("only a count-only or deferred listing names files to follow")
        if self.declared_at is not None and self.declared_count is None:
            raise ValueError("a listing says when its count was computed only if it gives one")
        return self


class RawRow(InternalModel):
    """One listing row, stamped with its source and the time the body was read."""

    source_id: SourceId
    fetched_at: UtcInstant
    raw_name: Annotated[str, StringConstraints(min_length=1, max_length=MAX_NAME)]
    raw_status: RawText
    raw_updated_text: RawText | None
    raw_extra: dict[str, JsonScalar]


class ViaPage(InternalModel):
    """A page read on the way to a list: it held no list and loads it from ``follows``."""

    url: Url
    fetched_at: UtcInstant = Field(description="When the page's bytes were read (capture time).")
    sha256: Sha256
    variant: str
    state: ListingState
    declared_count: Count | None = Field(
        description="The count the page itself gave, if any (a count-only page)."
    )
    count_at: UtcInstant | None = Field(
        default=None,
        description=(
            "When the page says its count was computed, if it says (see "
            "Listing.declared_at); the count may be older than the page's capture."
        ),
    )
    follows: Url = Field(description="The absolute URL of the file read next.")
    gap_seconds: int = Field(
        description="The next file's read time minus this page's (negative when read earlier)."
    )
    count_matches: bool | None = Field(
        default=None,
        description=(
            "For a page that gave a count: whether it equals the number of entries (rows "
            "plus nameless rows) in the list finally read; None when the page gave none."
        ),
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.state not in {ListingState.COUNT_ONLY, ListingState.DEFERRED}:
            raise ValueError("only a count-only or deferred page is followed")
        if (self.count_matches is None) != (self.declared_count is None):
            raise ValueError("a page's count is checked exactly when it gave one")
        if self.count_at is not None and self.declared_count is None:
            raise ValueError("a page says when its count was computed only if it gives one")
        return self


class ListingRead(InternalModel):
    """One body read from one source: where it came from and what it held.

    A list reached by following pages (``via``, outermost page first) is described
    by the list file's own URL, time and digest; the pages are in ``via``.
    """

    source_id: SourceId
    mode: ReadMode
    url: Annotated[str, StringConstraints(pattern=r"^https?://", max_length=2000)]
    fetched_at: UtcInstant
    retrieved_at: UtcInstant = Field(
        description="When these bytes were downloaded (for an archive copy, from the archive)."
    )
    sha256: Sha256
    bytes: Count
    variant: str
    state: ListingState
    rows: Count
    declared_count: Count | None
    skipped_rows: Count
    via: tuple[ViaPage, ...] = ()
    last_modified: UtcInstant | None = Field(
        default=None,
        description="The body's Last-Modified header, when the server sent one (live reads).",
    )


class HealthStatus(StrEnum):
    """How one source's read went."""

    OK = "ok"
    """Read and parsed; one or more rows."""
    EMPTY = "empty"
    """Read and parsed; the source said nothing is listed."""
    ERROR = "error"
    """The read or the parse failed."""
    STALE = "stale"
    """Read and parsed, but its list file has not changed since before the last winter."""
    SKIPPED = "skipped"
    """Not read: the registry keeps it from being polled (no endpoint, terms not read)."""


class RobotsRecord(InternalModel):
    """robots.txt's verdict on one URL read for a source (recorded, not obeyed)."""

    url: Annotated[str, StringConstraints(pattern=r"^https?://", max_length=2000)]
    state: RobotsState
    allowed: bool
    rule: Annotated[str, StringConstraints(max_length=MAX_REASON)]
    crawl_delay: Annotated[float, Field(ge=0)] | None = None


class SourceHealth(InternalModel):
    """The outcome of one attempt to read one source."""

    source_id: SourceId
    url: Annotated[str, StringConstraints(pattern=r"^https?://", max_length=2000)] | None
    checked_at: UtcInstant
    status: HealthStatus
    rows: Count
    http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    not_modified: bool = False
    sha256: Sha256 | None = None
    bytes: Count | None = None
    variant: str | None = None
    reason: Annotated[str, StringConstraints(max_length=MAX_REASON)] | None = None
    via_url: Url | None = Field(
        default=None,
        description="The page that led to ``url`` when the list was read by following it.",
    )
    last_modified: UtcInstant | None = Field(
        default=None, description="The list file's Last-Modified header, when sent."
    )
    robots: tuple[RobotsRecord, ...] = Field(
        default=(),
        description=(
            "robots.txt's verdict on each URL requested for this source (pages "
            "followed, the list file, redirect hops), in request order."
        ),
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        needs_reason = {HealthStatus.ERROR, HealthStatus.SKIPPED, HealthStatus.STALE}
        if self.status in needs_reason and not self.reason:
            raise ValueError("an error or a skip says why")
        if self.status is not HealthStatus.OK and self.rows:
            raise ValueError("only an ok read has rows")
        if self.status is HealthStatus.OK and not self.rows:
            raise ValueError("an ok read has rows; a read with none is empty")
        return self


def stale_before(now: datetime) -> datetime:
    """Return the start of the last winter that has ended by ``now`` (1 November, UTC).

    Winters run from 1 November to 31 March. On 2026-09-26 the last winter is
    2025-26, so a list file last modified before 2025-11-01 is stale; so it stays
    until the 2026-27 winter ends on 31 March 2027.
    """
    moment = now.astimezone(UTC)
    year = moment.year - 1 if moment.month > WINTER_END_MONTH else moment.year - 2
    return datetime(year, WINTER_START_MONTH, 1, tzinfo=UTC)


def count_only_reason(listing: Listing) -> str:
    """Say why a count-only or deferred listing yields no rows (health records an error)."""
    loads = f"; it loads {listing.follows[0]}" if listing.follows else ""
    if listing.state is ListingState.DEFERRED:
        return (
            "the page holds no list and no count: it loads its list after the page does; "
            f"variant {listing.variant}{loads}"
        )
    return (
        f"the page gives only a count ({listing.declared_count} listed), not the list; "
        f"variant {listing.variant}{loads}"
    )


class ShapeError(ValueError):
    """A body does not have any shape the adapter knows.

    Raised instead of returning an empty listing, so a redesigned page shows up
    as an error rather than as a day with no closings.
    """

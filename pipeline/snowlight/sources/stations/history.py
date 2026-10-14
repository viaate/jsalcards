"""A channel's dated history: the posts a feed or a site keeps, stamped by its own server.

The proven share asks whether a source's list has been seen holding closings (see
:mod:`snowlight.sources.stations.proof`): live, or in an archived capture of its page made
on a storm day. Some channels keep that record themselves. A district's Apptegy live feed
(:mod:`snowlight.sources.stations.apptegy_feed`) answers its older posts by page, each
stamped with the moment it was published; a station's closings articles
(:mod:`snowlight.sources.stations.wp_closings`) are posts WordPress stamps the same way.
Fremont County #215's feed holds "SCHOOL CLOSURE. Due to hazardous conditions with blowing
and drifting snow, ALL schools in Fremont School District will be closed today (Tuesday,
February 14)." published at 2023-02-14T05:38:00-07:00; KIFI's site, the article "School
closures and delays for Wednesday, March 6" published at 2024-03-06T13:18:52Z with 19
entries. Such a post is the list seen populated on that day, as surely as a capture the
archive made of the page that morning: the time is the server's, written when the post went
out, not a date in the text that could be a leftover's.

A *history fixture* keeps such a post: a live read (the project's User-Agent, robots.txt's
verdict recorded) of the page of the feed or the REST answer that holds it, sliced to that
one post (each adapter's ``slice_body``: a feed page's first post announcing a closing, a REST
answer's closings article; the other posts and every field the adapter does not read are
dropped), with its provenance in this folder's
``PROVENANCE.json`` (:class:`~snowlight.sources.stations.fixtures.FixtureEntry`): ``mode``
``history``, ``url`` the exact address read (with its page or search), ``retrieved_at``
when it was read, ``captured_at`` the post's own time (published, or last changed for an
article: a moment the list held it; :func:`make_entry` checks it is the post's),
``original_sha256`` and ``original_bytes`` of the whole answer as read. A feed moves on as
posts are added, so the answer cannot be downloaded again as it was; the post can (its id is
kept).

A history read proves its source only by the stricter rule of
:func:`snowlight.sources.stations.notices.history_row_proves`, which
:func:`snowlight.sources.stations.notices.gate_proofs` applies to every proof of this mode,
whatever the source: a district channel's post must announce a closing, a delay, an early
dismissal, a remote day or no school, for weather or an emergency
(:func:`snowlight.sources.stations.notices.weather_closing`: a delay counts, as it does for
the district notice gate: Johnson County #1's "all Buffalo School are on a One Hour Delay
today", 2024-02-27, under a Winter Storm Warning; so does a closing of one of a district's
schools for an emergency: Wind River's Pavillion school, closed for a water main break on
2026-08-18 while Crowheart stayed open; a station's closings article is a list, any of
whose rows is a closing); no day it names may lie outside the
window of the dated rule around its publication
(:data:`~snowlight.sources.stations.notices.DATED_BEFORE` before,
:data:`~snowlight.sources.stations.notices.DATED_AFTER` after: a post that names an old day
is a leftover, not that day's news); and the NWS must corroborate the weather: an advisory
or warning (:data:`~snowlight.sources.stations.notices.CORROBORATING_WEIGHT`) over one of the
source's counties on the school day it was published (a post made from about 4 PM local time
on is about the next morning) or, when that is a weekend, the Monday after; or the
post names an emergency the weather service does not record (a power outage, a water main
break, a boil-water notice, an evacuation: :data:`~snowlight.sources.stations.notices.EMERGENCY`).
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from snowlight.output import write_bytes_atomic
from snowlight.sources.stations import apptegy_feed, wp_closings
from snowlight.sources.stations.fixtures import (
    PROVENANCE_FILE,
    README_FILE,
    Expected,
    FixtureEntry,
    load_entries,
)
from snowlight.sources.stations.model import ReadMode
from snowlight.sources.stations.registry import PIPELINE_ROOT

DEFAULT_FOLDER = PIPELINE_ROOT / "tests" / "stations" / "fixtures" / "history"
SLICERS = {
    "apptegy-feed-closings-v2": apptegy_feed.slice_body,
    "wp-closings-articles-v2": wp_closings.slice_body,
}
"""Slicing methods by name. A method's output never changes once fixtures use it."""


@dataclass(frozen=True, slots=True)
class Origin:
    """Where a history fixture's answer came from."""

    source_id: str
    adapter: str
    url: str
    retrieved_at: str
    published_at: str


def make_entry(
    file: str, origin: Origin, original: bytes, method: str, note: str
) -> tuple[FixtureEntry, bytes]:
    """Slice an answer read live into a history fixture, and describe it.

    The slice keeps fewer rows than the answer (the closings only), so unlike an adapter
    fixture it is not required to read as the original does; it must read as a populated
    list in the adapter's variant.

    Raises:
        ValueError: the slice holds no row.
    """
    from snowlight.sources.stations.adapters import ADAPTERS  # noqa: PLC0415 - import cycle

    sliced = SLICERS[method](original)
    listing = ADAPTERS[origin.adapter](sliced)
    if not listing.rows:
        raise ValueError(f"{file}: the {method} slice holds no row")
    times = {row.updated_text for row in listing.rows}
    if len(times) != 1 or _instant(times.pop()) != _instant(origin.published_at):
        raise ValueError(f"{file}: the slice is not one post published at {origin.published_at}")
    expected = Expected(
        variant=listing.variant,
        state=listing.state,
        rows=len(listing.rows),
        names=tuple(row.name for row in listing.rows),
    )
    entry = FixtureEntry.model_validate(
        {
            "file": file,
            "source_id": origin.source_id,
            "adapter": origin.adapter,
            "mode": ReadMode.HISTORY,
            "url": origin.url,
            "captured_at": origin.published_at,
            "archive_url": None,
            "retrieved_at": origin.retrieved_at,
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "original_bytes": len(original),
            "slice": method,
            "sha256": hashlib.sha256(sliced).hexdigest(),
            "bytes": len(sliced),
            "expected": expected,
            "note": note,
        }
    )
    return entry, sliced


def _instant(text: str | None) -> datetime | None:
    """An ISO 8601 time as a UTC instant to the second (None for none)."""
    if text is None:
        return None
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment.astimezone(UTC).replace(microsecond=0)


def render_readme(entries: Sequence[FixtureEntry]) -> str:
    """The history fixtures' README, from their provenance."""
    lines = [
        "# History fixtures",
        "",
        "Each file is a real answer read live with the project's User-Agent (robots.txt's",
        "verdict recorded): a page of a district's Apptegy live feed, or a station's",
        "WordPress REST answer of closings articles, sliced to the post that announces a",
        "closing (the method named below, `snowlight.sources.stations.history.SLICERS`).",
        "`Published` is the post's own time as its server stamped it (when it was published,",
        "or last changed for an article: a moment the list held it); `Retrieved` is when the",
        "answer was read. A feed moves on as",
        "posts are added, so the answer cannot be downloaded again as it was: its SHA-256",
        "is the one read. See `snowlight.sources.stations.history` for the rule such a",
        "post proves its source by.",
        "",
        "This file is generated from `PROVENANCE.json`; edit that, not this.",
        "",
        "| File | Source | URL | Published (UTC) | Retrieved (UTC) | Original SHA-256 | Slice"
        " | Variant | Rows |",
        "|---|---|---|---|---|---|---|---|---:|",
    ]
    for entry in entries:
        lines.append(
            f"| `{entry.file}` | {entry.source_id} | {entry.url}"
            f" | {entry.captured_at:%Y-%m-%d %H:%M:%S} | {entry.retrieved_at:%Y-%m-%d %H:%M:%S}"
            f" | `{entry.original_sha256[:16]}…` ({entry.original_bytes} bytes) | {entry.slice}"
            f" | {entry.expected.variant} | {entry.expected.rows} |"
        )
    notes = [entry for entry in entries if entry.note]
    if notes:
        lines += ["", "Notes:", ""]
        lines += [f"- `{entry.file}`: {entry.note}" for entry in notes]
    return "\n".join(lines) + "\n"


def write_fixtures(folder: Path, entries: Sequence[tuple[FixtureEntry, bytes]]) -> None:
    """Add or replace history fixtures, then rewrite ``PROVENANCE.json`` and ``README.md``."""
    current = {entry.file: entry for entry in load_entries(folder)}
    for entry, body in entries:
        write_bytes_atomic(folder / entry.file, body)
        current[entry.file] = entry
    ordered = [current[name] for name in sorted(current)]
    data = [entry.model_dump(mode="json") for entry in ordered]
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    write_bytes_atomic(folder / PROVENANCE_FILE, text.encode("utf-8"))
    write_bytes_atomic(folder / README_FILE, render_readme(ordered).encode("utf-8"))

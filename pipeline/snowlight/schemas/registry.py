"""Every published JSON file, the path the site serves it at, and its model.

This is the list :mod:`snowlight.schemas.export` turns into ``schemas/*.schema.json``
and ``npm run gen:types`` turns into TypeScript. A new published JSON file is added
here, and nowhere else.

Paths are relative to the site's data root (``pipeline/out/site-data`` when built
locally). ``{id}`` stands for a replay id.

Published files that are not JSON documents have no model and are listed in
:data:`OTHER_PUBLISHED_FILES` instead: ``schools/points.bin`` (byte layout in
:mod:`snowlight.directory.points`), ``schools/schools.pmtiles`` (vector tiles,
:mod:`snowlight.directory.tiles`), the search index (``web/src/search/format.ts``)
and its JSON Lines inputs (checked by :mod:`snowlight.places.records`).

A file whose name ends in :data:`INTERNAL_SUFFIX` may sit in the site-data folder
next to what it describes (``schools/manifest.internal.json``), but is never
published. Any other file there that is in neither list is a mistake, and
:func:`snowlight.schemas.site.validate_site` reports it.
"""

from dataclasses import dataclass

from snowlight.schemas.base import PublishedModel
from snowlight.schemas.directory import SchoolDirectoryMeta
from snowlight.schemas.live import AlertsFile, ClosingsFile, CoveredFile
from snowlight.schemas.predictions import PredictionsFile
from snowlight.schemas.replays import ReplayFile, ReplayIndex
from snowlight.schemas.stats import SeasonStats, TrackRecord


@dataclass(frozen=True, slots=True)
class PublishedFile:
    """One published JSON file."""

    name: str
    path: str
    model: type[PublishedModel]


PUBLISHED_FILES: tuple[PublishedFile, ...] = (
    PublishedFile("school-directory", "schools/meta.json", SchoolDirectoryMeta),
    PublishedFile("closings", "live/closings.json", ClosingsFile),
    PublishedFile("covered", "live/covered.json", CoveredFile),
    PublishedFile("alerts", "live/alerts.json", AlertsFile),
    PublishedFile("predictions", "predictions/latest.json", PredictionsFile),
    PublishedFile("season-stats", "stats/season.json", SeasonStats),
    PublishedFile("track-record", "track-record.json", TrackRecord),
    PublishedFile("replay-index", "replays/index.json", ReplayIndex),
    PublishedFile("replay", "replays/{id}.json", ReplayFile),
)

BY_NAME: dict[str, PublishedFile] = {entry.name: entry for entry in PUBLISHED_FILES}

# Published files that are not JSON documents: their builders check them. Text files
# among them (the .jsonl search inputs) are still scanned for addresses and source
# names before publishing.
OTHER_PUBLISHED_FILES: tuple[str, ...] = (
    "schools/points.bin",
    "schools/schools.pmtiles",
    "search-index.bin",
    "search/cities.jsonl",
    "search/zips.jsonl",
)

# Files ending in this are the pipeline's own records: never published.
INTERNAL_SUFFIX = ".internal.json"

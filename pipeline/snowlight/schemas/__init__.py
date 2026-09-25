"""The contract between the pipeline and the site: one pydantic model per published file.

From models to the browser::

    pipeline/snowlight/schemas/*.py      pydantic models (this package)
        | uv run python -m snowlight.schemas
    schemas/*.schema.json                 JSON Schema 2020-12, plus fingerprint.json
        | npm run gen:types                (web/scripts/gen-types.mjs)
    web/src/types/generated/index.ts      TypeScript types and code tables

Both steps are deterministic, and each test suite fails when its generated files
are stale: ``pytest`` compares ``schemas/`` with the models and runs the type
generator's ``--check``; ``npm run check`` compares the fingerprint the types were
generated from with ``schemas/fingerprint.json``.

* :mod:`~snowlight.schemas.base`: published and internal models, and the guard that
  keeps source names and URLs out of published ones.
* :mod:`~snowlight.schemas.scalars` and :mod:`~snowlight.schemas.vocab`: shared scalar
  types and code tables.
* :mod:`~snowlight.schemas.directory`, :mod:`~snowlight.schemas.live`,
  :mod:`~snowlight.schemas.predictions`, :mod:`~snowlight.schemas.stats` and
  :mod:`~snowlight.schemas.replays`: the published files.
* :mod:`~snowlight.schemas.internal`: provenance records, never published, and the
  projections from them to published files.
* :mod:`~snowlight.schemas.registry` and :mod:`~snowlight.schemas.export`: the list
  of published files and the JSON Schema writer.
"""

from snowlight.schemas.base import (
    InternalModel,
    PublishedContentError,
    PublishedModel,
    check_published_bytes,
    screen_text,
)
from snowlight.schemas.directory import DirectoryStamp, SchoolDirectoryMeta
from snowlight.schemas.internal import (
    ClosingObservation,
    ConflictError,
    CoverageObservation,
    RunManifest,
    SourceSnapshot,
    closings_file,
    covered_file,
)
from snowlight.schemas.live import (
    Alert,
    AlertsFile,
    Closing,
    ClosingsDay,
    ClosingsFile,
    CoveredFile,
    check_live_pair,
    ranges_from_indices,
)
from snowlight.schemas.predictions import (
    DistrictForecast,
    Forecast,
    NotEnoughData,
    NoThreat,
    PredictionsFile,
)
from snowlight.schemas.registry import PUBLISHED_FILES, PublishedFile
from snowlight.schemas.replays import ReplayFile, ReplayIndex, ReplaySummary, check_summary
from snowlight.schemas.stats import Calibration, LeadRecord, SeasonStats, TrackRecord
from snowlight.schemas.vocab import Reason, Status

__all__ = [
    "PUBLISHED_FILES",
    "Alert",
    "AlertsFile",
    "Calibration",
    "Closing",
    "ClosingObservation",
    "ClosingsDay",
    "ClosingsFile",
    "ConflictError",
    "CoverageObservation",
    "CoveredFile",
    "DirectoryStamp",
    "DistrictForecast",
    "Forecast",
    "InternalModel",
    "LeadRecord",
    "NoThreat",
    "NotEnoughData",
    "PredictionsFile",
    "PublishedContentError",
    "PublishedFile",
    "PublishedModel",
    "Reason",
    "ReplayFile",
    "ReplayIndex",
    "ReplaySummary",
    "RunManifest",
    "SchoolDirectoryMeta",
    "SeasonStats",
    "SourceSnapshot",
    "Status",
    "TrackRecord",
    "check_live_pair",
    "check_published_bytes",
    "check_summary",
    "closings_file",
    "covered_file",
    "ranges_from_indices",
    "screen_text",
]

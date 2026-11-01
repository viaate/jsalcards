"""The one adapter from the outcome-blind live labels (advisory-sane L1) to the class anchor's
live update (:mod:`snowlight.predict.anchor`, Addendum B2).

L1 (:mod:`snowlight.predict.live_read`) keeps its private record in its ``READS_DIR``,
``out/internal/predict/reads/`` (restored from its own Actions cache before the passes):
``rows/<day>.json``, one labeled school day (its ``ReadDay``: the alerted districts' rows,
``district``, ``weather`` (the class number), ``after``, ``label``, ``tier``, ``market``, and
``sources``, the lists that read it, counted only), and ``trials/<day>.jsonl``, its
co-listing trials (``tier``, ``named``). The folder is L1's own constant; the files are read
as plain JSON, so a day L1's models would refuse is left out and said here, never fatal.

Only rows a read labeled (``no_school``, ``delayed``, ``unnamed``, the last counting open, the
owner's O5) with a tier enter; ``unknown`` and ``not_read`` rows do not. With no record (no day
labeled yet, or the reads cache lost it) the labels are empty and the anchor serves its prior's
level, which is correct. A day that does not read is left out and said, never fatal: a broken
day must not darken a pass.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Final, cast

from snowlight.predict import live_read
from snowlight.predict.anchor import (
    Anchor,
    AnchorSettings,
    LabelKind,
    LiveLabels,
    LiveRow,
    Plausible,
    Tier,
    Trials,
    fit,
)
from snowlight.predict.artifact import ModelArtifact
from snowlight.predict.config import PIPELINE_ROOT, PredictConfig
from snowlight.predict.exposure import EXPOSURE_PATH, Exposure
from snowlight.predict.exposure import load as load_exposure
from snowlight.predict.geography import REGION_OF
from snowlight.predict.situations import Situation, WeatherClass

READS_DIR: Final = live_read.READS_DIR
"""L1's private record."""
LABELS: Final[frozenset[str]] = frozenset({"no_school", "delayed", "unnamed"})
TIERS: Final[frozenset[str]] = frozenset({"A", "B"})
RECORD_SCHEMA: Final = 1


def _day_of(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


def _rows(day: date, body: object) -> list[LiveRow]:
    """One day's labeled rows.

    Raises:
        ValueError: the day's file is not one L1 writes.
    """
    if not isinstance(body, dict) or body.get("schema_version") != RECORD_SCHEMA:
        raise ValueError("not a read day of schema 1")
    if body.get("day") != day.isoformat():
        raise ValueError(f"names day {body.get('day')!r}")
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise ValueError("no rows")
    found: list[LiveRow] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("a row is not an object")
        label, tier = row.get("label"), row.get("tier")
        if label not in LABELS or tier not in TIERS:
            continue
        district, weather, market = row.get("district"), row.get("weather"), row.get("market")
        if not isinstance(district, str) or not isinstance(weather, int):
            raise ValueError("a row has no district or class")
        situation = Situation.of(WeatherClass(weather), row.get("after") is True)
        sources = row.get("sources")
        lists = len({s for s in sources if isinstance(s, str)}) if isinstance(sources, list) else 0
        found.append(
            LiveRow(
                day=day,
                district=district,
                market=market if isinstance(market, str) else None,
                tier=cast("Tier", tier),
                label=cast("LabelKind", label),
                weather=situation.key,
                lists=max(lists, 1),
            )
        )
    return found


def _trials(
    path: Path, day: date, tally: dict[str, list[int]], dates: dict[str, set[date]]
) -> None:
    """Add one day's closed co-listing trials (hits, trials) per tier.

    Raises:
        ValueError: a line does not read.
    """
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        trial = json.loads(line)
        tier = trial.get("tier") if isinstance(trial, dict) else None
        named = trial.get("named") if isinstance(trial, dict) else None
        if tier not in TIERS or not isinstance(named, bool):
            raise ValueError("a trial has no tier or naming")
        found = tally.setdefault(str(tier), [0, 0])
        found[0] += int(named)
        found[1] += 1
        dates.setdefault(str(tier), set()).add(day)


def read_labels(
    folder: Path = READS_DIR,
    *,
    since: date | None = None,
    warn: Callable[[str], None] = lambda _line: None,
) -> LiveLabels:
    """The record's labeled rows and trials (empty, ``found`` false, when there is none).

    ``since``: the first day the fit reads (``live_update.fit_from``); a day file before it is
    skipped by its name, unread, with its trials, so a record kept forever costs each process
    only the days the fit can use (R3-S4)."""
    root = folder / "rows"
    if not root.is_dir():
        return LiveLabels()
    rows: list[LiveRow] = []
    tally: dict[str, list[int]] = {}
    dates: dict[str, set[date]] = {}
    days = 0
    for path in sorted(root.glob("*.json")):
        day = _day_of(path)
        if day is None or (since is not None and day < since):
            continue
        try:
            found = _rows(day, json.loads(path.read_text(encoding="utf-8")))
            trials = folder / "trials" / f"{day.isoformat()}.jsonl"
            mine: dict[str, list[int]] = {}
            mine_dates: dict[str, set[date]] = {}
            if trials.is_file():
                _trials(trials, day, mine, mine_dates)
        except (OSError, ValueError, KeyError) as error:
            warn(f"anchor: the live labels of {day}: {type(error).__name__}: left out")
            continue
        rows.extend(found)
        for tier, (hits, count) in mine.items():
            total = tally.setdefault(tier, [0, 0])
            total[0] += hits
            total[1] += count
        for tier, seen in mine_dates.items():
            dates.setdefault(tier, set()).update(seen)
        days += 1
    return LiveLabels(
        rows=tuple(rows),
        trials={
            cast("Tier", tier): Trials(hits=hits, trials=count, dates=len(dates.get(tier, ())))
            for tier, (hits, count) in sorted(tally.items())
        },
        days=days,
        found=True,
    )


ANCHOR_REPORT: Final = PIPELINE_ROOT / "out" / "internal" / "predict" / "anchor.json"
"""The private report of the class levels a process serves (never published)."""


def serving_anchor(
    config: PredictConfig,
    artifact: ModelArtifact,
    *,
    folder: Path = READS_DIR,
    exposure_path: Path = EXPOSURE_PATH,
    warn: Callable[[str], None] = lambda _line: None,
) -> Anchor | None:
    """The class anchor a serving process uses (``serve.anchor``; off: ``None``), fitted on
    the live labels the record holds now (Addendum A item 4: refreshed with each day's run).

    An exposure file that does not read leaves every unit at its class level (no exposure
    term, no region delta) and says so: never back to an archive closure share."""
    if not config.serve.anchor:
        return None
    settings = AnchorSettings.of(config)
    try:
        exposure = load_exposure(exposure_path)
    except (OSError, ValueError, KeyError) as error:
        warn(f"anchor: the exposure file: {type(error).__name__}: serving the class levels alone")
        exposure = Exposure((), {}, {}, {}, {}, {})
    labels = read_labels(folder, since=settings.fit_from, warn=warn)
    places = {
        leaid: (entry.county, REGION_OF.get(entry.state) if entry.state else None)
        for leaid, entry in artifact.districts.items()
    }
    return fit(settings, exposure, labels, places)


def anchor_line(anchor: Anchor) -> str:
    """One log line: each class's level at the reference district with its 80% band, its
    delay share and the live rows it rests on."""
    parts = []
    for key, found in anchor.fits.items():
        low, high = found.band
        parts.append(
            f"{key} {float(found.level(0.0)):.3f} ({low:.3f}-{high:.3f}) q {found.q:.3f} "
            f"rows {found.rows} on {found.dates} dates"
        )
    record = f"{anchor.labels.days} labeled days" if anchor.labels.found else "no read record"
    return f"anchor: {'; '.join(parts)}; {record}"


def write_report(
    anchor: Anchor, path: Path = ANCHOR_REPORT, *, plausible: Plausible | None = None
) -> None:
    """Keep the private report (``anchor.json``), with what the plausibility check did on the
    served districts once a serving model is built (``plausible``)."""
    body = anchor.summary()
    if plausible is not None:
        body["plausibility"] = plausible.summary()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, sort_keys=True, indent=1) + "\n", encoding="utf-8")

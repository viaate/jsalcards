"""Check a built site-data folder against the contract before it is published.

:func:`validate_site` accounts for every file under a site-data root
(``pipeline/out/site-data`` when built locally):

* each published JSON file is validated strictly against its model;
* each other published file (:data:`~snowlight.schemas.registry.OTHER_PUBLISHED_FILES`)
  is listed, and the text ones are scanned for addresses and source names;
* each ``*.internal.json`` file is listed as skipped: it is never published, and
  the publishing step must leave it out;
* any other file is a problem: nothing in the site reads it, and nothing has
  checked that it is fit to publish.

Then it checks the published files against each other:

* every file with a :class:`~snowlight.schemas.directory.DirectoryStamp` points into
  the ``schools/meta.json`` beside it;
* ``live/closings.json`` and ``live/covered.json`` come from the same run;
* every replay file is named by its id, and every entry of ``replays/index.json``
  has a file whose frames it describes.

Published files that are absent are skipped (a site can go live before it has
predictions); files that are present must be right. Run it from ``pipeline/``::

    uv run python -m snowlight.schemas --validate out/site-data
"""

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from snowlight.schemas.base import PublishedContentError, PublishedModel, check_published_bytes
from snowlight.schemas.directory import DirectoryStamp, SchoolDirectoryMeta
from snowlight.schemas.live import ClosingsFile, CoveredFile, check_live_pair
from snowlight.schemas.registry import (
    BY_NAME,
    INTERNAL_SUFFIX,
    OTHER_PUBLISHED_FILES,
    PUBLISHED_FILES,
    PublishedFile,
)
from snowlight.schemas.replays import ReplayFile, ReplayIndex, check_summary

_REPLAY_DIR = "replays"
_REPLAY_INDEX = "index.json"
_TEXT_SUFFIXES = (".json", ".jsonl")


@dataclass(slots=True)
class SiteReport:
    """What :func:`validate_site` found, by path relative to the site-data root.

    ``checked`` files were validated against their model, ``scanned`` ones are
    other published text files, ``unchecked`` ones are other published binary
    files (their builders check them), and ``skipped`` ones are never published.
    """

    checked: list[str] = field(default_factory=list)
    scanned: list[str] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def published(self) -> list[str]:
        """Every file the site would serve, sorted."""
        return sorted([*self.checked, *self.scanned, *self.unchecked])


def _load[M: PublishedModel](
    model: type[M], path: Path, shown: str, report: SiteReport
) -> M | None:
    data = path.read_bytes()
    try:
        document = model.from_json_bytes(data)
        check_published_bytes(data)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        at = f" at {where}" if where else ""
        report.problems.append(
            f"{shown}: {error.error_count()} problem(s); first{at}: {first['msg']}"
        )
        return None
    except PublishedContentError as error:
        report.problems.append(f"{shown}: {error}")
        return None
    report.checked.append(shown)
    return document


def _single(entry: PublishedFile, root: Path, report: SiteReport) -> PublishedModel | None:
    path = root / entry.path
    if not path.is_file():
        return None
    return _load(entry.model, path, entry.path, report)


def _load_replays(root: Path, report: SiteReport) -> dict[str, ReplayFile]:
    replays: dict[str, ReplayFile] = {}
    replay_dir = root / _REPLAY_DIR
    if not replay_dir.is_dir():
        return replays
    for path in sorted(replay_dir.glob("*.json")):
        if path.name == _REPLAY_INDEX:
            continue
        shown = f"{_REPLAY_DIR}/{path.name}"
        replay = _load(ReplayFile, path, shown, report)
        if replay is None:
            continue
        if replay.id != path.stem:
            report.problems.append(f"{shown}: holds replay {replay.id}")
        replays[path.stem] = replay
    return replays


def _check_stamps(
    root: Path,
    loaded: dict[str, PublishedModel],
    replays: dict[str, ReplayFile],
    report: SiteReport,
) -> None:
    stamped: list[tuple[str, DirectoryStamp]] = [
        (name, directory)
        for name, document in loaded.items()
        if isinstance(directory := getattr(document, "directory", None), DirectoryStamp)
    ]
    stamped.extend((f"replay {key}", replay.directory) for key, replay in replays.items())
    meta = loaded.get("school-directory")
    if not isinstance(meta, SchoolDirectoryMeta):
        if stamped and not (root / BY_NAME["school-directory"].path).exists():
            report.problems.append("schools/meta.json is missing, so no index can be checked")
        return
    stamp = meta.stamp()
    report.problems.extend(
        f"{name}: indexes directory {directory}, but meta.json is {stamp}"
        for name, directory in stamped
        if directory != stamp
    )


def _check_live(root: Path, loaded: dict[str, PublishedModel], report: SiteReport) -> None:
    closings, covered = loaded.get("closings"), loaded.get("covered")
    if isinstance(closings, ClosingsFile) and isinstance(covered, CoveredFile):
        try:
            check_live_pair(closings, covered)
        except ValueError as error:
            report.problems.append(str(error))
    present = [(root / BY_NAME[name].path).exists() for name in ("closings", "covered")]
    if any(present) and not all(present):
        report.problems.append("live/closings.json and live/covered.json are published together")


def _check_replays(
    root: Path,
    loaded: dict[str, PublishedModel],
    replays: dict[str, ReplayFile],
    report: SiteReport,
) -> None:
    index = loaded.get("replay-index")
    if not isinstance(index, ReplayIndex):
        if replays and not (root / BY_NAME["replay-index"].path).exists():
            report.problems.append("replay files are published without replays/index.json")
        return
    for summary in index.replays:
        replay = replays.get(summary.id)
        if replay is None:
            report.problems.append(f"replays/index.json lists {summary.id}, which has no file")
            continue
        try:
            check_summary(summary, replay)
        except ValueError as error:
            report.problems.append(str(error))
    listed = {summary.id for summary in index.replays}
    report.problems.extend(
        f"replays/{key}.json is not in replays/index.json"
        for key in sorted(replays)
        if key not in listed
    )


def _is_replay(path: str) -> bool:
    folder, _, name = path.partition("/")
    return folder == _REPLAY_DIR and "/" not in name and name.endswith(".json")


def _account_for_others(root: Path, report: SiteReport) -> None:
    """Scan, list or refuse every file that no model covers."""
    modeled = {entry.path for entry in PUBLISHED_FILES if "{id}" not in entry.path}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        shown = path.relative_to(root).as_posix()
        if shown in modeled or _is_replay(shown):
            continue
        if shown.endswith(INTERNAL_SUFFIX):
            report.skipped.append(shown)
        elif shown not in OTHER_PUBLISHED_FILES:
            report.problems.append(
                f"{shown}: not a published file; register it in snowlight.schemas.registry "
                f"or, if it is the pipeline's own record, name it *{INTERNAL_SUFFIX}"
            )
        elif shown.endswith(_TEXT_SUFFIXES):
            try:
                check_published_bytes(path.read_bytes())
            except (PublishedContentError, UnicodeDecodeError) as error:
                report.problems.append(f"{shown}: {error}")
            else:
                report.scanned.append(shown)
        else:
            report.unchecked.append(shown)


def validate_site(root: Path) -> SiteReport:
    """Validate every file under ``root``, alone and together (see the module docstring)."""
    report = SiteReport()
    if root.is_dir():
        _account_for_others(root, report)
    loaded = {
        entry.name: document
        for entry in PUBLISHED_FILES
        if "{id}" not in entry.path and (document := _single(entry, root, report)) is not None
    }
    replays = _load_replays(root, report)
    _check_stamps(root, loaded, replays, report)
    _check_live(root, loaded, report)
    _check_replays(root, loaded, replays, report)
    return report

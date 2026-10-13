"""The committed replay seeds, ``pipeline/data/replays/<D>.json``.

Each committed seed must validate, be named by its day, be a school day (a
weekday, not a holiday), light at least :data:`MIN_LIT` schools with sorted,
unique NCES ids, hold nothing but ids, dates, hashes and its own words (the
raw-text scan), and have been built by the status reader and matcher of this
tree. A seed whose reader or matcher hash differs fails here; the way out is
``snowlight replays build --day D --write-seed`` against the archive, and a
re-audit when any status changes (the replay spec, section 4.8).

The matcher hash covers the NWS counties its place guard read, so it is
recomputed only where the county file is cached (it is after any local
``replays build``); elsewhere that one check is skipped and says so.

Until a seed is committed the per-seed tests are skipped; the checks
themselves run on SYNTHETIC seeds below.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import pytest

from snowlight.output import JSONValue
from snowlight.replays.build import MIN_LIT
from snowlight.replays.cli import DEFAULT_ALIASES, DEFAULT_SEEDS, PIPELINE_ROOT
from snowlight.replays.gates import holidays
from snowlight.replays.seed import (
    Built,
    Quality,
    ReplaySeed,
    counties_sha256,
    matcher_sha256,
    read_seed,
    reader_sha256,
    unsafe_strings,
    write_seed,
)
from snowlight.weights.cache import DEFAULT_CACHE_DIR, SIBLING_CACHE_DIRS, cache_path
from snowlight.weights.zones import COUNTY_RELEASE, read_counties

SEEDS: Final = sorted(DEFAULT_SEEDS.glob("*.json")) if DEFAULT_SEEDS.is_dir() else []
SATURDAY: Final = 5


@dataclass(frozen=True, slots=True)
class Tree:
    """This tree's reader and matcher hashes; ``None`` where it cannot say."""

    reader: str | None
    matcher: str | None


def tree_hashes(root: Path = PIPELINE_ROOT, aliases: Path = DEFAULT_ALIASES) -> Tree:
    """The reader hash (``None`` without ``snowlight/classify``) and the matcher hash
    (``None`` without a cached NWS county file)."""
    try:
        reader: str | None = reader_sha256(root)
    except FileNotFoundError:
        reader = None
    cached = [
        cache_path(folder, COUNTY_RELEASE.url)
        for folder in (DEFAULT_CACHE_DIR, *SIBLING_CACHE_DIRS)
    ]
    found = next((path for path in cached if path.is_file()), None)
    try:
        matcher = (
            None
            if found is None
            else matcher_sha256(root, aliases, counties_sha256(read_counties(found)))
        )
    except FileNotFoundError:
        matcher = None
    return Tree(reader, matcher)


def seed_problems(path: Path, tree: Tree) -> list[str]:
    """Why the committed seed at ``path`` may not ship; [] when it may."""
    try:
        seed = read_seed(path)
    except ValueError as error:
        return [f"not a valid seed: {str(error).splitlines()[0]}"]
    problems: list[str] = []
    if path.name != f"{seed.id}.json":
        problems.append(f"named {path.name}, holds {seed.id}")
    day = date.fromisoformat(seed.day)
    if day.weekday() >= SATURDAY:
        problems.append(f"{seed.day} is a weekend day")
    if day in holidays(day.year):
        problems.append(f"{seed.day} is a holiday")
    if len(seed.statuses) < MIN_LIT:
        problems.append(f"{len(seed.statuses)} statuses, fewer than {MIN_LIT}")
    ids = [status[0] for status in seed.statuses]
    if ids != sorted(set(ids)):
        problems.append("ids are not sorted and unique")
    text = unsafe_strings(seed.as_json())
    if text:
        problems.append(f"{len(text)} strings that are not ids, dates, hashes or its words")
    if tree.reader is None:
        problems.append("this tree has no status reader (snowlight/classify) to check against")
    elif seed.built.reader_sha256 != tree.reader:
        problems.append("built by another status reader than this tree's")
    if tree.matcher is not None and seed.built.matcher_sha256 != tree.matcher:
        problems.append("built by another matcher than this tree's")
    return problems


@pytest.mark.skipif(not SEEDS, reason="no seed is committed in pipeline/data/replays")
@pytest.mark.parametrize("path", SEEDS, ids=[path.name for path in SEEDS])
def test_each_committed_seed_may_ship(path: Path) -> None:
    tree = tree_hashes()
    assert seed_problems(path, tree) == []
    if tree.matcher is None:
        pytest.skip("matcher hash not checked: no cached NWS county file (run replays build)")


# SYNTHETIC seeds: invented ids (99...), invented hashes.

READER: Final = "a" * 64
MATCHER: Final = "b" * 64
TREE: Final = Tree(READER, MATCHER)


def _seed(day: str = "2026-01-05", lit: int = MIN_LIT, **built: str) -> ReplaySeed:
    statuses = tuple((f"99{n:010d}", 0, 0, "station_list") for n in range(lit))
    return ReplaySeed(
        schema_version=1,
        id=day,
        day=day,
        built=Built(
            rules="replay-1",
            rules_sha256="e" * 64,
            min_confidence=0.8,
            allowed_notes=("undated", "unread_words"),
            reader_sha256=built.get("reader", READER),
            matcher_sha256=built.get("matcher", MATCHER),
            registry_sha256="c" * 64,
            archive_sha256="d" * 64,
            zones_sha256="f" * 64,
            directory_generated_on="2025-12-01",
        ),
        quality=Quality(lit=lit, sources=2, markets=2, corroborated=0, conflicts=0),
        statuses=statuses,  # type: ignore[arg-type]  # status codes as the JSON holds them
    )


def _write(tmp_path: Path, seed: ReplaySeed, name: str | None = None) -> Path:
    path = tmp_path / (name or f"{seed.id}.json")
    write_seed(path, seed)
    return path


def test_a_good_synthetic_seed_may_ship(tmp_path: Path) -> None:
    assert seed_problems(_write(tmp_path, _seed()), TREE) == []


@pytest.mark.parametrize(
    ("seed", "name", "problem"),
    [
        (_seed("2026-01-03"), None, "2026-01-03 is a weekend day"),
        (_seed("2024-01-15"), None, "2024-01-15 is a holiday"),
        (_seed("2025-01-20"), None, "2025-01-20 is a holiday"),
        (_seed("2025-02-17"), None, "2025-02-17 is a holiday"),
        (_seed(lit=MIN_LIT - 1), None, f"{MIN_LIT - 1} statuses, fewer than {MIN_LIT}"),
        (_seed(), "2026-01-06.json", "named 2026-01-06.json, holds 2026-01-05"),
        (_seed(reader="0" * 64), None, "built by another status reader than this tree's"),
        (_seed(matcher="0" * 64), None, "built by another matcher than this tree's"),
    ],
)
def test_a_synthetic_seed_that_may_not_ship(
    tmp_path: Path, seed: ReplaySeed, name: str | None, problem: str
) -> None:
    assert seed_problems(_write(tmp_path, seed, name), TREE) == [problem]


def test_the_raw_text_scan_runs_on_every_committed_seed(tmp_path: Path) -> None:
    path = _write(tmp_path, _seed())
    value: JSONValue = json.loads(path.read_bytes())
    assert isinstance(value, dict)
    built = value["built"]
    assert isinstance(built, dict)
    built["allowed_notes"] = ["undated", "Closed Tuesday"]
    path.write_text(json.dumps(value))
    assert seed_problems(path, TREE) == ["1 strings that are not ids, dates, hashes or its words"]


def test_a_seed_that_does_not_validate(tmp_path: Path) -> None:
    path = tmp_path / "2026-01-05.json"
    path.write_text("{}")
    (problem,) = seed_problems(path, TREE)
    assert problem.startswith("not a valid seed")


def test_a_tree_without_a_reader_checks_no_seed(tmp_path: Path) -> None:
    path = _write(tmp_path, _seed())
    assert seed_problems(path, Tree(None, MATCHER)) == [
        "this tree has no status reader (snowlight/classify) to check against"
    ]


def test_without_cached_counties_the_matcher_is_not_checked(tmp_path: Path) -> None:
    path = _write(tmp_path, _seed(matcher="0" * 64))
    assert seed_problems(path, Tree(READER, None)) == []


def test_the_tree_hashes_follow_the_reader_files(tmp_path: Path) -> None:
    assert tree_hashes(tmp_path, tmp_path / "aliases.yaml").reader is None
    classify = tmp_path / "snowlight" / "classify"
    classify.mkdir(parents=True)
    (classify / "parse.py").write_text("# SYNTHETIC reader\n")
    first = tree_hashes(tmp_path, tmp_path / "aliases.yaml").reader
    (classify / "parse.py").write_text("# SYNTHETIC reader, changed\n")
    assert first is not None
    assert tree_hashes(tmp_path, tmp_path / "aliases.yaml").reader not in {None, first}

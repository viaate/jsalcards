"""``snowlight replays publish``: SYNTHETIC seeds against a SYNTHETIC directory.

No real school, station, list or storm day is described here: the schools are
invented (ids ``99...`` and ``A99...``), and so are the seeds' statuses.
"""

import gzip
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from snowlight.cli import main
from snowlight.output import JSONValue, write_json
from snowlight.replays import publish as publishing
from snowlight.replays.publish import (
    PublishError,
    follows_day_convention,
    publish,
    read_schools,
)
from snowlight.replays.seed import Built, Quality, ReplaySeed, write_seed
from snowlight.schemas.replays import ReplayFile, ReplayIndex, check_summary
from snowlight.schemas.site import validate_site

NOW = datetime(2026, 1, 7, 13, 0, tzinfo=UTC)
DAY = "2026-01-05"  # a Monday, two days before NOW
STATES = ("KS", "MO", "NE")
BUILT = Built(
    rules="replay-1",
    rules_sha256="e" * 64,
    min_confidence=0.8,
    allowed_notes=("undated", "unread_words"),
    reader_sha256="a" * 64,
    matcher_sha256="b" * 64,
    registry_sha256="c" * 64,
    archive_sha256="d" * 64,
    zones_sha256="f" * 64,
    directory_generated_on="2025-12-01",
)


def public_id(number: int) -> str:
    return f"99{number:010d}"


PRIVATE = ("A9900001", "A9900002")


def directory_ids(publics: int) -> list[str]:
    return [*(public_id(n) for n in range(publics)), *PRIVATE]


def write_directory(root: Path, publics: int = 6000, *, generated_on: str = "2026-01-06") -> Path:
    """A SYNTHETIC directory build: ``internal/directory/schools.parquet`` and
    ``site/schools/meta.json``. Returns the site root."""
    sids: list[JSONValue] = list(directory_ids(publics))
    names: list[JSONValue] = [f"Synthetic School {n}" for n in range(len(sids))]
    frame = pl.DataFrame(
        {
            "index": pl.Series(range(len(sids)), dtype=pl.UInt32),
            "id": sids,
            "state": [STATES[n % len(STATES)] for n in range(len(sids))],
            "name": names,
        }
    )
    (root / "internal" / "directory").mkdir(parents=True, exist_ok=True)
    frame.write_parquet(root / "internal" / "directory" / "schools.parquet")
    meta: JSONValue = {
        "schema_version": 1,
        "generated_on": generated_on,
        "count": len(sids),
        "ids": sids,
        "names": [f"Synthetic School {n}" for n in range(len(sids))],
        "districts": {"ids": ["9900001", "9900002"], "names": ["Synthetic A", "Synthetic B"]},
        "school_years": {"public": "2024-2025", "private": "2023-2024"},
    }
    write_json(root / "site" / "schools" / "meta.json", meta)
    return root / "site"


def seed(day: str, sids: Sequence[str], *, status: int = 0, reason: int | None = 0) -> ReplaySeed:
    statuses = tuple((sid, status, reason, "station_list") for sid in sorted(set(sids)))
    return ReplaySeed.model_validate(
        {
            "schema_version": 1,
            "id": day,
            "day": day,
            "built": BUILT.model_dump(),
            "quality": Quality(
                lit=len(statuses), sources=2, markets=2, corroborated=0, conflicts=0
            ).model_dump(),
            "statuses": statuses,
        }
    )


class Paths:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.seeds = root / "seeds"
        self.directory = root / "internal" / "directory"
        self.site = root / "site"
        self.meta = self.site / "schools" / "meta.json"
        self.out = self.site / "replays"

    def add(self, value: ReplaySeed, name: str | None = None) -> Path:
        path = self.seeds / (name or f"{value.id}.json")
        write_seed(path, value)
        return path

    def run(self, now: datetime = NOW, out: Path | None = None) -> publishing.PublishResult:
        return publish(self.seeds, self.directory, self.meta, out or self.out, generated_at=now)


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    write_directory(tmp_path)
    return Paths(tmp_path)


def read_replay(path: Path) -> ReplayFile:
    return ReplayFile.from_json_bytes(path.read_bytes())


def read_index(path: Path) -> ReplayIndex:
    return ReplayIndex.from_json_bytes(path.read_bytes())


def test_a_seed_is_published_by_directory_index_with_the_meta_stamp(paths: Paths) -> None:
    sids = [public_id(40), public_id(3), PRIVATE[1], public_id(17)]
    value = seed(DAY, sids, status=2, reason=1)
    statuses = list(value.statuses)
    statuses[0] = (statuses[0][0], 1, None, "station_list")
    paths.add(value.model_copy(update={"statuses": tuple(statuses)}))
    result = paths.run()
    assert result.published == (DAY,)
    assert result.skipped == ()
    replay = read_replay(paths.out / f"{DAY}.json")
    order = directory_ids(6000)
    expected = sorted(
        (order.index(sid), status, 0, 0, reason) for sid, status, reason, _ in statuses
    )
    assert [tuple(int(v) if v is not None else None for v in row) for row in replay.rows] == (
        expected
    )
    assert replay.id == DAY
    assert replay.start == datetime(2026, 1, 5, 12, tzinfo=UTC)
    assert (replay.step_minutes, replay.frames) == (1440, 1)
    assert replay.generated_at == NOW
    assert replay.directory == read_schools(paths.directory, paths.meta).stamp
    assert replay.directory.generated_on == date(2026, 1, 6)
    assert follows_day_convention(replay)
    # the site's file holds indexes, never the seed's NCES ids
    text = (paths.out / f"{DAY}.json").read_text()
    assert not any(sid in text for sid in sids)


def test_the_index_entry_is_checked_against_its_file_and_names_its_states(paths: Paths) -> None:
    sids = [public_id(n) for n in (0, 1, 3, 4)]  # KS, MO, KS, MO
    paths.add(seed(DAY, sids))
    paths.run()
    index = read_index(paths.out / "index.json")
    replay = read_replay(paths.out / f"{DAY}.json")
    (summary,) = index.replays
    check_summary(summary, replay)
    assert summary.states == ("KS", "MO")
    assert (summary.schools, summary.peak_schools, summary.peak_frame) == (4, 4, 0)
    assert index.generated_at == NOW
    report = validate_site(paths.site)
    assert report.problems == []
    assert {"replays/index.json", f"replays/{DAY}.json"} <= set(report.checked)


def test_the_index_is_sorted_by_day(paths: Paths) -> None:
    for day in ("2025-12-17", "2024-01-16", "2025-02-19"):
        paths.add(seed(day, [public_id(n) for n in range(5)]))
    result = paths.run()
    assert result.published == ("2024-01-16", "2025-02-19", "2025-12-17")
    ids = [summary.id for summary in read_index(paths.out / "index.json").replays]
    assert ids == ["2024-01-16", "2025-02-19", "2025-12-17"]


@pytest.mark.parametrize(
    ("missing", "published"),
    [(0, True), (1, True), (2, True), (3, False)],
)
def test_up_to_two_percent_of_ids_may_be_missing(
    paths: Paths, missing: int, published: bool
) -> None:
    present = [public_id(n) for n in range(100 - missing)]
    absent = [public_id(900_000 + n) for n in range(missing)]
    paths.add(seed(DAY, present + absent))
    result = paths.run()
    assert (result.published == (DAY,)) is published
    if published:
        assert len(read_replay(paths.out / f"{DAY}.json").rows) == 100 - missing
    else:
        assert result.skipped[0].reason == f"{missing} of its 100 schools are not in this directory"
        assert not paths.out.exists()


@pytest.mark.parametrize(
    ("day", "published"),
    [("2026-01-04", True), ("2026-01-05", True), ("2026-01-06", False), ("2026-01-07", False)],
)
def test_a_day_less_than_two_days_old_is_refused(paths: Paths, day: str, published: bool) -> None:
    paths.add(seed(day, [public_id(1)]))
    result = paths.run()
    assert (result.published == (day,)) is published
    if not published:
        assert result.skipped[0].reason == "its day is less than 2 days before 2026-01-07"


def test_a_future_day_is_refused(paths: Paths) -> None:
    paths.add(seed("2026-02-02", [public_id(1)]))
    assert paths.run().published == ()


def test_the_age_is_counted_from_the_utc_day_of_generated_at(paths: Paths) -> None:
    paths.add(seed(DAY, [public_id(1)]))
    late = datetime(2026, 1, 6, 23, 59, 59, tzinfo=UTC)  # Jan 6 in UTC: Jan 5 is one day back
    assert paths.run(late).published == ()
    assert paths.run(datetime(2026, 1, 7, 0, 0, tzinfo=UTC)).published == (DAY,)


@pytest.mark.parametrize(
    ("name", "content", "reason"),
    [
        ("2026-01-05-b.json", None, "its name is not <YYYY-MM-DD>.json"),
        ("jan5.json", None, "its name is not <YYYY-MM-DD>.json"),
        ("2026-01-02.json", None, "it holds day 2026-01-05"),
        ("2026-01-05.json", "{}", "it is not a valid seed"),
        ("2026-01-05.json", "not json", "it is not a valid seed"),
    ],
)
def test_a_file_that_breaks_the_day_convention_is_skipped(
    paths: Paths, name: str, content: str | None, reason: str
) -> None:
    if content is None:
        paths.add(seed(DAY, [public_id(1)]), name)
    else:
        paths.seeds.mkdir(parents=True)
        (paths.seeds / name).write_text(content)
    result = paths.run()
    assert result.published == ()
    assert result.skipped[0].seed == name
    assert result.skipped[0].reason.startswith(reason)
    assert not paths.out.exists()


def test_a_skipped_seed_does_not_stop_the_others(paths: Paths) -> None:
    paths.add(seed("2025-12-17", [public_id(1)]))
    paths.add(seed("2026-01-06", [public_id(2)]))  # too recent
    paths.seeds.joinpath("2025-12-18.json").write_text("{}")
    result = paths.run()
    assert result.published == ("2025-12-17",)
    assert [skip.seed for skip in result.skipped] == ["2025-12-18.json", "2026-01-06.json"]
    assert [s.id for s in read_index(paths.out / "index.json").replays] == ["2025-12-17"]


def test_a_seed_that_lights_nothing_here_is_skipped(paths: Paths) -> None:
    paths.add(seed(DAY, []))
    result = paths.run()
    assert result.skipped[0].reason == "it lights no school in this directory"


@pytest.mark.parametrize(
    "change",
    [
        {"frames": 2},
        {"step_minutes": 60},
        {"start": datetime(2026, 1, 5, 13, tzinfo=UTC)},
        {"start": datetime(2026, 1, 6, 12, tzinfo=UTC)},
        {"id": "2026-01-05-b"},
    ],
)
def test_the_day_convention(paths: Paths, change: dict[str, object]) -> None:
    paths.add(seed(DAY, [public_id(1)]))
    paths.run()
    replay = read_replay(paths.out / f"{DAY}.json")
    assert follows_day_convention(replay)
    assert not follows_day_convention(replay.model_copy(update=change))


def test_with_no_seeds_nothing_is_read_or_written(tmp_path: Path) -> None:
    out = tmp_path / "site" / "replays"
    result = publish(
        tmp_path / "no-seeds",
        tmp_path / "no-directory",
        tmp_path / "no-meta.json",
        out,
        generated_at=NOW,
    )
    assert result == publishing.PublishResult((), (), False, 0, ())
    assert not out.exists()


def test_an_empty_seeds_folder_removes_a_stale_index_and_days(paths: Paths) -> None:
    paths.add(seed(DAY, [public_id(1)]))
    paths.run()
    assert (paths.out / "index.json").exists()
    (paths.seeds / f"{DAY}.json").unlink()
    (paths.out / "notes.txt").write_text("kept: not a replay name")
    result = paths.run()
    assert result.removed == (f"{DAY}.json", "index.json")
    assert sorted(path.name for path in paths.out.iterdir()) == ["notes.txt"]
    (paths.out / "notes.txt").unlink()
    paths.run()
    assert not paths.out.exists()


def test_a_day_no_longer_published_is_removed(paths: Paths) -> None:
    paths.add(seed("2025-12-17", [public_id(1)]))
    paths.add(seed(DAY, [public_id(1)]))
    paths.run()
    (paths.seeds / "2025-12-17.json").unlink()
    result = paths.run()
    assert result.removed == ("2025-12-17.json",)
    assert sorted(path.name for path in paths.out.iterdir()) == [f"{DAY}.json", "index.json"]


def test_publishing_is_byte_identical_across_runs(paths: Paths) -> None:
    for day in ("2024-01-16", DAY):
        paths.add(seed(day, [public_id(n) for n in range(0, 3000, 7)], status=1, reason=None))
    first, second = paths.root / "a", paths.root / "b"
    paths.run(out=first)
    paths.run(out=second)
    paths.run(out=second)
    names = sorted(path.name for path in first.iterdir())
    assert names == sorted(path.name for path in second.iterdir())
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_a_five_thousand_school_day_is_within_the_size_budget(paths: Paths) -> None:
    paths.add(seed(DAY, [public_id(n) for n in range(5000)]))
    result = paths.run()
    data = (paths.out / f"{DAY}.json").read_bytes()
    assert len(data) <= publishing.MAX_DAY_BYTES
    assert len(gzip.compress(data)) <= publishing.MAX_DAY_GZIP_BYTES
    assert (paths.out / "index.json").stat().st_size <= publishing.MAX_INDEX_BYTES
    assert result.total_bytes == len(data) + (paths.out / "index.json").stat().st_size


@pytest.mark.parametrize(
    ("budget", "value", "reason"),
    [
        ("MAX_DAY_BYTES", 1000, "its file is "),
        ("MAX_DAY_GZIP_BYTES", 100, "its file is "),
        ("MAX_INDEX_BYTES", 100, "the index would be "),
        ("MAX_TOTAL_BYTES", 1500, "the replays would be over 1,500 bytes together"),
    ],
)
def test_a_file_over_a_budget_is_skipped(
    paths: Paths, monkeypatch: pytest.MonkeyPatch, budget: str, value: int, reason: str
) -> None:
    monkeypatch.setattr(publishing, budget, value)
    paths.add(seed(DAY, [public_id(n) for n in range(200)]))
    result = paths.run()
    assert result.published == ()
    assert result.skipped[0].reason.startswith(reason)
    assert not paths.out.exists()


def test_the_total_budget_keeps_the_oldest_days_that_fit(
    paths: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    for day in ("2025-12-15", "2025-12-16", "2025-12-17"):
        paths.add(seed(day, [public_id(n) for n in range(40)]))
    one = paths.run()
    assert len(one.published) == 3
    size = (paths.out / "2025-12-15.json").stat().st_size
    monkeypatch.setattr(publishing, "MAX_TOTAL_BYTES", 2 * size + 600)
    result = paths.run()
    assert result.published == ("2025-12-15", "2025-12-16")
    assert [skip.seed for skip in result.skipped] == ["2025-12-17.json"]
    assert result.total_bytes <= 2 * size + 600


def test_a_meta_of_another_build_stops_the_run(paths: Paths) -> None:
    paths.add(seed(DAY, [public_id(1)]))
    write_directory(paths.root / "other", publics=10)
    paths.meta.write_bytes((paths.root / "other" / "site" / "schools" / "meta.json").read_bytes())
    with pytest.raises(PublishError, match="does not list the schools"):
        paths.run()


def test_a_missing_directory_stops_a_run_with_seeds(paths: Paths) -> None:
    paths.add(seed(DAY, [public_id(1)]))
    (paths.directory / "schools.parquet").unlink()
    with pytest.raises(PublishError, match="cannot read the directory"):
        paths.run()


def _cli(paths: Paths, *extra: str) -> list[str]:
    return [
        "replays",
        "publish",
        "--seeds",
        str(paths.seeds),
        "--directory",
        str(paths.directory),
        "--meta",
        str(paths.meta),
        "--out",
        str(paths.out),
        *extra,
    ]


def test_the_command_publishes_and_warns(
    paths: Paths, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.add(seed(DAY, [public_id(1)]))
    paths.add(seed("2026-01-06", [public_id(1)]))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert main(_cli(paths, "--now", "2026-01-07T07:00:00-06:00")) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == (
        "::warning::replays publish left out 2026-01-06.json: "
        "its day is less than 2 days before 2026-01-07"
    )
    assert lines[1].startswith(f"replays: published {DAY} and index.json (")
    assert read_replay(paths.out / f"{DAY}.json").generated_at == NOW
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert main(_cli(paths, "--now", "2026-01-07T13:00:00Z")) == 0
    assert capsys.readouterr().out.startswith("warning: replays publish left out")


def test_the_command_with_no_seeds(paths: Paths, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_cli(paths)) == 0
    assert capsys.readouterr().out == "replays: nothing to publish, no replays/ folder\n"
    assert not paths.out.exists()


def test_the_command_fails_on_an_inconsistent_directory(
    paths: Paths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths.add(seed(DAY, [public_id(1)]))
    (paths.directory / "schools.parquet").unlink()
    assert main(_cli(paths, "--now", "2026-01-07T13:00:00Z")) == 1
    assert "snowlight replays publish: error: cannot read the directory" in capsys.readouterr().err


@pytest.mark.parametrize("text", ["2026-01-07", "2026-01-07T13:00:00", "soon"])
def test_now_needs_a_moment_with_an_offset(
    paths: Paths, text: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(_cli(paths, "--now", text))
    assert "--now" in capsys.readouterr().err


def test_the_published_index_reads_as_json(paths: Paths) -> None:
    paths.add(seed(DAY, [public_id(1)]))
    paths.run()
    value = json.loads((paths.out / "index.json").read_bytes())
    assert value["replays"][0]["start"] == "2026-01-05T12:00:00Z"
    assert value["replays"][0]["step_minutes"] == 1440

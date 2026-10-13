"""``snowlight replays build`` and ``days`` on a SYNTHETIC world with a stub reader."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import ModuleType

import polars as pl
import pytest

from replays.world import (
    DAY,
    StubZones,
    disk_counties,
    raw_row,
    stub_parse,
    utc,
    write_disk_world,
)
from snowlight.cli import build_parser, main
from snowlight.replays import cli
from snowlight.replays.build import BuildError, ZoneLookup
from snowlight.replays.gates import ParseFn
from snowlight.replays.seed import archive_sha256, read_seed, unsafe_strings
from snowlight.weights.zones import CountyList

MORN = utc("2024-01-16 05:26")
ON = "on=2024-01-16"


def _world(root: Path, per_district: int) -> Path:
    rows = [
        raw_row("hearst-a", MORN, "Quillfeather R-7", f"closed;{ON}", "Jackson, Quillfeather, MO"),
        raw_row("hearst-b", MORN, "Tansyridge USD 900", f"delayed;{ON}", "Johnson, Tansyridge, KS"),
        raw_row("hearst-a", MORN, "First Baptist Church of Quillfeather", f"closed;{ON}"),
    ]
    write_disk_world(root, per_district=per_district, rows=rows)
    reader = root / "reader" / "snowlight" / "classify"
    reader.mkdir(parents=True)
    (reader / "__init__.py").write_text("# SYNTHETIC reader stand-in\n", encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def big(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A SYNTHETIC world that passes the bar: 260 schools from two stations in two markets."""
    return _world(tmp_path_factory.mktemp("big"), 130)


def _loaders(root: Path, lookups: list[ZoneLookup] | None = None) -> cli.Loaders:
    def reader() -> tuple[ParseFn, Path]:
        return stub_parse, root / "reader"

    def lookup(cache_dir: Path, day: date) -> cli.Zones:
        del cache_dir, day
        return cli.Zones(lookups.pop(0) if lookups else StubZones(), ("SYNTHETIC release",))

    return cli.Loaders(
        reader=reader,
        lookup=lookup,
        counties=disk_counties,
        forget=lambda: None,
        forget_reader=lambda: None,
    )


def _args(root: Path, *extra: str, action: str = "build") -> argparse.Namespace:
    words = ["replays", action]
    if action == "build":
        words += ["--day", "2024-01-16"]
    words += [
        "--archive",
        str(root / "archive"),
        "--registry",
        str(root / "sources"),
        "--directory",
        str(root / "directory"),
        "--meta",
        str(root / "meta.json"),
        "--aliases",
        str(root / "aliases.yaml"),
        "--out",
        str(root / "out"),
        *extra,
    ]
    return build_parser().parse_args(words)


def test_build_checks_and_writes_the_seed(big: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.run_build(_args(big, "--check", "--write-seed"), _loaders(big))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "2024-01-16 | 260 | 2 | 2 | 0 | 0 | 0 | pass" in out
    assert "A7: two builds are byte-identical" in out
    seed = read_seed(big / "out" / "seeds" / "2024-01-16.json")
    assert seed.quality.lit == 260
    assert unsafe_strings(seed.as_json()) == []
    report = json.loads((big / "out" / "2024-01-16.report.internal.json").read_text())
    assert report["passed"] is True
    assert report["drops"]["rows"] == {"not_matched": 1}
    assert len(report["audit"]) == 60


def test_two_builds_that_differ_fail_a7(big: Path, capsys: pytest.CaptureFixture[str]) -> None:
    class NoKansas(StubZones):
        def zone_for(
            self, county_fips: str | None, lat: float | None, lon: float | None, /
        ) -> str | None:
            return None if county_fips == "20091" else super().zone_for(county_fips, lat, lon)

    loaders = _loaders(big, [StubZones(), NoKansas()])
    code = cli.run_build(_args(big, "--check", "--write-seed", "--out", str(big / "a7")), loaders)
    out = capsys.readouterr().out
    assert code == 1
    assert "A7: two builds differ" in out
    assert "seed: not written" in out
    assert not (big / "a7" / "seeds").exists()
    report = json.loads((big / "a7" / "2024-01-16.report.internal.json").read_text())
    assert report["failures"] == ["A7: two builds differ"]
    again = _loaders(big, [StubZones(), NoKansas()])
    assert cli.run_build(_args(big, "--check", "--out", str(big / "a7b")), again) == 1
    assert "A7: two builds differ" in capsys.readouterr().out


def test_the_check_prepares_the_run_again(big: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A7 rebuilds from the files: another match of the archive, with another worker count."""
    workers: list[int] = []
    forgotten: list[str] = []
    real = cli._prepare

    def prepare(args: argparse.Namespace, loaders: cli.Loaders) -> cli.Run:
        workers.append(args.workers)
        return real(args, loaders)

    monkeypatch.setattr(cli, "_prepare", prepare)
    loaders = cli.Loaders(
        reader=_loaders(big).reader,
        lookup=_loaders(big).lookup,
        counties=disk_counties,
        forget=lambda: forgotten.append("zones"),
        forget_reader=lambda: forgotten.append("reader"),
    )
    assert cli.run_build(_args(big, "--check", "--out", str(big / "twice")), loaders) == 0
    assert workers == [1, 2]
    assert forgotten == ["zones", "reader"]


def test_writing_a_seed_always_builds_twice(
    big: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A7 is part of the bar a seed is written under, with or without ``--check``."""
    workers: list[int] = []
    real = cli._prepare

    def prepare(args: argparse.Namespace, loaders: cli.Loaders) -> cli.Run:
        workers.append(args.workers)
        return real(args, loaders)

    monkeypatch.setattr(cli, "_prepare", prepare)
    out = big / "seed-only"
    assert cli.run_build(_args(big, "--write-seed", "--out", str(out)), _loaders(big)) == 0
    assert workers == [1, 2]
    assert "A7: two builds are byte-identical" in capsys.readouterr().out
    assert (out / "seeds" / "2024-01-16.json").is_file()


def test_the_reader_caches_are_emptied_through_the_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    public = ModuleType("SYNTHETIC reader")
    public.cache_clear = lambda: calls.append("cache_clear")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, cli.READER_MODULE, public)
    cli.forget_reader()
    assert calls == ["cache_clear"]
    bare = ModuleType("SYNTHETIC reader")
    parse = ModuleType("SYNTHETIC parse")
    parse._forget_words = lambda: calls.append("_forget_words")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, cli.READER_MODULE, bare)
    monkeypatch.setitem(sys.modules, f"{cli.READER_MODULE}.parse", parse)
    cli.forget_reader()
    assert calls == ["cache_clear", "_forget_words"]
    monkeypatch.delitem(sys.modules, f"{cli.READER_MODULE}.parse")
    cli.forget_reader()  # a reader with no caches to empty
    assert len(calls) == 2


def _rewrite_rows(root: Path, comment: str) -> None:
    """Give hearst-a's district row a comment: the reader then reads it as remote learning."""
    path = root / "archive" / "rows.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        if row["raw_name"] == "Quillfeather R-7":
            row["raw_extra"]["comments_line1"] = comment
    text = "".join(json.dumps(row) + "\n" for row in rows)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)  # an atomic rewrite, as the stations merge writes


def _racing(root: Path) -> cli.Loaders:
    """Loaders whose first county load rewrites the archive (v2 lands while the run matches)."""
    landed: list[bool] = []

    def counties() -> CountyList:
        if not landed:
            _rewrite_rows(root, "Remote learning day")
            landed.append(True)
        return disk_counties()

    return replace(_loaders(root), counties=counties)


def test_an_archive_rewritten_during_preparation_does_not_mix_into_the_seed(
    tmp_path: Path,
) -> None:
    """The archive is read once: the build is v1's, and its hash names v1, though v2 lands while
    the run matches. (Built alone, v2 lights Quillfeather's schools as remote.)"""
    seeds = []
    for name, comment in (("v1", None), ("v2", "Remote learning day")):
        root = _world(tmp_path / name, 130)
        if comment:
            _rewrite_rows(root, comment)
        out = tmp_path / f"out-{name}"
        assert cli.run_build(_args(root, "--write-seed", "--out", str(out)), _loaders(root)) == 0
        seeds.append(read_seed(out / "seeds" / "2024-01-16.json"))
    v1, v2 = seeds
    assert v1.statuses != v2.statuses

    race = _world(tmp_path / "race", 130)
    loaders = _racing(race)
    made, _report = cli._build(cli._prepare(_args(race), loaders), DAY, loaders)
    assert made.seed.statuses == v1.statuses
    assert made.seed.built.archive_sha256 == v1.built.archive_sha256

    again = _world(tmp_path / "race-again", 130)
    out = tmp_path / "out-race"
    assert cli.run_build(_args(again, "--write-seed", "--out", str(out)), _racing(again)) == 1
    assert not (out / "seeds").exists()  # A7 builds again from v2: the builds differ


def test_a_run_reads_the_archive_it_hashes(tmp_path: Path) -> None:
    """One preparation hashes and reads the same bytes, whatever lands after it read them."""
    root = _world(tmp_path / "w", 130)
    before = cli.snapshot_archive(root / "archive", tmp_path / "copy")
    _rewrite_rows(root, "Remote learning day")
    assert archive_sha256(tmp_path / "copy") == before
    assert archive_sha256(root / "archive") != before


def test_an_archive_rewritten_between_its_two_files_stops_the_build(tmp_path: Path) -> None:
    root = _world(tmp_path / "w", 1)
    reads: list[int] = []

    def read(path: Path) -> bytes:
        data = path.read_bytes()
        if path.name == "reads.jsonl":
            reads.append(1)
            return data if len(reads) == 1 else data + b"\n"
        return data

    with pytest.raises(BuildError, match="changed while it was read"):
        cli.snapshot_archive(root / "archive", tmp_path / "copy", read)


def test_builds_in_two_processes_with_other_hash_seeds_are_the_same_bytes(
    big: Path, tmp_path: Path
) -> None:
    tests = Path(__file__).resolve().parents[1]
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from pathlib import Path;"
        "from replays.test_cli import _args, _loaders;"
        "from snowlight.replays import cli;"
        "root = Path(sys.argv[2]);"
        "args = _args(root, '--write-seed', '--out', sys.argv[3], '--workers', sys.argv[4]);"
        "sys.exit(cli.run_build(args, _loaders(root)))"
    )
    digests = []
    for seed, workers in (("1", "1"), ("777", "3")):
        out = tmp_path / f"seed-{seed}"
        env = {**os.environ, "PYTHONHASHSEED": seed}
        done = subprocess.run(  # noqa: S603 - this interpreter, a fixed program
            [sys.executable, "-c", code, str(tests), str(big), str(out), workers],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        files = (out / "seeds" / "2024-01-16.json", out / "2024-01-16.report.internal.json")
        digests.append([hashlib.sha256(path.read_bytes()).hexdigest() for path in files])
    assert digests[0] == digests[1]


def test_a_day_that_fails_the_bar_writes_no_seed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _world(tmp_path, 3)
    code = cli.run_build(_args(root, "--write-seed"), _loaders(root))
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL A2: 6 lit from 2 sources in 2 markets" in out
    assert not (root / "out" / "seeds").exists()
    assert (root / "out" / "2024-01-16.report.internal.json").is_file()


def test_days_builds_the_table(big: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = _args(big, "--out", str(big / "days"), action="days")
    code = cli.run_days(args, _loaders(big), days=(DAY, date(2024, 1, 15)))
    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[0] == " | ".join(cli.HEADER)
    assert out[1].startswith("2024-01-16 | 260 |")
    assert out[2].startswith("2024-01-15 | 0 |")
    assert "A1: holiday" in out[2]
    assert sorted(p.name for p in (big / "days").iterdir()) == [
        "2024-01-15.report.internal.json",
        "2024-01-16.report.internal.json",
    ]


def test_the_candidates_are_the_specs_twelve() -> None:
    assert len(cli.CANDIDATES) == 12
    assert list(cli.CANDIDATES) == sorted(cli.CANDIDATES)
    assert all(day.weekday() < 5 for day in cli.CANDIDATES)


def test_without_the_reader_the_command_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "READER_MODULE", "snowlight.no_such_reader")
    root = _world(tmp_path, 1)
    words = [str(a) for a in ("replays", "build", "--day", "2024-01-16", "--out", root / "o")]
    assert main(words) == 2
    assert "is not on this branch" in capsys.readouterr().err
    assert main(["replays", "days", "--out", str(root / "o")]) == 2
    assert not (root / "o").exists()


SYNTHETIC_MODEL = (
    "from typing import Literal\n"
    "type Note = Literal['undated', 'unread_words', 'hedged', 'conflict', 'revoked', 'negated', "
    "'superseded', 'ambiguous', 'partial_program']\n"
    "JUDGMENT = 0.8\n"
    "UNKNOWN = 0.1\n"
    "CONFLICTING = 0.25\n"
    "STATUS_KINDS = ('closed', 'delayed', 'remote', 'early_dismissal')\n"
)


def test_the_reader_loads_through_the_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "synthreader" / "classify"
    package.mkdir(parents=True)
    (tmp_path / "synthreader" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text(
        "def parse_status(text, *, posted_at, tz):\n    return (text, posted_at, tz)\n",
        encoding="utf-8",
    )
    (package / "model.py").write_text(SYNTHETIC_MODEL, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(cli, "READER_MODULE", "synthreader.classify")
    try:
        parse, root = cli.load_reader()
        assert root == tmp_path
        assert parse("x", posted_at=None, tz="UTC") == ("x", None, "UTC")  # type: ignore[arg-type, comparison-overlap]
        (package / "model.py").unlink()
        sys.modules.pop("synthreader.classify.model", None)
        with pytest.raises(cli.ReaderMissingError, match="has no model"):
            cli.load_reader()
    finally:
        for name in ("synthreader.classify.model", "synthreader.classify", "synthreader"):
            sys.modules.pop(name, None)


def _module(source: str) -> ModuleType:
    module = ModuleType("SYNTHETIC")
    exec(source, module.__dict__)  # noqa: S102 - a fixed SYNTHETIC source
    return module


@pytest.mark.parametrize(
    ("reader", "model", "message"),
    [
        ("X = 1\n", SYNTHETIC_MODEL, "has no parse_status"),
        ("def parse_status(text, posted_at, tz): ...\n", SYNTHETIC_MODEL, "is not"),
        ("def parse_status(text, *, posted_at): ...\n", SYNTHETIC_MODEL, "is not"),
        ("def parse_status(text, *, when, tz): ...\n", SYNTHETIC_MODEL, "is not"),
        (
            "def parse_status(text, *, posted_at, tz): ...\n",
            SYNTHETIC_MODEL.replace("0.8", "0.75"),
            "levels",
        ),
        (
            "def parse_status(text, *, posted_at, tz): ...\n",
            SYNTHETIC_MODEL.replace("UNKNOWN = 0.1", "UNKNOWN = 0.0"),
            "levels",
        ),
        (
            "def parse_status(text, *, posted_at, tz): ...\n",
            SYNTHETIC_MODEL.replace("'unread_words', ", ""),
            "notes lack",
        ),
        (
            "def parse_status(text, *, posted_at, tz): ...\n",
            SYNTHETIC_MODEL.replace("'revoked', ", ""),
            "notes lack",
        ),
        (
            "def parse_status(text, *, posted_at, tz): ...\n",
            SYNTHETIC_MODEL.replace("'conflict', ", "'conflicting', "),
            "notes lack",
        ),
        (
            "def parse_status(text, *, posted_at, tz): ...\n",
            SYNTHETIC_MODEL.replace("CONFLICTING = 0.25", "CONFLICTING = 0.2"),
            "conflict level",
        ),
        (
            "def parse_status(text, *, posted_at, tz): ...\n",
            SYNTHETIC_MODEL.replace("'early_dismissal')", "'early_dismissal', 'hybrid')"),
            "status kinds",
        ),
        (
            "def parse_status(text, *, posted_at, tz): ...\n",
            SYNTHETIC_MODEL.replace("STATUS_KINDS", "KINDS"),
            "status kinds",
        ),
    ],
)
def test_a_reader_unlike_the_protocol_is_refused(reader: str, model: str, message: str) -> None:
    with pytest.raises(cli.ReaderMissingError, match=message):
        cli.check_reader(_module(reader), _module(model))


def test_a_reader_that_is_refused_stops_the_command(
    big: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def refused() -> tuple[ParseFn, Path]:
        raise cli.ReaderMissingError("SYNTHETIC: parse_status is not (text, *, posted_at, tz)")

    loaders = cli.Loaders(reader=refused, lookup=_loaders(big).lookup, counties=disk_counties)
    assert cli.run_build(_args(big, "--out", str(big / "refused")), loaders) == 2
    assert "is not (text" in capsys.readouterr().err


def test_meta_must_describe_the_directory(big: Path, tmp_path: Path) -> None:
    meta = json.loads((big / "meta.json").read_text())
    schools = pl.read_parquet(big / "directory" / "schools.parquet")
    assert cli.check_meta(meta, schools) == "2026-09-24"
    with pytest.raises(BuildError, match="does not describe"):
        cli.check_meta({**meta, "ids": meta["ids"][::-1]}, schools)
    with pytest.raises(BuildError, match="does not describe"):
        cli.check_meta({**meta, "count": 1}, schools)
    other = tmp_path / "meta.json"
    other.write_text(json.dumps({**meta, "count": 3}), encoding="utf-8")
    assert cli.run_build(_args(big, "--meta", str(other)), _loaders(big)) == 1


def test_the_matcher_hash_is_over_the_aliases_used(big: Path, tmp_path: Path) -> None:
    pins = cli._prepare(_args(big), _loaders(big)).pins
    other = tmp_path / "aliases.yaml"
    other.write_text("schema_version: 1\nmarkets: {}\n# another file\n", encoding="utf-8")
    again = cli._prepare(_args(big, "--aliases", str(other)), _loaders(big)).pins
    assert again["matcher_sha256"] != pins["matcher_sha256"]
    assert {k: v for k, v in again.items() if k != "matcher_sha256"} == {
        k: v for k, v in pins.items() if k != "matcher_sha256"
    }


def test_bad_inputs_fail_cleanly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _world(tmp_path, 1)
    (root / "archive" / "reads.jsonl").write_text('{"source_id": 1}\n', encoding="utf-8")
    assert cli.run_build(_args(root), _loaders(root)) == 1
    assert "snowlight replays build: error:" in capsys.readouterr().err
    assert cli.run_days(_args(root, action="days"), _loaders(root), days=(DAY,)) == 1
    assert "snowlight replays days: error:" in capsys.readouterr().err

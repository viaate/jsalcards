"""When a pass publishes, and every way it stays dark."""

import gzip
import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from predict import world
from snowlight.predict import cli
from snowlight.predict.alerts_live import UgcIndex
from snowlight.predict.config import PredictConfig
from snowlight.predict.inputs import directory_from_files, read_local
from snowlight.predict.publish import (
    Dark,
    DarkError,
    Mode,
    State,
    blank_file,
    check_alert_age,
    check_budget,
    check_collapse,
    check_coverage,
    checked,
    content_digest,
    due,
    mode_of,
    upload,
)
from snowlight.predict.serve import DeployedDirectory
from snowlight.schemas.directory import DirectoryEdition, written_edition
from snowlight.schemas.predictions import PredictionsFile
from snowlight.sources.nws.alerts import ActiveFeed, parse_active

SETTINGS = world.CONFIG.serve
NOW = world.utc("2026-01-07T02:00:00")


class MemoryHost:
    """A host in memory; ``broken`` makes reads give other bytes."""

    def __init__(self, broken: bool = False) -> None:
        self.files: dict[str, bytes] = {}
        self.broken = broken
        self.writes = 0

    def read(self, key: str) -> bytes | None:
        found = self.files.get(key)
        return b"{}" if self.broken and found is not None else found

    def write(self, files: Mapping[str, bytes]) -> None:
        self.writes += 1
        self.files.update(files)


def feed(updated: str = "2026-01-07T01:55:00+00:00", alerts: int = 1) -> ActiveFeed:
    features = [
        world.feature(
            f"/O.NEW.KEAX.WS.W.{i:04d}.260107T0600Z-260108T0000Z/",
            ("MOZ028",),
            sent="2026-01-06T20:00:00+00:00",
            onset="2026-01-07T06:00:00+00:00",
            ends="2026-01-08T00:00:00+00:00",
        )
        for i in range(1, alerts + 1)
    ]
    return parse_active(world.feed_bytes(features, updated))


def make_pass(  # noqa: PLR0913 - every input a test may swap
    host: MemoryHost | None = None,
    *,
    mode: Mode = Mode.ON,
    alerts: ActiveFeed | None = None,
    directory: DeployedDirectory | None = None,
    config: PredictConfig = world.CONFIG,
    now: datetime = NOW,
) -> cli.Pass:
    lon, lat = world.lon_lat()

    def read_directory() -> DeployedDirectory:
        if directory is None:
            raise DarkError(Dark.EDITION, "test")
        return directory

    return cli.Pass(
        config=config,
        mode=mode,
        host=host,
        directory=read_directory,
        alerts=lambda: (alerts or feed(), True),
        ugcs=lambda _d: UgcIndex.build(lon, lat, world.ugc_areas()),
        zone_fallback=lambda _lon, _lat: None,
        model=world.model,
        state=State(),
        now=lambda: now,
        history=lambda _start, _end: [],
    )


def test_a_pass_publishes_then_waits_for_a_change_or_the_heartbeat(capsys: Any) -> None:
    host = MemoryHost()
    run = make_pass(host, directory=world.directory())
    assert cli.one_pass(run) == 0
    key = "v1/predictions/latest.json"
    assert key in host.files
    published = PredictionsFile.from_json_bytes(host.files[key])
    assert published.generated_at == NOW
    assert len(published.districts) == 5
    # The same content a minute later: not uploaded again.
    run.now = lambda: NOW + timedelta(minutes=1)
    assert cli.one_pass(run) == 0
    assert host.writes == 1
    # The heartbeat (with a feed as fresh as ever).
    run.now = lambda: NOW + timedelta(minutes=31)
    run.alerts = lambda: (feed(updated="2026-01-07T02:30:00+00:00"), True)
    assert cli.one_pass(run) == 0
    assert host.writes == 2
    assert "uploaded v1/predictions/latest.json" in capsys.readouterr().out


def test_a_private_school_with_no_time_zone_is_said_on_every_pass(capsys: Any) -> None:
    # The first private school has no zone in the model and the point lookup finds none: its
    # today is unknown, so it gets no chance, and the pass says so rather than drop it quietly.
    committed = world.model()
    first = world.PRIVATE_IDS[0]
    private = dict(committed.private)
    private[first] = private[first].model_copy(update={"time_zone": None})
    changed = committed.model_copy(update={"private": private})
    host = MemoryHost()
    run = make_pass(host, directory=world.directory())
    run.model = lambda: changed
    assert cli.one_pass(run) == 0
    published = PredictionsFile.from_json_bytes(host.files["v1/predictions/latest.json"])
    served = [entry.school for entry in published.schools]
    assert world.FIRST_PRIVATE not in served
    assert served == [world.FIRST_PRIVATE + 1, world.FIRST_PRIVATE + 2]
    found = capsys.readouterr()
    assert "2 private schools" in found.out
    assert "warning: 1 private schools of the contiguous states have no time zone" in found.err


def test_off_and_shadow() -> None:
    host = MemoryHost()
    assert cli.one_pass(make_pass(host, mode=Mode.OFF, directory=world.directory())) == 0
    assert host.files == {}
    assert cli.one_pass(make_pass(host, mode=Mode.SHADOW, directory=world.directory())) == 0
    assert list(host.files) == ["v1-shadow/predictions/latest.json"]
    assert mode_of(None) is Mode.OFF
    assert mode_of("on") is Mode.ON
    with pytest.raises(ValueError, match="maybe"):
        mode_of("maybe")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"alerts": "stale"}, "alerts_stale"),
        ({"directory": None}, "edition_unreadable"),
        ({"coverage": True}, "coverage"),
        ({"broken": True}, "read_back"),
        ({"budget": True}, "size"),
    ],
)
def test_every_refusal_publishes_nothing(change: dict[str, Any], reason: str, capsys: Any) -> None:
    host = MemoryHost(broken=bool(change.get("broken")))
    config = world.CONFIG
    if change.get("budget"):
        config = config.model_copy(
            update={"serve": SETTINGS.model_copy(update={"budget_raw_bytes": 100})}
        )
    directory: DeployedDirectory | None = world.directory()
    if "directory" in change:
        directory = None
    run = make_pass(
        host,
        alerts=feed(updated="2026-01-07T01:00:00+00:00") if change.get("alerts") else None,
        directory=directory,
        config=config,
    )
    if change.get("coverage"):
        bare = world.model()
        run.model = lambda: bare.model_copy(
            update={"districts": dict(list(bare.districts.items())[:4])}
        )
        run.zone_fallback = lambda _lon, _lat: "America/Denver"
    assert cli.one_pass(run) == cli.EXIT_DARK
    assert reason in capsys.readouterr().err
    if not change.get("broken"):
        assert host.files == {}


def held(state: State) -> int | None:
    return state.held_count


def test_an_alert_collapse_waits_for_the_next_pass() -> None:
    state = State(winter_alerts=60)
    with pytest.raises(DarkError, match="alert_collapse"):
        check_collapse(5, state, SETTINGS)
    assert held(state) == 5
    check_collapse(6, state, SETTINGS)  # the next pass confirms it
    assert state.winter_alerts == 6
    assert held(state) is None
    small = State(winter_alerts=40)
    check_collapse(0, small, SETTINGS)  # from 50 or fewer, no hold
    assert small.winter_alerts == 0
    host = MemoryHost()
    run = make_pass(host, directory=world.directory())
    run.state = State(winter_alerts=80)
    assert cli.one_pass(run) == cli.EXIT_DARK
    assert host.files == {}
    assert cli.one_pass(run) == 0
    assert host.files


def test_the_small_checks() -> None:
    check_alert_age(NOW, NOW, SETTINGS)
    with pytest.raises(DarkError, match="alerts_stale"):
        check_alert_age(None, NOW, SETTINGS)
    with pytest.raises(DarkError, match="coverage"):
        check_coverage(0.98, SETTINGS)
    check_coverage(0.99, SETTINGS)
    with pytest.raises(DarkError, match="invalid"):
        checked(b'{"schema_version": 1}')
    data = blank_file(world.STAMP, (date(2026, 1, 7), date(2026, 1, 8)), NOW)
    assert checked(data).districts == ()
    assert check_budget(data, SETTINGS) == len(gzip.compress(data, mtime=0))
    later = json.loads(data) | {"generated_at": "2026-01-07T03:00:00Z"}
    assert content_digest(data) == content_digest(json.dumps(later).encode())
    state = State(digest=content_digest(data), uploaded_at=NOW)
    assert not due(state, content_digest(data), NOW + timedelta(minutes=29), SETTINGS, grid=False)
    assert due(state, content_digest(data), NOW + timedelta(minutes=30), SETTINGS, grid=False)
    assert due(state, "other", NOW, SETTINGS, grid=False)
    with pytest.raises(DarkError, match="read_back"):
        upload(MemoryHost(broken=True), "v1/predictions/latest.json", data)
    kept = State.from_json(State(digest="x", uploaded_at=NOW, winter_alerts=3).as_json())
    assert kept.uploaded_at == NOW
    assert kept.winter_alerts == 3
    assert State.from_json({"memory": "nope"}).memory == []


def test_directory_files_must_be_the_deployed_edition(tmp_path: Path) -> None:
    meta, points = world.meta_bytes(), world.points_bytes()
    edition = written_edition(meta, points)
    directory, _meta = directory_from_files(edition, meta, points)
    assert directory.stamp == edition.stamp()
    other = DirectoryEdition(
        schema_version=1,
        generated_on=edition.generated_on,
        schools=edition.schools,
        districts=edition.districts,
        content_sha256="0" * 64,
    )
    with pytest.raises(DarkError, match="edition"):
        directory_from_files(other, meta, points)
    with pytest.raises(DarkError, match="edition"):
        directory_from_files(edition, meta, points[:-1])
    (tmp_path / "meta.json").write_bytes(meta)
    (tmp_path / "points.bin").write_bytes(points)
    assert read_local(tmp_path).stamp == edition.stamp()
    (tmp_path / "edition.json").write_bytes(other.to_json_bytes())
    with pytest.raises(DarkError, match="edition"):
        read_local(tmp_path)


def test_a_pass_reads_the_day_after_from_the_hosts_day_timeline() -> None:
    host = MemoryHost()
    host.files["v1/live/days/2026-01-06.json"] = world.timeline().to_json_bytes()
    host.files["v1/live/days/2026-01-05.json"] = b"{}"
    run = make_pass(host, directory=world.directory())
    built = run.serve_model(world.directory())
    closed = cli._closed_on(run, built)
    assert closed(date(2026, 1, 6)) == frozenset({1})
    # A file that does not validate is not "no closings": the pass would publish from fewer
    # inputs, so it goes dark (only a file the host does not hold means none).
    with pytest.raises(DarkError, match="day_file"):
        closed(date(2026, 1, 5))
    assert cli.one_pass(run) == cli.EXIT_DARK
    assert "v1/predictions/latest.json" not in host.files
    del host.files["v1/live/days/2026-01-05.json"]
    assert closed(date(2026, 1, 2)) is None  # none published
    assert cli._closed_on(make_pass(None, mode=Mode.OFF), built)(date(2026, 1, 6)) is None
    assert cli.one_pass(run) == 0

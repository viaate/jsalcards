"""The switch rehearsal (S8-E E8, ``live rehearse``) on a SYNTHETIC world: the overrides
writer, the reader in ``on``, the overrides writer again, all on ``v1-rehearse`` of the
rehearsal's own folder host with cold local state, the admin's status a SYNTHETIC override
served on the loopback.

* the override is served after each switch, and a writer that drops it fails the rehearsal;
* the configured host is never written (the SYNTHETIC status goes to the runner's own folder
  only), nothing outside ``v1-rehearse/`` is written there, and the D1 store is never made:
  the rehearsal refuses to run with a Cloudflare secret set, or with LIVE_PUBLISH on;
* the reader's pass reads no source and every request goes to the loopback (no station page,
  no robots.txt from a second runner);
* the rehearsal prefix ends blanked and held.
"""

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from live.test_cli import MORNING, Clock, Rig, _loaders, make_rig
from live.test_edition import OWN
from snowlight import cli
from snowlight.live import cli as live_cli
from snowlight.live.ingest import SourceRead
from snowlight.live.merge import AdminStatus
from snowlight.live.overrides import DeployedSchools
from snowlight.live.publish import HOLD, OPENS, REHEARSE, holds
from snowlight.live.rehearse import fixture, shows
from snowlight.schemas.live import ClosingsFile


def _schools(rig: Rig) -> DeployedSchools:
    """The world's schools as the deployed directory names them (three districts, as the
    edition's stamp says): Alpha's in Central time, the rest without a zone but Escambia's."""
    ordered = sorted(rig.world.dir.schools.values(), key=lambda school: school.index)
    groups = {"2000001": 0, "1200510": 1}
    return DeployedSchools(
        stamp=OWN.stamp(),
        content_sha256=OWN.content_sha256,
        school_ids=tuple(school.record.id for school in ordered),
        district_ids=("2000001", "1200510", "9999999"),
        district_of=tuple(groups.get(school.record.district_id or "", 2) for school in ordered),
        zones=("America/Chicago", "America/Chicago", None),
    )


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "live.yaml"
    path.write_text(
        f"""host:
  kind: dir
  folder: {tmp_path / "host"}
state:
  kind: d1
site: https://synthetic.example
site_repository: viaate/synthetic
""",
        encoding="utf-8",
    )
    return path


def _rehearse(  # noqa: PLR0913 - the rehearsal and its stand-ins
    tmp_path: Path,
    rig: Rig,
    env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    drop: bool = False,
    client: Callable[[], httpx.Client] = httpx.Client,
) -> int:
    def no_store(*_args: object) -> object:
        raise AssertionError("the rehearsal never makes the D1 store")

    monkeypatch.setattr(live_cli, "make_store", no_store)
    clock = Clock(MORNING)
    base = _loaders(rig, clock)
    schools = _schools(rig)

    def parts(
        config: live_cli.LiveConfig, step_env: live_cli.Env, args: argparse.Namespace
    ) -> live_cli.Parts:
        made = base.parts(config, step_env, args)
        found = live_cli.reader_overrides(
            step_env, httpx.Client(), made.ingest.publisher, lambda: schools
        )

        def none(_now: datetime) -> Sequence[AdminStatus]:
            return ()

        made.ingest.overrides = none if drop else found

        def reads(
            _now: datetime, _only: Sequence[str], _tick: Callable[[], None]
        ) -> Sequence[SourceRead]:
            raise AssertionError("the rehearsal reads no source")

        return live_cli.Parts(made.ingest, reads)

    host = tmp_path / "state" / "host"

    def served(path: str) -> bytes | None:
        clock.now += timedelta(seconds=90)  # the CDN's delay: the next writer starts later
        found = host / path
        return found.read_bytes() if found.is_file() else None

    loaders = replace(
        base,
        parts=parts,
        env=lambda: env,
        schools=lambda _config, _env: schools,
        served=served,
        client=client,
    )
    argv = ["live", "rehearse", "--config", str(_config(tmp_path))]
    argv += ["--state", str(tmp_path / "state"), "--internal", str(tmp_path / "internal")]
    args = cli.build_parser().parse_args(argv)
    return int(args.handler(args, loaders))


def _written(tmp_path: Path) -> set[str]:
    assert not (tmp_path / "host").exists()  # the configured host is never written
    host = tmp_path / "state" / "host"
    return {str(path.relative_to(host)).split("/")[0] for path in host.rglob("*") if path.is_file()}


def test_the_override_is_served_after_each_switch_and_nothing_leaves_the_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = make_rig()
    assert _rehearse(tmp_path, rig, {}, monkeypatch) == 0
    out = capsys.readouterr().out
    assert out.count("s later") == 3
    assert "rehearse: overrides: exit 0; published" in out
    assert "rehearse: reader on: exit" in out
    assert "the override was served within one pass of each switch" in out
    # no source read: G12b refuses the lists, and the admin's status goes out alone
    assert "refusals health; uploaded 3; edition equal; the admin's statuses on the last" in out
    assert _written(tmp_path) == {REHEARSE}  # never v1/ or v1-shadow/
    host = tmp_path / "state" / "host" / REHEARSE
    assert holds((host / HOLD).read_bytes())  # ends held
    assert shows((host / OPENS).read_bytes(), 0) is None  # and blanked
    assert not ClosingsFile.from_json_bytes((host / "live" / "closings.json").read_bytes()).days


def test_a_writer_that_drops_the_override_fails_the_rehearsal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _rehearse(tmp_path, make_rig(), {}, monkeypatch, drop=True) == 1
    out = capsys.readouterr().out
    assert "reader on: exit" in out
    assert "not served within one pass after ['reader on', 'overrides']" in out
    assert _written(tmp_path) == {REHEARSE}


@pytest.mark.parametrize(
    "env",
    [
        {"CLOUDFLARE_API_TOKEN": "SYNTHETIC"},
        {"CLOUDFLARE_ACCOUNT_ID": "SYNTHETIC"},
        {"LIVE_PUBLISH": "On"},
    ],
)
def test_it_refuses_with_a_d1_secret_or_live_publish_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    assert _rehearse(tmp_path, make_rig(), env, monkeypatch) == 1
    assert not (tmp_path / "host").exists()
    assert not (tmp_path / "state" / "host").exists()


def test_the_fixture_is_an_open_status_today_in_the_schools_zone() -> None:
    schools = _schools(make_rig())
    made = fixture(schools, MORNING)
    assert made.school == 0
    body: dict[str, Any] = json.loads(made.body)
    (override,) = body["overrides"]
    assert (override["status"], override["days"], override["time_zone"]) == (
        "open",
        ["2026-11-17"],
        "America/Chicago",
    )
    nowhere = replace(schools, zones=(None, None, None))
    with pytest.raises(ValueError, match="no school"):
        fixture(nowhere, MORNING)


class Recording(httpx.BaseTransport):
    """A transport that keeps every request's host and sends it on."""

    def __init__(self) -> None:
        self.hosts: list[str] = []
        self.real = httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.hosts.append(request.url.host)
        return self.real.handle_request(request)


def test_the_rehearsal_reads_no_source_and_asks_only_the_loopback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the reader step's reads raise if called (see _rehearse): its pass reads nothing, so no
    # station page and no robots.txt is asked from the drill's runner; every request any
    # writer makes through the CLI's client goes to the SYNTHETIC override on the loopback
    transport = Recording()
    made = _rehearse(
        tmp_path, make_rig(), {}, monkeypatch, client=lambda: httpx.Client(transport=transport)
    )
    assert made == 0
    assert transport.hosts
    assert set(transport.hosts) == {"127.0.0.1"}
    assert _written(tmp_path) == {REHEARSE}


def test_no_reads_reads_nothing() -> None:
    assert live_cli.no_reads(MORNING, (), lambda: None) == ()

"""The admin's statuses in every reader pass (S8-E section 3). SYNTHETIC world, host and API.

* each pass applies them on top of the lists (``with_overrides``), in ``shadow`` as in ``on``;
* an API error refuses the pass, so nothing is dropped on a blip; no API means none;
* a pass refused by health (G12b) or the spike hold (G12e) alone, when they changed since
  the last upload, publishes the last published list rows unchanged with the new statuses,
  under ``generated_at`` = the last published + 1 s (a status set after that has no
  "Posted" time); unchanged statuses wait for the gate;
* :class:`~snowlight.live.overrides.ApiRoot` follows live-ingest.yml's check job, and
  :func:`~snowlight.live.overrides.fetch_live` asks a 404, a 5xx or no answer again once.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from live.test_cli import MORNING, Rig, make_rig
from live.test_edition import OWN, Source
from live.test_publish import Host
from snowlight.live.edition import EditionWatch
from snowlight.live.ingest import Ingest, SourceRead
from snowlight.live.ledger import Outcome
from snowlight.live.merge import AdminStatus
from snowlight.live.overrides import ApiRoot, OverridesError, fetch_live
from snowlight.live.publish import ADMIN_ONLY, CLOSINGS, Exit, LivePublisher, Mode
from snowlight.schemas.live import ClosingsFile
from snowlight.schemas.vocab import Status

DAY = date(2026, 11, 17)


def _admin(rig: Rig, index: int, at: datetime, status: Status = Status.CLOSED) -> AdminStatus:
    nces = next(nces for nces, school in rig.world.dir.schools.items() if school.index == index)
    return AdminStatus(
        school=index,
        nces_id=nces,
        day=DAY,
        status=status,
        shift_minutes=None,
        clock_minute=None,
        set_at=at,
        level="school",
        key=f"synthetic-{index}-{status.name}",
    )


def _ingest(
    rig: Rig,
    host: Host,
    tmp: Path,
    mode: Mode,
    overrides: Callable[[datetime], Sequence[AdminStatus]],
) -> Ingest:
    publisher = LivePublisher(
        host=host,
        directory=rig.world.dir,
        state_dir=tmp / f"state-{mode.value}",
        internal_dir=tmp / "i",
        mode=mode,
    )
    return Ingest(
        ledger=rig.world.ledger,
        resolver=rig.world.resolver(),
        stations=rig.world.stations,
        publisher=publisher,
        watch=EditionWatch(own=OWN, source=Source([OWN])),
        internal_dir=tmp / "i",
        overrides=overrides,
    )


def _file(host: Host, prefix: str) -> ClosingsFile:
    return ClosingsFile.from_json_bytes((host.root / prefix / CLOSINGS).read_bytes())


def _reads(rig: Rig, at: datetime, outcome: Outcome = Outcome.OK) -> list[SourceRead]:
    return [replace(read, fetched_at=at, outcome=outcome) for read in rig.reads]


@pytest.mark.parametrize(("mode", "prefix"), [(Mode.SHADOW, "v1-shadow"), (Mode.ON, "v1")])
def test_each_pass_applies_the_admins_statuses(mode: Mode, prefix: str, tmp_path: Path) -> None:
    rig = make_rig()
    host = Host(tmp_path / "host")
    admin = _admin(rig, 3, MORNING - timedelta(minutes=30))
    ingest = _ingest(rig, host, tmp_path, mode, lambda _now: [admin])
    assert ingest.run_pass(rig.reads, MORNING).exit is Exit.OK
    found = {(row.school, row.status, row.manual) for row in _file(host, prefix).closings()}
    assert (3, Status.CLOSED, True) in found
    assert (0, Status.CLOSED, False) in found  # the lists' own row stands beside it


def test_an_api_error_refuses_the_pass_and_no_api_means_none(tmp_path: Path) -> None:
    rig = make_rig()
    host = Host(tmp_path / "host")

    def broken(_now: datetime) -> Sequence[AdminStatus]:
        raise OverridesError("GET v1/overrides: HTTP 503", answered=True, status=503)

    ingest = _ingest(rig, host, tmp_path, Mode.SHADOW, broken)
    report = ingest.run_pass(rig.reads, MORNING)
    assert (report.exit, report.refusals) == (Exit.REFUSED, ("overrides",))
    assert not (host.root / "v1-shadow" / CLOSINGS).exists()
    quiet = _ingest(rig, host, tmp_path, Mode.SHADOW, lambda _now: ())
    assert quiet.run_pass(rig.reads, MORNING + timedelta(minutes=5)).exit is Exit.OK


def test_the_admin_does_not_wait_for_the_health_gate(tmp_path: Path) -> None:
    rig = make_rig()
    host = Host(tmp_path / "host")
    statuses: list[AdminStatus] = []
    ingest = _ingest(rig, host, tmp_path, Mode.SHADOW, lambda _now: list(statuses))
    assert ingest.run_pass(rig.reads, MORNING).exit is Exit.OK
    first = _file(host, "v1-shadow")
    # the lists go unhealthy (every read errs) and the admin sets a status
    later = MORNING + timedelta(minutes=20)
    statuses.append(_admin(rig, 3, later - timedelta(minutes=10)))
    report = ingest.run_pass(_reads(rig, later, Outcome.ERROR), later)
    assert report.refusals == ("health",)
    assert report.uploaded
    shown = _file(host, "v1-shadow")
    assert shown.generated_at == first.generated_at + timedelta(seconds=1)  # the list's age
    lists = {(row.school, row.status) for row in first.closings()}
    assert {(row.school, row.status) for row in shown.closings() if not row.manual} == lists
    manual = [row for row in shown.closings() if row.manual]
    assert [(row.school, row.status) for row in manual] == [(3, Status.CLOSED)]
    assert manual[0].announced_at is None  # set after the file's moment: no "Posted" time
    # the same statuses on the next unhealthy pass wait for the gate
    again = ingest.run_pass(
        _reads(rig, later + timedelta(minutes=5), Outcome.ERROR), later + timedelta(minutes=5)
    )
    assert (again.exit, again.uploaded) == (Exit.REFUSED, ())
    assert {"health", "spike_hold"} == ADMIN_ONLY


# The API root ------------------------------------------------------------------------------


def _cloudflare(subdomain: object, scripts: object, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer SYNTHETIC-token"
        if request.url.path.endswith("/workers/subdomain"):
            return httpx.Response(
                status, json={"success": status == 200, "result": {"subdomain": subdomain}}
            )
        return httpx.Response(status, json={"success": status == 200, "result": scripts})

    return httpx.Client(transport=httpx.MockTransport(handler))


SECRETS = {"CLOUDFLARE_API_TOKEN": "SYNTHETIC-token", "CLOUDFLARE_ACCOUNT_ID": "synthetic-account"}


def test_the_api_root_follows_the_check_job() -> None:
    none = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(500)))
    assert (
        ApiRoot({"SNOWLIGHT_API_ROOT": "https://api.synthetic.example/"}, none).find()
        == "https://api.synthetic.example/"
    )
    with pytest.raises(OverridesError):
        ApiRoot({"SNOWLIGHT_API_ROOT": "http://api.synthetic.example/"}, none).find()
    assert ApiRoot({}, none).find() is None  # no root and no secrets: no API
    found = ApiRoot(SECRETS, _cloudflare("synthetic", [{"id": "snowlight-api"}])).find()
    assert found == "https://snowlight-api.synthetic.workers.dev/"
    assert ApiRoot(SECRETS, _cloudflare("synthetic", [{"id": "other"}])).find() is None
    assert ApiRoot(SECRETS, _cloudflare(None, [])).find() is None
    with pytest.raises(OverridesError):
        ApiRoot(SECRETS, _cloudflare("synthetic", [], status=500)).find()
    with pytest.raises(OverridesError):
        ApiRoot(SECRETS, _cloudflare("Not A Name!", [])).find()


def _api(answers: list[int]) -> httpx.Client:
    def handler(_request: httpx.Request) -> httpx.Response:
        status = answers.pop(0)
        if status == 200:
            return httpx.Response(
                200, json={"overrides": []}, headers={"content-type": "application/json"}
            )
        return httpx.Response(status)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_live_asks_again_once() -> None:
    pauses: list[float] = []
    root = "https://api.synthetic.example/"
    assert fetch_live(_api([404, 404]), root, sleep=pauses.append) == ()  # not deployed
    assert fetch_live(_api([503, 200]), root, sleep=pauses.append) == ()
    with pytest.raises(OverridesError):
        fetch_live(_api([503, 502]), root, sleep=pauses.append)
    with pytest.raises(OverridesError):
        fetch_live(_api([403]), root, sleep=pauses.append)
    assert pauses == [10.0, 10.0, 10.0]

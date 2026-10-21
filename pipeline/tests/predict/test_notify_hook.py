"""The predictions loop runs the chance notifier (docs/notify.md) after a pass whose file is
the one the site shows: on the live root only, and a notifier that fails never fails the
pass. SYNTHETIC world (tests/predict/world.py)."""

from datetime import datetime

import pytest

from predict import world as predict_world
from predict.test_publish import MemoryHost, make_pass
from snowlight.predict import cli as predict_cli
from snowlight.predict.publish import Mode
from snowlight.predict.serve import DeployedDirectory
from snowlight.schemas.predictions import PredictionsFile


@pytest.mark.parametrize("mode", ["on", "shadow"])
def test_the_predictions_loop_notifies_only_on_the_live_root(
    mode: str, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[PredictionsFile, datetime]] = []

    def notify(file: PredictionsFile, _directory: DeployedDirectory, now: datetime) -> str:
        calls.append((file, now))
        return "notify chance: 0 due"

    host = MemoryHost()
    run = make_pass(host, mode=Mode(mode), directory=predict_world.directory())
    run.notify = notify
    assert predict_cli.one_pass(run) == 0
    if mode == "shadow":
        assert calls == []
        return
    [(file, _now)] = calls
    assert file.to_json_bytes() == host.files["v1/predictions/latest.json"]
    assert "notify chance: 0 due" in capsys.readouterr().out
    # Unchanged and not due: the file the site shows is still this one.
    assert predict_cli.one_pass(run) == 0
    assert len(calls) == 2

    def broken(*_args: object) -> str:
        raise RuntimeError("boom secret")

    run.notify = broken
    assert predict_cli.one_pass(run) == 0
    err = capsys.readouterr().err
    assert "notify: RuntimeError: nothing sent this pass" in err
    assert "secret" not in err

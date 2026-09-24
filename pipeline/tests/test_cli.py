"""Tests for the command-line entry point."""

import runpy
import sys
import tomllib
from pathlib import Path

import pytest

import snowlight
from snowlight.cli import main


def test_version_flag_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"snowlight {snowlight.__version__}"


def test_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
    assert snowlight.__version__ == pyproject["project"]["version"]


def test_no_arguments_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out.startswith("usage: snowlight")


def test_unknown_argument_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--nope"])
    assert excinfo.value.code == 2
    assert "unrecognized arguments: --nope" in capsys.readouterr().err


def test_python_dash_m_runs_the_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["snowlight"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("snowlight", run_name="__main__")
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.startswith("usage: snowlight")

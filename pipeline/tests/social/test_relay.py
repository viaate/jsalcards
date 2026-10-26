"""The cards' way from the render job to the post job: through the render job's log, checked
against its digest, only the known files, each within its size (all SYNTHETIC)."""

import base64
import hashlib
import json
from pathlib import Path

import pytest

from snowlight.social import relay
from snowlight.social.relay import RelayError, receive, send
from social.fakes import PNG

STAMP = "2026-10-26T16:37:01.1234567Z "


def folder(tmp: Path) -> Path:
    made = tmp / "render"
    made.mkdir()
    (made / "picture.json").write_text('{"kind": "national"}')
    (made / "picture.png").write_bytes(PNG + b"MAP-ONLY" * 1000)
    for post in ("dev-log", "waitlist"):
        (made / f"{post}.png").write_bytes(PNG + post.encode() * 3000)
        (made / f"{post}.json").write_text(json.dumps({"post": post}))
    return made


def sent(tmp: Path) -> tuple[str, str, Path]:
    lines: list[str] = []
    output = tmp / "github-output"
    digest = send(folder(tmp), lines.append, output)
    assert output.read_text() == f"digest={digest}\n"
    # As the log API gives it: a timestamp before each line, other lines around them.
    log = "\n".join(
        ["2026-10-26T16:37:00.0Z ##[group]Run uv run", *(STAMP + line for line in lines), "x"]
    )
    return log, digest, tmp / "taken"


def test_the_cards_go_through_the_log_whole(tmp_path: Path) -> None:
    log, digest, out = sent(tmp_path)
    names = receive(log, digest, out)
    assert names == ["dev-log.json", "dev-log.png", "picture.json", "waitlist.json", "waitlist.png"]
    for name in names:
        assert (out / name).read_bytes() == (tmp_path / "render" / name).read_bytes()
    assert not (out / "picture.png").exists(), "the map alone is not needed to post"
    longest = max(len(line) for line in log.splitlines())
    assert longest <= len(STAMP) + len("social-relay 00001 ") + relay.LINE


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda log: log.replace("social-relay 00002", "social-relay 00003", 1), "out of order"),
        (lambda log: "\n".join(line for line in log.splitlines() if "00002" not in line), "order"),
        (lambda log: log.split("social-relay end")[0], "missing or cut"),
        (lambda _log: "", "missing or cut"),
    ],
)
def test_a_cut_or_reordered_bundle_is_refused(tmp_path: Path, change: object, problem: str) -> None:
    log, digest, out = sent(tmp_path)
    with pytest.raises(RelayError, match=problem):
        receive(change(log), digest, out)  # type: ignore[operator]
    assert not out.exists()


def test_a_bundle_the_render_job_did_not_make_is_refused(tmp_path: Path) -> None:
    log, digest, out = sent(tmp_path)
    with pytest.raises(RelayError, match="not the one"):
        receive(log, "0" * 64, out)
    with pytest.raises(RelayError, match="no digest"):
        receive(log, "", out)
    rows = [line for line in log.splitlines() if "social-relay 0" in line]
    forged = log.replace(rows[0][-8:], "AAAAAAAA")
    with pytest.raises(RelayError, match="not the one"):
        receive(forged, digest, out)


def forge(files: dict[str, bytes]) -> tuple[str, str]:
    data = json.dumps(
        {"files": {name: base64.b64encode(value).decode() for name, value in files.items()}}
    ).encode()
    encoded = base64.b64encode(data).decode()
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    rows = [encoded[i : i + relay.LINE] for i in range(0, len(encoded), relay.LINE)]
    lines = [f"social-relay {n:05d} {row}" for n, row in enumerate(rows, start=1)]
    lines.append(f"social-relay end {len(rows)} {digest}")
    return "\n".join(lines), digest


@pytest.mark.parametrize(
    ("files", "problem"),
    [
        ({"../../etc/passwd": b"x"}, "does not take"),
        ({"post.sh": b"x"}, "does not take"),
        ({"dev-log.json": b"x" * (64 * 1024 + 1)}, "too big"),
    ],
)
def test_only_the_known_files_within_their_size_are_taken(
    tmp_path: Path, files: dict[str, bytes], problem: str
) -> None:
    log, digest = forge(files)
    with pytest.raises(RelayError, match=problem):
        receive(log, digest, tmp_path / "taken")
    assert not (tmp_path / "taken").exists()


def test_a_render_without_a_picture_hands_nothing_over(tmp_path: Path) -> None:
    with pytest.raises(RelayError, match=r"no picture\.json"):
        send(tmp_path, print, None)

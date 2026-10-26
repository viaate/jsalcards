"""The seal, the X client's edge cases, the Haiku writer's stops, the log scan, the CLI's
output and the content loader (all SYNTHETIC values, mocked HTTP)."""

import io
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from snowlight.cli import main
from snowlight.social import logscan, seal
from snowlight.social.cli import Output, commits
from snowlight.social.content import ContentError, load
from snowlight.social.writer import MAX_CALLS, AnswerError, CallCapError, Writer, draft
from snowlight.social.xapi import (
    RefreshRefusedError,
    RefreshUnknownError,
    RefusedError,
    UnknownOutcomeError,
    XClient,
)
from social import fakes
from social.fakes import FakeAnthropic, FakeX, make_root

GOOD = {
    "text": "Dev log: the closings reader runs 24/7 in practice mode.",
    "image_id": "img-1",
    "kind": "dev_log",
    "facts_used": ["reader"],
}


def test_the_seal_opens_only_under_its_client_secret() -> None:
    sealed = seal.seal("refresh-value", "secret-a")
    assert "refresh-value" not in sealed
    assert seal.seal("refresh-value", "secret-a") != sealed, "a fresh nonce each time"
    assert seal.unseal(sealed, "secret-a") == "refresh-value"
    with pytest.raises(seal.SealError, match="did not open"):
        seal.unseal(sealed, "secret-b")
    with pytest.raises(seal.SealError, match="known format"):
        seal.unseal("plain", "secret-a")
    with pytest.raises(seal.SealError, match="damaged"):
        seal.unseal("v1.AAAA", "secret-a")
    with pytest.raises(seal.SealError, match="damaged"):
        seal.unseal("v1.@@@", "secret-a")
    with pytest.raises(ValueError, match="no client secret"):
        seal.seal("x", "")
    assert seal.fingerprint("seed", "secret-a") != seal.fingerprint("seed", "secret-b")
    assert seal.fingerprint("seed", "secret-a") != seal.fingerprint("other", "secret-a")


def _x(handler: httpx.MockTransport) -> XClient:
    return XClient(httpx.Client(transport=handler), mask=lambda _v: None, sleep=lambda _s: None)


def test_refresh_failures_are_told_apart() -> None:
    def refused(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized_client"})

    with pytest.raises(RefreshRefusedError, match=r"HTTP 401 \(unauthorized_client\)"):
        _x(httpx.MockTransport(refused)).refresh("a", "b", "c")

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic", request=request)

    with pytest.raises(RefreshUnknownError, match="no answer"):
        _x(httpx.MockTransport(down)).refresh("a", "b", "c")

    def empty(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token_type": "bearer"})

    with pytest.raises(RefreshUnknownError, match="no access token"):
        _x(httpx.MockTransport(empty)).refresh("a", "b", "c")

    def odd(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(RefreshUnknownError, match="HTTP 200"):
        _x(httpx.MockTransport(odd)).refresh("a", "b", "c")


def test_a_refresh_without_rotation_keeps_the_token() -> None:
    world = FakeX(rotate=False)
    tokens = _x(httpx.MockTransport(world.handle)).refresh(
        fakes.CLIENT_ID, fakes.CLIENT_SECRET, fakes.SEED
    )
    assert tokens.refresh == fakes.SEED
    assert "media.write" in tokens.scopes


def test_an_image_still_processing_is_waited_for_and_a_failed_one_refused() -> None:
    world = FakeX(processing=["in_progress", "in_progress", "succeeded"])
    world.issued.append("tok")
    client = _x(httpx.MockTransport(world.handle))
    assert client.upload_image("tok", "a.png", fakes.PNG, "image/png") == "1880028106020515840"
    world.processing = ["in_progress", "failed"]
    with pytest.raises(RefusedError, match="could not process"):
        client.upload_image("tok", "a.png", fakes.PNG, "image/png")
    world.processing = ["pending"] + ["in_progress"] * 9
    with pytest.raises(RefusedError, match="still processing"):
        client.upload_image("tok", "a.png", fakes.PNG, "image/png")


def test_upload_and_post_outcomes() -> None:
    def gone(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("synthetic", request=request)

    with pytest.raises(RefusedError, match="no answer"):
        _x(httpx.MockTransport(gone)).upload_image("t", "a.png", b"", "image/png")

    def nameless(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"id": "x1"}})

    with pytest.raises(RefusedError, match="no media id"):
        _x(httpx.MockTransport(nameless)).upload_image("t", "a.png", b"", "image/png")

    def never(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic", request=request)

    with pytest.raises(RefusedError, match="never reached"):
        _x(httpx.MockTransport(never)).post("t", "x", "1")

    def busy(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(UnknownOutcomeError, match="HTTP 503"):
        _x(httpx.MockTransport(busy)).post("t", "x", "1")

    def no_id(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"data": {}})

    with pytest.raises(UnknownOutcomeError, match="no post id"):
        _x(httpx.MockTransport(no_id)).post("t", "x", "1")

    def limited(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"errors": [{"title": "Too Many Requests"}]})

    with pytest.raises(RefusedError, match=r"HTTP 429 \(Too Many Requests\)"):
        _x(httpx.MockTransport(limited)).post("t", "x", "1")


def _content(tmp_path: Path) -> object:
    return load(make_root(tmp_path))


def test_the_writer_stops_on_a_refusal_a_cut_answer_and_a_bad_schema(tmp_path: Path) -> None:
    content = load(make_root(tmp_path))
    said: list[str] = []
    haiku = FakeAnthropic(
        [{"_stop": "refusal", "_text": ""}, {"_stop": "max_tokens", "_text": "{"}]
    )
    assert (
        draft(
            Writer(haiku.client()),
            content,
            style="dev_log",
            today=date(2026, 10, 26),
            commits=[],
            say=said.append,
        )
        is None
    )
    assert "Haiku declined to answer" in said[0]
    assert "stopped early (max_tokens)" in said[1]
    writer = Writer(
        FakeAnthropic(
            [{"_text": "not json"}, {"text": "x"}, {"status": 529}, {"ok": "maybe"}]
        ).client()
    )
    with pytest.raises(AnswerError, match="not JSON"):
        writer.write("p")
    with pytest.raises(AnswerError, match="schema"):
        writer.write("p")
    with pytest.raises(AnswerError, match="HTTP 529"):
        writer.write("p")
    with pytest.raises(AnswerError, match="schema"):
        writer.review("p")
    assert writer.calls == MAX_CALLS
    with pytest.raises(CallCapError):
        writer.write("p")


def test_the_writer_refuses_an_unknown_image_kind_or_fact(tmp_path: Path) -> None:
    content = load(make_root(tmp_path))
    said: list[str] = []
    wrong = {**GOOD, "image_id": "nope", "kind": "waitlist", "facts_used": ["made-up"]}
    haiku = FakeAnthropic([dict(wrong), dict(GOOD), {"ok": True, "problems": ["but this"]}])
    assert (
        draft(
            Writer(haiku.client()),
            content,
            style="dev_log",
            today=date(2026, 10, 26),
            commits=[],
            say=said.append,
        )
        is None
    )
    assert "the image id is not in the library" in said[0]
    assert "the kind must be dev_log" in said[0]
    assert "facts_used names facts" in said[0]
    assert "but this" in said[1]
    haiku = FakeAnthropic([dict(GOOD), {"status": 500}, dict(GOOD), {"ok": True, "problems": []}])
    written = draft(
        Writer(haiku.client()),
        content,
        style="dev_log",
        today=date(2026, 10, 26),
        commits=[],
        say=said.append,
    )
    assert written is not None
    assert written.image.id == "img-1"


def test_logscan_finds_secret_shapes_and_spares_ordinary_log_lines() -> None:
    ordinary = "\n".join(
        [
            "2026-10-26T16:37:01.1234567Z Download action repository"
            " 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1'",
            "run 9f1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
            " /opt/hostedtoolcache/Python/3.12.7/x64/lib/python3.12",
            "social: posted queue:0001 as 1850000000000000002:"
            " https://x.com/SnowlightMap/status/1850000000000000002",
            "X_CLIENT_SECRET: ***",
        ]
    )
    assert logscan.findings(ordinary) == []
    leaked = "token " + fakes.token("Lk") + "\nkey sk-ant-api03-abcdefghijklmnopqrstuvwxyz"
    assert logscan.findings(leaked) == ["line 1: 48 characters", "line 2: 39 characters"]
    assert logscan.scrub(f"a {fakes.SEED} b", []) == "a *** b"
    assert logscan.scrub("short secretvalue here", ["secretvalue"]) == "short *** here"


def test_output_scrubs_and_masks_only_in_actions() -> None:
    stream = io.StringIO()
    out = Output({"X_CLIENT_SECRET": fakes.CLIENT_SECRET, "GITHUB_ACTIONS": "true"}, stream)
    out.mask("derived-value-1")
    out.mask("")
    out.say(f"x {fakes.CLIENT_SECRET} derived-value-1")
    assert stream.getvalue() == "::add-mask::derived-value-1\nx *** ***\n"
    local = io.StringIO()
    out = Output({}, local)
    out.mask("derived-value-2")
    out.say("derived-value-2")
    assert local.getvalue() == "***\n"


def test_scan_log_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clean = tmp_path / "clean.log"
    clean.write_text("all fine\n")
    assert main(["social", "scan-log", str(clean)]) == 0
    dirty = tmp_path / "dirty.log"
    dirty.write_text("x " + fakes.token("Dd") + "\n")
    assert main(["social", "scan-log", str(dirty)]) == 1
    out = capsys.readouterr().out
    assert "secret-shaped value at line 1" in out
    assert "Dd" not in out


def test_post_command_without_secrets_posts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("X_CLIENT_ID", "X_CLIENT_SECRET", "X_REFRESH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    make_root(tmp_path)
    assert main(["social", "post", "--root", str(tmp_path), "--event", "schedule"]) == 0
    assert "nothing posts" in capsys.readouterr().out


def test_commit_subjects_come_from_git(tmp_path: Path) -> None:
    assert commits(tmp_path, None) == []
    repo = Path(__file__).resolve().parents[3]
    assert isinstance(commits(repo, None), list)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda s: (s / "facts.md").unlink(), "facts.md is missing"),
        (lambda s: (s / "images" / "img-1.json").write_text("{"), "not readable JSON"),
        (
            lambda s: (s / "images" / "img-1.json").write_text(json.dumps({"id": "img-1"})),
            "malformed",
        ),
        (lambda s: (s / "images" / "img-2.png").unlink(), "img-2.png is missing"),
        (lambda s: (s / "images" / "img-2.png").write_bytes(b"GIF89a"), "not the image"),
        (
            lambda s: (s / "images" / "img-2.png").write_bytes(
                fakes.PNG + b"0" * (5 * 1024 * 1024)
            ),
            "over 5 MB",
        ),
        (
            lambda s: (s / "images" / "img-3.json").write_text(
                (s / "images" / "img-2.json").read_text()
            ),
            "names another id",
        ),
        (
            lambda s: (s / "queue" / "0001.json").write_text(json.dumps({"id": "0001"})),
            "queue/0001.json is malformed",
        ),
        (
            lambda s: (s / "queue" / "0002.json").write_text(json.dumps(fakes.queued("0001"))),
            "queue/0002.json names another id",
        ),
    ],
)
def test_malformed_content_is_named(tmp_path: Path, change: object, message: str) -> None:
    root = make_root(tmp_path, queue=[fakes.queued("0001")])
    change(root / "social")  # type: ignore[operator]
    with pytest.raises(ContentError, match=message):
        load(root)

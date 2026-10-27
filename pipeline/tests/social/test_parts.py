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
from snowlight.social.post import haiku_on
from snowlight.social.rules import chances_shown, model_fact_for, parse_facts
from snowlight.social.writer import (
    MAX_CALLS,
    AnswerError,
    CallCapError,
    Writer,
    draft,
    usable_commits,
)
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
    sealed = seal.seal("refresh-value", "secret-a", version=3)
    assert "refresh-value" not in sealed
    assert sealed.startswith("v1.")
    assert seal.seal("refresh-value", "secret-a", version=3) != sealed, "a fresh nonce each time"
    assert seal.unseal(sealed, "secret-a", version=3) == "refresh-value"
    with pytest.raises(seal.SealError, match="did not open"):
        seal.unseal(sealed, "secret-b", version=3)
    with pytest.raises(seal.SealError, match="known format"):
        seal.unseal("plain", "secret-a", version=3)
    with pytest.raises(seal.SealError, match="damaged"):
        seal.unseal("v1.AAAA", "secret-a", version=3)
    with pytest.raises(seal.SealError, match="damaged"):
        seal.unseal("v1.@@@", "secret-a", version=3)
    with pytest.raises(ValueError, match="no client secret"):
        seal.seal("x", "", version=1)


def test_a_seal_written_back_at_another_version_does_not_open() -> None:
    older = seal.seal("spent-refresh-value", "secret-a", version=2)
    for version in (1, 3, 4):
        with pytest.raises(seal.SealError, match="did not open"):
            seal.unseal(older, "secret-a", version=version)
    assert seal.unseal(older, "secret-a", version=2) == "spent-refresh-value"

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

    with pytest.raises(UnknownOutcomeError, match="not a 201 with the post's id"):
        _x(httpx.MockTransport(no_id)).post("t", "x", "1")

    def moved(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(302)

    with pytest.raises(RefusedError, match="HTTP 302") as refused:
        _x(httpx.MockTransport(moved)).post("t", "x", "1")
    assert refused.value.status == 302

    def limited(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"errors": [{"title": "Too Many Requests"}]})

    with pytest.raises(RefusedError, match=r"HTTP 429 \(Too Many Requests\)"):
        _x(httpx.MockTransport(limited)).post("t", "x", "1")


@pytest.mark.parametrize(
    ("status", "body"),
    [
        pytest.param(200, b"", id="200-empty"),
        pytest.param(200, b'{"data": {"id": "1850000000000000002", "text": "x"}}', id="200-id"),
        pytest.param(201, b"<html><body>Created</body></html>", id="201-not-json"),
        pytest.param(201, b'{"errors": [{"title": "Service Unavailable"}]}', id="201-errors"),
        pytest.param(201, b'{"data": {"id": "18500x"}}', id="201-bad-id"),
        pytest.param(202, b'{"data": {"id": "1850000000000000002"}}', id="202"),
        pytest.param(204, b"", id="204"),
    ],
)
def test_a_2xx_post_answer_without_a_201_post_id_is_unknown_never_a_refusal(
    status: int, body: bytes
) -> None:
    """X may have made the post: never a refusal, which would drop the claim and send it again."""

    def odd(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body)

    with pytest.raises(UnknownOutcomeError, match=f"HTTP {status}"):
        _x(httpx.MockTransport(odd)).post("t", "x", "1")


def test_a_201_with_the_post_id_is_posted() -> None:
    def made(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"data": {"id": "1850000000000000002", "text": "x"}})

    assert _x(httpx.MockTransport(made)).post("t", "x", "1") == "1850000000000000002"


@pytest.mark.parametrize(
    ("header", "on"),
    [
        ("HAIKU_POSTS = on", True),
        ("HAIKU_POSTS=ON", True),
        ("HAIKU_POSTS = off", False),
        ("", False),
        ("HAIKU_POSTS = yes", False),
        ("  HAIKU_POSTS = on", False),
        ("HAIKU_POSTS = on\n\nHAIKU_POSTS = on", False),
        ("HAIKU_POSTS = on\n\nHAIKU_POSTS = off", False),
    ],
)
def test_only_one_haiku_posts_on_line_switches_the_haiku_writer_on(header: str, on: bool) -> None:
    facts = fakes.FACTS.replace("HAIKU_POSTS = on", header)
    assert haiku_on(parse_facts(facts)) is on


def test_the_haiku_writer_ships_switched_off() -> None:
    real = (Path(__file__).resolve().parents[3] / "social" / "facts.md").read_text(encoding="utf-8")
    assert "\nHAIKU_POSTS = off\n" in real
    assert haiku_on(parse_facts(real)) is False


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


MODEL_FACTS = (
    fakes.FACTS + "- [LIVE] model: The chances come from a prediction model, not a guess."
    " | terms: prediction model, model, not a guess\n"
    "- [LIVE] model-days: The model is trained on 2,388 real past school days."
    " | terms: trained on, past school days\n"
    "- [LIVE] model-tested: I tested the model walk-forward on past winters."
    " | terms: walk-forward, past winters\n"
    "- [COMING] model-learning: The model will learn from this winter. | terms: learn from\n"
)


def test_every_haiku_post_states_the_days_model_fact(tmp_path: Path) -> None:
    content = load(make_root(tmp_path, facts=MODEL_FACTS))
    day = date(2026, 10, 26)
    fact = model_fact_for(content.facts, day)
    assert fact is not None
    assert [item.id for item in content.facts.model] == ["model", "model-days", "model-tested"]
    stated = {
        "model": "Dev log: the chances come from a prediction model, not a guess.",
        "model-days": "Dev log: the model is trained on 2,388 real past school days.",
        "model-tested": "Dev log: I tested the model walk-forward on past winters.",
    }[fact.id]
    other = next(item for item in content.facts.model if item.id not in {fact.id, "model"})
    vague = {**GOOD, "text": "Dev log: the closings reader runs 24/7 in practice mode."}
    wrong = {**GOOD, "text": stated, "facts_used": [other.id]}
    right = {**GOOD, "text": stated, "facts_used": [fact.id]}
    haiku = FakeAnthropic([dict(vague), dict(wrong), dict(right), {"ok": True, "problems": []}])
    said: list[str] = []
    writer = Writer(haiku.client())
    args = {"style": "dev_log", "today": day, "commits": [], "say": said.append}
    assert draft(writer, content, **args) is None  # type: ignore[arg-type]
    assert f"the model fact for 2026-10-26 is {fact.id}" in said[0]
    assert "it says nothing about the prediction model" in said[1]
    assert f"facts_used must name the model fact {fact.id}" in said[2]
    prompt = haiku.requests[0]["messages"][0]["content"]
    assert "Model fact for this post (state it in my own words" in prompt
    assert fact.text in prompt
    system = haiku.requests[0]["system"]
    assert "Model first" in system
    assert "Never describe, name or compare any other product" in system
    written = draft(Writer(haiku.client()), content, **args)  # type: ignore[arg-type]
    assert written is not None
    assert written.facts_used == (fact.id,)
    review = haiku.requests[-1]
    assert f"Model fact it was given: {fact.text}" in review["messages"][0]["content"]
    assert "does not state the model fact it was given" in review["system"]
    # The next day asks for the next model fact.
    assert model_fact_for(content.facts, date(2026, 10, 27)) != fact


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


def test_commit_subjects_come_from_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Git exports these to its hooks (the local pre-push gate runs this suite from one), and
    # git log then reads that repository from any directory: clear them so tmp_path is no repo.
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
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


def test_haiku_sees_no_commit_subject_with_a_number_a_station_or_a_chance() -> None:
    real = (Path(__file__).resolve().parents[3] / "social" / "facts.md").read_text(encoding="utf-8")
    facts = parse_facts(real)
    assert not chances_shown(facts)
    subjects = [
        "give a district with no weather threat 0% as it counts",
        "its chance the students' average with a closed school as 100%",
        "Wyoming's acceptance at 85.8% plain",
        "Read KIFI's closings articles",
        "Show each district's chance in its panel",
        "Link the waitlist from snowlightmap.com",
        "Draw the map's school specks at every zoom",
        "Keep the waitlist form inside its card on phones",
    ]
    assert usable_commits(subjects, facts) == [
        "Draw the map's school specks at every zoom",
        "Keep the waitlist form inside its card on phones",
    ]
    live = parse_facts(real.replace("- [TESTING] chances:", "- [LIVE] chances:"))
    assert "Show each district's chance in its panel" in usable_commits(subjects, live)

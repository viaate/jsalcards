"""Whole runs of ``snowlight social post`` against the fakes (mocked HTTP only).

Every run's output is grepped the way the workflow's log check greps the job log: no secret
the run was given or derived, and no secret-shaped value at all, may appear in it.
"""

import io
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from snowlight.social import logscan, seal
from snowlight.social.cli import Output
from snowlight.social.content import ContentError, load
from snowlight.social.issue import REFUSED_TITLE, TITLE, UNCERTAIN_TITLE
from snowlight.social.post import MAX_HAIKU_PER_DAY, QUIET, Deps, draft_mark, run
from snowlight.social.store import MAX_POSTS_PER_DAY, TABLES
from snowlight.social.xapi import RefusedError, XClient
from social import fakes
from social.fakes import (
    FRESH_SHOWS,
    Clock,
    FakeAnthropic,
    World,
    at,
    make_picture,
    make_root,
    queued,
    unpictured,
)

GOOD_DRAFT = {
    "text": "I keep the closings reader running 24/7 in practice mode."
    " Join the waitlist, link in my bio.",
    "image_id": "img-2",  # the library's newest: the fallback when no fresh picture is given
    "kind": "waitlist",
    "facts_used": ["reader", "waitlist"],
}
GOOD_DEV_LOG = {
    **GOOD_DRAFT,
    "kind": "dev_log",
    "text": "Dev log: the closings reader runs 24/7 in practice mode.",
}
OTHER_DEV_LOG = {**GOOD_DEV_LOG, "text": "Dev log: I keep the closings reader running 24/7."}
OK = {"ok": True, "problems": []}
TABLES_SQL = TABLES[1]


class Runner:
    def __init__(self, root: Path, world: World, clock: Clock) -> None:
        self.picture: Path | None = None
        self.root = root
        self.world = world
        self.clock = clock
        self.logs: list[str] = []
        self.masked: list[str] = []
        self.haiku: FakeAnthropic | None = None

    def __call__(self, event: str = "push", **extra: str) -> int:
        # Each run has its own run id, as on GitHub.
        environment = fakes.env(
            **{"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": str(1001 + len(self.logs)), **extra}
        )
        stream = io.StringIO()
        output = Output(environment, stream)

        def mask(value: str) -> None:
            self.masked.append(value)
            output.mask(value)

        client = self.world.client()
        haiku = self.haiku

        def make() -> Any:
            assert haiku is not None, "Haiku was asked without an answer queued"
            return haiku.client()

        deps = Deps(
            http=client,
            x=XClient(client, mask=mask, sleep=lambda _s: None),
            say=output.say,
            mask=mask,
            now=self.clock,
            commits=lambda _since: ["Show the waitlist count", "Fix the map's zoom"],
            haiku_client=make,
            db_pause=0.0,
        )
        before = len(self.world.x.issued)
        code = run(environment, self.root, event, deps, self.picture)
        log = stream.getvalue()
        self.logs.append(log)
        self.check_log(log, environment, self.world.x.issued[before:])
        return code

    def check_log(self, log: str, environment: dict[str, str], issued: list[str]) -> None:
        # Every line is plain text or one of the code's own commands: nothing from outside
        # can start a command (::stop-commands:: would let the masks below print as text).
        masked = set(self.masked)
        for line in log.splitlines():
            assert line == line.strip(), line
            if line.startswith("::add-mask::"):
                assert line.removeprefix("::add-mask::") in masked | set(self.world.x.issued)
            elif line.startswith("::"):
                assert line.startswith(("::error::", "::warning::", "::notice::")), line
            if not line.startswith("::add-mask::"):
                for command in ("::stop-commands::", "::echo::", "::add-mask::", "##["):
                    assert command not in line[2:], line
        shown = "\n".join(line for line in log.splitlines() if not line.startswith("::add-mask::"))
        for name in (
            "X_CLIENT_ID",
            "X_CLIENT_SECRET",
            "X_REFRESH_TOKEN",
            "X_ACCESS_TOKEN",
            "X_ACCESS_TOKEN_SECRET",
            "CLOUDFLARE_API_TOKEN",
            "GITHUB_TOKEN",
        ):
            assert not environment.get(name) or environment[name] not in shown, name
        for value in [*self.masked, *self.world.x.valid, *self.world.x.issued, fakes.ANTHROPIC_KEY]:
            assert value not in shown
        assert logscan.findings(shown) == []
        masks = {
            line.removeprefix("::add-mask::")
            for line in log.splitlines()
            if line.startswith("::add-mask::")
        }
        assert set(issued) <= masks, "every access token is masked"

    @property
    def log(self) -> str:
        return self.logs[-1]


@pytest.fixture
def world() -> World:
    return World()


def make(
    tmp_path: Path,
    world: World,
    *,
    queue: list[dict[str, Any]] | None = None,
    when: str = "2026-10-26T16:37:00",
) -> Runner:
    return Runner(make_root(tmp_path, queue=queue), world, Clock(at(when)))


def test_the_first_run_posts_the_queued_post_and_stores_the_rotated_token_sealed(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    assert runner() == 0
    assert len(world.x.posts) == 1
    post = world.x.posts[0]
    assert post == {"text": queued("0001")["text"], "media": {"media_ids": ["1880028106020515840"]}}
    row = world.d1.row("SELECT * FROM social_token")
    assert row is not None
    assert row["version"] == 1
    assert row["lease"] is None
    (rotated,) = world.x.valid
    assert rotated not in json.dumps(row)
    assert seal.unseal(row["sealed"], fakes.CLIENT_SECRET, version=1) == rotated
    assert row["seed"] == seal.fingerprint(fakes.SEED, fakes.CLIENT_SECRET)
    posted = world.d1.row("SELECT * FROM social_posts")
    assert posted is not None
    assert posted["slot"] == "queue:0001"
    assert posted["state"] == "posted"
    assert posted["post_id"] == "1850000000000000002"
    assert "https://x.com/SnowlightMap/status/1850000000000000002" in runner.log


def test_a_posted_queue_item_never_posts_again_and_a_push_run_spends_no_token(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    assert runner() == 0
    runner.clock.at += timedelta(hours=1)
    assert runner() == 0
    assert len(world.x.posts) == 1
    assert world.x.refreshes == 1
    assert "Haiku writes only on the daily scheduled run" in runner.log


def test_the_scheduled_run_without_an_anthropic_key_says_so_and_spends_nothing(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world)
    assert runner("schedule") == 0
    assert "no Anthropic key" in runner.log
    assert world.x.refreshes == 0
    assert world.d1.row("SELECT * FROM social_token") is None


def test_one_post_a_run_and_the_next_from_the_stored_chain(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    assert runner() == 0
    assert [p["text"] for p in world.x.posts] == [queued("0001")["text"]]
    runner.clock.at += timedelta(hours=2)
    assert runner() == 0
    assert len(world.x.posts) == 2
    assert "from the stored token (version 1)" in runner.log
    row = world.d1.row("SELECT version FROM social_token")
    assert row == {"version": 2}


def test_the_day_never_holds_more_than_three_posts(tmp_path: Path, world: World) -> None:
    assert MAX_POSTS_PER_DAY == 3, "the owner: at least one post a day, 2 to 3 is best"
    runner = make(
        tmp_path, world, queue=[queued("0001"), queued("0002"), queued("0003"), queued("0004")]
    )
    for _ in range(4):
        runner()
        runner.clock.at += timedelta(minutes=30)
    assert len(world.x.posts) == 3
    assert "taken or the day's cap is reached" in runner.log
    assert len({post["text"] for post in world.x.posts}) <= 3
    assert [row["slot"] for row in world.d1.rows("SELECT slot FROM social_posts")] == [
        "queue:0001",
        "queue:0002",
        "queue:0003",
    ], "never a duplicate post"
    runner.clock.at += timedelta(days=1)
    assert runner() == 0
    assert len(world.x.posts) == 4


def test_haiku_writes_the_daily_post_and_styles_alternate(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")], when="2026-10-26T10:00:00")
    assert runner() == 0
    runner.clock.at = at("2026-10-27T16:37:00")
    runner.haiku = FakeAnthropic([dict(GOOD_DRAFT), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert world.x.posts[-1]["text"] == GOOD_DRAFT["text"]
    requests = runner.haiku.requests
    assert len(requests) == 2
    for request in requests:
        assert request["model"] == "claude-haiku-5-5"
        assert request["max_tokens"] == 1024
        assert request["output_config"]["effort"] == "low"
        assert request["output_config"]["format"]["type"] == "json_schema"
    assert "Set kind to waitlist." in requests[0]["messages"][0]["content"]
    assert "Show the waitlist count" in requests[0]["messages"][0]["content"]
    row = world.d1.row("SELECT * FROM social_posts WHERE kind = 'haiku'")
    assert row is not None
    assert row["slot"] == "haiku:2026-10-27#1"
    assert row["style"] == "waitlist"
    runner.clock.at = at("2026-10-28T16:37:00")
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert "Set kind to dev_log." in runner.haiku.requests[0]["messages"][0]["content"]
    assert len(world.x.posts) == 3


@pytest.mark.parametrize(
    ("line", "on"),
    [
        pytest.param("HAIKU_POSTS = on", True, id="on"),
        pytest.param("HAIKU_POSTS = off", False, id="off"),
        pytest.param("", False, id="no-line"),
    ],
)
def test_the_haiku_writer_switch_decides_whether_any_run_calls_anthropic(
    tmp_path: Path, world: World, line: str, on: bool
) -> None:
    """With the key set, a switched-off writer is never asked: a scheduled run posts the
    queued post that is due, and neither a scheduled nor a push run with nothing queued calls
    Anthropic. Switched on, the next day's scheduled run has Haiku write, as before."""
    runner = Runner(
        make_root(
            tmp_path,
            queue=[queued("0001")],
            facts=fakes.FACTS.replace("HAIKU_POSTS = on", line),
        ),
        world,
        Clock(at("2026-10-26T16:37:00")),
    )
    runner.haiku = FakeAnthropic([dict(GOOD_DRAFT), dict(OK)])
    key = fakes.ANTHROPIC_KEY
    assert runner("schedule", ANTHROPIC_API_KEY=key) == 0
    assert [post["text"] for post in world.x.posts] == [queued("0001")["text"]]
    assert ("Haiku writer is off" in runner.log) is not on
    runner.clock.at = at("2026-10-27T16:37:00")
    assert runner("push", ANTHROPIC_API_KEY=key) == 0
    assert runner.haiku.requests == []
    assert runner("schedule", ANTHROPIC_API_KEY=key) == 0
    if on:
        assert len(runner.haiku.requests) == 2
        assert world.x.posts[-1]["text"] == GOOD_DRAFT["text"]
        return
    assert "nothing queued, and the Haiku writer is off: no post" in runner.log
    assert runner.haiku.requests == [], "no Anthropic call"
    assert len(world.x.posts) == 1
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_haiku_days") == {"n": 0}


def test_no_haiku_post_within_3_hours_of_the_last_post(tmp_path: Path, world: World) -> None:
    """The 13:07 run GitHub started 43 minutes late (its post claimed at 13:50) still leaves
    the 17:37 run room to write; a run under three hours after it does not."""
    assert timedelta(hours=3) == QUIET
    runner = make(tmp_path, world, queue=[queued("0001")], when="2026-10-26T13:50:00")
    assert runner() == 0
    runner.clock.at = at("2026-10-26T16:40:00")
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert "in the last 3 hours" in runner.log
    assert len(world.x.posts) == 1
    runner.clock.at = at("2026-10-26T17:37:00")
    runner.haiku = FakeAnthropic([dict(GOOD_DRAFT), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert len(world.x.posts) == 2, "3 h 47 min after the late post, Haiku writes"


def test_at_most_three_haiku_posts_a_day_even_when_asked_again(
    tmp_path: Path, world: World
) -> None:
    assert MAX_HAIKU_PER_DAY == 3
    runner = make(tmp_path, world, when="2026-10-27T00:41:00")
    drafts = [GOOD_DEV_LOG, GOOD_DRAFT, OTHER_DEV_LOG]
    for when, draft in zip(("00:41", "13:07", "17:37"), drafts, strict=True):
        runner.clock.at = at(f"2026-10-27T{when}:00")
        runner.haiku = FakeAnthropic([dict(draft), dict(OK)])
        assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert len(world.x.posts) == 3
    slots = [row["slot"] for row in world.d1.rows("SELECT slot FROM social_posts")]
    assert slots == ["haiku:2026-10-27#1", "haiku:2026-10-27#2", "haiku:2026-10-27#3"]
    runner.clock.at = at("2026-10-27T23:30:00")
    runner.haiku = FakeAnthropic([])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert "the day's cap of 3 posts is reached" in runner.log
    assert runner.haiku.requests == []
    assert len(world.x.posts) == 3


def test_two_failed_haiku_drafts_mean_no_post_from_that_try_within_four_calls(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world)
    bad = {**GOOD_DEV_LOG, "text": "Dev log: 99% sure the map is live now at snowlightmap.com"}
    runner.haiku = FakeAnthropic(
        [dict(bad), dict(GOOD_DEV_LOG), {"ok": False, "problems": ["claims something new"]}]
    )
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert len(runner.haiku.requests) == 3
    assert "no post from this try" in runner.log
    assert "Haiku calls this run: 3" in runner.log
    assert world.x.posts == []
    assert world.x.refreshes == 0
    retry = runner.haiku.requests[1]["messages"][0]["content"]
    assert "URL or a domain" in retry
    assert "the number 99" in retry


def test_a_refused_refresh_opens_one_issue_and_a_new_secret_starts_the_chain_again(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    assert runner() == 0
    world.x.valid.clear()
    runner.clock.at += timedelta(hours=1)
    assert runner() == 1
    assert "X refused the refresh token: HTTP 400 (invalid_request)" in runner.log
    assert [issue["title"] for issue in world.github.issues] == [TITLE]
    assert "X_REFRESH_TOKEN" in world.github.issues[0]["body"]
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts") == {"n": 1}
    assert "It is not retried." in world.github.issues[0]["body"]
    runner.clock.at += timedelta(hours=1)
    calls = world.github.calls
    assert runner() == 0
    assert "posting is stopped until a new X_REFRESH_TOKEN is pasted" in runner.log
    assert len(world.github.issues) == 1, "never a second issue"
    assert world.x.refreshes == 2, "the refused token is never sent to X again"
    assert world.github.calls == calls, "the issue is not touched again either"
    new_seed = fakes.token("Rn")
    world.x.valid.add(new_seed)
    runner.clock.at += timedelta(hours=1)
    assert runner(X_REFRESH_TOKEN=new_seed) == 0
    assert "from the X_REFRESH_TOKEN secret" in runner.log
    assert world.github.issues[0]["state"] == "closed"
    assert world.github.comments
    row = world.d1.row("SELECT version, seed FROM social_token")
    assert row == {"version": 2, "seed": seal.fingerprint(new_seed, fakes.CLIENT_SECRET)}
    assert len(world.x.posts) == 2


def test_a_chain_another_run_holds_is_never_spent(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    assert runner() == 0
    world.d1.db.execute(
        "UPDATE social_token SET lease = 'other.1', lease_until = '2026-10-26T17:00:00Z'"
    )
    world.d1.db.commit()
    runner.clock.at += timedelta(minutes=5)
    assert runner() == 1
    assert "token chain is not free" in runner.log
    assert world.x.refreshes == 1
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts") == {"n": 1}
    runner.clock.at += timedelta(minutes=30)
    assert runner() == 0, "an expired lease is taken over"
    assert len(world.x.posts) == 2


def test_a_post_x_may_have_made_is_never_sent_again(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.x.post_raises = httpx.ReadTimeout
    assert runner() == 1
    assert "it may be posted" in runner.log
    assert world.d1.row("SELECT state FROM social_posts") == {"state": "uncertain"}
    assert [issue["title"] for issue in world.github.issues] == [UNCERTAIN_TITLE]
    world.x.post_raises = None
    runner.clock.at += timedelta(days=1)
    assert runner() == 0
    assert world.x.posts == []


@pytest.mark.parametrize(
    ("status", "body"),
    [
        pytest.param(200, b"", id="200-empty"),
        pytest.param(201, b"<html><body>Created</body></html>", id="201-not-json"),
        pytest.param(201, b'{"errors": [{"title": "Service Unavailable"}]}', id="201-errors-only"),
        pytest.param(202, b'{"data": {"id": "1850000000000000002"}}', id="202"),
        pytest.param(204, b"", id="204"),
    ],
)
def test_a_2xx_post_answer_without_a_201_post_id_keeps_the_claim_and_opens_the_issue(
    tmp_path: Path, world: World, status: int, body: bytes
) -> None:
    """X made the post and answered oddly: the slot stays (uncertain), is never sent again,
    the owner's issue says how to check, and the run ends red."""
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.x.post_answer = (status, body)
    assert runner() == 1
    assert len(world.x.posts) == 1
    assert world.d1.row("SELECT state, post_id FROM social_posts") == {
        "state": "uncertain",
        "post_id": None,
    }
    assert f"X answered the post with HTTP {status}" in runner.log
    assert "it may be posted, so queue:0001 is never sent again" in runner.log
    assert "nothing was posted" not in runner.log
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_refusals") == {"n": 0}
    (issue,) = world.github.issues
    assert issue["title"] == UNCERTAIN_TITLE
    assert issue["body"].startswith(
        f"The post queue:0001 went to X, and X answered the post with HTTP {status}"
    )
    world.x.post_answer = None
    for event in ("push", "schedule"):
        runner.clock.at += timedelta(hours=12)
        assert runner(event) == 0
    assert len(world.x.posts) == 1, "never sent again"
    assert world.d1.row("SELECT state FROM social_posts") == {"state": "uncertain"}
    assert [(issue["title"], issue["state"]) for issue in world.github.issues] == [
        (UNCERTAIN_TITLE, "open")
    ]


def test_a_201_answer_with_the_post_id_records_the_post(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.x.post_answer = (201, b'{"data": {"id": "1850000000000000077", "text": "x"}}')
    assert runner() == 0
    assert world.d1.row("SELECT state, post_id FROM social_posts") == {
        "state": "posted",
        "post_id": "1850000000000000077",
    }
    assert world.github.issues == []


def test_a_2xx_refusal_after_the_post_request_never_drops_the_claim(
    tmp_path: Path, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule on ``sent``, held in the run too: a refusal with a 2xx status keeps the claim."""

    def odd(_self: XClient, _access: str, _text: str, _media_id: str) -> str:
        raise RefusedError("X refused the post: HTTP 200", status=200)

    monkeypatch.setattr(XClient, "post", odd)
    runner = make(tmp_path, world, queue=[queued("0001")])
    assert runner() == 1
    assert world.d1.row("SELECT state FROM social_posts") == {"state": "uncertain"}
    assert [issue["title"] for issue in world.github.issues] == [UNCERTAIN_TITLE]


def test_a_post_x_refused_is_tried_again_by_a_later_run(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.x.post_status = 429
    assert runner() == 1
    assert "X refused the post: HTTP 429 (Forbidden)" in runner.log
    assert world.github.issues == [], "a refusal a later run may get past opens no issue"
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts") == {"n": 0}
    assert world.d1.row("SELECT version FROM social_token") == {"version": 1}
    world.x.post_status = 201
    runner.clock.at += timedelta(hours=1)
    assert runner() == 0
    assert len(world.x.posts) == 1


def test_a_token_without_media_write_posts_nothing(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.x.scope = "tweet.read tweet.write users.read offline.access"
    assert runner() == 1
    assert "lacks the scopes media.write" in runner.log
    assert world.x.uploads == 0
    assert world.github.issues[0]["body"].startswith("The X token lacks the scopes media.write")
    assert world.d1.row("SELECT version FROM social_token") == {"version": 1}


def test_a_failed_upload_posts_nothing(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.x.upload_status = 403
    assert runner() == 1
    assert world.x.posts == []
    assert "X refused the image upload: HTTP 403 (Forbidden)" in runner.log


def test_an_unanswered_refresh_spends_no_claim(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.x.refresh_status = 503
    assert runner() == 1
    assert "the next run tries again" in runner.log
    assert world.d1.row("SELECT lease FROM social_token") == {"lease": None}
    assert world.github.issues == []


def test_a_rotated_token_that_cannot_be_stored_opens_the_issue(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.d1.fail_next = ["UPDATE social_token SET version"] * 3 + [
        "SELECT version, sealed, lease"
    ] * 6
    assert runner() == 1, "red: the owner must paste a new token"
    assert "could not be stored" in runner.log
    assert len(world.x.posts) == 1, "the fresh access token still posts the claimed post"
    assert [issue["title"] for issue in world.github.issues] == [TITLE]
    assert world.github.issues[0]["state"] == "open", "the issue stays open: the chain is lost"
    body = world.github.issues[0]["body"]
    assert body.startswith("X gave the posting workflow a new refresh token, but it could not")
    assert "X refused" not in body


def test_a_store_whose_answer_was_lost_reads_its_write_back(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.d1.fail_next = ["ran:UPDATE social_token SET version"]
    assert runner() == 0
    assert world.d1.row("SELECT version FROM social_token") == {"version": 1}
    assert len(world.x.posts) == 1


def test_a_queued_post_that_fails_the_checks_is_refused_and_the_next_one_goes(
    tmp_path: Path, world: World
) -> None:
    bad = queued("0001", "Snowlight is live now, the most accurate map. Visit snowlightmap.com!!")
    runner = make(tmp_path, world, queue=[bad, queued("0002")])
    assert runner() == 1
    assert "queued post 0001 is refused" in runner.log
    assert len(world.x.posts) == 1
    assert world.d1.row("SELECT slot FROM social_posts") == {"slot": "queue:0002"}


def test_missing_secrets_and_database_stop_before_anything_is_spent(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    assert runner(X_REFRESH_TOKEN="") == 0
    assert "nothing posts" in runner.log
    assert runner(CLOUDFLARE_API_TOKEN="") == 0
    assert "CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID" in runner.log
    world.d1.has_database = False
    assert runner() == 1
    assert "no database snowlight-live-state" in runner.log
    world.d1.has_database = True
    world.d1.fail_next = ["CREATE TABLE"] * 2
    assert runner() == 1
    assert "the D1 store failed" in runner.log
    assert world.x.refreshes == 0


def test_a_malformed_social_folder_stops_the_run_red(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world)
    (tmp_path / "social" / "facts.md").write_text("- [LIVE] Bad Id: nothing\n")
    assert runner() == 1
    assert "facts line 1 does not parse" in runner.log


def test_a_stored_token_under_another_client_secret_opens_the_issue(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    assert runner() == 0
    other = seal.seal("x", fakes.token("Zz"), version=1)
    world.d1.db.execute("UPDATE social_token SET sealed = ?", (other,))
    world.d1.db.commit()
    runner.clock.at += timedelta(hours=1)
    assert runner() == 1
    assert "did not open" in runner.log
    assert len(world.github.issues) == 1


FIRST = (
    "Snowlight dev log: the closings reader runs 24/7 in practice mode and checks lists every"
    " 5 minutes in the morning and evening. Waitlist link in my bio."
)


def test_a_queued_post_goes_with_the_fresh_picture(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[unpictured("0001", FIRST, ["national", "district"])])
    runner.picture = make_picture(tmp_path, at("2026-10-26T16:35:00"))
    assert runner() == 0
    assert len(world.x.posts) == 1
    assert b"FRESH-PICTURE" in world.x.uploaded[0]
    assert f"social: picture: {FRESH_SHOWS} (taken for this post)" in runner.log
    posted = world.d1.row("SELECT image FROM social_posts")
    assert posted == {"image": "fresh-20261026t1635"}


@pytest.mark.parametrize(
    ("kind", "taken", "why"),
    [
        ("closings", "2026-10-26T16:35:00", None),  # a kind the queued text does not fit
        ("national", "2026-10-26T15:00:00", "is not from this run"),
        ("national", "2026-10-26T16:50:00", "is not from this run"),  # from the future
    ],
)
def test_without_a_fitting_fresh_picture_the_newest_library_image_goes_as_older(
    tmp_path: Path, world: World, kind: str, taken: str, why: str | None
) -> None:
    runner = make(tmp_path, world, queue=[unpictured("0001", FIRST, ["national", "district"])])
    runner.picture = make_picture(tmp_path, at(taken), kind=kind)
    assert runner() == 0
    assert b"FRESH-PICTURE" not in world.x.uploaded[0]
    assert "(an older picture, taken 2026-10-20, not a picture of now)" in runner.log
    assert world.d1.row("SELECT image FROM social_posts") == {"image": "img-2"}
    if why is not None:
        assert why in runner.log
        assert "the dev_log post uses img-2 from 2026-10-20, as an older picture" in runner.log


def test_a_missing_or_malformed_picture_falls_back(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[unpictured("0001", FIRST)])
    runner.picture = tmp_path / "nothing"
    assert runner() == 0
    assert "the Render step left no fresh picture" in runner.log
    folder = make_picture(tmp_path, at("2026-10-26T16:35:00"))
    (folder / "picture.json").write_text("not json")
    runner.picture = folder
    world.d1.db.execute("DELETE FROM social_posts")
    world.d1.db.commit()
    assert runner() == 0
    assert "the fresh picture is malformed" in runner.log
    assert [b"FRESH-PICTURE" in body for body in world.x.uploaded] == [False, False]


def test_an_older_picture_is_never_called_current(tmp_path: Path, world: World) -> None:
    now_text = FIRST.replace("Waitlist link", "Right now it is quiet. Waitlist link")
    runner = make(tmp_path, world, queue=[unpictured("0001", now_text)])
    assert runner() == 1
    assert "it says 'right now' but the picture is an older one" in runner.log
    assert world.x.posts == []
    runner.picture = make_picture(tmp_path, at("2026-10-26T16:35:00"))
    assert runner() == 0, "the same words go with a current fresh picture"
    runner.picture = make_picture(tmp_path, at("2026-10-26T16:35:00"), current=False)
    world.d1.db.execute("DELETE FROM social_posts")
    world.d1.db.commit()
    assert runner() == 1, "a fresh picture of an old closings file is not current"


def test_a_queued_post_with_no_picture_at_all_is_refused(tmp_path: Path, world: World) -> None:
    runner = Runner(
        make_root(tmp_path, queue=[unpictured("0001", FIRST)], images=0),
        world,
        Clock(at("2026-10-26T16:37:00")),
    )
    assert runner() == 1
    assert "it has no picture" in runner.log
    assert world.x.refreshes == 0


def test_haiku_sees_only_the_fresh_picture(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world)
    runner.picture = make_picture(tmp_path, at("2026-10-26T16:35:00"))
    runner.haiku = FakeAnthropic([{**GOOD_DEV_LOG, "image_id": "fresh-20261026t1635"}, dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    prompt = runner.haiku.requests[0]["messages"][0]["content"]
    assert f"- fresh-20261026t1635: {FRESH_SHOWS} (taken for this post)" in prompt
    assert "img-1" not in prompt
    assert "img-2" not in prompt
    assert (
        f"Image: {FRESH_SHOWS} (taken for this post)"
        in (runner.haiku.requests[1]["messages"][0]["content"])
    )
    assert b"FRESH-PICTURE" in world.x.uploaded[0]


def test_the_fresh_card_goes_with_its_alt_text(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[unpictured("0001", FIRST)])
    runner.picture = make_picture(tmp_path, at("2026-10-26T16:35:00"))
    assert runner() == 0
    assert world.x.alts == [
        {
            "id": "1880028106020515840",
            "metadata": {
                "alt_text": {"text": "SYNTHETIC alt text of the fresh dev-log card for the tests"}
            },
        }
    ]
    assert len(world.x.posts) == 1


def test_a_refused_alt_text_does_not_stop_the_post(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[unpictured("0001", FIRST)])
    runner.picture = make_picture(tmp_path, at("2026-10-26T16:35:00"))
    world.x.alt_status = 403
    assert runner() == 0
    assert "the alt text was not set (X refused the alt text: HTTP 403 (Forbidden))" in runner.log
    assert len(world.x.posts) == 1


def test_a_style_whose_card_failed_takes_the_library_card(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[unpictured("0001", FIRST)])
    runner.picture = make_picture(tmp_path, at("2026-10-26T16:35:00"), cards=("waitlist",))
    assert runner() == 0
    assert "no fresh dev-log card; that post uses the library's card" in runner.log
    assert b"FRESH-PICTURE" not in world.x.uploaded[0]
    assert world.d1.row("SELECT image FROM social_posts") == {"image": "img-2"}


def test_a_fallback_card_in_the_render_folder_is_not_taken_as_fresh(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[unpictured("0001", FIRST)])
    folder = make_picture(tmp_path, at("2026-10-26T16:35:00"))
    note = folder / "dev-log.json"
    note.write_text(note.read_text().replace('"fallback": false', '"fallback": true'))
    runner.picture = folder
    assert runner() == 0
    assert "the dev-log card is not this run's" in runner.log
    assert b"FRESH-PICTURE" not in world.x.uploaded[0]


def test_the_library_falls_back_by_the_post_style(tmp_path: Path) -> None:
    root = make_root(tmp_path, images=0)
    images = root / "social" / "images"
    for name, style, day in (
        ("old-dev", "dev_log", "2026-10-20"),
        ("new-wait", "waitlist", "2026-10-26"),
    ):
        (images / f"{name}.png").write_bytes(fakes.PNG)
        (images / f"{name}.json").write_text(
            json.dumps(
                {
                    "id": name,
                    "file": f"{name}.png",
                    "day": day,
                    "shows": "SYNTHETIC test card: the national map at night",
                    "alt": "SYNTHETIC alt text of a library card for the tests",
                    "style": style,
                }
            )
        )
    content = load(root)
    dev = content.newest("dev_log")
    wait = content.newest("waitlist")
    assert dev is not None
    assert wait is not None
    assert (dev.id, wait.id) == ("old-dev", "new-wait")
    assert dev.alt == "SYNTHETIC alt text of a library card for the tests"
    assert "(an older picture, taken 2026-10-20, not a picture of now)" in dev.describe()


INJECTIONS = ("x\n::stop-commands::pwn", "x\r\n::stop-commands::pwn", "x\u2028##[add-mask]y")


def test_haikus_free_text_never_starts_a_workflow_command(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world)
    runner.haiku = FakeAnthropic(
        [dict(GOOD_DEV_LOG), {"ok": False, "problems": list(INJECTIONS)}, dict(GOOD_DEV_LOG), OK]
    )
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert len(world.x.posts) == 1
    lines = runner.log.splitlines()
    refused = next(line for line in lines if "refused" in line)
    assert "stop-commands" in refused
    assert "::stop-commands" not in refused
    assert not any(line.startswith(("::stop", "##[")) for line in lines)
    # The masks come after the refusal and are still commands the runner reads.
    assert any(line.startswith("::add-mask::") for line in lines[lines.index(refused) :])


def test_a_queued_posts_text_never_starts_a_workflow_command(tmp_path: Path, world: World) -> None:
    text = "Dev log: the calculator\n::stop-commands::pwn\r\n::add-mask::x is fine."
    runner = make(tmp_path, world, queue=[queued("0001", text), queued("0002")])
    assert runner() == 1  # 0001 refused (the log says why), 0002 posted
    assert len(world.x.posts) == 1
    assert sum(line.startswith("::error::") for line in runner.log.splitlines()) == 1


@pytest.mark.parametrize("injected", INJECTIONS)
def test_one_say_is_one_line_and_never_a_command(injected: str) -> None:
    stream = io.StringIO()
    output = Output({"GITHUB_ACTIONS": "true"}, stream)
    output.say(f"social: {injected}")
    output.say(f"::warning::social: {injected}")
    output.say(f"  ::set-output name=a::{injected}")
    output.mask("Two9PiecesTwo9Pieces\r\nSecond9PieceSecond9Piece")
    lines = stream.getvalue().splitlines()
    assert lines[0].startswith("social: x ")
    assert lines[1].startswith("::warning::social: x ")
    assert lines[2].startswith(": :set-output")
    for line in lines[:3]:
        assert "::stop-commands::" not in line
        assert "##[" not in line
    assert lines[3:] == [
        "::add-mask::Two9PiecesTwo9Pieces",
        "::add-mask::Second9PieceSecond9Piece",
    ]


def test_the_real_anthropic_client_retries_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from snowlight.social import post  # noqa: PLC0415 - the module's private factory

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SYNTHETIC")
    client = post._anthropic()
    assert client.max_retries == 0, "the four-call cap counts requests, so nothing retries"
    assert client.timeout == 60.0


@pytest.mark.parametrize("missing", ["tweet.read", "users.read", "tweet.write"])
def test_a_token_without_a_scope_the_post_needs_posts_nothing_and_says_which(
    tmp_path: Path, world: World, missing: str
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.x.scope = " ".join(
        scope
        for scope in ("tweet.read", "tweet.write", "users.read", "offline.access", "media.write")
        if scope != missing
    )
    assert runner() == 1
    assert f"lacks the scopes {missing}" in runner.log
    assert world.x.uploads == 0
    assert world.x.posts == []
    assert f"lacks the scopes {missing}" in world.github.issues[0]["body"]


def test_a_strangers_issue_with_the_same_title_is_never_patched_or_closed(
    tmp_path: Path, world: World
) -> None:
    world.github.issues.append(
        {"number": 1, "state": "open", "title": TITLE, "body": "theirs", "user": fakes.STRANGER}
    )
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    world.x.valid.clear()
    assert runner() == 1
    stranger, mine = world.github.issues
    assert stranger["body"] == "theirs"
    assert mine["user"] == fakes.BOT_USER
    assert mine["title"] == TITLE
    assert mine["body"].startswith(
        "X refused the refresh token the posting workflow uses (HTTP 400 (invalid_request)) ("
    )
    new_seed = fakes.token("Rn")
    world.x.valid.add(new_seed)
    runner.clock.at += timedelta(hours=1)
    assert runner(X_REFRESH_TOKEN=new_seed) == 0
    assert stranger["state"] == "open"
    assert mine["state"] == "closed"
    assert [number for number, _ in world.github.comments] == [2]


def test_a_new_secret_is_checked_and_the_issue_closed_on_a_run_with_nothing_to_post(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    assert runner() == 0  # 0001 posted; the queue is empty now and there is no Anthropic key
    world.x.valid.clear()
    runner.clock.at += timedelta(hours=1)
    (tmp_path / "social" / "queue" / "0002.json").write_text(json.dumps(queued("0002")))
    (tmp_path / "social" / "queue" / "0002.png").write_bytes(fakes.PNG)
    assert runner() == 1
    assert world.github.issues[0]["state"] == "open"
    refreshes = world.x.refreshes
    # The same secret again: nothing is tried on a run with nothing new to post.
    world.d1.db.execute("DELETE FROM social_posts WHERE slot = 'queue:0002'")
    world.d1.db.commit()
    (tmp_path / "social" / "queue" / "0002.json").unlink()
    runner.clock.at += timedelta(days=1)
    assert runner("schedule") == 0
    assert world.x.refreshes == refreshes
    assert "until a new X_REFRESH_TOKEN is pasted" in runner.log
    # The owner pastes a new one: the scheduled run checks it and closes the issue.
    new_seed = fakes.token("Rn")
    world.x.valid.add(new_seed)
    runner.clock.at += timedelta(days=1)
    assert runner("schedule", X_REFRESH_TOKEN=new_seed) == 0
    assert world.x.refreshes == refreshes + 1
    assert len(world.x.posts) == 1
    assert world.github.issues[0]["state"] == "closed"
    assert world.d1.row("SELECT refused FROM social_token") == {"refused": None}


def test_a_claim_whose_answer_was_lost_is_read_back_and_posts(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.d1.fail_next = ["ran:INSERT INTO social_posts"]
    assert runner() == 0
    assert len(world.x.posts) == 1
    assert world.d1.row("SELECT state FROM social_posts") == {"state": "posted"}


def test_a_claim_a_stopped_run_left_is_never_sent_and_warned_about(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.d1.db.execute(TABLES_SQL)
    world.d1.db.execute(
        "INSERT INTO social_posts (slot, kind, style, day, state, image, claimed_at, run)"
        " VALUES ('queue:0001', 'queue', 'dev_log', '2026-10-26', 'claimed', 'img-1',"
        " '2026-10-26T15:00:00Z', '999.1')"
    )
    world.d1.db.commit()
    assert runner() == 0
    assert world.x.posts == []
    assert "::warning::social: queue:0001 was claimed by run 999.1" in runner.log
    assert "delete its social_posts row" in runner.log


def test_a_draft_after_a_thinking_block_is_read_from_its_text_block(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world)
    runner.haiku = FakeAnthropic(
        [{**GOOD_DEV_LOG, "_thinking": ""}, {**OK, "_thinking": "The draft is true."}]
    )
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert world.x.posts[0]["text"] == GOOD_DEV_LOG["text"]


def test_an_answer_cut_off_while_thinking_is_a_failed_try(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world)
    cut = {"_thinking": "", "_only_thinking": True, "_stop": "max_tokens"}
    runner.haiku = FakeAnthropic([dict(cut), dict(cut)])
    # Both tries ran out at the cap: the day's post is lost to it, so the run ends red with a
    # warning the lead sees (MAX_TOKENS may need raising), and each call's tokens are logged.
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 1
    assert world.x.posts == []
    assert "Haiku stopped early (max_tokens)" in runner.log
    assert "social: Haiku calls this run: 2 (output tokens each, of at most 1024: 10, 10)" in (
        runner.log
    )
    assert "::warning::social: 2 of Haiku's answers ran out at 1024 tokens" in runner.log


def test_one_answer_cut_off_then_a_good_one_posts_green(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world)
    cut = {"_thinking": "", "_only_thinking": True, "_stop": "max_tokens"}
    runner.haiku = FakeAnthropic([dict(cut), dict(GOOD_DEV_LOG), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert len(world.x.posts) == 1
    assert "ran out at" not in runner.log


def test_the_cards_handed_over_by_the_render_jobs_log_go_out(tmp_path: Path, world: World) -> None:
    from snowlight.social.relay import receive, send  # noqa: PLC0415 - the relay's two ends

    runner = make(tmp_path, world, queue=[unpictured("0001", FIRST)])
    rendered = make_picture(tmp_path, at("2026-10-26T16:35:00"))
    lines: list[str] = []
    digest = send(rendered, lines.append, None)
    taken = tmp_path / "taken"
    receive("\n".join(f"2026-10-26T16:36:00.0Z {line}" for line in lines), digest, taken)
    assert not (taken / "picture.png").exists()
    runner.picture = taken
    assert runner() == 0
    assert b"FRESH-PICTURE" in world.x.uploaded[0]


def test_a_card_whose_alt_text_holds_a_link_is_not_used(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[unpictured("0001", FIRST)])
    folder = make_picture(tmp_path, at("2026-10-26T16:35:00"))
    card = json.loads((folder / "dev-log.json").read_text())
    card["alt"] = "SYNTHETIC alt text that sends people to evil.example for the tests"
    (folder / "dev-log.json").write_text(json.dumps(card))
    runner.picture = folder
    assert runner() == 0
    assert b"FRESH-PICTURE" not in world.x.uploaded[0]
    assert "alt text holds a link" in runner.log


# Chances while the site is locked (F). The fakes' facts file has no LIVE `chances` fact, so
# these runs are in that mode; every predictions number here is SYNTHETIC.

DISTRICT_SHOWS = (
    "SYNTHETIC: a picture of the Snowlight map zoomed to the schools of a public school district"
    " in Montana: its chance of no school on Tuesday, October 27 is 74%, the highest of any"
    " district that day."
)
DISTRICT_CHANCE: dict[str, Any] = {
    "text": "74%",
    "day": "2026-10-27",
    "scope": "district",
    "districts": 18227,
    "at_most": False,
}
DISTRICT_SEEN: dict[str, Any] = {"chance": DISTRICT_CHANCE, "state": "Montana"}


def _with_seen(folder: Path, seen: dict[str, Any]) -> Path:
    note = folder / "picture.json"
    data = json.loads(note.read_text())
    data["seen"] = seen
    note.write_text(json.dumps(data))
    return folder


@pytest.mark.parametrize(
    "case",
    [
        ("district", DISTRICT_SHOWS, DISTRICT_SEEN, None),
        (
            "national",
            FRESH_SHOWS,
            {"chance": {**DISTRICT_CHANCE, "scope": "highest"}},
            None,
        ),
        ("national", FRESH_SHOWS + " Not in the picture: a chance of 1% everywhere.", {}, None),
        ("national", FRESH_SHOWS, {}, "The dark national Snowlight map, top chance 74%"),
    ],
)
def test_a_fresh_picture_that_gives_a_chance_is_not_used_while_chances_are_testing(
    tmp_path: Path, world: World, case: tuple[str, str, dict[str, Any], str | None]
) -> None:
    kind, shows, seen, alt = case
    runner = make(tmp_path, world, queue=[unpictured("0001", FIRST)])
    folder = _with_seen(
        make_picture(tmp_path, at("2026-10-26T16:35:00"), kind=kind, shows=shows), seen
    )
    if alt is not None:
        for post in ("dev-log", "waitlist"):
            note = folder / f"{post}.json"
            note.write_text(note.read_text().replace("SYNTHETIC alt text", alt))
    runner.picture = folder
    assert runner() == 0
    assert "gives a chance" in runner.log
    assert b"FRESH-PICTURE" not in world.x.uploaded[0]
    assert world.d1.row("SELECT image FROM social_posts") == {"image": "img-2"}
    assert "74" not in "".join(alt["metadata"]["alt_text"]["text"] for alt in world.x.alts)


def test_haiku_gives_no_chance_while_chances_are_testing(tmp_path: Path, world: World) -> None:
    """Rule F end to end: Haiku is told chances are TESTING, a draft with a district's 74% or
    the nation's 1% is refused, and what is posted holds no percent and no chance word."""
    runner = make(tmp_path, world)
    runner.picture = make_picture(tmp_path, at("2026-10-26T16:35:00"))
    fresh = "fresh-20261026t1635"
    leaky = {
        **GOOD_DEV_LOG,
        "image_id": fresh,
        "text": "Dev log: a district in Montana is at 74% for Tuesday, and 1% everywhere else."
        " The closings reader runs 24/7 in practice mode.",
    }
    runner.haiku = FakeAnthropic([leaky, {**GOOD_DEV_LOG, "image_id": fresh}, dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    first = runner.haiku.requests[0]["messages"][0]["content"]
    assert "The chances are TESTING" in first
    assert "never say how high or low a chance is" in first.replace("\n", " ")
    retry = runner.haiku.requests[1]["messages"][0]["content"]
    assert "it gives a chance as a number ('%')" in retry
    check = runner.haiku.requests[2]["messages"][0]["content"]
    assert "The chances are TESTING (the site is locked)" in check
    posted = world.x.posts[-1]["text"]
    assert "%" not in posted
    assert "chance" not in posted.lower()


def test_with_chances_live_a_district_picture_goes_out(tmp_path: Path, world: World) -> None:
    """The switch back: the same district picture is used once the facts mark chances LIVE."""
    facts = fakes.FACTS + (
        "- [LIVE] chances: Each school day the model works out a chance of no school."
        " | terms: chance, chances\n"
    )
    runner = Runner(
        make_root(tmp_path, queue=[unpictured("0001", FIRST)], facts=facts),
        world,
        Clock(at("2026-10-26T16:37:00")),
    )
    folder = make_picture(
        tmp_path, at("2026-10-26T16:35:00"), kind="district", shows=DISTRICT_SHOWS
    )
    runner.picture = _with_seen(folder, DISTRICT_SEEN)
    assert runner() == 0
    assert b"FRESH-PICTURE" in world.x.uploaded[0]


def test_a_library_card_that_gives_a_chance_stops_the_run_while_chances_are_testing(
    tmp_path: Path, world: World
) -> None:
    root = make_root(tmp_path, queue=[unpictured("0001", FIRST)])
    note = root / "social" / "images" / "img-1.json"
    entry = json.loads(note.read_text())
    entry["shows"] += ". Not in the picture: the chance of no school is at most 1% everywhere."
    note.write_text(json.dumps(entry))
    with pytest.raises(ContentError, match="gives a chance while chances are TESTING"):
        load(root)
    runner = Runner(root, world, Clock(at("2026-10-26T16:37:00")))
    assert runner() == 1
    assert world.x.posts == []
    assert world.x.refreshes == 0


# -- stopped posting spends nothing (no Haiku call, no claim, no refresh) ---------------------


def _refused_chain(tmp_path: Path, world: World) -> Runner:
    """A world whose chain X refused (one post went out first), with more queued."""
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002"), queued("0003")])
    assert runner() == 0
    world.x.valid.clear()
    runner.clock.at += timedelta(hours=1)
    assert runner() == 1
    assert world.x.refreshes == 2
    assert world.d1.row("SELECT refused FROM social_token") == {
        "refused": seal.fingerprint(fakes.SEED, fakes.CLIENT_SECRET)
    }
    return runner


def test_a_refused_chain_sends_nothing_on_queued_push_runs(tmp_path: Path, world: World) -> None:
    runner = _refused_chain(tmp_path, world)
    calls = world.github.calls
    for _ in range(4):
        runner.clock.at += timedelta(hours=1)
        assert runner() == 0
        assert "posting is stopped until a new X_REFRESH_TOKEN is pasted" in runner.log
        assert "claimed" not in runner.log
    assert world.x.refreshes == 2
    assert world.github.calls == calls
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts") == {"n": 1}


def test_a_refused_chain_asks_haiku_nothing_on_scheduled_runs(tmp_path: Path, world: World) -> None:
    runner = _refused_chain(tmp_path, world)
    for name in ("0002", "0003"):  # nothing queued: the scheduled runs would ask Haiku
        (tmp_path / "social" / "queue" / f"{name}.json").unlink()
    runner.haiku = FakeAnthropic([])
    for when in ("2026-10-27T16:37:00", "2026-10-27T20:41:00", "2026-10-28T16:37:00"):
        runner.clock.at = at(when)
        assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
        assert "posting is stopped until a new X_REFRESH_TOKEN is pasted" in runner.log
    assert runner.haiku.requests == []
    assert world.x.refreshes == 2
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_haiku_days") == {"n": 0}
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts") == {"n": 1}


def test_a_new_secret_after_a_refused_chain_posts_the_queue_again(
    tmp_path: Path, world: World
) -> None:
    runner = _refused_chain(tmp_path, world)
    new_seed = fakes.token("Rn")
    world.x.valid.add(new_seed)
    runner.clock.at += timedelta(hours=1)
    assert runner(X_REFRESH_TOKEN=new_seed) == 0
    assert world.x.refreshes == 3
    assert len(world.x.posts) == 2
    assert world.github.issues[0]["state"] == "closed"


# -- at most three Haiku tries a day -------------------------------------------------------


BAD_DRAFT = {**GOOD_DEV_LOG, "text": "Dev log: 99% sure the map is live now at snowlightmap.com"}


def test_a_failed_haiku_try_counts_toward_the_day_s_three(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, when="2026-10-27T00:41:00")
    for when in ("00:41", "13:07", "17:37"):
        runner.clock.at = at(f"2026-10-27T{when}:00")
        runner.haiku = FakeAnthropic([dict(BAD_DRAFT), dict(BAD_DRAFT)])
        assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
        assert "no Haiku draft passed: no post from this try" in runner.log
    assert world.d1.rows("SELECT day, state FROM social_haiku_days ORDER BY day") == [
        {"day": f"2026-10-27#{n}", "state": "failed"} for n in (1, 2, 3)
    ]
    runner.clock.at = at("2026-10-27T23:00:00")
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert runner.haiku.requests == [], "no fourth try that day"
    assert "already asked to write 3 times on 2026-10-27" in runner.log
    assert world.x.posts == []
    assert world.x.refreshes == 0
    runner.clock.at = at("2026-10-28T13:07:00")
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert len(runner.haiku.requests) == 2, "the next day writes again"
    assert len(world.x.posts) == 1


def test_a_try_from_before_the_three_a_day_counts_too(tmp_path: Path, world: World) -> None:
    """A row named by the day alone (one try a day, before Oct 27) counts as that day's
    first try: the day gets two more, never a fresh three."""
    runner = make(tmp_path, world, when="2026-10-27T13:07:00")
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])
    for sql in TABLES:
        world.d1.db.execute(sql)
    world.d1.db.execute(
        "INSERT INTO social_haiku_days (day, state, run, at) VALUES"
        " ('2026-10-27', 'failed', 'old', '2026-10-27T00:00:00Z')"
    )
    world.d1.db.commit()
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert world.d1.row("SELECT slot FROM social_posts") == {"slot": "haiku:2026-10-27#2"}


def test_the_noon_run_writes_when_the_morning_run_never_ran(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, when="2026-10-27T17:37:00")
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert len(world.x.posts) == 1
    row = world.d1.row("SELECT day, state FROM social_haiku_days")
    assert row == {
        "day": "2026-10-27#1",
        "state": f"drafted {draft_mark(str(GOOD_DEV_LOG['text']))}",
    }


def test_a_run_that_lost_the_race_for_its_try_asks_haiku_nothing(
    tmp_path: Path, world: World
) -> None:
    """Another run made this try's row (``<day>#1``) between this run's count and its own
    insert: no second try, no Anthropic call and no post."""
    runner = make(tmp_path, world, when="2026-10-27T13:07:00")
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])

    def other_run() -> None:
        world.d1.db.execute(
            "INSERT INTO social_haiku_days (day, state, run, at) VALUES"
            " ('2026-10-27#1', 'writing', 'other', '2026-10-27T13:07:01Z')"
        )
        world.d1.db.commit()

    world.d1.hooks.append(("INSERT INTO social_haiku_days", other_run))
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert "Haiku was already asked to write for 2026-10-27#1 (writing): no second try" in (
        runner.log
    )
    assert runner.haiku.requests == []
    assert world.x.posts == []
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts") == {"n": 0}


def test_a_try_whose_slot_was_already_posted_asks_haiku_nothing(
    tmp_path: Path, world: World
) -> None:
    """The slot ``haiku:<day>#1`` holds a post while no try row counts it (a row lost to an
    error): no Anthropic call, never a second post in that slot."""
    runner = make(tmp_path, world, when="2026-10-27T17:37:00")
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])
    for sql in TABLES:
        world.d1.db.execute(sql)
    world.d1.db.execute(
        "INSERT INTO social_posts (slot, kind, style, day, state, image, claimed_at, run)"
        " VALUES ('haiku:2026-10-27#1', 'haiku', 'dev_log', '2026-10-27', 'posted', 'fresh',"
        " '2026-10-27T13:07:00Z', 'old')"
    )
    world.d1.db.commit()
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert "Haiku already posted for 2026-10-27#1" in runner.log
    assert runner.haiku.requests == []
    assert world.x.posts == []


def test_a_draft_the_same_as_a_recent_haiku_post_is_never_sent(
    tmp_path: Path, world: World
) -> None:
    """X refuses a duplicate post, and a refusal for good holds all posting: a later try
    whose draft says the same as an earlier Haiku post (case and punctuation aside) is
    dropped and counts as a failed try."""
    runner = make(tmp_path, world, when="2026-10-27T00:41:00")
    same = {**GOOD_DEV_LOG, "text": str(GOOD_DEV_LOG["text"]).upper().replace(":", " -")}
    runs = [
        ("2026-10-27T00:41:00", GOOD_DEV_LOG),  # dev log, posted
        ("2026-10-27T13:07:00", GOOD_DRAFT),  # the waitlist post between
        ("2026-10-27T17:37:00", same),  # a dev log again, saying the same
        ("2026-10-30T13:07:00", same),  # days later, still recent
    ]
    for when, draft in runs:
        runner.clock.at = at(when)
        runner.haiku = FakeAnthropic([dict(draft), dict(OK)])
        assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
        assert ("says the same as a recent or queued post" in runner.log) is (draft is same)
    assert [post["text"] for post in world.x.posts] == [GOOD_DEV_LOG["text"], GOOD_DRAFT["text"]]
    states = [row["state"] for row in world.d1.rows("SELECT state FROM social_haiku_days")]
    assert states[2:] == ["failed", "failed"]


def test_a_draft_the_same_as_a_posted_queued_post_is_never_sent(
    tmp_path: Path, world: World
) -> None:
    """A queued post goes out and its file is removed from the queue (the lead's step): its
    mark stays in ``social_marks``, so a later Haiku draft with the same words (case and
    punctuation aside) is dropped as a failed try, with no call to X."""
    text = str(GOOD_DEV_LOG["text"]) + " Waitlist link in my bio."
    runner = make(tmp_path, world, queue=[queued("0001", text)], when="2026-10-26T13:07:00")
    assert runner("schedule") == 0
    assert [post["text"] for post in world.x.posts] == [text]
    assert world.d1.row("SELECT slot, mark FROM social_marks") == {
        "slot": "queue:0001",
        "mark": draft_mark(text),
    }
    (tmp_path / "social" / "queue" / "0001.json").unlink()
    (tmp_path / "social" / "queue" / "0001.png").unlink()
    refreshes = world.x.refreshes
    runner.clock.at = at("2026-10-27T13:07:00")
    # The day's first Haiku post follows a dev log, so it is a waitlist post.
    same = {**GOOD_DRAFT, "text": text.lower().replace(":", " -").replace(".", "")}
    runner.haiku = FakeAnthropic([dict(same), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert "says the same as a recent or queued post" in runner.log
    assert len(world.x.posts) == 1
    assert world.x.refreshes == refreshes, "no call to X for a dropped draft"
    assert world.d1.row("SELECT state FROM social_haiku_days") == {"state": "failed"}


def test_a_draft_the_same_as_a_post_still_queued_is_never_sent(
    tmp_path: Path, world: World
) -> None:
    """A queued post that waits (refused by the checks today) would later go out after a Haiku
    post with its words, and X would refuse it: such a draft is dropped too."""
    text = str(GOOD_DEV_LOG["text"]) + " Waitlist link in my bio."
    runner = make(tmp_path, world, queue=[queued("0001", text + "!!")], when="2026-10-27T13:07:00")
    runner.haiku = FakeAnthropic([{**GOOD_DEV_LOG, "text": text}, dict(OK)])
    runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY)
    assert "queued post 0001 is refused: it has '!!'" in runner.log
    assert "says the same as a recent or queued post" in runner.log
    assert world.x.posts == []


def test_a_mark_that_cannot_be_kept_claims_nothing(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.d1.fail_next += ["INSERT INTO social_marks"] * 2  # the first and its one retry
    assert runner() == 1
    assert world.x.posts == []
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts") == {"n": 0}
    assert runner() == 0
    assert len(world.x.posts) == 1


def test_a_haiku_post_x_did_not_take_is_never_sent_again_and_counts_as_a_try(
    tmp_path: Path, world: World
) -> None:
    """X never got the post (the refresh failed): nothing went out, and the day's next run is
    a new try of its own, with its own slot, posted once."""
    runner = make(tmp_path, world, when="2026-10-27T13:07:00")
    world.x.refresh_status = 503
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 1
    world.x.refresh_status = 200
    runner.clock.at = at("2026-10-27T17:37:00")
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert [post["text"] for post in world.x.posts] == [GOOD_DEV_LOG["text"]], runner.log
    assert world.d1.row("SELECT slot FROM social_posts") == {"slot": "haiku:2026-10-27#2"}


def test_a_bad_anthropic_key_stops_at_once_and_ends_red(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, when="2026-10-27T16:37:00")
    for status in (401, 404):
        runner.haiku = FakeAnthropic([{"status": status}, dict(GOOD_DEV_LOG), dict(OK)])
        assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 1
        assert len(runner.haiku.requests) == 1, "no second try after a fatal answer"
        assert f"the Anthropic API answered HTTP {status}" in runner.log
        assert "check ANTHROPIC_API_KEY" in runner.log
        assert world.d1.row("SELECT state FROM social_haiku_days") == {"state": "failed"}
        world.d1.db.execute("DELETE FROM social_haiku_days")
        world.d1.db.commit()
    assert world.x.refreshes == 0


def test_an_overloaded_anthropic_answer_is_one_failed_try(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, when="2026-10-27T16:37:00")
    runner.haiku = FakeAnthropic([{"status": 529}, dict(GOOD_DEV_LOG), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert len(runner.haiku.requests) == 3
    assert len(world.x.posts) == 1


# -- the token chain's failure paths ----------------------------------------------------------


def test_a_rotated_token_lost_to_a_changed_row_stops_the_chain(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])

    def another_run_takes_the_row() -> None:
        world.d1.db.execute("UPDATE social_token SET lease = 'other.1'")
        world.d1.db.commit()

    world.d1.hooks = [("UPDATE social_token SET version", another_run_takes_the_row)]
    assert runner() == 1, "red: the chain is lost"
    assert "the rotated token could not be stored" in runner.log
    assert len(world.x.posts) == 1, "the fresh access token still posts the claimed post"
    assert [issue["title"] for issue in world.github.issues] == [TITLE]
    assert "changed under the run" in world.github.issues[0]["body"]
    assert world.d1.row("SELECT refused FROM social_token") == {
        "refused": seal.fingerprint(fakes.SEED, fakes.CLIENT_SECRET)
    }
    runner.clock.at += timedelta(hours=1)
    assert runner() == 0
    assert "posting is stopped until a new X_REFRESH_TOKEN is pasted" in runner.log
    assert world.x.refreshes == 1


def test_a_seal_written_back_at_another_version_stops_the_chain(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002"), queued("0003")])
    assert runner() == 0
    first = world.d1.row("SELECT sealed FROM social_token")
    assert first is not None
    runner.clock.at += timedelta(hours=1)
    assert runner() == 0
    world.d1.db.execute("UPDATE social_token SET sealed = ?", (first["sealed"],))  # replayed
    world.d1.db.commit()
    runner.clock.at += timedelta(days=1)
    assert runner() == 1
    assert "did not open" in runner.log
    assert world.x.refreshes == 2, "the replayed (spent) token is never sent"
    assert world.github.issues[0]["state"] == "open"


def test_a_late_refresh_is_never_started(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])

    class Late(Clock):  # each reading of the clock is 4 minutes on (slow D1 and Haiku calls)
        def __call__(self) -> Any:
            self.at += timedelta(minutes=4)
            return self.at

    runner.clock = Late(at("2026-10-26T16:37:00"))
    assert runner() == 1
    assert "too late to refresh the token before the step's timeout" in runner.log
    assert world.x.refreshes == 0
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts") == {"n": 0}, "claim dropped"


def test_a_lease_taken_late_runs_from_when_it_is_taken(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    taken: list[str] = []

    class Ticking(Clock):
        def __call__(self) -> Any:
            self.at += timedelta(seconds=20)
            return self.at

    runner.clock = Ticking(at("2026-10-26T16:37:00"))

    def record() -> None:
        row = world.d1.row("SELECT lease_until FROM social_token")
        taken.append(str(row["lease_until"]) if row else "")

    world.d1.hooks = [("UPDATE social_token SET version", record)]
    assert runner() == 0
    start = at("2026-10-26T16:37:00")
    (until,) = taken
    lease_until = at(until.removesuffix("Z"))
    assert lease_until - start > timedelta(minutes=10, seconds=20), "timed from the take"


def test_a_failed_lease_release_still_opens_the_issue_and_drops_the_claim(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    assert runner() == 0
    world.x.valid.clear()
    world.d1.fail_next = ["UPDATE social_token SET lease = NULL"] * 2
    runner.clock.at += timedelta(hours=1)
    assert runner() == 1
    assert "lease was not given back" in runner.log
    assert [issue["title"] for issue in world.github.issues] == [TITLE]
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts") == {"n": 1}, "claim dropped"


def test_a_failure_mid_send_drops_the_claim(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])

    def the_image_goes_missing() -> None:
        (tmp_path / "social" / "queue" / "0001.png").unlink()

    world.d1.hooks = [("INSERT INTO social_posts", the_image_goes_missing)]
    assert runner() == 1
    assert "the post stopped (FileNotFoundError" in runner.log
    assert world.x.posts == []
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts") == {"n": 0}


def test_a_post_whose_record_failed_says_its_id(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.d1.fail_next = ["UPDATE social_posts SET state = 'posted'"] * 6
    assert runner() == 1
    assert len(world.x.posts) == 1
    assert "queue:0001 is posted as 1850000000000000002, but its record stays claimed" in (
        runner.log
    )


def test_a_posted_record_is_asked_again(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.d1.fail_next = ["UPDATE social_posts SET state = 'posted'"] * 2
    assert runner() == 0
    assert world.d1.row("SELECT state FROM social_posts") == {"state": "posted"}


# -- X refusing a post for good holds posting until the owner acts -----------------------------


@pytest.mark.parametrize(("where", "status"), [("post", 402), ("post", 403), ("upload", 403)])
def test_a_post_x_refuses_for_good_holds_posting_until_the_issue_is_closed(
    tmp_path: Path, world: World, where: str, status: int
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    setattr(world.x, f"{where}_status", status)
    assert runner() == 1
    assert [issue["title"] for issue in world.github.issues] == [REFUSED_TITLE]
    body = world.github.issues[0]["body"]
    assert f"HTTP {status}" in body
    assert "It is not retried." in body
    refreshes = world.x.refreshes
    for _ in range(3):
        runner.clock.at += timedelta(hours=1)
        assert runner() == 0
        assert "posting is stopped since X refused a post" in runner.log
    assert world.x.refreshes == refreshes, "no refresh while posting is held"
    assert world.x.posts == []
    setattr(world.x, f"{where}_status", 201 if where == "post" else 200)
    world.github.issues[0]["state"] = "closed"  # the owner fixed it and closed the issue
    runner.clock.at += timedelta(hours=1)
    assert runner() == 0
    assert "the owner closed issue #1 about X's refusal: trying again" in runner.log
    assert len(world.x.posts) == 1
    assert world.d1.row("SELECT held, held_issue FROM social_token") == {
        "held": None,
        "held_issue": None,
    }


def test_a_new_secret_lifts_a_hold_and_a_post_closes_the_issue(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.x.post_status = 402
    assert runner() == 1
    world.x.post_status = 201
    new_seed = fakes.token("Rn")
    world.x.valid.add(new_seed)
    runner.clock.at += timedelta(hours=1)
    assert runner(X_REFRESH_TOKEN=new_seed) == 0
    assert "X_REFRESH_TOKEN is new since X refused a post" in runner.log
    assert len(world.x.posts) == 1
    assert world.github.issues[0]["state"] == "closed"
    assert world.github.comments[-1][1] == "X took a post again; posting continues."


# -- the first post waits for its fresh card ------------------------------------------------------


def test_a_fresh_only_post_waits_for_a_fresh_card_and_holds_the_queue(
    tmp_path: Path, world: World
) -> None:
    first = unpictured("0001", FIRST, pictures=["national", "region"])
    first["fresh_only"] = True
    runner = make(tmp_path, world, queue=[first, queued("0002")])
    runner.haiku = FakeAnthropic([])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 1
    assert "queued post 0001 waits for a fresh card" in runner.log
    assert world.x.refreshes == 0
    assert runner.haiku.requests == []
    runner.picture = make_picture(tmp_path, runner.clock.at, kind="closings")
    assert runner() == 1, "a fresh card of a kind its text does not fit"
    assert world.x.posts == []
    runner.picture = make_picture(tmp_path, runner.clock.at)
    assert runner() == 0
    assert world.x.posts[0]["text"] == FIRST
    assert "fresh" in world.d1.row("SELECT image FROM social_posts")["image"]  # type: ignore[index]


def test_a_fresh_only_post_never_names_its_own_image(tmp_path: Path, world: World) -> None:
    item = queued("0001")
    item["fresh_only"] = True
    runner = make(tmp_path, world, queue=[item])
    assert runner() == 1
    assert "social/queue/0001.json is malformed" in runner.log


# -- closings stay off the posts' pictures until the facts file marks them LIVE ---------------

CLOSINGS_SHOWS = (
    "SYNTHETIC: a picture of the Snowlight map zoomed to the area with the most schools lit up"
    " for weather: 7 schools glow in this view (5 closed, 2 delayed), mostly in New York."
)


def test_a_fresh_closings_picture_is_not_used_while_closings_are_not_live(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[unpictured("0001", FIRST)])
    runner.picture = make_picture(tmp_path, runner.clock.at, kind="closings", shows=CLOSINGS_SHOWS)
    assert runner() == 0
    assert "the fresh picture shows closings while they are not LIVE" in runner.log
    assert b"FRESH-PICTURE" not in world.x.uploaded[0], "the library card went instead"
    assert "lit up" not in runner.log.split("social: picture:")[-1]


def test_a_fresh_card_whose_alt_text_shows_closings_is_not_used(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[unpictured("0001", FIRST)])
    folder = make_picture(tmp_path, runner.clock.at)
    note = folder / "dev-log.json"
    card = json.loads(note.read_text())
    card["alt"] = "SYNTHETIC alt text: the map with 7 schools closed in this view"
    note.write_text(json.dumps(card))
    runner.picture = folder
    assert runner() == 0
    assert "the dev-log card's alt text shows closings" in runner.log
    assert b"FRESH-PICTURE" not in world.x.uploaded[0]


def test_with_closings_live_a_closings_picture_goes_out(tmp_path: Path, world: World) -> None:
    facts = fakes.FACTS.replace("- [COMING] closings:", "- [LIVE] closings:")
    runner = Runner(
        make_root(tmp_path, queue=[unpictured("0001", FIRST)], facts=facts),
        world,
        Clock(at("2026-10-26T16:37:00")),
    )
    runner.picture = make_picture(tmp_path, at("2026-10-26T16:35:00"), kind="closings")
    assert runner() == 0
    assert b"FRESH-PICTURE" in world.x.uploaded[0]


def test_a_library_card_that_shows_closings_stops_the_run_while_they_are_not_live(
    tmp_path: Path, world: World
) -> None:
    root = make_root(tmp_path, queue=[unpictured("0001", FIRST)])
    note = root / "social" / "images" / "img-1.json"
    entry = json.loads(note.read_text())
    entry["shows"] += ". 40 schools are lit up for weather."
    note.write_text(json.dumps(entry))
    with pytest.raises(ContentError, match="shows closings while closings are not LIVE"):
        load(root)
    runner = Runner(root, world, Clock(at("2026-10-26T16:37:00")))
    assert runner() == 1
    assert world.x.posts == []
    assert world.x.refreshes == 0


# -- round 2: stops and holds that outlast a failed record, refusals that end, lost answers ----


def test_a_stop_the_database_could_not_record_still_stops_the_next_runs(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002"), queued("0003")])
    assert runner() == 0
    world.x.valid.clear()  # X now refuses the stored token
    world.d1.fail_next = ["UPDATE social_token SET refused"] * 2
    runner.clock.at += timedelta(hours=1)
    assert runner() == 1, "a stop that was not recorded ends the run red"
    assert "the stopped chain could not be recorded" in runner.log
    assert world.d1.row("SELECT refused FROM social_token") == {"refused": None}
    (issue,) = world.github.issues
    mark = seal.fingerprint(fakes.SEED, fakes.CLIENT_SECRET)[:12]
    assert (
        f"<!-- snowlight-social: the token chain stopped at version 1 seed {mark} -->"
        in (issue["body"])
    )
    refreshes = world.x.refreshes
    for event in ("push", "schedule"):
        runner.clock.at += timedelta(hours=1)
        assert runner(event) == 0
        assert "posting is stopped until a new X_REFRESH_TOKEN is pasted" in runner.log
    assert world.x.refreshes == refreshes, "the refused token is never sent to X again"
    # A new secret starts it again, and the issue closes.
    new_seed = fakes.token("Rn")
    world.x.valid.add(new_seed)
    runner.clock.at += timedelta(hours=1)
    assert runner(X_REFRESH_TOKEN=new_seed) == 0
    assert len(world.x.posts) == 2
    assert world.github.issues[0]["state"] == "closed"


def test_an_open_token_issue_left_from_a_chain_that_works_again_stops_nothing(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    assert runner() == 0
    # An open bot issue marked at an older version (its close failed when the chain worked).
    world.github.issues.append(
        {
            "number": 1,
            "state": "open",
            "user": fakes.BOT_USER,
            "title": TITLE,
            "body": "X refused it.\n\n"
            "<!-- snowlight-social: the token chain stopped at version 0 -->",
        }
    )
    runner.clock.at += timedelta(hours=1)
    assert runner() == 0
    assert len(world.x.posts) == 2


def test_a_stranger_s_issue_with_the_mark_stops_nothing(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    assert runner() == 0
    world.github.issues.append(
        {
            "number": 1,
            "state": "open",
            "user": fakes.STRANGER,
            "title": TITLE,
            "body": "<!-- snowlight-social: the token chain stopped at version 1 -->",
        }
    )
    runner.clock.at += timedelta(hours=1)
    assert runner() == 0
    assert len(world.x.posts) == 2


def _issues_api_down(world: World) -> None:
    working = world.github.handle

    def broken(request: httpx.Request) -> httpx.Response:
        if request.method in ("POST", "PATCH"):
            return httpx.Response(500, json={})
        return working(request)

    world.github.handle = broken  # type: ignore[method-assign]
    world.restore_github = working  # type: ignore[attr-defined]


def test_a_hold_whose_issue_could_not_be_opened_holds_until_its_issue_is_opened_and_closed(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    working = world.github.handle
    _issues_api_down(world)
    world.x.post_status = 402
    assert runner() == 1
    assert world.github.issues == []
    assert world.d1.row("SELECT held_issue FROM social_token") == {"held_issue": None}
    refreshes, uploads = world.x.refreshes, world.x.uploads
    for _ in range(3):
        runner.clock.at += timedelta(hours=1)
        assert runner() == 1, "red while the owner has no issue"
        assert "the owner's issue was not opened then: opening it now" in runner.log
        assert "the owner closed" not in runner.log
    assert (world.x.refreshes, world.x.uploads) == (refreshes, uploads), "nothing sent"
    world.github.handle = working  # type: ignore[method-assign]
    runner.clock.at += timedelta(hours=1)
    assert runner() == 1
    assert [issue["title"] for issue in world.github.issues] == [REFUSED_TITLE]
    assert "HTTP 402" in world.github.issues[0]["body"]
    assert world.d1.row("SELECT held_issue FROM social_token") == {"held_issue": 1}
    runner.clock.at += timedelta(hours=1)
    assert runner() == 0
    assert "issue #1 says what to do" in runner.log
    world.x.post_status = 201
    world.github.issues[0]["state"] = "closed"
    runner.clock.at += timedelta(hours=1)
    assert runner() == 0
    assert "the owner closed issue #1 about X's refusal: trying again" in runner.log
    assert len(world.x.posts) == 1


def test_a_post_x_refuses_twice_with_a_400_is_skipped_and_the_rest_go_on(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    world.x.upload_status = 400
    assert runner() == 1
    assert "one more such refusal skips it" in runner.log
    assert world.github.issues == []
    runner.clock.at += timedelta(hours=4)
    assert runner() == 1
    assert "X refused queue:0001 2 times in a row (HTTP 400): it is skipped for good" in (
        runner.log
    )
    assert [issue["title"] for issue in world.github.issues] == ["X posting: a post was skipped"]
    assert world.d1.row("SELECT state FROM social_posts WHERE slot = 'queue:0001'") == {
        "state": "skipped"
    }
    world.x.upload_status = 200
    uploads = world.x.uploads
    runner.clock.at += timedelta(minutes=10)
    assert runner() == 0, "the skipped post never goes again, and counts toward no cap"
    assert world.x.uploads == uploads + 1
    assert [post["text"] for post in world.x.posts] == [queued("0002")["text"]]
    assert world.d1.row("SELECT slot FROM social_posts WHERE state = 'posted'") == {
        "slot": "queue:0002"
    }


@pytest.mark.parametrize("status", [429, 500])
def test_a_rate_limit_or_a_server_error_is_never_counted_toward_a_skip(
    tmp_path: Path, world: World, status: int
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.x.upload_status = status
    for _ in range(3):
        assert runner() == 1
        runner.clock.at += timedelta(hours=4)
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts") == {"n": 0}
    world.x.upload_status = 200
    assert runner() == 0
    assert len(world.x.posts) == 1


def test_a_refusal_after_a_refresh_whose_answer_was_lost_says_so_in_the_issue(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002"), queued("0003")])
    assert runner() == 0
    world.x.refresh_status = 503
    runner.clock.at += timedelta(hours=1)
    assert runner() == 1
    assert world.d1.row("SELECT lease FROM social_token") == {"lease": None}
    assert world.d1.row("SELECT unknown FROM social_token")["unknown"] is not None  # type: ignore[index]
    world.x.refresh_status = 200
    world.x.valid.clear()  # X had taken that refresh: the stored token is spent
    runner.clock.at += timedelta(hours=1)
    assert runner() == 1
    (issue,) = world.github.issues
    assert "got no answer, so X most likely took that refresh and spent the token" in issue["body"]


def test_the_cloudflare_token_only_ever_goes_to_cloudflare(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    # A setting naming another host is ignored: the World refuses any host it does not know.
    assert runner(CLOUDFLARE_API_URL="https://elsewhere.test/client/v4") == 0
    assert len(world.x.posts) == 1
    from snowlight.social.store import API, CloudflareSecrets  # noqa: PLC0415

    secrets = CloudflareSecrets.from_env(
        {
            "CLOUDFLARE_API_TOKEN": "t",
            "CLOUDFLARE_ACCOUNT_ID": "a",
            "CLOUDFLARE_API_URL": "https://elsewhere.test",
        }
    )
    assert secrets is not None
    assert secrets.api == API == "https://api.cloudflare.com/client/v4"


# -- round 3: a refused new secret whose stop was not recorded, a lost refusal count, GitHub
# pages that are not JSON, and a refresh X did not take ---------------------------------------


def test_a_refused_new_secret_whose_stop_was_not_recorded_is_sent_to_x_once(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002"), queued("0003")])
    assert runner() == 0  # the chain is at version 1 from SEED
    bad = fakes.token("Bd")  # the owner pastes a token X refuses too
    world.d1.fail_next = ["UPDATE social_token SET refused"] * 50
    before = world.x.refreshes
    codes = []
    for _ in range(3):
        runner.clock.at += timedelta(hours=1)
        codes.append(runner(X_REFRESH_TOKEN=bad))
    assert codes == [1, 0, 0]
    assert world.x.refreshes - before == 1, "the refused new secret is sent to X once"
    (issue,) = world.github.issues
    mark = seal.fingerprint(bad, fakes.CLIENT_SECRET)[:12]
    assert f"stopped at version 1 seed {mark} -->" in issue["body"]
    assert seal.fingerprint(bad, fakes.CLIENT_SECRET) not in issue["body"]
    assert world.d1.row("SELECT version, refused FROM social_token") == {
        "version": 1,
        "refused": None,
    }
    # Another new secret is not the marked one: it is tried.
    good = fakes.token("Gd")
    world.x.valid.add(good)
    runner.clock.at += timedelta(hours=1)
    assert runner(X_REFRESH_TOKEN=good) == 0
    assert len(world.x.posts) == 2
    assert world.github.issues[0]["state"] == "closed"


def test_a_refused_new_secret_whose_stop_was_not_recorded_asks_haiku_no_more(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")], when="2026-10-25T10:00:00")
    assert runner() == 0
    bad = fakes.token("Bd")
    world.d1.fail_next = ["UPDATE social_token SET refused"] * 50
    calls = 0
    before = world.x.refreshes
    for when, draft in (
        ("2026-10-26T16:37:00", GOOD_DRAFT),
        ("2026-10-27T16:37:00", GOOD_DEV_LOG),
        ("2026-10-28T16:37:00", GOOD_DRAFT),
    ):
        runner.clock.at = at(when)
        runner.haiku = FakeAnthropic([dict(draft), dict(OK)])
        runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY, X_REFRESH_TOKEN=bad)
        calls += len(runner.haiku.requests)
    assert world.x.refreshes - before == 1
    assert calls == 2, "only the first day's try is spent before the stop"


def test_a_refusal_counted_twice_by_a_lost_answer_counts_once(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    world.x.upload_status = 400
    world.d1.fail_next = ["ran:INSERT INTO social_refusals"]
    assert runner() == 1
    assert world.d1.row("SELECT count FROM social_refusals") == {"count": 1}
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts WHERE state = 'skipped'") == {
        "n": 0
    }
    assert world.github.issues == []
    # A second refusal by another run is the second: the post is skipped then.
    runner.clock.at += timedelta(hours=4)
    assert runner() == 1
    assert world.d1.row("SELECT state FROM social_posts WHERE slot = 'queue:0001'") == {
        "state": "skipped"
    }


def test_a_github_page_that_is_not_json_is_one_warning_and_the_post_goes(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    working = world.github.handle

    def page(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=b"<html>oops</html>")
        return working(request)

    world.github.handle = page  # type: ignore[method-assign]
    assert runner() == 0
    assert len(world.x.posts) == 1
    assert "the token issue was not read (JSONDecodeError)" in runner.log
    assert "Traceback" not in runner.log


def test_a_github_page_that_is_not_json_never_breaks_a_held_or_stopped_run(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    world.x.post_status = 402  # X refuses the post for good: posting is held with an issue
    assert runner() == 1
    working = world.github.handle

    def page(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=b"<html>oops</html>")
        return working(request)

    world.github.handle = page  # type: ignore[method-assign]
    runner.clock.at += timedelta(hours=1)
    assert runner() == 0
    assert "posting is stopped since X refused a post" in runner.log
    world.x.valid.clear()
    world.x.post_status = 201
    runner.clock.at += timedelta(hours=1)
    runner(X_REFRESH_TOKEN=fakes.token("Nw"))
    assert "Traceback" not in runner.log


@pytest.mark.parametrize("status", [429, 403])
def test_a_refresh_x_did_not_take_records_no_lost_answer(
    tmp_path: Path, world: World, status: int
) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002"), queued("0003")])
    assert runner() == 0
    world.x.refresh_status = status
    runner.clock.at += timedelta(hours=1)
    assert runner() == 1
    assert world.d1.row("SELECT unknown, lease FROM social_token") == {
        "unknown": None,
        "lease": None,
    }
    world.x.refresh_status = 200
    world.x.valid.clear()
    runner.clock.at += timedelta(hours=1)
    assert runner() == 1
    (issue,) = world.github.issues
    assert "most likely took that refresh" not in issue["body"]


PAIR = (fakes.token("Oa"), fakes.token("Os"))


def _pair(**extra: str) -> dict[str, str]:
    return {"X_ACCESS_TOKEN": PAIR[0], "X_ACCESS_TOKEN_SECRET": PAIR[1], **extra}


def test_the_access_token_pair_is_exchanged_once_and_the_chain_goes_on_from_it(
    tmp_path: Path, world: World
) -> None:
    world.x.pair = PAIR
    world.x.scope = "tweet.read tweet.write users.read offline.access"  # the console's token
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002")])
    assert runner(**_pair()) == 0
    assert world.x.exchanges == 1
    assert world.x.refreshes == 0, "the exchanged pair is used, not X_REFRESH_TOKEN"
    assert "refreshed from the X_ACCESS_TOKEN pair, exchanged once" in runner.log
    assert len(world.x.posts) == 1
    row = world.d1.row("SELECT version, seed FROM social_token")
    start = f"oauth1\n{PAIR[0]}\n{PAIR[1]}"
    assert row == {"version": 1, "seed": seal.fingerprint(start, fakes.CLIENT_SECRET)}
    world.x.scope = world.x.exchange_scope  # a refresh keeps the exchanged token's scopes
    runner.clock.at += timedelta(hours=1)
    assert runner(**_pair()) == 0
    assert world.x.exchanges == 1, "the same pair is never exchanged again"
    assert world.x.refreshes == 1
    assert "from the stored token (version 1)" in runner.log
    assert len(world.x.posts) == 2


def test_the_pair_starts_a_chain_the_refresh_token_stopped_and_closes_the_issue(
    tmp_path: Path, world: World
) -> None:
    world.x.scope = "tweet.read tweet.write users.read offline.access"
    runner = make(tmp_path, world, queue=[queued("0001")])
    assert runner() == 1
    assert "lacks the scopes media.write" in runner.log
    assert [issue["state"] for issue in world.github.issues] == ["open"]
    runner.clock.at += timedelta(hours=1)
    assert runner() == 0
    assert "until a new X_REFRESH_TOKEN is pasted" in runner.log
    world.x.pair = PAIR
    runner.clock.at += timedelta(hours=1)
    assert runner(**_pair()) == 0
    assert world.x.exchanges == 1
    assert len(world.x.posts) == 1
    assert world.github.issues[0]["state"] == "closed"


def test_a_refused_pair_opens_the_issue_and_is_never_sent_again(
    tmp_path: Path, world: World
) -> None:
    world.x.pair = (fakes.token("Oa"), fakes.token("Os"))  # not the pair in the secrets
    runner = make(tmp_path, world, queue=[queued("0001")])
    assert runner(**_pair()) == 1
    assert "X refused the token exchange: HTTP 400 (invalid_grant)" in runner.log
    (issue,) = world.github.issues
    assert issue["title"] == TITLE
    assert "X_ACCESS_TOKEN" in issue["body"]
    assert world.x.posts == []
    runner.clock.at += timedelta(hours=1)
    assert runner(**_pair()) == 0
    assert "until a new X_ACCESS_TOKEN pair is pasted" in runner.log
    assert world.x.exchanges == 1, "the refused pair is never sent to X again"
    world.x.pair = PAIR
    runner.clock.at += timedelta(hours=1)
    assert runner(**_pair()) == 0, "the same secrets stay stopped even once X would take them"
    assert world.x.exchanges == 1
    fresh = (fakes.token("Ob"), fakes.token("Ot"))
    world.x.pair = fresh
    runner.clock.at += timedelta(hours=1)
    assert runner(X_ACCESS_TOKEN=fresh[0], X_ACCESS_TOKEN_SECRET=fresh[1]) == 0
    assert len(world.x.posts) == 1
    assert world.github.issues[0]["state"] == "closed"


def test_an_exchange_without_an_answer_posts_nothing_and_the_next_run_exchanges_again(
    tmp_path: Path, world: World
) -> None:
    world.x.pair = PAIR
    world.x.exchange_status = 503
    runner = make(tmp_path, world, queue=[queued("0001")])
    assert runner(**_pair()) == 1
    assert "the token exchange failed: HTTP 503" in runner.log
    assert world.github.issues == [], "no answer is no refusal: nothing for the owner to do"
    assert world.d1.row("SELECT COUNT(*) AS n FROM social_posts") == {"n": 0}, "claim dropped"
    world.x.exchange_status = 200
    runner.clock.at += timedelta(hours=1)
    assert runner(**_pair()) == 0
    assert world.x.exchanges == 2
    assert len(world.x.posts) == 1


def test_half_a_pair_leaves_the_chain_on_the_refresh_token(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    assert runner(X_ACCESS_TOKEN=PAIR[0]) == 0
    assert world.x.exchanges == 0
    assert "only one of X_ACCESS_TOKEN and X_ACCESS_TOKEN_SECRET is set" in runner.log
    assert "from the X_REFRESH_TOKEN secret" in runner.log
    assert runner(X_REFRESH_TOKEN="", X_ACCESS_TOKEN=PAIR[0]) == 0
    assert "nothing posts" in runner.log


def test_a_post_refused_under_the_pair_names_the_pair_and_a_new_pair_lifts_the_hold(
    tmp_path: Path, world: World
) -> None:
    world.x.pair = PAIR
    world.x.post_status = 401
    runner = make(tmp_path, world, queue=[queued("0001")])
    assert runner(**_pair()) == 1
    (issue,) = world.github.issues
    assert issue["title"] == REFUSED_TITLE
    assert "X_ACCESS_TOKEN_SECRET" in issue["body"]
    assert "X_REFRESH_TOKEN" not in issue["body"], (
        "a refresh token never lifts a hold under the pair"
    )
    world.x.post_status = 201
    runner.clock.at += timedelta(hours=1)
    assert runner(**_pair()) == 0
    assert world.x.posts == [], "held while the issue is open and the pair is the same"
    fresh = (fakes.token("Ob"), fakes.token("Ot"))
    world.x.pair = fresh
    runner.clock.at += timedelta(hours=1)
    assert runner(X_ACCESS_TOKEN=fresh[0], X_ACCESS_TOKEN_SECRET=fresh[1]) == 0
    assert "X_ACCESS_TOKEN pair is new since X refused a post" in runner.log
    assert len(world.x.posts) == 1
    assert world.x.exchanges == 2


def test_a_scheduled_run_with_nothing_to_post_checks_a_new_pair_and_closes_the_issue(
    tmp_path: Path, world: World
) -> None:
    world.x.scope = "tweet.read tweet.write users.read offline.access"
    runner = make(tmp_path, world, queue=[queued("0001")])
    assert runner() == 1
    assert "lacks the scopes media.write" in runner.log
    (tmp_path / "social" / "queue" / "0001.json").unlink()
    world.x.pair = PAIR
    runner.clock.at += timedelta(hours=1)
    assert runner("schedule", **_pair()) == 0
    assert "X_ACCESS_TOKEN pair is new since the chain stopped: checking it" in runner.log
    assert world.x.exchanges == 1
    assert world.github.issues[0]["state"] == "closed"
    runner.clock.at += timedelta(hours=1)
    assert runner("schedule", **_pair()) == 0
    assert world.x.exchanges == 1, "a working chain is never exchanged again"


def test_the_stored_chain_goes_on_from_one_exchange_across_runs(
    tmp_path: Path, world: World
) -> None:
    world.x.pair = PAIR
    runner = make(tmp_path, world, queue=[queued(f"000{n}") for n in range(1, 4)])
    for _ in range(3):
        assert runner(**_pair()) == 0
        runner.clock.at += timedelta(hours=8)
    assert world.x.exchanges == 1
    assert world.x.refreshes == 2
    assert len(world.x.posts) == 3

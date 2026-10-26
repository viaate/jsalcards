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
from snowlight.social.issue import TITLE
from snowlight.social.post import Deps, run
from snowlight.social.xapi import XClient
from social import fakes
from social.fakes import Clock, FakeAnthropic, World, at, make_root, queued

GOOD_DRAFT = {
    "text": "I keep the closings reader running 24/7 in practice mode."
    " Join the waitlist, link in my bio.",
    "image_id": "img-1",
    "kind": "waitlist",
    "facts_used": ["reader", "waitlist"],
}
GOOD_DEV_LOG = {
    **GOOD_DRAFT,
    "kind": "dev_log",
    "text": "Dev log: the closings reader runs 24/7 in practice mode.",
}
OK = {"ok": True, "problems": []}


class Runner:
    def __init__(self, root: Path, world: World, clock: Clock) -> None:
        self.root = root
        self.world = world
        self.clock = clock
        self.logs: list[str] = []
        self.masked: list[str] = []
        self.haiku: FakeAnthropic | None = None

    def __call__(self, event: str = "push", **extra: str) -> int:
        environment = fakes.env(GITHUB_ACTIONS="true", **extra)
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
        code = run(environment, self.root, event, deps)
        log = stream.getvalue()
        self.logs.append(log)
        self.check_log(log, environment, self.world.x.issued[before:])
        return code

    def check_log(self, log: str, environment: dict[str, str], issued: list[str]) -> None:
        shown = "\n".join(line for line in log.splitlines() if not line.startswith("::add-mask::"))
        for name in (
            "X_CLIENT_ID",
            "X_CLIENT_SECRET",
            "X_REFRESH_TOKEN",
            "CLOUDFLARE_API_TOKEN",
            "GITHUB_TOKEN",
        ):
            assert not environment[name] or environment[name] not in shown, name
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
    assert seal.unseal(row["sealed"], fakes.CLIENT_SECRET) == rotated
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


def test_the_day_never_holds_more_than_two_posts(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001"), queued("0002"), queued("0003")])
    for _ in range(3):
        runner()
        runner.clock.at += timedelta(minutes=30)
    assert len(world.x.posts) == 2
    assert "taken or the day's cap is reached" in runner.log
    runner.clock.at += timedelta(days=1)
    assert runner() == 0
    assert len(world.x.posts) == 3


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
    assert row["slot"] == "haiku:2026-10-27"
    assert row["style"] == "waitlist"
    runner.clock.at = at("2026-10-28T16:37:00")
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert "Set kind to dev_log." in runner.haiku.requests[0]["messages"][0]["content"]
    assert len(world.x.posts) == 3


def test_no_haiku_post_within_20_hours_of_the_last_post(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")], when="2026-10-26T01:00:00")
    assert runner() == 0
    runner.clock.at = at("2026-10-26T16:37:00")
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert "in the last 20 hours" in runner.log
    assert len(world.x.posts) == 1


def test_one_haiku_post_a_day_even_when_asked_again(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world)
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    world.d1.db.execute("UPDATE social_posts SET claimed_at = '2026-10-25T00:00:00Z'")
    world.d1.db.commit()
    runner.haiku = FakeAnthropic([])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert "Haiku already posted today" in runner.log
    assert len(world.x.posts) == 1


def test_two_failed_haiku_drafts_mean_no_post_today_within_four_calls(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world)
    bad = {**GOOD_DEV_LOG, "text": "Dev log: 99% sure the map is live now at snowlightmap.com"}
    runner.haiku = FakeAnthropic(
        [dict(bad), dict(GOOD_DEV_LOG), {"ok": False, "problems": ["claims something new"]}]
    )
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert len(runner.haiku.requests) == 3
    assert "no post today" in runner.log
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
    runner.clock.at += timedelta(hours=1)
    assert runner() == 1
    assert len(world.github.issues) == 1, "the open issue is updated, never a second one"
    assert world.x.refreshes == 3
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
    world.x.post_raises = None
    runner.clock.at += timedelta(days=1)
    assert runner() == 0
    assert world.x.posts == []


def test_a_post_x_refused_is_tried_again_by_a_later_run(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, queue=[queued("0001")])
    world.x.post_status = 403
    assert runner() == 1
    assert "X refused the post: HTTP 403 (Forbidden)" in runner.log
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
    assert runner() == 1
    assert "could not be stored" in runner.log
    assert world.x.posts == []
    assert [issue["title"] for issue in world.github.issues] == [TITLE]


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
    other = seal.seal("x", fakes.token("Zz"))
    world.d1.db.execute("UPDATE social_token SET sealed = ?", (other,))
    world.d1.db.commit()
    runner.clock.at += timedelta(hours=1)
    assert runner() == 1
    assert "did not open" in runner.log
    assert len(world.github.issues) == 1

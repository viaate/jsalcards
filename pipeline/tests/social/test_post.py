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
from snowlight.social.issue import REFUSED_TITLE, TITLE
from snowlight.social.post import Deps, run
from snowlight.social.store import TABLES
from snowlight.social.xapi import XClient
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
    world.x.post_raises = None
    runner.clock.at += timedelta(days=1)
    assert runner() == 0
    assert world.x.posts == []


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
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert world.x.posts == []
    assert "Haiku stopped early (max_tokens)" in runner.log
    assert "social: Haiku calls this run: 2" in runner.log


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


# -- one Haiku try a day -------------------------------------------------------------------


BAD_DRAFT = {**GOOD_DEV_LOG, "text": "Dev log: 99% sure the map is live now at snowlightmap.com"}


def test_a_failed_haiku_day_is_not_tried_again_by_the_second_slot(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, when="2026-10-27T16:37:00")
    runner.haiku = FakeAnthropic([dict(BAD_DRAFT), dict(BAD_DRAFT)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert "no Haiku draft passed: no post today" in runner.log
    assert world.d1.row("SELECT day, state FROM social_haiku_days") == {
        "day": "2026-10-27",
        "state": "failed",
    }
    runner.clock.at = at("2026-10-27T20:41:00")
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert runner.haiku.requests == [], "no second try that day"
    assert "already asked to write for 2026-10-27 (failed)" in runner.log
    assert world.x.posts == []
    assert world.x.refreshes == 0
    runner.clock.at = at("2026-10-28T16:37:00")
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert len(runner.haiku.requests) == 2, "the next day writes again"
    assert len(world.x.posts) == 1


def test_the_second_slot_writes_when_the_first_never_ran(tmp_path: Path, world: World) -> None:
    runner = make(tmp_path, world, when="2026-10-27T20:41:00")
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert len(world.x.posts) == 1
    assert world.d1.row("SELECT state FROM social_haiku_days") == {"state": "drafted"}


def test_a_haiku_post_x_did_not_take_is_not_written_again_that_day(
    tmp_path: Path, world: World
) -> None:
    runner = make(tmp_path, world, when="2026-10-27T16:37:00")
    world.x.refresh_status = 503
    runner.haiku = FakeAnthropic([dict(GOOD_DEV_LOG), dict(OK)])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 1
    world.x.refresh_status = 200
    runner.clock.at = at("2026-10-27T20:41:00")
    runner.haiku = FakeAnthropic([])
    assert runner("schedule", ANTHROPIC_API_KEY=fakes.ANTHROPIC_KEY) == 0
    assert runner.haiku.requests == []
    assert world.x.posts == []


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
    assert "the owner closed the issue about X's refusal: trying again" in runner.log
    assert len(world.x.posts) == 1
    assert world.d1.row("SELECT held FROM social_token") == {"held": None}


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

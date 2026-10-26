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
from snowlight.social.content import load
from snowlight.social.issue import TITLE
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
    other = seal.seal("x", fakes.token("Zz"))
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
    assert mine["body"].startswith("X refused the refresh token the posting workflow uses")
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

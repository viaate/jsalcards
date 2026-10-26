"""One run of ``snowlight social post``: at most one post (docs/social.md, "A run").

1. Read ``social/`` (facts, image library, queue). A malformed file stops the run red.
2. Without the X secrets, or the Cloudflare ones, say what is missing and stop (green).
3. Pick the post: the oldest queued post not posted yet that passes the checks; else, on the
   daily scheduled run only, with ``ANTHROPIC_API_KEY`` set, nothing posted in the last
   :data:`QUIET` and no Haiku post today, one post Haiku writes (styles alternate).
4. Claim its slot in D1 (the claim also holds the day's cap), take the token chain, refresh,
   store the rotated token, upload the image and post. Every failure after the claim drops
   the claim, except a post X may have made (``uncertain``: never sent again).

Caps (all in code): one post a run; :data:`snowlight.social.store.MAX_POSTS_PER_DAY` a UTC
day; one Haiku post a UTC day (its slot is the day); four Haiku calls a run, each at most
1,024 tokens (:mod:`snowlight.social.writer`).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

import anthropic
import httpx

from snowlight.social import seal
from snowlight.social.content import Content, ContentError, Image, load
from snowlight.social.issue import GitHub
from snowlight.social.rules import Style, check
from snowlight.social.store import (
    D1,
    MAX_POSTS_PER_DAY,
    ChainBusyError,
    CloudflareSecrets,
    MissingDatabaseError,
    Store,
    StoreError,
)
from snowlight.social.writer import Writer, draft
from snowlight.social.xapi import (
    NEEDED_SCOPES,
    RefreshRefusedError,
    RefreshUnknownError,
    RefusedError,
    Tokens,
    UnknownOutcomeError,
    XClient,
)

QUIET: Final = timedelta(hours=20)
"""Haiku writes only when nothing was posted for this long."""
ACCOUNT: Final = "SnowlightMap"
MAX_COMMITS: Final = 30

type Env = Mapping[str, str]


@dataclass(frozen=True, slots=True)
class XSecrets:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    refresh_seed: str = field(repr=False)

    @classmethod
    def from_env(cls, env: Env) -> "XSecrets | None":
        names = ("X_CLIENT_ID", "X_CLIENT_SECRET", "X_REFRESH_TOKEN")
        values = [env.get(name, "") for name in names]
        if not all(values):
            return None
        return cls(*values)


@dataclass(frozen=True, slots=True)
class Pick:
    slot: str
    kind: str
    style: Style
    text: str
    image: Image


def _anthropic() -> anthropic.Anthropic:  # pragma: no cover - the real client
    return anthropic.Anthropic(max_retries=0, timeout=60.0)


@dataclass(slots=True)
class Deps:
    http: httpx.Client
    x: XClient
    say: Callable[[str], None]
    mask: Callable[[str], None]
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    commits: Callable[[datetime | None], Sequence[str]] = lambda _since: ()
    anthropic: Callable[[], anthropic.Anthropic] = _anthropic
    db_pause: float = 3.0


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _queued(
    content: Content, taken: set[str], today: date, say: Callable[[str], None]
) -> tuple[Pick | None, bool]:
    """The oldest queued post that may go, and whether one was refused by the checks."""
    refused = False
    for item in content.queue:
        if item.slot in taken:
            continue
        problems = check(
            item.text,
            style=item.style,
            facts=content.facts,
            image_description=item.image.describe(),
            image_is_today=item.image.day == today,
        )
        if problems:
            refused = True
            say(f"::error::social: queued post {item.id} is refused: " + "; ".join(problems))
            continue
        return Pick(item.slot, "queue", item.style, item.text, item.image), refused
    return None, refused


@dataclass(slots=True)
class Run:
    """One run's state once the store is reached."""

    env: Env
    deps: Deps
    content: Content
    store: Store
    secrets: XSecrets
    github: GitHub | None
    run_id: str
    now: datetime

    def say(self, line: str) -> None:
        self.deps.say(line)

    def haiku(self, event: str, taken: set[str]) -> Pick | None:  # noqa: PLR0911 - one reason a return
        """The day's Haiku post, when every condition for one holds."""
        today = self.now.date()
        if event != "schedule":
            self.say("social: nothing queued; Haiku writes only on the daily scheduled run")
            return None
        if not self.env.get("ANTHROPIC_API_KEY"):
            self.say("social: nothing queued, and no Anthropic key (ANTHROPIC_API_KEY): no post")
            return None
        slot = f"haiku:{today.isoformat()}"
        if slot in taken:
            self.say("social: Haiku already posted today")
            return None
        last = self.store.last_post()
        claimed = _when(last.get("claimed_at")) if last is not None else None
        if claimed is not None and self.now - claimed < QUIET:
            self.say("social: something was posted in the last 20 hours: no Haiku post")
            return None
        if not self.content.images:
            self.say("::warning::social: the image library is empty: no Haiku post")
            return None
        style: Style = (
            "waitlist" if last is not None and last.get("style") == "dev_log" else "dev_log"
        )
        since = (_when(last.get("posted_at")) or claimed) if last is not None else None
        writer = Writer(self.deps.anthropic())
        commits = list(self.deps.commits(since))[:MAX_COMMITS]
        written = draft(
            writer, self.content, style=style, today=today, commits=commits, say=self.say
        )
        self.say(f"social: Haiku calls this run: {writer.calls}")
        if written is None:
            self.say("::warning::social: both Haiku drafts failed a check: no post today")
            return None
        return Pick(slot, "haiku", style, written.text, written.image)

    def issue(self, why: str) -> None:
        if self.github is None:
            self.say("::warning::social: no GITHUB_TOKEN: the owner's issue is not opened")
            return
        try:
            number = self.github.report(self.deps.http, why, self.now)
        except httpx.HTTPError as error:
            self.say(
                f"::warning::social: the owner's issue was not opened ({type(error).__name__})"
            )
            return
        self.say(f"social: issue #{number} tells the owner how to paste a new refresh token")

    def drop(self, pick: Pick) -> None:
        try:
            self.store.release(pick.slot, self.run_id)
        except StoreError:
            self.say(f"::warning::social: the claim on {pick.slot} could not be dropped")

    def refresh(self) -> Tokens | None:
        """The tokens, with the rotated refresh token stored; ``None`` when that failed (the
        reason said, and the owner's issue opened when they must act)."""
        try:
            chain = self.store.take_chain(self.run_id, self.now)
        except (ChainBusyError, StoreError) as error:
            self.say(f"::warning::social: the token chain is not free ({error}): nothing posts")
            return None
        seed = seal.fingerprint(self.secrets.refresh_seed, self.secrets.client_secret)
        if chain.version == 0 or not chain.sealed or chain.seed != seed:
            token, source = self.secrets.refresh_seed, "the X_REFRESH_TOKEN secret"
        else:
            try:
                token = seal.unseal(chain.sealed, self.secrets.client_secret)
            except seal.SealError as error:
                self.say(f"::error::social: {error}")
                self.store.release_chain(self.run_id)
                self.issue("the stored token did not open")
                return None
            self.deps.mask(token)
            source = f"the stored token (version {chain.version})"
        try:
            tokens = self.deps.x.refresh(self.secrets.client_id, self.secrets.client_secret, token)
        except RefreshRefusedError as error:
            self.say(f"::error::social: {error} (from {source})")
            self.store.release_chain(self.run_id)
            self.issue(str(error))
            return None
        except RefreshUnknownError as error:
            self.say(f"::error::social: {error}; the next run tries again")
            self.store.release_chain(self.run_id)
            return None
        sealed = seal.seal(tokens.refresh, self.secrets.client_secret)
        try:
            version = self.store.store_chain(chain, self.run_id, sealed, seed, self.deps.now())
        except StoreError as error:
            self.say(f"::error::social: the rotated token could not be stored ({error})")
            self.issue("the rotated token could not be stored")
            return None
        self.say(
            f"social: refreshed from {source}; the rotated token is stored sealed"
            f" (version {version})"
        )
        if self.github is not None:
            try:
                if (closed := self.github.resolve(self.deps.http)) is not None:
                    self.say(f"social: closed issue #{closed}")
            except httpx.HTTPError as error:
                self.say(f"::warning::social: the issue was not closed ({type(error).__name__})")
        return tokens

    def send(self, pick: Pick) -> int:
        """Refresh, upload and post a claimed pick; the exit code."""
        tokens = self.refresh()
        if tokens is None:
            self.drop(pick)
            return 1
        missing = sorted(NEEDED_SCOPES - tokens.scopes) if tokens.scopes else []
        if missing:
            self.say(
                f"::error::social: the X token lacks the scopes {', '.join(missing)}: nothing posts"
            )
            self.drop(pick)
            return 1
        x = self.deps.x
        try:
            image = pick.image
            media_id = x.upload_image(
                tokens.access, image.path.name, image.path.read_bytes(), image.content_type
            )
            post_id = x.post(tokens.access, pick.text, media_id)
        except RefusedError as error:
            self.say(f"::error::social: {error}: nothing was posted")
            self.drop(pick)
            return 1
        except UnknownOutcomeError as error:
            self.say(
                f"::error::social: {error}: it may be posted, so {pick.slot} is never sent"
                f" again (check @{ACCOUNT})"
            )
            try:
                self.store.uncertain(pick.slot, self.run_id)
            except StoreError:
                self.say(f"::warning::social: {pick.slot} stays claimed (never sent again)")
            return 1
        try:
            self.store.posted(pick.slot, self.run_id, post_id, self.deps.now())
        except StoreError:
            self.say(f"::warning::social: {pick.slot} is posted; its record stays claimed")
        self.say(
            f"social: posted {pick.slot} as {post_id}: https://x.com/{ACCOUNT}/status/{post_id}"
        )
        self.say(f"social: text: {pick.text}")
        return 0


def _start(env: Env, root: Path, deps: Deps) -> Run | int:
    """The run's state, or the exit code when it stops before the store."""
    say = deps.say
    try:
        content = load(root)
    except ContentError as error:
        say(f"::error::social: {error}")
        return 1
    secrets = XSecrets.from_env(env)
    if secrets is None:
        say("::notice::social: no X_CLIENT_ID, X_CLIENT_SECRET and X_REFRESH_TOKEN: nothing posts")
        return 0
    cloudflare = CloudflareSecrets.from_env(env)
    if cloudflare is None:
        say(
            "::warning::social: the job sees no CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID"
            " (repository secrets, or environment secrets of x-posting): the rotated token"
            " cannot be stored, so nothing posts (docs/social.md)"
        )
        return 0
    github = (
        GitHub(token=env["GITHUB_TOKEN"], repository=env["GITHUB_REPOSITORY"])
        if env.get("GITHUB_TOKEN") and env.get("GITHUB_REPOSITORY")
        else None
    )
    run_id = f"{env.get('GITHUB_RUN_ID', 'local')}.{env.get('GITHUB_RUN_ATTEMPT', '1')}"
    try:
        store = Store(D1.find(deps.http, cloudflare, pause=deps.db_pause))
        store.prepare()
    except MissingDatabaseError as error:
        say(f"::warning::social: {error}: nothing posts")
        return 1
    except StoreError as error:
        say(f"::warning::social: the D1 store failed ({error}): nothing posts")
        return 1
    return Run(env, deps, content, store, secrets, github, run_id, deps.now())


def run(env: Env, root: Path, event: str, deps: Deps) -> int:
    """One run; its exit code (1 when the owner or the lead should look)."""
    started = _start(env, root, deps)
    if isinstance(started, int):
        return started
    one = started
    try:
        taken = one.store.taken_slots()
        pick, refused = _queued(one.content, taken, one.now.date(), one.say)
        if pick is None and one.store.posts_on(one.now.date().isoformat()) >= MAX_POSTS_PER_DAY:
            one.say(f"social: the day's cap of {MAX_POSTS_PER_DAY} posts is reached")
        elif pick is None:
            pick = one.haiku(event, taken)
        if pick is not None and not one.store.claim(
            pick.slot,
            kind=pick.kind,
            style=pick.style,
            image=pick.image.id,
            run=one.run_id,
            now=one.now,
        ):
            one.say(f"social: {pick.slot} is taken or the day's cap is reached: nothing posts")
            pick = None
    except StoreError as error:
        one.say(f"::warning::social: the D1 store failed ({error}): nothing posts")
        return 1
    if pick is None:
        return 1 if refused else 0
    one.say(f"social: claimed {pick.slot} ({pick.style}, image {pick.image.id})")
    return one.send(pick) or (1 if refused else 0)

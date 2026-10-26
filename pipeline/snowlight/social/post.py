"""One run of ``snowlight social post``: at most one post (docs/social.md, "A run").

1. Read ``social/`` (facts, image library, queue). A malformed file stops the run red.
2. Without the X secrets, or the Cloudflare ones, say what is missing and stop (green).
3. Pick the post: the oldest queued post not posted yet that passes the checks; else, on the
   daily scheduled run only, with ``ANTHROPIC_API_KEY`` set, nothing posted in the last
   :data:`QUIET` and no Haiku post today, one post Haiku writes (styles alternate).
4. Claim its slot in D1 (the claim also holds the day's cap), take the token chain, refresh,
   store the rotated token, upload the image and post. Every failure after the claim drops
   the claim, except a post X may have made (``uncertain``: never sent again).
5. A scheduled run with nothing to post still refreshes once when the chain stopped and the
   ``X_REFRESH_TOKEN`` secret is not the one that stopped (the owner pasted a new one), so the
   new token is checked and the owner's issue closes without waiting for a post.

Caps (all in code): one post a run; :data:`snowlight.social.store.MAX_POSTS_PER_DAY` a UTC
day; one Haiku post a UTC day (its slot is the day); four Haiku calls a run, each at most
1,024 tokens (:mod:`snowlight.social.writer`).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import anthropic
import httpx
from pydantic import ValidationError

from snowlight.social import seal
from snowlight.social.cards import Card, Post
from snowlight.social.content import Content, ContentError, Image, check_image, load
from snowlight.social.issue import GitHub
from snowlight.social.picture import NOTE, Taken
from snowlight.social.rules import MENTION, URL, Style, chances_shown, check, mentions_chance
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

FRESH_FOR: Final = timedelta(minutes=40)
"""How old the render job's picture may be when the post step reads it (the render job's
Render step times out after 15 minutes, and the post job starts right after it)."""
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


def _anthropic() -> anthropic.Anthropic:
    """The real client: it retries nothing, so :data:`snowlight.social.writer.MAX_CALLS`
    counts every request."""
    return anthropic.Anthropic(max_retries=0, timeout=60.0)


@dataclass(slots=True)
class Deps:
    http: httpx.Client
    x: XClient
    say: Callable[[str], None]
    mask: Callable[[str], None]
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    commits: Callable[[datetime | None], Sequence[str]] = lambda _since: ()
    haiku_client: Callable[[], anthropic.Anthropic] = _anthropic
    db_pause: float = 3.0


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


CARD_OF: Final[Mapping[str, Post]] = {"dev_log": "dev-log", "waitlist": "waitlist"}
"""The card each post style goes out with."""

type Fresh = Mapping[str, Image]
"""The run's fresh cards by post style."""


def fresh_picture(
    folder: Path | None, now: datetime, say: Callable[[str], None], *, chances: bool
) -> Fresh:
    """The render job's fresh cards of this run by post style (handed over by
    :mod:`snowlight.social.relay`); none (the reason said) when there is no picture, or it is
    malformed, or it is not from the last :data:`FRESH_FOR`, or, without ``chances`` (the
    facts file's switch), it gives a chance. A style whose card failed, or whose alt text
    holds a link or a chance, is left out (that post goes with the library's card)."""
    if folder is None:
        return {}
    note = folder / NOTE
    if not note.is_file():
        say("::warning::social: the Render step left no fresh picture")
        return {}
    try:
        taken = Taken.model_validate_json(note.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        say("::warning::social: the fresh picture is malformed; it is not used")
        return {}
    age = now - taken.taken_at
    if not timedelta(minutes=-2) <= age <= FRESH_FOR:
        say("::warning::social: the fresh picture is not from this run; it is not used")
        return {}
    if not chances and (
        taken.kind == "district" or taken.seen.chance is not None or mentions_chance(taken.shows)
    ):
        say("::warning::social: the fresh picture gives a chance while chances are TESTING")
        return {}
    cards: dict[str, Image] = {}
    for style, post in CARD_OF.items():
        try:
            card = Card.model_validate_json((folder / f"{post}.json").read_text(encoding="utf-8"))
            check_image(folder / card.file)
        except (OSError, ValidationError, ContentError):
            say(f"::warning::social: no fresh {post} card; that post uses the library's card")
            continue
        if card.post != post or card.fallback:
            say(f"::warning::social: the {post} card is not this run's; it is not used")
            continue
        if URL.search(card.alt) or MENTION.search(card.alt):
            say(f"::warning::social: the {post} card's alt text holds a link; it is not used")
            continue
        if not chances and mentions_chance(card.alt):
            say(f"::warning::social: the {post} card's alt text gives a chance; it is not used")
            continue
        cards[style] = Image(
            id=f"fresh-{taken.taken_at.astimezone(UTC):%Y%m%dt%H%M}",
            path=folder / card.file,
            day=taken.taken_at.astimezone(UTC).date(),
            shows=taken.shows,
            fresh=taken.kind,
            current=taken.current,
            alt=card.alt,
            style=style,
        )
    return cards


def picture_for(  # noqa: PLR0913 - the post's parts
    content: Content,
    fresh: Fresh,
    style: str,
    kinds: tuple[str, ...] | None,
    own: Image | None,
    *,
    say: Callable[[str], None],
) -> Image | None:
    """A post's picture: the fresh card for its style when the picture's kind fits, else
    ``own``, else the library's newest card (stored cards keep their own day and
    description). An older picture is said in the log, by the one the post goes with."""
    image = fresh.get(style)
    if image is not None and (kinds is None or image.fresh in kinds):
        return image
    older = own or content.newest(style)
    if older is not None:
        why = "no fresh card fits it" if fresh.get(style) is not None else "no fresh card"
        say(
            f"::warning::social: {why}: the {style} post uses {older.id} from"
            f" {older.day.isoformat()}, as an older picture"
        )
    return older


def _queued(
    content: Content, taken: set[str], fresh: Fresh, say: Callable[[str], None]
) -> tuple[Pick | None, bool]:
    """The oldest queued post that may go, and whether one was refused by the checks."""
    refused = False
    for item in content.queue:
        if item.slot in taken:
            continue
        image = picture_for(content, fresh, item.style, item.pictures, item.image, say=say)
        problems = (
            ["it has no picture: no fresh one fits and the library is empty"]
            if image is None
            else check(
                item.text,
                style=item.style,
                facts=content.facts,
                image_description=image.describe(),
                image_is_today=image.current,
            )
        )
        if problems or image is None:
            refused = True
            say(f"::error::social: queued post {item.id} is refused: " + "; ".join(problems))
            continue
        return Pick(item.slot, "queue", item.style, item.text, image), refused
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
    fresh: Fresh = field(default_factory=dict)
    chain_lost: bool = False
    """The rotated token could not be stored (the run may still post, and ends red)."""

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
        style: Style = (
            "waitlist" if last is not None and last.get("style") == "dev_log" else "dev_log"
        )
        image = picture_for(self.content, self.fresh, style, None, None, say=self.say)
        if image is None:
            self.say("::warning::social: no fresh picture and an empty library: no Haiku post")
            return None
        since = (_when(last.get("posted_at")) or claimed) if last is not None else None
        writer = Writer(self.deps.haiku_client())
        commits = list(self.deps.commits(since))[:MAX_COMMITS]
        # The picture is the only one Haiku sees, and its description the only facts about it.
        content = replace(self.content, images=(image,))
        written = draft(writer, content, style=style, today=today, commits=commits, say=self.say)
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

    @property
    def seed(self) -> str:
        """The fingerprint of the ``X_REFRESH_TOKEN`` secret (never the secret)."""
        return seal.fingerprint(self.secrets.refresh_seed, self.secrets.client_secret)

    def stopped(self, why: str) -> None:
        """The chain stopped: open the owner's issue, and record which secret it was."""
        self.issue(why)
        try:
            self.store.stopped(self.seed)
        except StoreError:
            self.say("::warning::social: the stopped chain could not be recorded")

    def refresh(self) -> Tokens | None:  # noqa: PLR0911 - one reason a return
        """The tokens, with the rotated refresh token stored; ``None`` when no token came
        (the reason said, and the owner's issue opened when they must act). When the rotated
        token could not be stored the tokens still come back (this run may post) and the
        issue is opened."""
        try:
            chain = self.store.take_chain(self.run_id, self.now)
        except (ChainBusyError, StoreError) as error:
            self.say(f"::warning::social: the token chain is not free ({error}): nothing posts")
            return None
        seed = self.seed
        if chain.version == 0 or not chain.sealed or chain.seed != seed:
            token, source = self.secrets.refresh_seed, "the X_REFRESH_TOKEN secret"
        else:
            try:
                token = seal.unseal(chain.sealed, self.secrets.client_secret)
            except seal.SealError as error:
                self.say(f"::error::social: {error}")
                self.store.release_chain(self.run_id)
                self.stopped(
                    "The refresh token stored for the posting workflow could not be opened"
                    " (it is sealed with X_CLIENT_SECRET; was that secret changed?)"
                )
                return None
            self.deps.mask(token)
            source = f"the stored token (version {chain.version})"
        try:
            tokens = self.deps.x.refresh(self.secrets.client_id, self.secrets.client_secret, token)
        except RefreshRefusedError as error:
            self.say(f"::error::social: {error} (from {source})")
            self.store.release_chain(self.run_id)
            answer = str(error).removeprefix("X refused the refresh token: ")
            self.stopped(f"X refused the refresh token the posting workflow uses ({answer})")
            return None
        except RefreshUnknownError as error:
            self.say(f"::error::social: {error}; the next run tries again")
            self.store.release_chain(self.run_id)
            return None
        sealed = seal.seal(tokens.refresh, self.secrets.client_secret)
        try:
            version = self.store.store_chain(chain, self.run_id, sealed, seed, self.deps.now())
        except ChainBusyError as error:
            self.say(f"::warning::social: the rotated token was not stored ({error})")
            return tokens
        except StoreError as error:
            self.say(f"::error::social: the rotated token could not be stored ({error})")
            self.stopped(
                "X gave the posting workflow a new refresh token, but it could not be stored"
                " in the D1 database, so the next run has no token that works"
            )
            self.chain_lost = True
            return tokens
        self.say(
            f"social: refreshed from {source}; the rotated token is stored sealed"
            f" (version {version})"
        )
        return tokens

    def usable(self, tokens: Tokens) -> bool:
        """Whether the token has every scope a post needs: if not, the owner's issue says
        which are missing; if so, the chain works again and the issue is closed."""
        missing = sorted(NEEDED_SCOPES - tokens.scopes) if tokens.scopes else []
        if missing:
            names = ", ".join(missing)
            self.say(f"::error::social: the X token lacks the scopes {names}: nothing posts")
            self.stopped(f"The X token lacks the scopes {names}, which a post needs")
            return False
        if self.chain_lost:
            return True  # the token works for this run, but the chain stays stopped
        try:
            if self.store.refused_seed() is not None:
                self.store.working()
        except StoreError:
            self.say("::warning::social: the working chain could not be recorded")
        if self.github is not None:
            try:
                if (closed := self.github.resolve(self.deps.http)) is not None:
                    self.say(f"social: closed issue #{closed}")
            except httpx.HTTPError as error:
                self.say(f"::warning::social: the issue was not closed ({type(error).__name__})")
        return True

    def recover(self) -> int:
        """A scheduled run with nothing to post: refresh once when the chain stopped and the
        ``X_REFRESH_TOKEN`` secret is not the one that stopped; the exit code."""
        refused = self.store.refused_seed()
        if refused is None:
            return 0
        if refused == self.seed:
            self.say(
                "::warning::social: posting is stopped until a new X_REFRESH_TOKEN is pasted"
                " (the open issue says how)"
            )
            return 0
        self.say("social: X_REFRESH_TOKEN is new since the chain stopped: checking it")
        tokens = self.refresh()
        return 0 if tokens is not None and self.usable(tokens) else 1

    def send(self, pick: Pick) -> int:
        """Refresh, upload and post a claimed pick; the exit code."""
        tokens = self.refresh()
        if tokens is None or not self.usable(tokens):
            self.drop(pick)
            return 1
        x = self.deps.x
        try:
            image = pick.image
            media_id = x.upload_image(
                tokens.access, image.path.name, image.path.read_bytes(), image.content_type
            )
            if image.alt:
                try:
                    x.describe(tokens.access, media_id, image.alt)
                except RefusedError as error:
                    self.say(f"::warning::social: the alt text was not set ({error})")
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
        self.say(f"social: picture: {pick.image.describe()}")
        return 1 if self.chain_lost else 0


def _start(env: Env, root: Path, deps: Deps, picture: Path | None) -> Run | int:
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
    now = deps.now()
    fresh = fresh_picture(picture, now, say, chances=chances_shown(content.facts))
    return Run(env, deps, content, store, secrets, github, run_id, now, fresh)


def run(env: Env, root: Path, event: str, deps: Deps, picture: Path | None = None) -> int:
    """One run; its exit code (1 when the owner or the lead should look). ``picture`` is the
    Render step's folder (:mod:`snowlight.social.render`)."""
    started = _start(env, root, deps, picture)
    if isinstance(started, int):
        return started
    one = started
    try:
        for row in one.store.stale_claims(one.now):
            one.say(
                f"::warning::social: {row.get('slot')} was claimed by run {row.get('run')} at"
                f" {row.get('claimed_at')} and never finished: it may or may not be on"
                f" @{ACCOUNT}. It is never sent again by itself; check the account, then delete"
                " its social_posts row (docs/social.md)"
            )
        taken = one.store.taken_slots()
        pick, refused = _queued(one.content, taken, one.fresh, one.say)
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
        try:
            recovered = one.recover() if event == "schedule" else 0
        except StoreError as error:
            one.say(f"::warning::social: the D1 store failed ({error})")
            recovered = 1
        return 1 if refused else recovered
    one.say(f"social: claimed {pick.slot} ({pick.style}, image {pick.image.id})")
    return one.send(pick) or (1 if refused else 0)

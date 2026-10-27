"""The GitHub issues that say posting stopped and what the owner must do.

* :data:`TOKEN` ("X posting stopped: refresh token"): the token chain stopped; the owner
  pastes a new refresh token. Closed with a comment by the first run whose refresh works
  again with every scope a post needs.
* :data:`REFUSED` ("X posting stopped: X refused the post"): X refused a post or its image
  for good (no credits, no write permission, a duplicate). The owner fixes it and closes the
  issue (or pastes a new refresh token); the next run then tries once more. Closed with a
  comment by the next run that posts.
* :data:`SKIPPED` ("X posting: a post was skipped"): X refused one post twice with the same
  answer (an image or text X does not take): that post is skipped for good, and the others go
  on. The owner fixes or removes it and closes the issue.
* :data:`UNCERTAIN` ("X posting: check whether a post went out"): a post request went to X
  and its outcome is unknown (no answer, a 5xx, or a 2xx without the post's id): X may have
  made it, so it is never sent again by itself, and the others go on. The owner checks the
  account, records the post or deletes its row, and closes the issue.

The :data:`TOKEN` issue's body ends with a hidden line naming the stored chain's version when
the chain stopped and the first :data:`SEED_SHOWN` hex characters of the keyed fingerprint of
the secret that was refused (:data:`MARK`: a count and an HMAC under the client secret, nothing
that can be turned back into a token): while that issue is open, the chain is still at that
version and ``X_REFRESH_TOKEN`` is still that secret, every run stops, even when the database
could not record the stop (:meth:`GitHub.stopped_at`), whichever secret the stored chain
started from.

Each is opened (or, when already open, its body brought up to date) with the job's
``GITHUB_TOKEN`` (``issues: write``). Nothing in it comes from X but the HTTP status and
error code.

Only an issue the workflow itself opened counts (its author is :data:`BOT`): in a public
repository anyone can open an issue with the same title, and the owner's steps for the X
token must never go into, or close, an issue a stranger wrote and can edit.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

import httpx

API: Final = "https://api.github.com"
TITLE: Final = "X posting stopped: refresh token"
REFUSED_TITLE: Final = "X posting stopped: X refused the post"
SKIPPED_TITLE: Final = "X posting: a post was skipped"
UNCERTAIN_TITLE: Final = "X posting: check whether a post went out"
TIMEOUT: Final = httpx.Timeout(20.0, connect=10.0)
MARK: Final = "<!-- snowlight-social: the token chain stopped at version {version} seed {seed} -->"
MARKED: Final = re.compile(
    r"<!-- snowlight-social: the token chain stopped at version (\d+)(?: seed ([0-9a-f]{12}))? -->"
)
SEED_SHOWN: Final = 12
"""How many hex characters of the keyed fingerprint of the refused secret the mark holds: enough
to tell one pasted secret from another, nothing that can be turned back into it."""
BOT: Final = "github-actions[bot]"
"""The author of the workflow's own issues (the job's ``GITHUB_TOKEN``)."""

BODY: Final = """{why} ({when}), so nothing posts on @SnowlightMap until a new refresh token \
is in place. It is not retried.

To start it again:

1. Open the X developer console, the app of @SnowlightMap, **Keys and tokens**.
2. Under **OAuth 2.0**, generate a new access token and refresh token for @SnowlightMap \
(the scopes must include tweet.read, tweet.write, users.read, offline.access and \
media.write). If the client secret was regenerated too, also update `X_CLIENT_SECRET`.
3. On GitHub: Settings > Environments > **x-posting** > Environment secrets > \
`X_REFRESH_TOKEN` > edit, paste the new refresh token, save. Never paste it anywhere else.
4. Nothing else to do: the next scheduled run (daily, 16:37 and 20:41 UTC) sees that the \
secret is new and starts from it, even when it has nothing to post, and this issue closes \
itself once the new token works with every scope above.

docs/social.md has the details."""

REFUSED_BODY: Final = """{why} ({when}), so nothing posts on @SnowlightMap until this issue \
is closed. It is not retried.

What X's answer means, and what to do:

- **HTTP 402**: the X developer account has no credits left for posting. Add credits, or \
move to a plan that allows posting, in the X developer console.
- **HTTP 403**: the app may not post for @SnowlightMap, or X took the post for a duplicate. \
In the X developer console, the app's **User authentication settings** must give **Read and \
write** permission; after changing them, generate a new access token and refresh token and \
paste the refresh token into `X_REFRESH_TOKEN` (Settings > Environments > **x-posting**). If \
the post was a duplicate, delete its file from `social/queue`.
- **HTTP 401**: X refused the token for this call: generate a new token pair and paste the \
refresh token into `X_REFRESH_TOKEN`.

When it is fixed, close this issue (or paste a new `X_REFRESH_TOKEN`): the next run tries \
once more, and opens this issue again if X still refuses.

docs/social.md has the details."""

SKIPPED_BODY: Final = """{why} ({when}). That post is skipped from now on: no run sends it \
again, and the other posts go on.

X's answer (an HTTP 4xx such as 400 or 413) usually means it does not take that post's image \
or text: an image too large or of a kind it does not take, or text it will not post. To post \
it after all, fix the file and give it a new id (a new file name in `social/queue`), or \
delete it. Then close this issue.

docs/social.md has the details."""

UNCERTAIN_BODY: Final = """{why} ({when}). X may have made that post, so no run sends it \
again by itself; the other posts go on.

Check @SnowlightMap, then in the Cloudflare dashboard > D1 > `snowlight-live-state` > \
Console (every such post: `SELECT slot, claimed_at FROM social_posts WHERE state = \
'uncertain'`):

- **The post is on the account**: record it with the number at the end of its address \
(x.com/SnowlightMap/status/NUMBER): `UPDATE social_posts SET state = 'posted', post_id = \
'NUMBER' WHERE slot = 'SLOT'`, with SLOT the slot named above (such as `queue:0001`).
- **It is not there** and should go: `DELETE FROM social_posts WHERE slot = 'SLOT' AND state \
= 'uncertain'`; the next run posts it.

Then close this issue.

docs/social.md has the details."""


@dataclass(frozen=True, slots=True)
class Issue:
    title: str
    body: str
    closing: str
    """The comment the issue is closed with once posting works again."""


TOKEN: Final = Issue(TITLE, BODY, "The refresh token works again; posting continues.")
REFUSED: Final = Issue(REFUSED_TITLE, REFUSED_BODY, "X took a post again; posting continues.")
SKIPPED: Final = Issue(SKIPPED_TITLE, SKIPPED_BODY, "")
UNCERTAIN: Final = Issue(UNCERTAIN_TITLE, UNCERTAIN_BODY, "")


@dataclass(frozen=True, slots=True)
class GitHub:
    token: str = field(repr=False)
    repository: str
    api: str = API

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _open_item(self, client: httpx.Client, issue: Issue) -> dict[str, object] | None:
        response = client.get(
            f"{self.api}/repos/{self.repository}/issues",
            params={"state": "open", "creator": BOT, "per_page": 100},
            headers=self._headers(),
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        for item in response.json():
            if (
                isinstance(item, dict)
                and item.get("title") == issue.title
                and "pull_request" not in item
                and isinstance(item.get("number"), int)
                and _by_the_workflow(item)
            ):
                return item
        return None

    def _open_issue(self, client: httpx.Client, issue: Issue) -> int | None:
        item = self._open_item(client, issue)
        number = item.get("number") if item is not None else None
        return number if isinstance(number, int) else None

    def stopped_at(self, client: httpx.Client) -> tuple[int, str | None] | None:
        """The chain version the open :data:`TOKEN` issue says the chain stopped at, with the
        fingerprint prefix of the refused secret (``None`` in a mark written before it was
        kept), or ``None`` (no open issue of the workflow's own, or no such line in it).

        Raises:
            httpx.HTTPError: GitHub could not be reached or refused.
            ValueError: GitHub's answer was not JSON.
        """
        item = self._open_item(client, TOKEN)
        body = item.get("body") if item is not None else None
        found = MARKED.search(body) if isinstance(body, str) else None
        return (int(found.group(1)), found.group(2)) if found else None

    def is_closed(self, client: httpx.Client, number: int) -> bool:
        """Whether the workflow's own issue ``number`` is closed.

        Raises:
            httpx.HTTPError: GitHub could not be reached or refused.
            ValueError: GitHub's answer was not JSON.
        """
        response = client.get(
            f"{self.api}/repos/{self.repository}/issues/{number}",
            headers=self._headers(),
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        item = response.json()
        return isinstance(item, dict) and _by_the_workflow(item) and item.get("state") == "closed"

    def is_open(self, client: httpx.Client, issue: Issue = TOKEN) -> bool:
        """Whether the workflow's own ``issue`` is open.

        Raises:
            httpx.HTTPError: GitHub could not be reached or refused.
            ValueError: GitHub's answer was not JSON.
        """
        return self._open_issue(client, issue) is not None

    def report(  # noqa: PLR0913 - the issue, its words and its hidden mark
        self,
        client: httpx.Client,
        why: str,
        now: datetime,
        issue: Issue = TOKEN,
        *,
        version: int | None = None,
        seed: str = "",
    ) -> int:
        """Open the issue, or update the open one; its number. ``version`` (the chain's when
        it stopped) and the first :data:`SEED_SHOWN` characters of ``seed`` (the keyed
        fingerprint of the refused secret) go into the body as the hidden :data:`MARK` line.

        Raises:
            httpx.HTTPError: GitHub could not be reached or refused.
            ValueError: GitHub's answer was not JSON.
        """
        body = issue.body.format(why=why.rstrip("."), when=now.strftime("%Y-%m-%d %H:%M UTC"))
        if version is not None:
            body += "\n\n" + MARK.format(version=version, seed=seed[:SEED_SHOWN])
        number = self._open_issue(client, issue)
        if number is None:
            response = client.post(
                f"{self.api}/repos/{self.repository}/issues",
                json={"title": issue.title, "body": body},
                headers=self._headers(),
                timeout=TIMEOUT,
            )
        else:
            response = client.patch(
                f"{self.api}/repos/{self.repository}/issues/{number}",
                json={"body": body},
                headers=self._headers(),
                timeout=TIMEOUT,
            )
        response.raise_for_status()
        answer = response.json()
        made = answer.get("number") if isinstance(answer, dict) else None
        return made if isinstance(made, int) else (number or 0)

    def resolve(self, client: httpx.Client, issue: Issue = TOKEN) -> int | None:
        """Close the open ``issue``, if any, with a comment; its number.

        Raises:
            httpx.HTTPError: GitHub could not be reached or refused.
            ValueError: GitHub's answer was not JSON.
        """
        number = self._open_issue(client, issue)
        if number is None:
            return None
        client.post(
            f"{self.api}/repos/{self.repository}/issues/{number}/comments",
            json={"body": issue.closing},
            headers=self._headers(),
            timeout=TIMEOUT,
        ).raise_for_status()
        client.patch(
            f"{self.api}/repos/{self.repository}/issues/{number}",
            json={"state": "closed", "state_reason": "completed"},
            headers=self._headers(),
            timeout=TIMEOUT,
        ).raise_for_status()
        return number


def _by_the_workflow(item: dict[str, object]) -> bool:
    user = item.get("user")
    return isinstance(user, dict) and user.get("login") == BOT and user.get("type") == "Bot"

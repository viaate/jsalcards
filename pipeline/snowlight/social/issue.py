"""The GitHub issues that say posting stopped and what the owner must do.

* :data:`TOKEN` ("X posting stopped: refresh token"): the token chain stopped; the owner
  pastes a new refresh token. Closed with a comment by the first run whose refresh works
  again with every scope a post needs.
* :data:`REFUSED` ("X posting stopped: X refused the post"): X refused a post or its image
  for good (no credits, no write permission, a duplicate). The owner fixes it and closes the
  issue (or pastes a new refresh token); the next run then tries once more. Closed with a
  comment by the next run that posts.

Each is opened (or, when already open, its body brought up to date) with the job's
``GITHUB_TOKEN`` (``issues: write``). Nothing in it comes from X but the HTTP status and
error code.

Only an issue the workflow itself opened counts (its author is :data:`BOT`): in a public
repository anyone can open an issue with the same title, and the owner's steps for the X
token must never go into, or close, an issue a stranger wrote and can edit.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

import httpx

API: Final = "https://api.github.com"
TITLE: Final = "X posting stopped: refresh token"
REFUSED_TITLE: Final = "X posting stopped: X refused the post"
TIMEOUT: Final = httpx.Timeout(20.0, connect=10.0)
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


@dataclass(frozen=True, slots=True)
class Issue:
    title: str
    body: str
    closing: str
    """The comment the issue is closed with once posting works again."""


TOKEN: Final = Issue(TITLE, BODY, "The refresh token works again; posting continues.")
REFUSED: Final = Issue(REFUSED_TITLE, REFUSED_BODY, "X took a post again; posting continues.")


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

    def _open_issue(self, client: httpx.Client, issue: Issue) -> int | None:
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
                return int(item["number"])
        return None

    def is_open(self, client: httpx.Client, issue: Issue = TOKEN) -> bool:
        """Whether the workflow's own ``issue`` is open.

        Raises:
            httpx.HTTPError: GitHub could not be reached or refused.
        """
        return self._open_issue(client, issue) is not None

    def report(self, client: httpx.Client, why: str, now: datetime, issue: Issue = TOKEN) -> int:
        """Open the issue, or update the open one; its number.

        Raises:
            httpx.HTTPError: GitHub could not be reached or refused.
        """
        body = issue.body.format(why=why.rstrip("."), when=now.strftime("%Y-%m-%d %H:%M UTC"))
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
        made = response.json().get("number")
        return made if isinstance(made, int) else (number or 0)

    def resolve(self, client: httpx.Client, issue: Issue = TOKEN) -> int | None:
        """Close the open ``issue``, if any, with a comment; its number.

        Raises:
            httpx.HTTPError: GitHub could not be reached or refused.
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

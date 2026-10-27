"""The X API v2 calls a post needs (checked against docs.x.com, October 2026).

* **Refresh** (OAuth 2.0, confidential client): ``POST https://api.x.com/2/oauth2/token``,
  form ``grant_type=refresh_token&refresh_token=<token>``, HTTP Basic auth with the client
  id and secret. The answer holds ``access_token`` (about 2 hours), the rotated
  ``refresh_token`` and the granted ``scope``.
* **Image upload**: ``POST https://api.x.com/2/media/upload``, multipart form fields ``media``
  (the file) and ``media_category=tweet_image`` (scope ``media.write``); the answer's
  ``data.id`` is the media id. A ``data.processing_info`` that is not done yet is polled with
  ``GET /2/media/upload?command=STATUS&media_id=<id>``.
* **Alt text**: ``POST https://api.x.com/2/media/metadata`` with ``{"id": <media id>,
  "metadata": {"alt_text": {"text": ...}}}`` (scope ``media.write``, at most 1,000
  characters); HTTP 200.
* **Post**: ``POST https://api.x.com/2/tweets`` with ``{"text": ..., "media": {"media_ids":
  [<id>]}}`` (scopes ``tweet.read tweet.write users.read``); HTTP 201 with ``data.id``.

Errors keep only what the log may show: the HTTP status and X's error code or title, never
a token, a header or the request.
"""

import base64
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

import httpx

API: Final = "https://api.x.com"
TIMEOUT: Final = httpx.Timeout(30.0, connect=10.0)
NEEDED_SCOPES: Final = frozenset(
    {"tweet.read", "tweet.write", "users.read", "media.write", "offline.access"}
)
"""POST /2/tweets needs tweet.read, tweet.write and users.read; the upload and alt text need
media.write; a refresh token needs offline.access (docs.x.com)."""
EXCHANGE_GRANT: Final = "urn:ietf:params:oauth:grant-type:token-exchange"
OAUTH1_TOKEN_TYPE: Final = "urn:x:params:oauth:token-type:oauth1_token"  # noqa: S105 - a type name
"""The grant and subject type of X's OAuth 1.0a to OAuth 2.0 token exchange (docs.x.com)."""
FOR_GOOD: Final = frozenset({401, 402, 403})
"""X's answers to an upload or a post that no later run can change by itself: the token may
not do it (401), the account has no credits (402), or the app may not post or the post is a
duplicate (403)."""
STATUS_POLLS: Final = 5
MAX_WAIT: Final = 10.0
CODE: Final = re.compile(r"^[A-Za-z0-9_. -]{1,80}$")
"""What an error code or title must look like to be shown (no free text)."""

type Mask = Callable[[str], None]


class XError(RuntimeError):
    """An X call failed; the message is safe for the log."""


class RefreshRefusedError(XError):
    """X refused the refresh token (``invalid_grant``, ``invalid_request``, 401): the owner
    must paste a new one."""


class RefreshUnknownError(XError):
    """No usable answer to the refresh. ``maybe_spent``: X may have taken the refresh and
    spent the token (no answer, a 5xx, or a 200 without the tokens); not after an answer that
    says X did not take it (429 or another 4xx)."""

    def __init__(self, message: str, *, maybe_spent: bool = True) -> None:
        super().__init__(message)
        self.maybe_spent = maybe_spent


class ScopeError(XError):
    """The token lacks a scope a post needs."""


class RefusedError(XError):
    """X answered and did not post (nothing to undo). ``status`` is X's HTTP status when it
    answered: a 401, 402 or 403 (:data:`FOR_GOOD`) holds posting until the owner acts; any
    other refusal may be tried again by a later run."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def for_good(self) -> bool:
        return self.status in FOR_GOOD


class UnknownOutcomeError(XError):
    """The post request was sent and no answer came: X may have posted it."""


@dataclass(frozen=True, slots=True)
class Tokens:
    access: str = field(repr=False)
    refresh: str = field(repr=False)
    scopes: frozenset[str]


def _code(body: object) -> str:
    """X's error code or title, when it looks like one."""
    if not isinstance(body, dict):
        return ""
    for key in ("error", "title"):
        value = body.get(key)
        if isinstance(value, str) and CODE.match(value):
            return value
    errors = body.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        for key in ("title", "code"):
            value = errors[0].get(key)
            if isinstance(value, (str, int)) and CODE.match(str(value)):
                return str(value)
    return ""


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _say(response: httpx.Response) -> str:
    code = _code(_json(response))
    return f"HTTP {response.status_code}" + (f" ({code})" if code else "")


class XClient:
    def __init__(
        self,
        client: httpx.Client,
        *,
        api: str = API,
        mask: Mask,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._api = api
        self._mask = mask
        self._sleep = sleep

    def refresh(self, client_id: str, client_secret: str, refresh_token: str) -> Tokens:
        """A new access token and the rotated refresh token, both masked at once.

        Raises:
            RefreshRefusedError: X answered 400 or 401 (the token or the client is refused).
            RefreshUnknownError: no answer, a 5xx, an answer without the tokens (each may
                have spent the token), or a 429 or another 4xx (X did not take it).
        """
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self._mask(basic)
        try:
            response = self._client.post(
                f"{self._api}/2/oauth2/token",
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                headers={"Authorization": f"Basic {basic}"},
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as error:
            raise RefreshUnknownError(
                f"the token refresh got no answer ({type(error).__name__})"
            ) from None
        body = _json(response)
        if response.status_code in (400, 401):
            raise RefreshRefusedError(f"X refused the refresh token: {_say(response)}")
        if response.status_code != httpx.codes.OK or not isinstance(body, dict):
            raise RefreshUnknownError(
                f"the token refresh failed: {_say(response)}",
                maybe_spent=response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR
                or response.status_code == httpx.codes.OK,
            )
        access = body.get("access_token")
        if not isinstance(access, str) or not access:
            raise RefreshUnknownError("the token answer holds no access token")
        self._mask(access)
        rotated = body.get("refresh_token")
        if isinstance(rotated, str) and rotated:
            self._mask(rotated)
        else:
            rotated = refresh_token
        scope = body.get("scope")
        scopes = frozenset(scope.split()) if isinstance(scope, str) else frozenset()
        return Tokens(access=access, refresh=rotated, scopes=scopes)

    def exchange(
        self, client_id: str, client_secret: str, oauth1_token: str, oauth1_secret: str
    ) -> Tokens:
        """An OAuth 2.0 token pair for the account's OAuth 1.0a access token and its secret,
        both masked at once (docs.x.com, "Migrating OAuth 1.0a user tokens to OAuth 2.0"): an
        app with Read and write permission gets every write scope, ``media.write`` among them,
        and always a refresh token. Exchanging the same pair again gives a new token pair and
        ends the one before, so a run exchanges only when the chain starts from this pair.

        Raises:
            RefreshRefusedError: X answered 400, 401 or 403 (the pair or the client is refused).
            RefreshUnknownError: no answer, another status, or an answer without the tokens
                (``maybe_spent`` stays false: a later exchange of the same pair still works).
        """
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self._mask(basic)
        try:
            response = self._client.post(
                f"{self._api}/2/oauth2/token",
                data={
                    "grant_type": EXCHANGE_GRANT,
                    "subject_token": oauth1_token,
                    "subject_token_type": OAUTH1_TOKEN_TYPE,
                    "oauth_token_secret": oauth1_secret,
                },
                headers={"Authorization": f"Basic {basic}"},
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as error:
            raise RefreshUnknownError(
                f"the token exchange got no answer ({type(error).__name__})"
            ) from None
        body = _json(response)
        if response.status_code in (400, 401, 403):
            raise RefreshRefusedError(f"X refused the token exchange: {_say(response)}")
        if response.status_code != httpx.codes.OK or not isinstance(body, dict):
            raise RefreshUnknownError(f"the token exchange failed: {_say(response)}")
        access, refresh = body.get("access_token"), body.get("refresh_token")
        if not isinstance(access, str) or not access:
            raise RefreshUnknownError("the exchange answer holds no access token")
        self._mask(access)
        if not isinstance(refresh, str) or not refresh:
            raise RefreshUnknownError("the exchange answer holds no refresh token")
        self._mask(refresh)
        scope = body.get("scope")
        scopes = frozenset(scope.split()) if isinstance(scope, str) else frozenset()
        return Tokens(access=access, refresh=refresh, scopes=scopes)

    def upload_image(self, access: str, name: str, data: bytes, content_type: str) -> str:
        """The media id of one uploaded image (asked again once after no answer or a 5xx:
        an unused upload posts nothing).

        Raises:
            RefusedError: the upload failed; nothing was posted.
        """
        response: httpx.Response | None = None
        for _ in range(2):
            try:
                response = self._client.post(
                    f"{self._api}/2/media/upload",
                    data={"media_category": "tweet_image"},
                    files={"media": (name, data, content_type)},
                    headers={"Authorization": f"Bearer {access}"},
                    timeout=TIMEOUT,
                )
            except httpx.HTTPError:
                response = None
                continue
            if response.status_code < 500:  # noqa: PLR2004 - HTTP 5xx
                break
        if response is None:
            raise RefusedError("the image upload got no answer")
        body = _json(response)
        data_part = body.get("data") if isinstance(body, dict) else None
        if response.status_code != httpx.codes.OK or not isinstance(data_part, dict):
            raise RefusedError(
                f"X refused the image upload: {_say(response)}", status=response.status_code
            )
        media_id = data_part.get("id")
        if not isinstance(media_id, str) or not media_id.isdigit():
            raise RefusedError("the image upload answer holds no media id")
        self._wait(access, media_id, data_part.get("processing_info"))
        return media_id

    def _wait(self, access: str, media_id: str, info: object) -> None:
        for _ in range(STATUS_POLLS):
            if not isinstance(info, dict):
                return
            state = info.get("state")
            if state == "succeeded":
                return
            if state == "failed":
                raise RefusedError("X could not process the image")
            after = info.get("check_after_secs")
            self._sleep(min(float(after), MAX_WAIT) if isinstance(after, int) else 1.0)
            try:
                response = self._client.get(
                    f"{self._api}/2/media/upload",
                    params={"command": "STATUS", "media_id": media_id},
                    headers={"Authorization": f"Bearer {access}"},
                    timeout=TIMEOUT,
                )
            except httpx.HTTPError:
                continue
            body = _json(response)
            data_part = body.get("data") if isinstance(body, dict) else None
            info = data_part.get("processing_info") if isinstance(data_part, dict) else None
        if isinstance(info, dict) and info.get("state") != "succeeded":
            raise RefusedError("the image was still processing")

    def describe(self, access: str, media_id: str, alt: str) -> None:
        """Set an uploaded image's alt text (asked once; a post goes without it on failure).

        Raises:
            RefusedError: X did not set it.
        """
        try:
            response = self._client.post(
                f"{self._api}/2/media/metadata",
                json={"id": media_id, "metadata": {"alt_text": {"text": alt[:1000]}}},
                headers={"Authorization": f"Bearer {access}"},
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as error:
            raise RefusedError(f"the alt text got no answer ({type(error).__name__})") from None
        if response.status_code != httpx.codes.OK:
            raise RefusedError(f"X refused the alt text: {_say(response)}")

    def post(self, access: str, text: str, media_id: str) -> str:
        """Post the text with the image; the post's id. Sent once, never again.

        Only a 201 whose JSON holds the post's id (``data.id``) is posted. Any other 2xx (a
        200, 202 or 204, or a 201 without that id) may have made the post, so it is never a
        refusal: its outcome is unknown.

        Raises:
            RefusedError: X answered 3xx or 4xx (it did not post), or the request never left.
            UnknownOutcomeError: the request was sent and no answer came, a 5xx, or a 2xx
                that does not give the post's id.
        """
        try:
            response = self._client.post(
                f"{self._api}/2/tweets",
                json={"text": text, "media": {"media_ids": [media_id]}},
                headers={"Authorization": f"Bearer {access}"},
                timeout=TIMEOUT,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            raise RefusedError(
                f"the post request never reached X ({type(error).__name__})"
            ) from None
        except httpx.HTTPError as error:
            raise UnknownOutcomeError(f"the post got no answer ({type(error).__name__})") from None
        if response.status_code >= 500:  # noqa: PLR2004 - HTTP 5xx
            raise UnknownOutcomeError(f"X answered the post with {_say(response)}")
        if not httpx.codes.is_success(response.status_code):
            raise RefusedError(f"X refused the post: {_say(response)}", status=response.status_code)
        body = _json(response)
        data_part = body.get("data") if isinstance(body, dict) else None
        post_id = data_part.get("id") if isinstance(data_part, dict) else None
        if (
            response.status_code != httpx.codes.CREATED
            or not isinstance(post_id, str)
            or not post_id.isdigit()
        ):
            raise UnknownOutcomeError(
                f"X answered the post with {_say(response)}, not a 201 with the post's id"
            )
        return post_id

"""The accounts database (D1, ``snowlight-accounts``) over the Cloudflare API.

The sender runs in GitHub Actions with the same two secrets the API's deploy uses
(``CLOUDFLARE_API_TOKEN``, ``CLOUDFLARE_ACCOUNT_ID``): it finds the database by name and
sends one SQL statement per request, values always as bound parameters. An error names the
HTTP status only, never the statement or a value, so no key or address reaches the log.
"""

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import httpx

API: Final = "https://api.cloudflare.com/client/v4"
DATABASE: Final = "snowlight-accounts"
MAX_PARAMS: Final = 100
"""D1 binds at most 100 parameters to one statement."""
TIMEOUT: Final = httpx.Timeout(30.0, connect=10.0)
RETRY_PAUSE: Final = 5.0

type Row = dict[str, Any]
type Value = str | int | float | None


class D1Error(RuntimeError):
    """The database could not be read or written (the message names only the HTTP status)."""


class NoTablesError(D1Error):
    """The notification tables are not there yet (migration 0004 is not applied)."""


@dataclass(frozen=True, slots=True)
class Secrets:
    token: str
    account: str
    api: str = API

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Secrets | None":
        """The Cloudflare secrets, or ``None`` when either is missing (the sender stays dark)."""
        token = env.get("CLOUDFLARE_API_TOKEN", "")
        account = env.get("CLOUDFLARE_ACCOUNT_ID", "")
        if not token or not account:
            return None
        return cls(token=token, account=account, api=env.get("CLOUDFLARE_API_URL") or API)


class D1:
    """One database, by id."""

    def __init__(
        self,
        client: httpx.Client,
        secrets: Secrets,
        database: str,
        *,
        pause: float = RETRY_PAUSE,
    ) -> None:
        self._client = client
        self._secrets = secrets
        self._database = database
        self._pause = pause

    @classmethod
    def find(cls, client: httpx.Client, secrets: Secrets, *, pause: float = RETRY_PAUSE) -> "D1":
        """The accounts database, found by name.

        Raises:
            D1Error: the account lists no such database, or the list cannot be read.
        """
        url = f"{secrets.api}/accounts/{secrets.account}/d1/database"
        body = _answer(
            lambda: client.get(
                url, params={"name": DATABASE}, headers=_auth(secrets), timeout=TIMEOUT
            ),
            pause,
        )
        found = [
            item
            for item in body.get("result") or []
            if isinstance(item, dict) and item.get("name") == DATABASE
        ]
        if not found or not isinstance(found[0].get("uuid"), str):
            raise D1Error(f"the Cloudflare account has no database {DATABASE}")
        return cls(client, secrets, str(found[0]["uuid"]), pause=pause)

    def query(self, sql: str, params: Sequence[Value] = ()) -> list[Row]:
        """The rows of one statement.

        Raises:
            NoTablesError: a table it names is not there.
            D1Error: anything else went wrong.
        """
        if len(params) > MAX_PARAMS:
            raise ValueError(f"D1 binds at most {MAX_PARAMS} parameters")
        url = (
            f"{self._secrets.api}/accounts/{self._secrets.account}"
            f"/d1/database/{self._database}/query"
        )
        body = _answer(
            lambda: self._client.post(
                url,
                json={"sql": sql, "params": list(params)},
                headers=_auth(self._secrets),
                timeout=TIMEOUT,
            ),
            self._pause,
        )
        results = body.get("result")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            raise D1Error("the D1 answer holds no result")
        rows = results[0].get("results") or []
        if not isinstance(rows, list):
            raise D1Error("the D1 answer holds no rows")
        return [row for row in rows if isinstance(row, dict)]


def _auth(secrets: Secrets) -> dict[str, str]:
    return {"Authorization": f"Bearer {secrets.token}"}


def _answer(request: Any, pause: float) -> dict[str, Any]:
    """The JSON of a successful answer; no answer or a 5xx is asked again once."""
    response: httpx.Response | None = None
    for attempt in range(2):
        try:
            response = request()
        except httpx.HTTPError:
            response = None
        if response is not None and response.status_code < 500:  # noqa: PLR2004 - HTTP 5xx
            break
        if attempt == 0:
            time.sleep(pause)
    if response is None:
        raise D1Error("the Cloudflare API did not answer")
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise D1Error(f"the Cloudflare API answered HTTP {response.status_code} without JSON")
    if response.status_code != httpx.codes.OK or body.get("success") is not True:
        messages = " ".join(
            str(error.get("message", ""))
            for error in body.get("errors") or []
            if isinstance(error, dict)
        )
        if "no such table" in messages:
            raise NoTablesError("the notification tables are not there yet")
        raise D1Error(f"the Cloudflare API answered HTTP {response.status_code}")
    return body

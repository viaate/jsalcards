"""The serving pass's inputs from the world: the deployed directory, the alerts, the boundaries.

* The deployed directory: the edition the site serves (S8-0's reader,
  :class:`snowlight.directory.deployed.Reader`, never a plain GET), and the ``meta.json``
  and ``points.bin`` its page names; both must be the ones the edition names (their
  written digest), or the pass is dark.
* The alerts: ``api.weather.gov/alerts/active`` with a User-Agent naming the site (free,
  no key), conditionally on the last ETag.
* The NWS zone and county boundaries in effect today (cached; the workflow keeps the
  cache folder between runs).
"""

import os
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import httpx

from snowlight import __version__
from snowlight.directory.deployed import DeployedEditionError, Reader
from snowlight.directory.points import PointsFormatError, decode
from snowlight.predict.publish import Dark, DarkError
from snowlight.predict.serve import DeployedDirectory
from snowlight.schemas.directory import DirectoryEdition, SchoolDirectoryMeta, written_edition
from snowlight.sources.nws.alerts import (
    ACCEPT,
    ACTIVE_URL,
    ActiveFeed,
    AlertFormatError,
    NwsAlert,
    parse_active,
)

USER_AGENT: Final = f"snowlight-predict/{__version__} (+https://snowlightmap.com)"
"""The NWS asks every client to name itself and a contact."""
TIMEOUT: Final = httpx.Timeout(30.0, connect=15.0)
EDITION_WAIT: Final = timedelta(minutes=2)


def verify() -> ssl.SSLContext | bool:  # pragma: no cover - the machine's certificates
    """The TLS check: a proxy's CA bundle when ``SSL_CERT_FILE`` names one."""
    bundle = os.environ.get("SSL_CERT_FILE")
    return ssl.create_default_context(cafile=bundle) if bundle else True


def client(headers: Mapping[str, str] | None = None) -> httpx.Client:  # pragma: no cover
    """An HTTP client that names the site."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, **(headers or {})},
        timeout=TIMEOUT,
        follow_redirects=True,
        verify=verify(),
    )


def directory_from_files(
    edition: DirectoryEdition, meta_bytes: bytes, points_bytes: bytes
) -> tuple[DeployedDirectory, SchoolDirectoryMeta]:
    """The deployed directory, once ``meta.json`` and ``points.bin`` are the ones ``edition``
    names.

    Raises:
        DarkError: they are not, or one does not read.
    """
    try:
        made = written_edition(meta_bytes, points_bytes)
        meta = SchoolDirectoryMeta.from_json_bytes(meta_bytes)
        points = decode(points_bytes)
    except (ValueError, PointsFormatError) as error:
        raise DarkError(Dark.EDITION, f"directory files: {type(error).__name__}") from error
    if made != edition:
        raise DarkError(Dark.EDITION, "meta.json and points.bin are not the deployed edition")
    try:
        directory = DeployedDirectory(
            edition.stamp(),
            meta.districts.ids,
            points,
            content_sha256=edition.content_sha256,
            school_ids=meta.ids,
        )
    except ValueError as error:
        raise DarkError(Dark.EDITION, str(error)) from error
    return directory, meta


def read_deployed(
    site: str, repository: str, token: str | None
) -> DeployedDirectory:  # pragma: no cover - the live site and GitHub's API
    """The directory the site serves now (see the module docstring).

    Raises:
        DarkError: it cannot be known for certain.
    """
    return read_deployed_meta(site, repository, token)[0]


def read_deployed_meta(
    site: str, repository: str, token: str | None
) -> tuple[DeployedDirectory, SchoolDirectoryMeta]:  # pragma: no cover - the live site
    """The directory the site serves now and its ``meta.json`` (the school ids), as
    :func:`read_deployed` reads them.

    Raises:
        DarkError: it cannot be known for certain.
    """
    api_headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        api_headers["Authorization"] = f"Bearer {token}"
    with (
        client() as cdn,
        httpx.Client(
            base_url="https://api.github.com",
            headers={"User-Agent": USER_AGENT, **api_headers},
            timeout=TIMEOUT,
            follow_redirects=True,
            verify=verify(),
        ) as api,
    ):
        reader = Reader(
            site_url=site, repository=repository, api=api, cdn=cdn, max_wait=EDITION_WAIT
        )
        try:
            found = reader.read()
            if found.data is None:
                raise DarkError(Dark.EDITION, "the site serves no edition")
            edition = DirectoryEdition.from_json_bytes(found.data)
            files = reader.page_directory(None, datetime.now(UTC) + EDITION_WAIT)
        except (DeployedEditionError, httpx.HTTPError, ValueError) as error:
            raise DarkError(Dark.EDITION, type(error).__name__) from error
    return directory_from_files(edition, files.meta, files.points)


def read_local(folder: Path) -> DeployedDirectory:
    """A directory from a folder holding ``meta.json``, ``points.bin`` and, when it has one,
    ``edition.json`` (a dry run against a local build).

    Raises:
        DarkError: the files do not read or do not agree.
    """
    meta = (folder / "meta.json").read_bytes()
    points = (folder / "points.bin").read_bytes()
    edition_path = folder / "edition.json"
    if edition_path.exists():
        edition = DirectoryEdition.from_json_bytes(edition_path.read_bytes())
    else:
        try:
            edition = written_edition(meta, points)
        except ValueError as error:
            raise DarkError(Dark.EDITION, type(error).__name__) from error
    return directory_from_files(edition, meta, points)[0]


@dataclass(slots=True)
class AlertsReader:
    """Reads the active alerts, asking again only with the last ETag."""

    http: httpx.Client
    etag: str | None = None
    feed: ActiveFeed | None = None
    fetched_at: datetime | None = None
    notes: list[str] = field(default_factory=list)

    def read(self) -> tuple[ActiveFeed, bool]:
        """The feed and whether it changed since the last read.

        Raises:
            DarkError: it cannot be read.
        """
        headers = {"Accept": ACCEPT}
        if self.etag and self.feed is not None:
            headers["If-None-Match"] = self.etag
        try:
            response = self.http.get(ACTIVE_URL, headers=headers)
        except httpx.HTTPError as error:
            raise DarkError(Dark.ALERTS, type(error).__name__) from error
        if response.status_code == httpx.codes.NOT_MODIFIED and self.feed is not None:
            return self.feed, False
        if response.status_code != httpx.codes.OK:
            raise DarkError(Dark.ALERTS, f"HTTP {response.status_code}")
        try:
            feed = parse_active(response.content)
        except AlertFormatError as error:
            raise DarkError(Dark.ALERTS, "not an alerts feed") from error
        self.etag = response.headers.get("etag")
        self.feed = feed
        self.fetched_at = datetime.now(UTC)
        return feed, True


HISTORY_URL: Final = "https://api.weather.gov/alerts"
HISTORY_EVENTS: Final = (
    "Blizzard Warning",
    "Ice Storm Warning",
    "Winter Storm Warning",
    "Lake Effect Snow Warning",
    "Extreme Cold Warning",
    "Wind Chill Warning",
    "Hurricane Warning",
    "Tropical Storm Warning",
    "Winter Weather Advisory",
    "Freezing Rain Advisory",
    "Lake Effect Snow Advisory",
)
"""The NWS event names of the class-making VTEC codes (:data:`CLASS_BY_CODE`)."""
HISTORY_PAGES: Final = 40


@dataclass(slots=True)
class AlertsHistory:
    """Reads the alert products issued in a span (``api.weather.gov/alerts?start=&end=``), to
    rebuild a lost alert memory."""

    http: httpx.Client

    def read(self, start: datetime, end: datetime) -> list[NwsAlert]:  # pragma: no cover
        """Every class-making product issued from ``start`` to ``end``, every page.

        Raises:
            DarkError: a page cannot be read, or there are more pages than allowed.
        """
        params: dict[str, str] | None = {
            "start": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "actual",
            "event": ",".join(HISTORY_EVENTS),
            "limit": "500",
        }
        url = HISTORY_URL
        found: list[NwsAlert] = []
        for _page in range(HISTORY_PAGES):
            try:
                response = self.http.get(url, params=params, headers={"Accept": ACCEPT})
            except httpx.HTTPError as error:
                raise DarkError(Dark.MEMORY, f"alert history: {type(error).__name__}") from error
            if response.status_code != httpx.codes.OK:
                raise DarkError(Dark.MEMORY, f"alert history: HTTP {response.status_code}")
            try:
                page = parse_active(response.content)
                following = response.json().get("pagination", {}).get("next")
            except (AlertFormatError, ValueError, AttributeError) as error:
                raise DarkError(Dark.MEMORY, "alert history: not an alerts page") from error
            found.extend(page.alerts)
            if not page.alerts or not isinstance(following, str):
                return found
            url, params = following, None
        raise DarkError(Dark.MEMORY, f"alert history: more than {HISTORY_PAGES} pages")

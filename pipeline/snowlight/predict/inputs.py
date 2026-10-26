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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from urllib.parse import urlencode

import httpx

from snowlight import __version__
from snowlight.directory.deployed import DeployedEditionError, Reader
from snowlight.directory.points import PointsFormatError, decode
from snowlight.predict.publish import Dark, DarkError
from snowlight.predict.serve import DeployedDirectory
from snowlight.predict.situations import HEADS_UP_BY_CODE
from snowlight.schemas.directory import DirectoryEdition, SchoolDirectoryMeta, written_edition
from snowlight.sources.nws.alerts import (
    ACCEPT,
    ACTIVE_URL,
    ActiveFeed,
    AlertFormatError,
    NwsAlert,
    parse_active,
)
from snowlight.sources.nws.http import HttpCache, parse_iso_utc
from snowlight.sources.nws.iem import FINAL_AFTER, PROVISIONAL_MAX_AGE, WATCHWARN_URL
from snowlight.weather.hazards import ALERT_TYPES, CONUS_STATES
from snowlight.weights.archive import EventRow, read_rows, request_window

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
HEADS_UP_EVENTS: Final = tuple(
    kind.event
    for kind in ALERT_TYPES
    if any(
        f"{phenomena}.{significance}" in HEADS_UP_BY_CODE for phenomena, significance in kind.codes
    )
)
"""The NWS event names of the heads-up VTEC codes (:data:`HEADS_UP_BY_CODE`, retired ones too)."""
PRODUCT_EVENTS: Final = HISTORY_EVENTS + HEADS_UP_EVENTS
"""What the outlook's product log rebuilds from (S7-F): the classes' products and the
heads-ups'. The alert memory's own read stays :data:`HISTORY_EVENTS`."""
HISTORY_PAGES: Final = 40


@dataclass(slots=True)
class AlertsHistory:
    """Reads the alert products issued in a span (``api.weather.gov/alerts?start=&end=``), to
    rebuild a lost alert memory."""

    http: httpx.Client

    def read(
        self,
        start: datetime,
        end: datetime,
        *,
        events: tuple[str, ...] = HISTORY_EVENTS,
        before: Callable[[], bool] | None = None,
    ) -> list[NwsAlert]:
        """Every product of ``events`` (the class-making ones by default) issued from ``start``
        to ``end``, page by page, each once. ``before``, asked before every page, says whether
        there is still time to read it (the outlook's bounded read; ``None``: no limit).

        The feed pages newest first. It is read to its end, and also stops, whole, at a page
        that holds nothing new: a ``next`` link already followed or a page of products already
        read (the cursor looping), or a page of products all issued before ``start`` (the
        rest are older still). A fresh start once went dark at the page bound on such a feed.

        Raises:
            DarkError: a page cannot be read, there are more pages of new products than
                allowed (the error says how far back they reached), or ``before`` said no.
        """
        params: dict[str, str] | None = {
            "start": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "actual",
            "event": ",".join(events),
            "limit": "500",
        }
        url = HISTORY_URL
        found: dict[str, NwsAlert] = {}
        followed: set[str] = set()
        for _page in range(HISTORY_PAGES):
            if before is not None and not before():
                raise DarkError(Dark.MEMORY, "alert history: the time for this read is up")
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
            fresh = [alert for alert in page.alerts if alert.id not in found]
            found.update((alert.id, alert) for alert in fresh)
            if (
                not fresh
                or not isinstance(following, str)
                or following in followed
                or all(alert.sent < start for alert in fresh)
            ):
                return list(found.values())
            followed.add(following)
            url, params = following, None
        oldest = min(alert.sent for alert in found.values())
        raise DarkError(
            Dark.MEMORY,
            f"alert history: more than {HISTORY_PAGES} pages ({len(found):,} products, back to "
            f"{oldest.astimezone(UTC):%Y-%m-%dT%H:%MZ})",
        )


# --- the heads-up history (S7-F F1, spec-f s. 2 and 11) ----------------------------------------

HEADS_UP_PAIRS: Final = (
    ("WS", "A"),
    ("BZ", "A"),
    ("LE", "A"),
    ("WC", "A"),
    ("EC", "A"),
    ("HU", "A"),
    ("TR", "A"),
    ("CW", "Y"),
    ("WC", "Y"),
)
"""The phenomena and significance pairs asked of IEM: every heads-up code
(:data:`~snowlight.predict.situations.HEADS_UP_BY_CODE`), retired codes included."""
HEADS_UP_CODES: Final = frozenset(
    f"{phenomena}.{significance}" for phenomena, significance in HEADS_UP_PAIRS
)
HEADS_UP_CACHE: Final = Path(__file__).resolve().parents[2] / ".cache" / "predict"
"""The heads-up files' own cache tree (gitignored): the weights build's files and their
provenance stay untouched."""
HEADS_UP_FOLDER: Final = "watchwarn-headsup-csv"
FIRST_HEADS_UP_SEASON: Final = 2015
CODE_SEASONS: Final[Mapping[str, tuple[int | None, int | None]]] = {
    "BZ.A": (None, 2016),
    "LE.A": (None, 2016),
    "WC.A": (None, 2023),
    "WC.Y": (None, 2023),
    "EC.A": (2024, None),
    "CW.Y": (2024, None),
}
"""The seasons (first, last; by starting year) a code may have rows in: the NWS folded the
Blizzard and Lake Effect Snow Watches into the Winter Storm Watch from 2017-18, and replaced the
Wind Chill Watch and Advisory with the Extreme Cold Watch and the Cold Weather Advisory from
2024-25 (spec-f GF9: counts asserted per season)."""


def headsup_url(year: int) -> str:
    """The ``watchwarn.py`` CSV request for one school year of heads-up rows: the weights
    build's request (:func:`snowlight.weights.archive.year_url`) with the heads-up pairs."""
    first, end = request_window(year)
    query = {
        "accept": "csv",
        "sts": f"{first.isoformat()}T00:00Z",
        "ets": f"{end.isoformat()}T00:00Z",
        "limitps": "1",
        "phenomena": ",".join(phenomena for phenomena, _ in HEADS_UP_PAIRS),
        "significance": ",".join(significance for _, significance in HEADS_UP_PAIRS),
        "location_group": "states",
        "states": ",".join(sorted(set(CONUS_STATES))),
    }
    return f"{WATCHWARN_URL}?{urlencode(query, safe=',:')}"


def headsup_path(root: Path, year: int) -> Path:
    """Where one school year's heads-up file is cached."""
    return root / "mesonet.agron.iastate.edu" / HEADS_UP_FOLDER / f"{year}-{year + 1}.csv"


@dataclass(frozen=True, slots=True)
class HeadsUpSeason:
    """One school year's heads-up rows, their counts by code, and the file's provenance."""

    year: int
    rows: int
    by_code: Mapping[str, int]
    closed_tropical: int
    """Tropical watch and warning rows no product ended, ended when their event's last
    explicitly ended row did (:func:`snowlight.weights.archive.close_open_tropical`)."""
    sha256: str
    url: str
    bytes: int
    final: bool


def read_headsup(text: str) -> tuple[list[EventRow], dict[str, int], int]:
    """The zone rows of one heads-up file, their count by code, and how many tropical rows no
    product ended were ended with their event (a Tropical Storm or Hurricane Watch is issued
    until further notice, and IEM keeps a placeholder end days later: spec-f s. 3). Such a row
    carries ``recorded_end``: its ``end`` came from later products, so a state at an earlier
    time reads the row as open until that end has passed (docs/predict.md).

    Raises:
        snowlight.weights.archive.ArchiveCsvError: the file is malformed or holds another code.
    """
    rows, stats = read_rows(text, codes=HEADS_UP_CODES)
    closed = sum(1 for row in stats.closed_tropical if row.end is not None)
    return rows, dict(sorted(stats.by_code.items())), closed


def code_problems(counts: Mapping[int, Mapping[str, int]]) -> list[str]:
    """Rows of a code in a season it cannot have (:data:`CODE_SEASONS`)."""
    problems: list[str] = []
    for year, by_code in sorted(counts.items()):
        for code, count in sorted(by_code.items()):
            first, last = CODE_SEASONS.get(code, (None, None))
            if count and (
                (first is not None and year < first) or (last is not None and year > last)
            ):
                problems.append(f"{year}-{(year + 1) % 100:02d}: {count} rows of {code}")
    return problems


def load_headsup(
    year: int, http: HttpCache, root: Path = HEADS_UP_CACHE
) -> HeadsUpSeason:  # pragma: no cover - IEM
    """One school year's heads-up file, fetched when missing or provisional, as the weights
    build fetches its own (a file is final once fetched 21 days after its window ended).

    Raises:
        snowlight.weights.archive.ArchiveCsvError: the file is malformed.
    """
    url, dest = headsup_url(year), headsup_path(root, year)
    end = datetime.combine(request_window(year)[1], datetime.min.time(), tzinfo=UTC)
    cached = http.cached(url, dest)
    final_copy = (
        cached is not None and parse_iso_utc(cached.provenance.checked_at) >= end + FINAL_AFTER
    )
    file = http.fetch(url, dest, max_age=None if final_copy else PROVISIONAL_MAX_AGE)
    rows, by_code, closed = read_headsup(file.path.read_text(encoding="utf-8"))
    return HeadsUpSeason(
        year,
        len(rows),
        by_code,
        closed,
        file.provenance.sha256,
        url,
        file.provenance.size,
        parse_iso_utc(file.provenance.checked_at) >= end + FINAL_AFTER,
    )

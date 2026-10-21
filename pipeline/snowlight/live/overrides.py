"""Manual statuses (accounts spec C): the admin's overrides, published in the live closings file.

The site's admin sets a status by hand in the admin view, for a district (every one of its
schools) or for one school: closed, a delayed start (its minutes), an early dismissal (its
time) or open, for the days the admin picks in the school's own time zone: today, tomorrow,
or today and tomorrow. The API (the ``snowlight-api`` Worker) keeps one per district or
school (saving again replaces it, days and all) and serves the active ones with the listed
days that have not ended, without the admin's note or name, at ``GET {API}/v1/overrides``.
live-ingest.yml runs ``snowlight live overrides`` every 5 minutes (the owner's Cloudflare
timer dispatches it):

1. :func:`fetch` reads them. Anything but a well-formed answer (an HTTP error, a body that
   is not JSON, a field missing, unknown or out of range) is :class:`OverridesError`:
   nothing is published and the public file stays as it is.
2. :func:`resolve` checks every id against the deployed directory (the school ids of the
   ``meta.json`` the site serves, its district list, and each school's district in
   ``points.bin``): a district's override covers each of its schools, and an id the
   deployed directory does not hold lights nothing. An override lights exactly the days it
   lists that are the school's today or tomorrow, in its district's time zone (the model's,
   :func:`zone_table`; the predictions file gives the page the same one; a school without a
   district takes the zone of the nearest school with one), with its current status, delay
   and time, and nothing else: no day is guessed or carried over. A day it no longer lists
   (it was saved again with other days, or deleted) goes at the next pass. An expired
   override, a school whose time zone is not known, and an override whose days the admin
   view named in another zone than this one (``zone_differs``: its dates may not be the
   school's today and tomorrow) light nothing. A school's own
   override beats its district's. A day shown with the same status, delay and time keeps
   the time it was first posted (:func:`resolve`, ``shown``).
3. :func:`~snowlight.live.merge.with_overrides` puts them on top of the lists' statuses,
   so the admin outranks every list read (S8-E brings the lists; there are none yet).
4. :class:`~snowlight.live.publish.LivePublisher` gates and publishes the result, as for
   the lists: stamped with the deployed directory, refused while the hold is set,
   uploaded when the content changed and as the heartbeat, with the day timelines; the
   heartbeat is every 10 minutes (:data:`HEARTBEAT`). Nothing is uploaded
   when the overrides light nothing and the public files show no status
   (:func:`nothing_to_publish`), so a quiet day writes nothing.

The published rows carry the closings file's ``manual`` mark, which the page shows as a
short line saying the site's team confirmed it (never a station or list); the private
provenance line keeps ``source_type`` ``admin``. A status shows "Posted" at the time the
admin first set it on that day (a save that keeps it as it is keeps the time).
"""

import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import numpy as np
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    ValidationError,
    model_validator,
)

from snowlight.directory.points import NO_DISTRICT
from snowlight.live.merge import AdminStatus, Merged
from snowlight.live.publish import CLOSINGS, OPENS
from snowlight.live.publishers import Publisher
from snowlight.live.resolve import LiveDirectory, LiveSchool
from snowlight.replays.build import School
from snowlight.schemas.directory import DirectoryStamp, SchoolDirectoryMeta
from snowlight.schemas.live import Closing, ClosingsFile, OpensFile, local_days
from snowlight.schemas.scalars import MAX_SHIFT_MINUTES
from snowlight.schemas.vocab import Status

if TYPE_CHECKING:
    from snowlight.predict.serve import DeployedDirectory

PATH: Final = "v1/overrides"
"""The public list of active overrides, under the API root."""
MAX_BYTES: Final = 2 * 1024 * 1024
MAX_OVERRIDES: Final = 10_000
CLOCK_SLACK: Final = timedelta(seconds=60)
"""How far ahead of this machine's clock an override's ``set_at`` may be (the Worker's
clock): it is published as set now; further ahead, it lights nothing."""
TIMEOUT: Final = httpx.Timeout(20.0, connect=10.0)
MAX_DAYS: Final = 2
"""An override lists one or two days: today, tomorrow, or both."""
HEARTBEAT: Final = timedelta(minutes=10)
"""The overrides pass's heartbeat (:attr:`LivePublisher.heartbeat
<snowlight.live.publish.LivePublisher.heartbeat>`). The live repository's Pages site is
built from its branch, and GitHub builds a branch at most about 10 times an hour; a
5-minute heartbeat (12 commits an hour, beside predict.yml's) would hold builds back, and
an edit or a take-down with them. Every 10 minutes keeps the file well inside the page's
20 minutes (``LIVE_FRESH_MS``); a change still uploads on the pass that finds it."""

STATUS_OF: Final[Mapping[str, Status | None]] = {
    "closed": Status.CLOSED,
    "delayed": Status.DELAYED,
    "early_dismissal": Status.EARLY_DISMISSAL,
    "open": None,
}
"""The API's status words and the published status (``None``: open, no row)."""


class OverridesError(RuntimeError):
    """The overrides cannot be trusted: nothing is published (the message holds codes only)."""


type Id = Annotated[str, StringConstraints(pattern=r"^[0-9A-Za-z]{1,20}$")]
type LocalTime = Annotated[str, StringConstraints(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]
type ZoneName = Annotated[
    str,
    StringConstraints(max_length=64, pattern=r"^[A-Z][A-Za-z]+(?:/[A-Za-z][A-Za-z0-9_+-]*){1,2}$"),
]


class Override(BaseModel):
    """One active override as the API serves it."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    scope: Literal["district", "school"]
    id: Id
    status: Literal["closed", "delayed", "early_dismissal", "open"]
    minutes: Annotated[StrictInt, Field(ge=1, le=MAX_SHIFT_MINUTES)] | None = None
    """How late a delayed start begins (a delay has it; nothing else does)."""
    at_local_time: LocalTime | None = None
    """The dismissal time, ``HH:MM`` local (an early dismissal has it; nothing else does)."""
    days: Annotated[tuple[date, ...], Field(min_length=1, max_length=MAX_DAYS)]
    """The school-local days it holds, ascending and next to each other: the ones the admin
    listed whose end had not passed when the API answered."""
    time_zone: ZoneName | None
    """The zone the admin view listed the days in (``None``: set before days were stored);
    the days are read as the school's own local dates."""
    set_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.expires_at <= self.set_at:
            raise ValueError("an override expires after it is set")
        if any(later - earlier != timedelta(days=1) for earlier, later in pairwise(self.days)):
            raise ValueError("an override's days are ascending and next to each other")
        wanted = (self.status == "delayed", self.status == "early_dismissal")
        if (self.minutes is not None, self.at_local_time is not None) != wanted:
            raise ValueError("a delay has its minutes, an early dismissal its time, no other")
        return self

    @property
    def clock_minute(self) -> int | None:
        if self.at_local_time is None:
            return None
        hours, minutes = self.at_local_time.split(":")
        return int(hours) * 60 + int(minutes)

    def key(self) -> str:
        """The override's id in the private provenance: a digest of its scope, target and
        times (no words)."""
        body = f"{self.scope}|{self.id}|{self.set_at.isoformat()}|{self.expires_at.isoformat()}"
        return hashlib.sha256(body.encode()).hexdigest()[:32]


class OverridesResponse(BaseModel):
    """``GET /v1/overrides``: ``{"overrides": [...]}`` (other fields are ignored)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    overrides: Annotated[tuple[Override, ...], Field(max_length=MAX_OVERRIDES)]


def api_url(root: str) -> str:
    """``{root}/v1/overrides`` for an ``https://`` root (``http://`` only for a loopback
    test server).

    Raises:
        OverridesError: the root is not such a URL.
    """
    url = httpx.URL(root.strip())
    loopback = url.scheme == "http" and url.host in {"127.0.0.1", "localhost"}
    if not (url.scheme == "https" or loopback) or not url.host or url.query or url.fragment:
        raise OverridesError("the API root is not an https URL")
    return str(url.join(PATH if url.path.endswith("/") else f"{url.path}/{PATH}"))


def parse(body: bytes) -> tuple[Override, ...]:
    """The overrides of one answer.

    Raises:
        OverridesError: it is not a well-formed list of overrides.
    """
    if len(body) > MAX_BYTES:
        raise OverridesError("the answer is too large")
    try:
        found = OverridesResponse.model_validate_json(body, strict=True)
    except ValidationError as error:
        problems = error.errors()
        code = problems[0]["type"] if problems else "invalid"
        where = ".".join(str(part) for part in problems[0]["loc"]) if problems else ""
        raise OverridesError(f"malformed answer ({code} at {where or '-'})") from error
    return found.overrides


def fetch(client: httpx.Client, root: str) -> tuple[Override, ...]:
    """Read the active overrides from the API.

    Raises:
        OverridesError: the API did not answer with a well-formed list.
    """
    url = api_url(root)
    try:
        response = client.get(
            url,
            headers={"Accept": "application/json", "Cache-Control": "no-cache"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as error:
        raise OverridesError(f"GET {PATH}: {type(error).__name__}") from error
    if response.status_code != httpx.codes.OK:
        raise OverridesError(f"GET {PATH}: HTTP {response.status_code}")
    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind != "application/json":
        raise OverridesError(f"GET {PATH}: not JSON")
    return parse(response.content)


def zone_table(path: Path | None = None) -> dict[str, str]:
    """Each district's IANA time zone by its id, from the committed model (every deployed
    district has one; the predictions file gives the page the same zones).

    Raises:
        OSError, pydantic.ValidationError: the model cannot be read.
    """
    from snowlight.predict import artifact  # noqa: PLC0415 - only the overrides pass needs it

    model = artifact.load() if path is None else artifact.load(path)
    return {
        district: entry.time_zone
        for district, entry in model.districts.items()
        if entry.time_zone is not None
    }


@dataclass(frozen=True, slots=True)
class DeployedSchools:
    """The deployed directory as the overrides need it: every school's id and district,
    and every district's id and time zone, in published (index) order."""

    stamp: DirectoryStamp
    content_sha256: str
    school_ids: tuple[str, ...]
    district_ids: tuple[str, ...]
    district_of: tuple[int | None, ...]
    """Each school's district index (``None``: a school without one)."""
    zones: tuple[str | None, ...]
    """Each district's time zone (``None``: not known)."""
    lon_e6: tuple[int, ...] = ()
    lat_e6: tuple[int, ...] = ()
    """Each school's place (``points.bin``; empty: not known), for a school without a zone."""

    def __post_init__(self) -> None:
        if not (
            len(self.school_ids) == len(self.district_of) == self.stamp.schools
            and len(self.district_ids) == len(self.zones) == self.stamp.districts
            and len(self.lon_e6) == len(self.lat_e6) in {0, self.stamp.schools}
        ):
            raise ValueError("the schools and districts disagree with the stamp")

    @classmethod
    def from_deployed(
        cls, directory: "DeployedDirectory", meta: SchoolDirectoryMeta, zones: Mapping[str, str]
    ) -> "DeployedSchools":
        """From the deployed directory, its ``meta.json`` and :func:`zone_table`.

        Raises:
            ValueError: they are not one directory, or it names no content digest.
        """
        if meta.stamp() != directory.stamp or tuple(meta.districts.ids) != directory.district_ids:
            raise ValueError("meta.json is not the deployed directory's")
        if directory.content_sha256 is None:
            raise ValueError("the deployed directory names no content digest")
        district_of = tuple(
            None if int(value) == NO_DISTRICT else int(value)
            for value in directory.points.district.tolist()
        )
        return cls(
            stamp=directory.stamp,
            content_sha256=directory.content_sha256,
            school_ids=tuple(meta.ids),
            district_ids=directory.district_ids,
            district_of=district_of,
            zones=tuple(zones.get(district) for district in directory.district_ids),
            lon_e6=tuple(int(value) for value in directory.points.lon_e6.tolist()),
            lat_e6=tuple(int(value) for value in directory.points.lat_e6.tolist()),
        )

    def zone_of(self, school: int) -> str | None:
        district = self.district_of[school]
        return None if district is None else self.zones[district]

    def borrowed_zones(self, wanted: Iterable[int]) -> dict[int, str]:
        """For each of ``wanted`` (schools without a zone of their own), the zone of the
        nearest school that has one (none without places, or when no school has one)."""
        needed = sorted(set(wanted))
        if not needed or not self.lon_e6:
            return {}
        zones = [self.zone_of(index) for index in range(len(self.school_ids))]
        known = np.flatnonzero(np.array([zone is not None for zone in zones], dtype=bool))
        if known.size == 0:
            return {}
        lon = np.asarray(self.lon_e6, dtype=np.float64)[known] / 1e6
        lat = np.asarray(self.lat_e6, dtype=np.float64)[known] / 1e6
        found: dict[int, str] = {}
        for school in needed:
            here_lat = self.lat_e6[school] / 1e6
            east = (lon - self.lon_e6[school] / 1e6) * np.cos(np.radians(here_lat))
            north = lat - here_lat
            nearest = zones[int(known[int(np.argmin(east * east + north * north))])]
            if nearest is not None:
                found[school] = nearest
        return found

    def live_directory(self, borrowed: Mapping[int, str] | None = None) -> LiveDirectory:
        """The publisher's view (:class:`~snowlight.live.resolve.LiveDirectory`): each
        school by id with its index and time zone (its own, or ``borrowed``), for the change
        log and day timelines."""
        borrowed = borrowed or {}
        schools: dict[str, LiveSchool] = {}
        sizes: Counter[str] = Counter()
        for index, (school_id, district) in enumerate(
            zip(self.school_ids, self.district_of, strict=True)
        ):
            district_id = None if district is None else self.district_ids[district]
            if district_id is not None:
                sizes[district_id] += 1
            zone = self.zone_of(index) or borrowed.get(index)
            schools[school_id] = LiveSchool(
                record=School(
                    id=school_id,
                    state="",
                    public=len(school_id) == 12,  # noqa: PLR2004 - an NCES public school id
                    status=None,
                    county_fips=None,
                    lat=None,
                    lon=None,
                    district_id=district_id,
                ),
                index=index,
                charter=False,
                zones=() if zone is None else (zone,),
            )
        return LiveDirectory(
            schools=schools, district_sizes=dict(sizes), edition=self.content_sha256
        )


@dataclass(frozen=True, slots=True)
class Resolved:
    """What the overrides light: one admin status per school and day, and why the rest
    light nothing (counts by code)."""

    statuses: tuple[AdminStatus, ...]
    withheld: Mapping[str, int]
    borrowed: Mapping[int, str] = field(default_factory=dict)
    """The zone each lit school without one of its own took (from
    :meth:`DeployedSchools.borrowed_zones`)."""


def _targets(
    override: Override,
    schools: dict[str, int],
    districts: dict[str, int],
    members: Mapping[int, Sequence[int]],
) -> Sequence[int]:
    """The schools an override covers (none: its id is not in the deployed directory)."""
    if override.scope == "school":
        target = schools.get(override.id)
        return () if target is None else (target,)
    district = districts.get(override.id)
    return () if district is None else members.get(district, ())


def _zone(name: str | None) -> ZoneInfo | None:
    try:
        return None if name is None else ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _school_zone(override: Override, name: str | None) -> ZoneInfo | str:
    """The school's zone (``name``) for ``override``, or why it lights nothing there: the
    zone is not known, or the admin view named the override's days in another zone (its
    "today" and "tomorrow" may then be other dates than the school's)."""
    zone = _zone(name)
    if name is None or zone is None:
        return "no_time_zone"
    if override.time_zone is not None and override.time_zone != name:
        return "zone_differs"
    return zone


def held_rows(
    shown: ClosingsFile | None, schools: DeployedSchools
) -> dict[tuple[int, date], Closing]:
    """The rows the public closings file ``shown`` holds, by school and day (none when it
    is missing or was stamped with another directory: its school indexes mean other
    schools)."""
    if shown is None or shown.directory != schools.stamp:
        return {}
    return {(row.school, row.day): row for row in shown.closings()}


def _days_lit(  # noqa: PLR0913, PLR0917 - one school's part of resolve
    override: Override,
    school: int,
    nces_id: str,
    zone: ZoneInfo,
    now: datetime,
    held: Mapping[tuple[int, date], Closing],
    published: datetime,
) -> list[AdminStatus]:
    """The statuses ``override`` lights for one school (:func:`resolve`): one for each day it
    lists that is the school's today or tomorrow, with its current status, delay and time."""
    status = STATUS_OF[override.status]
    shift = override.minutes if status is not None else None
    clock = override.clock_minute if status is not None else None
    window_first, window_last = local_days(now)
    today = now.astimezone(zone).date()
    found: list[AdminStatus] = []
    for day in override.days:
        if not (today <= day <= today + timedelta(days=1) and window_first <= day <= window_last):
            continue
        at = min(override.set_at, published)
        same = held.get((school, day))
        if (
            same is not None
            and same.manual
            and same.announced_at is not None
            and (same.status, same.shift_minutes, same.clock_minute) == (status, shift, clock)
        ):
            at = min(at, same.announced_at)  # unchanged on this day: it keeps the time first posted
        found.append(
            AdminStatus(
                school=school,
                nces_id=nces_id,
                day=day,
                status=status,
                shift_minutes=shift,
                clock_minute=clock,
                set_at=at,
                level=override.scope,
                key=override.key(),
            )
        )
    return found


def resolve(
    overrides: Sequence[Override],
    schools: DeployedSchools,
    now: datetime,
    shown: ClosingsFile | None = None,
) -> Resolved:
    """The admin statuses the overrides give at ``now`` (see the module).

    ``shown`` is the public closings file, read only for the "Posted" times: a day the
    override lights with the status, delay and time the map already shows for it as a
    manual status keeps the time that row was first posted (a re-save does not move
    "Posted"); any change on that day posts it anew. What the map shows never decides
    which days light.
    """
    held = held_rows(shown, schools)
    withheld: Counter[str] = Counter()
    school_index = {school_id: index for index, school_id in enumerate(schools.school_ids)}
    district_index = {district: index for index, district in enumerate(schools.district_ids)}
    members: dict[int, list[int]] = {}
    for index, district in enumerate(schools.district_of):
        if district is not None:
            members.setdefault(district, []).append(index)
    chosen: list[tuple[Override, Sequence[int]]] = []
    for override in overrides:
        targets = _targets(override, school_index, district_index, members)
        if override.expires_at <= now:
            withheld["expired"] += 1
        elif override.set_at > now + CLOCK_SLACK:
            withheld["set_ahead"] += 1
        elif not targets:
            withheld["not_in_directory"] += 1
        else:
            chosen.append((override, targets))
    borrowed = schools.borrowed_zones(
        school for _, targets in chosen for school in targets if schools.zone_of(school) is None
    )
    published = now.replace(microsecond=0)
    found: list[AdminStatus] = []
    lit: dict[int, str] = {}
    for override, targets in chosen:
        for school in targets:
            name = schools.zone_of(school) or borrowed.get(school)
            zone = _school_zone(override, name)
            if isinstance(zone, str):
                withheld[zone] += 1
                continue
            statuses = _days_lit(
                override, school, schools.school_ids[school], zone, now, held, published
            )
            if not statuses:
                withheld["not_today_or_tomorrow"] += 1
                continue
            if school in borrowed:
                lit[school] = borrowed[school]
            found.extend(statuses)
    return Resolved(statuses=tuple(found), withheld=dict(sorted(withheld.items())), borrowed=lit)


EMPTY: Final = Merged(
    closings=(), opens=(), provenance=(), withheld={}, breakers=(), fast_vanishes=()
)
"""No list statuses (S8-E brings the list readers)."""


def read_shown(host: Publisher, prefix: str | None) -> ClosingsFile | None:
    """The public closings file under ``prefix`` (``None``: publishing is off, the file is
    missing, or it does not validate and is published over).

    Raises:
        PublishError: it could not be read.
    """
    if prefix is None:
        return None
    data = host.read(f"{prefix}/{CLOSINGS}")
    if data is None:
        return None
    try:
        return ClosingsFile.model_validate_json(data)
    except ValidationError:
        return None


def nothing_to_publish(lit: bool, host: Publisher, prefix: str | None) -> bool:
    """Whether a pass can stop at once: nothing ``lit`` (no override, or none that lights a
    status or an open statement), and the public files (under ``prefix``; none when
    publishing is off) show no status and no open statement, or are missing.

    A public file that does not validate is published over (``False``).

    Raises:
        PublishError: a public file could not be read.
    """
    if lit:
        return False
    if prefix is None:
        return True
    closings = host.read(f"{prefix}/{CLOSINGS}")
    opens = host.read(f"{prefix}/{OPENS}")
    try:
        if closings is not None and ClosingsFile.model_validate_json(closings).days:
            return False
        if opens is not None and OpensFile.model_validate_json(opens).opens:
            return False
    except ValidationError:
        return False
    return True

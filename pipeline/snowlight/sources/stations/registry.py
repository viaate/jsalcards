"""The station registry: every closings source, one YAML file per platform.

``pipeline/config/sources/*.yaml`` are loaded together (they are the pipeline's
``sources.yaml``, split so each platform's file can change on its own). Each file
holds one platform and its stations::

    platform:
      id: gray                      # also the file name: gray.yaml
      name: ...
      operator: ...
      adapter: gray                 # the parse() of snowlight.sources.stations.<adapter>
                                    # (a dash as "_"), found from this file by
                                    # snowlight.sources.stations.adapters
      poll_minutes: 10
      terms:
        automated_access: forbidden # permitted | forbidden | unread
        summary: ...
        evidence: [{url, read_at, sha256, excerpt: [verbatim clauses]}]
        permission: null            # or {granted_by, granted_on, reference, scope}
        owner_decision: null        # or {decided_by, decided_on, reference, scope}
      notes: ...
      shared_paths: [{url, role, seen}]  # applications several stations' pages loaded
    stations:
      - id: gray-kctv               # the source id every raw row carries
        call_sign: KCTV
        name: KCTV 5
        market: Kansas City         # the market the research recorded
        dma: Kansas City, MO DMA    # the market's label in the county crosswalk
        states: [KS, MO]
        counties: {basis: dma, source: ..., fips: ["20091", ...]}
        page_url: https://www.kctv5.com/weather/closings/
        data_url: https://s3.amazonaws.com/grayfilestore-kctv/closingsData/closings_KCTV.json
        export_url: https://s3.amazonaws.com/grayfilestore-kctv/closingsData/closings_KCTV.json
                                    # the file a page's closings component loads
                                    # without naming it (Gray's GSync export), for
                                    # the archive reader; may differ from data_url
        page_check: {checked_at, page, loads: [...], shows, method}
                                    # what the page requested when opened in a
                                    # browser: data_url is the list it loads today
        archive_urls: [...]         # URL forms whose Wayback captures hold this list
        poll_minutes: null          # null: the platform's
        status: active              # active | no_endpoint
        evidence: ...               # how the endpoint and page are known
        list_files: [{url, loaded_by: frame | script | unseen, seen}]  # files the
                                    # page loaded its list from (each also in
                                    # archive_urls); unseen: no downloaded page
                                    # capture shows how, ``seen`` says why it is
                                    # the station's
        robots: [{url, checked_at, state, allowed, rule, crawl_delay, disallowed_agents}]
        leaids: ["2200030", ...]    # a district-level source only: the NCES district
                                    # IDs whose schools it covers (see below)

A district-level source (a school district's own alert page, or a state's list of
its school systems) names the districts it speaks for in ``leaids``, NCES district
IDs (LEAIDs, seven digits): it covers exactly the schools of those districts, never
a whole county (:func:`snowlight.sources.stations.coverage.district_cover`), and
its ``counties`` (basis ``district``) are the counties those schools stand in.

The live poller reads ``data_url`` when there is one, else ``page_url``.
``data_url`` is the list the station's page loads today (``page_check`` records
the browser check that shows it, made with :mod:`snowlight.sources.stations.pagecheck`;
a Gray station whose page loads no list, or which has no page of its own, is
``no_endpoint`` with the check in its evidence; the fetcher reads a list file whose
``Last-Modified`` predates the last winter as stale). A station is
polled only when its status is ``active`` and its platform's terms permit
automated access, or a written permission from the operator covers it, or the
project owner's recorded decision to read it anyway does (``owner_decision``: the
terms stay recorded here, word for word, as notes); otherwise it is skipped, and
the skip is recorded as its health. Platforms whose terms have not been read are
not polled. robots.txt does not exclude a station: the owner decided on
2026-09-26 to read closings pages and files even where it disallows them; each
URL's verdict is recorded in ``robots`` (by ``snowlight stations robots``) and in
every live read's health. Counties are five-digit county FIPS codes; ``basis`` says
where they come from (``dma``: the station's market in a published DMA county list;
``observed``: counties that appear in the station's own lists; ``state``: a
statewide list, every county of its state).
"""

import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Self

import yaml  # type: ignore[import-untyped, unused-ignore]
from pydantic import Field, StringConstraints, ValidationError, model_validator

from snowlight.output import write_bytes_atomic
from snowlight.schemas.base import InternalModel
from snowlight.schemas.internal import Sha256, SourceId
from snowlight.schemas.scalars import UtcInstant
from snowlight.sources.stations.robots import RobotsState

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_DIR = PIPELINE_ROOT / "config" / "sources"

type Url = Annotated[str, StringConstraints(pattern=r"^https?://[^\s]+$", max_length=2000)]
type HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://[^\s]+$", max_length=2000)]
type Text = Annotated[str, StringConstraints(min_length=1, max_length=4000)]
type LongText = Annotated[str, StringConstraints(min_length=1, max_length=8000)]
type Fips = Annotated[str, StringConstraints(pattern=r"^[0-9]{5}$")]
type Leaid = Annotated[str, StringConstraints(pattern=r"^[0-9]{7}$")]
"""An NCES local education agency (school district) ID, as the CCD writes it."""
type StateCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
type Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=40)]

SHORT_ITEM = 12
MIN_POLL_MINUTES = 5
MAX_POLL_MINUTES = 24 * 60
HEADER = (
    "# Station registry for one platform. Loaded with every other file in this folder\n"
    "# by snowlight.sources.stations.registry; see its docstring for the fields.\n"
    "# `snowlight stations robots --update` rewrites the robots blocks in place.\n"
)


class RegistryError(ValueError):
    """The registry files do not load or do not agree with each other."""


class AccessPolicy(StrEnum):
    """What a platform's terms say about reading it with software."""

    PERMITTED = "permitted"
    FORBIDDEN = "forbidden"
    UNREAD = "unread"


class Permission(InternalModel):
    """Written permission from the operator, which lifts a ``forbidden`` policy."""

    granted_by: Text
    granted_on: date
    reference: Text
    scope: Text


class OwnerDecision(InternalModel):
    """The project owner's decision to read a platform although its terms forbid it.

    This is not the operator's permission (see :class:`Permission`): the terms still
    forbid automated access and stay recorded. It records who decided, when, where
    the decision is written down, and what it covers. robots.txt is read and its
    verdict recorded for every URL, but it does not exclude a closings page or
    list file either (the owner's decision of 2026-09-26); an active block (a
    403, a bot challenge) is never worked around.
    """

    decided_by: Text
    decided_on: date
    reference: Text
    scope: Text


class TermsEvidence(InternalModel):
    """Where the terms were read, when, and what they say (verbatim)."""

    url: HttpsUrl
    read_at: UtcInstant
    sha256: Sha256 | None
    excerpt: tuple[Text, ...]


class Terms(InternalModel):
    """A platform's terms of use as they bear on automated reading."""

    automated_access: AccessPolicy
    summary: Text
    evidence: tuple[TermsEvidence, ...]
    permission: Permission | None = None
    owner_decision: OwnerDecision | None = None

    @property
    def pollable(self) -> bool:
        """Whether live polling may proceed as far as the terms go.

        True when the terms permit it, or when they forbid it and either the
        operator's written permission or the project owner's decision is recorded.
        Terms not yet read are never pollable.
        """
        if self.automated_access is AccessPolicy.PERMITTED:
            return True
        return self.automated_access is AccessPolicy.FORBIDDEN and (
            self.permission is not None or self.owner_decision is not None
        )

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.automated_access is not AccessPolicy.UNREAD and not self.evidence:
            raise ValueError("terms marked as read need evidence of where they were read")
        if self.permission is not None and self.automated_access is AccessPolicy.PERMITTED:
            raise ValueError("permission is only recorded against forbidding terms")
        if self.owner_decision is not None and self.automated_access is not AccessPolicy.FORBIDDEN:
            raise ValueError("an owner's decision is only recorded against forbidding terms")
        return self


class SharedPath(InternalModel):
    """Files under one address that several stations' pages loaded, none a list itself.

    For example the script application a frame showed, which then read the
    station's own list file. Archived captures under ``url`` (its host and path, as
    a prefix; query and fragment ignored) were downloaded as evidence of what the
    pages loaded; the archive reader sets them aside instead of reading them as a
    station's list.
    """

    url: Url
    role: Text
    seen: Text


class Platform(InternalModel):
    """One closings system that several stations share."""

    id: Slug
    name: Text
    operator: Text
    adapter: Slug
    poll_minutes: Annotated[int, Field(ge=MIN_POLL_MINUTES, le=MAX_POLL_MINUTES)]
    terms: Terms
    notes: LongText
    shared_paths: tuple[SharedPath, ...] = ()


class CountyBasis(StrEnum):
    """Where a station's county list comes from."""

    DMA = "dma"
    OBSERVED = "observed"
    DISTRICT = "district"
    """A district-level source (``Station.leaids``): the counties its districts'
    schools stand in, in the NCES school directory. Only those schools count."""
    STATE = "state"
    """A statewide list (a state agency's, or one arranged by every county of a state):
    every county of its state in the Census county Gazetteer."""


class Counties(InternalModel):
    """The counties a station's list covers, and the basis for saying so."""

    basis: CountyBasis
    source: Text
    fips: tuple[Fips, ...]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if list(self.fips) != sorted(set(self.fips)):
            raise ValueError("county FIPS codes are listed once each, in order")
        if not self.fips:
            raise ValueError("a county list names at least one county")
        return self


class RobotsCheck(InternalModel):
    """One robots.txt decision for one URL a station uses."""

    url: Url
    checked_at: UtcInstant
    state: RobotsState
    allowed: bool
    rule: Text
    crawl_delay: Annotated[float, Field(ge=0)] | None
    disallowed_agents: tuple[str, ...]
    sha256: Sha256 | None


class ListFile(InternalModel):
    """A file on another host that a station's closings page framed or loaded its list from.

    Such a file is the station's list for as long as the page loaded it, so its
    URL is also one of the station's ``archive_urls``; ``seen`` records the page
    capture that shows the page loading it. ``loaded_by`` is ``unseen`` for a file
    no downloaded page capture names: then ``seen`` gives the evidence that the
    file is the station's list (where it is kept, and what its rows show).
    """

    url: Url
    loaded_by: Annotated[str, StringConstraints(pattern=r"^(frame|script|unseen)$")]
    seen: Text


class PageCheck(InternalModel):
    """What a station's closings page requested when it was opened in a browser.

    ``loads`` lists the list files the page framed or fetched (without the
    cache-busting query a page adds), so ``data_url`` can be checked against what
    the page shows. ``shows`` is a short excerpt of what the page displayed.
    """

    checked_at: UtcInstant
    page: Url
    loads: tuple[Url, ...]
    shows: Text
    method: Text


class StationStatus(StrEnum):
    """Whether a station has an endpoint to read."""

    ACTIVE = "active"
    NO_ENDPOINT = "no_endpoint"


class Station(InternalModel):
    """One source: a station's closings list."""

    id: SourceId
    platform: Slug
    call_sign: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{2,8}(?:-[A-Z0-9]{1,3})?$")]
    name: Text
    market: Text
    dma: Text | None
    states: tuple[StateCode, ...]
    counties: Counties | None
    page_url: Url | None
    data_url: Url | None
    export_url: Url | None = None
    archive_urls: tuple[Url, ...]
    poll_minutes: Annotated[int, Field(ge=MIN_POLL_MINUTES, le=MAX_POLL_MINUTES)] | None
    status: StationStatus
    evidence: Text
    list_files: tuple[ListFile, ...] = ()
    page_check: PageCheck | None = None
    robots: tuple[RobotsCheck, ...] = ()
    leaids: tuple[Leaid, ...] = Field(
        default=(),
        description=(
            "A district-level source's NCES district IDs: it covers exactly those "
            "districts' schools, not its counties whole (empty for every other source)."
        ),
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        missing = [f.url for f in self.list_files if f.url not in self.archive_urls]
        if missing:
            raise ValueError(f"{self.id}: list files are archive URLs too: {missing}")
        if self.export_url is not None and self.export_url not in self.archive_urls:
            raise ValueError(f"{self.id}: the export URL is an archive URL too")
        check = self.page_check
        if check is not None and self.data_url is not None and self.data_url not in check.loads:
            raise ValueError(f"{self.id}: data_url is not among the files its page loads")
        if not self.id.startswith(f"{self.platform}-"):
            raise ValueError(f"station id {self.id!r} starts with its platform id")
        if self.status is StationStatus.ACTIVE and self.poll_url is None:
            raise ValueError(f"{self.id}: an active station needs a page or data URL")
        if self.status is StationStatus.NO_ENDPOINT and (self.data_url or self.page_url):
            raise ValueError(f"{self.id}: a station with no endpoint lists no URL")
        if list(self.states) != sorted(set(self.states)) or not self.states:
            raise ValueError(f"{self.id}: states are listed once each, in order")
        if list(self.leaids) != sorted(set(self.leaids)):
            raise ValueError(f"{self.id}: LEAIDs are listed once each, in order")
        district = self.counties is not None and self.counties.basis is CountyBasis.DISTRICT
        if bool(self.leaids) != district:
            raise ValueError(
                f"{self.id}: a district-level source names its LEAIDs, and only its "
                "counties have the district basis"
            )
        return self

    @property
    def poll_url(self) -> str | None:
        """The URL the live poller reads: the data endpoint when there is one."""
        return self.data_url or self.page_url

    @property
    def export(self) -> str | None:
        """The list file the station's pages load without naming it in the page.

        Gray's Arc pages build the address of the station's GSync export in script,
        so a count-only or lazy page is followed to this file: ``export_url`` when
        the registry names it, else ``data_url``.
        """
        return self.export_url or self.data_url


class PlatformFile(InternalModel):
    """The contents of one ``<platform>.yaml``."""

    platform: Platform
    stations: tuple[Station, ...]


class Registry:
    """Every platform and station, loaded from one folder."""

    def __init__(self, files: Mapping[str, PlatformFile]) -> None:
        self.files = dict(files)
        self.platforms: dict[str, Platform] = {}
        self.stations: dict[str, Station] = {}
        for name, loaded in self.files.items():
            platform = loaded.platform
            if platform.id != name:
                raise RegistryError(f"{name}.yaml holds platform {platform.id!r}")
            self.platforms[platform.id] = platform
            for station in loaded.stations:
                if station.platform != platform.id:
                    raise RegistryError(f"{station.id} is filed under {platform.id}")
                if station.id in self.stations:
                    raise RegistryError(f"station id {station.id!r} is used twice")
                self.stations[station.id] = station

    def platform_of(self, station: Station) -> Platform:
        """Return the platform ``station`` belongs to."""
        return self.platforms[station.platform]

    def poll_minutes(self, station: Station) -> int:
        """Return how often ``station`` is polled, in minutes."""
        return station.poll_minutes or self.platform_of(station).poll_minutes

    def active(self) -> list[Station]:
        """Return the stations with an endpoint, in id order."""
        return sorted(
            (s for s in self.stations.values() if s.status is StationStatus.ACTIVE),
            key=lambda s: s.id,
        )

    def check_adapters(self, known: Iterable[str]) -> None:
        """Raise if a platform names an adapter that does not exist."""
        names = set(known)
        for platform in self.platforms.values():
            if platform.adapter not in names:
                raise RegistryError(f"platform {platform.id} names unknown adapter")


def _json_value(value: object) -> str:
    # YAML turns unquoted dates and times into objects; the models read text.
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"not a registry value: {value!r}")


def _load_yaml(path: Path) -> str:
    """Return the YAML file's content as JSON text, for strict validation."""
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RegistryError(f"{path.name}: {error}") from error
    return json.dumps(data, default=_json_value)


def load_registry(folder: Path = DEFAULT_REGISTRY_DIR) -> Registry:
    """Load and cross-check every ``*.yaml`` file in ``folder``."""
    files: dict[str, PlatformFile] = {}
    paths = sorted(folder.glob("*.yaml"))
    if not paths:
        raise RegistryError(f"no registry files in {folder}")
    for path in paths:
        if not re.fullmatch(r"[a-z0-9-]+\.yaml", path.name):
            raise RegistryError(f"{path.name}: registry files are named <platform>.yaml")
        try:
            files[path.stem] = PlatformFile.model_validate_json(_load_yaml(path))
        except ValidationError as error:
            raise RegistryError(f"{path.name}: {error}") from error
    return Registry(files)


class _Dumper(yaml.SafeDumper):  # type: ignore[misc]
    pass


def _str_representer(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


def _list_representer(dumper: yaml.SafeDumper, value: list[object]) -> yaml.Node:
    # Lists of short codes (county FIPS, state abbreviations) are written on one wrapped
    # line; everything else one item per line.
    short = all(isinstance(item, str) and len(item) <= SHORT_ITEM for item in value)
    return dumper.represent_sequence(
        "tag:yaml.org,2002:seq", value, flow_style=short and bool(value)
    )


_Dumper.add_representer(str, _str_representer)
_Dumper.add_representer(list, _list_representer)


def dump_platform_file(content: PlatformFile) -> bytes:
    """Serialize a platform file deterministically (fields in model order)."""
    data = content.model_dump(mode="json")
    for station in data["stations"]:
        if not station.get("leaids"):
            station.pop("leaids", None)  # only a district-level source names LEAIDs
    text: str = yaml.dump(
        data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100, indent=2
    )
    return (HEADER + text).encode("utf-8")


def write_platform_file(folder: Path, content: PlatformFile) -> Path:
    """Write ``content`` to ``<folder>/<platform id>.yaml`` atomically."""
    path = folder / f"{content.platform.id}.yaml"
    write_bytes_atomic(path, dump_platform_file(content))
    return path

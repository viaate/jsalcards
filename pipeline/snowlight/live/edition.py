"""The ingest's directory handshake (spec 8, step 4): publish only against the deployed directory.

The live file's school indexes are positions in the deployed ``meta.json``, so the
ingest publishes only while the directory it indexes into (its own build's
``schools/edition.json``) has the same content as the one the site serves. It then
stamps the file with the *deployed* stamp: the ingest never has to reproduce the
date (the stamp's date is an identifier, never compared with today).

:class:`EditionWatch` runs at start and before every publish:

* **Equal content** (the deployed ``content_sha256``, school and district counts
  equal its own): publish with the deployed stamp.
* **Different content**: refuse (G12a) and alert. When the deployed stamp is a stamp
  a public file carries (``published``: the stamp read back from the host, and the one
  this process remembers; a same-day content change: the date did not move), or when
  the public files could not all be read back, first publish a blank file with that
  stamp at once (:attr:`EditionVerdict.blank`; a blank skips any file under another
  stamp), so a page that loaded the new ``meta.json`` cannot light old indexes from the
  last file. The caller then exits; its successor starts on the new directory.
* **No edition deployed**: refuse; nothing deployed can be indexed against.
* **The read failed** (an API error, a CDN copy not yet provably current, or a new
  deployment still in progress, while the one before it is still the one served):
  keep the last good verdict for up to :data:`GRACE` (30 min) after it was made, then
  refuse and alert. A routine redeploy is in progress for tens of seconds: nothing
  goes dark for it.
  A **new deployment that has settled and whose edition cannot be read** keeps
  nothing: its content may have changed under the same stamp, so the verdict is
  ``unreadable``, the caller alerts, and every public file is blanked under its own
  stamp (:class:`UnverifiedDeployError`, :attr:`EditionVerdict.blank_every`).

The deployed edition is read through :mod:`snowlight.directory.deployed` (S8-0), never
with a plain GET: the CDN in front of Pages ignores cache-busting queries. Reading it
downloads the live deploy's artifact, so :class:`PagesDeployed` reads it again only when
the newest ``github-pages`` deployment changed (one API call per check otherwise).

The zone table must index into the same edition (:func:`check_zones`).
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol

from pydantic import ValidationError

from snowlight.directory.deployed import (
    DeployedEdition,
    DeployedEditionError,
    DeployInProgressError,
    EditionMismatchError,
    LiveDeployment,
    Reader,
)
from snowlight.schemas.directory import DirectoryEdition, DirectoryStamp

GRACE: Final = timedelta(minutes=30)
"""How long a good verdict stands while the deployed edition cannot be read."""


class EditionState(StrEnum):
    """What the handshake found."""

    EQUAL = "equal"
    """The deployed directory has this build's content."""
    KEPT = "kept"
    """The read failed; the last equal verdict, within :data:`GRACE`, stands."""
    DIFFERENT = "different"
    """The deployed directory has other content."""
    NONE_DEPLOYED = "none_deployed"
    UNREADABLE = "unreadable"
    """The read failed with no equal verdict within :data:`GRACE`."""


@dataclass(frozen=True, slots=True)
class EditionVerdict:
    """One handshake's verdict."""

    state: EditionState
    checked_at: datetime
    """When the verdict was made (a kept verdict keeps its own time)."""
    stamp: DirectoryStamp | None = None
    """The deployed stamp to publish with (``equal`` and ``kept`` only)."""
    blank: DirectoryStamp | None = None
    """Publish a blank file with this stamp at once: a public file carries it, and the
    content behind it changed (``different``) or a new deployment cannot be read
    (``unreadable``)."""
    deployed: DirectoryStamp | None = None
    """The deployed directory's stamp, when it was read."""
    note: str = ""
    """Why a read failed (an error's first line; no content)."""
    blank_every: bool = False
    """Publish a blank in place of every public file, each under its own stamp (a new
    deployment cannot be read: its stamp is unknown)."""
    alert: bool = False
    """Raise the alert: other content is deployed, a new deployment cannot be read, or
    an equal verdict could not be renewed within :data:`GRACE`."""

    @property
    def wants_blank(self) -> bool:
        return self.blank is not None or self.blank_every

    @property
    def ok(self) -> bool:
        """Whether the gate's edition check (G12a) passes."""
        return self.state in {EditionState.EQUAL, EditionState.KEPT} and self.stamp is not None


class DeployedSource(Protocol):
    """Reads the edition the site serves (:class:`snowlight.directory.deployed.Reader`)."""

    def read(self) -> DeployedEdition: ...


class UnverifiedDeployError(DeployedEditionError):
    """A deployment newer than the one the last verdict was read from has settled and cannot
    be read: what it serves is unknown, so no earlier verdict may stand for it."""


@dataclass(slots=True)
class PagesDeployed:
    """The deployed edition, read again only when the newest Pages deployment changes."""

    reader: Reader
    _seen: LiveDeployment | None = None
    _edition: DeployedEdition | None = None

    def read(self) -> DeployedEdition:
        """Raises :class:`DeployedEditionError` when it cannot be known for certain, and
        :class:`UnverifiedDeployError` when that is a settled new deployment's edition (a
        deployment still in progress raises :class:`DeployInProgressError`: the one before
        it is still served)."""
        newest = self.reader.newest_deployment()
        if newest is not None and newest == self._seen and self._edition is not None:
            return self._edition
        try:
            edition = self.reader.read()
        except DeployInProgressError:
            raise
        except DeployedEditionError as error:
            if self._edition is not None and newest != self._seen:
                raise UnverifiedDeployError(f"a new deployment: {error}") from error
            raise
        self._seen, self._edition = newest, edition
        return edition


def deployed_edition(source: DeployedSource) -> DirectoryEdition | None:
    """The deployed directory's edition, or ``None`` when none is deployed.

    Raises:
        DeployedEditionError: it cannot be known for certain.
    """
    try:
        found = source.read()
    except EditionMismatchError as error:
        # The deployed edition.json names another directory than the meta.json the
        # site serves beside it: the page reads that meta.json, so it is the one.
        return error.made
    if found.data is None:
        return None
    try:
        return DirectoryEdition.from_json_bytes(found.data)
    except (ValidationError, ValueError) as error:
        raise DeployedEditionError("the deployed edition.json is not an edition") from error


def own_edition(site_data: Path) -> DirectoryEdition:
    """This build's edition: ``<site_data>/schools/edition.json`` as the build wrote it.

    Raises:
        OSError: the file cannot be read.
        pydantic.ValidationError: it is not an edition.
    """
    return DirectoryEdition.from_json_bytes((site_data / "schools" / "edition.json").read_bytes())


def check_zones(own: DirectoryEdition, zones: DirectoryEdition) -> None:
    """Refuse a zone table made for another directory than this build's.

    Raises:
        ValueError: the zone table names another edition.
    """
    if zones != own:
        raise ValueError("the zone table indexes another directory edition than this build's")


def _first_line(error: BaseException) -> str:
    text = str(error).strip().splitlines()
    return f"{type(error).__name__}: {text[0] if text else ''}"[:200]


@dataclass(slots=True)
class EditionWatch:
    """Checks this build's edition against the deployed one (see the module)."""

    own: DirectoryEdition
    source: DeployedSource
    grace: timedelta = GRACE
    last: EditionVerdict | None = None
    """The last verdict made from a read (never a kept one)."""
    log: Callable[[str], None] = field(default=lambda _line: None)

    def check(
        self,
        now: datetime,
        *,
        published: Collection[DirectoryStamp],
        complete: bool = True,
    ) -> EditionVerdict:
        """The verdict at ``now``; ``published`` holds the stamps a public file carries (read
        back from the host, and remembered); ``complete`` is false when a public file could
        not be read back (other content then blanks under the deployed stamp anyway)."""
        try:
            deployed = deployed_edition(self.source)
        except UnverifiedDeployError as error:
            self.last = None  # nothing read before a new deployment stands for it
            self.log("edition: unreadable (a new deployment)")
            return EditionVerdict(
                EditionState.UNREADABLE,
                now,
                blank_every=True,
                alert=True,
                note=_first_line(error),
            )
        except DeployedEditionError as error:
            return self._unreadable(now, _first_line(error))
        if deployed is None:
            verdict = EditionVerdict(EditionState.NONE_DEPLOYED, now)
        elif self._same(deployed):
            verdict = EditionVerdict(
                EditionState.EQUAL, now, stamp=deployed.stamp(), deployed=deployed.stamp()
            )
        else:
            stamp = deployed.stamp()
            verdict = EditionVerdict(
                EditionState.DIFFERENT,
                now,
                blank=stamp if stamp in published or not complete else None,
                deployed=stamp,
                alert=True,
            )
        self.last = verdict
        self.log(f"edition: {verdict.state}")
        return verdict

    def _same(self, deployed: DirectoryEdition) -> bool:
        return (
            deployed.content_sha256 == self.own.content_sha256
            and deployed.schools == self.own.schools
            and deployed.districts == self.own.districts
        )

    def _unreadable(self, now: datetime, note: str) -> EditionVerdict:
        last = self.last
        if (
            last is not None
            and last.state is EditionState.EQUAL
            and timedelta(0) <= now - last.checked_at <= self.grace
        ):
            self.log("edition: kept (the deployed edition could not be read)")
            return replace(last, state=EditionState.KEPT, note=note)
        self.log("edition: unreadable")
        expired = last is not None and last.state is EditionState.EQUAL
        return EditionVerdict(EditionState.UNREADABLE, now, note=note, alert=expired)

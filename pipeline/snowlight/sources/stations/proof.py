"""Proven coverage: stations whose list has been seen populated at least once.

A list that answers but has never been seen holding a row may not be one anyone
uses (Utah counted as covered only through a page that was empty whenever it
was read). The *proven* share counts a working station only when a read of its
list held at least one row: live, in an archived Wayback capture, or in a
committed test fixture (a real live or archived body; its provenance is in the
fixture folder's ``PROVENANCE.json``; or a post of the channel's own dated history,
read live and kept as a fixture of mode ``history``, whose time is the post's own: see
:mod:`snowlight.sources.stations.history`). The evidence per station is the read with
the most rows among those of its current list, else among all its reads:

* ``current`` is true when the read is of the list the station's registry entry
  reads today: the read's URL (or a page it was reached through) is the station's
  ``page_url`` or ``data_url`` (compared with :func:`~snowlight.sources.stations.archive.url_key`,
  so ``?_renderer=json`` or ``wp-json`` forms of the same page do not count as the
  same address unless registered).
* ``address`` says which of the station's addresses the read is of: ``current``
  (as above), ``former`` (one of the registry's ``former_urls``: the station's own
  list at the address it had before it moved, with the evidence of the move
  recorded there) or ``earlier`` (any other archive URL: another vendor's file a
  page once framed, say).
* ``proves`` is true for a read of the current or a former address. Only such a
  proof makes a station proven; an earlier list file seen populated (a
  Tribune-era frame, say) is kept as evidence but does not.

Why a former address proves the station (decided 2026-10-04, for the coverage
gate): the proven share asks whether the outlet's closings channel is used at all,
since a list never seen holding a row may be one nobody fills. A station that
moved its own list (Scripps moved KPAX's closings module from
``/weather/school-closings-delays`` to ``/school-closings-delays``; Alachua
County Public Schools moved its homepage from sbac.edu, which now redirects to
alachuaschools.net) still runs the same channel, so the old address seen holding
rows answers that question. The same holds for a capture of the current address
in an earlier form of the page (a district homepage's older slider, read by the
station's own adapter). A district's alert channel still needs a row announcing
a closing (:mod:`snowlight.sources.stations.notices`), at either address.
* ``shared``: a station whose list file is the same file another station reads
  (the registry's ``data_url``, else its ``page_url``, compared with ``url_key``)
  is proven by that station's proof when it has none of its own (decided
  2026-10-05, for the coverage gate): the file is one list, shown on several
  stations' sites, and the question is whether the list is used. Cowles' five
  Montana stations (KULR Billings, KFBB Great Falls, KTMF Missoula, KWYB Butte -
  Bozeman, KHBB Helena) all frame one statewide file today
  (``KULR_School_Results/closings.html``, "School Closures Around Montana"); KULR's
  ``/schoolclosures/`` page, in its 2019 form, listed that system's "Statewide school
  delays and closures" for March 4, 2019 (Amsterdam, Belgrade and Bozeman in the
  Butte - Bozeman market, Seeley Swan in Missoula's, Geyser in Great Falls',
  Rossiter in Helena's, and Billings' schools). Gray's satellite stations read their
  parent's file (KTRE reads KLTV's, KSNB reads KOLN's). The proof is recorded with
  ``address`` ``shared``, ``shared_with`` (the station whose read it is) and
  ``shared_list`` (the file), ``current`` false.
* ``capture_url`` is the Wayback link of an archived read
  (``https://web.archive.org/web/<timestamp>/<url>``); a live read has none.

For each working station without such a proof, ``checked`` says what was looked
at: its live reads, the archived captures read (with their states) and those
that failed (with the reason, such as a capture the archive answered 403 for or
never downloaded), and the fixtures that hold its bodies.

Written into ``coverage.json`` (internal, never published) by
:func:`add_proven`::

    "proven": {"national": Share, "states": {"AL": Share, ...},
               "counties": {fips: {"schools", "covered", "proven": [id, ...],
                                   "proven_districts": [id, ...]}},
               "stations": {"working": n, "proven": n, "unproven": n, "shared": n},
               "evidence": {"archive_reads": {"path", "sha256", "reads"} | null,
                            "archive_health": {...} | null, "live_reads": {...} | null,
                            "fixtures": [{"path", "sha256", "entries"}, ...]}},
    "unproven": [{"id", "checked": {...}}, ...],
    "stations": {id: {..., "proof": null | {"mode", "url", "capture_url", "captured_at",
                                            "rows", "sha256", "variant", "basis",
                                            "current", "address", "proves",
                                            "shared_with"?, "shared_list"?}}}

(``Share`` as in :mod:`~snowlight.sources.stations.coverage`, with its ``weighted``
part when closure weights are given.)
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import polars as pl
from pydantic import TypeAdapter, ValidationError

from snowlight.output import JSONValue
from snowlight.sources.stations.archive import url_key
from snowlight.sources.stations.coverage import (
    CoverageError,
    StationState,
    Weights,
    measure,
    without_counties,
)
from snowlight.sources.stations.fixtures import FixtureEntry
from snowlight.sources.stations.http import iso_utc
from snowlight.sources.stations.model import (
    ListingRead,
    ListingState,
    ReadMode,
    SourceHealth,
)
from snowlight.sources.stations.registry import Registry, Station

WAYBACK = "https://web.archive.org/web/"
PROVENANCE_FILE = "PROVENANCE.json"
CHECKED_LIMIT = 40
"""At most this many reads of each kind are listed in ``checked`` (the counts are complete)."""


class ProofError(ValueError):
    """An evidence file does not have the shape its writer gives it."""


@dataclass(frozen=True, slots=True)
class Proof:
    """One read of a station's list that held rows."""

    source_id: str
    mode: str
    url: str
    captured_at: datetime
    rows: int
    sha256: str
    variant: str
    basis: str
    """Where the read is recorded: ``live reads``, ``archive reads`` or ``fixture <file>``."""
    via: tuple[str, ...] = ()

    @property
    def capture_url(self) -> str | None:
        """The Wayback link of an archived read."""
        if self.mode != ReadMode.ARCHIVE.value:
            return None
        return f"{WAYBACK}{self.captured_at:%Y%m%d%H%M%S}/{self.url}"

    def current(self, station: Station) -> bool:
        """Whether this is a read of the list the station's entry reads today.

        A read of a channel's dated history (``history``) is of a page of the feed or a
        window of the posts the station's entry reads (``?page_no=11``, ``&after=...``): it
        is compared without the parameters that page or window a list (:data:`PAGING`),
        but with every one that says which list it is (a search, a category), so another
        search of the same endpoint is not the station's list.
        """
        own = {url_key(url) for url in (station.page_url, station.data_url) if url}
        if self.mode == ReadMode.HISTORY.value:
            own = {_list_key(url) for url in (station.page_url, station.data_url) if url}
            return _list_key(self.url) in own
        return any(url_key(url) in own for url in (self.url, *self.via))

    def former(self, station: Station) -> bool:
        """Whether this is a read of one of the station's own former addresses."""
        own = {url_key(item.url) for item in station.former_urls}
        return any(url_key(url) in own for url in (self.url, *self.via))

    def address(self, station: Station) -> str:
        """``current``, ``former`` or ``earlier`` (see the module docstring)."""
        if self.current(station):
            return "current"
        return "former" if self.former(station) else "earlier"

    def proves(self, station: Station) -> bool:
        """Whether this read proves the station: of its current or a former address."""
        return self.address(station) != "earlier"

    def as_json(self, station: Station) -> dict[str, JSONValue]:
        """The evidence as ``coverage.json`` records it."""
        return {
            "mode": self.mode,
            "url": self.url,
            "capture_url": self.capture_url,
            "captured_at": iso_utc(self.captured_at),
            "rows": self.rows,
            "sha256": self.sha256,
            "variant": self.variant,
            "basis": self.basis,
            "current": self.current(station),
            "address": self.address(station),
            "proves": self.proves(station),
        }


PAGING = frozenset(
    {"page", "page_no", "per_page", "offset", "after", "before", "order", "orderby", "_fields"}
)
"""Query parameters that page, window, order or trim a list's answer without changing
which list it is (a REST list's ``page`` and ``after``, an Apptegy feed's ``page_no``)."""


def _list_key(url: str) -> str:
    """A URL's key (:func:`url_key`, which keeps no query) with the parameters that say
    which list it is, every one but :data:`PAGING`, sorted."""
    kept = sorted(
        (name.lower(), value)
        for name, value in parse_qsl(urlsplit(url).query, keep_blank_values=True)
        if name.lower() not in PAGING
    )
    query = "&".join(f"{name}={value}" for name, value in kept)
    base = url_key(urlsplit(url)._replace(query="", fragment="").geturl())
    return f"{base}?{query}" if query else base


@dataclass(slots=True)
class Evidence:
    """Every populated read, and what else was checked, per station."""

    proofs: dict[str, list[Proof]] = field(default_factory=lambda: defaultdict(list))
    checked: dict[str, dict[str, list[dict[str, JSONValue]]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(list))
    )
    files: dict[str, JSONValue] = field(default_factory=dict)
    chosen: dict[str, Proof] = field(default_factory=dict)
    """A gated station's proof to record, as the notice gate chose it
    (:func:`snowlight.sources.stations.notices.gate_proofs`): its earliest proof whose row
    names weather or an emergency."""

    def best(self, station: Station) -> Proof | None:
        """The proof with the most rows, of the current address, else a former one, else any.

        A gated station's proof is the one the notice gate chose (:attr:`chosen`) when it is
        of the address the rule would take (current, else former)."""
        found = self.proofs.get(station.id, [])
        if not found:
            return None
        current = [proof for proof in found if proof.current(station)]
        former = [proof for proof in found if proof.former(station)]
        pool = current or former or found
        picked = self.chosen.get(station.id)
        if picked is not None and picked in pool:
            return picked
        return max(pool, key=lambda proof: (proof.rows, proof.captured_at))


_READS = TypeAdapter(ListingRead)
_ENTRIES = TypeAdapter(list[FixtureEntry])


def _record(path: Path, count: int) -> dict[str, JSONValue]:
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "entries": count,
    }


def read_reads(path: Path) -> list[ListingRead]:
    """Read a ``reads.jsonl`` written by ``stations fetch`` or ``stations archive parse``."""
    reads = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            reads.append(_READS.validate_json(line))
        except ValidationError as error:
            raise ProofError(f"{path}:{number}: {error}") from error
    return reads


def read_health(path: Path) -> list[SourceHealth]:
    """Read the sources of a ``health.json``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [SourceHealth.model_validate_json(json.dumps(item)) for item in data["sources"]]
    except (ValueError, KeyError, TypeError) as error:
        raise ProofError(f"{path}: {error}") from error


def fixture_entries(root: Path) -> list[tuple[Path, list[FixtureEntry]]]:
    """Every fixture provenance file under ``root`` that lists fixture entries."""
    found = []
    for path in sorted(root.rglob(PROVENANCE_FILE)):
        data = json.loads(path.read_text(encoding="utf-8"))
        # Reference files (DMA lists, robots.txt) keep other provenance records.
        if not isinstance(data, list) or not all(
            isinstance(item, dict) and "expected" in item for item in data
        ):
            continue
        try:
            found.append((path, _ENTRIES.validate_json(path.read_bytes())))
        except ValidationError as error:
            raise ProofError(f"{path}: {error}") from error
    return found


def _add_reads(evidence: Evidence, reads: Iterable[ListingRead], basis: str) -> None:
    for read in reads:
        kind = "live" if read.mode is ReadMode.LIVE else "archived"
        if read.state is ListingState.POPULATED and read.rows > 0:
            evidence.proofs[read.source_id].append(
                Proof(
                    source_id=read.source_id,
                    mode=read.mode.value,
                    url=read.url,
                    captured_at=read.fetched_at,
                    rows=read.rows,
                    sha256=read.sha256,
                    variant=read.variant,
                    basis=basis,
                    via=tuple(page.url for page in read.via),
                )
            )
        evidence.checked[read.source_id][kind].append(
            {"captured_at": iso_utc(read.fetched_at), "url": read.url, "state": read.state.value}
        )


def _add_failures(evidence: Evidence, health: Iterable[SourceHealth]) -> None:
    for entry in health:
        if entry.status.value in {"ok", "empty"}:
            continue
        evidence.checked[entry.source_id]["archive_failures"].append(
            {"captured_at": iso_utc(entry.checked_at), "url": entry.url, "reason": entry.reason}
        )


def _add_fixtures(
    evidence: Evidence, root: Path, folders: Sequence[tuple[Path, list[FixtureEntry]]]
) -> None:
    for path, entries in folders:
        for entry in entries:
            evidence.checked[entry.source_id]["fixtures"].append(
                {
                    "file": entry.file,
                    "state": entry.expected.state.value,
                    "rows": entry.expected.rows,
                }
            )
            if entry.expected.state is not ListingState.POPULATED or entry.expected.rows == 0:
                continue
            evidence.proofs[entry.source_id].append(
                Proof(
                    source_id=entry.source_id,
                    mode=entry.mode.value,
                    url=entry.url,
                    captured_at=entry.captured_at,
                    rows=entry.expected.rows,
                    sha256=entry.original_sha256,
                    variant=entry.expected.variant,
                    basis=f"fixture {path.parent.relative_to(root).as_posix() or '.'}/{entry.file}",
                )
            )


def gather(
    *,
    live_reads: Path | None,
    archive_reads: Path | None,
    archive_health: Path | None,
    fixtures: Path | None,
) -> Evidence:
    """Collect the evidence from whichever of the files exist."""
    evidence = Evidence()
    for key, path, basis in (
        ("live_reads", live_reads, "live reads"),
        ("archive_reads", archive_reads, "archive reads"),
    ):
        if path is not None and path.is_file():
            reads = read_reads(path)
            _add_reads(evidence, reads, basis)
            evidence.files[key] = _record(path, len(reads))
        else:
            evidence.files[key] = None
    if archive_health is not None and archive_health.is_file():
        health = read_health(archive_health)
        _add_failures(evidence, health)
        evidence.files["archive_health"] = _record(archive_health, len(health))
    else:
        evidence.files["archive_health"] = None
    folders = fixture_entries(fixtures) if fixtures is not None and fixtures.is_dir() else []
    if fixtures is not None:
        _add_fixtures(evidence, fixtures, folders)
    evidence.files["fixtures"] = [_record(path, len(entries)) for path, entries in folders]
    return evidence


def _checked(evidence: Evidence, station_id: str) -> dict[str, JSONValue]:
    found = evidence.checked.get(station_id, {})
    summary: dict[str, JSONValue] = {}
    for kind in ("live", "archived", "archive_failures", "fixtures"):
        items = found.get(kind, [])
        summary[kind] = {"count": len(items), "items": list(items[:CHECKED_LIMIT])}
    return summary


def list_file(station: Station) -> str | None:
    """The URL key of the file a station's list is read from: its data file, else its page."""
    url = station.data_url or station.page_url
    return url_key(url) if url else None


def shared_proofs(
    registry: Registry,
    states: Mapping[str, StationState],
    bests: Mapping[str, Proof | None],
) -> dict[str, tuple[Station, Proof]]:
    """Each working station with no proof of its own that reads a proven station's list file.

    Maps the station's id to the proven station (the first by id among those
    reading the same file) and its proof (see ``shared`` in the module docstring).
    """
    proven_by_file: dict[str, tuple[Station, Proof]] = {}
    for station in sorted(registry.stations.values(), key=lambda item: item.id):
        best = bests.get(station.id)
        key = list_file(station)
        if key is None or best is None or not best.proves(station):
            continue
        if states[station.id].state == "working":
            proven_by_file.setdefault(key, (station, best))
    found: dict[str, tuple[Station, Proof]] = {}
    for station in sorted(registry.stations.values(), key=lambda item: item.id):
        best = bests.get(station.id)
        if states[station.id].state != "working" or (best is not None and best.proves(station)):
            continue
        key = list_file(station)
        other = proven_by_file.get(key) if key is not None else None
        if other is not None and other[0].id != station.id:
            found[station.id] = other
    return found


def _shared_json(owner: Station, best: Proof) -> dict[str, JSONValue]:
    found = best.as_json(owner)
    found.update(
        current=False,
        address="shared",
        proves=True,
        shared_with=owner.id,
        shared_list=owner.data_url or owner.page_url,
    )
    return found


def add_proven(  # noqa: PLR0913 - the measure's own inputs, and the evidence
    result: dict[str, JSONValue],
    registry: Registry,
    schools: pl.DataFrame,
    states: Mapping[str, StationState],
    evidence: Evidence,
    *,
    weights: Weights | None = None,
    assumed: Mapping[str, list[str]] | None = None,
    pandemic_only: Iterable[str] | None = None,
) -> None:
    """Add the proven share, each station's evidence and the unproven list to ``result``.

    The proven share is the coverage measure again, counting only the working
    stations with a proof of their list (at its current or a former address, or
    the proof of another station reading the same list file).

    With ``assumed`` (:func:`snowlight.sources.stations.coverage.market_assumptions`: each
    station's counties over a state line that only its market credits it with), the proven
    measure is taken once more without them, as ``proven.market_checked``: the share that
    rests on rows seen, not on a market's map alone. With ``pandemic_only``
    (:func:`snowlight.sources.stations.notices.pandemic_only_lists`: proven lists never seen
    holding a closing but the pandemic's), it is taken once more without those lists, as
    ``proven.pandemic_checked``.
    """
    stations = result.get("stations")
    if not isinstance(stations, dict):
        raise CoverageError("coverage result has no station table")
    proven_states: dict[str, StationState] = {}
    unproven: list[JSONValue] = []
    counts = {"working": 0, "proven": 0, "unproven": 0, "shared": 0}
    bests = {sid: evidence.best(station) for sid, station in registry.stations.items()}
    shared = shared_proofs(registry, states, bests)
    for station in sorted(registry.stations.values(), key=lambda item: item.id):
        state = states[station.id]
        best = bests[station.id]
        entry = stations.get(station.id)
        if isinstance(entry, dict):
            entry["proof"] = best.as_json(station) if best is not None else None
            if station.id in shared:
                entry["proof"] = _shared_json(*shared[station.id])
        proven_states[station.id] = state
        if state.state != "working":
            continue
        counts["working"] += 1
        if (best is not None and best.proves(station)) or station.id in shared:
            counts["proven"] += 1
            counts["shared"] += station.id in shared
            continue
        counts["unproven"] += 1
        proven_states[station.id] = StationState("unproven", "never seen populated")
        unproven.append({"id": station.id, "checked": _checked(evidence, station.id)})
    shares = measure(registry, schools, proven_states, None, weights=weights)
    result["proven"] = {
        "national": shares["national"],
        "states": shares["states"],
        "counties": _proven_counties(shares.get("counties")),
        "stations": dict(counts),
        "evidence": dict(evidence.files),
    }
    result["unproven"] = unproven
    if assumed is not None:
        checked = measure(
            without_counties(registry, assumed), schools, proven_states, None, weights=weights
        )
        proven_part = result["proven"]
        assert isinstance(proven_part, dict)  # noqa: S101 - set just above
        proven_part["market_checked"] = {
            "rule": MARKET_RULE,
            "national": checked["national"],
            "states": checked["states"],
            "assumed": {sid: list(fips) for sid, fips in sorted(assumed.items())},
        }
    if pandemic_only is not None:
        listed = sorted(set(pandemic_only))
        without = {
            sid: (StationState("unproven", "pandemic reads only") if sid in listed else value)
            for sid, value in proven_states.items()
        }
        again = measure(registry, schools, without, None, weights=weights)
        proven_part = result["proven"]
        assert isinstance(proven_part, dict)  # noqa: S101 - set just above
        proven_part["pandemic_checked"] = {
            "rule": PANDEMIC_RULE,
            "stations": list(listed),
            "national": again["national"],
            "states": again["states"],
        }


PANDEMIC_RULE = (
    "a proven closings list every populated read of which is the pandemic's (read in its "
    "first wave, March to June 2020, or every row a health closing) does not count"
)
MARKET_RULE = (
    "a station's county across its home state's line counts only when a row of the station's "
    "named a place in it; the station's market (DMA) alone does not credit it"
)


def _proven_counties(counties: JSONValue) -> dict[str, JSONValue]:
    """Each county's schools covered by a proven station, and which proven stations cover it."""
    if not isinstance(counties, dict):
        raise CoverageError("the proven measure has no county table")
    table: dict[str, JSONValue] = {}
    for fips, info in counties.items():
        if not isinstance(info, dict):
            continue
        table[fips] = {
            "schools": info.get("schools"),
            "covered": info.get("covered"),
            "proven": info.get("working"),
            "proven_districts": info.get("districts"),
        }
    return table


def summary_line(result: Mapping[str, JSONValue]) -> str | None:
    """One line on the proven share, for the command's output (None without it)."""
    proven = result.get("proven")
    national = proven.get("national") if isinstance(proven, dict) else None
    if not isinstance(proven, dict) or not isinstance(national, dict):
        return None
    line = f"proven (lists seen with rows): {float(str(national['share'])):.1%}"
    weighted = national.get("weighted")
    if isinstance(weighted, dict):
        line += f", closure-weighted {float(str(weighted['share'])):.1%}"
    counts = proven.get("stations")
    if isinstance(counts, dict):
        line += f"; {counts.get('proven')} of {counts.get('working')} working stations proven"
    return line

"""The national coverage gate: what each state still lacks, station by station.

The gate's targets apply to the *proven* share of ``coverage.json`` (a station
counts only once its list has been seen with a row, live or archived, at its
current address or a former address of its own list; see
:mod:`snowlight.sources.stations.proof`): 95% of the directory's schools
nationally, plain and closure-weighted, and 90% in each of the 48 states and DC.
This module reads the coverage result and says, for every state short of the
target, which sources could close the gap and what is known of each: whether it
is working, whether it is proven, how many schools (and how much closure weight)
proving it would add, and what the archive holds of its list. It also picks the
archived captures most likely to prove the stations that would add the most
(:func:`plan_captures`), for the archive-captures workflow.

Marginal gain: a working, unproven station's gain is the schools it covers
(whole counties, or its districts' schools for a district-level source) that no
proven working station covers; its closure-weighted gain sums those schools'
own weights (:meth:`~snowlight.sources.stations.coverage.Weights.school`). The
gains are computed school by school, the way :func:`~snowlight.sources.stations.coverage.measure`
counts, and :func:`check_totals` holds the proven totals so computed to the
coverage result's own.

The archive census: for each URL a station reads or read (its page, data file,
archive URLs and the list files its pages loaded), the captures the downloaded
CDX listings hold (HTTP 200 and revisits, which replay an earlier 200; a
revisit of a 404 page or a redirect the listings hold is left out), those
made in a winter month, their distinct digests, and how many captures were read
(downloaded and run through the adapters, or identical to a read one by digest)
with what result. A capture is *read* when its bytes were read (a read of the
list, a page on the way to it, or a failure recorded in the archive health: state
``error`` when its adapter refused the page, ``shell`` when it recognized a page that
loads its list from an address the archive does not hold near it),
when the archive answered it with a redirect to another address, which the
workflow followed (state ``redirect``: it holds no list of its own;
:func:`redirected_captures`), or when the archive replayed it as HTTP 403, 404
or 410 (state ``gone``: a page that was not there, or the site's refusal of the
archive's crawler; :func:`missing_captures`), or replays it as HTTP 429 on every
request over several hours (state ``refused``: the site's rate limit met by the
crawl; :func:`refused_captures`), or when the archive answered it
with another capture of the same address, the only one it serves for it (state
``replaced``; :func:`replaced_captures`); a
capture whose CDX digest equals a read capture's holds the same bytes. A capture
the archive holds only the first 1,048,576 bytes of, which its adapter could not
read (state ``cut``: Frenchtown's Nuxt 2 homepage of 2023-12-02, whose
``window.__NUXT__`` payload, the only place its alert banner is written, runs
past the cut; :func:`~snowlight.sources.stations.archive.cut_off`), holds no page
of the list a read could see, as a 404 does not: it neither shows nor hides a
closing, so it is not misread unless the text it does hold shows one.
Whether a URL was listed at all is known from the listing files' names (the
workflow names each after the pattern it asked for), so an empty listing is
told apart from a URL never asked about.

Verdicts (``verdict`` of each station in ``gate.json``):

* ``proven``: its list has been seen with a row, at its current or a former address,
  or it reads the same list file as a station so proven (``shared`` in
  :mod:`snowlight.sources.stations.proof`: Cowles' Montana stations, Gray's satellites);
* ``not-working``: its latest live read is stale, an error or skipped (the
  reason is kept); it does not count toward coverage at all;
* ``no-endpoint``: registered with no known closings endpoint;
* ``unread``: working, never seen populated, and some listed captures of its
  current page or data file, or of a former address of its own list (the
  registry's ``former_urls``), made in its *closure window* are not read yet
  (``unread_due`` counts them; ``unread`` counts every unread capture and
  ``unread_storm`` those on storm days). A station's closure days are its storm
  days (the school days an NWS winter, cold or tropical warning or advisory
  covered one of its counties, :mod:`snowlight.sources.stations.storms`) and the
  school days on which a proven whole-county list sharing one of its counties was
  seen with a row in an archived capture (:func:`closure_days`; ``unread_closure``
  counts the unread captures on those days that are not storm days); its closure
  window is those days and the :data:`NEAR_DAYS` either side of each
  (:func:`near_days`; ``unread_near`` counts the unread captures on those other
  days), since schools stay closed while roads are cleared after a storm and
  close the day before a hurricane. Captures from before the station's page took
  a form its adapter reads (:func:`readable_since`) are not due: they would be
  refused; nor are those from after it became a page whose list no read can see
  (:func:`blind_since`);
* ``misread``: working, never seen populated, and a read capture of its list's
  addresses made in its closure window was misread: its adapter refused it (a page
  form no reader knows: read state ``error``, whatever the closure-text check said
  of it, and any capture identical to it by digest) or it showed a closing that none
  of its rows holds (the
  closure-text check, :mod:`snowlight.sources.stations.closure_text`: the KULR page
  of 2019 that listed 25 schools in a form the Cowles adapter refused; Orange's
  homepage of Hurricane Ian whose slider caption no reader looked at). Such a read
  says nothing of whether the list was in use, so no settled verdict is given until
  the form is read (``misread`` and ``window_misread`` in its census). A page its
  adapter recognized as one that loads its list from an address the archive does
  not hold (a shell) is not misread unless it showed a closing itself;
* ``storm-read``: working, never seen populated, every address of its list was
  listed, and every listed capture of those addresses made in its closure window
  was read (or is identical to one read), none with a row, and at least one of
  them saw the list itself (``empty`` or ``count_only``, or a district's notice
  that announced no closing; ``window_seen`` counts those captures by digest).
  Captures made on other days may be unread (``unread`` counts them). The premise
  (a list in use holds a row on some capture made in its closure window) is
  measured on the proven sources' own archived reads (:func:`calibration`, written
  into ``gate.json``), and how strong the verdict is depends on ``window_seen``.
  Only given when storm days are known;
* ``no-storm-capture``: the same, but no read in its closure window saw the list
  (the archive holds no capture of it made there, or only page shells), though
  reads of other days did: no archived capture on or near a day its schools could
  have closed is left to read;
* ``unreadable`` instead of either when no read saw the list at all (each was
  refused, or was a page that loads its list from an address the archive does
  not hold) and at least :data:`SHELL_READS` captures were read;
* ``unconfirmed`` instead of ``storm-read``, ``no-storm-capture``, ``all-read`` or
  ``unreadable`` when a read capture of its list made in its closure window showed
  a closing that its rows hold but that did not prove it (the closure-text check's
  ``read``, ``window_noted`` in its census): a district's notice or homepage text
  that names no weather or emergency and no NWS warning corroborates (a calendar's
  "No School Monday, March 20th", Geraldine's PIR day of 2023; Converse #1's "No School
  in Converse 1-October 13, 2021", captured three days after it; see
  :func:`snowlight.sources.stations.notices.dated_closing`), or a story card that is
  not a list's entry. Nothing left in the archive's window can settle it either way,
  so it is terminal, but the list may well be in use;
* ``older-unread``: working, never seen populated, every listed capture of its
  list's addresses was read (none held a row) or there is none, and the captures
  still unread are of other addresses it read before (another vendor's file a
  page once framed), which cannot prove it
  (:meth:`snowlight.sources.stations.proof.Proof.proves`);
* ``all-read``: working, never seen populated, every address of its list (its
  current page and data file, and any former address) was listed, and every
  capture of its URLs that the listings hold, or that was asked for by time, was
  read (or is identical to one read), none with a row;
* ``unreadable``: the same, but every capture read was refused by its adapter
  (an earlier form of the page no adapter reads) or was a page shell whose list
  the archive does not hold (see ``storm-read`` for the same case with
  fair-weather captures unread);
* ``no-capture``: working, never seen populated, its URLs were listed and the
  archive holds no capture of any of them (or only captures it replays as a 404
  page or a redirect elsewhere);
* ``not-listed``: working and never seen populated, no unread capture of its
  list is known, and its current page or data file (or a former address of its
  list) was never listed: what the archive holds of that address is unknown, so
  no other verdict can be given (the reads of its other addresses, if any, are
  in its census).

``all-read``, ``storm-read``, ``unconfirmed``, ``no-storm-capture``,
``unreadable``, ``no-capture`` and ``no-endpoint`` are terminal (:data:`TERMINAL`): no archived
capture left in the station's closure window could prove it. ``misread`` is not:
a station with a misread capture in its closure window never gets a terminal
verdict (other than ``proven``), and the states it touches stay open. A state short of
the target is *settled* when every source whose proof would add a school to it
has a terminal verdict (or is proven, or not working), and no first-hand record of
a source the registry does not hold keeps it open (``open_records``: one that says
its site was not read, or was checked before :data:`FRESH_SINCE`; see
:func:`open_records`); its ``open`` sources are the rest (:func:`plan_due` asks for
what keeps them open).

Written (internal, never published) to ``gate.json`` beside ``coverage.json``::

    {"generated_at", "coverage": {"path", "sha256", "generated_at"},
     "targets": {"national", "state"},
     "national": {"proven": Share, "gap": {"schools", "weighted"},
                  "to_target": {"schools", "weighted"}, "settled": bool},
     "states": {ST: {"proven": Share, "meets_target": bool,
                     "gap": {"schools", "weighted"},
                     "to_target": {"schools", "weighted"},
                     "private_schools": n, "stations": [id, ...],
                     "settled": bool, "open": [id, ...],
                     "open_records": [{"source_id", "verdict", "checked_at", "why"}, ...]}},
     "stations": {id: {"name", "platform", "market", "states", "status", "state",
                       "reason", "proven", "district_level",
                       "gain": {"schools", "weighted", "by_state": {ST: [n, w]}},
                       "verdict", "readable_since", "blind_since", "closure_days": n,
                       "near_days": n, "window_seen": n, "archive": [KeyCensus, ...]}},
     "ranking": [{"id", "schools", "weighted", "verdict"}, ...],
     "calibration": {"near_days": n,
                     "lists" | "channels": {"closure_days" | "window": [Bin, ...],
                                            "closure_days_missed" | "window_missed":
                                                [{"id", "window_reads"}, ...]}} | null,
     "dmas": {label: {"schools", "working", "proven", "working_district",
                      "proven_district"}},
     "dma_summary": {"markets", "with_a_working_source", "with_a_whole_county_source",
                     "with_a_proven_source", "biggest_by_schools": [...]}}

    KeyCensus = {"key", "current", "former", "listed", "listing_asked", "winter", "digests",
                 "read": {"populated": n, "empty": n, "error": n, ...},
                 "read_captures": n, "unread": n, "unread_storm": n,
                 "unread_closure": n, "unread_near": n, "unread_due": n,
                 "window_seen": n, "misread": n, "window_misread": n, "window_noted": n}
    Bin = {"reads": "0" | "1" | "2" | "3-4" | "5-9" | "10+", "sources": n,
           "none_showed": n}

(``Share`` as in :mod:`~snowlight.sources.stations.coverage`. ``gap`` is what
the proven share lacks of every school, ``to_target`` what it lacks of the
target; ``private_schools`` counts the state's schools no district holds, which
only a whole-county source can cover. A market (``dmas``) counts both its
whole-county sources and the district-level sources with schools in its
counties: every market should have a working source, the largest two or more.)

:func:`gap_records` turns the report into one record per source touching each
state short of the target, in the shape of the gap-state part's first-hand file
(``docs/research/firsthand/gaps.json``), with a ``gate`` block; ``snowlight
stations gate records`` merges them into that file (:func:`merge_records`).
"""

import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from snowlight.output import JSONValue, write_json
from snowlight.sources.stations.archive import (
    CUT_OFF,
    Capture,
    SnapshotRecord,
    find_manifests,
    read_cdx,
    read_manifest,
    url_key,
    winter_season,
)
from snowlight.sources.stations.closure_text import MISREAD, SHELL_REASONS, Checked
from snowlight.sources.stations.coverage import NATIONAL_TARGET, STATE_TARGET, Weights
from snowlight.sources.stations.http import iso_utc
from snowlight.sources.stations.model import ListingRead, ListingState, ReadMode, SourceHealth
from snowlight.sources.stations.registry import Registry, Station, StationStatus
from snowlight.sources.stations.storms import StormDays, school_day
from snowlight.weights.codes import BY_CODE
from snowlight.weights.count import Tally

GATE_FILE = "gate.json"
REVISIT = "-"
"""The CDX status of a revisit record (an unchanged capture, replaying an earlier one)."""
REPLAYABLE = frozenset({"200", REVISIT})
"""CDX status codes the archive replays: an HTTP 200, or a revisit of an earlier one."""
_UNSAFE = re.compile(r"[^A-Za-z0-9]")


class GateError(ValueError):
    """The coverage result or the archive files do not have the shape the gate needs."""


def school_frame(schools: pl.DataFrame, weights: Weights | None) -> pl.DataFrame:
    """Return the directory's schools with the columns the gate reads and each school's weight.

    Columns: ``state``, ``county_fips``, ``district_id`` (null for a school no
    district holds) and ``weight`` (the school's closure weight, 0.0 when it has
    none or no weights are given).
    """
    needed = {"state", "county_fips"}
    if not needed <= set(schools.columns):
        raise GateError(f"the school directory lacks {sorted(needed - set(schools.columns))}")
    frame = schools.select(
        pl.col("state").cast(pl.String),
        pl.col("county_fips").cast(pl.String),
        (
            pl.col("district_id").cast(pl.String)
            if "district_id" in schools.columns
            else pl.lit(None, dtype=pl.String).alias("district_id")
        ),
        (pl.col("index") if "index" in schools.columns else pl.lit(None, dtype=pl.Int64)).alias(
            "index"
        ),
    )
    if weights is None:
        return frame.drop("index").with_columns(pl.lit(0.0).alias("weight"))
    values = [
        weights.school(int(index) if index is not None else None, str(fips)) or 0.0
        for index, fips in zip(
            frame["index"].to_list(), frame["county_fips"].to_list(), strict=True
        )
    ]
    return frame.drop("index").with_columns(pl.Series("weight", values, dtype=pl.Float64))


def _mask(station: Station, frame: pl.DataFrame) -> pl.Series:
    """Which schools a station covers: its districts' schools, or its counties' schools."""
    if station.leaids:
        return frame["district_id"].is_in(list(station.leaids)).fill_null(value=False)
    if station.counties is None:
        return pl.Series([False] * frame.height, dtype=pl.Boolean)
    return frame["county_fips"].is_in(list(station.counties.fips))


@dataclass(frozen=True, slots=True)
class Gain:
    """The schools proving one station would add to the proven share."""

    schools: int
    weighted: float
    by_state: Mapping[str, tuple[int, float]]

    def as_json(self) -> dict[str, JSONValue]:
        """The gain as ``gate.json`` records it."""
        return {
            "schools": self.schools,
            "weighted": round(self.weighted, 1),
            "by_state": {
                state: [count, round(weight, 1)]
                for state, (count, weight) in sorted(self.by_state.items())
            },
        }


def _covered(registry: Registry, frame: pl.DataFrame, ids: Iterable[str]) -> pl.Series:
    covered = pl.Series([False] * frame.height, dtype=pl.Boolean)
    for station_id in ids:
        covered = covered | _mask(registry.stations[station_id], frame)
    return covered


def marginal_gains(
    registry: Registry, frame: pl.DataFrame, working: set[str], proven: set[str]
) -> dict[str, Gain]:
    """Return what proving each working, unproven station would add (see the module docstring)."""
    base = _covered(registry, frame, proven & working)
    gains: dict[str, Gain] = {}
    for station_id in sorted(working - proven):
        added = frame.filter(_mask(registry.stations[station_id], frame) & ~base)
        by_state: dict[str, tuple[int, float]] = {}
        for row in (
            added.group_by("state")
            .agg(pl.len().alias("n"), pl.col("weight").sum().alias("w"))
            .iter_rows(named=True)
        ):
            by_state[str(row["state"])] = (int(row["n"]), float(row["w"]))
        gains[station_id] = Gain(
            schools=added.height, weighted=float(added["weight"].sum()), by_state=by_state
        )
    return gains


def check_totals(
    registry: Registry,
    frame: pl.DataFrame,
    proven: set[str],
    result: Mapping[str, JSONValue],
    *,
    tolerance: float = 0.5,
) -> None:
    """Hold the proven totals counted school by school to the coverage result's own.

    Raises :class:`GateError` when the national proven count differs, or the
    weighted sum differs by more than ``tolerance`` (the result rounds to 0.1).
    """
    national = _proven_national(result)
    covered = _covered(registry, frame, proven)
    count = int(covered.sum())
    if count != national.get("covered"):
        raise GateError(
            f"the gate counts {count} proven schools, coverage.json {national.get('covered')}"
        )
    weighted = national.get("weighted")
    if isinstance(weighted, dict):
        total = float(frame.filter(covered)["weight"].sum())
        if abs(total - float(str(weighted.get("covered")))) > tolerance:
            raise GateError(
                f"the gate sums {total:.1f} proven weight, coverage.json {weighted.get('covered')}"
            )


def _proven_national(result: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    proven = result.get("proven")
    national = proven.get("national") if isinstance(proven, dict) else None
    if not isinstance(national, dict):
        raise GateError("coverage.json has no proven share (run the coverage with its evidence)")
    return national


def _station_table(result: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    stations = result.get("stations")
    if not isinstance(stations, dict):
        raise GateError("coverage.json has no station table")
    return stations


def proven_and_working(result: Mapping[str, JSONValue]) -> tuple[set[str], set[str]]:
    """Return the working stations and the proven ones among them, from ``coverage.json``."""
    working: set[str] = set()
    proven: set[str] = set()
    for station_id, entry in _station_table(result).items():
        if not isinstance(entry, dict) or entry.get("state") != "working":
            continue
        working.add(station_id)
        found = entry.get("proof")
        if isinstance(found, dict) and found.get("proves", found.get("current")) is True:
            proven.add(station_id)
    unproven = result.get("unproven")
    if isinstance(unproven, list):
        listed = {item.get("id") for item in unproven if isinstance(item, dict)}
        proven -= {str(item) for item in listed}
    return working, proven


# The archive census -----------------------------------------------------------------


def current_keys(station: Station) -> list[str]:
    """The URL keys of the list a station reads today: its page and its data file."""
    return sorted({url_key(url) for url in (station.page_url, station.data_url) if url})


def former_keys(station: Station) -> list[str]:
    """The URL keys of the station's own former addresses of its list (``former_urls``)."""
    return sorted({url_key(item.url) for item in station.former_urls} - set(current_keys(station)))


def proving_keys(station: Station) -> list[str]:
    """The URL keys whose reads can prove the station: current and former addresses.

    Only a read of one of these (or reached through one) proves the station
    (:meth:`snowlight.sources.stations.proof.Proof.proves`), so only their
    captures are worth asking the archive for.
    """
    return sorted({*current_keys(station), *former_keys(station)})


def station_keys(station: Station) -> list[str]:
    """Every URL key a station reads or read: page, data file, archive URLs, list files."""
    urls = [station.page_url, station.data_url, station.export_url, *station.archive_urls]
    urls += [item.url for item in station.list_files]
    return sorted({url_key(url) for url in urls if url})


@dataclass(slots=True)
class Census:
    """What the downloaded listings and captures say, by URL key."""

    listings: dict[str, list[Capture]] = field(default_factory=dict)
    listing_names: set[str] = field(default_factory=set)
    read: dict[tuple[str, str], str] = field(default_factory=dict)
    """(capture timestamp, URL key) to what reading it gave: a listing state, or ``error``."""
    misread: dict[tuple[str, str], str] = field(default_factory=dict)
    """(capture timestamp, URL key) of each capture the closure-text check found misread:
    ``unrecognized`` (its adapter refused its form) or ``missed`` (it showed a closing its
    rows do not hold); see :mod:`snowlight.sources.stations.closure_text`."""
    noted: frozenset[tuple[str, str]] = frozenset()
    """(capture timestamp, URL key) of each capture that showed a closing its rows hold
    (the closure-text check's ``read``): of an unproven station, rows that did not prove it."""

    def asked(self, key: str) -> bool:
        """Whether a listing was asked for that covers ``key`` (by the listing files' names).

        A listing's file is named after the URL it asked for (every character
        outside A-Za-z0-9 made ``_``), then, in the workflow's current format, the
        two days of its window and the hash of its filter. It covers ``key`` when
        it asked for that URL, or for a prefix of it (a trailing ``*``, which
        names the same way as a trailing ``/``, so a listing of ``host/`` also
        counts for the host's other paths). A listing of another path of the
        same host does not cover its homepage.
        """
        stems = (_UNSAFE.sub("_", key), _UNSAFE.sub("_", f"www.{key}"))
        for name in self.listing_names:
            asked = listing_url_part(name)
            for stem in stems:
                if asked == stem or (asked.endswith("_") and stem.startswith(asked[:-1])):
                    return True
        return False

    def digest_states(self, key: str) -> dict[str, str]:
        """Each digest of ``key``'s listed captures that was read, with what reading it gave."""
        found: dict[str, str] = {}
        for capture in self.listings.get(key, []):
            state = self.read.get((capture.timestamp, key))
            if state is not None:
                found.setdefault(capture.digest, state)
                if state == "populated":
                    found[capture.digest] = state
        return found


_LISTING_NAME = re.compile(r"^(?P<url>.*?)(?:__\d{8}-\d{8})?(?:__f[0-9a-f]{8})?\.json$")


def listing_url_part(name: str) -> str:
    """The part of a CDX listing's file name that names the URL it asked for."""
    found = _LISTING_NAME.match(name)
    return found.group("url") if found is not None else name


def load_listings(root: Path) -> tuple[dict[str, list[Capture]], set[str]]:
    """Read every CDX listing under ``root`` (folders named ``cdx*``).

    Returns the replayable captures by URL key (each capture once) and the
    listing files' names (so a listing that came back empty still shows it was
    asked for).

    A revisit record (status ``-``) replays an earlier capture with the same
    digest. When the listings of the same address hold that earlier capture with
    another status than 200 (a 404 page, a redirect), the revisit replays that
    answer, not a page, and is left out with it: an address that has answered 404
    since a station moved its list is listed as revisits of its 404 page.
    """
    found: dict[str, dict[tuple[str, str], Capture]] = defaultdict(dict)
    answered: dict[str, dict[str, str]] = defaultdict(dict)
    names: set[str] = set()
    for path in sorted(root.rglob("*.json")):
        folders = path.relative_to(root).parts[:-1]
        if not any(part.startswith("cdx") for part in folders):
            continue
        names.add(path.name)
        for capture in read_cdx(path):
            key = url_key(capture.original)
            if capture.status != REVISIT:
                answered[key].setdefault(capture.digest, capture.status)
                if capture.status == "200":
                    answered[key][capture.digest] = "200"
            if capture.status in REPLAYABLE:
                found[key][(capture.timestamp, capture.original)] = capture
    listings = {
        key: sorted(
            (
                capture
                for capture in captures.values()
                if capture.status != REVISIT or answered[key].get(capture.digest, "200") == "200"
            ),
            key=lambda c: c.timestamp,
        )
        for key, captures in found.items()
    }
    return listings, names


def _stamp(moment: datetime) -> str:
    return f"{moment:%Y%m%d%H%M%S}"


def read_captures(
    reads: Iterable[ListingRead], failures: Iterable[SourceHealth]
) -> dict[tuple[str, str], str]:
    """Map each archived capture that was read to what reading it gave.

    A list read by following pages counts for the list file (its state) and for
    each page on the way (``deferred`` or ``count_only``); a failure recorded in
    the archive health counts as ``error`` (its adapter refused the page) unless the
    capture was also read, as ``shell`` when its adapter recognized a page that
    loads its list from another address the archive does not hold near it
    (:data:`~snowlight.sources.stations.closure_text.SHELL_REASONS`), or as ``cut``
    when the archive holds only the first part of the page and its adapter could
    not read it (:func:`~snowlight.sources.stations.archive.cut_off`).
    """
    found: dict[tuple[str, str], str] = {}
    for read in reads:
        found[(_stamp(read.fetched_at), url_key(read.url))] = read.state.value
        for page in read.via:
            found.setdefault((_stamp(page.fetched_at), url_key(page.url)), page.state.value)
    for failure in failures:
        if failure.url is None or failure.status.value in {"ok", "empty"}:
            continue
        if failure.sha256 is None:
            continue  # never downloaded: nothing was read
        reason = failure.reason or ""
        if reason.startswith(CUT_OFF):
            state = "cut"
        elif reason.startswith(SHELL_REASONS):
            state = "shell"
        else:
            state = "error"
        found.setdefault((_stamp(failure.checked_at), url_key(failure.url)), state)
    return found


def downloaded_keys(root: Path) -> set[tuple[str, str]]:
    """(Capture timestamp, URL key) of every capture downloaded under ``root``."""
    done: set[tuple[str, str]] = set()
    for manifest in find_manifests(root):
        for record in read_manifest(manifest):
            if record.file is not None:
                done.add(_record_key(record))
    return done


def _record_key(record: SnapshotRecord) -> tuple[str, str]:
    return (
        record.final_timestamp or record.timestamp,
        url_key(record.final_original or record.url),
    )


@dataclass(frozen=True, slots=True)
class KeyCensus:
    """The archive's captures of one URL key, and how many were read."""

    key: str
    listed: int
    listing_asked: bool
    winter: int
    digests: int
    read: Mapping[str, int]
    read_captures: int
    unread: int
    unread_storm: int
    current: bool = True
    """Whether the key is the station's current page or data file (:func:`current_keys`)."""
    former: bool = False
    """Whether the key is one of the station's own former addresses (:func:`former_keys`)."""
    unread_closure: int = 0
    """Unread captures on a day a proven list sharing a county held a row, not a storm day."""
    unread_due: int = 0
    """Unread captures in its closure window (a closure day or a day near one), in a form
    its adapter reads."""
    unread_near: int = 0
    """Unread captures on a day near a closure day (:data:`NEAR_DAYS`), not a closure day."""
    window_seen: int = 0
    """Distinct captures in its closure window whose read saw the list (:data:`LIST_SEEN`)."""
    misread: int = 0
    """Captures misread: refused by their adapter (read state ``error``), or found by the
    closure-text check showing a closing their rows do not hold (or identical, by digest,
    to a capture that was)."""
    window_misread: int = 0
    """Of those, the captures made in its closure window."""
    window_noted: int = 0
    """Captures in its closure window that showed a closing its rows hold (:attr:`Census.noted`)."""

    @property
    def proving(self) -> bool:
        """Whether a read of this key can prove the station (current or former address)."""
        return self.current or self.former

    def as_json(self) -> dict[str, JSONValue]:
        """The census as ``gate.json`` records it."""
        return {
            "key": self.key,
            "current": self.current,
            "former": self.former,
            "listed": self.listed,
            "listing_asked": self.listing_asked,
            "winter": self.winter,
            "digests": self.digests,
            "read": dict(sorted(self.read.items())),
            "read_captures": self.read_captures,
            "unread": self.unread,
            "unread_storm": self.unread_storm,
            "unread_closure": self.unread_closure,
            "unread_near": self.unread_near,
            "unread_due": self.unread_due,
            "window_seen": self.window_seen,
            "misread": self.misread,
            "window_misread": self.window_misread,
            "window_noted": self.window_noted,
        }


def key_census(  # noqa: PLR0913 - the key, where it is known from, and which address it is
    census: Census,
    station_id: str,
    key: str,
    storms: StormDays | None,
    *,
    current: bool = True,
    former: bool = False,
    closure: Collection[date] = frozenset(),
    near: Collection[date] = frozenset(),
    since: str | None = None,
    until: str | None = None,
) -> KeyCensus:
    """Count one URL key's captures and what is known of each (see the module docstring).

    A capture read though no listing holds it (asked for by a guessed time, the
    archive serving its nearest) counts as read too. ``current`` says whether the
    key is one of the station's :func:`current_keys`, ``former`` whether it is
    one of its :func:`former_keys`. ``closure`` holds the station's school days
    on which a proven list sharing one of its counties held a row
    (:func:`closure_days`), ``near`` the days near one of its closure days
    (:func:`near_days`), ``since`` the time before which its page was in a form
    its adapter refuses (:func:`readable_since`) and ``until`` the time from
    which it holds no list a read can see (:func:`blind_since`). Its *closure
    window* is its storm days, ``closure`` and ``near``; an unread capture in the
    window, made after ``since`` and before ``until``, is *due*, and
    ``window_seen`` counts the distinct captures in the window (by digest) whose
    read saw the list.
    """
    captures = census.listings.get(key, [])
    states = census.digest_states(key)
    read: dict[str, int] = defaultdict(int)
    seen: set[str] = set()
    window: set[str] = set()
    unread = unread_storm = unread_closure = unread_near = unread_due = 0
    misread: set[str] = set()
    window_misread: set[str] = set()
    noted: set[str] = set()
    misread_digests = {c.digest for c in captures if (c.timestamp, key) in census.misread}
    noted_digests = {c.digest for c in captures if (c.timestamp, key) in census.noted}

    def where(moment: datetime) -> tuple[bool, bool, bool]:
        storm = storms is not None and storms.score(station_id, moment) > 0
        day = school_day(moment)
        listed_day = day in closure and not storm
        return storm, listed_day, day in near and not storm and not listed_day

    def mark(stamp: str, state: str, in_window: bool, digest: str | None = None) -> None:
        """Count whether one read capture was misread, or showed a closing that did not prove.

        A capture its adapter refused (``error``) is misread whatever the closure-text
        check said of it, and so is one identical by digest to a capture the check found
        misread; a capture identical to one that showed a closing is noted the same way.
        """
        if (
            state == "error"
            or (stamp, key) in census.misread
            or (digest is not None and digest in misread_digests)
        ):
            misread.add(stamp)
            if in_window:
                window_misread.add(stamp)
        if in_window and (
            (stamp, key) in census.noted or (digest is not None and digest in noted_digests)
        ):
            noted.add(stamp)

    for capture in captures:
        state = census.read.get((capture.timestamp, key)) or states.get(capture.digest)
        storm, listed_day, near_day = where(capture.when)
        if state is None:
            unread += 1
            unread_storm += storm
            unread_closure += listed_day
            unread_near += near_day
            if (storm or listed_day or near_day) and _in_form(capture.timestamp, since, until):
                unread_due += 1
            continue
        seen.add(capture.timestamp)
        read[state] += 1
        in_window = storm or listed_day or near_day
        if state in LIST_SEEN and in_window:
            window.add(capture.digest)
        mark(capture.timestamp, state, in_window, capture.digest)
    for (stamp, read_key), state in census.read.items():
        if read_key == key and stamp not in seen:
            seen.add(stamp)
            read[state] += 1
            in_window = any(where(_moment(stamp)))
            if state in LIST_SEEN and in_window:
                window.add(f"@{stamp}")
            mark(stamp, state, in_window)
    return KeyCensus(
        key=key,
        listed=len(captures),
        listing_asked=bool(captures) or census.asked(key),
        winter=sum(1 for c in captures if winter_season(c.when) is not None),
        digests=len({c.digest for c in captures}),
        read=dict(read),
        read_captures=len(seen),
        unread=unread,
        unread_storm=unread_storm,
        current=current,
        former=former,
        unread_closure=unread_closure,
        unread_due=unread_due,
        unread_near=unread_near,
        window_seen=len(window),
        misread=len(misread),
        window_misread=len(window_misread),
        window_noted=len(noted),
    )


def _moment(stamp: str) -> datetime:
    """The UTC time of a ``YYYYMMDDhhmmss`` capture timestamp."""
    return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def near_days(
    station_id: str, storms: StormDays | None, closure: Collection[date]
) -> frozenset[date]:
    """The days within :data:`NEAR_DAYS` of one of a station's closure days, not one itself.

    A station's closure days are its storm days and its proven-list days
    (:func:`closure_days`). Lists in use hold rows on the days next to them too:
    schools stay closed while roads are cleared after a storm, and a closing is
    posted the day before a hurricane lands (see :func:`calibration`, which
    measures how often a proven source showed its list's use only there).
    """
    core = set(closure)
    if storms is not None:
        core |= set(storms.by_station.get(station_id, {}))
    found = {
        day + timedelta(days=step)
        for day in core
        for step in range(-NEAR_DAYS, NEAR_DAYS + 1)
        if step
    }
    return frozenset(found - core)


def _in_form(stamp: str, since: str | None, until: str | None) -> bool:
    """Whether a capture was made while the page was in a form a read can see the list in."""
    return (since is None or stamp > since) and (until is None or stamp < until)


LIST_SEEN = frozenset({"empty", "count_only", "populated"})
"""Read states that saw the list itself (not a page shell, a redirect or a refusal).

``populated`` counts for a district's notice that announced no closing (it does not
prove the station, but its list was seen)."""
SHELL_READS = 3
"""Reads of a list's addresses, none of which saw the list, after which no more
fair-weather captures are asked for: the page is a shell or a form no adapter reads."""
NEAR_DAYS = 2
"""Days on either side of a closure day that are in a station's closure window too.

A list in use holds rows next to its closure days as well: schools stay closed
while roads are cleared after a storm and close the day before a hurricane lands,
and a district's closing notice stays on its homepage for days. The window is
measured on the archive's own record each time the report is built
(:func:`calibration`, in ``gate.json``): how many proven sources, by how many of
their window captures were read, showed their use on none of them, with the
closure days alone and with these days added."""
TERMINAL = frozenset(
    {
        "all-read",
        "storm-read",
        "unconfirmed",
        "no-storm-capture",
        "unreadable",
        "no-capture",
        "no-endpoint",
    }
)
"""Verdicts after which no archive read is left that could prove the station."""


def verdict(
    state: str,
    proven: bool,
    keys: Sequence[KeyCensus],
    status: StationStatus,
    *,
    storm_days: bool = False,
) -> str:
    """The station's verdict code (see the module docstring).

    ``storm_days`` says whether the census counted storm days; without them no
    capture is known to be due, and ``storm-read`` is never given.
    """
    if status is StationStatus.NO_ENDPOINT or state == "no_endpoint":
        return "no-endpoint"
    if state != "working" or proven:
        return "proven" if state == "working" else "not-working"
    proving = [item for item in keys if item.proving]
    still = _open_verdict(proving)
    if still is not None:
        return still
    if any(item.unread for item in proving):
        found = _fair_verdict(proving) if storm_days else "unread"
    else:
        found = _read_verdict(keys)
    if found in _NOTED_OVER and any(item.window_noted for item in proving):
        return "unconfirmed"
    return found


_NOTED_OVER = frozenset({"storm-read", "no-storm-capture", "all-read", "unreadable"})
"""Terminal verdicts that ``unconfirmed`` replaces when a window capture showed a closing
its rows hold but that did not prove the station."""


def _open_verdict(proving: Sequence[KeyCensus]) -> str | None:
    """``unread``, ``not-listed`` or ``misread`` when one keeps the station open, else None."""
    if any(item.unread_due for item in proving):
        return "unread"
    if any(not item.listing_asked for item in proving):
        return "not-listed"
    if any(item.window_misread for item in proving):
        return "misread"
    return None


def _fair_verdict(proving: Sequence[KeyCensus]) -> str:
    """The verdict of a station whose only unread captures were made outside its closure window.

    ``storm-read`` when a read in its closure window saw the list (and none of
    them held a row), ``no-storm-capture`` when reads saw the list but none in
    its window did (the archive holds no capture of the list made in it, or only
    page shells), ``unreadable`` when no read saw the list at all.
    """
    if any(found in LIST_SEEN for item in proving for found in item.read):
        return "storm-read" if any(item.window_seen for item in proving) else "no-storm-capture"
    return "unreadable" if sum(item.read_captures for item in proving) >= SHELL_READS else "unread"


def _read_verdict(keys: Sequence[KeyCensus]) -> str:
    """The verdict of a working, unproven station whose list's addresses were all listed."""
    if any(item.unread for item in keys):
        return "older-unread"
    states = {state for item in keys for state in item.read}
    if states - _NO_PAGE - _NO_LIST:
        return "all-read"
    if states & _NO_LIST:
        return "unreadable"
    return "no-capture" if any(item.listing_asked for item in keys) else "not-listed"


_NO_LIST = frozenset({"error", "shell"})
"""Read states of captures that showed no list a read could see: a page form its adapter
refuses, or a page that loads its list from an address the archive does not hold."""
_NO_PAGE = frozenset({"gone", "refused", "redirect", "replaced", "cut"})
"""Read states of captures that held no page of the list of their own: a 404 replayed,
a refusal replayed, a redirect, a capture the archive answered with another one, or
a page the archive holds only the first part of, without the part its list is in."""


def closure_days(
    registry: Registry, reads: Iterable[ListingRead], proven: Collection[str]
) -> dict[str, frozenset[date]]:
    """Each station's school days on which a proven list sharing one of its counties held a row.

    The days come from the archived captures read populated (``reads``) of the
    proven whole-county stations (a district's notice is not a list of closings
    in the county), each placed on its school day
    (:func:`~snowlight.sources.stations.storms.school_day`); a station's days are
    those of every such station with a county in common. They are days on which
    closings were posted in its market, whatever the weather codes said (a
    hurricane's eve, a fire, a power cut, fog): a list in use was likely to hold
    rows then too.
    """
    by_county: dict[str, set[date]] = defaultdict(set)
    for station_id, populated in _populated_days(registry, reads, proven).items():
        counties = registry.stations[station_id].counties
        for fips in counties.fips if counties is not None else ():
            by_county[fips] |= populated
    found: dict[str, frozenset[date]] = {}
    for station in registry.stations.values():
        if station.counties is None:
            continue
        days: set[date] = set()
        for fips in station.counties.fips:
            days |= by_county.get(fips, set())
        if days:
            found[station.id] = frozenset(days)
    return found


def _populated_days(
    registry: Registry, reads: Iterable[ListingRead], proven: Collection[str]
) -> dict[str, set[date]]:
    """Each proven whole-county station's school days on which an archived read held a row."""
    found: dict[str, set[date]] = defaultdict(set)
    for read in reads:
        if read.mode is not ReadMode.ARCHIVE or read.state is not ListingState.POPULATED:
            continue
        if read.source_id not in proven:
            continue
        station = registry.stations.get(read.source_id)
        if station is None or station.leaids or station.counties is None:
            continue
        found[read.source_id].add(school_day(read.fetched_at))
    return found


CALIBRATION_BINS: tuple[tuple[int, int | None, str], ...] = (
    (0, 0, "0"),
    (1, 1, "1"),
    (2, 2, "2"),
    (3, 4, "3-4"),
    (5, 9, "5-9"),
    (10, None, "10+"),
)
"""How :func:`calibration` groups sources by the distinct window captures read."""


def _bin(count: int) -> str:
    for low, high, label in CALIBRATION_BINS:
        if count >= low and (high is None or count <= high):
            return label
    raise AssertionError(count)  # pragma: no cover - the bins cover every count


def _kept_times(entry: JSONValue) -> set[str]:
    """The capture times of a gated channel's archived proofs that announced a closing."""
    kept = entry.get("kept_proofs") if isinstance(entry, dict) else None
    items = kept if isinstance(kept, list) else []
    return {
        str(item.get("captured_at"))
        for item in items
        if isinstance(item, dict) and item.get("mode") == ReadMode.ARCHIVE.value
    }


def calibration(  # noqa: PLR0912 - one pass over the proven sources, two kinds, two windows
    registry: Registry,
    reads: Sequence[ListingRead],
    proven: Collection[str],
    storms: StormDays,
    result: Mapping[str, JSONValue],
) -> dict[str, JSONValue]:
    """Measure the closure window on the proven sources' own archived reads.

    The ``storm-read`` verdict rests on a premise the archive can test: a list in
    use holds a row on some capture made in its closure window. For every proven
    source with an archived read that showed its use (a whole-county list: a row;
    a district channel: a notice that announced a closing, as the district notice
    gate kept it), this counts the distinct captures of it read in its closure
    window that saw the list (:data:`LIST_SEEN`, by body hash), and whether one of
    them showed its use. A source's closure window here is its storm days and the
    days other proven lists sharing one of its counties held a row (its own rows
    left out, so it is a test and not a tautology), alone (``closure_days``) and
    with the :data:`NEAR_DAYS` either side (``window``). Status boards, which hold
    rows every day, are left out. ``none_showed`` counts the sources whose window
    reads all looked unused; ``missed`` names those read at least once there.
    """
    gated_block = result.get("district_notice_gate")
    gated = gated_block if isinstance(gated_block, dict) else {}
    populated = _populated_days(registry, reads, proven)
    fips_of = {
        station.id: frozenset(station.counties.fips)
        for station in registry.stations.values()
        if station.counties is not None
    }
    archived: dict[str, list[ListingRead]] = defaultdict(list)
    for read in reads:
        if read.mode is ReadMode.ARCHIVE and read.source_id in proven:
            archived[read.source_id].append(read)
    tables: dict[str, dict[str, dict[str, dict[str, int]]]] = {
        kind: {
            name: {label: {"sources": 0, "none_showed": 0} for *_, label in CALIBRATION_BINS}
            for name in ("closure_days", "window")
        }
        for kind in ("lists", "channels")
    }
    missed: dict[str, dict[str, list[JSONValue]]] = {
        kind: {"closure_days": [], "window": []} for kind in ("lists", "channels")
    }
    for station_id, found in sorted(archived.items()):
        station = registry.stations.get(station_id)
        if station is None or station_id not in fips_of:
            continue
        entry = gated.get(station_id)
        if isinstance(entry, dict):
            if entry.get("kind") != "channel":
                continue
            kind, kept = "channels", _kept_times(entry)
            showed = [read for read in found if iso_utc(read.fetched_at) in kept]
        elif station.leaids:
            continue
        else:
            kind = "lists"
            showed = [read for read in found if read.state is ListingState.POPULATED]
        if not showed:
            continue
        core = set(storms.by_station.get(station_id, {}))
        for other, days in populated.items():
            if other != station_id and fips_of[station_id] & fips_of.get(other, frozenset()):
                core |= days
        for name, reach in (("closure_days", 0), ("window", NEAR_DAYS)):
            window = {
                day + timedelta(days=step) for day in core for step in range(-reach, reach + 1)
            }
            seen = {
                read.sha256
                for read in found
                if read.state.value in LIST_SEEN and school_day(read.fetched_at) in window
            }
            hit = any(school_day(read.fetched_at) in window for read in showed)
            cell = tables[kind][name][_bin(len(seen))]
            cell["sources"] += 1
            cell["none_showed"] += not hit
            if seen and not hit:
                missed[kind][name].append({"id": station_id, "window_reads": len(seen)})
    out: dict[str, JSONValue] = {"near_days": NEAR_DAYS}
    for kind, by_window in tables.items():
        block: dict[str, JSONValue] = {}
        for name, cells in by_window.items():
            rows: list[JSONValue] = [
                {"reads": label, **cells[label]} for *_, label in CALIBRATION_BINS
            ]
            block[name] = rows
            block[f"{name}_missed"] = list(missed[kind][name])
        out[kind] = block
    return out


# The report -------------------------------------------------------------------------


def _share_field(share: Mapping[str, JSONValue], name: str) -> float:
    value = share.get(name)
    if not isinstance(value, int | float):
        raise GateError(f"a share lacks {name!r}")
    return float(value)


def _gap(share: Mapping[str, JSONValue], target: float) -> tuple[dict[str, JSONValue], ...]:
    schools, covered = _share_field(share, "schools"), _share_field(share, "covered")
    gap: dict[str, JSONValue] = {"schools": int(schools - covered)}
    to_target: dict[str, JSONValue] = {
        "schools": max(0, int(-(-(target * schools - covered) // 1)))
    }
    weighted = share.get("weighted")
    if isinstance(weighted, dict):
        w_schools, w_covered = _share_field(weighted, "schools"), _share_field(weighted, "covered")
        gap["weighted"] = round(w_schools - w_covered, 1)
        to_target["weighted"] = round(max(0.0, target * w_schools - w_covered), 1)
    return gap, to_target


def _meets(share: Mapping[str, JSONValue]) -> bool:
    weighted = share.get("weighted")
    meets = share.get("meets_target") is True
    if isinstance(weighted, dict):
        meets = meets and weighted.get("meets_target") is True
    return meets


def build_report(  # noqa: PLR0913 - the report joins every input the gate reads
    registry: Registry,
    result: Mapping[str, JSONValue],
    frame: pl.DataFrame,
    census: Census,
    storms: StormDays | None,
    *,
    coverage_file: Mapping[str, JSONValue],
    now: datetime,
    closure: Mapping[str, Collection[date]] | None = None,
    reads: Sequence[ListingRead] = (),
    records: Sequence[Mapping[str, JSONValue]] | None = None,
) -> dict[str, JSONValue]:
    """Build ``gate.json`` (see the module docstring).

    ``closure`` holds each station's proven-list days (:func:`closure_days`);
    ``reads`` are the archive's reads, from which :func:`calibration` measures the
    closure window on the proven sources (given storm days). ``records`` are the
    first-hand gap file's records: a state short of the target is not settled while
    one of them keeps it open (:func:`open_records`). Without them (None) no state
    short of the target is settled.
    """
    working, proven = proven_and_working(result)
    closure = closure or {}
    held = open_records(records, registry) if records is not None else None
    check_totals(registry, frame, proven, result)
    gains = marginal_gains(registry, frame, working, proven)
    table = _station_table(result)
    stations: dict[str, JSONValue] = {}
    ranked: list[tuple[float, str, dict[str, JSONValue]]] = []
    by_state: dict[str, list[str]] = defaultdict(list)
    for station in sorted(registry.stations.values(), key=lambda s: s.id):
        entry = table.get(station.id)
        state = str(entry.get("state")) if isinstance(entry, dict) else "not_read"
        reason = entry.get("reason") if isinstance(entry, dict) else None
        own, former = set(current_keys(station)), set(former_keys(station))
        since = readable_since(census, proving_keys(station))
        until = blind_since(census, proving_keys(station))
        days = closure.get(station.id, frozenset())
        near = near_days(station.id, storms, days) if storms is not None else frozenset()
        keys = [
            key_census(
                census,
                station.id,
                key,
                storms,
                current=key in own,
                former=key in former,
                closure=days,
                near=near,
                since=since,
                until=blind_since(census, [key]),
            )
            for key in station_keys(station)
        ]
        code = verdict(
            state, station.id in proven, keys, station.status, storm_days=storms is not None
        )
        gain = gains.get(station.id)
        stations[station.id] = {
            "name": station.name,
            "platform": station.platform,
            "market": station.market,
            "states": list(station.states),
            "status": station.status.value,
            "state": state,
            "reason": reason,
            "proven": station.id in proven,
            "district_level": bool(station.leaids),
            "gain": gain.as_json() if gain is not None else None,
            "verdict": code,
            "readable_since": since,
            "blind_since": until,
            "closure_days": len(days),
            "near_days": len(near),
            "window_seen": sum(item.window_seen for item in keys if item.proving),
            "archive": [item.as_json() for item in keys],
        }
        for code_state in station.states:
            by_state[code_state].append(station.id)
        if gain is not None and gain.schools:
            item: dict[str, JSONValue] = {
                "id": station.id,
                "schools": gain.schools,
                "weighted": round(gain.weighted, 1),
                "verdict": code,
            }
            ranked.append((-round(gain.weighted, 1), station.id, item))
    ranking: list[JSONValue] = [item for _, _, item in sorted(ranked, key=lambda x: x[:2])]
    proven_block = result.get("proven")
    if not isinstance(proven_block, dict) or not isinstance(proven_block.get("states"), dict):
        raise GateError("coverage.json has no proven share per state")
    national = _proven_national(result)
    gap, to_target = _gap(national, NATIONAL_TARGET)
    private = frame.filter(pl.col("district_id").is_null()).group_by("state").len().iter_rows()
    private_by_state = {str(state): int(count) for state, count in private}
    states: dict[str, JSONValue] = {}
    state_shares = proven_block["states"]
    assert isinstance(state_shares, dict)  # noqa: S101 - checked above
    for code_state, share in sorted(state_shares.items()):
        if not isinstance(share, dict):
            raise GateError(f"coverage.json's proven share for {code_state} is not a table")
        state_gap, state_to = _gap(share, STATE_TARGET)
        meets = _meets(share)
        still = _open_sources(code_state, by_state.get(code_state, []), stations)
        kept: list[JSONValue] = [item.as_json() for item in (held or {}).get(code_state, [])]
        states[code_state] = {
            "proven": share,
            "meets_target": meets,
            "gap": state_gap,
            "to_target": state_to,
            "private_schools": private_by_state.get(code_state, 0),
            "stations": list(by_state.get(code_state, [])),
            "settled": meets or (held is not None and not still and not kept),
            "open": [] if meets else still,
            "open_records": [] if meets else kept,
        }
    covered_states = result.get("states")
    return {
        "generated_at": iso_utc(now),
        "coverage": dict(coverage_file),
        "targets": {"national": NATIONAL_TARGET, "state": STATE_TARGET},
        "owner_gate": owner_gate(
            state_shares,
            covered_states if isinstance(covered_states, dict) else {},
            national,
            checked=_dict_at(proven_block, "market_checked"),
            counties=_dict_at(result, "counties"),
            proven_counties=_dict_at(proven_block, "counties"),
            pandemic=_dict_at(proven_block, "pandemic_checked"),
        ),
        "national": {
            "proven": national,
            "meets_target": _meets(national),
            "gap": gap,
            "to_target": to_target,
            "settled": all(
                isinstance(entry, dict) and entry.get("settled") is True
                for entry in states.values()
            ),
        },
        "states": states,
        "stations": stations,
        "ranking": ranking,
        "calibration": (
            calibration(registry, reads, proven, storms, result) if storms is not None else None
        ),
        **dma_report(result, working, proven),
    }


# The owner's gate ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Acceptance:
    """The owner's acceptance of a dig state's proven shares as they stood, under the target.

    The state then meets while its exact proven shares stay at least the figures the owner
    accepted (:attr:`plain` and :attr:`weighted`), and fails the gate if either drops below
    them; reaching the target meets as it would without the acceptance.
    """

    decided_on: date
    quote: str
    plain: float
    weighted: float
    note: str


@dataclass(frozen=True, slots=True)
class OwnerGate:
    """The coverage gate the project owner set, in place of 90% in every state.

    Decided on 2026-10-13 (about 7:45 AM Central): "dig for 90%+ of Idaho and Wyoming
    and leave it there". So the gate passes when (1) each of :attr:`dig` is at least
    :attr:`state_target` proven, plain and closure-weighted; (2) the national
    closure-weighted proven share is at least :attr:`national_weighted`; (3) every state
    not in :attr:`dig` or :attr:`rare` stays at the state target, plain and weighted (it
    was there on 2026-10-13: Utah and Alabama at 100%, Texas at 91.3%). The states in
    :attr:`rare` (where closures are rare: the ones below the target at the decision) are
    not dug further: each keeps an honest record of what is covered, what is proven and
    what is missing, marked :data:`NOT_PURSUED`, and is never called met or settled on
    that account.

    A later decision can accept a dig state's proven shares as they stand, under the
    target (:attr:`accepted`): the gate stores the accepted figures with the decision, the
    state meets while its exact shares stay at least those figures and fails if either drops
    below them, and its line records its shares exactly (never rounded up) with the
    acceptance. Wyoming's were accepted on 2026-10-13 at 85.8% plain and 87.7%
    closure-weighted ("yea call it done nw": Wyoming is done at its honest numbers; its last
    schools prove themselves on a real storm-day read once live). Idaho keeps the target,
    plain and weighted.
    """

    decided_on: date
    quote: str
    dig: tuple[str, ...]
    rare: tuple[str, ...]
    state_target: float
    national_weighted: float
    accepted: Mapping[str, Acceptance] = field(default_factory=dict)


ACCEPTED = "accepted: owner decision 2026-10-13"
"""The note a dig state's line carries when the owner accepted its shares as they stood."""

OWNER_GATE = OwnerGate(
    decided_on=date(2026, 10, 13),
    quote="dig for 90%+ of Idaho and Wyoming and leave it there",
    dig=("ID", "WY"),
    rare=("AZ", "CA", "FL", "LA", "MS", "NV"),
    state_target=STATE_TARGET,
    national_weighted=NATIONAL_TARGET,
    accepted={
        "WY": Acceptance(
            decided_on=date(2026, 10, 13),
            quote="yea call it done nw",
            plain=0.858,
            weighted=0.877,
            note=ACCEPTED,
        )
    },
)
NOT_PURSUED = "not pursued: owner decision 2026-10-13 (rare-closure state)"
"""The note every record of a :attr:`OwnerGate.rare` state carries."""


def _dict_at(table: Mapping[str, JSONValue], key: str) -> dict[str, JSONValue] | None:
    value = table.get(key)
    return value if isinstance(value, dict) else None


def _fraction(share: JSONValue, *path: str) -> float | None:
    value: JSONValue = share
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return float(value) if isinstance(value, int | float) else None


def _at_least(share: JSONValue, target: float, *path: str) -> bool:
    """Whether a coverage share (at ``path``) is at least ``target``, never rounded up.

    ``coverage.json`` rounds each share to four decimals, so a true 89.997% is stored as
    0.9. The decision is made on what is exact: a plain share's integer counts
    (``covered`` / ``schools``), and the measure's own ``meets_target`` (computed by
    :func:`snowlight.sources.stations.coverage._share` on the unrounded ratio, against
    the same targets the owner's gate uses) when it says no. The rounded ``share`` must
    reach the target too.
    """
    value: JSONValue = share
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    if not isinstance(value, dict) or value.get("meets_target") is False:
        return False
    found = value.get("share")
    if not isinstance(found, int | float) or isinstance(found, bool) or found < target:
        return False
    schools, covered = value.get("schools"), value.get("covered")
    if (
        not path
        and isinstance(schools, int)
        and not isinstance(schools, bool)
        and isinstance(covered, int)
        and not isinstance(covered, bool)
        and schools > 0
    ):
        return covered >= target * schools
    return True


def _at_least_figure(share: JSONValue, figure: float, *path: str) -> bool:
    """Whether a coverage share (at ``path``) is at least an accepted ``figure``, exactly.

    Both the four-decimal ``share`` and the counts (``covered`` / ``schools``) must reach
    it; the measure's own ``meets_target`` is against the target, not the figure. A plain
    share's counts are whole schools, so it is decided exactly; a closure-weighted share's
    are coverage's, kept to a tenth of a weighted school.
    """
    value: JSONValue = share
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    if not isinstance(value, dict):
        return False
    found = value.get("share")
    if not isinstance(found, int | float) or isinstance(found, bool) or found < figure:
        return False
    schools, covered = value.get("schools"), value.get("covered")
    if (
        isinstance(schools, int | float)
        and not isinstance(schools, bool)
        and isinstance(covered, int | float)
        and not isinstance(covered, bool)
        and schools > 0
    ):
        return covered >= figure * schools
    return True


def _state_line(
    code: str,
    proven: JSONValue,
    covered: JSONValue,
    target: float,
    accepted: Acceptance | None = None,
) -> dict[str, JSONValue]:
    """One state's shares under the owner's gate: covered and proven, plain and weighted.

    With ``accepted`` (the owner accepted the state's shares as they stood, under the
    target), the state meets while both exact shares stay at least the accepted figures (or
    reach the target); the line says so under ``rule`` and ``accepted`` and keeps its shares
    exactly as measured.
    """
    plain, weighted = _fraction(proven, "share"), _fraction(proven, "weighted", "share")
    schools = _fraction(proven, "schools")
    proven_schools = _fraction(proven, "covered")
    covered_schools = _fraction(covered, "covered")
    return {
        "state": code,
        "schools": int(schools) if schools is not None else None,
        "covered": {
            "schools": int(covered_schools) if covered_schools is not None else None,
            "share": _fraction(covered, "share"),
            "weighted_share": _fraction(covered, "weighted", "share"),
        },
        "proven": {
            "schools": int(proven_schools) if proven_schools is not None else None,
            "share": plain,
            "weighted_share": weighted,
        },
        "missing": {
            "uncovered": int(schools - covered_schools)
            if schools is not None and covered_schools is not None
            else None,
            "covered_unproven": int(covered_schools - proven_schools)
            if covered_schools is not None and proven_schools is not None
            else None,
        },
        "rule": (
            f"proven at least {_pct(accepted.plain)} plain and {_pct(accepted.weighted)} "
            f"closure-weighted, {accepted.note} (target {_pct(target)})"
            if accepted is not None
            else f"proven at least {_pct(target)}, plain and closure-weighted"
        ),
        "accepted": (
            {
                "note": accepted.note,
                "decided_on": accepted.decided_on.isoformat(),
                "quote": accepted.quote,
                "plain": accepted.plain,
                "weighted": accepted.weighted,
                "weighted_measured": _pct(weighted) if weighted is not None else None,
                "plain_measured": (
                    f"{_pct(plain)} ({int(proven_schools)} of {int(schools)} schools)"
                    if plain is not None and proven_schools is not None and schools is not None
                    else None
                ),
            }
            if accepted is not None
            else None
        ),
        "meets": plain is not None
        and weighted is not None
        and (
            (_at_least(proven, target) and _at_least(proven, target, "weighted"))
            or (
                accepted is not None
                and _at_least_figure(proven, accepted.plain)
                and _at_least_figure(proven, accepted.weighted, "weighted")
            )
        ),
    }


THIN_MARGIN = 0.92
"""A kept state under this share (plain or weighted) is listed with its margin over the target:
one false proof there could take it under."""


def _market_check(
    code: str,
    checked: Mapping[str, JSONValue],
    counties: Mapping[str, JSONValue],
    proven_counties: Mapping[str, JSONValue],
    target: float,
) -> dict[str, JSONValue] | None:
    """A state's proven shares with no county credited across a state line by a market alone
    (``proven.market_checked`` of ``coverage.json``), and the credits so assumed."""
    states = checked.get("states")
    share = states.get(code) if isinstance(states, dict) else None
    if not isinstance(share, dict):
        return None
    assumed = checked.get("assumed")
    assumed_credits: list[JSONValue] = []
    for station_id, fips_list in sorted(assumed.items()) if isinstance(assumed, dict) else []:
        mine: list[str] = []
        for fips in fips_list if isinstance(fips_list, list) else []:
            county = counties.get(str(fips))
            shown = proven_counties.get(str(fips))
            proven_here = shown.get("proven") if isinstance(shown, dict) else None
            if (
                isinstance(county, dict)
                and county.get("state") == code
                and isinstance(proven_here, list)
                and station_id in proven_here
            ):
                mine.append(str(fips))
        if mine:
            schools = sum(
                int(str(entry.get("schools", 0)))
                for entry in (counties.get(fips) for fips in mine)
                if isinstance(entry, dict)
            )
            assumed_credits.append(
                {"station": station_id, "counties": list(mine), "schools": schools}
            )
    weighted = share.get("weighted")
    return {
        "rule": checked.get("rule"),
        "schools": share.get("covered"),
        "share": share.get("share"),
        "weighted_share": weighted.get("share") if isinstance(weighted, dict) else None,
        "meets": _at_least(share, target) and _at_least(share, target, "weighted"),
        "assumed_credits": assumed_credits,
    }


def _pandemic_check(
    code: str, pandemic: Mapping[str, JSONValue], line: Mapping[str, JSONValue]
) -> dict[str, JSONValue] | None:
    """A state's proven shares without the lists seen only with the pandemic's closings."""
    states = pandemic.get("states")
    share = states.get(code) if isinstance(states, dict) else None
    proven = line.get("proven")
    if not isinstance(share, dict) or not isinstance(proven, dict):
        return None
    if share.get("covered") == proven.get("schools"):
        return None
    return {
        "rule": pandemic.get("rule"),
        "stations": pandemic.get("stations"),
        "schools": share.get("covered"),
        "share": share.get("share"),
        "weighted_share": _fraction(share, "weighted", "share"),
    }


def _thin(line: Mapping[str, JSONValue], target: float) -> dict[str, JSONValue] | None:
    """A kept state's margin over the target when its proven share is under
    :data:`THIN_MARGIN`: how many schools it may lose and still meet it."""
    proven = line.get("proven")
    if not isinstance(proven, dict):
        return None
    plain, weighted = proven.get("share"), proven.get("weighted_share")
    schools, covered = line.get("schools"), proven.get("schools")
    if not isinstance(plain, float | int) or not isinstance(weighted, float | int):
        return None
    if min(plain, weighted) >= THIN_MARGIN:
        return None
    margin = (
        int(covered) - math.ceil(target * int(schools) - 1e-9)
        if isinstance(schools, int) and isinstance(covered, int)
        else None
    )
    return {"state": line.get("state"), "share": plain, "weighted_share": weighted,
            "schools_above_target": margin}  # fmt: skip


def owner_gate(  # noqa: PLR0913 - the shares, the gate, and the market check's tables
    proven_states: Mapping[str, JSONValue],
    covered_states: Mapping[str, JSONValue],
    national: Mapping[str, JSONValue],
    gate: OwnerGate = OWNER_GATE,
    *,
    checked: Mapping[str, JSONValue] | None = None,
    counties: Mapping[str, JSONValue] | None = None,
    proven_counties: Mapping[str, JSONValue] | None = None,
    pandemic: Mapping[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    """The owner's gate over a coverage result's shares (see :class:`OwnerGate`).

    Returns ``{"decided_on", "quote", "passes", "dig": [line, ...], "national":
    {"weighted_share", "target", "meets"}, "kept": {"states", "short": [line, ...],
    "thin": [...]}, "rare": [line + {"note"}, ...]}``; each line is a state's covered and
    proven shares, what it is missing (schools no working source covers, and schools covered
    but not proven) and whether it meets the state target (plain and weighted).

    With ``checked`` (``proven.market_checked`` of ``coverage.json``) and the county tables,
    each dig state's line carries ``market_checked``: its proven shares when no county
    across a state line is credited by a market alone, and each such credit (the station,
    its counties in the state, their schools). The gate is decided on the proven share as
    the coverage measure defines it; the market check says how much of it rests on a
    market's map rather than a row seen, for the owner to weigh. The kept states under
    :data:`THIN_MARGIN` are listed with their margin (``kept.thin``). With ``pandemic``
    (``proven.pandemic_checked``), each dig state's line carries ``pandemic_checked``: its
    shares without the proven lists never seen holding a closing but the pandemic's, when
    they differ.
    """
    lines = {
        code: _state_line(
            code,
            share,
            covered_states.get(code),
            gate.state_target,
            gate.accepted.get(code) if code in gate.dig else None,
        )
        for code, share in sorted(proven_states.items())
    }
    if checked is not None:
        for code in gate.dig:
            if code in lines:
                lines[code]["market_checked"] = _market_check(
                    code, checked, counties or {}, proven_counties or {}, gate.state_target
                )
    for code in gate.dig if pandemic is not None else ():
        if code in lines and pandemic is not None:
            lines[code]["pandemic_checked"] = _pandemic_check(code, pandemic, lines[code])
    dig = [lines[code] for code in gate.dig if code in lines]
    rare = [{**lines[code], "note": NOT_PURSUED} for code in gate.rare if code in lines]
    kept_codes = [code for code in lines if code not in gate.dig and code not in gate.rare]
    short: list[JSONValue] = [
        lines[code] for code in kept_codes if lines[code]["meets"] is not True
    ]
    weighted = _fraction(dict(national), "weighted", "share")
    national_meets = weighted is not None and _at_least(
        dict(national), gate.national_weighted, "weighted"
    )
    thin: list[JSONValue] = []
    for code in kept_codes:
        margin = _thin(lines[code], gate.state_target) if lines[code]["meets"] is True else None
        if margin is not None:
            thin.append(margin)
    checked_national = checked.get("national") if checked is not None else None
    checked_states = checked.get("states") if checked is not None else None
    market_short: list[JSONValue] = []
    for code in kept_codes if isinstance(checked_states, dict) else []:
        share = checked_states.get(code) if isinstance(checked_states, dict) else None
        if not isinstance(share, dict) or lines[code]["meets"] is not True:
            continue
        if not (
            _at_least(share, gate.state_target) and _at_least(share, gate.state_target, "weighted")
        ):
            market_short.append(
                {
                    "state": code,
                    "share": share.get("share"),
                    "weighted_share": _fraction(share, "weighted", "share"),
                }
            )
    dig_meets = len(dig) == len(gate.dig) and all(line["meets"] is True for line in dig)
    return {
        "decided_on": gate.decided_on.isoformat(),
        "quote": gate.quote,
        "passes": dig_meets and national_meets and not short,
        "dig": list(dig),
        "national": {
            "weighted_share": weighted,
            "target": gate.national_weighted,
            "meets": national_meets,
            "market_checked_weighted_share": _fraction(checked_national, "weighted", "share")
            if isinstance(checked_national, dict)
            else None,
        },
        "kept": {
            "states": len(kept_codes),
            "short": short,
            "thin": thin,
            "market_checked_short": market_short,
        },
        "rare": list(rare),
    }


def _open_sources(
    state: str, ids: Iterable[str], stations: Mapping[str, JSONValue]
) -> list[JSONValue]:
    """The sources touching ``state`` whose proof would add to it and whose verdict is open.

    A source is open while its verdict is not :data:`TERMINAL` (nor ``proven`` or
    ``not-working``): an archive read could still prove it. One whose proof would
    add no school in the state (others proven cover all of its) is left out.
    """
    found: list[JSONValue] = []
    for station_id in ids:
        entry = stations.get(station_id)
        if not isinstance(entry, dict):
            continue
        code = entry.get("verdict")
        if code in TERMINAL or code in {"proven", "not-working"}:
            continue
        gain = entry.get("gain")
        by_state = gain.get("by_state") if isinstance(gain, dict) else None
        here = by_state.get(state) if isinstance(by_state, dict) else None
        if not isinstance(here, list) or not any(here):
            continue
        found.append(station_id)
    return found


FRESH_SINCE = datetime(2026, 10, 1, tzinfo=UTC)
"""A first-hand record checked before this can no longer settle a state.

The gap-state part's checks of late September 2026 called some district homepages
"not built" on a glance that no longer held a fortnight later (St. Lucie's WordPress
homepage, with an emergency-alert plugin and Smart Slider sliders a reader here
reads), and some "not read" after one timeout (Corona-Norco and Desert Sands, whose
SharpSchool alert service answers today). Such a record says nothing of today's
site, so a state it touches stays open until the source is checked again."""
NOT_READ = "not read"
"""A record's verdict prefix for a source whose site was never read."""
_POINTER = re.compile(r"^(?:other part's station|belongs to part)[^(]*\(([a-z0-9-]+)")


@dataclass(frozen=True, slots=True)
class OpenRecord:
    """A first-hand record of a source not built that keeps the states it touches open."""

    source_id: str
    states: tuple[str, ...]
    verdict: str
    checked_at: str | None
    why: str
    """``not-read`` (the site was never read), ``unchecked`` (no time of check) or
    ``stale`` (checked before :data:`FRESH_SINCE`)."""

    def as_json(self) -> dict[str, JSONValue]:
        """The record as ``gate.json`` lists it under each state it keeps open."""
        return {
            "source_id": self.source_id,
            "verdict": self.verdict,
            "checked_at": self.checked_at,
            "why": self.why,
        }


def _checked(value: JSONValue) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _record_states(record: Mapping[str, JSONValue]) -> tuple[str, ...]:
    listed = record.get("states")
    found: set[str] = set()
    if isinstance(listed, list):
        found.update(code for code in listed if isinstance(code, str))
    gap_state = record.get("gap_state")
    if isinstance(gap_state, str):
        found.add(gap_state)
    return tuple(sorted(found))


def record_built(record: Mapping[str, JSONValue], registry: Registry) -> bool:
    """Whether a first-hand record describes a source the registry holds.

    A record names its station in ``built_as``, or, when it only points to another
    part's station, in its verdict ("other part's station (gray-wala)"); the gate
    judges such a source by its station, not by the record. The coverage gate's own
    records (a ``gate`` block of this piece) are of registry stations too. A record
    naming a station the registry does not hold is not built.
    """
    block = record.get("gate")
    if isinstance(block, dict) and block.get("piece") == GATE_PIECE:
        return True
    built = record.get("built_as")
    ids = [str(item) for item in built] if isinstance(built, list) else []
    if not ids:
        verdict = record.get("verdict")
        found = _POINTER.match(verdict) if isinstance(verdict, str) else None
        ids = [found.group(1)] if found is not None else []
    return bool(ids) and all(item in registry.stations for item in ids)


def open_records(
    records: Iterable[Mapping[str, JSONValue]],
    registry: Registry,
    *,
    fresh_since: datetime = FRESH_SINCE,
) -> dict[str, list[OpenRecord]]:
    """The first-hand records that keep each state open, by state.

    A record of a source the registry does not hold (:func:`record_built`) keeps
    every state it touches open when its verdict is "not read" (the site was never
    read: a timeout on one day, a refused connection), or when it was checked before
    ``fresh_since`` or carries no time of check: only a check of today's site can say
    that no reader here reads it. Records of registry stations are left out (the
    gate judges the station).
    """
    found: dict[str, list[OpenRecord]] = defaultdict(list)
    for record in records:
        if record_built(record, registry):
            continue
        verdict = str(record.get("verdict") or "")
        checked = _checked(record.get("checked_at"))
        if verdict.startswith(NOT_READ):
            why = "not-read"
        elif checked is None:
            why = "unchecked"
        elif checked < fresh_since:
            why = "stale"
        else:
            continue
        stamp = record.get("checked_at")
        states = _record_states(record)
        item = OpenRecord(
            source_id=str(record.get("source_id")),
            states=states,
            verdict=verdict,
            checked_at=stamp if isinstance(stamp, str) else None,
            why=why,
        )
        for code in states:
            found[code].append(item)
    return dict(found)


BIG_MARKETS = 25
"""The largest markets by schools, which should each have two working sources or more."""


@dataclass(frozen=True, slots=True)
class Market:
    """One market's working and proven sources, whole-county and district-level."""

    schools: int
    working: tuple[str, ...]
    proven: tuple[str, ...]
    working_district: tuple[str, ...]
    proven_district: tuple[str, ...]

    def as_json(self) -> dict[str, JSONValue]:
        """The market as ``gate.json`` records it."""
        return {
            "schools": self.schools,
            "working": list(self.working),
            "proven": list(self.proven),
            "working_district": list(self.working_district),
            "proven_district": list(self.proven_district),
        }


def _ids(value: JSONValue) -> set[str]:
    return {str(item) for item in value} if isinstance(value, list) else set()


def markets(
    result: Mapping[str, JSONValue], working: set[str], proven: set[str]
) -> dict[str, Market]:
    """Each market's sources: ``coverage.json``'s whole-county ones and its counties' districts."""
    table = result.get("dmas")
    counties = result.get("counties")
    if not isinstance(table, dict) or not isinstance(counties, dict):
        return {}
    districts_of: dict[str, set[str]] = defaultdict(set)
    for entry in counties.values():
        if isinstance(entry, dict):
            for label in _ids(entry.get("dmas")):
                districts_of[label] |= _ids(entry.get("districts"))
    found: dict[str, Market] = {}
    for label, info in sorted(table.items()):
        if not isinstance(info, dict):
            continue
        whole = _ids(info.get("working"))
        district = districts_of.get(label, set()) & working
        schools = info.get("schools")
        found[label] = Market(
            schools=int(schools) if isinstance(schools, int) else 0,
            working=tuple(sorted(whole)),
            proven=tuple(sorted(whole & proven)),
            working_district=tuple(sorted(district)),
            proven_district=tuple(sorted(district & proven)),
        )
    return found


def dma_report(
    result: Mapping[str, JSONValue], working: set[str], proven: set[str]
) -> dict[str, JSONValue]:
    """The market table and summary of ``gate.json``.

    A market has a working source when a whole-county source or a district-level
    source with schools in its counties works there; ``biggest_by_schools`` lists
    the largest markets, which should each have two working sources or more.
    """
    found = markets(result, working, proven)
    biggest = sorted(found.items(), key=lambda item: (-item[1].schools, item[0]))[:BIG_MARKETS]
    summary: dict[str, JSONValue] = {
        "markets": len(found),
        "with_a_working_source": sum(bool(m.working or m.working_district) for m in found.values()),
        "with_a_whole_county_source": sum(bool(m.working) for m in found.values()),
        "with_a_proven_source": sum(bool(m.proven or m.proven_district) for m in found.values()),
        "biggest_by_schools": [
            {
                "dma": label,
                "schools": market.schools,
                "working": len(market.working),
                "working_district": len(market.working_district),
                "proven": len(market.proven),
            }
            for label, market in biggest
        ],
    }
    return {
        "dmas": {label: market.as_json() for label, market in found.items()},
        "dma_summary": summary,
    }


def file_record(path: Path, result: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """The coverage file the report was built from: path, SHA-256 and generation time."""
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "generated_at": result.get("generated_at"),
    }


def load_result(path: Path) -> dict[str, JSONValue]:
    """Read ``coverage.json``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise GateError(f"{path}: {error}") from error
    if not isinstance(data, dict):
        raise GateError(f"{path}: not a JSON object")
    return data


def write_report(out_dir: Path, report: Mapping[str, JSONValue]) -> Path:
    """Write ``gate.json`` (internal)."""
    path = out_dir / GATE_FILE
    write_json(path, dict(report))
    return path


# The capture plan -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanOptions:
    """What :func:`plan_captures` picks."""

    limit: int = 250
    per_station: int = 25
    min_weighted: float = 5.0
    """Leave out stations whose proof would add less closure weight than this."""
    min_score: float = 0.05
    """A storm day's score (the market's mean warning weight) at least this."""
    outlier_ratio: float = 1.08
    """A capture at least this many times its winter's median size counts as large."""
    only: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class PlannedCapture:
    """One capture to ask the archive for, with why it was picked."""

    timestamp: str
    url: str
    station: str
    why: str

    def as_json(self) -> dict[str, JSONValue]:
        """The capture as the request file and the wanted-captures record list it."""
        return {
            "timestamp": self.timestamp,
            "url": self.url,
            "station": self.station,
            "why": self.why,
        }


def readable_since(census: Census, keys: Sequence[str]) -> str | None:
    """The capture time before which a station's page was in a form its adapter refuses.

    Among the read captures of ``keys``: the latest one the adapter refused
    (``error``), or read as a page whose list the archive does not hold (``shell``),
    that is older than the earliest one it read (any other state but
    a capture that held no page of its own: ``gone``, ``redirect``, ``replaced``), as
    a ``YYYYMMDDhhmmss`` timestamp; None when no refused read precedes a read one
    (or nothing was read), so no capture is left out. A district that moved its
    homepage to the platform its adapter reads leaves refused captures of its old
    site before that time, and asking for more of them would prove nothing.
    """
    wanted = set(keys)
    reads = [
        (stamp, state)
        for (stamp, key), state in census.read.items()
        if key in wanted and state != "replaced"
    ]
    read = [stamp for stamp, state in reads if state not in _NO_LIST and state not in _NO_PAGE]
    if not read:
        return None
    first = min(read)
    refused = [stamp for stamp, state in reads if state in _NO_LIST and stamp < first]
    return max(refused) if refused else None


BLIND_STATES = frozenset({"deferred", "redirect", "error", "shell", "gone", "refused", "cut"})
"""Read states that did not see the list: a page shell, a redirect, a refusal, a 404, a
page the archive cut off before its list."""


def blind_since(census: Census, keys: Sequence[str]) -> str | None:
    """The capture time from which a station's page holds no list a read can see.

    The report and the due plan ask it of each key alone: a page that took to loading
    its list by script (Granite's homepage, from 2023-03-10) says nothing of the file it
    loads (its ``wp-json`` notifications, captured through 2026), whose captures stay due.

    Among the read captures of ``keys`` made after the last one that saw the list
    (:data:`LIST_SEEN`; any, when none did): when there are at least
    :data:`SHELL_READS` of them and none saw the list (each a page that loads its
    list by script, a redirect or a refusal), the earliest of them, as a
    ``YYYYMMDDhhmmss`` timestamp; otherwise None. A district whose homepage moved
    to a template that loads its notices by script (a Finalsite homepage that
    asks ``/fs/pages/<id>/page-pops``, which the archive almost never holds), or
    to a platform no adapter reads, leaves captures after that time that cannot
    show the list, and asking for more of them would prove nothing: they are not
    due (:func:`key_census`), as those before :func:`readable_since` are not.
    """
    wanted = set(keys)
    reads = sorted(
        (stamp, state)
        for (stamp, key), state in census.read.items()
        if key in wanted and state != "replaced"
    )
    seen = [stamp for stamp, state in reads if state in LIST_SEEN]
    last = max(seen) if seen else ""
    after = [(stamp, state) for stamp, state in reads if stamp > last]
    if len(after) < SHELL_READS or any(state not in BLIND_STATES for _, state in after):
        return None
    return after[0][0]


def _unread(
    census: Census, keys: Sequence[str], done: set[tuple[str, str]]
) -> list[tuple[Capture, str]]:
    pool: list[tuple[Capture, str]] = []
    for key in keys:
        known = census.digest_states(key)
        for capture in census.listings.get(key, []):
            if capture.status != "200" or capture.digest in known:
                continue
            if (capture.timestamp, key) in done or (capture.timestamp, key) in census.read:
                continue
            pool.append((capture, key))
    return pool


def _large(
    census: Census, pool: Sequence[tuple[Capture, str]], ratio: float
) -> list[tuple[float, Capture, str, float]]:
    sizes: dict[tuple[str, int], list[int]] = defaultdict(list)
    for key in {key for _, key in pool}:
        for capture in census.listings.get(key, []):
            season = winter_season(capture.when)
            if season is not None and capture.status == "200" and capture.length:
                sizes[(key, season)].append(capture.length)
    found: list[tuple[float, Capture, str, float]] = []
    for capture, key in pool:
        season = winter_season(capture.when)
        if season is None or not capture.length or not sizes.get((key, season)):
            continue
        middle = statistics.median(sizes[(key, season)])
        if middle and capture.length / middle >= ratio:
            found.append((capture.length / middle, capture, key, middle))
    found.sort(key=lambda item: (-item[0], item[1].timestamp))
    return found


def plan_captures(  # noqa: PLR0913 - the plan joins the ranking, the census and the storm days
    registry: Registry,
    ranking: Sequence[Mapping[str, JSONValue]],
    census: Census,
    done: set[tuple[str, str]],
    *,
    storms: StormDays | None,
    options: PlanOptions | None = None,
) -> list[PlannedCapture]:
    """Pick unread captures of the unproven stations that would add the most closure weight.

    Stations are taken in the ranking's order (closure-weighted gain first), and
    for each, among the captures of its current page and data file and of its own
    former addresses (:func:`proving_keys`, the only reads that can prove it): its unread captures
    on storm days (strongest first; one per URL and day), then the largest of its
    winters' captures, never two with one digest, up to ``per_station``, until
    ``limit`` captures are picked. Captures from before the page took a form its
    adapter reads are left out (:func:`readable_since`).
    """
    options = options or PlanOptions()
    plan: list[PlannedCapture] = []
    taken: set[tuple[str, str]] = set()
    for item in ranking:
        if len(plan) >= options.limit:
            break
        station_id = str(item.get("id"))
        weighted = item.get("weighted")
        if not isinstance(weighted, int | float) or weighted < options.min_weighted:
            continue
        if options.only is not None and station_id not in options.only:
            continue
        station = registry.stations.get(station_id)
        if station is None:
            raise GateError(f"the ranking names {station_id}, which the registry lacks")
        keys = proving_keys(station)
        since = readable_since(census, keys)
        pool = [
            (capture, key)
            for capture, key in _unread(census, keys, done)
            if since is None or capture.timestamp > since
        ]
        room = min(options.per_station, options.limit - len(plan))
        picked = _pick(
            station_id, pool, census, storms=storms, options=options, room=room, taken=taken
        )
        plan.extend(picked)
    return plan


def _pick(  # noqa: PLR0913 - one station's share of the plan
    station_id: str,
    pool: Sequence[tuple[Capture, str]],
    census: Census,
    *,
    storms: StormDays | None,
    options: PlanOptions,
    room: int,
    taken: set[tuple[str, str]],
) -> list[PlannedCapture]:
    picked: list[PlannedCapture] = []
    digests: set[str] = set()
    days: set[tuple[str, date]] = set()

    def add(capture: Capture, key: str, why: str) -> None:
        if len(picked) >= room or capture.digest in digests:
            return
        if (capture.timestamp, key) in taken:
            return
        digests.add(capture.digest)
        taken.add((capture.timestamp, key))
        picked.append(PlannedCapture(capture.timestamp, capture.original, station_id, why))

    if storms is not None:
        scored = [(storms.score(station_id, capture.when), capture, key) for capture, key in pool]
        scored = [entry for entry in scored if entry[0] >= options.min_score]
        scored.sort(key=lambda entry: (-entry[0], -(entry[1].length or 0), entry[1].timestamp))
        for score, capture, key in scored:
            day = school_day(capture.when)
            if (key, day) in days:
                continue
            days.add((key, day))
            add(capture, key, f"storm day {day.isoformat()} (market score {score:.2f})")
    for ratio, capture, key, middle in _large(census, pool, options.outlier_ratio):
        add(
            capture,
            key,
            f"largest captures of its winter ({capture.length} bytes, {ratio:.2f} x the "
            f"winter's median of {middle:.0f})",
        )
    return picked


@dataclass(frozen=True, slots=True)
class DueOptions:
    """What :func:`plan_due` picks."""

    limit: int = 250
    first: int = 3
    """Captures per source in the first pass (its strongest storm days first)."""
    only: frozenset[str] | None = None
    """The sources to plan; with it, a named source is planned even when it keeps no state
    open (one whose proof would add no school, its schools proven by another source), so
    that every source touching a short state can be settled."""
    skip: frozenset[tuple[str, str]] = frozenset()
    """(Timestamp, URL key) of captures already asked for by runs not downloaded yet."""


@dataclass(frozen=True, slots=True)
class DuePlan:
    """The due captures to ask for, and the addresses still to list."""

    snapshots: list[PlannedCapture]
    listings: list[dict[str, JSONValue]]

    def as_json(self) -> dict[str, JSONValue]:
        """The plan as the archive request file takes it."""
        snapshots: list[JSONValue] = [item.as_json() for item in self.snapshots]
        listings: list[JSONValue] = [dict(item) for item in self.listings]
        found: dict[str, JSONValue] = {"snapshots": snapshots}
        if listings:
            found["cdx"] = listings
        return found


def open_sources(report: Mapping[str, JSONValue]) -> list[str]:
    """Every open source of the states short of the target, closure-weighted gain first."""
    states = report.get("states")
    stations = report.get("stations")
    if not isinstance(states, dict) or not isinstance(stations, dict):
        raise GateError("the gate report has no state or station table")
    ids: set[str] = set()
    for entry in states.values():
        still = entry.get("open") if isinstance(entry, dict) else None
        if isinstance(still, list):
            ids.update(str(item) for item in still)

    def weight(station_id: str) -> float:
        entry = stations.get(station_id)
        gain = entry.get("gain") if isinstance(entry, dict) else None
        value = gain.get("weighted") if isinstance(gain, dict) else None
        return float(value) if isinstance(value, int | float) else 0.0

    return sorted(ids, key=lambda station_id: (-weight(station_id), station_id))


def _due_pool(  # noqa: PLR0913 - the station, its days and what is already read or asked
    census: Census,
    station_id: str,
    keys: Sequence[str],
    *,
    storms: StormDays,
    closure: Collection[date],
    since: str | None,
    taken: set[tuple[str, str]],
) -> list[tuple[float, Capture, str]]:
    """A station's unread captures in its closure window, as (score, capture, key).

    Captures from before ``since`` (:func:`readable_since`) are left out, and so are a
    key's captures from after it became blind (:func:`blind_since` of that key alone:
    a page that took to loading its list by script hides nothing of the file it loads).

    The score is the storm score on a storm day, 0 on a proven-list day and
    :data:`_NEAR` on a day near one of them (:func:`near_days`), so storm days
    come first. A revisit record replays an earlier capture with its digest; it is
    asked for by that capture's own time when the listings hold it (the archive
    serves the same bytes), so one digest is asked for once.
    """
    near = near_days(station_id, storms, closure)
    pool: list[tuple[float, Capture, str]] = []
    for key in keys:
        until = blind_since(census, [key])
        known = census.digest_states(key)
        originals = {
            capture.digest: capture
            for capture in census.listings.get(key, [])
            if capture.status == "200"
        }
        for capture in census.listings.get(key, []):
            if capture.digest in known or (capture.timestamp, key) in census.read:
                continue
            if not _in_form(capture.timestamp, since, until):
                continue
            score = storms.score(station_id, capture.when)
            day = school_day(capture.when)
            if score <= 0 and day not in closure:
                if day not in near:
                    continue
                score = _NEAR
            asked = originals.get(capture.digest, capture) if capture.status == REVISIT else capture
            if (asked.timestamp, key) in taken:
                continue
            pool.append((score, asked, key))
    pool.sort(key=lambda item: (-item[0], -(item[1].length or 0), item[1].timestamp))
    return pool


_NEVER_SEEN = -1.0
"""The plan's mark for a capture asked for because no read has seen the list yet."""
_OLDER = -2.0
"""The plan's mark for a capture of an earlier address of an older-unread source."""
_NEAR = -0.5
"""The plan's mark for a capture made near one of the station's closure days."""


def _left(
    census: Census, keys: Sequence[str], taken: set[tuple[str, str]]
) -> list[tuple[Capture, str]]:
    """Every unread capture of ``keys``, a revisit asked for by its original's time."""
    found: list[tuple[Capture, str]] = []
    for key in keys:
        known = census.digest_states(key)
        listed = census.listings.get(key, [])
        originals = {capture.digest: capture for capture in listed if capture.status == "200"}
        for capture in listed:
            if capture.digest in known or (capture.timestamp, key) in census.read:
                continue
            asked = originals.get(capture.digest, capture) if capture.status == REVISIT else capture
            if (asked.timestamp, key) not in taken and (asked, key) not in found:
                found.append((asked, key))
    return found


def _reads_of(census: Census, keys: Sequence[str]) -> int:
    """How many captures of ``keys`` were read."""
    wanted = set(keys)
    return sum(1 for _, key in census.read if key in wanted)


def _never_seen(census: Census, keys: Sequence[str]) -> bool:
    """Whether no read of ``keys`` saw the list itself (:data:`LIST_SEEN`)."""
    wanted = set(keys)
    return not any(state in LIST_SEEN for (_, key), state in census.read.items() if key in wanted)


def _unlisted(census: Census, keys: Sequence[str], station_id: str) -> list[dict[str, JSONValue]]:
    return [
        {
            "url": key,
            "from": "20170101",
            "to": "20260930",
            "filter": ["statuscode:200"],
            "collapse": "timestamp:10",
            "station": station_id,
            "why": "never listed: an address of the source's list, so no verdict but "
            "not-listed could be given; listed to learn what the archive holds of it",
        }
        for key in keys
        if not census.listings.get(key) and not census.asked(key)
    ]


def plan_due(  # noqa: PLR0913 - the plan joins the report, the census and the days
    registry: Registry,
    report: Mapping[str, JSONValue],
    census: Census,
    done: set[tuple[str, str]],
    *,
    storms: StormDays,
    closure: Mapping[str, Collection[date]],
    options: DueOptions | None = None,
) -> DuePlan:
    """Pick the due captures of every open source of the states short of the target.

    The sources are those :func:`open_sources` names, closure-weighted gain first
    (with ``options.only``, those of them it names, then the other sources it names).
    For each, the captures that keep it open: its unread captures in its closure
    window (storm days, strongest first, its proven-list days, then the days within
    :data:`NEAR_DAYS` of them), from after its
    page took a form its adapter reads; a source whose list was never seen and
    has no due capture left gets its largest captures, until :data:`SHELL_READS`
    of its captures are read; an address of its list never listed is listed. A
    first pass takes up to ``first`` captures of each source, so the likeliest
    proof of every source is read in the first run; a second takes the rest in
    order, until ``limit``.
    """
    options = options or DueOptions()
    taken: set[tuple[str, str]] = set(done) | set(options.skip)
    pools: list[tuple[str, list[tuple[float, Capture, str]]]] = []
    listings: list[dict[str, JSONValue]] = []
    ordered = open_sources(report)
    if options.only is not None:
        ordered = [item for item in ordered if item in options.only]
        ordered += sorted(options.only - set(ordered))
    for station_id in ordered:
        station = registry.stations.get(station_id)
        if station is None:
            raise GateError(f"the report names {station_id}, which the registry lacks")
        keys = proving_keys(station)
        listings += _unlisted(census, keys, station_id)
        since = readable_since(census, keys)
        pool = _due_pool(
            census,
            station_id,
            keys,
            storms=storms,
            closure=closure.get(station_id, frozenset()),
            since=since,
            taken=taken,
        )
        reads = _reads_of(census, keys)
        if not pool and _never_seen(census, keys) and reads < SHELL_READS:
            fair = [
                (_NEVER_SEEN, capture, key)
                for capture, key in _unread(census, keys, taken)
                if since is None or capture.timestamp > since
            ]
            fair.sort(key=lambda item: (-(item[1].length or 0), item[1].timestamp))
            pool = fair[: SHELL_READS - reads]
        if not pool and not _unread(census, keys, set()):
            # Older-unread: only captures of addresses that cannot prove it are left;
            # reading them settles it as all-read (or proves it unreadable).
            others = [key for key in station_keys(station) if key not in set(keys)]
            pool = [(_OLDER, capture, key) for capture, key in _left(census, others, taken)]
        pools.append((station_id, pool))
    plan: list[PlannedCapture] = []
    asked: set[tuple[str, str]] = set()

    def add(station_id: str, score: float, capture: Capture, key: str) -> None:
        if len(plan) >= options.limit or (capture.timestamp, key) in asked:
            return
        asked.add((capture.timestamp, key))
        day = school_day(capture.when).isoformat()
        if score > 0:
            why = f"storm day {day} (market score {score:.2f})"
        elif score == _NEVER_SEEN:
            why = f"{day}: one of its largest captures, as no read has seen its list yet"
        elif score == _OLDER:
            why = (
                f"{day}: an unread capture of an earlier address of its list, the last left "
                "(read so that every capture of it is read)"
            )
        elif score == _NEAR:
            why = f"{day}: within {NEAR_DAYS} days of one of its closure days"
        else:
            why = f"{day}: a day a proven list sharing its counties held a row"
        plan.append(PlannedCapture(capture.timestamp, capture.original, station_id, why))

    for station_id, pool in pools:
        for score, capture, key in pool[: options.first]:
            add(station_id, score, capture, key)
    for station_id, pool in pools:
        for score, capture, key in pool[options.first :]:
            add(station_id, score, capture, key)
    return DuePlan(plan, listings)


_HOP = re.compile(r"/web/(?P<stamp>[0-9]{14})id_/(?P<url>.+)$")


def redirected_captures(records: Iterable[SnapshotRecord]) -> dict[tuple[str, str], str]:
    """Map each capture the archive answered with a redirect to another address to ``redirect``.

    A snapshot request names a capture (its timestamp and URL); the archive may
    first move to the nearest capture of the same URL, and that capture may be a
    redirect (301, 302) to another address, whose capture the workflow then
    reads. The redirecting capture holds no list of its own; it was read all the
    same (the workflow followed it), so the census counts it as read, with the
    state ``redirect``. The capture on the other side is counted under its own
    address, by the read of its body.
    """
    found: dict[tuple[str, str], str] = {}
    for record in records:
        stamp, key = record.timestamp, url_key(record.url)
        for hop in record.hops:
            matched = _HOP.search(str(hop.get("location", "")))
            if matched is None:
                break
            if url_key(matched["url"]) != key:
                found.setdefault((stamp, key), "redirect")
                break
            stamp = matched["stamp"]
    return found


GONE_ERRORS = frozenset({"HTTP 403", "HTTP 404", "HTTP 410"})
"""Snapshot errors that mean the archive replayed the capture as a page that is not there
(404, 410) or that the site refused the archive's crawler (403); a 403 is never retried."""


def missing_captures(records: Iterable[SnapshotRecord]) -> dict[tuple[str, str], str]:
    """Map each capture the archive replayed as HTTP 403, 404 or 410 to ``gone``.

    The archive replays a capture with the status the site sent (the ``id_``
    form), so a capture it answers with 404 or 410 is one of a page that was not
    there: a revisit record of an address that answered 404 (whose first capture
    the listings may file under another form of the URL), or a page the site had
    removed; one it answers with 403 is the site's refusal of the archive's
    crawler (never asked for again). It holds no list; it was read all the same,
    so the census counts it as read, with the state ``gone``.
    """
    found: dict[tuple[str, str], str] = {}
    for record in records:
        if record.file is not None or record.error not in GONE_ERRORS:
            continue
        found.setdefault((record.timestamp, url_key(record.url)), "gone")
        if record.final_timestamp is not None:
            final = (record.final_timestamp, url_key(record.final_original or record.url))
            found.setdefault(final, "gone")
    return found


REFUSED_ERROR = "HTTP 429"
REFUSED_HOURS = 3
"""Different hours in which a capture was asked for and answered 429 (each time after the
workflow's own retries with backoff) before it counts as refused."""


def refused_captures(records: Iterable[SnapshotRecord]) -> dict[tuple[str, str], str]:
    """Map each capture the archive answers with a replayed refusal to ``refused``.

    A 429 is the archive's own answer when it is asked too fast, and the workflow
    retries it with backoff (four tries over two and a half minutes); but a
    capture whose crawl met the site's own rate limit (a revisit record of that
    answer) is replayed as 429 every time it is asked for. A capture asked for
    directly (no redirect on the way), answered 429 in at least
    :data:`REFUSED_HOURS` different hours (by separate runs, which read other
    captures meanwhile) and never served, is such a replay: it holds no list, and
    asking again gives the same answer. The census counts it as read, with the
    state ``refused``.
    """
    hours: dict[tuple[str, str], set[str]] = defaultdict(set)
    served: set[tuple[str, str]] = set()
    for record in records:
        capture = (record.timestamp, url_key(record.url))
        if record.file is not None:
            served.add(capture)
            continue
        if record.error == REFUSED_ERROR and not record.hops and record.retrieved_at:
            hours[capture].add(record.retrieved_at[:13])
    return {
        capture: "refused"
        for capture, seen in hours.items()
        if len(seen) >= REFUSED_HOURS and capture not in served
    }


def replaced_captures(records: Iterable[SnapshotRecord]) -> dict[tuple[str, str], str]:
    """Map each capture the archive answered with another of the same address to ``replaced``.

    Asked for a capture it cannot replay (a revisit whose payload it lacks), the
    archive moves to the nearest capture of the same address that it can, and the
    read of that body is filed under that capture's time. The capture asked for is
    never served; asking again gives the same substitute. The census counts it as
    read, with the state ``replaced`` (it neither saw nor missed the list).
    """
    found: dict[tuple[str, str], str] = {}
    for record in records:
        if record.file is None or record.final_timestamp in {None, record.timestamp}:
            continue
        key = url_key(record.url)
        if url_key(record.final_original or record.url) == key:
            found.setdefault((record.timestamp, key), "replaced")
    return found


def census_from_files(
    artifacts: Path,
    archive_reads: Sequence[ListingRead],
    archive_health: Sequence[SourceHealth],
    checks: Checked | None = None,
) -> Census:
    """Build the census from the artifacts folder and the archive's reads and failures.

    Captures the archive answered with a redirect to another address count as read
    (:func:`redirected_captures`), and so do those it replayed as a page that was
    not there (:func:`missing_captures`), those it answered with another
    capture of the same address (:func:`replaced_captures`) and those it replays
    as the site's refusal (:func:`refused_captures`, over every run's manifest),
    unless a read of their own body says otherwise. ``checks`` (the closure-text
    check's outcomes) marks the captures it found misread, and those that showed a
    closing their rows hold (:attr:`Census.noted`).
    """
    listings, names = load_listings(artifacts)
    read = read_captures(archive_reads, archive_health)
    everything: list[SnapshotRecord] = []
    for manifest in find_manifests(artifacts):
        records = read_manifest(manifest)
        everything += records
        for capture, state in redirected_captures(records).items():
            read.setdefault(capture, state)
        for capture, state in missing_captures(records).items():
            read.setdefault(capture, state)
        for capture, state in replaced_captures(records).items():
            read.setdefault(capture, state)
    for capture, state in refused_captures(everything).items():
        read.setdefault(capture, state)
    outcomes = checks.outcomes.items() if checks is not None else ()
    misread = {capture: outcome for capture, outcome in outcomes if outcome in MISREAD}
    noted = frozenset(capture for capture, outcome in outcomes if outcome == "read")
    return Census(listings, names, read, misread, noted)


def group_days(tally: Tally) -> dict[str, dict[str, dict[date, float]]]:
    """Return each hazard group's county days from a weights tally: group, county, day, weight.

    Like :func:`snowlight.sources.stations.storms.county_days`, for every group of
    :mod:`snowlight.weights.codes` (winter, cold, tropical, flood, ...), each day
    at the largest weight among the group's codes that covered it.
    """
    found: dict[str, dict[str, dict[date, float]]] = defaultdict(lambda: defaultdict(dict))
    for fips, years in tally.counties.items():
        for counts in years.values():
            for code, days in counts.by_code.items():
                closure = BY_CODE.get(code)
                if closure is None:
                    continue
                target = found[closure.group][fips]
                for day in days:
                    target[day] = max(target.get(day, 0.0), closure.weight)
    return {group: dict(counties) for group, counties in found.items()}


def hazard_days(
    counties: Mapping[str, Mapping[str, Mapping[date, float]]], groups: Iterable[str]
) -> dict[str, dict[date, float]]:
    """Merge per-group county days (group, county, day, weight) over ``groups``."""
    merged: dict[str, dict[date, float]] = defaultdict(dict)
    for group in groups:
        for fips, days in counties.get(group, {}).items():
            for day, weight in days.items():
                merged[fips][day] = max(merged[fips].get(day, 0.0), weight)
    return dict(merged)


# Station-by-station records for the first-hand gap file ------------------------------

GATE_PIECE = "s4"
_VERDICT_TEXT = {
    "proven": (
        "proven: its list has been seen with a row (at its current or a former address, or "
        "as the list file another proven station reads too)"
    ),
    "not-working": "not working: its latest live read does not count",
    "no-endpoint": "no known closings endpoint",
    "unread": "unproven: captures of its list are not read yet",
    "misread": (
        "unproven, open: an archived capture of its list made in its closure window was "
        "refused by its adapter (a page form no reader knows) or showed a closing its rows "
        "do not hold (the closure-text check); no verdict is given until that form is read"
    ),
    "storm-read": (
        "unproven: every archived capture of its list made in its closure window (a storm "
        "day, a day its counties' proven lists named closures, or a day within two days of "
        "one) was read, none with a row and none showing a closing its rows do not hold, and "
        "at least one of them showed the list (captures of other days may be unread)"
    ),
    "unconfirmed": (
        "unproven: every archived capture of its list made in its closure window that could "
        "be read was read, and at least one showed a closing, a delay or no school that its "
        "rows hold but that does not prove it: a district's notice or page text that names "
        "no weather or emergency (a calendar's planned day reads the same), or a story that "
        "is not a list's entry; the list may be in use"
    ),
    "no-storm-capture": (
        "unproven: no archived capture of its list made in its closure window (a storm day, "
        "a day its counties' proven lists named closures, or a day within two days of one) "
        "shows the list: the archive holds none, or only page shells that show no closing; "
        "its other captures showed the list, empty (captures of other days may be unread)"
    ),
    "older-unread": (
        "unproven: no unread capture of its list remains, at its current or a former "
        "address (none read held a row); only captures of other addresses it read before "
        "are unread, and they cannot prove it"
    ),
    "all-read": "unproven: every archived capture of its list was read, none with a row",
    "unreadable": (
        "unproven: no archived capture of its list that was read showed the list: each made "
        "in its closure window is a page that loads its list from an address the archive "
        "does not hold and shows no closing itself (others may be a form no adapter reads)"
    ),
    "no-capture": "unproven: the archive holds no capture of its list",
    "not-listed": (
        "unproven: an address of its list (its current page or data file, or a former "
        "address) was never listed, so what the archive holds of it is unknown"
    ),
}


def _census_sentence(keys: Sequence[Mapping[str, JSONValue]]) -> str:
    parts: list[str] = []
    for item in keys:
        listed, read = item.get("listed"), item.get("read_captures")
        address = "current" if item.get("current", True) else None
        address = address or ("former" if item.get("former") else "earlier")
        label = f"{item.get('key')} ({address})"
        if not listed and not read:
            asked = "listed, none held" if item.get("listing_asked") else "never listed"
            parts.append(f"{label}: {asked}")
            continue
        states = item.get("read")
        found = (
            ", ".join(f"{count} {state}" for state, count in sorted(states.items()))
            if isinstance(states, dict) and states
            else "none read"
        )
        parts.append(
            f"{label}: {listed} captures listed ({item.get('winter')} in winter, "
            f"{item.get('digests')} distinct), {read} read ({found}), {item.get('unread')} not "
            f"read ({item.get('unread_storm')} on storm days, {item.get('unread_closure', 0)} "
            f"more on days its counties' proven lists named closures, "
            f"{item.get('unread_near', 0)} more within {NEAR_DAYS} days of one; "
            f"{item.get('unread_due', 0)} of them due); {item.get('window_seen', 0)} distinct "
            "captures in its closure window showed the list" + _check_clause(item)
        )
    return "; ".join(parts) if parts else "no URL"


def _check_clause(item: Mapping[str, JSONValue]) -> str:
    """What the closure-text check said of an address's captures in its closure window."""
    parts = []
    misread, noted = item.get("window_misread"), item.get("window_noted")
    if isinstance(misread, int) and misread:
        parts.append(f"{misread} of them misread (refused, or a closing its rows do not hold)")
    if isinstance(noted, int) and noted:
        parts.append(
            f"{noted} of them showed a closing its rows hold that did not prove it (no weather "
            "or emergency named)"
        )
    return f" ({'; '.join(parts)})" if parts else ""


def gap_records(
    registry: Registry,
    report: Mapping[str, JSONValue],
    result: Mapping[str, JSONValue],
    *,
    checked_at: datetime,
) -> list[dict[str, JSONValue]]:
    """Return one gap-file record per source touching each state short of the target.

    The records take the shape of ``docs/research/firsthand/gaps.json`` (the
    gap-state part's first-hand file) and add a ``gate`` block: the station's
    state and reason from ``coverage.json``, its proof (or none), what proving it
    would add in the state and nationally, and the archive census of every URL it
    reads or read. ``verdict`` is the gate's verdict in words.
    """
    stations = report.get("stations")
    states = report.get("states")
    table = _station_table(result)
    if not isinstance(stations, dict) or not isinstance(states, dict):
        raise GateError("the gate report has no station or state table")
    records: list[dict[str, JSONValue]] = []
    rare = rare_lines(report)
    for code, entry in sorted(states.items()):
        if not isinstance(entry, dict) or entry.get("meets_target") is True:
            continue
        ids = entry.get("stations")
        for station_id in ids if isinstance(ids, list) else []:
            station = registry.stations[str(station_id)]
            gate_entry = stations.get(station.id)
            coverage_entry = table.get(station.id)
            if not isinstance(gate_entry, dict):
                raise GateError(f"the gate report lacks {station.id}")
            record = _gap_record(
                station,
                registry,
                code,
                entry=gate_entry,
                coverage_entry=coverage_entry,
                checked_at=checked_at,
            )
            line = rare.get(code)
            if line is not None:
                record = _not_pursued(record, line)
            records.append(record)
    return records


def rare_lines(report: Mapping[str, JSONValue]) -> dict[str, Mapping[str, JSONValue]]:
    """The owner's gate's line for each rare-closure state, by state."""
    block = report.get("owner_gate")
    lines = block.get("rare") if isinstance(block, dict) else None
    return {
        str(line.get("state")): line
        for line in (lines if isinstance(lines, list) else [])
        if isinstance(line, dict)
    }


def state_sentence(line: Mapping[str, JSONValue]) -> str:
    """What a state's line says: covered, proven and missing, in words."""
    covered, proven, missing = line.get("covered"), line.get("proven"), line.get("missing")
    if not isinstance(covered, dict) or not isinstance(proven, dict):
        return ""
    if not isinstance(missing, dict):
        return ""
    return (
        f"{line.get('state')}: {line.get('schools')} schools; covered by a working source "
        f"{covered.get('schools')} ({_pct(covered.get('share'))}, "
        f"{_pct(covered.get('weighted_share'))} closure-weighted); proven {proven.get('schools')} "
        f"({_pct(proven.get('share'))}, {_pct(proven.get('weighted_share'))} closure-weighted); "
        f"missing: {missing.get('uncovered')} schools no working source covers and "
        f"{missing.get('covered_unproven')} covered by sources never seen holding a closing"
    )


def percent(value: JSONValue) -> str:
    """A share as a percentage to a tenth, cut, never rounded up (0.8995 is 89.9%)."""
    if not isinstance(value, int | float):
        return "-"
    tenths = math.floor(float(value) * 1000 + 1e-9)
    return f"{tenths / 10:.1f}%"


_pct = percent


def _not_pursued(
    record: dict[str, JSONValue], line: Mapping[str, JSONValue]
) -> dict[str, JSONValue]:
    """A rare-closure state's record: the owner's decision and the state's shares, said first."""
    notes = record.get("notes")
    block = record.get("gate")
    return {
        **record,
        "owner_decision": NOT_PURSUED,
        "notes": f"{NOT_PURSUED}. {state_sentence(line)}. {notes}",
        "gate": {**block, "owner_gate": dict(line)} if isinstance(block, dict) else block,
    }


def _gap_record(  # noqa: PLR0913 - one record joins the registry, the report and the result
    station: Station,
    registry: Registry,
    code: str,
    *,
    entry: Mapping[str, JSONValue],
    coverage_entry: JSONValue,
    checked_at: datetime,
) -> dict[str, JSONValue]:
    platform = registry.platforms[station.platform]
    verdict_code = str(entry.get("verdict"))
    gain = entry.get("gain")
    by_state = gain.get("by_state") if isinstance(gain, dict) else None
    in_state = by_state.get(code) if isinstance(by_state, dict) else None
    archive_keys = entry.get("archive")
    keys = (
        [item for item in archive_keys if isinstance(item, dict)]
        if isinstance(archive_keys, list)
        else []
    )
    proof_block = coverage_entry.get("proof") if isinstance(coverage_entry, dict) else None
    reason = entry.get("reason")
    notes = [_VERDICT_TEXT.get(verdict_code, verdict_code)]
    if reason:
        notes.append(f"live read: {reason}")
    if isinstance(in_state, list) and len(in_state) == 2:  # noqa: PLR2004 - [schools, weight]
        notes.append(
            f"proving it would add {in_state[0]} schools ({in_state[1]} closure-weighted) here"
        )
    notes.append(f"archive: {_census_sentence(keys)}")
    robots = [
        f"{check.url}: {'allowed' if check.allowed else 'disallowed'} ({check.rule})"
        for check in station.robots
    ]
    return {
        "group": platform.operator,
        "source_id": station.id,
        "gap_state": code,
        "market_or_region": station.market,
        "states": list(station.states),
        "origin": _origin(station.page_url or station.data_url),
        "closings_url": station.page_url,
        "status": station.status.value,
        "robots": {"checks": list(robots)} if robots else None,
        "rendering": None,
        "variant": None,
        "data_endpoint": {"url": station.data_url} if station.data_url else None,
        "empty_state_text": None,
        "vendor": platform.name,
        "terms_note": (
            f"automated access {platform.terms.automated_access.value} (see {platform.id}.yaml)"
        ),
        "wayback_patterns": [f"{key}*" for key in station_keys(station)],
        "checked_at": iso_utc(checked_at),
        "notes": "; ".join(notes) + ".",
        "verdict": _VERDICT_TEXT.get(verdict_code, verdict_code),
        "built_as": [station.id] if station.status is not StationStatus.NO_ENDPOINT else [],
        "wayback": {"census": list(keys)},
        "gate": {
            "piece": GATE_PIECE,
            "verdict": verdict_code,
            "state": entry.get("state"),
            "reason": reason,
            "proven": entry.get("proven"),
            "proof": proof_block,
            "gain": gain,
            "district_level": entry.get("district_level"),
            "closure_days": entry.get("closure_days"),
            "near_days": entry.get("near_days"),
            "window_seen": entry.get("window_seen"),
            "former_urls": [
                {"url": item.url, "evidence": item.evidence} for item in station.former_urls
            ],
        },
    }


def _origin(url: str | None) -> str | None:
    if not url:
        return None
    parts = url.split("/", 3)
    return "/".join(parts[:3]) if len(parts) >= 3 else url  # noqa: PLR2004 - scheme, blank, host


def merge_records(
    existing: Sequence[Mapping[str, JSONValue]],
    records: Sequence[Mapping[str, JSONValue]],
    rare: Mapping[str, Mapping[str, JSONValue]] | None = None,
    result: Mapping[str, JSONValue] | None = None,
) -> list[JSONValue]:
    """Replace this piece's earlier gate records in the gap file with ``records``.

    Records of other pieces (no ``gate`` block, or another piece's) are kept as
    they are, in order; this piece's records follow them. A kept record filed under a
    rare-closure state (``gap_state`` in ``rare``, the owner's gate's lines,
    :func:`rare_lines`) is marked with the owner's decision (``owner_decision``,
    :data:`NOT_PURSUED`) and the state's current shares in words (``owner_gate_state``:
    covered, proven and missing), its own fields and notes left as they are. With the
    coverage ``result``, a kept record's ``proof`` block (what each station it was built as
    has been seen holding) is rewritten from it (:func:`current_proof`), dated, so no record
    keeps a proof the gate no longer accepts (Palm Beach's storm-information link of
    2024-10-10, which round 2 stopped counting).
    """
    kept: list[JSONValue] = []
    for item in existing:
        block = item.get("gate")
        if isinstance(block, dict) and block.get("piece") == GATE_PIECE:
            continue
        record = dict(item)
        built = record.get("built_as")
        if result is not None and isinstance(record.get("proof"), dict) and isinstance(built, list):
            record["proof"] = {str(sid): current_proof(result, str(sid)) for sid in built}
        line = (rare or {}).get(str(record.get("gap_state")))
        if line is not None:
            record["owner_decision"] = NOT_PURSUED
            record["owner_gate_state"] = state_sentence(line)
        kept.append(record)
    return kept + [dict(item) for item in records]


PROOF_EXAMPLES = 3


def current_proof(result: Mapping[str, JSONValue], station_id: str) -> dict[str, JSONValue]:
    """What ``coverage.json`` says today of a station's proof, for a first-hand record.

    ``as_of`` is the measure's time; ``state`` the station's (working, stale, error ...);
    ``proven`` whether it counts toward the proven share (working, and seen holding a
    closing by the proof rules in force); ``evidence`` the proof it counts on (none when
    unproven); and, for a district channel or a board, how many populated reads the notice
    gate dropped, with a few of them and why.
    """
    stations = result.get("stations")
    entry = stations.get(station_id) if isinstance(stations, dict) else None
    unproven = result.get("unproven")
    unproven_ids = {
        str(item.get("id")) for item in unproven if isinstance(item, dict)
    } if isinstance(unproven, list) else set()  # fmt: skip
    state = entry.get("state") if isinstance(entry, dict) else None
    evidence = entry.get("proof") if isinstance(entry, dict) else None
    proven = state == "working" and station_id not in unproven_ids and isinstance(evidence, dict)
    found: dict[str, JSONValue] = {
        "as_of": result.get("generated_at"),
        "state": state if isinstance(state, str) else "not in the registry",
        "proven": proven,
        "evidence": evidence if proven else None,
    }
    notices = result.get("district_notice_gate")
    gate_entry = notices.get(station_id) if isinstance(notices, dict) else None
    if isinstance(gate_entry, dict):
        dropped = gate_entry.get("dropped")
        found["notice_gate"] = {
            "kind": gate_entry.get("kind"),
            "kept": gate_entry.get("kept"),
            "dropped": gate_entry.get("dropped_count"),
            "dropped_examples": [
                {key: item.get(key) for key in ("captured_at", "mode", "row", "reason")}
                for item in (dropped if isinstance(dropped, list) else [])[:PROOF_EXAMPLES]
                if isinstance(item, dict)
            ],
        }
    return found


# The gap file's summary section -------------------------------------------------------

GAPS_MD_START = (
    "<!-- coverage gate (s4): written by `snowlight stations gate records`; edits are replaced -->"
)
GAPS_MD_END = "<!-- end of the coverage gate's section -->"
_VERDICT_ORDER = (
    "proven",
    "unread",
    "misread",
    "older-unread",
    "storm-read",
    "unconfirmed",
    "no-storm-capture",
    "all-read",
    "unreadable",
    "no-capture",
    "not-listed",
    "not-working",
    "no-endpoint",
)


def _percent(share: Mapping[str, JSONValue], key: str = "share") -> str:
    """A share's percentage as every table the gate writes gives it: cut, never rounded up."""
    return percent(share.get(key))


def _weighted_percent(share: Mapping[str, JSONValue]) -> str:
    weighted = share.get("weighted")
    return _percent(weighted) if isinstance(weighted, dict) else "-"


def gate_section(report: Mapping[str, JSONValue]) -> str:
    """The gap file's summary of ``gate.json``: each state short of the target, in Markdown.

    One row per state whose proven share (plain or closure-weighted) is under the
    state target, with what it lacks of the target and how many of the sources
    touching it have each verdict; the per-source evidence is in ``gaps.json``.
    """
    national = report.get("national")
    states = report.get("states")
    stations = report.get("stations")
    if not isinstance(national, dict) or not isinstance(states, dict):
        raise GateError("the gate report has no national or state table")
    if not isinstance(stations, dict):
        raise GateError("the gate report has no station table")
    proven = national.get("proven")
    if not isinstance(proven, dict):
        raise GateError("the gate report has no national proven share")
    to_target = national.get("to_target")
    lacking = to_target if isinstance(to_target, dict) else {}
    lines = [
        GAPS_MD_START,
        "## The coverage gate (s4): states short of the proven target",
        "",
        f"From `gate.json` of {report.get('generated_at')} (coverage of "
        f"{_dig_text(report, 'coverage', 'generated_at')}). A station counts toward the proven "
        "share only once its list has been seen with a row, live or in an archived capture, "
        "at its current address or a former address of its own list (the registry's "
        "`former_urls`, each with the evidence of the move). National: "
        f"{_percent(proven)} of schools proven ({_weighted_percent(proven)} "
        f"closure-weighted); the target is {NATIONAL_TARGET:.0%} of both, "
        f"{lacking.get('schools')} schools ({lacking.get('weighted')} weighted) short. "
        f"Each state's target is {STATE_TARGET:.0%} of both. Every source touching a state "
        "below has its record in [`gaps.json`](gaps.json) (its `gate` block: verdict, proof, "
        "gain, and the archive census of every address it reads or read).",
        "",
        *_owner_lines(report),
        "| State | Proven | Weighted | Short (schools / weighted) | Sources by verdict | Open |",
        "|---|---|---|---|---|---|",
    ]
    met = settled = 0
    for code, entry in sorted(states.items()):
        if not isinstance(entry, dict):
            continue
        if entry.get("meets_target") is True:
            met += 1
            continue
        share = entry.get("proven")
        short = entry.get("to_target")
        ids = entry.get("stations")
        counts: dict[str, int] = defaultdict(int)
        for station_id in ids if isinstance(ids, list) else []:
            item = stations.get(str(station_id))
            if isinstance(item, dict):
                counts[str(item.get("verdict"))] += 1
        verdicts = ", ".join(f"{counts[name]} {name}" for name in _VERDICT_ORDER if counts[name])
        shortfall = (
            f"{short.get('schools')} / {short.get('weighted')}" if isinstance(short, dict) else "-"
        )
        still = entry.get("open")
        still_ids = [str(item) for item in still] if isinstance(still, list) else []
        kept = entry.get("open_records")
        kept_count = len(kept) if isinstance(kept, list) else 0
        settled += entry.get("settled") is True
        opened = ", ".join(
            part
            for part in (
                f"{len(still_ids)} sources" if still_ids else "",
                f"{kept_count} records" if kept_count else "",
            )
            if part
        )
        lines.append(
            f"| {code} | {_percent(share) if isinstance(share, dict) else '-'} | "
            f"{_weighted_percent(share) if isinstance(share, dict) else '-'} | {shortfall} | "
            f"{verdicts} | {opened or 'none: settled'} |"
        )
    lines += [
        "",
        f"{met} of {len(states)} states (with DC) meet the target; of the {len(states) - met} "
        f"short of it, {settled} are settled: every source whose proof would add to the state "
        "has a verdict after which no archived capture left could prove it ("
        + ", ".join(f"`{name}`" for name in sorted(TERMINAL))
        + "). Settled is not met: a settled state is still short, and an `unconfirmed` source in "
        "it showed closings on or near its storm days that the proof rule does not accept. "
        "A source is open (the last column counts them) while captures of its list made "
        f"in its closure window (its closure days and the {NEAR_DAYS} days either side) are "
        "unread or were misread (refused by its adapter, or showing a closing its rows do not "
        "hold: the closure-text check, `archive/closure-text.jsonl`), or an address of its list "
        "was never listed. A first-hand record of a source not built (a district or outlet "
        "the registry does not hold) keeps its states open too (the last column's records) "
        "while it says the site was not read, or was checked before "
        f"{FRESH_SINCE.date().isoformat()}: only a check of today's site can say no reader "
        "here reads it (`open_records` in `gate.json`). The window is measured on the "
        "proven sources' own archived reads (`calibration` in `gate.json`). Verdicts: "
        + "; ".join(f"`{name}`: {_VERDICT_TEXT[name]}" for name in _VERDICT_ORDER)
        + ".",
        GAPS_MD_END,
    ]
    return "\n".join(lines) + "\n"


def _owner_lines(report: Mapping[str, JSONValue]) -> list[str]:
    """The owner's gate in the gap file's section: its rule, each line and its verdict."""
    block = report.get("owner_gate")
    if not isinstance(block, dict):
        return []
    national = block.get("national")
    kept = block.get("kept")
    lines = [
        f"**The owner's gate** (decided {block.get('decided_on')}, replacing "
        f'{STATE_TARGET:.0%} in every state): "{block.get("quote")}". It '
        + ("**passes**" if block.get("passes") is True else "**does not pass**")
        + ".",
        "",
        "| Rule | State | Proven | Weighted | Meets |",
        "|---|---|---|---|---|",
    ]
    dig = block.get("dig")
    for line in dig if isinstance(dig, list) else []:
        if isinstance(line, dict):
            accepted = line.get("accepted")
            rule = (
                f"dig to {STATE_TARGET:.0%}; {accepted.get('note')} at "
                f"{_pct(accepted.get('plain'))} / {_pct(accepted.get('weighted'))}"
                if isinstance(accepted, dict)
                else f"dig to {STATE_TARGET:.0%}"
            )
            lines.append(_owner_row(rule, line))
    if isinstance(national, dict):
        lines.append(
            f"| national weighted at least {_pct(national.get('target'))} | US | - | "
            f"{_pct(national.get('weighted_share'))} | "
            f"{'yes' if national.get('meets') is True else 'no'} |"
        )
    if isinstance(kept, dict):
        short = kept.get("short")
        count = len(short) if isinstance(short, list) else 0
        lines.append(
            f"| keep the others at {STATE_TARGET:.0%} | {kept.get('states')} states | - | - | "
            + ("yes" if not count else f"no: {count} short")
            + " |"
        )
    rare = block.get("rare")
    for line in rare if isinstance(rare, list) else []:
        if isinstance(line, dict):
            lines.append(_owner_row(NOT_PURSUED, line))
    lines += ["", *_owner_notes(block)]
    return [*lines, ""]


def _owner_notes(block: Mapping[str, JSONValue]) -> list[str]:
    """The owner's gate's notes under its table: acceptances, market checks, thin margins and
    the rare-closure states' records."""
    national, kept = block.get("national"), block.get("kept")
    dig, rare = block.get("dig"), block.get("rare")
    lines: list[str] = []
    for line in dig if isinstance(dig, list) else []:
        accepted = line.get("accepted") if isinstance(line, dict) else None
        if isinstance(line, dict) and isinstance(accepted, dict):
            lines.append(
                f"- {line.get('state')}: accepted by the owner on {accepted.get('decided_on')} "
                f'("{accepted.get("quote")}") at {_pct(accepted.get("plain"))} proven plain and '
                f"{_pct(accepted.get('weighted'))} closure-weighted, under the "
                f"{_pct(STATE_TARGET)} target: it meets while its exact shares stay at least "
                f"these and fails if either drops below them. Measured: "
                f"{accepted.get('plain_measured')}, {accepted.get('weighted_measured')} "
                "closure-weighted."
            )
    for line in dig if isinstance(dig, list) else []:
        if isinstance(line, dict):
            lines += _market_lines(line)
            check = line.get("pandemic_checked")
            if isinstance(check, dict):
                listed = check.get("stations")
                names = ", ".join(f"`{s}`" for s in listed) if isinstance(listed, list) else ""
                lines.append(
                    f"- {line.get('state')}: without the proven lists never seen holding a "
                    f"closing but the pandemic's ({names}: every populated read of the first "
                    "wave, or every row a health closing), proven "
                    f"{_pct(check.get('share'))} ({check.get('schools')} of "
                    f"{line.get('schools')} schools), {_pct(check.get('weighted_share'))} "
                    "closure-weighted. Such a list counts: it lists closings only, and the "
                    "districts entered these themselves (a district channel's pandemic notice "
                    "proves nothing, the channel being for any news); it has yet to be seen on "
                    "a weather day."
                )
    if isinstance(national, dict) and national.get("market_checked_weighted_share") is not None:
        lines.append(
            "- National: with no county credited across a state line by a market alone, "
            f"{_pct(national.get('market_checked_weighted_share'))} closure-weighted (the "
            f"gate's measure: {_pct(national.get('weighted_share'))})."
        )
    thin = kept.get("thin") if isinstance(kept, dict) else None
    for item in thin if isinstance(thin, list) else []:
        if isinstance(item, dict):
            lines.append(
                f"- Kept, thin: {item.get('state')} is proven {_pct(item.get('share'))} "
                f"({_pct(item.get('weighted_share'))} closure-weighted), "
                f"{item.get('schools_above_target')} schools above the "
                f"{_pct(STATE_TARGET)} target (plain)."
            )
    market_short = kept.get("market_checked_short") if isinstance(kept, dict) else None
    if isinstance(market_short, list) and market_short:
        lines.append(
            "- Kept states that meet the target on the gate's measure but not when no county "
            "across a state line is credited by a market alone: "
            + "; ".join(
                f"{item.get('state')} {_pct(item.get('share'))} / "
                f"{_pct(item.get('weighted_share'))}"
                for item in market_short
                if isinstance(item, dict)
            )
            + "."
        )
    for line in rare if isinstance(rare, list) else []:
        if isinstance(line, dict):
            lines.append(f"- {state_sentence(line)}; {NOT_PURSUED}.")
    return lines


def _market_lines(line: Mapping[str, JSONValue]) -> list[str]:
    """A dig state's market check in words: its shares without market-only credits, and each
    credit a market alone gives it."""
    check = line.get("market_checked")
    if not isinstance(check, dict):
        return []
    found = [
        f"- {line.get('state')}: counting a county across a state line only where the station's "
        f"rows were seen naming a place in it, proven {_pct(check.get('share'))} "
        f"({check.get('schools')} of {line.get('schools')} schools), "
        f"{_pct(check.get('weighted_share'))} closure-weighted (the gate's measure, which "
        "credits a station with its whole market: "
        f"{_pct(_fraction(dict(line), 'proven', 'share'))}, "
        f"{_pct(_fraction(dict(line), 'proven', 'weighted_share'))}). Credited by market "
        "assumption only (no row of the station's ever named a place in the county):"
    ]
    credits_listed = check.get("assumed_credits")
    for item in credits_listed if isinstance(credits_listed, list) else []:
        if isinstance(item, dict):
            counties = item.get("counties")
            names = ", ".join(str(c) for c in counties) if isinstance(counties, list) else ""
            found.append(f"  - `{item.get('station')}`: {names} ({item.get('schools')} schools)")
    return found


def _owner_row(rule: str, line: Mapping[str, JSONValue]) -> str:
    proven = line.get("proven")
    plain = proven.get("share") if isinstance(proven, dict) else None
    weighted = proven.get("weighted_share") if isinstance(proven, dict) else None
    meets = "yes" if line.get("meets") is True else "no"
    return f"| {rule} | {line.get('state')} | {_pct(plain)} | {_pct(weighted)} | {meets} |"


def _dig_text(report: Mapping[str, JSONValue], *path: str) -> str:
    value: JSONValue = dict(report)
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return str(value)


def replace_section(text: str, section: str) -> str:
    """Put ``section`` in the gap file's Markdown: in place of the earlier one, or before
    the first second-level heading (after the file's introduction)."""
    start, end = text.find(GAPS_MD_START), text.find(GAPS_MD_END)
    if start != -1 and end != -1 and end > start:
        tail = text[end + len(GAPS_MD_END) :].removeprefix("\n")
        return text[:start] + section + tail
    heading = re.search(r"^## ", text, flags=re.MULTILINE)
    if heading is None:
        return text.rstrip("\n") + "\n\n" + section
    return text[: heading.start()] + section + "\n" + text[heading.start() :]

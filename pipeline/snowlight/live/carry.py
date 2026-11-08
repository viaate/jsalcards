"""What a reader hands its successor across a handover: ``carry.json`` in the private state.

A new process holds a source's statuses (G13) only for the sources it has read itself
(:mod:`snowlight.live.ingest`), because the rows of a read live in memory only. On Nov 5 a
successor so showed a source its predecessor held dark until its own next good read (the
predecessor's last read of it had failed, so the successor did not read it early): the lit
count fell 3 to 1 for 20 minutes across the process boundary alone.

So every pass writes the sources whose statuses it held, each with the time of the good read
that holds it (the ledger's ``last_good_at``) and the end of the hold it applied (G13: that
read's time plus the bound for the source as the pass saw it, a window or an alert or quiet),
and a key of everything a derivation and the hold depend on (the resolver's
``derived_version`` without the station part and the merge rules' digest). The successor
reads it once at its start (:func:`read_carry`) and, for each listed source it has not read
itself, treats the rows the ledger holds present as the rows of that read, while the ledger's
``last_good_at`` is still the one listed: it holds them while both the listed end and its own
G13 bound (from that read's own time) allow, so a status is never shown longer than the run
before would have shown it, and reuses only derivations made under its own version. Its own
first good read of the source replaces them, as any later read does.

The record travels in the pushed state with the ledger, and a successor uses it only when it
is the run before's last word: ``live finish --record``, the step after the reader has ended
and before the end push, marks the record final (:func:`finalize_carry`), and every pass
writes it afresh without the mark. So a snapshot pushed while the run went on (a loop push),
or left by a run whose end push failed, whose runner was lost or whose job was cut off, or a
pull that fell back to the previous slot, carries nothing: the run before may have read a
retraction after that snapshot and held the closing dark, while its uploads were refused or
failed and the host still serves the snapshot's pass, so nothing on the host tells the two
apart. A final record is the run's last completed pass's: a pass cut off or failed after its
reads leaves the one before it beside a ledger that holds the cut pass's reads. A good read
folded there moves the ledger's ``last_good_at``, which ends that source's carry; a read the
ledger could not take moves nothing, so the reader takes its source out of the record on
disk at once (:func:`drop_carry`), the moment it holds it dark. A source whose resolve failed
at the pass is carried as any other and also listed ``unknown`` with an end (counted in the
log lines): the run before withheld its states. The successor cannot tell a failure that
would recur from one that has passed: it resolves a carried source from the derivations the
ledger stores, without the read's rows, so a step only a read's rows reach (the unmatched
queue, a dated row's successor) does not run there. So it withholds the same states until it
holds rows of that source from its own read (its own resolve of them then judges, at each
pass, as in any run) or a read of it cannot be taken in, and never past the end listed:
:func:`withheld_until` from the last pass whose own resolve failed, the age past which a
record carries nothing at all, and never extended by a run that only inherited it (its own
record lists the source with the same end, or that bound from its own record's time when
that is earlier: a clock running behind the run before's, which the run after would
otherwise refuse as ``unreadable``). A failure that passed at the run before's last
pass so darkens those states in the successor until its own read, at most that end. The
record is also used only when it is not older than the closings file the live host serves now (its
``generated_at``, read back once at the start: one call to our own host's API per process
start; a refusal it meets is kept by the host client for the process): any later writer's
file (an overrides-only run, a blank) stops it. A missing, unreadable, other-version,
other-key, not final, future-stamped, over-age or behind record, and a host that cannot be
read or holds no file, carry nothing (one codes-only log line), and so does an entry whose
time does not match the ledger. A pass whose write fails removes the record, so an earlier
pass's record is never marked final for the run's end. Source ids, codes and times only;
the file is packed and pushed with the state and never exported.
"""

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, NamedTuple

from snowlight.live.guards import Rules
from snowlight.output import JSONValue, dumps_json, write_bytes_atomic

LOG: Final = logging.getLogger(__name__)
CARRY: Final = "carry.json"
CARRY_VERSION: Final = 2
FUTURE_LEEWAY: Final = timedelta(seconds=60)
"""A record stamped later than this after the reader's clock is not trusted."""


class Carried(NamedTuple):
    """One source the run before held: its last good read and the end of the hold it applied."""

    good: datetime
    until: datetime


class Carry(NamedTuple):
    """A usable record: the sources the run before held, and the sources whose states it
    withheld for a failing resolve at its last pass (``unknown``), each with the end of that
    withholding (:func:`withheld_until`)."""

    sources: dict[str, Carried]
    unknown: dict[str, datetime]


NOTHING: Final = Carry({}, {})


def withheld_until(failed_at: datetime, rules: Rules) -> datetime:
    """How long a successor withholds the states of a source whose resolve failed at
    ``failed_at`` and that it has not read itself: the longest G13 bound from that pass, the
    age past which a record carries nothing at all."""
    return failed_at + max(rules.hold_boosted, rules.hold_quiet)


def carry_key(resolver_version: str, rules: Rules) -> str:
    """The key a record must carry to be used: the record's schema, the resolver's
    ``derived_version`` (without the station part) and the merge rules (the G13 bounds)."""
    text = f"{CARRY_VERSION}|{resolver_version}|{rules.digest()}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _iso(moment: datetime) -> str:
    """Whole precision: a read stamped within the pass's last second is never later than it."""
    return moment.astimezone(UTC).isoformat()


def carry_bytes(
    key: str,
    now: datetime,
    held: Mapping[str, Carried],
    unknown: Mapping[str, datetime] | None = None,
) -> bytes:
    """The record: its version, key and time, each held source's last good read and the end
    of its hold, and each source whose states the pass withheld for a failing resolve with
    the end of that withholding."""
    unknown = unknown or {}
    listed: dict[str, JSONValue] = {sid: _iso(unknown[sid]) for sid in sorted(unknown)}
    return dumps_json(
        {
            "version": CARRY_VERSION,
            "key": key,
            "at": _iso(now),
            "sources": {
                sid: {"good": _iso(held[sid].good), "until": _iso(held[sid].until)}
                for sid in sorted(held)
            },
            "unknown": listed,
        }
    )


def write_carry(
    path: Path,
    *,
    key: str,
    now: datetime,
    held: Mapping[str, Carried],
    unknown: Mapping[str, datetime] | None = None,
) -> int:
    """Write the record atomically; the bytes written, or 0 when the write failed (logged by
    the error's type only: the pass goes on)."""
    try:
        data = carry_bytes(key, now, held, unknown)
        write_bytes_atomic(path, data)
    except (OSError, ValueError, TypeError) as error:
        LOG.error("carry write: %s", type(error).__name__)
        # an earlier pass's record must not stand for this one (finalize_carry would mark it)
        try:
            path.unlink(missing_ok=True)
        except OSError as gone:
            LOG.error("carry remove: %s", type(gone).__name__)
        return 0
    return len(data)


def drop_carry(path: Path, source_id: str) -> None:
    """Take ``source_id`` out of the record on disk at once: the reader has just failed to take
    in a read of it (the ledger's observe raised), dropped it from what it holds, and holds it
    dark from now on, while the ledger, whose transaction rolled back, still matches the
    record's entry. Were the pass then cut off or to raise before it writes its own record,
    ``live finish --record`` would mark this one final and a successor would relight the
    source. Its ``unknown`` entry goes too: the reader, holding no rows of it now, no longer
    withholds its states after this pass. A record that cannot be rewritten is removed
    (nothing is carried: the safe side). One codes-and-counts line when it changes the
    record; never raises."""
    try:
        try:
            document = json.loads(path.read_bytes())
        except FileNotFoundError:
            return
        sources = document.get("sources") if isinstance(document, dict) else None
        unknown = document.get("unknown", {}) if isinstance(document, dict) else None
        if not isinstance(sources, dict) or not isinstance(unknown, dict):
            raise ValueError("sources")
        if source_id not in sources and source_id not in unknown:
            return
        sources.pop(source_id, None)
        unknown.pop(source_id, None)
        write_bytes_atomic(path, dumps_json(document))
        LOG.warning("carry drop: 1 source (observe), %d left", len(sources))
    except Exception as error:
        try:
            path.unlink(missing_ok=True)
            LOG.error("carry drop: record removed (%s)", type(error).__name__)
        except Exception as gone:
            LOG.error("carry remove: %s", type(gone).__name__)


def finalize_carry(path: Path) -> str:
    """Mark the record final: ``live finish --record`` calls it once the reader has ended, so
    the end push carries the record of the run's last pass marked, and no other snapshot is
    (:func:`read_carry` uses only a final record). One codes-and-counts line; never raises."""
    try:
        document = json.loads(path.read_bytes())
        if not isinstance(document, dict) or not isinstance(document.get("sources"), dict):
            return "carry final: none (unreadable)"
        document["final"] = True
        write_bytes_atomic(path, dumps_json(document))
    except FileNotFoundError:
        return "carry final: none (missing)"
    except ValueError:
        return "carry final: none (unreadable)"
    except Exception as error:
        return f"carry final: none ({type(error).__name__})"
    unknown = document.get("unknown")
    if isinstance(unknown, dict) and unknown:
        return f"carry final: {len(document['sources'])} sources, {len(unknown)} unknown"
    return f"carry final: {len(document['sources'])} sources"


def _aware(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _entry(value: object, written: datetime, longest: timedelta) -> Carried | None:
    """One listed source, or ``None`` when it does not hold together (a read later than the
    record, or a hold ending before its read or longer than the longest bound)."""
    if not isinstance(value, dict):
        return None
    good, until = _aware(value.get("good")), _aware(value.get("until"))
    if good is None or until is None or good > written or not good <= until <= good + longest:
        return None
    return Carried(good, until)


def _behind(written: datetime, published: Callable[[], datetime | None]) -> str | None:
    """Why a record written at ``written`` is not what the host serves now, or ``None``."""
    try:
        served = published()
    except Exception as error:
        return f"host {type(error).__name__}"
    if served is None:
        return "unpublished"
    # the host serves a newer pass than this record's (whole seconds, as published): the state
    # is an older snapshot, and what that pass held may since have gone dark
    return "behind" if written < served else None


def _unknown(value: object, written: datetime, longest: timedelta) -> dict[str, datetime] | None:
    """The sources whose states the record withholds, each with the end of that (a record
    written before the list: none), or ``None`` when the list does not hold together (an
    entry not a time, or ending later than the longest bound after the record): the record
    then carries nothing, since which states it withheld cannot be known."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        return None
    found: dict[str, datetime] = {}
    for sid, end in value.items():
        moment = _aware(end)
        if not isinstance(sid, str) or moment is None or moment > written + longest:
            return None
        found[sid] = moment
    return found


def _parse(  # noqa: PLR0911 - one return per refusal
    path: Path,
    *,
    key: str,
    now: datetime,
    rules: Rules,
    published: Callable[[], datetime | None],
) -> tuple[Carry, str]:
    """The record's sources and a code: ``ok`` or why it carries nothing."""
    try:
        document = json.loads(path.read_bytes())
    except FileNotFoundError:
        return NOTHING, "missing"
    except (OSError, ValueError):
        return NOTHING, "unreadable"
    if not isinstance(document, dict) or not isinstance(document.get("sources"), dict):
        return NOTHING, "unreadable"
    if document.get("version") != CARRY_VERSION:
        return NOTHING, "version"
    if document.get("key") != key:
        return NOTHING, "key"
    if document.get("final") is not True:
        # a snapshot pushed while the run went on, or the last one of a run whose end push
        # failed: the run may since have read a retraction no upload has shown
        return NOTHING, "not final"
    written = _aware(document.get("at"))
    longest = max(rules.hold_boosted, rules.hold_quiet)
    unknown = None if written is None else _unknown(document.get("unknown"), written, longest)
    if written is None or unknown is None:
        return NOTHING, "unreadable"
    if written > now + FUTURE_LEEWAY:
        return NOTHING, "future"
    if now - written > longest:
        return NOTHING, "old"
    refused = _behind(written, published)
    if refused is not None:
        return NOTHING, refused
    found: dict[str, Carried] = {}
    for sid, value in document["sources"].items():
        entry = _entry(value, written, longest)
        if isinstance(sid, str) and entry is not None:
            found[sid] = entry
    return Carry(found, {sid: end for sid, end in unknown.items() if now <= end}), "ok"


def read_record(
    path: Path,
    *,
    key: str,
    now: datetime,
    rules: Rules,
    published: Callable[[], datetime | None],
) -> Carry:
    """What the run before handed over at its last pass: the sources it held, each with its
    last good read's time and the end of its hold, and the sources whose states it withheld
    for a failing resolve, each with the end of that; :data:`NOTHING` when the record cannot
    be used. ``published`` reads back the
    ``generated_at`` of the closings file the live host serves (``None``: no file); it is
    called only for a record that is otherwise usable, and may raise. Never raises; logs
    one line of codes and counts."""
    try:
        found, code = _parse(path, key=key, now=now, rules=rules, published=published)
    except Exception as error:
        found, code = NOTHING, f"error {type(error).__name__}"
    if code != "ok":
        LOG.info("carry: none (%s)", code)
    elif found.unknown:
        LOG.info("carry: %d sources, %d unknown", len(found.sources), len(found.unknown))
    else:
        LOG.info("carry: %d sources", len(found.sources))
    return found


def read_carry(
    path: Path,
    *,
    key: str,
    now: datetime,
    rules: Rules,
    published: Callable[[], datetime | None],
) -> dict[str, Carried]:
    """The sources of :func:`read_record` alone."""
    return read_record(path, key=key, now=now, rules=rules, published=published).sources

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
apart. A final record and the ledger pushed with it agree on the run's end. The record is
also used only when it is not older than the closings file the live host serves now (its
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
from snowlight.output import dumps_json, write_bytes_atomic

LOG: Final = logging.getLogger(__name__)
CARRY: Final = "carry.json"
CARRY_VERSION: Final = 2
FUTURE_LEEWAY: Final = timedelta(seconds=60)
"""A record stamped later than this after the reader's clock is not trusted."""


class Carried(NamedTuple):
    """One source the run before held: its last good read and the end of the hold it applied."""

    good: datetime
    until: datetime


def carry_key(resolver_version: str, rules: Rules) -> str:
    """The key a record must carry to be used: the record's schema, the resolver's
    ``derived_version`` (without the station part) and the merge rules (the G13 bounds)."""
    text = f"{CARRY_VERSION}|{resolver_version}|{rules.digest()}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _iso(moment: datetime) -> str:
    """Whole precision: a read stamped within the pass's last second is never later than it."""
    return moment.astimezone(UTC).isoformat()


def carry_bytes(key: str, now: datetime, held: Mapping[str, Carried]) -> bytes:
    """The record: its version, key and time, and each held source's last good read and the
    end of its hold."""
    return dumps_json(
        {
            "version": CARRY_VERSION,
            "key": key,
            "at": _iso(now),
            "sources": {
                sid: {"good": _iso(held[sid].good), "until": _iso(held[sid].until)}
                for sid in sorted(held)
            },
        }
    )


def write_carry(path: Path, *, key: str, now: datetime, held: Mapping[str, Carried]) -> int:
    """Write the record atomically; the bytes written, or 0 when the write failed (logged by
    the error's type only: the pass goes on)."""
    try:
        data = carry_bytes(key, now, held)
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


def _parse(  # noqa: PLR0911 - one return per refusal
    path: Path,
    *,
    key: str,
    now: datetime,
    rules: Rules,
    published: Callable[[], datetime | None],
) -> tuple[dict[str, Carried], str]:
    """The record's sources and a code: ``ok`` or why it carries nothing."""
    try:
        document = json.loads(path.read_bytes())
    except FileNotFoundError:
        return {}, "missing"
    except (OSError, ValueError):
        return {}, "unreadable"
    if not isinstance(document, dict) or not isinstance(document.get("sources"), dict):
        return {}, "unreadable"
    if document.get("version") != CARRY_VERSION:
        return {}, "version"
    if document.get("key") != key:
        return {}, "key"
    if document.get("final") is not True:
        # a snapshot pushed while the run went on, or the last one of a run whose end push
        # failed: the run may since have read a retraction no upload has shown
        return {}, "not final"
    written = _aware(document.get("at"))
    if written is None:
        return {}, "unreadable"
    if written > now + FUTURE_LEEWAY:
        return {}, "future"
    longest = max(rules.hold_boosted, rules.hold_quiet)
    if now - written > longest:
        return {}, "old"
    refused = _behind(written, published)
    if refused is not None:
        return {}, refused
    found: dict[str, Carried] = {}
    for sid, value in document["sources"].items():
        entry = _entry(value, written, longest)
        if isinstance(sid, str) and entry is not None:
            found[sid] = entry
    return found, "ok"


def read_carry(
    path: Path,
    *,
    key: str,
    now: datetime,
    rules: Rules,
    published: Callable[[], datetime | None],
) -> dict[str, Carried]:
    """The sources the run before held at its last pass, each with its last good read's time
    and the end of its hold; empty when the record cannot be used. ``published`` reads back
    the ``generated_at`` of the closings file the live host serves (``None``: no file); it is
    called only for a record that is otherwise usable, and may raise. Never raises; logs one
    line of codes and counts."""
    try:
        found, code = _parse(path, key=key, now=now, rules=rules, published=published)
    except Exception as error:
        found, code = {}, f"error {type(error).__name__}"
    if code == "ok":
        LOG.info("carry: %d sources", len(found))
    else:
        LOG.info("carry: none (%s)", code)
    return found

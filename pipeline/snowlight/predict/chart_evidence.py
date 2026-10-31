"""The night chart's shadow evidence (GC4, design spec chart-shadow W2 and W3): which pass injects
which fault, what each shadow pass records, and the counts-only summary of the last 48 hours the
lead reads from the public host (``predictions/chart-shadow.json``, beside the predictions file).

**The rotation** (``serve.chart_fault: rotate``). A grid pass's slot is its scheduled grid minute
(the latest :07 or :37 at or before it), counted from the epoch. Slot ``k`` injects a fault when
``k % ROTATE_EVERY == 0``: :data:`FAULTS` in turn, ``FAULTS[(k // ROTATE_EVERY) % 5]``. So 1 slot
in 6 injects, each fault comes back every 15 hours (3 or 4 times in 48 hours, at a time of day
9 hours later each day), and a pass run again in the same slot picks the same fault. A slot
injects once: a second grid pass in it (a run's first pass, which starts between grid minutes
and counts as a grid pass, can land in the slot the run before already injected) injects
nothing, so at most 1 grid pass in 6 injects. An event pass (between grid minutes) never
injects. A fixed fault (``raise`` and the others) injects on every pass, as before the rotation.

**What a fault does** (only to the in-memory shadow build; the published file is the chart-off
file whatever happens here):

- ``raise``: the night builder raises ``RuntimeError``: ``invalid (RuntimeError)``;
- ``stale_night_at``: ``night_at`` one minute past the cycle cap: ``invalid (night_at_age)``;
- ``frozen_listing``: the listing hides every file posted within the cap and a minute:
  ``nbm_stale``;
- ``bad_host``: every blend request goes to a host that never resolves: ``nbm_unreadable``;
- ``nbm_slow``: the reads run on a budget already spent: ``nbm_slow`` (the code an ``on`` pass
  gives when its reads do not finish within ``serve.chart_hold_seconds``).

A fault acts only on a pass whose gate opens (a slot with the gate shut is counted apart), and
``stale_night_at`` only on one that also built a night (it moves the nights' ``night_at``):
a gated ``stale_night_at`` pass with no night is counted apart too, as ``no_night``.

**What a pass records** (:func:`record`): its time, the fault (or none), whether the fetch gate
opened, the age of the blend cycle it read, the withheld codes, its nights, the read, build and
whole-tail times, and for an injected pass whether the in-memory with-nights file has no ``night``
and its bytes equal the published chart-off file's (computed in the pass). Counts and times only:
no name, no district, no text.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Final

FAULTS: Final = ("raise", "stale_night_at", "frozen_listing", "bad_host", "nbm_slow")
"""The faults the rotation cycles through, in order."""
EXPECTED: Final[Mapping[str, str]] = {
    "raise": "invalid (RuntimeError)",
    "stale_night_at": "invalid (night_at_age)",
    "frozen_listing": "nbm_stale",
    "bad_host": "nbm_unreadable",
    "nbm_slow": "nbm_slow",
}
"""The withheld code each fault must give."""
READER_FAULTS: Final = frozenset({"frozen_listing", "bad_host", "nbm_slow"})
"""The faults the blend's reader injects (the others act on the built nights)."""
ROTATE_EVERY: Final = 6
"""With ``rotate``, one grid pass in this many injects a fault."""
WINDOW: Final = timedelta(hours=48)
"""The summary's span: the records older than this are dropped."""
SCHEMA_VERSION: Final = 1
NAME: Final = "chart-shadow.json"
"""The summary's file, beside ``predictions/latest.json`` on the host."""


def grid_slot(now: datetime, minutes: Sequence[int]) -> int:
    """The pass's scheduled grid slot: the latest grid minute at or before ``now``, counted from
    the epoch (``len(minutes)`` slots an hour)."""
    grid = sorted(set(minutes))
    moment = now.astimezone(UTC).replace(second=0, microsecond=0)
    for _step in range(61):
        if moment.minute in grid:
            hours = int(moment.timestamp()) // 3600
            return hours * len(grid) + grid.index(moment.minute)
        moment -= timedelta(minutes=1)
    raise ValueError("an empty grid")


def fault_for(
    setting: str,
    now: datetime,
    minutes: Sequence[int],
    *,
    grid: bool,
    done: Iterable[Mapping[str, object]] = (),
) -> str | None:
    """The fault this pass injects: none; the fixed fault ``setting`` names, every pass; or, with
    ``rotate``, the rotation's fault on 1 slot in :data:`ROTATE_EVERY` (none between), once per
    slot: none when a record in ``done`` (the state's shadow records) already injected in it."""
    if setting == "none":
        return None
    if setting != "rotate":
        return setting
    if not grid:
        return None
    slot = grid_slot(now, minutes)
    if slot % ROTATE_EVERY or slot in _injected_slots(done, minutes):
        return None
    return FAULTS[(slot // ROTATE_EVERY) % len(FAULTS)]


def _injected_slots(records: Iterable[Mapping[str, object]], minutes: Sequence[int]) -> set[int]:
    """The slots of the records that injected a fault."""
    found: set[int] = set()
    for item in records:
        if item.get("fault") is None:
            continue
        try:
            at = datetime.fromisoformat(str(item["at"]))
        except (KeyError, ValueError):
            continue
        if at.tzinfo is not None:
            found.add(grid_slot(at, minutes))
    return found


def record(  # noqa: PLR0913 - one pass's facts
    now: datetime,
    *,
    fault: str | None,
    gated: bool,
    cycle: datetime | None,
    codes: Iterable[str],
    nights: int,
    read_ms: int,
    build_ms: int,
    extra_ms: int,
    clean: bool | None,
) -> dict[str, object]:
    """One shadow pass's record (counts and times only)."""
    at = now.astimezone(UTC).replace(microsecond=0)
    age = None if cycle is None else round((at - cycle) / timedelta(minutes=1))
    return {
        "at": at.isoformat(),
        "fault": fault,
        "gated": gated,
        "age": age,
        "codes": sorted(set(codes)),
        "nights": nights,
        "read_ms": read_ms,
        "build_ms": build_ms,
        "extra_ms": extra_ms,
        "clean": clean,
    }


def kept(records: Iterable[Mapping[str, object]], now: datetime) -> list[dict[str, object]]:
    """The records of the last :data:`WINDOW`, oldest first (one that does not read is dropped)."""
    since = now - WINDOW
    found: list[tuple[datetime, dict[str, object]]] = []
    for item in records:
        try:
            at = datetime.fromisoformat(str(item["at"]))
        except (KeyError, ValueError):
            continue
        if at.tzinfo is not None and since < at <= now + timedelta(minutes=5):
            found.append((at, dict(item)))
    found.sort(key=lambda pair: pair[0])
    return [item for _at, item in found]


def _ints(records: Iterable[Mapping[str, object]], key: str) -> list[int]:
    return [value for item in records if isinstance(value := item.get(key), int)]


def _spread(values: Sequence[int], *, least: bool = False) -> dict[str, int] | None:
    """p50, p95 and max (and min), nearest rank; None with no value."""
    if not values:
        return None
    ordered = sorted(values)

    def rank(percent: int) -> int:
        return ordered[max(0, -(-len(ordered) * percent // 100) - 1)]

    found = {"n": len(ordered), "p50": rank(50), "p95": rank(95), "max": ordered[-1]}
    return {"min": ordered[0], **found} if least else found


def _codes(item: Mapping[str, object]) -> list[str]:
    codes = item.get("codes")
    return [str(code) for code in codes] if isinstance(codes, list) else []


def _acted(item: Mapping[str, object]) -> bool:
    """Whether an injected fault had something to act on: the gate opened, and for
    ``stale_night_at`` a night was built (it moves the nights' ``night_at``)."""
    if item.get("gated") is not True:
        return False
    nights = item.get("nights")
    return item.get("fault") != "stale_night_at" or (isinstance(nights, int) and nights > 0)


def summary(
    records: Iterable[Mapping[str, object]], now: datetime, *, mode: str, setting: str
) -> dict[str, object]:
    """The counts-only summary of the last :data:`WINDOW` of shadow passes: passes (and how many
    opened the gate), the blend cycle's age at the clean passes that read one, the withheld codes
    of the clean passes (passes per code), the shadow tail's time, and per fault:

    - ``injected``: the passes it acted on (:func:`_acted`);
    - ``gate_shut``: its slots whose gate stayed shut, so the stage did not run;
    - ``no_night``: ``stale_night_at``'s gated passes that built no night (0 for the others);
    - ``with_expected_code`` and ``clean_chances``: of the injected passes, how many gave its
      code, and how many left the with-nights file with no night and the chart-off file's bytes;
    - ``not_clean``: every gated pass of the fault whose in-pass check failed (must be 0);
    - ``codes``: the codes its injected passes gave.

    GC4 is met for a fault when ``injected`` is at least 1 and ``with_expected_code`` and
    ``clean_chances`` both equal it."""
    found = kept(records, now)
    clean = [item for item in found if item.get("fault") is None]
    withheld: Counter[str] = Counter(code for item in clean for code in _codes(item))
    faults: dict[str, dict[str, object]] = {}
    for fault in FAULTS:
        slots = [item for item in found if item.get("fault") == fault]
        gated = [item for item in slots if item.get("gated") is True]
        injected = [item for item in gated if _acted(item)]
        produced: Counter[str] = Counter(code for item in injected for code in _codes(item))
        faults[fault] = {
            "injected": len(injected),
            "gate_shut": len(slots) - len(gated),
            "no_night": len(gated) - len(injected),
            "expected_code": EXPECTED[fault],
            "with_expected_code": sum(1 for item in injected if EXPECTED[fault] in _codes(item)),
            "clean_chances": sum(1 for item in injected if item.get("clean") is True),
            "not_clean": sum(1 for item in gated if item.get("clean") is False),
            "codes": dict(sorted(produced.items())),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.astimezone(UTC).replace(microsecond=0).isoformat(),
        "mode": mode,
        "chart_fault": setting,
        "window_hours": int(WINDOW / timedelta(hours=1)),
        "since": None if not found else found[0]["at"],
        "passes": len(found),
        "gated": sum(1 for item in found if item.get("gated") is True),
        "injected": sum(1 for item in found if item.get("fault") is not None and _acted(item)),
        "cycle_age_minutes": _spread(_ints(clean, "age"), least=True),
        "withheld": dict(sorted(withheld.items())),
        "extra_ms": _spread(_ints(found, "extra_ms")),
        "build_ms": _spread(_ints(found, "build_ms")),
        "read_ms": _spread(_ints(found, "read_ms")),
        "faults": faults,
    }

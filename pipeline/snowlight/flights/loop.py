"""The Flights live loop (docs/flights.md, "The live loop"): one live pass about every 20
minutes until a deadline, the way the closings reader keeps itself running.

Each pass is a child process under a hard time limit (a hang ends with that pass, never with
the loop), and the trip alerts follow each pass that wrote. A pass starts only when the host's
``latest.json`` is :data:`FRESH` old or more (or unreadable), and never sooner than
:data:`CADENCE` after the loop's previous pass began. A failed pass is one annotation and the
loop goes on; no pass starts at or after the deadline."""

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

CADENCE: Final = timedelta(minutes=20)
"""From one pass's start to the next."""
FRESH: Final = timedelta(minutes=15)
"""A ``latest.json`` younger than this is fresh: no pass yet (today's rule)."""
AHEAD: Final = timedelta(minutes=1)
"""A stamp further ahead of the clock than this is not believed: the file reads as unreadable."""
PASS_SECONDS: Final = 540.0
"""The hard limit of one pass (the pass itself stops asking after 6 minutes)."""
ALERTS_SECONDS: Final = 240.0
"""The hard limit of the trip alerts after a pass."""
EXIT_TIMEOUT: Final = 124
"""What a pass or the alerts that reached the hard limit count as (``timeout``'s code)."""

_WHY: Final = {
    3: "nothing written: neither the forecast nor the FAA status read",
    EXIT_TIMEOUT: "ended at its time limit",
}


@dataclass(frozen=True, slots=True)
class Outcome:
    """What a loop did: passes started, passes that wrote, passes that failed."""

    passes: int
    written: int
    failed: int


def made_of(body: bytes | None) -> datetime | None:
    """``generated_at`` of a ``latest.json`` body (``None``: no body, or none that reads)."""
    if body is None:
        return None
    try:
        made = json.loads(body).get("generated_at")
        moment = datetime.fromisoformat(made)
    except (ValueError, TypeError, AttributeError):
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(UTC)


def run(  # noqa: PLR0913 - the loop's clock, reads and children
    *,
    deadline: datetime,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None],
    made: Callable[[], datetime | None],
    one_pass: Callable[[], int],
    alerts: Callable[[], int],
    log: Callable[[str], None],
) -> Outcome:
    """Passes until ``deadline``; what they did. ``made`` reads the host's ``latest.json``
    stamp, ``one_pass`` and ``alerts`` run their child and give its exit code."""
    passes = written = failed = 0
    last: datetime | None = None
    while True:
        now = clock()
        if now >= deadline:
            break
        wake: datetime | None = None
        if last is not None and now < last + CADENCE:
            wake = last + CADENCE
        else:
            stamp = made()
            if stamp is not None and stamp > now + AHEAD:
                log(
                    f"flights loop: latest.json {_minute(stamp)} is ahead of the clock: a pass runs"
                )
                stamp = None
            if stamp is not None and now - stamp < FRESH:
                log(f"flights loop: latest.json made at {_minute(stamp)} is fresh: no pass yet")
                wake = stamp + FRESH
        if wake is not None:
            if wake >= deadline:
                break
            sleep(max((wake - now).total_seconds(), 1.0))
            continue
        last = now
        passes += 1
        code = one_pass()
        if code == 0:
            written += 1
            told = alerts()
            if told != 0:
                log(f"flights loop: the trip alerts ended with exit {told}; the loop goes on")
            continue
        failed += 1
        why = _WHY.get(code, "an error")
        log(
            f"::warning::flights loop: the pass at {_minute(now)} ended with exit {code} "
            f"({why}); the loop goes on"
        )
    log(f"flights loop: {passes} passes, {written} written, {failed} failed")
    return Outcome(passes=passes, written=written, failed=failed)


def until_of(text: str, now: datetime) -> datetime:
    """The deadline ``+300m`` (or ``5h``) names from ``now``."""
    body = text.lstrip("+").strip()
    if body.endswith("h"):
        return now + timedelta(hours=float(body[:-1]))
    return now + timedelta(minutes=float(body.removesuffix("m")))


def _minute(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")


def without(env: Mapping[str, str], names: Iterable[str]) -> dict[str, str]:
    """A child's environment: ``env`` less ``names`` (the secrets it never needs)."""
    dropped = set(names)
    return {key: value for key, value in env.items() if key not in dropped}

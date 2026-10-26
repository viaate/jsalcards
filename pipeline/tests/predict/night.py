"""A SYNTHETIC school night for the outlook's serving tests: a pass every half hour from the
afternoon before to the morning of, over a feed that changes as a storm's products would.

Every product, zone, time and amount here is made up for the tests; nothing comes from a real
alert or a real storm. The passes' published bytes are the golden of "off is S7-L's pass byte
for byte" (``golden/off_night.json``, written by this module's ``main`` with the code before
S7-F F3, and never again: a change to it is a change to what ships).
"""

import hashlib
import json
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from predict import world
from predict.test_publish import MemoryHost, make_pass
from snowlight.predict import cli
from snowlight.predict.artifact import ModelArtifact
from snowlight.predict.forecast_values import DistrictForecast, Forecasts
from snowlight.predict.outlook import Outlook, OutlookMode, fit
from snowlight.predict.outlook_live import ReadForecast
from snowlight.predict.publish import Mode
from snowlight.predict.serve import ServeModel
from snowlight.sources.nws.alerts import ActiveFeed, parse_active

GOLDEN: Final = Path(__file__).parent / "golden" / "off_night.json"
START: Final = world.utc("2026-01-06T15:07:00")  # 9:07 AM in Chicago, the day before
STEPS: Final = 44  # every 30 minutes to 12:37Z (6:37 AM in Chicago) on the school day
KEY: Final = "v1/predictions/latest.json"


def _vtec_time(text: str) -> str:
    """``2026-01-07T06:00`` as VTEC writes it (``260107T0600Z``)."""
    return f"{text[2:4]}{text[5:7]}{text[8:10]}T{text[11:13]}{text[14:16]}Z"


# Each SYNTHETIC product: in the feed from (inclusive) until (exclusive, empty: never), its
# action, code, event number, zone, when it was sent, its span and its event name.
PRODUCTS: Final = (
    ("2026-01-06T18:00", "2026-01-06T23:00", "NEW", "WS.A", 7, "MOZ028", "2026-01-06T18:00",
     "2026-01-07T06:00", "2026-01-08T00:00", "Winter Storm Watch"),
    ("2026-01-06T23:00", "", "UPG", "WS.A", 7, "MOZ028", "2026-01-06T23:00",
     "2026-01-07T06:00", "2026-01-08T00:00", "Winter Storm Watch"),
    ("2026-01-06T23:00", "", "EXA", "WS.W", 7, "MOZ028", "2026-01-06T23:00",
     "2026-01-07T06:00", "2026-01-08T00:00", "Winter Storm Warning"),
    ("2026-01-06T22:00", "2026-01-07T03:00", "NEW", "WW.Y", 8, "KSZ104", "2026-01-06T22:00",
     "2026-01-07T09:00", "2026-01-07T18:00", "Winter Weather Advisory"),
    ("2026-01-07T03:00", "2026-01-07T04:00", "CAN", "WW.Y", 8, "KSZ104", "2026-01-07T03:00",
     "2026-01-07T09:00", "2026-01-07T18:00", "Winter Weather Advisory"),
    ("2026-01-06T17:00", "2026-01-07T01:00", "NEW", "EC.A", 9, "UTZ105", "2026-01-06T17:00",
     "2026-01-07T09:00", "2026-01-07T17:00", "Extreme Cold Watch"),
    ("2026-01-07T01:00", "", "UPG", "EC.A", 9, "UTZ105", "2026-01-07T01:00",
     "2026-01-07T09:00", "2026-01-07T17:00", "Extreme Cold Watch"),
    ("2026-01-07T01:00", "", "NEW", "CW.Y", 10, "UTZ105", "2026-01-07T01:00",
     "2026-01-07T09:00", "2026-01-07T17:00", "Cold Weather Advisory"),
)  # fmt: skip


def products(now: datetime) -> list[dict[str, Any]]:
    """The SYNTHETIC products in the feed at ``now``: a winter storm watch for the Missouri
    zone from 18Z, upgraded to a warning at 23Z; a winter weather advisory for the Kansas zone
    at 22Z, cancelled at 03Z; an extreme cold watch for Utah from 17Z, replaced by a cold
    weather advisory at 01Z. In the order :data:`PRODUCTS` lists them, a watch before the
    product that replaces it."""
    t = now.strftime("%Y-%m-%dT%H:%M")
    order = (0, 1, 2, 3, 4, 5, 6, 7)
    found: list[dict[str, Any]] = []
    for k in order:
        since, until, action, code, etn, ugc, sent, onset, ends, event = PRODUCTS[k]
        if t < since or (until and t >= until):
            continue
        vtec = f"/O.{action}.KEAX.{code}.{etn:04d}.{_vtec_time(onset)}-{_vtec_time(ends)}/"
        found.append(
            world.feature(
                vtec,
                (ugc,),
                sent=f"{sent}:00+00:00",
                onset=f"{onset}+00:00",
                ends=f"{ends}+00:00",
                event=event,
            )
        )
    return found


def feed_at(now: datetime) -> ActiveFeed:
    """The feed a pass at ``now`` reads (updated a minute before)."""
    updated = (now - timedelta(minutes=1)).isoformat()
    return parse_active(world.feed_bytes(products(now), updated))


def times() -> list[datetime]:
    """Every pass of the night."""
    return [START + timedelta(minutes=30 * step) for step in range(STEPS)]


def run_night(
    mode: Mode = Mode.ON,
    *,
    prepare: Callable[[cli.Pass], None] | None = None,
    at: Sequence[datetime] | None = None,
) -> tuple[list[bytes | None], cli.Pass, MemoryHost]:
    """The night's passes on one pass object (its state carried pass to pass): the bytes the
    live root holds after each (``None`` before the first upload)."""
    host = MemoryHost()
    run = make_pass(host, mode=mode, directory=world.directory())
    clock = [START]
    run.now = lambda: clock[0]
    run.alerts = lambda: (feed_at(clock[0]), True)
    if prepare is not None:
        prepare(run)
    found: list[bytes | None] = []
    key = mode.key or KEY
    for moment in at if at is not None else times():
        clock[0] = moment
        assert cli.one_pass(run) == 0
        found.append(host.files.get(key))
    return found, run, host


def digests(files: Sequence[bytes | None]) -> list[str | None]:
    """Each file's SHA-256."""
    return [None if data is None else hashlib.sha256(data).hexdigest() for data in files]


def main() -> None:  # pragma: no cover - written once, with the code before S7-F F3
    """Write the golden digests of the night's published files."""
    files, _run, _host = run_night()
    GOLDEN.write_text(json.dumps({"digests": digests(files)}, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    main()


# --- the outlook's inputs: a SYNTHETIC T and a SYNTHETIC forecast --------------------------------


def outlook_model() -> tuple[ModelArtifact, Outlook]:
    """The v3 rates (the synthetic world's model) and a SYNTHETIC ``T``: two seasons of slot 5
    cases in Kansas and Missouri (:func:`predict.test_outlook.world_cases`)."""
    from predict.test_outlook import world_cases  # noqa: PLC0415

    return world.model(), fit(world_cases(), [2022, 2023])


def run_time(at: datetime) -> datetime:
    """The SYNTHETIC run that counts at ``at``: issued at :46 the hour before."""
    return at.replace(minute=0, second=0, microsecond=0) - timedelta(minutes=14)


SNOW: Final = {"2000004": (4, 6.2, 8.7), "2900001": (4, 6.0, 7.1)}
"""SYNTHETIC forecasts by LEAID: bucket 4 (6 to 9 inches), the schools' least and most."""


def fake_forecast(
    forecasts: Mapping[str, tuple[int, float, float]] = SNOW,
    *,
    stale: bool = False,
    error_zones: frozenset[str] = frozenset(),
) -> ReadForecast:
    """A reader of SYNTHETIC forecasts: each named district's bucket and snow range, every other
    district quiet; ``stale``: no run counts anywhere; ``error_zones``: those zones do not
    read."""

    def read(
        model: ServeModel,
        days: tuple[date, ...],
        now: datetime,
        moment: Callable[[date, str], datetime] | None,
        zones: Collection[str] | None,
    ) -> Forecasts:
        by_day: dict[date, dict[int, DistrictForecast]] = {}
        unread: dict[date, dict[str, str]] = {}
        for day in days:
            mine = by_day.setdefault(day, {})
            for index, leaid in enumerate(model.directory.district_ids):
                zone = model.time_zone[index]
                if zones is not None and zone not in zones:
                    continue
                if stale or zone in error_zones:
                    unread.setdefault(day, {})[zone] = "error" if zone in error_zones else "stale"
                    continue
                at = now if moment is None else moment(day, zone)
                code, low, high = forecasts.get(leaid, (0, 0.0, 0.2))
                mine[index] = DistrictForecast(
                    code=code, snow_low=low, snow_high=high, run_time=run_time(at)
                )
        return Forecasts(by_day, (), unread)

    return read


def with_outlook(mode: OutlookMode, read: ReadForecast | None = None) -> Callable[[cli.Pass], None]:
    """Prepares a pass with the outlook ``mode``, the SYNTHETIC ``T`` and forecast."""

    def prepare(run: cli.Pass) -> None:
        run.outlook_mode = mode
        run.outlook_model = outlook_model
        run.outlook_forecast = read if read is not None else fake_forecast()

    return prepare

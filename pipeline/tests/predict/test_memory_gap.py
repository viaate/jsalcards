"""A history error no longer darkens a pass whose alert memory the 5-minute checks kept whole
(predict-next MEMORY-GAP): the Nov 8 replay, every byte as today while the history answers, the
checks' proof, the chain a read breaks, the save at ``until`` and the switch. SYNTHETIC alerts
only."""

import argparse
import copy
import json
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from predict import night, world
from predict.test_frozen import headers
from predict.test_loop import storm_product
from predict.test_publish import MemoryHost, make_pass
from snowlight.predict import cli, host_files
from snowlight.predict.alerts_live import alerts_digest, live_events, memory_digest, withdrawn
from snowlight.predict.config import PredictConfig, ServeSettings
from snowlight.predict.outlook import OutlookMode
from snowlight.predict.publish import Dark, DarkError, State
from snowlight.schemas.predictions import Forecast, PredictionsFile
from snowlight.sources.nws.alerts import ActiveFeed, NwsAlert, parse_active

U = world.utc
KEY = "v1/predictions/latest.json"
JAN7 = date(2026, 1, 7)
ON = world.CONFIG
OFF = ON.model_copy(update={"serve": ON.serve.model_copy(update={"memory_checks": False})})
FAILED = "predict: dark (alert_memory: alert history: HTTP 500)"
WHOLE = "the memory was whole"
MINE, NEWER = "a" * 40, "b" * 40
REFUSED = host_files.Refused(Dark.EDITION, "edition.json: a key this code does not know")

type Features = Callable[[datetime, int], list[dict[str, Any]]]
"""The feed's alerts at a time; the int counts the reads made before at that same time (a
check's read is 0, the extra pass it starts reads 1)."""


@pytest.fixture(autouse=True)
def _forgotten() -> Iterator[None]:
    host_files.forget()
    yield
    host_files.forget()


def update(feature: dict[str, Any], name: str) -> dict[str, Any]:
    """A product of the feed with an id of its own (a second product of one VTEC event)."""
    feature["properties"]["id"] = f"urn:test:{name}"
    return feature


def history_of(*features: dict[str, Any]) -> list[NwsAlert]:
    """The products as the alert history gives them."""
    return [
        alert
        for one in features
        for alert in parse_active(world.feed_bytes([one], "2026-01-07T00:00:00+00:00")).alerts
    ]


def fresh(features: list[dict[str, Any]], at: datetime, *, age: float = 1) -> ActiveFeed:
    """The feed at ``at``, ``updated`` ``age`` minutes before."""
    return parse_active(world.feed_bytes(features, (at - timedelta(minutes=age)).isoformat()))


STORM = storm_product()


def quiet(_at: datetime, _n: int) -> list[dict[str, Any]]:
    """One quiet feed: the storm's warning alone."""
    return [STORM]


def a_minute_old(_at: datetime, _n: int) -> float:
    return 1


def chance(files: bytes, day: date = JAN7) -> float:
    """District 1's chance of no school on ``day`` in an uploaded file."""
    made = PredictionsFile.from_json_bytes(files)
    entry = made.districts[1].days[made.days.index(day)]
    assert isinstance(entry, Forecast)
    return round(entry.p_no_school, 2)


class Died(BaseException):
    """The run stops inside a pass (the OOM killer, a cancelled job)."""


@dataclass
class Ran:
    """One loop on a fake clock: what it did."""

    run: cli.Pass
    passes: list[datetime] = field(default_factory=list)
    uploads: list[tuple[datetime, bytes]] = field(default_factory=list)
    saves: list[tuple[datetime, dict[str, Any]]] = field(default_factory=list)
    asked: list[datetime] = field(default_factory=list)
    product_asked: list[datetime] = field(default_factory=list)
    dark: int = 0
    died: bool = False
    err: str = ""

    def at(self) -> list[str]:
        return [f"{when:%H:%M}" for when in self.passes]

    def chances(self) -> list[tuple[str, float]]:
        return [(f"{when:%H:%M}", chance(files)) for when, files in self.uploads]

    def saved_at(self) -> list[str]:
        return [f"{when:%H:%M}" for when, _ in self.saves]

    def last(self) -> State:
        return State.from_json(copy.deepcopy(self.saves[-1][1]))

    def longest_wait(self) -> timedelta:
        times = [when for when, _ in self.uploads]
        return max(b - a for a, b in pairwise(times))

    def lines(self, text: str) -> list[str]:
        return [line for line in self.err.splitlines() if text in line]


@dataclass(frozen=True)
class Setup:
    """One loop from ``start`` to ``until`` and everything a test may swap. ``history``: every
    product the history holds (each given once it was sent); ``fails``: from when (and until
    when) it raises; ``refused_from``: the directory refuses from then; ``die_at``: the first
    pass from then dies after it ran; ``stop_after``: the loop's sleep raises from then (the
    run is cut off)."""

    start: datetime
    until: datetime
    features: Features = quiet
    history: Sequence[NwsAlert] = ()
    fails: datetime | tuple[datetime, datetime] | None = None
    config: PredictConfig = ON
    state: State | None = None
    age: Callable[[datetime, int], float] = a_minute_old
    frozen: Path | None = None
    shadow: bool = False
    refused_from: datetime | None = None
    head: str | None = None
    die_at: datetime | None = None
    stop_after: datetime | None = None

    def failing_now(self, at: datetime) -> bool:
        if self.fails is None:
            return False
        begins, ends = (
            (self.fails, U("2100-01-01T00:00")) if isinstance(self.fails, datetime) else self.fails
        )
        return begins <= at < ends


@dataclass
class Fakes:
    """The fakes of one loop: its clock, the feed, the history, the directory, the uploads, the
    passes and the saves."""

    setup: Setup
    ran: Ran
    directory_of: Callable[[], Any]
    write: Callable[[Any], None]
    real_pass: Callable[..., int]
    clock: list[datetime] = field(default_factory=list)
    reads: list[datetime] = field(default_factory=list)

    def now(self) -> datetime:
        return self.clock[0]

    def alerts(self) -> tuple[ActiveFeed, bool]:
        at = self.now()
        n = self.reads.count(at)
        self.reads.append(at)
        return fresh(self.setup.features(at, n), at, age=self.setup.age(at, n)), True

    def history(self, asked: list[datetime]) -> Callable[[datetime, datetime], Sequence[NwsAlert]]:
        def read(_start: datetime, _end: datetime) -> Sequence[NwsAlert]:
            asked.append(self.now())
            if self.setup.failing_now(self.now()):
                raise DarkError(Dark.MEMORY, "alert history: HTTP 500")
            return [alert for alert in self.setup.history if alert.sent <= self.now()]

        return read

    def directory(self) -> Any:
        if self.setup.refused_from is not None and self.now() >= self.setup.refused_from:
            raise REFUSED
        return self.directory_of()

    def upload(self, files: Any) -> None:
        if KEY in files:
            self.ran.uploads.append((self.now(), files[KEY]))
        self.write(files)

    def one_pass(self, found: cli.Pass, *, grid: bool = True) -> int:
        self.ran.passes.append(self.now())
        code = self.real_pass(found, grid=grid)
        if self.setup.die_at is not None and self.now() >= self.setup.die_at:
            raise Died
        return code

    def sleep(self, seconds: float) -> None:
        if self.setup.stop_after is not None and self.now() >= self.setup.stop_after:
            raise Died
        self.clock[0] += timedelta(seconds=seconds)

    def save(self, saved: State) -> None:
        self.ran.saves.append((self.now(), copy.deepcopy(saved.as_json())))

    def head(self) -> str | None:
        return self.setup.head


def looped(capsys: Any, monkeypatch: Any, setup: Setup) -> Ran:
    """Run the real loop as ``setup`` says."""
    host_files.forget()
    host = MemoryHost()
    run = make_pass(host, directory=world.directory(), config=setup.config)
    ran = Ran(run)
    if setup.state is not None:
        run.state = setup.state
    fakes = Fakes(setup, ran, run.directory, host.write, cli.one_pass, [setup.start])
    run.now = fakes.now
    run.alerts = fakes.alerts
    run.history = fakes.history(ran.asked)
    if setup.shadow:
        run.product_history = fakes.history(ran.product_asked)
        night.with_outlook(OutlookMode.SHADOW)(run)
    if setup.frozen is not None:
        run.frozen = setup.frozen
    run.directory = fakes.directory
    monkeypatch.setattr(host, "write", fakes.upload)
    monkeypatch.setattr(cli, "one_pass", fakes.one_pass)
    capsys.readouterr()
    clock = cli.Loop(fakes.now, fakes.sleep, None if setup.head is None else fakes.head, MINE)
    try:
        ran.dark = cli.loop(run, setup.until, clock, fakes.save)
    except Died:
        ran.died = True
    finally:
        monkeypatch.setattr(cli, "one_pass", fakes.real_pass)
    ran.err = capsys.readouterr().err
    return ran


# --- 1. the Nov 8 replay -------------------------------------------------------------------


def test_a_history_error_at_a_quiet_grid_pass_no_longer_darkens_it(
    capsys: Any, monkeypatch: Any, tmp_path: Path
) -> None:
    start, until = U("2026-01-07T03:07"), U("2026-01-07T04:37")
    fails = (U("2026-01-07T03:37"), U("2026-01-07T03:57"))
    late: dict[str, int] = {}
    for label, config in (("off", OFF), ("on", ON)):
        folder = tmp_path / label
        folder.mkdir()
        ran = looped(
            capsys,
            monkeypatch,
            Setup(
                start=start,
                until=until,
                history=history_of(STORM),
                fails=fails,
                config=config,
                frozen=folder,
            ),
        )
        frozen = headers(folder, JAN7)
        late[label] = frozen["America/Chicago", "d1_2130"]["late_by_s"]
        if label == "off":  # pins today
            assert ran.dark == 2
            assert ran.at() == ["03:07", "03:37", "03:47", "03:57", "04:07"]
            assert ran.longest_wait() == timedelta(minutes=50)
            assert len(ran.lines(FAILED)) == 2
        else:
            assert ran.dark == 0
            assert ran.at() == ["03:07", "03:37", "04:07"]
            assert ran.longest_wait() == timedelta(minutes=30)
            assert [f"{when:%H:%M}" for when in ran.asked] == ["03:07", "03:37", "04:07"]
            assert ran.lines(WHOLE) == [
                "warning: predict: alert_memory: alert history: HTTP 500; the memory was whole "
                "at the 03:32Z check: the pass goes on from it"
            ]
            assert ran.lines("predict: dark (") == []
    assert late == {"off": 1620, "on": 420}
    # The outlook in shadow, its product history failing in the same window: the record step
    # backs off instead of asking the history that just failed.
    ran = looped(
        capsys,
        monkeypatch,
        Setup(
            start=start,
            until=until,
            history=history_of(STORM),
            fails=fails,
            shadow=True,
        ),
    )
    assert ran.dark == 0
    assert [f"{when:%H:%M}" for when in ran.product_asked] == ["03:07", "04:07"]
    assert ran.lines("outlook shadow: DarkError") == [
        "warning: outlook shadow: DarkError: nothing recorded this pass (alert_memory: the "
        "product log's history read failed; no new try before 04:07Z)"
    ]


# --- 2. while the history answers, every byte is today's -------------------------------------

CODES = {"WW": ("Y", "Winter Weather Advisory"), "WS": ("W", "Winter Storm Warning")}
EVENINGS: tuple[tuple[tuple[str, int, str, str, tuple[str, ...], str, str], ...], ...] = (
    # seed 0
    (
        ("01-06T22:24", 101, "NEW", "WS", ("KSZ104",), "01-07T07:24", "01-07T11:24"),
        ("01-06T22:57", 101, "EXP", "WS", ("KSZ104",), "01-07T07:24", "01-07T11:24"),
        ("01-06T22:36", 102, "NEW", "WW", ("KSZ104",), "01-07T00:36", "01-07T01:36"),
        ("01-06T23:09", 102, "UPG", "WW", ("KSZ104",), "01-07T00:36", "01-07T01:36"),
        ("01-06T23:17", 103, "NEW", "WW", ("MOZ028", "UTZ105"), "01-07T05:17", "01-07T09:17"),
        ("01-06T23:23", 103, "CAN", "WW", ("MOZ028", "UTZ105"), "01-07T05:17", "01-07T09:17"),
        ("01-06T23:34", 104, "NEW", "WS", ("UTZ105",), "01-07T08:34", "01-07T12:34"),
        ("01-07T00:07", 104, "CON", "WS", ("UTZ105",), "01-07T08:34", "01-07T12:34"),
        ("01-07T00:00", 105, "NEW", "WW", ("UTZ105",), "01-07T09:00", "01-07T21:00"),
        ("01-07T00:06", 105, "UPG", "WW", ("UTZ105",), "01-07T09:00", "01-07T21:00"),
        ("01-07T00:17", 106, "NEW", "WS", ("UTZ105",), "01-07T06:17", "01-07T18:17"),
        ("01-07T00:23", 106, "EXT", "WS", ("UTZ105",), "01-07T06:17", "01-07T20:17"),
        ("01-07T00:43", 107, "NEW", "WW", ("MOZ028",), "01-07T09:43", "01-07T10:43"),
        ("01-07T00:49", 107, "CAN", "WW", ("MOZ028",), "01-07T09:43", "01-07T10:43"),
        ("01-07T01:09", 108, "NEW", "WS", ("KSZ104",), "01-07T07:09", "01-07T19:09"),
        ("01-07T01:15", 108, "UPG", "WS", ("KSZ104",), "01-07T07:09", "01-07T19:09"),
        ("01-07T01:21", 109, "NEW", "WW", ("KSZ104", "MOZ028"), "01-07T10:21", "01-07T14:21"),
        ("01-07T01:35", 109, "CAN", "WW", ("KSZ104", "MOZ028"), "01-07T10:21", "01-07T14:21"),
        ("01-07T01:29", 110, "NEW", "WW", ("MOZ028",), "01-07T07:29", "01-07T11:29"),
        ("01-07T01:35", 110, "CON", "WW", ("MOZ028",), "01-07T07:29", "01-07T11:29"),
        ("01-07T02:10", 111, "NEW", "WW", ("MOZ028",), "01-07T02:10", "01-07T14:10"),
        ("01-07T03:20", 111, "UPG", "WW", ("MOZ028",), "01-07T02:10", "01-07T14:10"),
        ("01-07T02:22", 112, "NEW", "WW", ("UTZ105",), "01-07T11:22", "01-07T23:22"),
        ("01-07T02:55", 112, "EXP", "WW", ("UTZ105",), "01-07T11:22", "01-07T23:22"),
        ("01-07T02:39", 113, "NEW", "WS", ("KSZ104",), "01-07T02:39", "01-07T06:39"),
        ("01-07T03:12", 113, "EXT", "WS", ("KSZ104",), "01-07T02:39", "01-07T08:39"),
        ("01-07T02:47", 114, "NEW", "WW", ("MOZ028", "UTZ105"), "01-07T08:47", "01-07T09:47"),
        ("01-07T03:20", 114, "EXP", "WW", ("MOZ028", "UTZ105"), "01-07T08:47", "01-07T09:47"),
    ),
    # seed 1
    (
        ("01-06T22:15", 101, "NEW", "WW", ("KSZ104", "MOZ028"), "01-07T07:15", "01-07T11:15"),
        ("01-06T23:25", 101, "EXT", "WW", ("KSZ104", "MOZ028"), "01-07T07:15", "01-07T13:15"),
        ("01-06T22:18", 102, "NEW", "WS", ("KSZ104",), "01-07T07:18", "01-07T19:18"),
        ("01-06T22:24", 102, "EXP", "WS", ("KSZ104",), "01-07T07:18", "01-07T19:18"),
        ("01-06T22:30", 103, "NEW", "WW", ("KSZ104",), "01-06T22:30", "01-06T23:30"),
        ("01-06T22:36", 103, "UPG", "WW", ("KSZ104",), "01-06T22:30", "01-06T23:30"),
        ("01-06T22:33", 104, "NEW", "WS", ("KSZ104",), "01-06T22:33", "01-07T10:33"),
        ("01-06T22:47", 104, "EXP", "WS", ("KSZ104",), "01-06T22:33", "01-07T10:33"),
        ("01-06T22:50", 105, "NEW", "WW", ("MOZ028", "UTZ105"), "01-07T07:50", "01-07T11:50"),
        ("01-06T22:56", 105, "EXP", "WW", ("MOZ028", "UTZ105"), "01-07T07:50", "01-07T11:50"),
        ("01-06T23:16", 106, "NEW", "WW", ("UTZ105",), "01-07T05:16", "01-07T06:16"),
        ("01-06T23:49", 106, "UPG", "WW", ("UTZ105",), "01-07T05:16", "01-07T06:16"),
        ("01-06T23:33", 107, "NEW", "WW", ("KSZ104", "UTZ105"), "01-07T08:33", "01-07T20:33"),
        ("01-06T23:39", 107, "EXP", "WW", ("KSZ104", "UTZ105"), "01-07T08:33", "01-07T20:33"),
        ("01-06T23:41", 108, "NEW", "WS", ("MOZ028", "UTZ105"), "01-07T05:41", "01-07T17:41"),
        ("01-07T00:14", 108, "CON", "WS", ("MOZ028", "UTZ105"), "01-07T05:41", "01-07T17:41"),
        ("01-06T23:58", 109, "NEW", "WW", ("UTZ105",), "01-07T08:58", "01-07T12:58"),
        ("01-07T01:08", 109, "CON", "WW", ("UTZ105",), "01-07T08:58", "01-07T12:58"),
        ("01-07T00:15", 110, "NEW", "WW", ("KSZ104", "UTZ105"), "01-07T02:15", "01-07T03:15"),
        ("01-07T00:29", 110, "CON", "WW", ("KSZ104", "UTZ105"), "01-07T02:15", "01-07T03:15"),
        ("01-07T00:23", 111, "NEW", "WW", ("KSZ104", "UTZ105"), "01-07T06:23", "01-07T10:23"),
        ("01-07T00:56", 111, "UPG", "WW", ("KSZ104", "UTZ105"), "01-07T06:23", "01-07T10:23"),
        ("01-07T00:49", 112, "NEW", "WW", ("MOZ028", "UTZ105"), "01-07T02:49", "01-07T06:49"),
        ("01-07T00:55", 112, "EXP", "WW", ("MOZ028", "UTZ105"), "01-07T02:49", "01-07T06:49"),
        ("01-07T01:01", 113, "NEW", "WW", ("KSZ104", "UTZ105"), "01-07T10:01", "01-07T14:01"),
        ("01-07T01:07", 113, "UPG", "WW", ("KSZ104", "UTZ105"), "01-07T10:01", "01-07T14:01"),
        ("01-07T01:27", 114, "NEW", "WS", ("MOZ028", "UTZ105"), "01-07T03:27", "01-07T15:27"),
        ("01-07T01:41", 114, "UPG", "WS", ("MOZ028", "UTZ105"), "01-07T03:27", "01-07T15:27"),
    ),
    # seed 2
    (
        ("01-06T22:10", 101, "NEW", "WW", ("KSZ104",), "01-07T00:10", "01-07T12:10"),
        ("01-06T22:43", 101, "CAN", "WW", ("KSZ104",), "01-07T00:10", "01-07T12:10"),
        ("01-06T22:36", 102, "NEW", "WW", ("UTZ105",), "01-07T00:36", "01-07T04:36"),
        ("01-06T23:46", 102, "UPG", "WW", ("UTZ105",), "01-07T00:36", "01-07T04:36"),
        ("01-06T22:48", 103, "NEW", "WS", ("MOZ028", "UTZ105"), "01-07T04:48", "01-07T08:48"),
        ("01-06T23:21", 103, "EXP", "WS", ("MOZ028", "UTZ105"), "01-07T04:48", "01-07T08:48"),
        ("01-06T23:05", 104, "NEW", "WW", ("MOZ028",), "01-07T01:05", "01-07T02:05"),
        ("01-06T23:19", 104, "CAN", "WW", ("MOZ028",), "01-07T01:05", "01-07T02:05"),
        ("01-06T23:13", 105, "NEW", "WW", ("MOZ028", "UTZ105"), "01-07T08:13", "01-07T12:13"),
        ("01-06T23:46", 105, "UPG", "WW", ("MOZ028", "UTZ105"), "01-07T08:13", "01-07T12:13"),
        ("01-06T23:25", 106, "NEW", "WS", ("KSZ104", "MOZ028"), "01-07T08:25", "01-07T20:25"),
        ("01-06T23:39", 106, "EXP", "WS", ("KSZ104", "MOZ028"), "01-07T08:25", "01-07T20:25"),
        ("01-06T23:37", 107, "NEW", "WS", ("KSZ104", "UTZ105"), "01-07T08:37", "01-07T12:37"),
        ("01-07T00:47", 107, "EXP", "WS", ("KSZ104", "UTZ105"), "01-07T08:37", "01-07T12:37"),
        ("01-07T00:18", 108, "NEW", "WW", ("MOZ028", "UTZ105"), "01-07T06:18", "01-07T10:18"),
        ("01-07T00:51", 108, "CAN", "WW", ("MOZ028", "UTZ105"), "01-07T06:18", "01-07T10:18"),
        ("01-07T00:59", 109, "NEW", "WS", ("MOZ028", "UTZ105"), "01-07T09:59", "01-07T21:59"),
        ("01-07T01:32", 109, "UPG", "WS", ("MOZ028", "UTZ105"), "01-07T09:59", "01-07T21:59"),
        ("01-07T01:02", 110, "NEW", "WS", ("MOZ028",), "01-07T01:02", "01-07T02:02"),
        ("01-07T01:08", 110, "CAN", "WS", ("MOZ028",), "01-07T01:02", "01-07T02:02"),
        ("01-07T01:28", 111, "NEW", "WW", ("UTZ105",), "01-07T03:28", "01-07T07:28"),
        ("01-07T01:42", 111, "EXT", "WW", ("UTZ105",), "01-07T03:28", "01-07T09:28"),
        ("01-07T01:31", 112, "NEW", "WS", ("MOZ028",), "01-07T07:31", "01-07T11:31"),
        ("01-07T01:45", 112, "EXT", "WS", ("MOZ028",), "01-07T07:31", "01-07T13:31"),
        ("01-07T02:12", 113, "NEW", "WW", ("MOZ028",), "01-07T02:12", "01-07T03:12"),
        ("01-07T02:18", 113, "CON", "WW", ("MOZ028",), "01-07T02:12", "01-07T03:12"),
        ("01-07T02:24", 114, "NEW", "WS", ("MOZ028",), "01-07T04:24", "01-07T16:24"),
        ("01-07T02:30", 114, "EXP", "WS", ("MOZ028",), "01-07T04:24", "01-07T16:24"),
    ),
)
"""Three changing evenings (issued, continued, extended, cancelled, upgraded and expired
early), as ``p_same.py``'s generator gave them for seeds 0 to 2: (sent, event number, action,
phenomenon, zones, onset, ends), each time in January 2026."""


def stamp(when: datetime) -> str:
    return when.strftime("%y%m%dT%H%MZ")


def evening_product(row: tuple[str, int, str, str, tuple[str, ...], str, str]) -> dict[str, Any]:
    sent, number, action, phenomenon, zones, onset, ends = row
    at, begins, stops = (U(f"2026-{text}") for text in (sent, onset, ends))
    significance, event = CODES[phenomenon]
    vtec = (
        f"/O.{action}.KEAX.{phenomenon}.{significance}.{number:04d}.{stamp(begins)}-{stamp(stops)}/"
    )
    made = world.feature(
        vtec,
        zones,
        sent=at.isoformat(),
        onset=begins.isoformat(),
        ends=stops.isoformat(),
        event=event,
        message_type="Alert" if action == "NEW" else "Update",
    )
    return update(made, f"{number}:{action}:{at.isoformat()}:{','.join(zones)}")


EARLY = world.feature(
    "/O.NEW.KEAX.WW.Y.0005.260106T1800Z-260107T0030Z/",
    ("MOZ028",),
    sent="2026-01-06T16:00:00+00:00",
    onset="2026-01-06T18:00:00+00:00",
    ends="2026-01-07T00:30:00+00:00",
    event="Winter Weather Advisory",
)
"""A Winter Weather Advisory for the Missouri zone, 12:00 to 18:30 CST."""
EXPIRED = update(
    world.feature(
        "/O.EXP.KEAX.WW.Y.0005.000000T0000Z-260107T0030Z/",
        ("MOZ028",),
        sent="2026-01-06T23:45:00+00:00",
        onset="2026-01-06T18:00:00+00:00",
        ends="2026-01-07T00:30:00+00:00",
        event="Winter Weather Advisory",
        message_type="Update",
    ),
    "exp",
)
"""... expired early, at 17:45 CST."""


def evening(seed: int) -> tuple[Features, list[NwsAlert]]:
    """One changing evening: the feed holds each event's latest product until it ends."""
    timed = [
        (
            U("2026-01-06T16:00"),
            evening_product(
                ("01-06T16:00", 5, "NEW", "WW", ("MOZ028",), "01-06T18:00", "01-07T00:30")
            ),
        ),
        (
            U("2026-01-06T23:45"),
            evening_product(
                ("01-06T23:45", 5, "EXP", "WW", ("MOZ028",), "01-06T18:00", "01-07T00:30")
            ),
        ),
    ]
    timed += [(U(f"2026-{row[0]}"), evening_product(row)) for row in EVENINGS[seed]]
    timed.sort(key=lambda pair: pair[0])

    def features(at: datetime, _n: int) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for sent, product in timed:
            if sent > at:
                break
            props = product["properties"]
            latest[
                str((props["parameters"]["VTEC"][0].split(".")[3:6], props["geocode"]["UGC"]))
            ] = product
        return [one for one in latest.values() if U(one["properties"]["ends"][:19]) > at]

    return features, history_of(*(product for _, product in timed))


def early_expiry(at: datetime, _n: int) -> list[dict[str, Any]]:
    return [EARLY] if at < U("2026-01-06T23:45") else [EXPIRED]


def test_while_the_history_answers_every_byte_is_today_s(capsys: Any, monkeypatch: Any) -> None:
    # (a) One quiet day.
    day = U("2026-01-07T02:07")
    quiet = {
        label: looped(
            capsys,
            monkeypatch,
            Setup(
                start=day,
                until=day + timedelta(days=1),
                history=history_of(STORM),
                config=config,
            ),
        )
        for label, config in (("off", OFF), ("on", ON))
    }
    assert quiet["on"].uploads == quiet["off"].uploads
    assert len(quiet["on"].asked) == len(quiet["off"].asked) == 48
    # (b) Three changing evenings: equal pass for pass.
    for seed in range(3):
        features, history = evening(seed)
        ran = {
            label: looped(
                capsys,
                monkeypatch,
                Setup(
                    start=U("2026-01-06T22:07"),
                    until=U("2026-01-07T04:07"),
                    features=features,
                    history=history,
                    config=config,
                ),
            )
            for label, config in (("off", OFF), ("on", ON))
        }
        assert ran["on"].passes == ran["off"].passes, seed
        assert ran["on"].uploads == ran["off"].uploads, seed
        assert ran["on"].dark == ran["off"].dark == 0, seed
    # (c) The early-expiry evening: the rebuild's 0.57 and the kept memory's 0.01, as today.
    for config in (OFF, ON):
        expiry = looped(
            capsys,
            monkeypatch,
            Setup(
                start=U("2026-01-06T23:37"),
                until=U("2026-01-07T01:08"),
                features=early_expiry,
                history=history_of(EARLY, EXPIRED),
                config=config,
            ),
        )
        assert expiry.chances() == [
            ("23:37", 0.57),
            ("23:47", 0.01),
            ("00:07", 0.01),
            ("00:37", 0.57),
            ("01:07", 0.57),
        ]


# --- 3. the history down ----------------------------------------------------------------------


def test_with_the_history_down_the_pass_serves_the_memory_it_kept(
    capsys: Any, monkeypatch: Any
) -> None:
    ran = {
        label: looped(
            capsys,
            monkeypatch,
            Setup(
                start=U("2026-01-06T23:37"),
                until=U("2026-01-07T01:08"),
                features=early_expiry,
                history=history_of(EARLY, EXPIRED),
                fails=U("2026-01-07T00:30"),
                config=config,
            ),
        )
        for label, config in (("off", OFF), ("on", ON))
    }
    assert ran["off"].dark == 4
    assert ran["off"].chances()[-1][0] == "00:07"
    assert ran["on"].dark == 0
    assert ran["on"].chances()[-2:] == [("00:37", 0.01), ("01:07", 0.01)]  # what 00:07Z showed
    assert ran["on"].chances()[2] == ("00:07", 0.01)


# --- 4. the check, the chain and the break's save (unit) -------------------------------------

ADVISORY = world.feature(
    "/O.NEW.KEAX.WW.Y.0002.260107T0600Z-260108T0000Z/",
    ("KSZ104",),
    sent="2026-01-07T02:10:00+00:00",
    onset="2026-01-07T06:00:00+00:00",
    ends="2026-01-08T00:00:00+00:00",
    event="Winter Weather Advisory",
)
"""A new advisory for the Kansas zone."""
CANCEL = update(
    world.feature(
        "/O.CAN.KEAX.WS.W.0009.260107T0600Z-260108T0000Z/",
        ("KSZ104",),
        sent="2026-01-07T02:10:00+00:00",
        onset="2026-01-07T06:00:00+00:00",
        ends="2026-01-08T00:00:00+00:00",
        message_type="Update",
    ),
    "can9",
)
"""A ``CAN`` of an event the memory never held: no live event, one take-back."""


def clone(state: State) -> State:
    return State.from_json(copy.deepcopy(state.as_json()))


def lone(
    state: State | None, at: datetime, features: list[dict[str, Any]], *, fails: bool | Exception
) -> tuple[int, cli.Pass, list[datetime]]:
    """One pass at ``at`` from ``state``; the history raises when ``fails`` (``fails`` itself
    when it is an error)."""
    run = make_pass(MemoryHost(), directory=world.directory())
    if state is not None:
        run.state = state
    run.now = lambda: at
    feed = fresh(features, at)
    run.alerts = lambda: (feed, True)
    asked: list[datetime] = []

    def read(_start: datetime, _end: datetime) -> Sequence[NwsAlert]:
        asked.append(at)
        if isinstance(fails, Exception):
            raise fails
        if fails:
            raise DarkError(Dark.MEMORY, "alert history: HTTP 500")
        return history_of(STORM)

    run.history = read
    return cli.safe_pass(run, grid=True), run, asked


@dataclass
class Proved:
    """A pass at 02:07Z, then a check at 02:12Z that proved its memory whole."""

    run: cli.Pass
    feed: ActiveFeed
    digest: str
    checked: datetime


def proved() -> Proved:
    first = U("2026-01-07T02:07")
    code, run, _ = lone(None, first, [STORM], fails=False)
    assert code == 0
    feed = fresh([STORM], first)
    digest = memory_digest(live_events(feed), withdrawn(feed.alerts))
    assert run.state.memory_taken == digest
    checked = U("2026-01-07T02:12")
    assert cli.memory_checked(run.state, fresh([STORM], checked), checked, ON.serve) == digest
    assert run.state.checked_at == checked
    return Proved(run, feed, digest, checked)


AFTER = U("2026-01-07T02:17")
"""The reads after the proving check."""


def raising(*_args: Any) -> str:
    raise ValueError("no digest")


def test_a_check_proves_the_memory_whole_only_when_its_feed_holds_nothing_new() -> None:
    p = proved()
    state = p.run.state
    before = (
        copy.deepcopy(state.memory),
        state.observed_at,
        state.memory_taken,
        state.alerts_digest,
    )
    stale = fresh([STORM], AFTER, age=21)
    advisory = fresh([STORM, ADVISORY], AFTER)
    cancel = fresh([STORM, CANCEL], AFTER)
    assert live_events(cancel) == live_events(p.feed)
    assert withdrawn(cancel.alerts) != withdrawn(p.feed.alerts)
    late, early = p.checked + timedelta(minutes=21), p.checked - timedelta(minutes=1)
    cases: list[tuple[State, ActiveFeed, datetime]] = [
        (state, stale, AFTER),
        (state, advisory, AFTER),
        (state, cancel, AFTER),
        (state, fresh([STORM], late), late),
        (state, fresh([STORM], early), early),
        (replace(state, memory_since=None), fresh([STORM], AFTER), AFTER),
        (replace(state, memory_taken=None), fresh([STORM], AFTER), AFTER),
    ]
    for one, its_feed, now in cases:
        seen = cli.memory_checked(one, its_feed, now, ON.serve)
        assert seen == memory_digest(live_events(its_feed), withdrawn(its_feed.alerts))
        assert one.checked_at == p.checked
    assert cli.seen_in(stale) == p.digest
    assert len({cli.seen_in(advisory), cli.seen_in(cancel), p.digest}) == 3
    after = (state.memory, state.observed_at, state.memory_taken, state.alerts_digest)
    assert after == before


def test_a_read_that_saw_more_breaks_the_chain_unless_its_pass_took_it_in() -> None:
    p = proved()
    state = p.run.state
    advisory = fresh([STORM, ADVISORY], AFTER)
    new = cli.seen_in(advisory)
    for reads in ((p.digest,), (None,), ()):
        kept = clone(state)
        cli.chain_after(kept, *reads)
        assert (kept.memory_taken, kept.checked_at) == (p.digest, p.checked)
    for breaking in ((new,), (p.digest, new)):
        broken = clone(state)
        cli.chain_after(broken, *breaking)
        assert (broken.memory_taken, broken.checked_at) == (None, None)
    # ... unless the pass took that feed in.
    took = make_pass(MemoryHost(), directory=world.directory())
    took.state = clone(state)
    took.now = lambda: AFTER
    took.alerts = lambda: (advisory, True)
    assert cli.one_pass(took) == 0
    assert took._feed_seen == new
    assert took.state.memory_taken == new
    cli.chain_after(took.state, new)
    assert (took.state.memory_taken, took.state.checked_at) == (new, p.checked)


def test_a_break_is_saved_at_the_read_that_found_it(capsys: Any) -> None:
    p = proved()
    run, state = p.run, clone(p.run.state)
    new = cli.seen_in(fresh([STORM, ADVISORY], AFTER))
    saved: list[State] = []
    run._save = saved.append
    cli.keep_break(run, None)
    cli.keep_break(run, p.digest)
    assert saved == []
    cli.keep_break(run, new)
    cli.keep_break(run, "")
    assert len(saved) == 2
    for one in saved:
        assert "memory_taken" not in one.as_json()
        assert "checked_at" not in one.as_json()
    assert (run.state.memory_taken, run.state.checked_at) == (p.digest, p.checked)
    saved.clear()
    run.state = replace(clone(state), memory_taken=None, checked_at=None)
    cli.keep_break(run, new)
    assert saved == []
    run.state = replace(clone(state), memory_taken=None)
    cli.keep_break(run, new)
    assert len(saved) == 1
    saved.clear()
    run.state = clone(state)
    run._save = None
    cli.keep_break(run, new)
    assert saved == []

    def refuse(_state: State) -> None:
        raise OSError("no room")

    run._save = refuse
    capsys.readouterr()
    cli.keep_break(run, new)
    assert capsys.readouterr().err == "warning: the state did not save: no room\n"


def test_a_digest_that_raises_breaks_the_chain_and_darkens_nothing_new(
    capsys: Any, monkeypatch: Any
) -> None:
    p = proved()
    run = p.run
    saved: list[State] = []
    run._save = saved.append
    monkeypatch.setattr(cli, "memory_digest", raising)
    assert cli.seen_in(p.feed) == ""
    late_pass = U("2026-01-07T02:37")
    run.now = lambda: late_pass
    run.alerts = lambda: (fresh([STORM], late_pass, age=25), True)
    capsys.readouterr()
    assert cli.safe_pass(run, grid=True) == cli.EXIT_DARK
    dark = [line for line in capsys.readouterr().err.splitlines() if "dark (" in line]
    assert len(dark) == 1
    assert dark[0].startswith("predict: dark (alerts_stale: ")
    assert run._newer_code is False
    assert len(saved) == 1
    assert "memory_taken" not in saved[0].as_json()


def test_a_check_that_raises_breaks_the_chain_at_once(capsys: Any, monkeypatch: Any) -> None:
    """Each check's read breaks the chain, whether ``memory_checked`` raises or the loop's
    own digest of the feed does (the read answered but could not be judged); the passes
    are those of today."""
    real = alerts_digest

    def at_checks(events: Any) -> str:
        if sys._getframe(1).f_code.co_name == "loop":
            raise ValueError("no digest")
        return real(events)

    raised: dict[str, Ran] = {}
    for label, config, name, fake in (
        ("checked", ON, "memory_checked", raising),
        ("digest", ON, "alerts_digest", at_checks),
        ("off", OFF, None, None),
    ):
        if name is not None:
            monkeypatch.setattr(cli, name, fake)
        raised[label] = looped(
            capsys,
            monkeypatch,
            Setup(
                start=U("2026-01-07T02:07"),
                until=U("2026-01-07T03:10"),
                history=history_of(STORM),
                config=config,
            ),
        )
        monkeypatch.undo()
    for label in ("checked", "digest"):
        breaks = ["02:07", "02:12", "02:37", "02:42", "03:07", "03:10"]
        assert raised[label].saved_at() == breaks, label
        assert raised[label].at() == raised["off"].at() == ["02:07", "02:37", "03:07"], label
        assert raised[label].last().checked_at is None, label


# --- 5. no proof, no fallback -------------------------------------------------------------


def on_grid(at: datetime) -> bool:
    """A pass's own read on a grid wake (the loop reads no feed there)."""
    return at.minute in (7, 37) and at.second == 0


def test_no_proof_no_fallback(capsys: Any, monkeypatch: Any) -> None:
    fails = U("2026-01-07T02:37")

    def checks_fail(at: datetime, _n: int) -> list[dict[str, Any]]:
        if not on_grid(at):
            raise DarkError(Dark.ALERTS, "HTTP 503")
        return [STORM]

    for features, age in (
        (checks_fail, lambda _t, _n: 1),
        (quiet, lambda at, _n: 1 if on_grid(at) else 25),
    ):
        ran = looped(
            capsys,
            monkeypatch,
            Setup(
                start=U("2026-01-07T02:07"),
                until=U("2026-01-07T02:38"),
                features=features,
                age=age,
                history=history_of(STORM),
                fails=fails,
            ),
        )
        assert ran.at() == ["02:07", "02:37"]
        assert ran.lines("dark (") == [FAILED]
        assert ran.run.state.checked_at is None
    ran = looped(
        capsys,
        monkeypatch,
        Setup(
            start=fails,
            until=U("2026-01-07T02:38"),
            history=history_of(STORM),
            fails=fails,
        ),
    )
    assert ran.lines("dark (") == [FAILED]
    # Lone passes from saved states.
    code, run, _ = lone(None, U("2026-01-07T02:07"), [STORM], fails=False)
    assert code == 0
    base = run.state.as_json()
    assert base["memory_since"] == "2026-01-06T00:00:00+00:00"
    checked = "2026-01-07T02:32:00+00:00"
    control = {**base, "checked_at": checked}
    unexpected = "predict: dark (unexpected RuntimeError: alert history: no route)"
    states: dict[str, tuple[dict[str, Any], bool | Exception, str]] = {
        "memory_since later than the reach": (
            {**control, "memory_since": "2026-01-07T02:00:00+00:00"},
            True,
            FAILED,
        ),
        "no memory_since": (
            {k: v for k, v in control.items() if k != "memory_since"},
            True,
            FAILED,
        ),
        "no memory_taken": (
            {k: v for k, v in control.items() if k != "memory_taken"},
            True,
            FAILED,
        ),
        "memory_taken 7": ({**control, "memory_taken": 7}, True, FAILED),
        "checked after the pass": (
            {**base, "checked_at": "2026-01-07T02:38:00+00:00"},
            True,
            FAILED,
        ),
        "another error than the history's DarkError": (
            control,
            RuntimeError("alert history: no route"),
            unexpected,
        ),
    }
    for label, (saved, error, expected) in states.items():
        capsys.readouterr()
        code, _, asked = lone(State.from_json(copy.deepcopy(saved)), fails, [STORM], fails=error)
        err = capsys.readouterr().err
        assert code == cli.EXIT_DARK, label
        assert [line for line in err.splitlines() if "dark (" in line] == [expected], label
        assert WHOLE not in err, label
        assert asked == [fails], label
    # The control: the same state with every condition held goes on.
    capsys.readouterr()
    code, _, _ = lone(State.from_json(copy.deepcopy(control)), fails, [STORM], fails=True)
    err = capsys.readouterr().err
    assert code == 0
    assert f"{WHOLE} at the 02:32Z check" in err
    assert "dark (" not in err


# --- 6. what a fallback pass leaves ------------------------------------------------------------


def test_a_fallback_pass_leaves_the_memory_as_a_pass_without_a_rebuild_would(
    capsys: Any, monkeypatch: Any
) -> None:
    # A state whose memory_since is earlier than the reach, read a minute before the loop, so
    # keeping memory_since and setting it to the reach give different values.
    code, before, _ = lone(None, U("2026-01-07T03:06"), [STORM], fails=False)
    assert code == 0
    reach = "2026-01-06T00:00:00+00:00"
    earlier = "2026-01-05T12:00:00+00:00"
    assert before.state.as_json()["memory_since"] == reach
    before.state.memory_since = U(earlier)
    ran = looped(
        capsys,
        monkeypatch,
        Setup(
            start=U("2026-01-07T03:07"),
            until=U("2026-01-07T04:37"),
            history=history_of(STORM),
            fails=(U("2026-01-07T03:37"), U("2026-01-07T03:57")),
            state=before.state,
        ),
    )
    assert ran.saved_at() == ["03:07", "03:37", "04:07", "04:37"]
    kept, fallback, again = (saved for _, saved in ran.saves[:3])
    assert kept["memory_since"] == fallback["memory_since"] == earlier
    assert fallback["observed_at"] == "2026-01-07T03:37:00+00:00"
    at = U("2026-01-07T03:37")
    assert fallback["memory_taken"] == cli.seen_in(fresh([STORM], at))
    assert len(ran.lines(f"{WHOLE} at the 03:32Z check")) == 1
    # Its twin: the same state, read 5 minutes before, so the history is never asked.
    twin = State.from_json(copy.deepcopy(kept))
    twin.observed_at = U("2026-01-07T03:32")
    code, run, asked = lone(twin, at, [STORM], fails=True)
    assert code == 0
    assert asked == []
    assert run.state.as_json()["memory"] == fallback["memory"]
    # The next grid pass asks the history again, and its rebuild sets the reach.
    assert ran.asked == [at, U("2026-01-07T04:07")]
    assert again["memory_since"] == reach


# --- 7. the last check reaches the next run --------------------------------------------------


def test_the_last_check_reaches_the_next_run(capsys: Any, monkeypatch: Any) -> None:
    end = U("2026-01-07T03:07")
    for config in (ON, OFF):
        first = looped(
            capsys,
            monkeypatch,
            Setup(
                start=U("2026-01-07T02:07"),
                until=end,
                history=history_of(STORM),
                config=config,
            ),
        )
        if config is ON:
            assert first.last().checked_at == U("2026-01-07T03:02")
            assert len(first.saves) == len(first.passes) + 1
            after: tuple[tuple[float, int], ...] = ((3.5, 0), (15, 0), (15.5, 1))
        else:
            assert first.last().checked_at is None
            assert len(first.saves) == len(first.passes)
            after = ((3.5, 1),)
        for minutes, dark in after:
            start = end + timedelta(minutes=minutes)
            ran = looped(
                capsys,
                monkeypatch,
                Setup(
                    start=start,
                    until=start + timedelta(minutes=1),
                    history=history_of(STORM),
                    fails=start,
                    config=config,
                    state=first.last(),
                ),
            )
            assert ran.dark == dark, minutes
            assert len(ran.uploads) == 1 - dark, minutes


# --- 8. the switch ------------------------------------------------------------------------------


def test_the_switch(capsys: Any, monkeypatch: Any) -> None:
    assert PredictConfig.load().serve.memory_checks is True
    without = ON.serve.model_dump()
    del without["memory_checks"]
    assert ServeSettings.model_validate(without).memory_checks is False
    off = looped(
        capsys,
        monkeypatch,
        Setup(
            start=U("2026-01-07T02:07"),
            until=U("2026-01-07T03:10"),
            history=history_of(STORM),
            config=OFF,
        ),
    )
    assert len(off.saves) == len(off.passes) == 3
    for _, saved in off.saves:
        assert "memory_taken" not in saved
        assert "checked_at" not in saved
    # A state an on run saved loses both keys from an off run's first save, also when no pass
    # reaches the memory.
    on = looped(
        capsys,
        monkeypatch,
        Setup(
            start=U("2026-01-07T01:07"),
            until=U("2026-01-07T02:20"),
            history=history_of(STORM),
        ),
    )
    assert {"memory_taken", "checked_at"} <= set(on.saves[-1][1])
    refused = looped(
        capsys,
        monkeypatch,
        Setup(
            start=U("2026-01-07T02:37"),
            until=U("2026-01-07T02:50"),
            history=history_of(STORM),
            config=OFF,
            state=on.last(),
            refused_from=U("2026-01-07T02:37"),
        ),
    )
    assert refused.dark == 2
    assert refused.saved_at() == ["02:37", "02:47"]
    for _, saved in refused.saves:
        assert "memory_taken" not in saved
        assert "checked_at" not in saved
    assert State.from_json({"memory_taken": ""}).memory_taken is None
    assert State.from_json({"checked_at": "2026-01-07T02:32:00"}).checked_at is None
    assert State.from_json({"checked_at": "soon"}).checked_at is None


def answering(feed: ActiveFeed) -> Callable[[], tuple[ActiveFeed, bool]]:
    """A feed read that answers ``feed``."""
    return lambda: (feed, True)


def once(monkeypatch: Any, tmp_path: Path, run: cli.Pass) -> tuple[int, dict[str, Any]]:
    """``predict once`` with ``run`` as its pass: its exit code and the state it saved."""
    monkeypatch.setattr(cli, "make_pass", lambda _args, _env: run)
    path = tmp_path / "state.json"
    code = cli.run_once(argparse.Namespace(state=path), {})
    saved: dict[str, Any] = json.loads(path.read_text())
    return code, saved


def test_predict_once_clears_both_keys_off_and_judges_its_own_read(
    monkeypatch: Any, tmp_path: Path
) -> None:
    keys = {"memory_taken", "checked_at"}
    held = proved().run.state
    assert keys <= set(held.as_json())
    # Off: a state that holds both keys saves neither.
    off = make_pass(MemoryHost(), directory=world.directory(), config=OFF)
    off.state = clone(held)
    off.now = lambda: AFTER
    off.alerts = lambda: (fresh([STORM], AFTER), True)
    off.history = lambda _start, _end: history_of(STORM)
    code, saved = once(monkeypatch, tmp_path, off)
    assert code == 0
    assert not keys & set(saved)
    # On: its own read, stale so dark before the memory, breaks the chain when it holds what the
    # memory has not taken, and keeps it when it holds the same.
    for features, kept in (([STORM, CANCEL], False), ([STORM], True)):
        on = make_pass(MemoryHost(), directory=world.directory())
        on.state = clone(held)
        on.now = lambda: AFTER
        on.alerts = answering(fresh(features, AFTER, age=25))
        code, saved = once(monkeypatch, tmp_path, on)
        assert code == cli.EXIT_DARK
        assert (keys <= set(saved)) is kept
        assert bool(keys & set(saved)) is kept


# --- 9. a read that saw more breaks the chain --------------------------------------------------

LEFT = world.feature(
    "/O.NEW.KEAX.WW.Y.0007.260106T1800Z-260107T0600Z/",
    ("MOZ028",),
    sent="2026-01-06T16:00:00+00:00",
    onset="2026-01-06T18:00:00+00:00",
    ends="2026-01-07T06:00:00+00:00",
    event="Winter Weather Advisory",
)
"""A Winter Weather Advisory for the Missouri zone that leaves the feed at 01:45Z without a
cancel."""
UTAH = world.feature(
    "/O.NEW.KSLC.WS.W.0003.260107T1200Z-260108T0000Z/",
    ("UTZ105",),
    sent="2026-01-06T15:00:00+00:00",
    onset="2026-01-07T12:00:00+00:00",
    ends="2026-01-08T00:00:00+00:00",
)
"""A Utah warning that stands throughout."""


def cancelled(sent: str) -> dict[str, Any]:
    """The advisory's ``CAN``, sent at ``sent`` (UTC, HH:MM)."""
    return update(
        world.feature(
            "/O.CAN.KEAX.WW.Y.0007.000000T0000Z-260107T0600Z/",
            ("MOZ028",),
            sent=f"2026-01-07T{sent}:00+00:00",
            onset="2026-01-06T18:00:00+00:00",
            ends="2026-01-07T06:00:00+00:00",
            event="Winter Weather Advisory",
            message_type="Update",
        ),
        "can7",
    )


def extended(sent: str) -> dict[str, Any]:
    """The Utah warning extended by an ``EXT`` sent at ``sent``."""
    return update(
        world.feature(
            "/O.EXT.KSLC.WS.W.0003.260107T1200Z-260108T0600Z/",
            ("UTZ105",),
            sent=f"2026-01-07T{sent}:00+00:00",
            onset="2026-01-07T12:00:00+00:00",
            ends="2026-01-08T06:00:00+00:00",
            message_type="Update",
        ),
        "ext3",
    )


def left_world(
    cancel: dict[str, Any], within: Callable[[datetime, int], bool], ext: str | None = None
) -> tuple[Features, list[NwsAlert]]:
    """The advisory left the feed at 01:45Z; its ``cancel`` is in the feed ``within``; the
    Utah warning stands (extended at ``ext``)."""
    utah = UTAH if ext is None else extended(ext)

    def features(at: datetime, n: int) -> list[dict[str, Any]]:
        found = [UTAH if ext is None or at < U(f"2026-01-07T{ext}") else utah]
        if at < U("2026-01-07T01:45"):
            found.append(LEFT)
        if within(at, n):
            found.append(cancel)
        return found

    return features, history_of(UTAH, LEFT, cancel, *([utah] if ext is not None else []))


def between(start: str, end: str) -> Callable[[datetime, int], bool]:
    return lambda at, _n: U(f"2026-01-07T{start}") <= at < U(f"2026-01-07T{end}")


def test_a_read_that_saw_more_breaks_the_chain(capsys: Any, monkeypatch: Any) -> None:
    start = U("2026-01-07T01:07")

    def three(
        features: Features, history: list[NwsAlert], until: str, fails: str
    ) -> dict[str, Ran]:
        cases = {"answers": (ON, None), "on": (ON, fails), "off": (OFF, fails)}
        return {
            label: looped(
                capsys,
                monkeypatch,
                Setup(
                    start=start,
                    until=U(f"2026-01-07T{until}"),
                    features=features,
                    history=history,
                    config=config,
                    fails=None if failing is None else U(f"2026-01-07T{failing}"),
                ),
            )
            for label, (config, failing) in cases.items()
        }

    def dark_as_today(ran: dict[str, Ran]) -> None:
        for label in ("on", "off"):
            assert ran[label].dark == 1, label
            assert ran[label].lines(FAILED) == [FAILED], label
            assert ran[label].lines(WHOLE) == [], label

    # The CAN read by the 02:17, 02:22 and 02:27 checks, gone before the 02:37 pass.
    ran = three(*left_world(cancelled("02:13"), between("02:13", "02:28")), "02:40", "02:37")
    assert ran["answers"].chances()[-1] == ("02:37", 0.01)  # the rebuild withdraws it
    dark_as_today(ran)
    # A new advisory the check sees and its extra pass takes in: it goes on.
    issued = world.feature(
        "/O.NEW.KEAX.WW.Y.0008.260107T0300Z-260107T1800Z/",
        ("MOZ028",),
        sent="2026-01-07T02:31:00+00:00",
        onset="2026-01-07T03:00:00+00:00",
        ends="2026-01-07T18:00:00+00:00",
        event="Winter Weather Advisory",
    )
    change = looped(
        capsys,
        monkeypatch,
        Setup(
            start=U("2026-01-07T02:07"),
            until=U("2026-01-07T02:36"),
            features=lambda at, _n: [UTAH, *([issued] if at >= U("2026-01-07T02:31") else [])],
            history=history_of(UTAH, issued),
            fails=U("2026-01-07T02:30"),
        ),
    )
    assert change.dark == 0
    assert change.at() == ["02:07", "02:32"]
    assert change.lines(WHOLE) == [
        "warning: predict: alert_memory: alert history: HTTP 500; the memory was whole at the "
        "02:27Z check: the pass goes on from it"
    ]
    assert change.chances()[-1] == ("02:32", 0.57)
    # Re-armed without a rebuild: the CAN read by the 02:17 check alone, then an extra pass at
    # 02:22 for the Utah EXT takes in a feed the CAN has left.
    healed = three(
        *left_world(cancelled("02:13"), between("02:13", "02:20"), ext="02:21"), "03:10", "03:07"
    )
    assert "02:22" in healed["on"].at()
    assert healed["answers"].chances()[-1] == ("03:07", 0.01)
    dark_as_today(healed)
    # A check's read that its own pass did not take in: the 02:32 check reads the CAN and the
    # EXT, its pass's own read just after holds the EXT alone.
    only_the_check = three(
        *left_world(
            cancelled("02:30"),
            lambda at, n: at == U("2026-01-07T02:32") and n == 0,
            ext="02:31",
        ),
        "02:36",
        "02:30",
    )
    assert only_the_check["answers"].chances()[-1] == ("02:32", 0.01)
    dark_as_today(only_the_check)
    assert only_the_check["on"].saved_at().count("02:32") == 2
    # The same within the gap, so the extra pass does not rebuild: the 02:17 check reads the CAN
    # and the EXT, its pass's own read holds the EXT alone, and the break the check found holds
    # through the checks that follow to the 03:07 pass.
    within_the_gap = three(
        *left_world(
            cancelled("02:15"),
            lambda at, n: at == U("2026-01-07T02:17") and n == 0,
            ext="02:16",
        ),
        "03:10",
        "03:07",
    )
    assert "02:17" in within_the_gap["on"].at()
    assert within_the_gap["answers"].chances()[-1] == ("03:07", 0.01)
    dark_as_today(within_the_gap)


# --- 10. after a directory stretch ------------------------------------------------------------


def test_after_a_directory_stretch_the_successor_goes_on(capsys: Any, monkeypatch: Any) -> None:
    start, until = U("2026-01-07T02:07"), U("2026-01-07T03:12")
    refused = U("2026-01-07T02:10")

    def stretch(
        config: PredictConfig = ON,
        cancel: Callable[[datetime, int], bool] | None = None,
        stop_after: datetime | None = None,
    ) -> Ran:
        features = (
            quiet
            if cancel is None
            else (lambda at, n: [STORM, *([CANCEL] if cancel(at, n) else [])])
        )
        return looped(
            capsys,
            monkeypatch,
            Setup(
                start=start,
                until=until,
                features=features,
                history=history_of(STORM, CANCEL),
                config=config,
                refused_from=refused,
                head=NEWER,
                stop_after=stop_after,
            ),
        )

    def successor(first: State, at: datetime, config: PredictConfig = ON) -> Ran:
        return looped(
            capsys,
            monkeypatch,
            Setup(
                start=at,
                until=at + timedelta(minutes=1),
                history=history_of(STORM, CANCEL),
                fails=at,
                config=config,
                state=first,
            ),
        )

    handover = U("2026-01-07T03:00:30")
    for config in (ON, OFF):
        ran = stretch(config)
        assert ran.at() == ["02:07", "02:37", "02:47", "02:57"]
        assert ran.dark == 3
        assert len(ran.saves) == 4
        after = successor(ran.last(), handover, config)
        if config is ON:
            assert ran.last().checked_at == U("2026-01-07T02:57")
            assert after.dark == 0
            assert len(after.lines(f"{WHOLE} at the 02:57Z check")) == 1
        else:
            assert after.dark == 1
            assert after.lines(FAILED) == [FAILED]
    # A CAN of another event from 02:53: the 02:57 check saves the break.
    ran = stretch(cancel=lambda at, _n: at >= U("2026-01-07T02:53"))
    assert ran.saved_at() == ["02:07", "02:37", "02:47", "02:57", "02:57"]
    assert "memory_taken" not in ran.saves[-1][1]
    assert "checked_at" not in ran.saves[-1][1]
    assert successor(ran.last(), handover).lines(FAILED) == [FAILED]
    # Read only by the dark 02:37 grid pass: the break saved at that pass's read.
    ran = stretch(cancel=lambda at, _n: U("2026-01-07T02:33") <= at < U("2026-01-07T02:40"))
    assert ran.saved_at() == ["02:07", "02:37", "02:37", "02:47", "02:57"]
    assert successor(ran.last(), handover).lines(FAILED) == [FAILED]
    # Read only by the 02:52 check (no pass then), the run cut off right after it.
    cut = stretch(
        cancel=lambda at, _n: U("2026-01-07T02:50") <= at < U("2026-01-07T02:55"),
        stop_after=U("2026-01-07T02:52"),
    )
    assert cut.died
    assert cut.saved_at() == ["02:07", "02:37", "02:47", "02:52"]
    assert "memory_taken" not in cut.saves[-1][1]
    assert "checked_at" not in cut.saves[-1][1]
    early = U("2026-01-07T02:56:30")
    assert successor(cut.last(), early).lines(FAILED) == [FAILED]
    at_pass = State.from_json(copy.deepcopy(cut.saves[2][1]))
    assert at_pass.checked_at == U("2026-01-07T02:47")
    assert successor(at_pass, early).dark == 0  # what saves at passes alone would hand on

    # The run dies inside a pass, in test 9's world, the directory refusing from 02:10.
    # (i) the check's read, (ii) the pass's own read, (iii) the retry pass's own read after a
    # check that saw the quiet feed (its check saved nothing, so the pass's read saves).
    def retry_read(at: datetime, n: int) -> bool:
        return at == U("2026-01-07T02:47") and n == 1

    for sent, within, died in (
        ("02:55", between("02:55", "03:00"), "02:57"),
        ("03:05", between("03:05", "03:10"), "03:07"),
        ("02:46", retry_read, "02:47"),
    ):
        features, history = left_world(cancelled(sent), within)
        dead = looped(
            capsys,
            monkeypatch,
            Setup(
                start=U("2026-01-07T01:07"),
                until=U("2026-01-07T03:30"),
                features=features,
                history=history,
                refused_from=refused,
                die_at=U(f"2026-01-07T{died}"),
            ),
        )
        assert dead.died
        assert dead.saved_at()[-1] == died
        assert "memory_taken" not in dead.saves[-1][1]
        assert "checked_at" not in dead.saves[-1][1]
        at = U(f"2026-01-07T{died}") + timedelta(minutes=3, seconds=30)
        for fails, expect in ((at, None), (None, 0.01)):
            after = looped(
                capsys,
                monkeypatch,
                Setup(
                    start=at,
                    until=at + timedelta(minutes=1),
                    features=features,
                    history=history,
                    fails=fails,
                    state=dead.last(),
                ),
            )
            if expect is None:
                assert after.lines(FAILED) == [FAILED], died
                assert after.lines(WHOLE) == [], died
            else:
                assert after.chances()[0][1] == expect, died

"""The overrides job publishes ``v1`` as before the reader (S8-E round 4, privacy S2): its
publisher (``reader=False``) takes no recent day into its change log from the public day
timeline, and a blank keeps the host's default commit message; a reader's publisher does
both. SYNTHETIC world and host."""

import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from live.test_publish import MORNING, STAMP, Host, equal, storm
from live.world import World
from snowlight.live.overrides import EMPTY
from snowlight.live.publish import LivePublisher, Mode, day_path
from snowlight.live.publishers import DEFAULT_MESSAGE

V1 = "v1"


@dataclass
class Messages(Host):
    """The SYNTHETIC host, with a commit message as the GitHub host has, kept per write."""

    message: str = DEFAULT_MESSAGE
    sent: tuple[str, ...] = ()

    def write(self, files: dict[str, bytes]) -> None:  # type: ignore[override]
        self.sent = (*self.sent, self.message)
        self.message = DEFAULT_MESSAGE  # a per-write message, as the real host keeps it
        super().write(files)


def _publisher(world: World, host: Host, state: Path, *, reader: bool) -> LivePublisher:
    return LivePublisher(
        host=host,
        directory=world.dir,
        state_dir=state,
        internal_dir=state.parent / "internal",
        mode=Mode.ON,
        reader=reader,
    )


def _day(host: Host) -> bytes:
    return (host.root / V1 / day_path(MORNING.date())).read_bytes()


def test_the_overrides_job_takes_no_recent_day_from_the_public_timeline(tmp_path: Path) -> None:
    # the job's cache restores an older state (a failed save): its change log lacks a stretch
    # another run of the job published. As before the reader, the job writes the day from its
    # own log; a reader would take the public stretch in first
    days: dict[bool, bytes] = {}
    for reader in (False, True):
        world = World()
        root = tmp_path / ("reader" if reader else "job")
        host = Host(root / "host")
        state = root / "state"
        merged = storm(world)
        _publisher(world, host, state, reader=reader).publish(
            merged, now=MORNING, healthy_share=1.0, edition=equal(MORNING)
        )
        shutil.copytree(state, root / "older")  # the state the failed save left
        later = MORNING + timedelta(minutes=10)
        _publisher(world, host, state, reader=reader).publish(
            EMPTY, now=later, healthy_share=1.0, edition=equal(later)
        )
        last = MORNING + timedelta(minutes=20)
        _publisher(world, host, root / "older", reader=reader).publish(
            merged, now=last, healthy_share=1.0, edition=equal(last)
        )
        days[reader] = _day(host)
    # the job's day file is the one its own log makes: a run on a clean host with the same
    # older state writes the same bytes
    world = World()
    clean = Host(tmp_path / "clean" / "host")
    merged = storm(world)
    state = tmp_path / "clean" / "state"
    _publisher(world, clean, state, reader=False).publish(
        merged, now=MORNING, healthy_share=1.0, edition=equal(MORNING)
    )
    last = MORNING + timedelta(minutes=20)
    _publisher(world, clean, state, reader=False).publish(
        merged, now=last, healthy_share=1.0, edition=equal(last)
    )
    assert days[False] == _day(clean)
    assert days[True] != days[False]  # the reader keeps the dark stretch in its history


def test_the_overrides_jobs_blank_keeps_the_default_commit_message(tmp_path: Path) -> None:
    sent: dict[bool, tuple[str, ...]] = {}
    for reader in (False, True):
        world = World()
        host = Messages(tmp_path / f"host-{reader}")
        publisher = _publisher(world, host, tmp_path / f"state-{reader}", reader=reader)
        publisher.publish(storm(world), now=MORNING, healthy_share=1.0, edition=equal(MORNING))
        later = MORNING + timedelta(minutes=5)
        assert publisher.blank(now=later, stamp=STAMP).blank
        sent[reader] = host.sent
    assert sent[False][-1] == DEFAULT_MESSAGE
    assert sent[True][-1].startswith("live v1 blank ")

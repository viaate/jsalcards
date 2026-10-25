"""A shadow reader never touches ``v1/`` (S8-E section 3). SYNTHETIC world and host.

A shadow publisher is run through every path that writes: a good pass, a refused pass, the
edition blank (a stamp a public file carries, and a settled deployment that cannot be read),
the hold (and a file still lit under it), a hold set while the pass ran, a hold that cannot
be read after the upload, and the admin's statuses published alone. No key it writes is
under ``v1/``, while ``v1/`` holds the overrides job's own files throughout. ``live release``
needs ``--prefix``; ``live blank`` without one still holds and blanks every prefix.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pytest

from live.test_publish import MORNING, STAMP, Host, equal, storm
from live.world import World
from snowlight import cli
from snowlight.live.edition import EditionState, EditionVerdict
from snowlight.live.merge import AdminStatus
from snowlight.live.publish import (
    CLOSINGS,
    HOLD,
    PREFIXES,
    AdminPart,
    Exit,
    LiveHold,
    LivePublisher,
    Mode,
    emergency_blank,
    release,
)
from snowlight.live.publishers import PublishError
from snowlight.schemas.vocab import Status

SHADOW = "v1-shadow"


@dataclass
class Recording(Host):
    """The SYNTHETIC host, recording every key written; ``hold_reads_fail`` makes the hold
    file unreadable once an upload is in."""

    keys: list[str] = field(default_factory=list)
    hold_reads_fail: bool = False
    set_hold_on_write: bool = False

    def read(self, key: str) -> bytes | None:
        if self.hold_reads_fail and key.endswith(HOLD) and self.keys:
            raise PublishError("read hold: HTTP 503")
        return super().read(key)

    def write(self, files: Mapping[str, bytes]) -> None:
        self.keys.extend(files)
        super().write(files)
        if self.set_hold_on_write and any(key.endswith(CLOSINGS) for key in files):
            self.set_hold_on_write = False
            held = LiveHold(schema_version=1, held=True, at=MORNING, held_at=MORNING)
            super().write({f"{SHADOW}/{HOLD}": held.to_json_bytes()})


def _v1_publisher(world: World, host: Host, tmp: Path) -> None:
    """The overrides job's v1 file (what live-ingest.yml publishes today)."""
    LivePublisher(
        host=host,
        directory=world.dir,
        state_dir=tmp / "v1-state",
        internal_dir=tmp / "i",
        mode=Mode.ON,
    ).publish(storm(world), now=MORNING, healthy_share=1.0, edition=equal(MORNING))


def _shadow(world: World, host: Host, tmp: Path) -> LivePublisher:
    return LivePublisher(
        host=host,
        directory=world.dir,
        state_dir=tmp / "state",
        internal_dir=tmp / "i",
        mode=Mode.SHADOW,
    )


def _v1_keys(host: Recording) -> list[str]:
    return [key for key in host.keys if key.startswith("v1/")]


@pytest.fixture
def setup(tmp_path: Path) -> tuple[World, Recording, LivePublisher]:
    world = World()
    host = Recording(tmp_path / "host")
    _v1_publisher(world, host, tmp_path)
    host.keys.clear()
    return world, host, _shadow(world, host, tmp_path)


def test_every_shadow_path_writes_nothing_under_v1(
    setup: tuple[World, Recording, LivePublisher],
) -> None:
    world, host, shadow = setup
    v1_before = (host.root / "v1" / CLOSINGS).read_bytes()
    # a good pass, then an unchanged one, then a refused one
    later = MORNING + timedelta(minutes=5)
    merged = storm(world, later)
    assert (
        shadow.publish(merged, now=later, healthy_share=1.0, edition=equal(later)).exit is Exit.OK
    )
    refused = shadow.publish(
        merged, now=later + timedelta(minutes=5), healthy_share=0.1, edition=equal(later)
    )
    assert refused.exit is Exit.REFUSED
    # the edition blank: other content under the stamp both prefixes carry
    when = later + timedelta(minutes=10)
    different = EditionVerdict(
        EditionState.DIFFERENT, when, blank=STAMP, deployed=STAMP, alert=True
    )
    report = shadow.publish(merged, now=when, healthy_share=1.0, edition=different)
    assert report.blank
    # a settled deployment that cannot be read: every public file of the mode's prefix
    unread = EditionVerdict(EditionState.UNREADABLE, when, blank_every=True, alert=True)
    shadow.publish(merged, now=when + timedelta(minutes=1), healthy_share=1.0, edition=unread)
    # publish again, then the hold: the file still lit under it is blanked again
    when += timedelta(minutes=5)
    assert (
        shadow.publish(storm(world, when), now=when, healthy_share=1.0, edition=equal(when)).exit
        is Exit.OK
    )
    emergency_blank(host, when + timedelta(seconds=30), (SHADOW,))
    then = when + timedelta(minutes=5)
    held = shadow.publish(storm(world, then), now=then, healthy_share=1.0, edition=equal(when))
    assert held.refusals == ("held",)
    release(host, when + timedelta(minutes=6), (SHADOW,))
    # a hold set while the upload went up
    when += timedelta(minutes=10)
    host.set_hold_on_write = True
    shadow.publish(storm(world, when), now=when, healthy_share=1.0, edition=equal(when))
    release(host, when + timedelta(minutes=1), (SHADOW,))
    # a hold that cannot be read after the upload
    when += timedelta(minutes=10)
    host.keys.clear()
    host.hold_reads_fail = True
    unknown = shadow.publish(storm(world, when), now=when, healthy_share=1.0, edition=equal(when))
    assert unknown.exit is Exit.ERROR
    host.hold_reads_fail = False
    assert host.keys  # the blank went up, under v1-shadow
    # the admin's statuses alone, under a health refusal
    when += timedelta(minutes=10)
    admin = AdminPart(
        (
            AdminStatus(school=3, nces_id=next(iter(world.dir.schools)), day=date(2026, 11, 17),
                        status=Status.CLOSED, shift_minutes=None, clock_minute=None,
                        set_at=when - timedelta(minutes=1), level="school", key="synthetic"),
        )
    )  # fmt: skip
    shadow.publish(
        storm(world, when), now=when, healthy_share=0.1, edition=equal(when), admin=admin
    )
    assert _v1_keys(host) == []
    assert (host.root / "v1" / CLOSINGS).read_bytes() == v1_before


def test_the_whole_run_never_wrote_v1(tmp_path: Path) -> None:
    world = World()
    host = Recording(tmp_path / "host")
    _v1_publisher(world, host, tmp_path)
    host.keys.clear()
    shadow = _shadow(world, host, tmp_path)
    for step in range(4):
        now = MORNING + timedelta(minutes=5 * (step + 1))
        shadow.publish(
            storm(world, now), now=now, healthy_share=1.0, edition=equal(now), always=True
        )
    assert host.keys
    assert all(key.startswith(f"{SHADOW}/") for key in host.keys)


def test_release_needs_a_prefix_and_blank_holds_every_prefix(tmp_path: Path) -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["live", "release"])
    args = parser.parse_args(["live", "release", "--prefix", SHADOW])
    assert args.prefix == SHADOW
    assert parser.parse_args(["live", "blank"]).prefix == "every"
    host = Host(tmp_path / "host")
    assert release(host, MORNING, ()).exit is Exit.ERROR
    assert release(host, MORNING, ("v2",)).exit is Exit.ERROR
    report = emergency_blank(host, MORNING)
    assert {f"{prefix}/{HOLD}" for prefix in PREFIXES} <= set(report.uploaded)
    assert release(host, MORNING + timedelta(minutes=1), (SHADOW,)).exit is Exit.OK
    v1_hold = LiveHold.from_bytes((tmp_path / "host" / "v1" / HOLD).read_bytes())
    shadow_hold = LiveHold.from_bytes((tmp_path / "host" / SHADOW / HOLD).read_bytes())
    assert (v1_hold.held, shadow_hold.held) == (True, False)  # only the named prefix


def test_off_writes_nothing_at_all(tmp_path: Path) -> None:
    world = World()
    host = Recording(tmp_path / "host")
    off = LivePublisher(
        host=host,
        directory=world.dir,
        state_dir=tmp_path / "s",
        internal_dir=tmp_path / "i",
        mode=Mode.OFF,
    )
    report = off.publish(storm(world), now=MORNING, healthy_share=1.0, edition=equal(MORNING))
    assert (report.exit, host.keys) == (Exit.OK, [])
    unread = EditionVerdict(EditionState.UNREADABLE, MORNING, blank_every=True, alert=True)
    off.publish(storm(world), now=MORNING, healthy_share=1.0, edition=unread)
    assert host.keys == []

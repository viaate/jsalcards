"""predict learn labels a live day the same from the state export as from the whole state
(S8-E privacy 3: the Actions cache holds only the export). SYNTHETIC state."""

from datetime import date
from pathlib import Path

from predict import world
from predict.test_learn import DAY, WHOLE, listing, state_source
from snowlight.live.history import ChangeLog
from snowlight.live.ledger import Ledger
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.morning import ANY_KIND, MorningLog
from snowlight.live.state import ARCHIVE, export
from snowlight.predict import cli


def _state(folder: Path) -> None:
    folder.mkdir(parents=True)
    ledger = Ledger(folder / "ledger.sqlite")
    ledger.observe("tv", ReadOutcome.EMPTY, world.utc("2026-01-06T12:00:00"))
    ledger.close()
    for name in ("unmatched.json", "robots.json", "cadence.json", "publish.json", "pacer.json"):
        (folder / name).write_text("{}", encoding="utf-8")
    log = MorningLog(folder / "morning")
    log.record(world.utc("2026-01-06T13:00:00"), shown="v1", reads={"tv": WHOLE}, unknown=(),
               named={"2900002": {"*": {ANY_KIND}}})  # fmt: skip
    log.record(world.utc("2026-01-05T23:00:00"), shown="v1", reads={}, unknown=(),
               named={"2900003": {DAY.isoformat(): {"closed"}}})  # fmt: skip
    log.record(world.utc("2026-01-06T17:00:00"), shown="v1", reads={}, unknown=(), named={})
    ChangeLog(folder / "changes").commit(
        [
            listing(date(2026, 1, 2), "290000200003", "tv"),
            listing(date(2026, 1, 5), "290000200003", "tv"),
            listing(date(2026, 1, 5), "290000300004", "tv"),
        ]
    )


def test_predict_learn_labels_the_same_from_the_export(tmp_path: Path) -> None:
    _state(tmp_path / "state")
    store = tmp_path / "store"
    store.mkdir()
    (store / ARCHIVE).write_bytes(export(tmp_path / "state"))
    folder = cli.live_state_folder(tmp_path / "none", store, tmp_path / "scratch")
    assert folder == tmp_path / "scratch"
    exported = state_source(folder).morning(DAY)
    assert not isinstance(exported, str)
    assert exported.audience == {"tv": {"2900002": date(2026, 1, 2)}}
    assert exported == state_source(tmp_path / "state").morning(DAY)


def test_a_day_the_reader_ran_only_in_shadow_labels_nothing(tmp_path: Path) -> None:
    """The shadow export: every slot shown under v1-shadow only. Learning (which reads v1)
    labels nothing from it and writes nothing, rather than every district unknown."""
    from snowlight.predict.learn import NEVER  # noqa: PLC0415
    from snowlight.predict.live_labels import NOT_SHOWN  # noqa: PLC0415

    folder = tmp_path / "state"
    folder.mkdir()
    log = MorningLog(folder / "morning")
    for at in ("2026-01-06T13:00:00", "2026-01-06T17:00:00"):
        log.record(world.utc(at), shown="v1-shadow", reads={"tv": WHOLE}, unknown=(), named={})
    assert state_source(folder).morning(DAY) == NOT_SHOWN
    assert NOT_SHOWN in NEVER  # a later day need not wait for it

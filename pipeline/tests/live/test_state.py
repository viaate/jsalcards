"""The state stores: a folder, a private bucket and the Actions cache (SYNTHETIC state)."""

import io
import tarfile
from pathlib import Path

import httpx
import pytest

from live.test_publishers import Bucket
from live.world import ALPHA_SCHOOL, at, row
from snowlight.live.ledger import Ledger
from snowlight.live.ledger import Outcome as ReadOutcome
from snowlight.live.publishers import Credentials, PublishError
from snowlight.live.state import (
    STATE_KEY,
    LocalStateStore,
    StateError,
    bucket_store,
    check_state_key,
    pack,
    unpack,
)

KEYS = Credentials("SYNTHETICKEY", "SYNTHETIC/state-secret", "auto", "s3")


def _state(folder: Path) -> Ledger:
    folder.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(folder / "ledger.sqlite")
    ledger.observe("gray-synthetic", ReadOutcome.OK, at("2026-11-17 11:00"), [])
    ledger.observe("gray-synthetic", ReadOutcome.OK, at("2026-11-17 11:05"), [row(ALPHA_SCHOOL)])
    (folder / "publish.json").write_text('{"refused_streak": 0}', encoding="utf-8")
    (folder / "changes").mkdir(exist_ok=True)
    (folder / "changes" / "2026-11-17.jsonl").write_text('{"event":"lit"}\n', encoding="utf-8")
    (folder / "unmatched.json").write_text('{"entries":["SYNTHETIC name"]}', encoding="utf-8")
    return ledger


def test_pack_is_the_same_bytes_for_the_same_state(tmp_path: Path) -> None:
    ledger = _state(tmp_path / "state")
    first = pack(tmp_path / "state")
    assert pack(tmp_path / "state") == first
    ledger.close()


def test_a_ledger_open_for_writing_round_trips(tmp_path: Path) -> None:
    ledger = _state(tmp_path / "state")  # still open, as in a running ingest
    store = LocalStateStore(tmp_path / "store")
    assert store.push(tmp_path / "state") > 0
    names = store.pull(tmp_path / "restored")
    assert sorted(names) == [
        "changes/2026-11-17.jsonl",
        "ledger.sqlite",
        "publish.json",
        "unmatched.json",
    ]
    restored = Ledger(tmp_path / "restored" / "ledger.sqlite")
    assert [r.key for r in restored.rows("gray-synthetic")] == [
        r.key for r in ledger.rows("gray-synthetic")
    ]
    # the restored ledger keeps its secret: the same row has the same key
    assert restored.key("gray-synthetic", row(ALPHA_SCHOOL)) == ledger.key(
        "gray-synthetic", row(ALPHA_SCHOOL)
    )
    ledger.close()
    restored.close()


def test_a_first_run_pulls_nothing(tmp_path: Path) -> None:
    assert LocalStateStore(tmp_path / "empty").pull(tmp_path / "state") == []


def _archive(members: list[tuple[tarfile.TarInfo, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for info, data in members:
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@pytest.mark.parametrize("name", ["../escape.json", "/etc/escape.json", "a/../../escape.json"])
def test_unpack_refuses_paths_outside_the_folder(tmp_path: Path, name: str) -> None:
    data = _archive([(tarfile.TarInfo(name), b"{}")])
    with pytest.raises(StateError):
        unpack(data, tmp_path / "state")
    assert not (tmp_path / "escape.json").exists()


def test_unpack_refuses_links_and_damage(tmp_path: Path) -> None:
    link = tarfile.TarInfo("ledger.sqlite")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    with pytest.raises(StateError):
        unpack(_archive([(link, b"")]), tmp_path / "state")
    with pytest.raises(StateError, match="does not read"):
        unpack(b"not an archive", tmp_path / "state")


def test_the_bucket_store_keeps_state_under_its_one_key(tmp_path: Path) -> None:
    _state(tmp_path / "state").close()
    bucket = Bucket(KEYS)
    client = httpx.Client(transport=httpx.MockTransport(bucket))
    store = bucket_store("https://synthetic.r2.example", "snowlight-live-state", KEYS, client)
    assert store.pull(tmp_path / "restored") == []
    size = store.push(tmp_path / "state")
    stored, headers = bucket.objects[f"/snowlight-live-state/{STATE_KEY}"]
    assert len(stored) == size
    assert headers["cache-control"] == "no-store"
    assert headers["content-type"] == "application/gzip"
    assert "unmatched.json" in store.pull(tmp_path / "restored")


def test_the_bucket_store_refuses_any_other_key_and_reports_failures(tmp_path: Path) -> None:
    with pytest.raises(PublishError):
        check_state_key("v1/live/closings.json")
    _state(tmp_path / "state").close()
    bucket = Bucket(KEYS)
    bucket.fail = 500
    client = httpx.Client(transport=httpx.MockTransport(bucket))
    store = bucket_store("https://synthetic.r2.example", "private", KEYS, client)
    with pytest.raises(StateError, match=r"push: put state/live-state\.tar\.gz: HTTP 500"):
        store.push(tmp_path / "state")
    with pytest.raises(StateError, match="pull"):
        store.pull(tmp_path / "restored")


def test_temporary_files_are_not_kept(tmp_path: Path) -> None:
    folder = tmp_path / "state"
    folder.mkdir()
    (folder / ".publish.json.123.tmp").write_text("{}", encoding="utf-8")
    (folder / "ledger.sqlite-journal").write_text("x", encoding="utf-8")
    (folder / "publish.json").write_text("{}", encoding="utf-8")
    store = LocalStateStore(tmp_path / "store")
    store.push(folder)
    assert store.pull(tmp_path / "restored") == ["publish.json"]

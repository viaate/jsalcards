"""The data mirror's pin set, its release tag and the LSAD code table form."""

import re
from pathlib import Path

import pytest

from snowlight.mirror.pins import load_pin_set, mirror_root
from snowlight.sources.census.lsad import parse_lsad_codes
from snowlight.sources.mirror import (
    Form,
    Pin,
    asset_name,
    check_pin_set,
    lsad_table_page,
    pin_set_tag,
    pinned_digest,
    wait_from_env,
)

LSAD_FIXTURE = Path(__file__).resolve().parents[1] / "places" / "fixtures"
LSAD_FIXTURE /= "legal-status-codes.table.html"


def test_the_shipped_pin_set() -> None:
    pins = load_pin_set()
    assert len(pins) == len({pin.asset for pin in pins}) == 14
    assert [pin.url for pin in pins] == sorted(pin.url for pin in pins)
    assert re.fullmatch(r"data-mirror-[0-9a-f]{12}", pin_set_tag(pins))
    hosts = {pin.url.split("/")[2] for pin in pins}
    assert hosts == {"nces.ed.gov", "www2.census.gov", "www.census.gov"}
    # The release NCES has not published is not pinned, so it is not mirrored.
    assert not any("PRIVATESCH_2425" in pin.url for pin in pins)


def test_the_tag_names_the_whole_pin_set() -> None:
    one = Pin("https://h.test/a.zip", "a" * 64)
    two = Pin("https://h.test/b.zip", "b" * 64)
    assert pin_set_tag([one, two]) == pin_set_tag([two, one])
    assert pin_set_tag([one, two]) != pin_set_tag([one, Pin(two.url, "c" * 64)])
    assert pin_set_tag([one]) != pin_set_tag([Pin(one.url, one.sha256, Form.LSAD_TABLE)])


def test_a_pin_set_is_one_pin_per_url_and_asset() -> None:
    one = Pin("https://h.test/a.zip", "a" * 64)
    assert check_pin_set([one, one]) == (one,)
    with pytest.raises(ValueError, match="pinned twice"):
        check_pin_set([one, Pin(one.url, "b" * 64)])
    with pytest.raises(ValueError, match="share"):
        check_pin_set([one, Pin("https://other.test/x/a.zip", "b" * 64)])
    for url in ("http://h.test/a.zip", "https://h.test/a.zip?x=1", "https://h.test/a b.zip"):
        with pytest.raises(ValueError, match="asset"):
            asset_name(url)


def test_the_lsad_table_page_reads_back_to_the_same_codes(tmp_path: Path) -> None:
    page = LSAD_FIXTURE.read_text(encoding="utf-8")
    table = lsad_table_page(page)
    assert parse_lsad_codes(table.decode()) == parse_lsad_codes(page)
    assert lsad_table_page(table.decode()) == table
    # The same table in a page that differs elsewhere has the same digest.
    noisy = tmp_path / "noisy.html"
    noisy.write_text(page.replace("<table", "<p>token 1234</p><table", 1), encoding="utf-8")
    original = tmp_path / "page.html"
    original.write_text(page, encoding="utf-8")
    assert pinned_digest(noisy, Form.LSAD_TABLE) == pinned_digest(original, Form.LSAD_TABLE)
    assert pinned_digest(noisy, Form.FILE) != pinned_digest(original, Form.FILE)
    empty = tmp_path / "maintenance.html"
    empty.write_text("<html>down for maintenance</html>", encoding="utf-8")
    assert pinned_digest(empty, Form.LSAD_TABLE) is None


def test_the_root_and_wait_come_from_the_flag_or_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SNOWLIGHT_MIRROR", raising=False)
    assert mirror_root(None) is None
    monkeypatch.setenv("SNOWLIGHT_MIRROR", " https://m.test/ ")
    assert mirror_root(None) == "https://m.test/"
    assert mirror_root("") is None
    monkeypatch.setenv("SNOWLIGHT_REQUIRE_MIRROR", "1")
    assert mirror_root("https://m.test/") == "https://m.test/"
    for argument in ("", " ", None):
        monkeypatch.setenv("SNOWLIGHT_MIRROR", "")
        with pytest.raises(ValueError, match="no data mirror is set"):
            mirror_root(argument)
    monkeypatch.setenv("SNOWLIGHT_REQUIRE_MIRROR", "yes")
    with pytest.raises(ValueError, match="1 or 0"):
        mirror_root("https://m.test/")
    monkeypatch.setenv("SNOWLIGHT_REQUIRE_MIRROR", "0")
    assert mirror_root("") is None
    monkeypatch.setenv("SNOWLIGHT_MIRROR_WAIT", "")
    assert wait_from_env() == 0.0
    monkeypatch.setenv("SNOWLIGHT_MIRROR_WAIT", "900")
    assert wait_from_env() == 900.0
    monkeypatch.setenv("SNOWLIGHT_MIRROR_WAIT", "-1")
    with pytest.raises(ValueError, match="seconds"):
        wait_from_env()

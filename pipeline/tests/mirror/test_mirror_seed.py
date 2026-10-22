"""Seeding the data mirror from the origins: only what the release lacks, each file checked."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from snowlight.cli import main
from snowlight.mirror import cli as mirror_cli
from snowlight.mirror.cli import Releases, read_have, release_notes, seed
from snowlight.mirror.pins import load_pin_set
from snowlight.sources.mirror import Form, Pin, lsad_table_page, pin_set_tag
from snowlight.sources.nces.fetch import DownloadError, FileCache, SourceChangedError

LSAD_PAGE = (
    Path(__file__).resolve().parents[1] / "places" / "fixtures" / "legal-status-codes.table.html"
).read_text(encoding="utf-8")
LSAD_URL = "https://www.census.gov/library/reference/code-lists/legal-status-codes.html"
ZIP_URL = "https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PUBLICSCH_2425.zip"
ZIP_BYTES = b"PK\x03\x04 a pinned zip"
MAINTENANCE = b"<html><body>This site is under maintenance</body></html>"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


ROOT = "https://github.com/o/r/releases/download"


class Origin:
    """The origin servers; ``pages`` changes the LSAD page on every load, as census.gov does.

    ``releases`` holds the mirror's release assets by tag and asset name.
    """

    def __init__(
        self, files: dict[str, bytes], releases: dict[str, dict[str, bytes]] | None = None
    ) -> None:
        self.files = files
        self.releases = releases or {}
        self.loads = 0
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url.startswith(ROOT + "/"):
            tag, _slash, asset = url.removeprefix(ROOT + "/").partition("/")
            data = self.releases.get(tag, {}).get(asset)
            return httpx.Response(404) if data is None else httpx.Response(200, content=data)
        if url == LSAD_URL:
            self.loads += 1
            page = self.files[url].decode().replace("<table", f"<p>t{self.loads}</p><table", 1)
            return httpx.Response(200, content=page.encode(), headers={"Content-Type": "text/html"})
        if url not in self.files:
            return httpx.Response(404)
        return httpx.Response(200, content=self.files[url])

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def cache(self, root: Path) -> FileCache:
        return FileCache(root, self.client(), sleep=lambda _s: None)

    def releases_reader(self, tag: str, earlier: tuple[str, ...], scratch: Path) -> Releases:
        return Releases(self.client(), ROOT, tag, earlier, scratch, sleep=lambda _s: None)

    def origin_requests(self) -> list[str]:
        return [url for url in self.requests if not url.startswith(ROOT)]


def _held(*pins: Pin) -> dict[str, str | None]:
    return {pin.asset: f"sha256:{pin.sha256}" for pin in pins}


def _pins() -> tuple[Pin, Pin]:
    table = lsad_table_page(LSAD_PAGE)
    return Pin(ZIP_URL, _sha(ZIP_BYTES)), Pin(LSAD_URL, _sha(table), Form.LSAD_TABLE)


def test_seed_stages_what_the_release_lacks(tmp_path: Path) -> None:
    origin = Origin({ZIP_URL: ZIP_BYTES, LSAD_URL: LSAD_PAGE.encode()})
    zip_pin, lsad_pin = _pins()
    with origin.cache(tmp_path / "cache") as cache:
        staged = seed([(zip_pin, cache), (lsad_pin, cache)], {}, tmp_path / "up", print)
    assert [p.name for p in staged] == [zip_pin.asset, lsad_pin.asset]
    assert (tmp_path / "up" / zip_pin.asset).read_bytes() == ZIP_BYTES
    # The LSAD asset is the code table alone, the same whatever page carried it.
    assert _sha((tmp_path / "up" / lsad_pin.asset).read_bytes()) == lsad_pin.sha256
    origin.requests.clear()
    with origin.cache(tmp_path / "cache2") as cache:
        again = seed(
            [(zip_pin, cache), (lsad_pin, cache)], _held(zip_pin, lsad_pin), tmp_path / "up2", print
        )
    assert again == []
    assert origin.requests == []


def test_a_held_asset_counts_only_when_it_is_the_pinned_file(tmp_path: Path) -> None:
    """A listed asset whose digest is not the pin's (or, with no digest, whose bytes are not)
    is staged again, so a corrupt asset is replaced instead of kept forever."""
    zip_pin, _lsad = _pins()
    tag = "data-mirror-000000000001"
    origin = Origin({ZIP_URL: ZIP_BYTES}, {tag: {zip_pin.asset: b"PK\x03\x04 corrupt"}})

    def jobs(cache: FileCache) -> list[tuple[Pin, FileCache]]:
        return [(zip_pin, cache)]

    wrong = {zip_pin.asset: "sha256:" + "0" * 64}
    with origin.cache(tmp_path / "c1") as cache:
        staged = seed(jobs(cache), wrong, tmp_path / "up1", print)
    assert [p.read_bytes() for p in staged] == [ZIP_BYTES]
    unknown: dict[str, str | None] = {zip_pin.asset: None}
    reader = origin.releases_reader(tag, (), tmp_path / "s")
    with origin.cache(tmp_path / "c2") as cache:
        staged = seed(jobs(cache), unknown, tmp_path / "up2", print, reader)
    assert [p.read_bytes() for p in staged] == [ZIP_BYTES]
    # With no reader an unverifiable asset is staged again too: never assumed intact.
    with origin.cache(tmp_path / "c3") as cache:
        assert len(seed(jobs(cache), unknown, tmp_path / "up3", print)) == 1
    origin.releases[tag][zip_pin.asset] = ZIP_BYTES
    origin.requests.clear()
    with origin.cache(tmp_path / "c4") as cache:
        assert seed(jobs(cache), unknown, tmp_path / "up4", print, reader) == []
    assert origin.origin_requests() == []


def test_unchanged_files_are_copied_from_an_earlier_release(tmp_path: Path) -> None:
    """After a pin bump only the new file needs its origin: with the origins down, the
    files an earlier release holds intact are still staged, each checked against its pin."""
    zip_pin, lsad_pin = _pins()
    new_pin = Pin("https://nces.ed.gov/programs/edge/data/NEW.zip", _sha(b"PK\x03\x04 new"))
    table = lsad_table_page(LSAD_PAGE)
    newest, middle, oldest = (f"data-mirror-00000000000{i}" for i in (3, 2, 1))
    origin = Origin(
        {},
        {
            # The newest holds a file of the same name that is another release's bytes.
            newest: {zip_pin.asset: b"PK\x03\x04 revised in place"},
            middle: {zip_pin.asset: ZIP_BYTES},
            oldest: {lsad_pin.asset: table},
        },
    )
    reader = origin.releases_reader("data-mirror-ffffffffffff", (newest, middle, oldest), tmp_path)
    lines: list[str] = []
    with origin.cache(tmp_path / "cache") as cache:
        staged = seed(
            [(zip_pin, cache), (lsad_pin, cache)], {}, tmp_path / "up", lines.append, reader
        )
        assert [p.read_bytes() for p in staged] == [ZIP_BYTES, table]
        assert origin.origin_requests() == []
        assert f"  {zip_pin.asset}: staged from {middle} ({len(ZIP_BYTES)} bytes)" in lines
        # The copy sits in the seed's cache under its origin URL, for the proof's build.
        hit = cache.cached(ZIP_URL, zip_pin.sha256)
        assert hit is not None
        assert hit.mirror == f"{ROOT}/{middle}/{zip_pin.asset}"
        # A file no earlier release holds still needs its origin, which is down.
        with pytest.raises(DownloadError):
            seed([(new_pin, cache)], {}, tmp_path / "up2", lines.append, reader)
    assert origin.origin_requests() == [new_pin.url]


def test_a_maintenance_page_is_never_staged(tmp_path: Path) -> None:
    """HTML served with HTTP 200 in place of a pinned file fails its checksum."""
    origin = Origin({ZIP_URL: MAINTENANCE})
    zip_pin, _lsad = _pins()
    with origin.cache(tmp_path / "cache") as cache, pytest.raises(SourceChangedError):
        seed([(zip_pin, cache)], {}, tmp_path / "up", print)
    assert not (tmp_path / "up" / zip_pin.asset).exists()


def test_a_stale_cached_lsad_page_is_read_again(tmp_path: Path) -> None:
    origin = Origin({LSAD_URL: LSAD_PAGE.encode()})
    _zip, lsad_pin = _pins()
    old = LSAD_PAGE.replace(
        "</table>", "<tr><td>ZZ</td><td>gone (suffix)</td><td>x</td></tr></table>", 1
    )
    with origin.cache(tmp_path / "cache") as cache:
        path = cache.fetch(LSAD_URL).path
        path.write_text(old, encoding="utf-8")
        # The sidecar agrees with the old bytes, so the cache serves them.
        sidecar = path.with_name(path.name + ".provenance.json")
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        record["sha256"] = _sha(path.read_bytes())
        sidecar.write_text(json.dumps(record), encoding="utf-8")
        assert cache.fetch(LSAD_URL).from_cache
        seed([(lsad_pin, cache)], {}, tmp_path / "up", print)
    assert _sha((tmp_path / "up" / lsad_pin.asset).read_bytes()) == lsad_pin.sha256


def test_a_changed_lsad_table_stops_the_seed(tmp_path: Path) -> None:
    changed = LSAD_PAGE.replace(" (suffix)", " (prefix)", 1)
    origin = Origin({LSAD_URL: changed.encode()})
    _zip, lsad_pin = _pins()
    with (
        origin.cache(tmp_path / "cache") as cache,
        pytest.raises(SourceChangedError, match="code table"),
    ):
        seed([(lsad_pin, cache)], {}, tmp_path / "up", print)


def test_release_notes_list_every_pin() -> None:
    pins = load_pin_set()
    notes = release_notes(pin_set_tag(pins), pins)
    for pin in pins:
        assert f"| {pin.asset} | {pin.sha256}" in notes
    assert "(code table)" in notes


def test_cli_tag_and_seed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["mirror", "tag"]) == 0
    assert capsys.readouterr().out.strip() == pin_set_tag(load_pin_set())
    pins = load_pin_set()
    (tmp_path / "have.txt").write_text(
        "".join(f"{p.asset}\tsha256:{p.sha256}\n" for p in pins), encoding="utf-8"
    )
    assert read_have(tmp_path / "have.txt") == _held(*pins)
    (tmp_path / "bare.txt").write_text("a.zip\nb.zip\t\n\n", encoding="utf-8")
    assert read_have(tmp_path / "bare.txt") == {"a.zip": None, "b.zip": None}
    origin = Origin({})
    monkeypatch.setattr(
        mirror_cli, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(origin))
    )
    argv = ["mirror", "seed", "--dest", str(tmp_path / "up"), "--notes", str(tmp_path / "n.md")]
    cache_args = [
        "--nces-cache-dir",
        str(tmp_path / "n"),
        "--places-cache-dir",
        str(tmp_path / "p"),
    ]
    assert main([*argv, *cache_args, "--have", str(tmp_path / "have.txt")]) == 0
    assert origin.requests == []
    assert (tmp_path / "n.md").read_text(encoding="utf-8").startswith("Data mirror data-mirror-")
    # With nothing held, the first origin that is down fails the seed loudly.
    assert main([*argv, *cache_args]) == 1
    assert "snowlight mirror seed:" in capsys.readouterr().err


def test_cli_seed_copies_from_the_earlier_releases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pins = load_pin_set()
    tag = pin_set_tag(pins)
    earlier = "data-mirror-000000000001"
    origin = Origin({}, {earlier: {p.asset: b"held" for p in pins}})
    monkeypatch.setattr(mirror_cli, "make_client", origin.client)
    (tmp_path / "earlier.txt").write_text(f"{tag}\n{earlier}\n", encoding="utf-8")
    argv = [
        "mirror",
        "seed",
        "--dest",
        str(tmp_path / "up"),
        "--notes",
        str(tmp_path / "n.md"),
        "--nces-cache-dir",
        str(tmp_path / "n"),
        "--places-cache-dir",
        str(tmp_path / "p"),
        "--mirror",
        ROOT,
        "--earlier",
        str(tmp_path / "earlier.txt"),
    ]
    # The earlier release's assets are not the pinned files: refused, then the origins (down).
    assert main(argv) == 1
    err = capsys.readouterr().err
    assert f"not copied from {earlier}" in err
    asked = {url.removeprefix(ROOT + "/").split("/")[0] for url in origin.requests}
    assert tag not in asked

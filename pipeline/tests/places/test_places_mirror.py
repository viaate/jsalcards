"""The places build reading the data mirror: pinned releases, same bytes out, no origin."""

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from snowlight.cli import main
from snowlight.places import cli as places_cli
from snowlight.places.build import Pins, build_places
from snowlight.places.download import DownloadError, SourceCache
from snowlight.places.pins import PlacesPins, load_places_pins
from snowlight.sources.census.lsad import LSAD_URL
from snowlight.sources.mirror import Form, Mirror, lsad_table_page

if TYPE_CHECKING:
    from conftest import FakeServer

ROOT = "https://github.com/viaate/jsalcards/releases/download"


def _pins(server: "FakeServer") -> PlacesPins:
    files: dict[str, dict[str, str]] = {}
    for url in PlacesPins.model_construct(
        gazetteer_year=2026, grf_year=2025, popest_series="2020-2025", files={}
    ).urls():
        data = server.files[url]
        if url == LSAD_URL:
            canonical = lsad_table_page(data.decode())
            files[url] = {"sha256": hashlib.sha256(canonical).hexdigest(), "form": "lsad-table"}
        else:
            files[url] = {"sha256": hashlib.sha256(data).hexdigest()}
    return PlacesPins.model_validate(
        {"gazetteer_year": 2026, "grf_year": 2025, "popest_series": "2020-2025", "files": files}
    )


class MirrorServer:
    """The mirror release of the fixture pins; it records every request."""

    def __init__(self, mirror: Mirror, origin: "FakeServer") -> None:
        self.mirror = mirror
        self.assets: dict[str, bytes] = {}
        for pin in mirror.pins:
            data = origin.files[pin.url]
            if pin.form is Form.LSAD_TABLE:
                data = lsad_table_page(data.decode())
            self.assets[pin.asset] = data
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        name = url.removeprefix(self.mirror.base_url)
        if url.startswith(self.mirror.base_url) and name in self.assets:
            return httpx.Response(200, content=self.assets[name])
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def pinned(server: "FakeServer") -> PlacesPins:
    return _pins(server)


@pytest.fixture
def mirror(pinned: PlacesPins) -> Mirror:
    return Mirror(ROOT, tuple(pinned.pins()))


def _search(root: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted((root / "search").iterdir())}


def _build(cache: SourceCache, root: Path, pins: Pins | None) -> dict[str, object]:
    return build_places(cache, root / "search", root / "places.json", pins).manifest


def test_the_shipped_pins_name_every_file_of_their_releases() -> None:
    pins = load_places_pins()
    assert len(pins.pins()) == 7
    (lsad,) = [pin for pin in pins.pins() if pin.form is Form.LSAD_TABLE]
    assert lsad.url == LSAD_URL


def test_pins_must_name_exactly_the_build_files(pinned: PlacesPins) -> None:
    raw = pinned.model_dump(mode="json")
    extra = {
        **raw,
        "files": {**raw["files"], "https://www2.census.gov/x.zip": {"sha256": "0" * 64}},
    }
    with pytest.raises(ValueError, match="extra"):
        PlacesPins.model_validate(extra)
    files = dict(raw["files"])
    files.pop(LSAD_URL)
    with pytest.raises(ValueError, match="missing"):
        PlacesPins.model_validate({**raw, "files": files})
    plain = {**raw["files"], LSAD_URL: {"sha256": "0" * 64}}
    with pytest.raises(ValueError, match="lsad-table"):
        PlacesPins.model_validate({**raw, "files": plain})


def test_a_mirror_build_is_byte_identical_to_an_origin_build(
    server: "FakeServer", pinned: PlacesPins, mirror: Mirror, tmp_path: Path
) -> None:
    with SourceCache(tmp_path / "origin-cache", server.client()) as cache:
        _build(cache, tmp_path / "origin", None)
    from_mirror = MirrorServer(mirror, server)
    with SourceCache(tmp_path / "mirror-cache", from_mirror.client(), mirror=mirror) as cache:
        manifest = _build(cache, tmp_path / "mirror", Pins(2026, 2025, pinned.series))
    assert _search(tmp_path / "mirror") == _search(tmp_path / "origin")
    assert sorted(from_mirror.requests) == sorted(mirror.url_for(pin) for pin in mirror.pins)
    assert manifest["pages_consulted"] == []
    sources = manifest["sources"]
    assert isinstance(sources, list)
    assert all(entry["mirror"].startswith(mirror.base_url) for entry in sources)


def test_a_warm_cache_needs_no_mirror(
    server: "FakeServer", pinned: PlacesPins, mirror: Mirror, tmp_path: Path
) -> None:
    """Files cached from the origins serve a deploy, the LSAD page by its code table."""
    with SourceCache(tmp_path / "cache", server.client()) as cache:
        _build(cache, tmp_path / "origin", None)
    from_mirror = MirrorServer(mirror, server)
    with SourceCache(tmp_path / "cache", from_mirror.client(), mirror=mirror) as cache:
        _build(cache, tmp_path / "mirror", Pins(2026, 2025, pinned.series))
    assert from_mirror.requests == []
    assert _search(tmp_path / "mirror") == _search(tmp_path / "origin")


def test_a_cached_file_that_differs_from_its_pin_is_read_again(
    server: "FakeServer", mirror: Mirror, tmp_path: Path
) -> None:
    pin = next(p for p in mirror.pins if p.form is Form.FILE)
    with SourceCache(tmp_path, server.client()) as cache:
        cache.fetch(pin.url).path.write_bytes(b"changed")
    from_mirror = MirrorServer(mirror, server)
    with SourceCache(tmp_path, from_mirror.client(), mirror=mirror) as cache:
        fetched = cache.fetch(pin.url)
    assert fetched.sha256 == pin.sha256
    assert from_mirror.requests == [mirror.url_for(pin)]


def _forge_cache_entry(path: Path, data: bytes) -> None:
    """Replace a cached file and keep its sidecar consistent, as an older release would be."""
    sidecar = path.with_name(path.name + ".provenance.json")
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    path.write_bytes(data)
    record.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
    sidecar.write_text(json.dumps(record), encoding="utf-8")


def test_a_consistent_cache_entry_that_is_not_the_pin_is_never_served(
    server: "FakeServer", mirror: Mirror, tmp_path: Path
) -> None:
    """A cached file whose sidecar is valid but whose bytes are another release (a file
    revised in place upstream) is read again from the mirror, or fails when it lacks it."""
    for pin in mirror.pins:
        with SourceCache(tmp_path, server.client()) as cache:
            _forge_cache_entry(cache.fetch(pin.url).path, b"an older release of the file")
        lacking = MirrorServer(mirror, server)
        del lacking.assets[pin.asset]
        with (
            SourceCache(tmp_path, lacking.client(), mirror=mirror) as cache,
            pytest.raises(DownloadError, match="does not hold"),
        ):
            cache.fetch(pin.url)
        from_mirror = MirrorServer(mirror, server)
        with SourceCache(tmp_path, from_mirror.client(), mirror=mirror) as cache:
            fetched = cache.fetch(pin.url)
        assert pin.matches(fetched.path)
        assert from_mirror.requests == [mirror.url_for(pin)]


def test_the_mirror_reads_no_listing_and_no_unpinned_file(
    server: "FakeServer", mirror: Mirror, tmp_path: Path
) -> None:
    with SourceCache(tmp_path, MirrorServer(mirror, server).client(), mirror=mirror) as cache:
        with pytest.raises(DownloadError, match="listing"):
            cache.get_text("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/")
        with pytest.raises(DownloadError, match="not pinned"):
            cache.fetch("https://www2.census.gov/geo/other.zip")
    with pytest.raises(ValueError, match="revalidate"):
        SourceCache(tmp_path, server.client(), revalidate=True, mirror=mirror)


def test_cli_reads_the_pins_and_the_mirror_from_the_environment(  # noqa: PLR0913, PLR0917
    monkeypatch: pytest.MonkeyPatch,
    server: "FakeServer",
    pinned: PlacesPins,
    mirror: Mirror,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from_mirror = MirrorServer(mirror, server)
    monkeypatch.setattr(places_cli, "make_client", from_mirror.client)
    monkeypatch.setattr(places_cli, "pipeline_root", lambda: tmp_path)
    monkeypatch.setattr(places_cli, "load_places_pins", lambda: pinned)
    monkeypatch.setattr(places_cli, "load_mirror", lambda root: Mirror(root, mirror.pins))
    monkeypatch.setenv("SNOWLIGHT_MIRROR", ROOT)
    assert main(["places", "build"]) == 0
    assert f"the data mirror {mirror.base_url}" in capsys.readouterr().err
    assert len(from_mirror.requests) == len(mirror.pins)
    # A release flag that differs from its pin, --revalidate, or a bad root: exit 2.
    for argv in (["--grf-year", "2024"], ["--revalidate"], ["--mirror", "http://x.test/"]):
        assert main(["places", "build", *argv]) == 2, argv
    monkeypatch.setenv("SNOWLIGHT_MIRROR", "")
    monkeypatch.setattr(places_cli, "make_client", server.client)
    assert main(["places", "build", "--popest-series", "2020-2025"]) == 0


def test_cli_pinned_reads_the_pinned_releases_from_the_origins(
    monkeypatch: pytest.MonkeyPatch, server: "FakeServer", pinned: PlacesPins, tmp_path: Path
) -> None:
    """--pinned, the data mirror's proof of an origin build: no discovery, every file checked."""
    monkeypatch.setattr(places_cli, "make_client", server.client)
    monkeypatch.setattr(places_cli, "pipeline_root", lambda: tmp_path)
    monkeypatch.setattr(places_cli, "load_places_pins", lambda: pinned)
    monkeypatch.delenv("SNOWLIGHT_MIRROR", raising=False)
    assert main(["places", "build", "--pinned"]) == 0
    listing = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    assert server.hits[listing] == 0
    grf = "https://nces.ed.gov/programs/edge/data/GRF25.zip"
    server.files[grf] = server.files[grf] + b"changed"
    (tmp_path / ".cache").rename(tmp_path / "old-cache")
    assert main(["places", "build", "--pinned"]) == 1


def test_cli_with_a_required_mirror_and_none_set_reads_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """SNOWLIGHT_REQUIRE_MIRROR=1 (the Preview): no mirror root is exit 2, never an origin read."""

    def no_network() -> httpx.Client:
        raise AssertionError("the build must not open a client")

    monkeypatch.setattr(places_cli, "make_client", no_network)
    monkeypatch.setenv("SNOWLIGHT_REQUIRE_MIRROR", "1")
    monkeypatch.delenv("SNOWLIGHT_MIRROR", raising=False)
    for argv in ([], ["--pinned"], ["--mirror", ""], ["--mirror", "  "]):
        assert main(["places", "build", *argv]) == 2, argv
        assert "SNOWLIGHT_REQUIRE_MIRROR=1 but no data mirror is set" in capsys.readouterr().err
    monkeypatch.setenv("SNOWLIGHT_MIRROR", "")
    assert main(["places", "build"]) == 2

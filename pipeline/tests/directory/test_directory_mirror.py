"""The directory build reading the data mirror: same bytes out, nothing from NCES."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from snowlight.cli import main
from snowlight.directory.build import BuildPaths, BuildResult, build
from snowlight.directory.cli import USAGE
from snowlight.directory.config import DirectoryConfig
from snowlight.mirror.pins import directory_pins
from snowlight.sources.mirror import Mirror, Pin
from snowlight.sources.nces.fetch import DownloadError, FileCache, SourceMissingError

if TYPE_CHECKING:
    from directory.conftest import FixtureServer

ROOT = "https://github.com/viaate/jsalcards/releases/download"
PRIVATE_2425 = "https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PRIVATESCH_2425.zip"
pytestmark = pytest.mark.usefixtures("tippecanoe_or_stand_in")


class MirrorServer:
    """Serves each pinned fixture at its asset URL, and nothing else."""

    def __init__(self, mirror: Mirror, assets: dict[str, bytes]) -> None:
        self.mirror = mirror
        self.assets = assets
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        name = url.removeprefix(self.mirror.base_url)
        if url.startswith(self.mirror.base_url) and name in self.assets:
            data = self.assets[name]
            return httpx.Response(200, content=data, headers={"Content-Length": str(len(data))})
        return httpx.Response(404, text="Not Found")

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def _mirror(config: DirectoryConfig, wait: float = 0.0) -> Mirror:
    return Mirror(ROOT, tuple(directory_pins(config)), wait_seconds=wait)


def _assets(mirror: Mirror) -> dict[str, bytes]:
    fixtures = Path(__file__).resolve().parent / "fixtures"
    return {pin.asset: (fixtures / pin.asset).read_bytes() for pin in mirror.pins}


def _build(
    config: DirectoryConfig,
    root: Path,
    client: "FixtureServer | MirrorServer",
    mirror: Mirror | None,
) -> BuildResult:
    return build(
        config,
        BuildPaths(
            cache_dir=root / "cache",
            out_dir=root / "site-data",
            internal_dir=root / "internal",
            work_dir=root / "work",
        ),
        client_factory=client.client,
        log=lambda _message: None,
        now=lambda: datetime(2026, 9, 24, 23, 0, tzinfo=UTC),
        mirror=mirror,
    )


def _published(site: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(site)): path.read_bytes()
        for path in sorted(site.rglob("*"))
        if path.is_file() and not path.name.endswith(".internal.json")
    }


def test_a_mirror_build_is_byte_identical_to_an_origin_build(
    fixture_config: DirectoryConfig, tmp_path: Path, server: "FixtureServer"
) -> None:
    origin = _build(fixture_config, tmp_path / "origin", server, None)
    mirror = _mirror(fixture_config)
    from_mirror = MirrorServer(mirror, _assets(mirror))
    mirrored = _build(fixture_config, tmp_path / "mirror", from_mirror, mirror)
    published = _published(mirrored.site_dir)
    assert published == _published(origin.site_dir)
    assert {"edition.json", "schools.pmtiles"} <= set(published)
    # Every file came from the mirror release; nothing asked nces.ed.gov, not even
    # for the newer release that is not pinned.
    assert sorted(from_mirror.requests) == sorted(mirror.url_for(pin) for pin in mirror.pins)
    assert all(url.startswith(mirror.base_url) for url in from_mirror.requests)
    # The second build reads the cache alone.
    from_mirror.requests.clear()
    _build(fixture_config, tmp_path / "mirror", from_mirror, mirror)
    assert from_mirror.requests == []


def test_an_unpinned_release_is_skipped_as_not_published(
    fixture_config: DirectoryConfig, tmp_path: Path
) -> None:
    mirror = _mirror(fixture_config)
    with (
        FileCache(tmp_path, MirrorServer(mirror, {}).client(), mirror=mirror) as cache,
        pytest.raises(SourceMissingError, match="not pinned"),
    ):
        cache.fetch(PRIVATE_2425, None)


def test_a_pinned_file_the_mirror_lacks_never_falls_back(
    fixture_config: DirectoryConfig, tmp_path: Path
) -> None:
    """The mirror being behind is an error, not "not published": no older release is used."""
    mirror = _mirror(fixture_config, wait=60.0)
    pin = mirror.pins[0]
    assets = _assets(mirror)
    del assets[pin.asset]
    server = MirrorServer(mirror, assets)
    pauses: list[float] = []
    lines: list[str] = []
    with (
        FileCache(
            tmp_path, server.client(), mirror=mirror, sleep=pauses.append, log=lines.append
        ) as cache,
        pytest.raises(DownloadError, match="does not hold") as raised,
    ):
        cache.fetch(pin.url, pin.sha256)
    assert not isinstance(raised.value, SourceMissingError)
    # It waited for the seed (60 s in 30 s polls), then gave up.
    assert pauses == [30.0, 30.0]
    assert len(lines) == 2
    assert "waiting" in lines[0]
    assert server.requests == [mirror.url_for(pin)] * 3


def test_a_mirror_file_that_differs_from_its_pin_is_refused(
    fixture_config: DirectoryConfig, tmp_path: Path
) -> None:
    mirror = _mirror(fixture_config)
    pin = mirror.pins[0]
    server = MirrorServer(mirror, {pin.asset: b"PK\x03\x04 not the pinned file"})
    with FileCache(tmp_path, server.client(), mirror=mirror) as cache:
        with pytest.raises(DownloadError, match="does not match the pin"):
            cache.fetch(pin.url, pin.sha256)
        assert cache.cached(pin.url, pin.sha256) is None
    assert not any(tmp_path.rglob("*.zip"))


def test_a_consistent_cache_entry_that_is_not_the_pin_is_never_served(
    fixture_config: DirectoryConfig, tmp_path: Path
) -> None:
    """A cached file with a valid sidecar but other bytes is read again from the mirror."""
    mirror = _mirror(fixture_config)
    pin = mirror.pins[0]
    with FileCache(tmp_path, MirrorServer(mirror, _assets(mirror)).client(), mirror=mirror) as c:
        path = c.fetch(pin.url, pin.sha256).path
    sidecar = path.with_name(path.name + ".provenance.json")
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    older = b"PK\x03\x04 an older release of the file"
    path.write_bytes(older)
    record.update(sha256=hashlib.sha256(older).hexdigest(), bytes=len(older))
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    lacking = _assets(mirror)
    del lacking[pin.asset]
    with (
        FileCache(tmp_path, MirrorServer(mirror, lacking).client(), mirror=mirror) as cache,
        pytest.raises(DownloadError, match="does not hold"),
    ):
        cache.fetch(pin.url, pin.sha256)
    server = MirrorServer(mirror, _assets(mirror))
    with FileCache(tmp_path, server.client(), mirror=mirror) as cache:
        assert cache.fetch(pin.url, pin.sha256).sha256 == pin.sha256
    assert server.requests == [mirror.url_for(pin)]


def test_cli_with_a_required_mirror_and_none_set_reads_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """SNOWLIGHT_REQUIRE_MIRROR=1 (the Preview): no mirror root is a usage error, never NCES."""
    monkeypatch.setenv("SNOWLIGHT_REQUIRE_MIRROR", "1")
    monkeypatch.delenv("SNOWLIGHT_MIRROR", raising=False)
    for argv in ([], ["--mirror", ""]):
        assert main(["directory", "build", *argv]) == USAGE
        assert "SNOWLIGHT_REQUIRE_MIRROR=1 but no data mirror is set" in capsys.readouterr().err


def test_a_config_pin_the_mirror_does_not_hold_is_refused(
    fixture_config: DirectoryConfig, tmp_path: Path
) -> None:
    mirror = _mirror(fixture_config)
    pin = mirror.pins[0]
    with (
        FileCache(tmp_path, MirrorServer(mirror, {}).client(), mirror=mirror) as cache,
        pytest.raises(DownloadError, match="does not pin"),
    ):
        cache.fetch(pin.url, "0" * 64)


def test_server_errors_are_retried_then_reported(
    fixture_config: DirectoryConfig, tmp_path: Path
) -> None:
    mirror = _mirror(fixture_config)
    pin = mirror.pins[0]

    def busy(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(busy))
    with (
        FileCache(tmp_path, client, mirror=mirror, sleep=lambda _s: None) as cache,
        pytest.raises(DownloadError, match="giving up"),
    ):
        cache.fetch(pin.url, pin.sha256)


def test_the_mirror_root_must_be_https() -> None:
    with pytest.raises(ValueError, match="https"):
        Mirror("http://example.test/releases/download", ())
    with pytest.raises(ValueError, match="poll"):
        Mirror(ROOT, (), poll_seconds=0)
    with pytest.raises(ValueError, match="release tag"):
        Mirror(ROOT, (), release="v1/../x")
    earlier = Mirror(ROOT, (Pin("https://h.test/a.zip", "0" * 64),), release="data-mirror-0a")
    assert earlier.base_url == ROOT + "/data-mirror-0a/"
    assert Mirror(ROOT + "/", (Pin("https://h.test/a.zip", "0" * 64),)).base_url.startswith(
        ROOT + "/data-mirror-"
    )


def test_cli_refuses_a_mirror_root_that_is_not_https(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SNOWLIGHT_MIRROR", "http://example.test/releases/download")
    assert main(["directory", "build"]) == USAGE
    assert "the data mirror" in capsys.readouterr().err

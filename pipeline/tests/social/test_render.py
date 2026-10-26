"""The fresh picture's render in the pre-installed headless Chromium, against a SYNTHETIC
fixture page that stands in for the site: the same lock check, the same files read from the
same paths, and a stand-in ``window.snowlightMap`` whose glow layer counts the schools the
closings file lights today (snowlight.social.render). Skipped where no Chromium is installed
(the workflow installs one; this machine and CI need none)."""

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from snowlight.directory.points import encode
from snowlight.social.picture import Taken
from snowlight.social.render import (
    RenderError,
    directory_of,
    live_root,
    lock_value,
    render,
)

LOCK = "c3ludGhldGlj"  # SYNTHETIC: this fixture's own lock value
SCHOOLS = ["360000100001", "360000100002", "360000100003", "270000100001"]
DISTRICTS = ["3600001", "2700001"]
STAMP = {"generated_on": "2026-10-14", "schools": 4, "districts": 2}
POINTS = encode(
    [-78_880_000, -78_800_000, -78_700_000, -93_260_000],
    [42_890_000, 42_950_000, 42_800_000, 44_980_000],
    [0, 0, 0, 1],
    [0, 0, 0, 0],
    2,
)
META = json.dumps(
    {"generated_on": "2026-10-14", "ids": SCHOOLS, "districts": {"ids": DISTRICTS}}
).encode()

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>fixture</title>
<style>body { margin: 0; background: #05070c; color: #dde; font: 16px sans-serif; }
#lock:not([hidden]) { position: fixed; inset: 0; background: #223; }</style></head><body>
<div id="lock" hidden>waitlist</div><div id="panel"></div>
<script>
if (localStorage.getItem('sl-lock') === '__LOCK__') { /* unlocked */ }
else { document.getElementById('lock').hidden = false; }
const NOW = Date.parse('__NOW__');
const day = (offset) => new Date(NOW + offset * 3600000).toISOString().slice(0, 10);
const today = day(-4) === day(-8) ? day(-4) : null;
const stats = { dust: 0, frames: 0, glowCount: __GLOW_OFFSET__ };
window.snowlightMap = {
  ready: false,
  loaded() { return this.ready; }, areTilesLoaded() { return true; }, isMoving() { return false; },
  getLayer(id) { return id === 'snowlight-glow' ? { implementation: { stats } } : undefined; },
};
(async () => {
  await fetch('/data/schools/meta.0a1b2c.json');
  await fetch('/data/schools/points.0a1b2c.bin');
  stats.dust = 4;
  const closings = await fetch('/live-root/v1/live/closings.json');
  if (closings.ok) {
    const file = await closings.json();
    for (const group of file.days) if (group.day === today) stats.glowCount += group.gaps.length;
  }
  const district = new URLSearchParams(location.search).get('district');
  if (district !== null) {
    const file = await (await fetch('/live-root/v1/predictions/latest.json')).json();
    const column = file.days.indexOf(today ?? day(-4));
    const row = file.districts[__DISTRICTS__.indexOf(district)];
    const chance = row.days[column].p_no_school;
    document.getElementById('panel').textContent = Math.round(chance * 100) + '%';
  }
  stats.frames = 1;
  window.snowlightMap.ready = true;
})();
</script></body></html>"""


@dataclass
class Site:
    now: datetime
    closings: dict[str, Any] | None = None
    predictions: dict[str, Any] | None = None
    lock: bool = True
    glow_offset: int = 0
    requests: list[str] = field(default_factory=list)


def _handler(site: Site) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("content-type", kind)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            site.requests.append(path)
            if path == "/":
                page = (
                    PAGE.replace("__LOCK__", LOCK if site.lock else "")
                    .replace("__NOW__", site.now.isoformat().replace("+00:00", "Z"))
                    .replace("__GLOW_OFFSET__", str(site.glow_offset))
                    .replace("__DISTRICTS__", json.dumps(DISTRICTS))
                )
                if not site.lock:
                    page = page.replace("localStorage.getItem('sl-lock') === ''", "true")
                self._send(200, page.encode(), "text/html")
            elif path == "/data/schools/meta.0a1b2c.json":
                self._send(200, META, "application/json")
            elif path == "/data/schools/points.0a1b2c.bin":
                self._send(200, POINTS, "application/octet-stream")
            elif path == "/live-root/v1/live/closings.json" and site.closings is not None:
                self._send(200, json.dumps(site.closings).encode(), "application/json")
            elif path == "/live-root/v1/predictions/latest.json" and site.predictions is not None:
                self._send(200, json.dumps(site.predictions).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

    return Handler


@pytest.fixture(scope="module")
def chromium() -> bool:
    try:
        with sync_playwright() as playwright:
            playwright.chromium.launch().close()
    except PlaywrightError:
        pytest.skip("no Chromium is installed here")
    return True


@pytest.fixture
def served(chromium: bool) -> Iterator[tuple[Site, str]]:
    assert chromium
    site = Site(now=datetime(2026, 12, 10, 12, 10, tzinfo=UTC))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(site))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield site, f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def _predictions(chances: list[float]) -> dict[str, Any]:
    return {
        "directory": STAMP,
        "days": ["2026-12-09", "2026-12-10"],
        "districts": [
            {"district": i, "days": [{"state": "no_threat"}, {"p_no_school": c}]}
            for i, c in enumerate(chances)
        ],
    }


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_practice_mode_takes_the_national_map(served: tuple[Site, str], tmp_path: Path) -> None:
    site, base = served
    site.predictions = _predictions([0.01, 0.01])
    said: list[str] = []
    taken = render(tmp_path, site=base, now=lambda: site.now, say=said.append)
    assert taken is not None
    assert taken.kind == "national"
    assert "Not in the picture: Snowlight's chance of no school on December 10 is at most 1%" in (
        taken.shows
    )
    assert _png_size(tmp_path / "picture.png") == (1600, 900)
    note = Taken.model_validate_json((tmp_path / "picture.json").read_text())
    assert note == taken
    assert "/live-root/v1/predictions/latest.json" in site.requests
    assert not any(LOCK in line for line in said), "the lock value is never said"


def test_lit_schools_zoom_in_and_match_the_glow(served: tuple[Site, str], tmp_path: Path) -> None:
    site, base = served
    site.closings = {
        "generated_at": "2026-12-10T12:05:00Z",
        "directory": STAMP,
        "days": [{"day": "2026-12-10", "gaps": [0, 0, 1], "statuses": [0, 1, 0]}],
    }
    taken = render(tmp_path, site=base, now=lambda: site.now, say=lambda _line: None)
    assert taken is not None
    assert taken.kind == "closings"
    assert taken.lit == 3
    assert taken.query.startswith("?at=42.")
    assert "Across the country the map shows 3 schools" in taken.shows


def test_a_district_panel_must_show_its_chance(served: tuple[Site, str], tmp_path: Path) -> None:
    site, base = served
    site.predictions = _predictions([0.02, 0.41])
    taken = render(tmp_path, site=base, now=lambda: site.now, say=lambda _line: None)
    assert taken is not None
    assert taken.kind == "district"
    assert taken.query == "?district=2700001"
    assert "41%" in taken.shows


@pytest.mark.parametrize(
    ("lock", "glow_offset", "problem"),
    [(True, 1, "the map lit 1 schools; the description counts 0"), (False, 0, "no lock check")],
)
def test_a_picture_that_does_not_match_is_dropped_after_one_retry(
    served: tuple[Site, str], tmp_path: Path, lock: bool, glow_offset: int, problem: str
) -> None:
    site, base = served
    site.lock, site.glow_offset = lock, glow_offset
    said: list[str] = []
    assert render(tmp_path, site=base, now=lambda: site.now, say=said.append) is None
    tries = [line for line in said if "picture try" in line]
    assert len(tries) == 2
    assert problem in tries[0]
    assert not (tmp_path / "picture.png").exists()
    assert not (tmp_path / "picture.json").exists()


def test_the_pure_parts() -> None:
    assert lock_value("if (localStorage.getItem('sl-lock') === 'QUJD') {") == "QUJD"
    with pytest.raises(RenderError):
        lock_value("<html></html>")
    assert live_root("https://h.example/v1/live/closings.json") == "https://h.example/v1/"
    with pytest.raises(RenderError):
        live_root("https://h.example/v1/closings.json")
    directory = directory_of(META, POINTS)
    assert directory.stamp() == STAMP
    with pytest.raises(RenderError, match="disagree"):
        directory_of(
            json.dumps({"generated_on": "x", "ids": [], "districts": {"ids": []}}).encode(), POINTS
        )
    with pytest.raises(RenderError, match="malformed"):
        directory_of(b"[]", POINTS)
    with pytest.raises(RenderError, match="malformed"):
        directory_of(META, b"nope")

"""The fresh picture's render in the pre-installed headless Chromium, against a SYNTHETIC
fixture page that stands in for the site: the same lock check, the same files read from the
same paths, and a stand-in ``window.snowlightMap`` whose glow layer counts the schools the
closings file lights today (snowlight.social.render). Skipped where no Chromium is installed
(the workflow installs one; this machine and CI need none)."""

import argparse
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
from snowlight.social import cli
from snowlight.social.cards import Card
from snowlight.social.picture import Taken
from snowlight.social.render import (
    GL_ARGS,
    HOSTS,
    RenderError,
    View,
    allowed,
    directory_of,
    guard,
    launch,
    live_root,
    lock_value,
    render,
)
from snowlight.social.rules import (
    Facts,
    chances_shown,
    closings_shown,
    mentions_chance,
    mentions_closings,
    parse_facts,
)

LOCK = "c3ludGhldGlj"  # SYNTHETIC: this fixture's own lock value


def switches(chances: str, closings: str) -> Facts:
    """A SYNTHETIC facts file with the two switches as given and the A card's model line."""
    return parse_facts(
        f"- [{chances}] chances: SYNTHETIC chances. | terms: chance\n"
        f"- [{closings}] closings: SYNTHETIC closings on the map. | terms: closings\n"
        "- [LIVE] model: A prediction model trained on real closing records, not a guess.\n"
    )


SHOWN = switches("LIVE", "LIVE")
NO_CHANCES = switches("TESTING", "LIVE")
HELD_BACK = switches("TESTING", "COMING")
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
const stats = { dust: 0, frames: 0, glowCount: __GLOW_OFFSET__, dustInView: 0 };
const at = new URLSearchParams(location.search).get('at');
const zoom = (at ? Number(at.split(',')[2]) : 4.08) + __ZOOM_OFFSET__;
window.snowlightMap = {
  ready: false,
  loaded() { return this.ready; }, areTilesLoaded() { return true; }, isMoving() { return false; },
  getZoom() { return zoom; },
  getLayer(id) { return id === 'snowlight-glow' ? { implementation: { stats } } : undefined; },
};
(async () => {
  await fetch('/data/schools/meta.0a1b2c.json');
  await fetch('/data/schools/points.0a1b2c.bin');
  // As the site: school dust only between zoom 5 and 10.
  if (zoom > 5 && zoom < 10) { stats.dust = 4; stats.dustInView = 3; }
  const closings = await fetch('/live-root/v1/live/closings.json');
  if (closings.ok) {
    const file = await closings.json();
    for (const group of file.days) if (group.day === today) stats.glowCount += group.gaps.length;
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
    zoom_offset: float = 0.0
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
                    .replace("__ZOOM_OFFSET__", str(site.zoom_offset))
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
        "generated_at": "2026-12-10T12:00:00Z",
        "directory": STAMP,
        "days": ["2026-12-10", "2026-12-11"],
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
    taken = render(tmp_path, facts=SHOWN, site=base, now=lambda: site.now, say=said.append)
    assert taken is not None
    assert taken.kind == "national"
    assert (
        "Not in the picture: Snowlight's chance of no school on Friday, December 11 is at most 1%"
    ) in taken.shows
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
    taken = render(tmp_path, facts=SHOWN, site=base, now=lambda: site.now, say=lambda _line: None)
    assert taken is not None
    assert taken.kind == "closings"
    assert taken.lit == 3
    assert taken.query.startswith("?at=42.")
    assert "Across the country the map shows 3 schools" in taken.shows


def test_a_high_chance_frames_its_district(served: tuple[Site, str], tmp_path: Path) -> None:
    site, base = served
    site.predictions = _predictions([0.02, 0.41])
    taken = render(tmp_path, facts=SHOWN, site=base, now=lambda: site.now, say=lambda _line: None)
    assert taken is not None
    assert taken.kind == "district"
    assert taken.query.startswith("?at=44.")
    assert "41%" in taken.shows
    assert taken.seen.chance is not None
    assert taken.seen.chance.text == "41%"
    assert taken.seen.focus is not None


def test_a_calm_region_must_draw_its_specks(served: tuple[Site, str], tmp_path: Path) -> None:
    site, base = served
    view = View("?at=42.9,-78.8,6.1", "western New York")
    taken = render(
        tmp_path, facts=SHOWN, site=base, now=lambda: site.now, say=lambda _line: None, view=view
    )
    assert taken is not None
    assert taken.kind == "region"
    assert taken.seen.place == "western New York"
    said: list[str] = []
    far = View("?at=42.9,-78.8,11", "western New York")
    assert (
        render(tmp_path, facts=SHOWN, site=base, now=lambda: site.now, say=said.append, view=far)
        is None
    )
    assert any("drew no school specks" in line for line in said)


@pytest.mark.parametrize(
    "case",
    [
        (True, 1, 0.0, "the map lit 1 schools; the description counts 0"),
        (False, 0, 0.0, "no lock check"),
        (True, 0, 0.5, "the map opened at zoom 7, not the 6.5 asked"),
    ],
)
def test_a_picture_that_does_not_match_is_dropped_after_one_retry(
    served: tuple[Site, str], tmp_path: Path, case: tuple[bool, int, float, str]
) -> None:
    site, base = served
    lock, glow_offset, zoom_offset, problem = case
    site.lock, site.glow_offset, site.zoom_offset = lock, glow_offset, zoom_offset
    if zoom_offset:
        site.closings = {
            "generated_at": "2026-12-10T12:05:00Z",
            "directory": STAMP,
            "days": [{"day": "2026-12-10", "gaps": [0], "statuses": [0]}],
        }
    said: list[str] = []
    assert render(tmp_path, facts=SHOWN, site=base, now=lambda: site.now, say=said.append) is None
    tries = [line for line in said if "picture try" in line]
    assert len(tries) == 2
    assert problem in tries[0]
    assert not any(LOCK in line for line in said), "the lock value is never said"
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


def test_the_render_command_takes_a_view_only_with_its_place(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(
        out="unused", site="", live_dir="", view="?at=40.9,-80.6,6.1", place="", fallback=True
    )
    assert cli._render(args) == 2
    assert "--view and --place go together" in capsys.readouterr().out


def test_while_chances_are_testing_no_picture_or_card_gives_one(
    served: tuple[Site, str], tmp_path: Path
) -> None:
    """Rule F (SYNTHETIC predictions): a 74% district and a 1% nation give the national map,
    and neither the description, the cards' words nor their alt text hold any chance."""
    site, base = served
    site.predictions = _predictions([0.01, 0.74])
    said: list[str] = []
    taken = render(tmp_path, facts=NO_CHANCES, site=base, now=lambda: site.now, say=said.append)
    assert taken is not None
    assert taken.kind == "national"
    assert taken.seen.chance is None
    assert not mentions_chance(taken.shows)
    assert "/live-root/v1/predictions/latest.json" not in site.requests
    for post in ("dev-log", "waitlist"):
        card = Card.model_validate_json((tmp_path / f"{post}.json").read_text())
        assert not mentions_chance(card.alt), card.alt
    assert not any("74" in line or "chance" in line.lower() for line in said), said
    # The same files with chances LIVE give the district's chance picture.
    shown = render(tmp_path, facts=SHOWN, site=base, now=lambda: site.now, say=said.append)
    assert shown is not None
    assert shown.kind == "district"


def test_the_render_command_reads_the_switch_from_the_facts_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import snowlight.social.render as module  # noqa: PLC0415 - the module the command imports

    got: dict[str, object] = {}

    def fake(out: Path, **kwargs: object) -> None:
        got.update(kwargs, out=out)

    monkeypatch.setattr(module, "render", fake)
    repo = Path(__file__).resolve().parents[3]
    args = argparse.Namespace(
        out=str(tmp_path),
        root=str(repo),
        site="",
        live_dir="",
        view="",
        place="",
        fallback=False,
        sandbox=True,
    )
    assert cli._render(args) == 1  # the fake made no picture
    assert got["sandbox"] is True, "the workflow's --sandbox reaches the browser's launch"
    facts = got["facts"]
    assert isinstance(facts, Facts)
    assert not chances_shown(facts), "social/facts.md marks chances TESTING"
    assert not closings_shown(facts), "social/facts.md marks closings COMING"
    assert got["out"] == tmp_path
    # No facts file: no picture at all (never a guess at the switch).
    got.clear()
    args.root = str(tmp_path)
    assert cli._render(args) == 1
    assert got == {}


def test_while_closings_are_not_live_no_picture_or_card_shows_them(
    served: tuple[Site, str], tmp_path: Path
) -> None:
    """The closings switch (SYNTHETIC closings): a file lighting three schools today while the
    facts file marks closings COMING gives the calm national map, the page is served a 404
    for the file (no glow), and neither the description, the cards' words nor their alt text
    say anything of closings."""
    site, base = served
    site.closings = {
        "generated_at": "2026-12-10T12:05:00Z",
        "directory": STAMP,
        "days": [{"day": "2026-12-10", "gaps": [0, 0, 1], "statuses": [0, 1, 0]}],
    }
    said: list[str] = []
    taken = render(tmp_path, facts=HELD_BACK, site=base, now=lambda: site.now, say=said.append)
    assert taken is not None
    assert taken.kind == "national"
    assert taken.lit == 0
    assert not taken.seen.closings_read
    assert not mentions_closings(taken.shows), taken.shows
    assert not mentions_chance(taken.shows)
    for post in ("dev-log", "waitlist"):
        card = Card.model_validate_json((tmp_path / f"{post}.json").read_text())
        assert not mentions_closings(card.alt), card.alt
    # The same files with closings LIVE give the closings view.
    shown = render(tmp_path, facts=SHOWN, site=base, now=lambda: site.now, say=said.append)
    assert shown is not None
    assert shown.kind == "closings"


# -- the browser reaches only the site, its live files and its tiles, in its sandbox ------------


def test_only_the_site_its_live_files_and_its_tiles_may_be_fetched() -> None:
    hosts = HOSTS | {"127.0.0.1"}
    assert allowed("https://snowlightmap.com/data/schools/meta.0a1b.json", hosts)
    assert allowed("https://viaate.github.io/snowlight-live/v1/live/closings.json", hosts)
    assert allowed("https://tiles.openfreemap.org/planet/1/2/3.pbf", hosts)
    assert allowed("http://127.0.0.1:4797/", hosts)
    assert allowed("data:image/png;base64,AAAA", hosts)
    assert allowed("blob:https://snowlightmap.com/1234", hosts)
    for url in (
        "https://evil.example/x.js",
        "https://snowlightmap.com.evil.example/",
        "https://tiles.openfreemap.org.example/",
        "ftp://snowlightmap.com/",
        "file:///etc/passwd",
        "https://snowlight-api.example.workers.dev/session",
    ):
        assert not allowed(url, hosts), url


def test_the_guard_aborts_every_other_host_and_says_it_once(
    served: tuple[Site, str],
) -> None:
    _site, base = served
    said: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            blocked = guard(context, HOSTS | {"127.0.0.1"}, said.append)
            page = context.new_page()
            page.goto(base + "nothing-here", wait_until="load")
            fetched = page.evaluate(
                """async () => {
                  const results = [];
                  for (const url of ['https://outside.invalid/a.js', 'https://outside.invalid/b',
                                     'https://snowlightmap.com.outside.invalid/']) {
                    try { await fetch(url); results.push('fetched'); }
                    catch { results.push('blocked'); }
                  }
                  return results;
                }"""
            )
        finally:
            browser.close()
    assert fetched == ["blocked", "blocked", "blocked"]
    assert blocked == {"outside.invalid", "snowlightmap.com.outside.invalid"}
    assert said == [
        "social: the picture's browser blocked a request to outside.invalid",
        "social: the picture's browser blocked a request to snowlightmap.com.outside.invalid",
    ]


def test_the_guard_closes_every_websocket_and_the_browser_keeps_webrtc_off_udp(
    served: tuple[Site, str],
) -> None:
    _site, base = served
    said: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            blocked = guard(context, HOSTS | {"127.0.0.1"}, said.append)
            page = context.new_page()
            page.goto(base + "nothing-here", wait_until="load")
            opened = page.evaluate(
                """() => new Promise((done) => {
                  const socket = new WebSocket('wss://outside.invalid/socket');
                  socket.onopen = () => socket.send('x');
                  socket.onclose = () => done('closed');
                  setTimeout(() => done('timeout'), 5000);
                })"""
            )
        finally:
            browser.close()
    assert opened == "closed"
    assert "outside.invalid" in blocked
    assert said == ["social: the picture's browser blocked a WebSocket to outside.invalid"]
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in GL_ARGS


class _Chromium:
    """A stand-in browser type whose sandbox cannot start (as for root, or a runner that
    forbids it)."""

    def __init__(self, *, sandbox_starts: bool) -> None:
        self.sandbox_starts = sandbox_starts
        self.launches: list[bool] = []

    def launch(self, **options: Any) -> str:
        self.launches.append(options["chromium_sandbox"])
        if options["chromium_sandbox"] and not self.sandbox_starts:
            raise PlaywrightError("No usable sandbox!")
        return "browser"


@pytest.mark.parametrize("sandbox_starts", [True, False])
def test_the_workflow_s_browser_runs_in_its_sandbox_when_the_runner_allows_it(
    *, sandbox_starts: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    said: list[str] = []
    chromium = _Chromium(sandbox_starts=sandbox_starts)
    assert launch(chromium, sandbox=True, say=said.append) == "browser"  # type: ignore[arg-type, comparison-overlap]
    if sandbox_starts:
        assert chromium.launches == [True]
        assert said == ["social: the picture's browser runs in its sandbox"]
    else:
        assert chromium.launches == [True, False]
        assert said[0].startswith(
            "::warning::social: the picture's browser could not start in its sandbox"
        )
        assert "reaching only snowlightmap.com, tiles.openfreemap.org, viaate.github.io" in said[0]
    local = _Chromium(sandbox_starts=False)
    assert launch(local, sandbox=False, say=said.append) == "browser"  # type: ignore[arg-type, comparison-overlap]
    assert local.launches == [False]

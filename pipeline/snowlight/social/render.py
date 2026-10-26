"""Takes a post's fresh picture of the real site in headless Chromium (``snowlight social
render``, the social-post workflow's Render step, which holds no secret).

One attempt:

1. Read the site's lock value from its own page, and set it in this browser's storage only
   (the way web/e2e/waitlist.spec.ts unlocks it), so the map shows instead of the waitlist.
   The value is never printed or written anywhere.
2. Open the national map, signed out, and keep the bytes of the files it reads: the school
   directory (``schools/meta.*.json``, ``schools/points.*.bin``) and ``live/closings.json``
   from the live root the page names. Read ``predictions/latest.json`` from the same root.
3. :func:`snowlight.social.picture.choose` picks the view and writes what it shows.
4. Open that view with the page served exactly those live files, wait until the map is at
   rest with every tile in, check that it lit as many schools as the description counts (and
   that a district's panel shows the chance it names, and the waitlist is gone), and take a
   1600 x 900 PNG.

A failed attempt gets one more; a second failure exits 1 with no picture, and the post step
then uses the library's newest image with its own day and description (:mod:`.post`). The
result is ``picture.png`` and ``picture.json`` (:class:`Taken`) in the output folder.
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from playwright.sync_api import Browser, BrowserContext, Page, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from snowlight.directory.points import PointsFormatError, decode
from snowlight.social.picture import (
    FILE,
    HEIGHT,
    NOTE,
    SHOWN_ZONE,
    WIDTH,
    Directory,
    Picture,
    PictureError,
    Taken,
    choose,
)

SITE: Final = "https://snowlightmap.com/"
LOCK_KEY: Final = "sl-lock"
LOCK_VALUE: Final = re.compile(r"getItem\(\s*'sl-lock'\s*\)\s*===\s*'([A-Za-z0-9+/=]{1,64})'")
META: Final = re.compile(r"/data/schools/meta\.[0-9a-f]+\.json$")
POINTS: Final = re.compile(r"/data/schools/points\.[0-9a-f]+\.bin$")
CLOSINGS: Final = "live/closings.json"
PREDICTIONS: Final = "predictions/latest.json"
GLOW_LAYER: Final = "snowlight-glow"
ATTEMPTS: Final = 2
TIMEOUT_MS: Final = 120_000
"""How long one wait in an attempt may take (SwiftShader draws the map on the CPU)."""
GL_ARGS: Final = ("--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader")

SETTLED: Final = """() => {
  if (document.querySelector('svg.still') !== null) return false;
  const map = window.snowlightMap;
  if (map === undefined || !map.loaded() || !map.areTilesLoaded() || map.isMoving()) return false;
  const stats = map.getLayer('snowlight-glow')?.implementation?.stats;
  return stats !== undefined && stats.dust > 0 && stats.frames > 0;
}"""
STATE: Final = """() => {
  const stats = window.snowlightMap?.getLayer('snowlight-glow')?.implementation?.stats;
  const lock = document.getElementById('lock');
  return {
    glow: stats === undefined ? -1 : stats.glowCount,
    locked: lock !== null && !lock.hidden,
    text: document.body.innerText,
  };
}"""
TWO_FRAMES: Final = """() => new Promise((done) =>
  requestAnimationFrame(() => requestAnimationFrame(() => done(true))))"""


class RenderError(RuntimeError):
    """An attempt did not give a picture that matches its description (safe for the log)."""


@dataclass(slots=True)
class Kept:
    """A file the page read: where from, its status, headers and bytes."""

    url: str
    status: int
    headers: dict[str, str]
    body: bytes = field(repr=False)


def lock_value(html: str) -> str:
    """The site's unlock value, from its own page (never printed).

    Raises:
        RenderError: the page holds no lock the way index.html writes it.
    """
    found = LOCK_VALUE.search(html)
    if found is None:
        raise RenderError("the site's page holds no lock check where index.html has it")
    return found.group(1)


def live_root(closings_url: str) -> str:
    """The live root the page names, from the closings file's address."""
    if not closings_url.endswith(CLOSINGS):
        raise RenderError("the closings file is not at live/closings.json")
    return closings_url.removesuffix(CLOSINGS)


def directory_of(meta: bytes, points: bytes) -> Directory:
    """The deployed directory from ``meta.json`` and ``points.bin``.

    Raises:
        RenderError: either file is malformed, or they disagree.
    """
    try:
        parsed = json.loads(meta)
        decoded = decode(points)
    except (ValueError, PointsFormatError) as error:
        raise RenderError(f"the school directory is malformed ({type(error).__name__})") from None
    ids = parsed.get("ids") if isinstance(parsed, dict) else None
    districts = parsed.get("districts") if isinstance(parsed, dict) else None
    district_ids = districts.get("ids") if isinstance(districts, dict) else None
    generated_on = parsed.get("generated_on") if isinstance(parsed, dict) else None
    if (
        not isinstance(ids, list)
        or not isinstance(district_ids, list)
        or not isinstance(generated_on, str)
        or not all(isinstance(value, str) for value in ids + district_ids)
    ):
        raise RenderError("the school directory's meta.json is malformed")
    if len(ids) != len(decoded) or len(district_ids) != decoded.district_count:
        raise RenderError("the school directory's meta.json and points.bin disagree")
    return Directory(generated_on, tuple(ids), tuple(district_ids), decoded)


def _json(kept: Kept | None) -> Mapping[str, object] | None:
    """A live file's JSON; ``None`` when the page got none (a 404 in practice mode)."""
    if kept is None or kept.status != 200:  # noqa: PLR2004
        return None
    try:
        value = json.loads(kept.body)
    except ValueError:
        raise RenderError(f"{kept.url.rsplit('/', 1)[-1]} is not JSON") from None
    if not isinstance(value, dict):
        raise RenderError(f"{kept.url.rsplit('/', 1)[-1]} is not a JSON object")
    return value


@dataclass(slots=True)
class Attempt:
    """One attempt's browser context and the files its page read."""

    context: BrowserContext
    site: str
    say: Callable[[str], None]
    kept: dict[str, Kept] = field(default_factory=dict)
    serve: dict[str, Kept] = field(default_factory=dict)
    live: Path | None = None

    def _keep(self, name: str) -> Callable[[Route], None]:
        def handler(route: Route) -> None:
            url = route.request.url
            served = self.serve.get(name)
            if served is not None:
                route.fulfill(status=served.status, headers=served.headers, body=served.body)
                return
            if self.live is not None and name in {"closings", "predictions"}:
                path = self.live / (CLOSINGS if name == "closings" else PREDICTIONS)
                found = path.is_file()
                kept = Kept(
                    url,
                    200 if found else 404,
                    {"content-type": "application/json", "access-control-allow-origin": "*"},
                    path.read_bytes() if found else b"{}",
                )
                self.kept[name] = kept
                route.fulfill(status=kept.status, headers=kept.headers, body=kept.body)
                return
            response = route.fetch()
            self.kept[name] = Kept(url, response.status, dict(response.headers), response.body())
            route.fulfill(response=response)

        return handler

    def watch(self, page: Page) -> None:
        page.route(META, self._keep("meta"))
        page.route(POINTS, self._keep("points"))
        page.route(re.compile(re.escape(CLOSINGS) + r"$"), self._keep("closings"))
        page.route(re.compile(re.escape(PREDICTIONS) + r"$"), self._keep("predictions"))

    def settle(self, page: Page) -> None:
        page.wait_for_function(SETTLED, timeout=TIMEOUT_MS, polling=250)
        page.evaluate(TWO_FRAMES)

    def files(self, page: Page) -> tuple[Directory, Mapping[str, object] | None, str | None]:
        """The directory and closings the national map read, and the live root."""
        page.goto(self.site, wait_until="load", timeout=TIMEOUT_MS)
        self.settle(page)
        meta, points = self.kept.get("meta"), self.kept.get("points")
        if meta is None or points is None or meta.status != 200 or points.status != 200:  # noqa: PLR2004
            raise RenderError("the page did not read the school directory")
        closings = self.kept.get("closings")
        return (
            directory_of(meta.body, points.body),
            _json(closings),
            live_root(closings.url) if closings is not None else None,
        )

    def predictions(self, page: Page, root: str | None) -> Mapping[str, object] | None:
        if root is None:
            return None
        if self.live is not None:
            path = self.live / PREDICTIONS
            body, status = (path.read_bytes(), 200) if path.is_file() else (b"{}", 404)
            headers = {"content-type": "application/json", "access-control-allow-origin": "*"}
        else:
            response = page.request.get(root + PREDICTIONS, timeout=TIMEOUT_MS)
            body, status, headers = response.body(), response.status, dict(response.headers)
        kept = Kept(root + PREDICTIONS, status, headers, body)
        self.kept["predictions"] = kept
        return _json(kept)

    def take(self, page: Page, picture: Picture, out: Path) -> None:
        """Open the picture's view with the described files and check it before the shot."""
        for name in ("closings", "predictions"):
            kept = self.kept.get(name)
            if kept is not None:
                self.serve[name] = kept
        page.goto(self.site + picture.query, wait_until="load", timeout=TIMEOUT_MS)
        self.settle(page)
        if picture.panel is not None:
            page.wait_for_function(
                "(text) => document.body.innerText.includes(text)",
                arg=picture.panel,
                timeout=TIMEOUT_MS,
            )
            self.settle(page)
        state = page.evaluate(STATE)
        if not isinstance(state, dict):
            raise RenderError("the page's state could not be read")
        if state.get("locked") is not False:
            raise RenderError("the waitlist lock still shows")
        if state.get("glow") != picture.lit:
            raise RenderError(
                f"the map lit {state.get('glow')} schools; the description counts {picture.lit}"
            )
        page.screenshot(path=out / FILE, type="png", full_page=False)


def _attempt(  # noqa: PLR0913 - the attempt's parts
    browser: Browser,
    *,
    site: str,
    out: Path,
    now: Callable[[], datetime],
    say: Callable[[str], None],
    live: Path | None,
) -> Taken:
    context = browser.new_context(
        viewport={"width": WIDTH, "height": HEIGHT},
        device_scale_factor=1,
        color_scheme="dark",
        service_workers="block",
        timezone_id=str(SHOWN_ZONE),
        locale="en-US",
    )
    try:
        home = context.request.get(site, timeout=TIMEOUT_MS)
        if home.status != 200:  # noqa: PLR2004
            raise RenderError(f"the site answered HTTP {home.status}")
        value = lock_value(home.text())
        # The value goes into this browser's storage only; it is never printed.
        context.add_init_script(
            script=f"try {{ localStorage.setItem({json.dumps(LOCK_KEY)}, {json.dumps(value)}); }}"
            " catch {}"
        )
        page = context.new_page()
        attempt = Attempt(context, site, say, live=live)
        attempt.watch(page)
        directory, closings, root = attempt.files(page)
        predictions = attempt.predictions(page, root)
        picture = choose(closings=closings, predictions=predictions, directory=directory, now=now())
        say(f"social: the picture is the {picture.kind} view {picture.query or '(national)'}")
        attempt.take(page, picture, out)
    finally:
        context.close()
    return Taken(
        kind=picture.kind,
        query=picture.query,
        shows=picture.shows,
        taken_at=picture.taken_at,
        current=picture.current,
        lit=picture.lit,
        file=FILE,
    )


def render(  # noqa: PLR0913 - the render's parts
    out: Path,
    *,
    site: str = SITE,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    say: Callable[[str], None],
    live: Path | None = None,
    attempts: int = ATTEMPTS,
) -> Taken | None:
    """The fresh picture in ``out``, or ``None`` after ``attempts`` failed attempts.

    ``live`` serves the live files from a local folder instead of the live root (a dry run
    against a local build); the workflow never passes it.
    """
    out.mkdir(parents=True, exist_ok=True)
    for stale in (out / FILE, out / NOTE):
        stale.unlink(missing_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=list(GL_ARGS))
        try:
            for attempt in range(1, attempts + 1):
                try:
                    taken = _attempt(browser, site=site, out=out, now=now, say=say, live=live)
                except (RenderError, PictureError, PlaywrightError) as error:
                    say(f"::warning::social: picture try {attempt} failed: {_short(error)}")
                    (out / FILE).unlink(missing_ok=True)
                    continue
                (out / NOTE).write_text(taken.model_dump_json(indent=2) + "\n", encoding="utf-8")
                say(f"social: the picture shows: {taken.shows}")
                return taken
        finally:
            browser.close()
    return None


def _short(error: Exception) -> str:
    """An error's first line, short (Playwright's messages carry the whole call log)."""
    text = str(error).strip()
    return (text.splitlines()[0] if text else type(error).__name__)[:300]

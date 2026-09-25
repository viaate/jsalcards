/**
 * The map's limits, as someone using it meets them: zooming out stops at the
 * national view, panning keeps the country on screen, the limits follow the
 * window, a link outside them opens at the nearest allowed view, and every
 * school, even one on an island the outline leaves out, can be shown at
 * street zoom.
 *
 * Most checks read the screen: the continental outline and state lines are
 * the only bright pixels below the search bar at these zooms, so their extent
 * in a screenshot is where the country is. Those zooms stay below 7, where the
 * map draws only the bundled lines and asks nothing of the network. The
 * street-zoom checks read the view from the address bar instead.
 *
 * WebGL here runs on SwiftShader (software). Each test sets its own viewports,
 * so they run once, under the desktop project.
 */
import { expect, test } from '@playwright/test';
import type { Browser, BrowserContext, CDPSession, Page } from '@playwright/test';
import sharp from 'sharp';

import { mercatorXFromLng, mercatorYFromLat } from '../src/map/glow/mercator';
import { VIEW_LIMITS } from '../src/state/url';
import { US_BOUNDS } from '../src/map/basemap/us-geo';

interface Viewport {
  name: string;
  width: number;
  height: number;
  deviceScaleFactor: number;
  isMobile: boolean;
}

/** The window from the report: a desktop browser, not maximized. */
const DESKTOP: Viewport = {
  name: 'desktop 1565x957',
  width: 1565,
  height: 957,
  deviceScaleFactor: 1,
  isMobile: false,
};
const PHONE: Viewport = {
  name: 'phone 390x844',
  width: 390,
  height: 844,
  deviceScaleFactor: 3,
  isMobile: true,
};
const VIEWPORTS = [DESKTOP, PHONE];

/** Zoom levels the map may go past the national view, at most (the bar is half a level). */
const MAX_SLACK = 0.5;

/** Chrome's own GPU driver chatter under software WebGL, not the page's. */
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;

/** Width over height of the continental US in Web Mercator. */
const US_ASPECT =
  (mercatorXFromLng(US_BOUNDS[2]) - mercatorXFromLng(US_BOUNDS[0])) /
  (mercatorYFromLat(US_BOUNDS[1]) - mercatorYFromLat(US_BOUNDS[3]));

// Many screenshots and waits for easing, on a software renderer.
test.describe.configure({ timeout: 240_000 });

test.beforeEach(() => {
  test.skip(test.info().project.name !== 'desktop', 'Sets its own viewports; runs once.');
});

async function newContext(browser: Browser, viewport: Viewport): Promise<BrowserContext> {
  return browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: viewport.deviceScaleFactor,
    isMobile: viewport.isMobile,
    hasTouch: viewport.isMobile,
  });
}

/** Console errors and warnings, and page errors. */
function watch(page: Page): string[] {
  const problems: string[] = [];
  page.on('console', (message) => {
    const type = message.type();
    if ((type === 'error' || type === 'warning') && !GPU_DRIVER_NOISE.test(message.text())) {
      problems.push(`console.${type}: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  return problems;
}

async function open(page: Page, path = '/'): Promise<void> {
  await page.goto(path);
  await page.waitForFunction(() => document.querySelector('svg.still') === null, null, {
    timeout: 30_000,
  });
  await settle(page);
}

/** Waits out any easing, inertia and the address bar's write, then two frames. */
async function settle(page: Page, ms = 900): Promise<void> {
  await page.waitForTimeout(ms);
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            resolve();
          });
        });
      }),
  );
}

interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

async function box(page: Page, selector: string): Promise<Box> {
  const found = await page.locator(selector).first().boundingBox();
  if (found === null) throw new Error(`${selector} has no box`);
  return found;
}

/** Where the country's lines are on screen, in CSS pixels, and how many device pixels they light. */
interface Lines extends Box {
  lit: number;
}

/**
 * The extent of the bright pixels below the search bar, leaving out the
 * attribution button: the outline and state lines.
 */
async function lines(page: Page, viewport: Viewport): Promise<Lines> {
  const size = page.viewportSize() ?? viewport;
  const scale = viewport.deviceScaleFactor;
  const bar = await box(page, '.bar');
  const attribution = await box(page, '.maplibregl-ctrl-attrib');
  const { data, info } = await sharp(await page.screenshot())
    .removeAlpha()
    .greyscale()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const top = Math.ceil((bar.y + bar.height + 2) * scale);
  const skip = {
    x0: Math.floor((attribution.x - 4) * scale),
    y0: Math.floor((attribution.y - 4) * scale),
  };
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let lit = 0;
  for (let y = top; y < info.height; y++) {
    for (let x = 0; x < info.width; x++) {
      if (x >= skip.x0 && y >= skip.y0) continue;
      if ((data[y * info.width + x] ?? 0) <= 24) continue;
      lit++;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  if (lit === 0) return { x: size.width / 2, y: size.height / 2, width: 0, height: 0, lit };
  return {
    x: minX / scale,
    y: minY / scale,
    width: (maxX - minX + 1) / scale,
    height: (maxY - minY + 1) / scale,
    lit,
  };
}

/** The width the continental US has at the national view: fitted into the frame. */
async function fittedWidth(page: Page): Promise<number> {
  const frame = await box(page, '.frame');
  return Math.min(frame.width, frame.height * US_ASPECT);
}

/** The whole country is on screen: its lines clear every edge. */
function expectWholeCountry(found: Lines, width: number, height: number, where: string): void {
  expect(found.lit, where).toBeGreaterThan(500);
  expect(found.x, where).toBeGreaterThan(0);
  expect(found.x + found.width, where).toBeLessThan(width);
  expect(found.y + found.height, where).toBeLessThan(height);
}

/** Zoomed all the way out, the country is about as large as at the national view. */
async function expectNationalSize(page: Page, viewport: Viewport, where: string): Promise<Lines> {
  const size = page.viewportSize() ?? viewport;
  const found = await lines(page, viewport);
  const fitted = await fittedWidth(page);
  expectWholeCountry(found, size.width, size.height, where);
  expect(found.width, where).toBeGreaterThanOrEqual(fitted * 2 ** -MAX_SLACK - 2);
  expect(found.width, where).toBeLessThanOrEqual(fitted + 2);
  return found;
}

/** The ?at= view in the address bar, if any. */
function linkView(page: Page): { lat: number; lon: number; zoom: number } | null {
  const at = new URL(page.url()).searchParams.get('at');
  if (at === null) return null;
  const [lat = NaN, lon = NaN, zoom = NaN] = at.split(',').map(Number);
  return { lat, lon, zoom };
}

async function wheelOut(page: Page, times: number): Promise<void> {
  const size = page.viewportSize();
  await page.mouse.move((size?.width ?? 0) / 2, (size?.height ?? 0) / 2);
  for (let i = 0; i < times; i++) {
    await page.mouse.wheel(0, 400);
    await page.waitForTimeout(40);
  }
}

async function keys(page: Page, key: string, times: number): Promise<void> {
  await page.locator('.maplibregl-canvas').focus();
  for (let i = 0; i < times; i++) {
    await page.keyboard.press(key);
    await page.waitForTimeout(120);
  }
}

/**
 * A hard drag: `strokes` strokes across most of the screen in the direction
 * (x, y). Each starts a little aside from the last, as a hand's would, so
 * two strokes never read as a double click (which zooms in).
 */
async function drag(page: Page, x: number, y: number, strokes: number): Promise<void> {
  const size = page.viewportSize();
  const width = size?.width ?? 0;
  const height = size?.height ?? 0;
  for (let i = 0; i < strokes; i++) {
    const aside = (i % 5) * 24 - 48;
    const cx = width / 2 + (y === 0 ? 0 : aside);
    const cy = height / 2 + (x === 0 ? 0 : aside);
    await page.mouse.move(cx - x * width * 0.4, cy - y * height * 0.35);
    await page.mouse.down();
    await page.mouse.move(cx + x * width * 0.4, cy + y * height * 0.35, { steps: 5 });
    await page.mouse.up();
    await page.waitForTimeout(100);
  }
}

/**
 * A drag by (dx, dy) CSS pixels from the middle of the screen that comes to
 * rest before letting go, so the map follows the hand exactly, with no fling.
 */
async function slowDrag(page: Page, dx: number, dy: number): Promise<void> {
  const size = page.viewportSize();
  const cx = (size?.width ?? 0) / 2;
  const cy = (size?.height ?? 0) / 2;
  await page.mouse.move(cx - dx / 2, cy - dy / 2);
  await page.mouse.down();
  await page.mouse.move(cx + dx / 2, cy + dy / 2, { steps: 8 });
  await page.waitForTimeout(300);
  await page.mouse.up();
  await settle(page, 600);
}

/** Two fingers moving together, as a pinch to zoom out. */
async function pinchOut(cdp: CDPSession, cx: number, cy: number): Promise<void> {
  const at = (spread: number): { x: number; y: number }[] => [
    { x: cx - spread, y: cy },
    { x: cx + spread, y: cy },
  ];
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: at(150) });
  for (let spread = 140; spread >= 20; spread -= 10) {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: at(spread) });
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
}

/** Screenshots a few frames apart show the lines in the same place: nothing drifts or shakes. */
async function expectAtRest(page: Page, viewport: Viewport, where: string): Promise<void> {
  const first = await lines(page, viewport);
  for (let i = 0; i < 3; i++) {
    await page.waitForTimeout(150);
    const next = await lines(page, viewport);
    expect(Math.abs(next.x - first.x), where).toBeLessThanOrEqual(1);
    expect(Math.abs(next.y - first.y), where).toBeLessThanOrEqual(1);
    expect(Math.abs(next.width - first.width), where).toBeLessThanOrEqual(1);
  }
}

test.describe('zooming out', () => {
  for (const viewport of VIEWPORTS) {
    test(`stops at the national view: wheel and keys (${viewport.name})`, async ({ browser }) => {
      const context = await newContext(browser, viewport);
      const page = await context.newPage();
      const problems = watch(page);
      await open(page);
      const national = await lines(page, viewport);
      expect(national.width).toBeGreaterThan((await fittedWidth(page)) - 4);

      // The mouse wheel, hard: the country shrinks a little, then stops.
      await wheelOut(page, 30);
      await settle(page);
      const wheeled = await expectNationalSize(page, viewport, 'after the wheel');
      expect(wheeled.width).toBeLessThan(national.width - 4);
      // Most of the frame's width, as at the report's window.
      const frame = await box(page, '.frame');
      expect(wheeled.width / frame.width).toBeGreaterThan(0.7);
      // Pushing further does nothing, and nothing drifts or shakes.
      await wheelOut(page, 10);
      await settle(page, 400);
      await expectAtRest(page, viewport, 'wheel at the widest zoom');
      const pushed = await lines(page, viewport);
      expect(Math.abs(pushed.width - wheeled.width)).toBeLessThanOrEqual(1);

      // Back in with the keyboard, then out hard with it.
      const widestZoom = linkView(page)?.zoom ?? NaN;
      await keys(page, 'Equal', 2);
      await settle(page);
      expect(linkView(page)?.zoom).toBeCloseTo(widestZoom + 2, 1);
      await keys(page, 'Minus', 10);
      await settle(page);
      const keyed = await expectNationalSize(page, viewport, 'after the keys');
      expect(Math.abs(keyed.width - wheeled.width)).toBeLessThanOrEqual(2);

      // The address bar holds the widest view: no lower than the national zoom less half a level.
      const view = linkView(page);
      expect(view).not.toBeNull();
      expect(view?.zoom ?? 0).toBeGreaterThan(VIEW_LIMITS.minZoom);

      expect(problems).toEqual([]);
      await context.close();
    });
  }

  test('stops at the national view: pinch (phone 390x844)', async ({ browser }) => {
    const context = await newContext(browser, PHONE);
    const page = await context.newPage();
    const problems = watch(page);
    await open(page);
    const cdp = await context.newCDPSession(page);
    for (let i = 0; i < 4; i++) {
      await pinchOut(cdp, PHONE.width / 2, PHONE.height / 2);
      await page.waitForTimeout(200);
    }
    await settle(page);
    const pinched = await expectNationalSize(page, PHONE, 'after pinching');
    const frame = await box(page, '.frame');
    expect(pinched.width / frame.width).toBeGreaterThan(0.7);
    await expectAtRest(page, PHONE, 'pinch at the widest zoom');
    expect(problems).toEqual([]);
    await context.close();
  });
});

test.describe('panning', () => {
  /** The four ways to drag, as [name, x, y] unit steps. */
  const DIRECTIONS: [string, number, number][] = [
    ['right', 1, 0],
    ['left', -1, 0],
    ['down', 0, 1],
    ['up', 0, -1],
  ];

  for (const viewport of VIEWPORTS) {
    const { width, height } = viewport;

    test(`at the widest zoom the whole country stays on screen, dragged hard every way (${viewport.name})`, async ({
      browser,
    }) => {
      const context = await newContext(browser, viewport);
      const page = await context.newPage();
      const problems = watch(page);
      await open(page);
      await keys(page, 'Minus', 6);
      await settle(page);
      const widest = await lines(page, viewport);
      for (const [name, x, y] of DIRECTIONS) {
        const where = `widest zoom, dragged ${name}`;
        await drag(page, x, y, 3);
        await settle(page);
        const found = await lines(page, viewport);
        expectWholeCountry(found, width, height, where);
        expect(Math.abs(found.width - widest.width), where).toBeLessThanOrEqual(2);
        // Held at the edge: no drift back once let go.
        await expectAtRest(page, viewport, where);
      }
      expect(problems).toEqual([]);
      await context.close();
    });

    test(`zoomed in, part of the country stays well inside the screen, dragged hard every way (${viewport.name})`, async ({
      browser,
    }) => {
      const context = await newContext(browser, viewport);
      const page = await context.newPage();
      const problems = watch(page);
      await open(page);
      // One level in from the national view, then two, staying below zoom 7,
      // where only the bundled lines are drawn. The drags run on from each
      // other, so they reach the corners too.
      for (const [levels, strokes] of [
        [1, 3],
        [2, 6],
      ] as const) {
        await keys(page, 'Equal', 1);
        await settle(page);
        for (const [name, x, y] of DIRECTIONS) {
          const where = `${String(levels)} level(s) in, dragged ${name}`;
          await drag(page, x, y, strokes);
          await settle(page);
          const found = await lines(page, viewport);
          // A coast or border stays short of the far side: a fifth of the screen or more shows the country.
          expect(found.lit, where).toBeGreaterThan(200);
          if (x !== 0) expect(found.width, where).toBeGreaterThan(width * 0.2);
          if (y !== 0) expect(found.height, where).toBeGreaterThan(height * 0.2);
          if (x > 0) expect(found.x, where).toBeLessThan(width * 0.8);
          if (x < 0) expect(found.x + found.width, where).toBeGreaterThan(width * 0.2);
          if (y > 0) expect(found.y, where).toBeLessThan(height * 0.8);
          if (y < 0) expect(found.y + found.height, where).toBeGreaterThan(height * 0.2);
          if (name === 'right') await expectAtRest(page, viewport, where);
        }
      }
      expect(problems).toEqual([]);
      await context.close();
    });
  }
});

test.describe('the window', () => {
  test('the limits follow every window size, portrait and landscape', async ({ browser }) => {
    const context = await newContext(browser, DESKTOP);
    const page = await context.newPage();
    const problems = watch(page);
    await open(page);
    const sizes: [number, number][] = [
      [320, 568],
      [568, 320],
      [768, 1024],
      [1024, 768],
      [2560, 1440],
      [1440, 2560],
      [1565, 957],
    ];
    for (const [width, height] of sizes) {
      await page.setViewportSize({ width, height });
      await settle(page, 500);
      await keys(page, 'Minus', 6);
      await settle(page);
      await expectNationalSize(
        page,
        { ...DESKTOP, width, height },
        `${String(width)}x${String(height)}`,
      );
    }
    expect(problems).toEqual([]);
    await context.close();
  });

  test('a phone turned sideways and back keeps the country in view', async ({ browser }) => {
    const context = await newContext(browser, PHONE);
    const page = await context.newPage();
    const problems = watch(page);
    await open(page);
    await keys(page, 'Minus', 6);
    await settle(page);
    for (const [width, height] of [
      [844, 390],
      [390, 844],
    ] as const) {
      const turned = { ...PHONE, width, height };
      const where = `turned to ${String(width)}x${String(height)}`;
      await page.setViewportSize({ width, height });
      await settle(page);
      const found = await lines(page, turned);
      expect(found.lit, where).toBeGreaterThan(500);
      expect(found.width, where).toBeGreaterThan((await fittedWidth(page)) * 2 ** -MAX_SLACK - 2);
      await keys(page, 'Minus', 4);
      await settle(page);
      await expectNationalSize(page, turned, `${where}, zoomed out`);
    }
    expect(problems).toEqual([]);
    await context.close();
  });

  test('the national view refits to a new window until someone moves the map', async ({
    browser,
  }) => {
    const context = await newContext(browser, DESKTOP);
    const page = await context.newPage();
    const problems = watch(page);
    await open(page);
    await page.setViewportSize({ width: 1100, height: 800 });
    await settle(page);
    const refitted = await lines(page, DESKTOP);
    expect(Math.abs(refitted.width - (await fittedWidth(page)))).toBeLessThanOrEqual(3);
    expect(new URL(page.url()).search).toBe('');

    // A wheel zoom is a move: the view it chose stays through the next resize.
    await page.mouse.move(550, 450);
    await page.mouse.wheel(0, -200);
    await settle(page);
    const zoomed = linkView(page);
    expect(zoomed).not.toBeNull();
    await page.setViewportSize({ width: 1300, height: 850 });
    await settle(page);
    expect(linkView(page)?.zoom).toBeCloseTo(zoomed?.zoom ?? 0, 1);
    expect(problems).toEqual([]);
    await context.close();
  });
});

test.describe('links', () => {
  test('a link below the widest zoom or off the map opens at the nearest allowed view', async ({
    browser,
  }) => {
    for (const viewport of VIEWPORTS) {
      for (const at of ['0,0,0', '85,170,-3', '24,-150,1.5']) {
        const context = await newContext(browser, viewport);
        const page = await context.newPage();
        const problems = watch(page);
        const where = `${viewport.name}, ?at=${at}`;
        await open(page, `/?at=${at}`);
        const first = await lines(page, viewport);
        await expectNationalSize(page, viewport, where);
        // The address bar now holds the view on screen, inside the limits.
        const view = linkView(page);
        expect(view, where).not.toBeNull();
        if (view !== null) {
          expect(view.lat, where).toBeGreaterThanOrEqual(VIEW_LIMITS.south);
          expect(view.lat, where).toBeLessThanOrEqual(VIEW_LIMITS.north);
          expect(view.lon, where).toBeGreaterThanOrEqual(VIEW_LIMITS.west);
          expect(view.lon, where).toBeLessThanOrEqual(VIEW_LIMITS.east);
        }
        // No jump after load.
        await settle(page, 1200);
        const later = await lines(page, viewport);
        expect(Math.abs(later.x - first.x), where).toBeLessThanOrEqual(1);
        expect(Math.abs(later.y - first.y), where).toBeLessThanOrEqual(1);
        expect(Math.abs(later.width - first.width), where).toBeLessThanOrEqual(1);
        // Reopening that address shows the same view.
        await open(page, page.url());
        const reopened = await lines(page, viewport);
        expect(Math.abs(reopened.x - later.x), where).toBeLessThanOrEqual(2);
        expect(Math.abs(reopened.width - later.width), where).toBeLessThanOrEqual(2);
        expect(problems, where).toEqual([]);
        await context.close();
      }
    }
  });

  test('a link out at sea opens with the country on screen, and a link inside the limits opens as sent', async ({
    browser,
  }) => {
    const context = await newContext(browser, DESKTOP);
    const page = await context.newPage();
    const problems = watch(page);
    // Far out in the Pacific at zoom 5: back to the West Coast.
    await open(page, '/?at=36,-150,5');
    const found = await lines(page, DESKTOP);
    expect(found.lit).toBeGreaterThan(500);
    expect(found.width).toBeGreaterThan(DESKTOP.width * 0.25);
    const view = linkView(page);
    expect(view?.zoom).toBe(5);
    expect(view?.lon ?? 0).toBeGreaterThan(-128);

    // Kansas City at zoom 6, as sent: the address stays exactly as it was.
    await open(page, '/?at=39.04,-94.59,6');
    await settle(page, 800);
    expect(new URL(page.url()).searchParams.get('at')).toBe('39.04,-94.59,6');
    expect((await lines(page, DESKTOP)).lit).toBeGreaterThan(500);
    expect(problems).toEqual([]);
    await context.close();
  });
});

test.describe('schools', () => {
  /** Monhegan School, on its island off Maine: land the outline leaves out. */
  const MONHEGAN = { lat: 43.765918, lon: -69.318376 };

  for (const [viewport, zoom] of [
    [DESKTOP, 16],
    [{ ...PHONE, name: 'phone 320x568', width: 320, height: 568 }, 16],
    [{ ...PHONE, name: 'phone 320x568', width: 320, height: 568 }, 15],
  ] as const) {
    test(`a link to a school on an island opens on it at z${String(zoom)} and pans around it (${viewport.name})`, async ({
      browser,
    }) => {
      const context = await newContext(browser, viewport);
      const page = await context.newPage();
      const problems = watch(page);
      const sent = `${String(MONHEGAN.lat)},${String(MONHEGAN.lon)},${String(zoom)}`;
      await open(page, `/?at=${sent}`);
      await settle(page, 1500);
      // Centered on the school, to the link's precision: no snap away from it.
      const opened = linkView(page);
      expect(opened?.zoom).toBe(zoom);
      expect(Math.abs((opened?.lat ?? 0) - MONHEGAN.lat)).toBeLessThan(1e-5);
      expect(Math.abs((opened?.lon ?? 0) - MONHEGAN.lon)).toBeLessThan(1e-5);

      // A drag moves the map with the hand, in every direction, with the
      // school still on screen, and the drag back brings it to the center again.
      const { width, height } = viewport;
      const scale = 512 * 2 ** zoom;
      /** Where the school is from the center of the screen, in CSS pixels. */
      const offset = (): [number, number] => {
        const view = linkView(page);
        return [
          (mercatorXFromLng(MONHEGAN.lon) - mercatorXFromLng(view?.lon ?? 0)) * scale,
          (mercatorYFromLat(MONHEGAN.lat) - mercatorYFromLat(view?.lat ?? 0)) * scale,
        ];
      };
      for (const [x, y] of [
        [0, 1],
        [0, -1],
        [1, 0],
        [-1, 0],
      ] as const) {
        const where = `dragged ${String(x)},${String(y)}`;
        const reach = Math.min(width, height) * 0.3;
        await slowDrag(page, x * reach, y * reach);
        const [dx, dy] = offset();
        // The school moves with the hand and stays on screen. (Chrome drops
        // part of the first step of a scripted drag, anywhere on the map.)
        expect(x * dx + y * dy, where).toBeGreaterThan(reach * 0.8);
        expect(x * dx + y * dy, where).toBeLessThan(reach + 3);
        expect(Math.abs(y * dx - x * dy), where).toBeLessThan(3);
        await slowDrag(page, -x * reach, -y * reach);
        const [backX, backY] = offset();
        expect(Math.hypot(backX, backY), `${where} and back`).toBeLessThan(3);
      }
      expect(problems).toEqual([]);
      await context.close();
    });
  }
});

test.describe('the other controls', () => {
  test('arrow keys, a shift double-click and a box zoom keep to the limits (desktop 1565x957)', async ({
    browser,
  }) => {
    const { width, height } = DESKTOP;
    const context = await newContext(browser, DESKTOP);
    const page = await context.newPage();
    const problems = watch(page);
    await open(page);
    await keys(page, 'Minus', 6);
    await settle(page);
    const widest = await expectNationalSize(page, DESKTOP, 'the widest zoom');
    const widestZoom = linkView(page)?.zoom ?? NaN;

    // Arrow keys pan 100 px a press: 15 presses run far past every edge.
    for (const key of ['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown']) {
      await keys(page, key, 15);
      await settle(page);
      const found = await lines(page, DESKTOP);
      expectWholeCountry(found, width, height, key);
      expect(Math.abs(found.width - widest.width), key).toBeLessThanOrEqual(2);
    }

    // A double click with Shift zooms out a level: not past the widest zoom.
    await page.keyboard.down('Shift');
    await page.mouse.dblclick(width / 2, height / 2);
    await page.keyboard.up('Shift');
    await settle(page);
    await expectNationalSize(page, DESKTOP, 'after a shift double-click');
    expect(linkView(page)?.zoom).toBeCloseTo(widestZoom, 2);

    // A box drawn out over the Pacific and Canada, in the top-left corner,
    // zooms in about two levels and brings the coast in, not open water.
    await page.keyboard.down('Shift');
    await page.mouse.move(width * 0.02, height * 0.12);
    await page.mouse.down();
    await page.mouse.move(width * 0.22, height * 0.32, { steps: 8 });
    await page.mouse.up();
    await page.keyboard.up('Shift');
    await settle(page, 1200);
    expect(linkView(page)?.zoom ?? 0).toBeGreaterThan(widestZoom + 1.5);
    expect(linkView(page)?.zoom ?? 99).toBeLessThan(7);
    const boxed = await lines(page, DESKTOP);
    expect(boxed.lit).toBeGreaterThan(200);
    expect(boxed.x).toBeLessThan(width * 0.75);
    expect(boxed.x + boxed.width).toBeGreaterThan(width * 0.25);
    expect(boxed.y).toBeLessThan(height * 0.75);
    expect(boxed.y + boxed.height).toBeGreaterThan(height * 0.25);

    expect(problems).toEqual([]);
    await context.close();
  });
});
